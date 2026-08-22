"""RVC engine - the preset-voice workhorse.

Why RVC gives you true "preset voices":
  RVC splits speech into (a) *content* - what is being said, extracted by a
  HuBERT/ContentVec encoder that is deliberately speaker-independent, and
  (b) *identity* - the timbre, which lives entirely in the trained decoder
  plus its FAISS retrieval index. Your voice only ever supplies the content
  and the pitch contour. The decoder always renders that content in the
  target speaker's voice.

  That is why "Nathan" sounds like Nathan whether you, your sister, or your
  friend speaks into the mic. It is not a pitch shift - a pitch shift moves
  your own timbre around, whereas this replaces the timbre outright.

Realism levers, in order of impact:
  1. Correct octave (auto pitch match) - biggest single factor.
  2. f0 method: rmvpe is the accuracy/speed sweet spot; fcpe is faster.
  3. index_rate 0.5-0.75 - too high smears consonants, too low loses timbre.
  4. protect ~0.33 - stops breathy consonants turning into artefacts.
  5. Clean, gated, denoised input.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from ..dsp.pitch import semitones_between
from ..logging_setup import get_logger
from .base import ConversionParams, EngineCaps, EngineError, StreamingContext, VoiceEngine

log = get_logger("rvc")

RVC_SR = 16000  # HuBERT content encoder operates at 16 kHz


def resolve_device(requested: str = "auto") -> str:
    """Pick the best available compute device."""
    try:
        import torch
    except ImportError:
        return "cpu"

    if requested and requested != "auto":
        if requested.startswith("cuda") and not torch.cuda.is_available():
            log.warning("CUDA requested but unavailable; using CPU.")
            return "cpu"
        return requested

    if torch.cuda.is_available():
        return "cuda:0"
    try:  # AMD / Intel GPUs on Windows
        import torch_directml  # noqa: F401
        return "privateuseone:0"
    except ImportError:
        pass
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or len(x) == 0:
        return x.astype(np.float32)
    from scipy.signal import resample_poly
    from math import gcd
    g = gcd(src, dst)
    return resample_poly(x, dst // g, src // g).astype(np.float32)


class RVCEngine(VoiceEngine):
    caps = EngineCaps(
        name="rvc",
        display_name="RVC (preset voices)",
        needs_model=True,
        supports_gpu=True,
        description="Speaker-locked neural conversion. Same target voice for every user.",
    )

    def __init__(self, samplerate: int = 48000, device: str = "auto",
                 half: bool = True, context_ms: float = 1400.0, crossfade_ms: float = 32.0):
        super().__init__(samplerate)
        self.device = resolve_device(device)
        self.half = half and self.device.startswith("cuda")
        self.ctx = StreamingContext(RVC_SR, context_ms, crossfade_ms)
        self._rvc = None                      # backend handle
        self._infer_fn: Optional[Callable] = None
        self._model_path: Optional[Path] = None
        self._index_path: Optional[Path] = None
        self._auto_semis = 0.0
        self._src_f0_hz = 0.0

    # ------------------------------------------------------------- lifecycle
    def set_timing(self, context_ms: float, crossfade_ms: float) -> None:
        self.ctx.set_timing(context_ms, crossfade_ms)

    def load(self, preset) -> None:
        model = Path(getattr(preset, "model_path", "") or "")
        if not model.exists():
            raise EngineError(f"Model file missing for preset '{getattr(preset, 'id', '?')}': {model}")

        if self._loaded_preset == getattr(preset, "id", None) and self._rvc is not None:
            return

        self._model_path = model
        idx = getattr(preset, "index_path", None)
        self._index_path = Path(idx) if idx and Path(idx).exists() else None

        try:
            from rvc_python.infer import RVCInference
        except ImportError as exc:
            raise EngineError(
                "rvc-python is not installed. Install the GPU extras:\n"
                "  pip install -r requirements-gpu.txt"
            ) from exc

        log.info("Loading RVC model %s on %s", model.name, self.device)
        try:
            self._rvc = RVCInference(device=self.device)
            self._rvc.load_model(str(model))
            self._apply_backend_params()
        except Exception as exc:
            self._rvc = None
            raise EngineError(f"Failed to load RVC model: {exc}") from exc

        self._infer_fn = self._resolve_infer_fn()
        self._loaded_preset = getattr(preset, "id", model.stem)
        self.ctx.reset()

    def unload(self) -> None:
        self._rvc = None
        self._infer_fn = None
        super().unload()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def reset(self) -> None:
        self.ctx.reset()

    # ------------------------------------------------------------ parameters
    def set_params(self, params: ConversionParams) -> None:
        super().set_params(params)
        self._apply_backend_params()

    def _apply_backend_params(self) -> None:
        if self._rvc is None:
            return
        p = self.params
        payload = {
            "f0method": p.f0_method,
            "f0up_key": int(round(self._total_semitones())),
            "index_rate": float(p.index_rate),
            "protect": float(p.protect),
            "rms_mix_rate": float(p.rms_mix_rate),
            "filter_radius": 3,
            "resample_sr": 0,
        }
        for setter in ("set_params", "set_parameters"):
            fn = getattr(self._rvc, setter, None)
            if callable(fn):
                try:
                    fn(**payload)
                    return
                except TypeError:
                    try:
                        fn(payload)
                        return
                    except Exception:
                        pass
                except Exception as exc:
                    log.debug("set_params failed: %s", exc)
        # last resort: assign attributes the library reads directly
        for k, v in payload.items():
            if hasattr(self._rvc, k):
                try:
                    setattr(self._rvc, k, v)
                except Exception:
                    pass

    def _total_semitones(self) -> float:
        """Manual shift + automatic octave alignment to the target voice."""
        base = float(self.params.pitch_shift)
        if self.params.auto_pitch and self._auto_semis:
            base += self._auto_semis
        return float(np.clip(base, -24.0, 24.0))

    def update_auto_pitch(self, source_f0_hz: float) -> float:
        """Feed the measured speaker F0; returns the offset now in use.
        Snapped to whole semitones and hysteresis-damped so it does not
        wobble mid-sentence."""
        target = float(self.params.target_f0 or 0.0)
        if not (self.params.auto_pitch and target > 0 and source_f0_hz > 0):
            return self._auto_semis
        self._src_f0_hz = source_f0_hz
        raw = semitones_between(source_f0_hz, target)
        # prefer the nearest octave-consistent whole semitone
        snapped = float(np.clip(round(raw), -24, 24))
        if abs(snapped - self._auto_semis) >= 1.0:
            self._auto_semis = snapped
            self._apply_backend_params()
        return self._auto_semis

    # ------------------------------------------------------------- inference
    def _resolve_infer_fn(self) -> Callable:
        """rvc-python's in-memory API has moved around between releases, so
        probe for an array-in/array-out method and fall back to temp files."""
        for name in ("infer_array", "infer_numpy", "infer_data", "infer_audio"):
            fn = getattr(self._rvc, name, None)
            if callable(fn):
                log.info("RVC backend: using in-memory %s()", name)
                return self._wrap_array_fn(fn)
        log.warning("RVC backend exposes no in-memory inference; using temp-file "
                    "path (slower - expect higher latency).")
        return self._infer_via_tempfile

    def _wrap_array_fn(self, fn: Callable) -> Callable:
        def call(audio16k: np.ndarray) -> np.ndarray:
            out = fn(audio16k, RVC_SR)
            if isinstance(out, tuple):
                data = out[0]
                sr = out[1] if len(out) > 1 and isinstance(out[1], int) else RVC_SR
            else:
                data, sr = out, RVC_SR
            data = np.asarray(data, dtype=np.float32).reshape(-1)
            if np.issubdtype(data.dtype, np.integer):
                data = data.astype(np.float32) / 32768.0
            return _resample(data, sr, RVC_SR)
        return call

    def _infer_via_tempfile(self, audio16k: np.ndarray) -> np.ndarray:
        import soundfile as sf
        tmpdir = tempfile.gettempdir()
        src = os.path.join(tmpdir, "voxmorph_in.wav")
        dst = os.path.join(tmpdir, "voxmorph_out.wav")
        sf.write(src, audio16k, RVC_SR)
        self._rvc.infer_file(src, dst)
        data, sr = sf.read(dst, dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        return _resample(data, sr, RVC_SR)

    def convert(self, block: np.ndarray) -> np.ndarray:
        if self._rvc is None or self._infer_fn is None:
            return block.astype(np.float32)

        n_out = len(block)
        block16 = _resample(block.astype(np.float32), self.samplerate, RVC_SR)
        blk_len = len(block16)

        def _run():
            fed = self.ctx.build_input(block16)
            converted = self._infer_fn(fed)
            seg = self.ctx.extract_output(converted, blk_len)
            return _resample(seg, RVC_SR, self.samplerate)

        try:
            out = self._timed(_run)
        except Exception as exc:
            log.error("RVC inference failed, passing audio through: %s", exc)
            return block.astype(np.float32)

        if len(out) < n_out:
            out = np.concatenate([out, np.zeros(n_out - len(out), dtype=np.float32)])
        return out[:n_out].astype(np.float32)

    # ------------------------------------------------------------ offline
    def convert_file(self, in_path: str, out_path: str) -> None:
        """Batch/offline conversion - full quality, no streaming constraints."""
        if self._rvc is None:
            raise EngineError("No RVC model loaded.")
        self._rvc.infer_file(in_path, out_path)
