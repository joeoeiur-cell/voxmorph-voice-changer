"""Seed-VC engine - zero-shot cloning from a short reference clip.

Complements RVC rather than replacing it:

    RVC      trained per voice, ~10-40 ms inference, highest fidelity.
             Use for your permanent preset voices.
    Seed-VC  no training at all - drop in a 5-15 s reference clip and it
             clones that timbre immediately, at ~300 ms algorithmic latency.
             Use for one-off or user-supplied voices.

Latency is dominated by the diffusion sampler, so `diffusion_steps` is the
main speed/quality dial (4 = fast and usable, 10 = noticeably better, 25 =
offline quality).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

from ..logging_setup import get_logger
from .base import EngineCaps, EngineError, StreamingContext, VoiceEngine
from .rvc_engine import _resample, resolve_device

log = get_logger("seedvc")

SEEDVC_SR = 22050


class SeedVCEngine(VoiceEngine):
    caps = EngineCaps(
        name="seedvc",
        display_name="Seed-VC (zero-shot clone)",
        needs_model=True,
        supports_gpu=True,
        zero_shot=True,
        description="Clone any voice from a 5-15 second reference clip. No training.",
    )

    def __init__(self, samplerate: int = 48000, device: str = "auto",
                 context_ms: float = 2500.0, crossfade_ms: float = 40.0):
        super().__init__(samplerate)
        self.device = resolve_device(device)
        self.ctx = StreamingContext(SEEDVC_SR, context_ms, crossfade_ms)
        self.diffusion_steps = 6
        self.inference_cfg_rate = 0.7
        self._model = None
        self._reference: Optional[np.ndarray] = None
        self._reference_path: Optional[str] = None

    def set_timing(self, context_ms: float, crossfade_ms: float) -> None:
        self.ctx.set_timing(context_ms, crossfade_ms)

    def load(self, preset) -> None:
        ref = getattr(preset, "reference_path", None) or getattr(preset, "model_path", None)
        if not ref or not Path(ref).exists():
            raise EngineError("Seed-VC needs a reference audio clip (5-15 s of clean speech).")

        try:
            import soundfile as sf
        except ImportError as exc:
            raise EngineError("soundfile is required for Seed-VC references.") from exc

        data, sr = sf.read(str(ref), dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        self._reference = _resample(data, sr, SEEDVC_SR)
        self._reference_path = str(ref)

        self._model = self._build_model()
        self._loaded_preset = getattr(preset, "id", Path(ref).stem)
        self.ctx.reset()
        log.info("Seed-VC reference loaded: %s (%.1fs)",
                 Path(ref).name, len(self._reference) / SEEDVC_SR)

    def _build_model(self):
        """seed-vc is distributed as a repo rather than a pip package, so it is
        imported lazily and reported cleanly if absent."""
        try:
            from seed_vc.inference import VoiceConverter  # type: ignore
            return VoiceConverter(device=self.device)
        except Exception:
            pass
        try:
            from seed_vc import SeedVC  # type: ignore
            return SeedVC(device=self.device)
        except Exception as exc:
            raise EngineError(
                "Seed-VC backend not found. Install it with:\n"
                "  pip install git+https://github.com/Plachtaa/seed-vc.git\n"
                f"(import error: {exc})"
            ) from exc

    def unload(self) -> None:
        self._model = None
        self._reference = None
        super().unload()

    def reset(self) -> None:
        self.ctx.reset()

    def convert(self, block: np.ndarray) -> np.ndarray:
        if self._model is None or self._reference is None:
            return block.astype(np.float32)

        n_out = len(block)
        blk = _resample(block.astype(np.float32), self.samplerate, SEEDVC_SR)

        def _run():
            fed = self.ctx.build_input(blk)
            out = self._model.convert(
                source=fed,
                reference=self._reference,
                samplerate=SEEDVC_SR,
                diffusion_steps=self.diffusion_steps,
                inference_cfg_rate=self.inference_cfg_rate,
                pitch_shift=self.params.pitch_shift,
            )
            out = np.asarray(out, dtype=np.float32).reshape(-1)
            seg = self.ctx.extract_output(out, len(blk))
            return _resample(seg, SEEDVC_SR, self.samplerate)

        try:
            res = self._timed(_run)
        except Exception as exc:
            log.error("Seed-VC inference failed: %s", exc)
            return block.astype(np.float32)

        if len(res) < n_out:
            res = np.concatenate([res, np.zeros(n_out - len(res), dtype=np.float32)])
        return res[:n_out].astype(np.float32)
