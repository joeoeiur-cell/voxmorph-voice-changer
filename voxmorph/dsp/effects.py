"""Creative effects: delay, reverb, chorus, ring-mod and character voicings.
Every processor is streaming-safe (state carries across audio blocks)."""
from __future__ import annotations

import numpy as np

from .filters import Biquad, Cascade, bandpass, highpass, lowpass, peaking
from .kernels import allpass_kernel, comb_kernel


class DelayLine:
    """Fractional-read circular delay line."""

    def __init__(self, sr: int, max_seconds: float = 2.0):
        self.sr = sr
        self.size = int(sr * max_seconds) + 4
        self.buf = np.zeros(self.size, dtype=np.float32)
        self.w = 0

    def write_read(self, x: np.ndarray, delay_samples: np.ndarray | float) -> np.ndarray:
        n = len(x)
        idx = (self.w + np.arange(n)) % self.size
        self.buf[idx] = x
        d = np.asarray(delay_samples, dtype=np.float64)
        if d.ndim == 0:
            d = np.full(n, float(d))
        read = (idx - d) % self.size
        i0 = np.floor(read).astype(np.int64)
        frac = (read - i0).astype(np.float32)
        i1 = (i0 + 1) % self.size
        out = self.buf[i0] * (1.0 - frac) + self.buf[i1] * frac
        self.w = (self.w + n) % self.size
        return out.astype(np.float32)


class Echo:
    def __init__(self, sr: int, time_ms: float = 260.0, feedback: float = 0.35):
        self.line = DelayLine(sr, 2.0)
        self.d = sr * time_ms * 0.001
        self.fb = feedback
        self.tail = np.zeros(0, dtype=np.float32)
        self.damp = lowpass(4200.0, sr)

    def process(self, x: np.ndarray, mix: float) -> np.ndarray:
        if mix <= 0.001:
            return x
        wet = self.line.write_read(x + self._fb_signal(len(x)), self.d)
        self._store(wet)
        return (1.0 - mix * 0.5) * x + mix * self.damp.process(wet)

    def _fb_signal(self, n: int) -> np.ndarray:
        if len(self.tail) < n:
            self.tail = np.concatenate([self.tail, np.zeros(n - len(self.tail), dtype=np.float32)])
        out, self.tail = self.tail[:n] * self.fb, self.tail[n:]
        return out

    def _store(self, wet: np.ndarray) -> None:
        self.tail = np.concatenate([self.tail, wet.astype(np.float32)])[-int(self.d) - 4096:]


class Reverb:
    """Schroeder/Moorer reverb: 4 parallel combs -> 2 series allpasses.
    Cheap enough for realtime, and far more natural than a single delay."""

    _COMBS = (1116, 1188, 1277, 1356)
    _ALLPASS = (556, 441)

    def __init__(self, sr: int, room: float = 0.72):
        scale = sr / 44100.0
        self.comb_d = [int(d * scale) for d in self._COMBS]
        self.ap_d = [int(d * scale) for d in self._ALLPASS]
        self.comb_bufs = [np.zeros(d, dtype=np.float32) for d in self.comb_d]
        self.comb_idx = [0] * len(self.comb_d)
        self.comb_store = [0.0] * len(self.comb_d)
        self.ap_bufs = [np.zeros(d, dtype=np.float32) for d in self.ap_d]
        self.ap_idx = [0] * len(self.ap_d)
        self.room = room
        self.damp = 0.32
        self.tone = lowpass(7500.0, sr)

    def process(self, x: np.ndarray, mix: float) -> np.ndarray:
        if mix <= 0.001:
            return x
        n = len(x)
        xf = x.astype(np.float32)
        acc = np.zeros(n, dtype=np.float32)
        for c in range(len(self.comb_d)):
            out, self.comb_idx[c], self.comb_store[c] = comb_kernel(
                xf, self.comb_bufs[c], self.comb_d[c], self.comb_idx[c],
                float(self.comb_store[c]), float(self.room), float(self.damp),
            )
            acc += out
        acc /= len(self.comb_d)

        for a in range(len(self.ap_d)):
            acc, self.ap_idx[a] = allpass_kernel(
                acc, self.ap_bufs[a], self.ap_d[a], self.ap_idx[a], 0.5
            )

        return (1.0 - mix * 0.6) * x + mix * self.tone.process(acc)


