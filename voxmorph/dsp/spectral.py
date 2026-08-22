"""Streaming STFT engine: spectral denoise, phase-vocoder pitch shift and
formant warping, all in a single overlap-add pass.

Formant warping is what separates a *realistic* voice change from the classic
"chipmunk" effect: pitch and vocal-tract size are decoupled, so we can move
one without dragging the other along.
"""
from __future__ import annotations

import numpy as np

TWO_PI = 2.0 * np.pi


class OverlapAdd:
    """Constant-overlap-add framer. Feed arbitrary block sizes in, get the same
    number of samples out (after an initial n_fft priming latency)."""

    def __init__(self, n_fft: int = 1024, hop: int = 256):
        self.n_fft = n_fft
        self.hop = hop
        w = np.hanning(n_fft + 1)[:-1]
        self.win = np.sqrt(np.maximum(w, 0.0)).astype(np.float32)
        # normalise so analysis*synthesis windows sum to unity at this hop
        denom = np.zeros(n_fft, dtype=np.float64)
        for off in range(0, n_fft, hop):
            denom += np.roll(self.win.astype(np.float64) ** 2, off)
        self.win = (self.win / np.sqrt(np.maximum(denom.mean(), 1e-12))).astype(np.float32)

        self._in = np.zeros(0, dtype=np.float32)
        self._acc = np.zeros(n_fft, dtype=np.float32)
        self._primed = 0

    def reset(self) -> None:
        self._in = np.zeros(0, dtype=np.float32)
        self._acc = np.zeros(self.n_fft, dtype=np.float32)
        self._primed = 0

    def process(self, x: np.ndarray, spec_fn) -> np.ndarray:
        self._in = np.concatenate([self._in, x.astype(np.float32)])
        out = []
        while len(self._in) >= self.n_fft:
            frame = self._in[: self.n_fft] * self.win
            spec = np.fft.rfft(frame)
            spec = spec_fn(spec)
            y = np.fft.irfft(spec, n=self.n_fft).astype(np.float32) * self.win
            self._acc += y
            out.append(self._acc[: self.hop].copy())
            self._acc = np.concatenate([self._acc[self.hop:],
                                        np.zeros(self.hop, dtype=np.float32)])
            self._in = self._in[self.hop:]
        if not out:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(out)

    @property
    def latency_samples(self) -> int:
        return self.n_fft - self.hop


class SpectralProcessor:
    """Denoise + pitch + formant in one STFT pass."""

    def __init__(self, sr: int, n_fft: int = 1024, hop: int = 256):
        self.sr = sr
        self.n_fft = n_fft
        self.hop = hop
        self.ola = OverlapAdd(n_fft, hop)
        self.bins = n_fft // 2 + 1

        self._last_phase = np.zeros(self.bins)
        self._acc_phase = np.zeros(self.bins)
        self._expected = TWO_PI * hop * np.arange(self.bins) / n_fft
        self._noise_floor = np.full(self.bins, 1e-4)
        self._idx = np.arange(self.bins)

        self.pitch_ratio = 1.0      # 1.0 = unchanged
        self.formant_ratio = 1.0    # >1 = larger vocal tract (deeper/bigger)
        self.denoise = 0.0          # 0..1
        self._warm = 0

    # ------------------------------------------------------------------ api
    def set_pitch_semitones(self, semis: float) -> None:
        self.pitch_ratio = float(2.0 ** (semis / 12.0))

    def set_formant_semitones(self, semis: float) -> None:
        self.formant_ratio = float(2.0 ** (semis / 12.0))

    def reset(self) -> None:
        self.ola.reset()
        self._last_phase[:] = 0
        self._acc_phase[:] = 0
        self._warm = 0

    def process(self, x: np.ndarray) -> np.ndarray:
        active = (abs(self.pitch_ratio - 1.0) > 1e-3
                  or abs(self.formant_ratio - 1.0) > 1e-3
                  or self.denoise > 0.01)
        if not active:
            return x
        return self.ola.process(x, self._spec)

    # -------------------------------------------------------------- internal
    def _spec(self, spec: np.ndarray) -> np.ndarray:
        mag = np.abs(spec)
        phase = np.angle(spec)

        if self.denoise > 0.01:
            mag = self._denoise(mag)

        if abs(self.formant_ratio - 1.0) > 1e-3:
            mag = self._warp_formants(mag)

        if abs(self.pitch_ratio - 1.0) > 1e-3:
            return self._pitch_shift(mag, phase)

        self._last_phase = phase
        self._acc_phase = phase
        return mag * np.exp(1j * phase)

    def _denoise(self, mag: np.ndarray) -> np.ndarray:
        """Spectral gating with an adaptive minimum-statistics noise floor."""
        # noise floor tracks downward fast, upward slowly -> follows silence
        nf = self._noise_floor
        down = mag < nf
        nf[down] = 0.90 * nf[down] + 0.10 * mag[down]
        nf[~down] = 0.9995 * nf[~down] + 0.0005 * mag[~down]
        self._noise_floor = np.maximum(nf, 1e-7)

        over = self.denoise * 2.2
        snr = mag / (self._noise_floor * over + 1e-9)
        # Wiener-style soft mask; soft to avoid musical noise artefacts
        mask = (snr ** 2) / (1.0 + snr ** 2)
        mask = np.clip(mask, 1.0 - self.denoise, 1.0)
        return mag * mask

    def _spectral_envelope(self, mag: np.ndarray, quefrency: int = 42) -> np.ndarray:
        """Cepstral-liftered envelope = the vocal tract resonances."""
        log_mag = np.log(np.maximum(mag, 1e-9))
        cep = np.fft.irfft(log_mag, n=self.n_fft)
        cep[quefrency:self.n_fft - quefrency + 1] = 0.0
        env = np.exp(np.fft.rfft(cep, n=self.n_fft).real)
        return np.maximum(env, 1e-9)

    def _warp_formants(self, mag: np.ndarray) -> np.ndarray:
        env = self._spectral_envelope(mag)
        residual = mag / env                     # glottal excitation
        src = self._idx / self.formant_ratio     # stretch/squeeze the envelope
        warped = np.interp(src, self._idx, env, left=env[0], right=env[-1])
        return residual * warped

    def _pitch_shift(self, mag: np.ndarray, phase: np.ndarray) -> np.ndarray:
        """Phase-vocoder frequency-domain pitch shift with true-frequency
        estimation. No time-domain resampling, so it stays block-aligned."""
        dphi = phase - self._last_phase
        self._last_phase = phase
        dev = np.mod(dphi - self._expected + np.pi, TWO_PI) - np.pi
        true_advance = self._expected + dev      # per-hop phase advance

        r = self.pitch_ratio
        src = self._idx / r
        new_mag = np.interp(src, self._idx, mag, left=0.0, right=0.0)
        new_adv = np.interp(src, self._idx, true_advance, left=0.0, right=0.0) * r
        # bins that map outside the spectrum must not leak energy
        new_mag[src > self.bins - 1] = 0.0

        self._acc_phase = np.mod(self._acc_phase + new_adv, TWO_PI)
        return new_mag * np.exp(1j * self._acc_phase)
