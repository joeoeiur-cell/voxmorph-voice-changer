"""Fast fundamental-frequency estimation.

Used for two things:
  1. Auto pitch matching - measure the speaker's median F0 once, compare it to
     the preset voice's target F0, and set the semitone offset automatically.
     This is the single biggest realism win: an RVC model driven at the wrong
     octave sounds robotic no matter how good the checkpoint is.
  2. Autotune correction and the on-screen pitch meter.
"""
from __future__ import annotations

import numpy as np


def yin_f0(x: np.ndarray, sr: int, fmin: float = 60.0, fmax: float = 500.0,
           threshold: float = 0.13) -> float:
    """Single-frame YIN estimator. Returns 0.0 when the frame is unvoiced."""
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    if n < 256:
        return 0.0

    x = x - x.mean()  # DC offset biases the difference function

    tau_min = max(2, int(sr / fmax))
    tau_max = min(n // 2, int(sr / fmin))
    if tau_max <= tau_min:
        return 0.0

    # Integration window: must stay fixed across all lags, otherwise d(tau)
    # picks up an energy ramp and the estimate drifts sharp.
    W = n - tau_max
    if W < tau_min * 2:
        return 0.0

    # d(tau) = sum_j (x[j] - x[j+tau])^2, j in [0, W)
    #        = P[W] + (P[tau+W] - P[tau]) - 2 * r(tau)
    size = 1 << (n + W).bit_length()
    fx = np.fft.rfft(x, size)
    fw = np.fft.rfft(x[:W], size)
    r = np.fft.irfft(fx * np.conj(fw), size)[: tau_max + 1]

    P = np.concatenate([[0.0], np.cumsum(x ** 2)])
    taus = np.arange(tau_max + 1)
    d = P[W] + (P[taus + W] - P[taus]) - 2.0 * r
    d = np.maximum(d, 0.0)

    # cumulative mean normalised difference
    cmnd = np.ones_like(d)
    running = np.cumsum(d[1:])
    nz = running > 0
    cmnd[1:][nz] = d[1:][nz] * np.arange(1, tau_max + 1)[nz] / running[nz]

    window = cmnd[tau_min:tau_max]
    if window.size == 0:
        return 0.0

    below = np.flatnonzero(window < threshold)
    if below.size:
        tau = int(below[0]) + tau_min
        # walk to the local minimum of this dip
        while tau + 1 < tau_max and cmnd[tau + 1] < cmnd[tau]:
            tau += 1
    else:
        tau = int(np.argmin(window)) + tau_min
        if cmnd[tau] > 0.6:
            return 0.0  # clearly unvoiced

    # parabolic interpolation for sub-sample accuracy
    if 0 < tau < tau_max:
        a, b, c = cmnd[tau - 1], cmnd[tau], cmnd[tau + 1]
        denom = 2 * (2 * b - a - c)
        if abs(denom) > 1e-12:
            tau = tau + (c - a) / denom

    f0 = sr / max(tau, 1e-9)
    return float(f0) if fmin <= f0 <= fmax else 0.0


def median_f0(audio: np.ndarray, sr: int, frame_ms: float = 40.0,
              hop_ms: float = 20.0) -> float:
    """Median voiced F0 over a whole clip - robust to unvoiced frames."""
    frame = int(sr * frame_ms * 0.001)
    hop = int(sr * hop_ms * 0.001)
    if len(audio) < frame:
        return 0.0
    vals = []
    for start in range(0, len(audio) - frame, hop):
        f = yin_f0(audio[start:start + frame], sr)
        if f > 0:
            vals.append(f)
    if len(vals) < 3:
        return 0.0
    return float(np.median(vals))


def semitones_between(src_hz: float, dst_hz: float) -> float:
    if src_hz <= 0 or dst_hz <= 0:
        return 0.0
    return float(12.0 * np.log2(dst_hz / src_hz))


class PitchTracker:
    """Rolling F0 tracker fed from the realtime stream. Keeps a short history
    so the auto-pitch-match value is stable rather than jittery."""

    def __init__(self, sr: int, history: int = 60):
        self.sr = sr
        self.history: list[float] = []
        self.max_history = history
        self.current = 0.0

    def push(self, block: np.ndarray) -> float:
        f = yin_f0(block, self.sr)
        if f > 0:
            self.history.append(f)
            if len(self.history) > self.max_history:
                self.history.pop(0)
            self.current = f
        return f

    @property
    def median(self) -> float:
        return float(np.median(self.history)) if len(self.history) >= 5 else 0.0

    def reset(self) -> None:
        self.history.clear()
        self.current = 0.0