class Chorus:
    """Three-voice modulated delay - thickens a thin converted voice."""

    def __init__(self, sr: int):
        self.sr = sr
        self.line = DelayLine(sr, 0.1)
        self.phase = 0.0
        self.rates = (0.31, 0.47, 0.73)
        self.depths = (0.0022, 0.0031, 0.0018)
        self.base = 0.012

    def process(self, x: np.ndarray, mix: float) -> np.ndarray:
        if mix <= 0.001:
            return x
        n = len(x)
        t = (self.phase + np.arange(n)) / self.sr
        wet = np.zeros(n, dtype=np.float32)
        for rate, depth in zip(self.rates, self.depths):
            mod = (self.base + depth * np.sin(2 * np.pi * rate * t)) * self.sr
            wet += self.line.write_read(x, mod)
        wet /= len(self.rates)
        self.phase += n
        return (1.0 - mix * 0.5) * x + mix * wet


class RingMod:
    def __init__(self, sr: int, freq: float = 42.0):
        self.sr, self.freq, self.phase = sr, freq, 0.0

    def process(self, x: np.ndarray, amount: float) -> np.ndarray:
        if amount <= 0.001:
            return x
        n = len(x)
        t = (self.phase + np.arange(n)) / self.sr
        self.phase += n
        carrier = np.sin(2 * np.pi * self.freq * t).astype(np.float32)
        return (1.0 - amount) * x + amount * (x * carrier)


class Character:
    """Named voice colourations built from EQ + saturation + modulation."""

    NAMES = ("none", "robot", "telephone", "megaphone", "monster", "alien", "cave", "radio")

    def __init__(self, sr: int):
        self.sr = sr
        self.name = "none"
        self._chain = Cascade()
        self._ring = RingMod(sr, 50.0)
        self._reverb = Reverb(sr, 0.85)
        self._echo = Echo(sr, 90.0, 0.45)
        self._build()

    def set(self, name: str) -> None:
        if name == self.name:
            return
        self.name = name if name in self.NAMES else "none"
        self._build()

    def _build(self) -> None:
        sr = self.sr
        n = self.name
        if n == "telephone":
            self._chain = Cascade([highpass(320, sr, 0.9), lowpass(3200, sr, 0.9),
                                   peaking(1600, 6.0, 1.4, sr)])
        elif n == "radio":
            self._chain = Cascade([highpass(420, sr, 1.0), lowpass(4000, sr, 1.0),
                                   peaking(2200, 5.0, 1.6, sr)])
        elif n == "megaphone":
            self._chain = Cascade([highpass(500, sr, 1.1), lowpass(4200, sr, 0.8),
                                   peaking(1900, 9.0, 1.1, sr)])
        elif n == "monster":
            self._chain = Cascade([lowpass(3400, sr, 0.8), peaking(180, 7.0, 0.9, sr),
                                   peaking(2600, -5.0, 1.2, sr)])
        elif n == "alien":
            self._chain = Cascade([bandpass(1500, sr, 0.5), peaking(3000, 5.0, 1.5, sr)])
        elif n == "robot":
            self._chain = Cascade([peaking(900, 4.0, 1.0, sr), lowpass(5200, sr, 0.9)])
        elif n == "cave":
            self._chain = Cascade([lowpass(6000, sr, 0.7), peaking(300, 3.0, 1.0, sr)])
        else:
            self._chain = Cascade()

    @staticmethod
    def _saturate(x: np.ndarray, drive: float) -> np.ndarray:
        return np.tanh(x * drive) / np.tanh(drive)

    def process(self, x: np.ndarray) -> np.ndarray:
        if self.name == "none":
            return x
        y = self._chain.process(x).astype(np.float32)
        if self.name == "robot":
            y = self._ring.process(y, 0.85)
        elif self.name == "megaphone":
            y = self._saturate(y, 3.2)
            y = self._echo.process(y, 0.18)
        elif self.name == "radio":
            y = self._saturate(y, 2.4)
        elif self.name == "monster":
            y = self._saturate(y, 1.8)
        elif self.name == "alien":
            y = self._ring.process(y, 0.45)
        elif self.name == "cave":
            y = self._reverb.process(y, 0.55)
        return y.astype(np.float32)


class AutoTune:
    """Light pitch quantisation toward the equal-tempered grid. Applied as a
    correction hint to the spectral pitch shifter, not as a hard snap."""

    def __init__(self, sr: int):
        self.sr = sr
        self.last_correction = 0.0

    def correction_semitones(self, f0_hz: float, strength: float) -> float:
        if strength <= 0.001 or f0_hz <= 0:
            return 0.0
        midi = 69.0 + 12.0 * np.log2(max(f0_hz, 1e-6) / 440.0)
        target = round(midi)
        delta = float(target - midi)
        smooth = 0.65 * self.last_correction + 0.35 * (delta * strength)
        self.last_correction = smooth
        return smooth
