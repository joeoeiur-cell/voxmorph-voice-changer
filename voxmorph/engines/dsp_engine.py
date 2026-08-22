"""Pure-DSP engine: no model, no GPU, no download, ~2 ms latency.

This is the guaranteed-available fallback. It cannot give you somebody else's
identity (only a neural model can do that), but with independent pitch and
formant control it produces convincing age/size/gender shifts, and it is what
keeps the app usable on a laptop with no CUDA device.
"""
from __future__ import annotations

import numpy as np

from ..dsp.spectral import SpectralProcessor
from .base import EngineCaps, VoiceEngine


class DSPEngine(VoiceEngine):
    caps = EngineCaps(
        name="dsp",
        display_name="DSP (no model)",
        needs_model=False,
        supports_gpu=False,
        description="Instant pitch + formant morphing. Works on any hardware.",
    )

    def __init__(self, samplerate: int = 48000):
        super().__init__(samplerate)
        self.spectral = SpectralProcessor(samplerate, n_fft=1024, hop=256)
        self._pitch = 0.0
        self._formant = 0.0

    def load(self, preset) -> None:
        """DSP presets are just pitch/formant pairs stored in the catalog."""
        p = getattr(preset, "dsp", None) or {}
        self._pitch = float(p.get("pitch", 0.0))
        self._formant = float(p.get("formant", 0.0))
        self.spectral.set_pitch_semitones(self._pitch + self.params.pitch_shift)
        self.spectral.set_formant_semitones(self._formant + self.params.formant_shift)
        self._loaded_preset = getattr(preset, "id", "dsp")

    def set_params(self, params) -> None:
        super().set_params(params)
        self.spectral.set_pitch_semitones(self._pitch + params.pitch_shift)
        self.spectral.set_formant_semitones(self._formant + params.formant_shift)

    def reset(self) -> None:
        self.spectral.reset()

    def convert(self, block: np.ndarray) -> np.ndarray:
        def _run(b):
            out = self.spectral.process(b)
            if len(out) == len(b):
                return out
            if len(out) == 0:
                return np.zeros_like(b)
            return np.concatenate([out, b[len(out):]])[: len(b)]

        return self._timed(_run, block.astype(np.float32))
