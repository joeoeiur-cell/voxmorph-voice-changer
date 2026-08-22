"""Streaming biquad filters (Direct Form I, state preserved across blocks)."""
from __future__ import annotations

import math

import numpy as np


class Biquad:
    """Single biquad section. State survives between audio blocks, so there are
    no discontinuities at block boundaries."""

    __slots__ = ("b0", "b1", "b2", "a1", "a2", "_x1", "_x2", "_y1", "_y2")

    def __init__(self, b: tuple, a: tuple):
        a0 = a[0]
        self.b0, self.b1, self.b2 = b[0] / a0, b[1] / a0, b[2] / a0
        self.a1, self.a2 = a[1] / a0, a[2] / a0
        self.reset()

    def reset(self) -> None:
        self._x1 = self._x2 = self._y1 = self._y2 = 0.0

    def process(self, x: np.ndarray) -> np.ndarray:
        """Vectorised where possible; the recursive part uses lfilter."""
        from scipy.signal import lfilter

        b = np.array([self.b0, self.b1, self.b2], dtype=np.float64)
        a = np.array([1.0, self.a1, self.a2], dtype=np.float64)
        zi = np.array([
            self.b1 * self._x1 + self.b2 * self._x2 - self.a1 * self._y1 - self.a2 * self._y2,
            self.b2 * self._x1 - self.a2 * self._y1,
        ])
        y, zf = lfilter(b, a, x, zi=zi)
        if len(x):
            self._x2 = x[-2] if len(x) > 1 else self._x1
            self._x1 = x[-1]
            self._y2 = y[-2] if len(y) > 1 else self._y1
            self._y1 = y[-1]
        return y


# --------------------------------------------------------------- designers
def _w0(fc: float, sr: int) -> float:
    return 2.0 * math.pi * max(10.0, min(fc, sr * 0.49)) / sr


def peaking(fc: float, gain_db: float, q: float, sr: int) -> Biquad:
    A = 10 ** (gain_db / 40.0)
    w0 = _w0(fc, sr)
    alpha = math.sin(w0) / (2 * q)
    cw = math.cos(w0)
    b = (1 + alpha * A, -2 * cw, 1 - alpha * A)
    a = (1 + alpha / A, -2 * cw, 1 - alpha / A)
    return Biquad(b, a)


def low_shelf(fc: float, gain_db: float, sr: int, s: float = 0.9) -> Biquad:
    A = 10 ** (gain_db / 40.0)
    w0 = _w0(fc, sr)
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / 2 * math.sqrt((A + 1 / A) * (1 / s - 1) + 2)
    tsa = 2 * math.sqrt(A) * alpha
    b = (A * ((A + 1) - (A - 1) * cw + tsa),
         2 * A * ((A - 1) - (A + 1) * cw),
         A * ((A + 1) - (A - 1) * cw - tsa))
    a = ((A + 1) + (A - 1) * cw + tsa,
         -2 * ((A - 1) + (A + 1) * cw),
         (A + 1) + (A - 1) * cw - tsa)
    return Biquad(b, a)


def high_shelf(fc: float, gain_db: float, sr: int, s: float = 0.9) -> Biquad:
    A = 10 ** (gain_db / 40.0)
    w0 = _w0(fc, sr)
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / 2 * math.sqrt((A + 1 / A) * (1 / s - 1) + 2)
    tsa = 2 * math.sqrt(A) * alpha
    b = (A * ((A + 1) + (A - 1) * cw + tsa),
         -2 * A * ((A - 1) + (A + 1) * cw),
         A * ((A + 1) + (A - 1) * cw - tsa))
    a = ((A + 1) - (A - 1) * cw + tsa,
         2 * ((A - 1) - (A + 1) * cw),
         (A + 1) - (A - 1) * cw - tsa)
    return Biquad(b, a)


def highpass(fc: float, sr: int, q: float = 0.707) -> Biquad:
    w0 = _w0(fc, sr)
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / (2 * q)
    b = ((1 + cw) / 2, -(1 + cw), (1 + cw) / 2)
    a = (1 + alpha, -2 * cw, 1 - alpha)
    return Biquad(b, a)


def lowpass(fc: float, sr: int, q: float = 0.707) -> Biquad:
    w0 = _w0(fc, sr)
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / (2 * q)
    b = ((1 - cw) / 2, 1 - cw, (1 - cw) / 2)
    a = (1 + alpha, -2 * cw, 1 - alpha)
    return Biquad(b, a)


def bandpass(fc: float, sr: int, q: float = 1.0) -> Biquad:
    w0 = _w0(fc, sr)
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / (2 * q)
    b = (alpha, 0.0, -alpha)
    a = (1 + alpha, -2 * cw, 1 - alpha)
    return Biquad(b, a)


class Cascade:
    """Ordered chain of biquads."""

    def __init__(self, stages: list[Biquad] | None = None):
        self.stages = stages or []

    def process(self, x: np.ndarray) -> np.ndarray:
        for s in self.stages:
            x = s.process(x)
        return x

    def reset(self) -> None:
        for s in self.stages:
            s.reset()
