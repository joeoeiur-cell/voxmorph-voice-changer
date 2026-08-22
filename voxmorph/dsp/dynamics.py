"""Dynamics processors: gate, compressor, de-esser, brickwall limiter.
All are sample-accurate and keep envelope state across blocks."""
from __future__ import annotations

import numpy as np

from .filters import Biquad, bandpass, highpass
from .kernels import env_follow, gate_kernel, limiter_kernel


def _coef(ms: float, sr: int) -> float:
    """One-pole smoothing coefficient for a given time constant."""
    ms = max(0.05, ms)
    return float(np.exp(-1.0 / (sr * ms * 0.001)))


def db_to_lin(db: float) -> float:
    return float(10.0 ** (db / 20.0))


class EnvelopeFollower:
    def __init__(self, sr: int, attack_ms: float = 5.0, release_ms: float = 80.0):
        self.sr = sr
        self.set_times(attack_ms, release_ms)
        self.env = 0.0

    def set_times(self, attack_ms: float, release_ms: float) -> None:
        self.ca = _coef(attack_ms, self.sr)
        self.cr = _coef(release_ms, self.sr)

    def process(self, x: np.ndarray) -> np.ndarray:
        rect = np.abs(x).astype(np.float32)
        out, self.env = env_follow(rect, float(self.env), self.ca, self.cr)
        return out


class NoiseGate:
    """Hysteresis gate with hold + smooth release. Kills keyboard/fan noise
    between phrases without chopping word onsets."""

    def __init__(self, sr: int, threshold_db: float = -48.0,
                 attack_ms: float = 2.0, release_ms: float = 140.0, hold_ms: float = 90.0):
        self.sr = sr
        self.follower = EnvelopeFollower(sr, 1.0, 30.0)
        self.threshold_db = threshold_db
        self.ca = _coef(attack_ms, sr)
        self.cr = _coef(release_ms, sr)
        self.hold_samples = int(sr * hold_ms * 0.001)
        self.gain = 0.0
        self.hold = 0
        self.open = False

    def process(self, x: np.ndarray) -> np.ndarray:
        env = self.follower.process(x)
        thr = db_to_lin(self.threshold_db)
        thr_close = thr * 0.5          # 6 dB hysteresis
        out, self.gain, self.hold, self.open = gate_kernel(
            x.astype(np.float32), env.astype(np.float32),
            float(thr), float(thr_close), self.ca, self.cr,
            float(self.gain), int(self.hold), int(self.hold_samples), bool(self.open),
        )
        return out


class Compressor:
    """Soft-knee compressor with auto make-up gain - keeps the converted voice
    at a consistent level so the target timbre stays believable."""

    def __init__(self, sr: int, threshold_db: float = -20.0, ratio: float = 3.0,
                 attack_ms: float = 6.0, release_ms: float = 120.0, knee_db: float = 6.0):
        self.sr = sr
        self.threshold_db = threshold_db
        self.ratio = max(1.0, ratio)
        self.knee = knee_db
        self.follower = EnvelopeFollower(sr, attack_ms, release_ms)

    def process(self, x: np.ndarray) -> np.ndarray:
        env = self.follower.process(x)
        env_db = 20.0 * np.log10(np.maximum(env, 1e-9))
        over = env_db - self.threshold_db
        k = self.knee
        # soft knee
        gain_db = np.zeros_like(over)
        above = over > k / 2
        knee_zone = (over > -k / 2) & (over <= k / 2)
        gain_db[above] = (over[above]) * (1.0 / self.ratio - 1.0)
        if k > 0:
            t = over[knee_zone] + k / 2
            gain_db[knee_zone] = (1.0 / self.ratio - 1.0) * (t ** 2) / (2 * k)
        makeup = -self.threshold_db * (1.0 / self.ratio - 1.0) * 0.6
        return x * (10.0 ** ((gain_db + makeup) / 20.0))


class DeEsser:
    """Split-band de-esser. Sibilance is the #1 giveaway of AI voice
    conversion, so this runs after the model, not before."""

    def __init__(self, sr: int, freq: float = 6500.0, threshold_db: float = -30.0,
                 ratio: float = 4.0):
        self.detect: Biquad = bandpass(freq, sr, q=1.2)
        self.split: Biquad = highpass(freq, sr, q=0.707)
        self.comp = Compressor(sr, threshold_db, ratio, attack_ms=1.0, release_ms=45.0, knee_db=3.0)

    def process(self, x: np.ndarray) -> np.ndarray:
        sib = self.split.process(x)
        low = x - sib
        return low + self.comp.process(sib)


class Limiter:
    """Look-ahead brickwall limiter. Guarantees the virtual cable never clips,
    which otherwise sounds like digital crackle to listeners."""

    def __init__(self, sr: int, ceiling_db: float = -1.0, lookahead_ms: float = 3.0,
                 release_ms: float = 60.0):
        self.ceiling = db_to_lin(ceiling_db)
        self.la = max(1, int(sr * lookahead_ms * 0.001))
        self.delay = np.zeros(self.la, dtype=np.float32)
        self.cr = _coef(release_ms, sr)
        self.gain = 1.0

    def process(self, x: np.ndarray) -> np.ndarray:
        buf = np.concatenate([self.delay, x.astype(np.float32)])
        self.delay = buf[len(buf) - self.la:].copy()
        delayed = buf[: len(x)]

        peak = np.abs(x)
        # sliding max over the look-ahead window
        if self.la > 1:
            pad = np.concatenate([peak, np.zeros(self.la, dtype=peak.dtype)])
            win = np.lib.stride_tricks.sliding_window_view(pad, self.la)[: len(x)]
            peak = win.max(axis=1)

        target = np.where(peak > self.ceiling,
                          self.ceiling / np.maximum(peak, 1e-9), 1.0).astype(np.float32)
        out, self.gain = limiter_kernel(
            delayed.astype(np.float32), target, float(self.gain), self.cr
        )
        return out
