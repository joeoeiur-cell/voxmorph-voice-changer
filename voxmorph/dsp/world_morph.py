"""High-quality offline voice morphing with the WORLD vocoder.

WHY THIS EXISTS
---------------
The realtime path (dsp/spectral.py) uses a phase vocoder because it is fast
and block-aligned. Phase vocoders are also the source of "phasiness": the
per-bin phase reconstruction smears transients and decorrelates harmonics, so
a shifted voice picks up that hollow, synthetic edge. Comparative evaluations
of pitch-modification methods consistently rank source/filter vocoders
(WORLD, STRAIGHT) above phase vocoding for naturalness, and above TD-PSOLA
for large shifts where pitch-mark errors dominate.

So: realtime uses the fast path, and anything offline (file conversion, the
website demos) uses this one.

WHAT ACTUALLY MAKES A VOICE READ AS MALE OR FEMALE
--------------------------------------------------
Perceptual studies converge on three cues, in order of weight:

  1. F0 - fundamental frequency. Female/male ratio is roughly 1.5-1.6.
  2. Vocal tract length, heard through formant positions. Female formants sit
     about 1.15-1.20x higher; going the other way the scale factor is ~0.87.
  3. Source spectral tilt - how fast energy falls off with frequency. This is
     the cue almost every naive "voice changer" ignores, and it is why they
     sound like a pitch knob rather than a different person.

Two refinements that matter and that uniform scaling gets wrong:

  * Formants do NOT scale uniformly. F1 tracks vocal-tract length more weakly
    than F2/F3, so multiplying the whole spectrum by one constant overshoots
    the first formant and produces the classic "helium" colouration. This
    module warps piecewise, scaling the F1 region less.
  * The warp must be pinned at Nyquist, otherwise upward shifts either throw
    away the top octave or fold it back as aliasing-like brightness.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from ..logging_setup import get_logger

log = get_logger("world")

try:
    import pyworld
    HAVE_WORLD = True
except Exception:  # pragma: no cover - optional dependency
    pyworld = None
    HAVE_WORLD = False


@dataclass
class MorphSpec:
    """A target voice described in perceptual terms rather than DSP terms."""

    name: str = "custom"
    target_f0: float = 0.0       # Hz; 0 = keep the speaker's own pitch
    f0_ratio: float = 1.0        # used only when target_f0 is 0
    formant_ratio: float = 1.0   # >1 shortens the vocal tract (brighter/smaller)
    f1_damping: float = 0.72     # how much less the F1 region scales (0..1)
    tilt_db_oct: float = 0.0     # + brightens the source, - darkens it
    breathiness: float = 1.0     # >1 raises aperiodic (noise) energy
    f0_jitter: float = 0.0       # natural micro-variation, in cents
    description: str = ""


# Presets grounded in the measured ratios above rather than guesswork.
PRESETS = {
    "young_female": MorphSpec(
        name="Young Female", target_f0=208.0, formant_ratio=1.18,
        tilt_db_oct=0.9, breathiness=1.18, f0_jitter=9.0,
        description="Female F0 with a ~15% shorter vocal tract and a breathier source.",
    ),
    "soft_female": MorphSpec(
        name="Soft Female", target_f0=194.0, formant_ratio=1.14,
        tilt_db_oct=1.4, breathiness=1.32, f0_jitter=11.0,
        description="Gentler lift, more aspiration noise, softer glottal source.",
    ),
    "kid": MorphSpec(
        name="Kid", target_f0=262.0, formant_ratio=1.34,
        tilt_db_oct=1.2, breathiness=1.15, f0_jitter=14.0,
        description="Short vocal tract and high F0 - a child's proportions.",
    ),
    "deep_male": MorphSpec(
        name="Deep Male", target_f0=92.0, formant_ratio=0.90,
        tilt_db_oct=-1.1, breathiness=0.92, f0_jitter=6.0,
        description="Lower F0 with a ~10% longer tract and a darker, pressed source.",
    ),
    "giant": MorphSpec(
        name="Giant", target_f0=72.0, formant_ratio=0.78,
        tilt_db_oct=-2.4, breathiness=0.88, f0_jitter=5.0,
        description="Very long vocal tract; heavy low-frequency weight.",
    ),
    "demon": MorphSpec(
        name="Demon", target_f0=62.0, formant_ratio=0.72,
        tilt_db_oct=-3.0, breathiness=1.05, f0_jitter=7.0,
        description="Extreme tract lengthening with a rough, dark source.",
    ),
    "radio_host": MorphSpec(
        name="Radio Host", target_f0=108.0, formant_ratio=0.96,
        tilt_db_oct=-0.4, breathiness=0.90, f0_jitter=5.0,
        description="Slightly lower and fuller, with a controlled, pressed source.",
    ),
    "neutral": MorphSpec(name="Neutral"),
}


# --------------------------------------------------------------------------
# frequency warping
# --------------------------------------------------------------------------
def build_warp(freqs: np.ndarray, ratio: float, nyquist: float,
               f1_damping: float = 0.72, f1_edge: float = 1150.0) -> np.ndarray:
    """Map source frequencies to warped positions.

    Piecewise, not uniform:
      * below `f1_edge` (the F1 region) the scaling is reduced toward 1.0 by
        `f1_damping`, because F1 tracks vocal-tract length only weakly;
      * above it the full `ratio` applies;
      * the curve is then pinned so the top of the band maps exactly to
        Nyquist, which keeps an upward shift from discarding the top octave.
    """
    if abs(ratio - 1.0) < 1e-4:
        return freqs.copy()

    r_low = 1.0 + (ratio - 1.0) * (1.0 - f1_damping)
    warped = np.empty_like(freqs)

    low = freqs <= f1_edge
    warped[low] = freqs[low] * r_low

    # continuous join: carry the F1-region offset into the upper band
    join = f1_edge * r_low
    warped[~low] = join + (freqs[~low] - f1_edge) * ratio

    # pin the top of the band to Nyquist so nothing is lost or folded
    top = warped[-1]
    if top > nyquist:
        knee = nyquist * 0.72
        over = warped > knee
        span = top - knee
        if span > 1e-6:
            warped[over] = knee + (warped[over] - knee) * (nyquist - knee) / span
    return warped


def warp_envelope(sp: np.ndarray, fs: int, ratio: float,
                  f1_damping: float = 0.72) -> np.ndarray:
    """Resample each spectral-envelope frame along the warped frequency axis."""
    if abs(ratio - 1.0) < 1e-4:
        return sp
    n_bins = sp.shape[1]
    nyq = fs / 2.0
    freqs = np.linspace(0.0, nyq, n_bins)
    warped = build_warp(freqs, ratio, nyq, f1_damping)
    out = np.empty_like(sp)
    for i in range(sp.shape[0]):
        out[i] = np.interp(freqs, warped, sp[i])
    return out


def apply_tilt(sp: np.ndarray, fs: int, db_per_oct: float,
               pivot: float = 1000.0) -> np.ndarray:
    """Tilt the source spectrum around a pivot frequency.

    This is the third gender cue and the one most implementations skip.
    """
    if abs(db_per_oct) < 1e-3:
        return sp
    n_bins = sp.shape[1]
    freqs = np.linspace(1.0, fs / 2.0, n_bins)
    gain_db = db_per_oct * np.log2(freqs / pivot)
    return sp * (10.0 ** (gain_db / 10.0))[None, :]   # sp is power, hence /10


def apply_breathiness(ap: np.ndarray, amount: float) -> np.ndarray:
    """Scale aperiodicity - the noise/harmonic balance of the glottal source."""
    if abs(amount - 1.0) < 1e-3:
        return ap
    return np.clip(ap * amount, 1e-6, 1.0 - 1e-6)


def add_jitter(f0: np.ndarray, cents: float, seed: int = 0) -> np.ndarray:
    """Smoothed micro-variation in pitch. Perfectly steady F0 is the single
    biggest giveaway of synthetic speech."""
    if cents <= 0:
        return f0
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(len(f0))
    k = 9
    noise = np.convolve(noise, np.ones(k) / k, mode="same")   # slow drift
    out = f0 * (2.0 ** (noise * cents / 1200.0))
    return np.where(f0 > 0, out, 0.0)


# --------------------------------------------------------------------------
# main entry point
# --------------------------------------------------------------------------
def morph(audio: np.ndarray, fs: int, spec: MorphSpec,
          measured_f0: Optional[float] = None) -> Tuple[np.ndarray, dict]:
    """Analyse, transform and resynthesise. Returns (audio, report)."""
    if not HAVE_WORLD:
        raise RuntimeError("pyworld is required for high-quality morphing: "
                           "pip install pyworld")

    x = np.ascontiguousarray(audio, dtype=np.float64)

    # Harvest is slower than Dio but markedly more accurate on the low end,
    # which is exactly where male targets live.
    f0, t = pyworld.harvest(x, fs, f0_floor=55.0, f0_ceil=1000.0, frame_period=5.0)
    f0 = pyworld.stonemask(x, f0, t, fs)
    sp = pyworld.cheaptrick(x, f0, t, fs)
    ap = pyworld.d4c(x, f0, t, fs)

    voiced = f0[f0 > 0]
    src_f0 = float(np.median(voiced)) if voiced.size else 0.0
    if measured_f0:
        src_f0 = measured_f0

    # --- pitch -----------------------------------------------------------
    if spec.target_f0 > 0 and src_f0 > 0:
        ratio = spec.target_f0 / src_f0
    else:
        ratio = spec.f0_ratio
    ratio = float(np.clip(ratio, 0.25, 4.0))
    new_f0 = f0 * ratio
    new_f0 = add_jitter(new_f0, spec.f0_jitter)

    # --- vocal tract ------------------------------------------------------
    new_sp = warp_envelope(sp, fs, spec.formant_ratio, spec.f1_damping)
    new_sp = apply_tilt(new_sp, fs, spec.tilt_db_oct)
    new_ap = apply_breathiness(ap, spec.breathiness)

    y = pyworld.synthesize(np.ascontiguousarray(new_f0),
                           np.ascontiguousarray(new_sp),
                           np.ascontiguousarray(new_ap), fs, 5.0)

    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    if peak > 0:
        y = y / peak * 0.89

    out_voiced = new_f0[new_f0 > 0]
    report = {
        "source_f0": round(src_f0, 1),
        "target_f0": round(spec.target_f0 or src_f0 * spec.f0_ratio, 1),
        "achieved_f0": round(float(np.median(out_voiced)), 1) if out_voiced.size else 0.0,
        "f0_ratio": round(ratio, 3),
        "semitones": round(12 * np.log2(ratio), 2) if ratio > 0 else 0.0,
        "formant_ratio": spec.formant_ratio,
        "tilt_db_oct": spec.tilt_db_oct,
        "breathiness": spec.breathiness,
    }
    return y.astype(np.float32), report


def morph_preset(audio: np.ndarray, fs: int, preset: str) -> Tuple[np.ndarray, dict]:
    spec = PRESETS.get(preset)
    if spec is None:
        raise KeyError(f"Unknown morph preset '{preset}'. "
                       f"Available: {', '.join(sorted(PRESETS))}")
    return morph(audio, fs, spec)


def envelope_centroid(audio: np.ndarray, fs: int,
                      lo: float = 200.0, hi: float = 5000.0) -> float:
    """Spectral centroid of the *envelope* over the formant band.

    A far more robust proxy for vocal-tract length than peak picking: scaling
    the tract by r moves the whole envelope, so the centroid moves with it.
    """
    if not HAVE_WORLD:
        return 0.0
    x = np.ascontiguousarray(audio, dtype=np.float64)
    f0, t = pyworld.harvest(x, fs, f0_floor=55.0, f0_ceil=1000.0, frame_period=10.0)
    f0 = pyworld.stonemask(x, f0, t, fs)
    sp = pyworld.cheaptrick(x, f0, t, fs)
    voiced = sp[f0 > 0]
    if not len(voiced):
        return 0.0
    env = voiced.mean(axis=0)
    freqs = np.linspace(0, fs / 2, len(env))
    band = (freqs >= lo) & (freqs <= hi)
    w = env[band]
    return float(np.sum(freqs[band] * w) / max(np.sum(w), 1e-12))


def estimate_formants(audio: np.ndarray, fs: int, n: int = 3,
                      lo: float = 220.0, hi: float = 4200.0) -> list[float]:
    """Approximate F1..Fn from the averaged WORLD envelope.

    Restricted to the true formant band and heavily smoothed, because an
    unsmoothed envelope still carries harmonic ripple that a naive peak
    picker happily reports as a formant.
    """
    if not HAVE_WORLD:
        return []
    x = np.ascontiguousarray(audio, dtype=np.float64)
    f0, t = pyworld.harvest(x, fs, f0_floor=55.0, f0_ceil=1000.0, frame_period=10.0)
    f0 = pyworld.stonemask(x, f0, t, fs)
    sp = pyworld.cheaptrick(x, f0, t, fs)
    voiced = sp[f0 > 0]
    if not len(voiced):
        return []

    env = 10.0 * np.log10(np.maximum(voiced.mean(axis=0), 1e-12))
    freqs = np.linspace(0, fs / 2, len(env))

    # cepstral-style smoothing: keep only the slow spectral shape
    k = max(5, int(len(env) * 0.02) | 1)
    kernel = np.hanning(k)
    kernel /= kernel.sum()
    sm = np.convolve(env, kernel, mode="same")

    band = np.flatnonzero((freqs >= lo) & (freqs <= hi))
    peaks = [i for i in band[1:-1]
             if sm[i] > sm[i - 1] and sm[i] >= sm[i + 1]]
    peaks.sort(key=lambda i: -sm[i])          # strongest first
    chosen = sorted(peaks[: n * 2])[:n]       # then back into frequency order
    return [round(float(freqs[i]), 1) for i in chosen]
