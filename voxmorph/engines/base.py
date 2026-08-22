"""Engine interface + the streaming machinery every neural engine shares.

The hard part of realtime voice conversion is not the model, it is the
*windowing*. Neural VC models need surrounding context to produce a stable
timbre, but a realtime app can only ever give them audio from the past. The
standard solution (used by w-okada/voice-changer and seed-vc's realtime GUI,
and reimplemented here) is:

    [ ---- left context ---- | block | right pad ]
                              ^^^^^^^ the only part we actually emit

Each pass re-infers the context too, which is wasteful but keeps the model's
internal state consistent. Consecutive outputs are then equal-power
crossfaded so there is no click at the seam.
"""
from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from ..logging_setup import get_logger

log = get_logger("engine")


@dataclass
class EngineCaps:
    name: str
    display_name: str
    needs_model: bool = True
    supports_gpu: bool = True
    zero_shot: bool = False
    description: str = ""


@dataclass
class ConversionParams:
    pitch_shift: float = 0.0
    formant_shift: float = 0.0
    index_rate: float = 0.6
    protect: float = 0.33
    rms_mix_rate: float = 0.25
    f0_method: str = "rmvpe"
    target_f0: float = 0.0        # preset's natural F0, for auto pitch match
    auto_pitch: bool = True
    extra: dict = field(default_factory=dict)


class VoiceEngine(abc.ABC):
    """Base class for all conversion backends."""

    caps: EngineCaps

    def __init__(self, samplerate: int = 48000):
        self.samplerate = samplerate
        self.params = ConversionParams()
        self._loaded_preset: Optional[str] = None
        self.last_infer_ms: float = 0.0

    # ------------------------------------------------------------- lifecycle
    @abc.abstractmethod
    def load(self, preset) -> None:
        """Load a preset voice. Must be idempotent."""

    def unload(self) -> None:
        self._loaded_preset = None

    def warmup(self) -> None:
        """Run a dummy inference so the first real block is not slow."""
        try:
            self.convert(np.zeros(int(self.samplerate * 0.1), dtype=np.float32))
        except Exception as exc:
            log.debug("Warmup skipped: %s", exc)

    @property
    def loaded_preset(self) -> Optional[str]:
        return self._loaded_preset

    @property
    def ready(self) -> bool:
        return not self.caps.needs_model or self._loaded_preset is not None

    def set_params(self, params: ConversionParams) -> None:
        self.params = params

    # ------------------------------------------------------------ processing
    @abc.abstractmethod
    def convert(self, block: np.ndarray) -> np.ndarray:
        """Convert one block of mono float32 audio at self.samplerate."""

    def reset(self) -> None:
        """Clear streaming state (called on start/stop and preset change)."""

    # ------------------------------------------------------------- utilities
    def _timed(self, fn, *a, **kw):
        t0 = time.perf_counter()
        out = fn(*a, **kw)
        self.last_infer_ms = (time.perf_counter() - t0) * 1000.0
        return out


class StreamingContext:
    """Left-context ring buffer + equal-power crossfade for chunked neural
    inference. Engine-agnostic, so RVC and seed-vc share it."""

    def __init__(self, samplerate: int, context_ms: float, crossfade_ms: float):
        self.sr = samplerate
        self.set_timing(context_ms, crossfade_ms)
        self.buffer = np.zeros(0, dtype=np.float32)
        self.prev_tail = np.zeros(0, dtype=np.float32)

    def set_timing(self, context_ms: float, crossfade_ms: float) -> None:
        self.context = int(self.sr * context_ms * 0.001)
        self.xfade = max(16, int(self.sr * crossfade_ms * 0.001))
        # equal-power (constant-energy) crossfade curves
        t = np.linspace(0.0, 1.0, self.xfade, dtype=np.float32)
        self.fade_in = np.sin(t * np.pi / 2.0).astype(np.float32)
        self.fade_out = np.cos(t * np.pi / 2.0).astype(np.float32)
        self.reset()

    def reset(self) -> None:
        self.buffer = np.zeros(0, dtype=np.float32)
        self.prev_tail = np.zeros(0, dtype=np.float32)

    def build_input(self, block: np.ndarray) -> np.ndarray:
        """Append the new block and return [context + block] for inference."""
        self.buffer = np.concatenate([self.buffer, block.astype(np.float32)])
        keep = self.context + len(block) + self.xfade
        if len(self.buffer) > keep:
            self.buffer = self.buffer[-keep:]
        return self.buffer

    def extract_output(self, converted: np.ndarray, block_len: int) -> np.ndarray:
        """Take the newest block_len samples plus a crossfade region, and blend
        it against the previous pass so the seam is inaudible."""
        need = block_len + self.xfade
        if len(converted) < need:
            converted = np.concatenate(
                [np.zeros(need - len(converted), dtype=np.float32), converted]
            )
        seg = converted[-need:].astype(np.float32)

        head, tail = seg[: self.xfade], seg[self.xfade:]
        if len(self.prev_tail) == self.xfade:
            blended = self.prev_tail * self.fade_out + head * self.fade_in
        else:
            blended = head
        out = np.concatenate([blended, tail[: block_len - self.xfade]])

        self.prev_tail = seg[block_len:block_len + self.xfade].copy()
        if len(self.prev_tail) != self.xfade:
            self.prev_tail = np.zeros(self.xfade, dtype=np.float32)

        if len(out) < block_len:
            out = np.concatenate([out, np.zeros(block_len - len(out), dtype=np.float32)])
        return out[:block_len].astype(np.float32)


class EngineError(RuntimeError):
    """Raised when a backend cannot be initialised; the app degrades to DSP."""
