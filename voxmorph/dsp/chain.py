"""The post-conversion effects rack.

Signal order matters and is deliberate:

    input -> HPF -> denoise -> gate -> [VOICE MODEL] -> formant/pitch
          -> character -> EQ -> compressor -> de-esser
          -> chorus -> echo -> reverb -> limiter -> output

Cleanup happens *before* the model (garbage in, garbage out), while tone
shaping and dynamics happen *after* it, because the model output has its own
spectral balance that we want the final say over.
"""
from __future__ import annotations

import numpy as np

from ..config import FXConfig
from .dynamics import Compressor, DeEsser, Limiter, NoiseGate
from .effects import AutoTune, Character, Chorus, Echo, Reverb
from .filters import Cascade, high_shelf, highpass, low_shelf, peaking
from .spectral import SpectralProcessor


class PreChain:
    """Runs before the voice model: rumble removal, denoise, gating."""

    def __init__(self, sr: int, cfg: FXConfig):
        self.sr = sr
        self.hpf = highpass(75.0, sr, 0.707)
        self.gate = NoiseGate(sr, cfg.gate_threshold_db)
        self.spectral = SpectralProcessor(sr, n_fft=1024, hop=256)
        self.cfg = cfg

    def update(self, cfg: FXConfig) -> None:
        self.cfg = cfg
        self.gate.threshold_db = cfg.gate_threshold_db
        self.spectral.denoise = cfg.denoise_strength if cfg.denoise else 0.0

    def process(self, x: np.ndarray) -> np.ndarray:
        y = self.hpf.process(x).astype(np.float32)
        if self.cfg.denoise:
            self.spectral.denoise = self.cfg.denoise_strength
            out = self.spectral.process(y)
            # spectral stage has priming latency; pass through until it fills
            if len(out) == len(y):
                y = out
            elif len(out) > 0:
                y = np.concatenate([out, y[len(out):]])[: len(y)]
        if self.cfg.gate_enabled:
            y = self.gate.process(y)
        return y.astype(np.float32)


class PostChain:
    """Runs after the voice model: pitch/formant trim, character, dynamics, FX."""

    def __init__(self, sr: int, cfg: FXConfig):
        self.sr = sr
        self.cfg = cfg
        self.spectral = SpectralProcessor(sr, n_fft=1024, hop=256)
        self.character = Character(sr)
        self.eq = Cascade()
        self.comp = Compressor(sr, cfg.comp_threshold_db, cfg.comp_ratio)
        self.deesser = DeEsser(sr)
        self.chorus = Chorus(sr)
        self.echo = Echo(sr)
        self.reverb = Reverb(sr)
        self.limiter = Limiter(sr, ceiling_db=-1.0)
        self.autotune = AutoTune(sr)
        self._eq_key = None
        self.update(cfg)

    # ------------------------------------------------------------------ api
    def update(self, cfg: FXConfig, formant_semis: float = 0.0,
               pitch_semis: float = 0.0) -> None:
        self.cfg = cfg
        self.character.set(cfg.character)
        self.comp.threshold_db = cfg.comp_threshold_db
        self.comp.ratio = max(1.0, cfg.comp_ratio)
        self.spectral.set_formant_semitones(formant_semis)
        self.spectral.set_pitch_semitones(pitch_semis)

        key = (cfg.eq_low_db, cfg.eq_mid_db, cfg.eq_high_db)
        if key != self._eq_key:
            self._eq_key = key
            stages = []
            if abs(cfg.eq_low_db) > 0.05:
                stages.append(low_shelf(220.0, cfg.eq_low_db, self.sr))
            if abs(cfg.eq_mid_db) > 0.05:
                stages.append(peaking(1400.0, cfg.eq_mid_db, 0.9, self.sr))
            if abs(cfg.eq_high_db) > 0.05:
                stages.append(high_shelf(6200.0, cfg.eq_high_db, self.sr))
            self.eq = Cascade(stages)

    def process(self, x: np.ndarray) -> np.ndarray:
        cfg = self.cfg
        if not cfg.enabled:
            return self.limiter.process(x)

        y = x.astype(np.float32)

        out = self.spectral.process(y)
        if len(out) == len(y):
            y = out
        elif len(out) > 0:
            y = np.concatenate([out, y[len(out):]])[: len(y)]

        y = self.character.process(y)
        y = self.eq.process(y).astype(np.float32)

        if cfg.compressor:
            y = self.comp.process(y).astype(np.float32)
        if cfg.deesser:
            y = self.deesser.process(y).astype(np.float32)
        if cfg.chorus > 0.001:
            y = self.chorus.process(y, cfg.chorus)
        if cfg.echo > 0.001:
            y = self.echo.process(y, cfg.echo)
        if cfg.reverb > 0.001:
            y = self.reverb.process(y, cfg.reverb)
        if cfg.limiter:
            y = self.limiter.process(y)
        return np.clip(y, -1.0, 1.0).astype(np.float32)


class FXChain:
    """Convenience wrapper holding both halves of the rack."""

    def __init__(self, sr: int, cfg: FXConfig):
        self.pre = PreChain(sr, cfg)
        self.post = PostChain(sr, cfg)

    def update(self, cfg: FXConfig, formant_semis: float = 0.0,
               pitch_semis: float = 0.0) -> None:
        self.pre.update(cfg)
        self.post.update(cfg, formant_semis, pitch_semis)

    def reset(self) -> None:
        self.pre.spectral.reset()
        self.post.spectral.reset()
