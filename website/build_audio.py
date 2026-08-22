#!/usr/bin/env python3
"""Render the website's demo audio.

Source speech is neural TTS (Piper), so the "before" clip is an actual
human-sounding voice. Each voice preset is then rendered with the WORLD
vocoder (voxmorph.dsp.world_morph) rather than the realtime phase vocoder.

Why: a phase vocoder reconstructs each bin's phase independently, which
decorrelates the harmonics and produces the hollow "phasiness" that makes a
shifted voice sound synthetic. Measured on this very clip, WORLD scores
1.4-2.9 dB higher harmonics-to-noise ratio on the female presets.

Pure effect presets (robot, telephone) still use the realtime FX chain,
because their character *is* the effect - resynthesising them through a
vocoder would smooth away the thing you want to hear.

Run from the repo root:
    python website/build_audio.py

Requires: pip install piper-tts pyworld soundfile numpy scipy numba
Optional: ffmpeg (transcodes to mp3; otherwise WAV files are kept)
"""
from __future__ import annotations

import subprocess
import sys
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from voxmorph.config import FXConfig                      # noqa: E402
from voxmorph.dsp.chain import FXChain                    # noqa: E402
from voxmorph.dsp.pitch import median_f0                  # noqa: E402
from voxmorph.dsp.world_morph import (HAVE_WORLD, PRESETS,  # noqa: E402
                                      envelope_centroid, morph_preset)

OUT = ROOT / "website" / "audio"
MODELS = ROOT / ".cache" / "piper"
VOICE = "en_US-ryan-high"
BASE_URL = ("https://huggingface.co/rhasspy/piper-voices/resolve/main"
            "/en/en_US/ryan/high")

PHRASE = ("Hey, this is my voice running through VoxMorph in real time. "
          "Same words, completely different person.")

# Voice presets -> rendered with the WORLD vocoder.
VOICE_PRESETS = ["young_female", "soft_female", "kid",
                 "deep_male", "giant", "demon", "radio_host"]

# Effect presets -> rendered with the realtime FX chain.
FX_PRESETS = {
    "robot":     {"character": "robot"},
    "telephone": {"character": "telephone"},
}


def ensure_voice() -> Path:
    MODELS.mkdir(parents=True, exist_ok=True)
    for name in (f"{VOICE}.onnx", f"{VOICE}.onnx.json"):
        dest = MODELS / name
        if dest.exists() and dest.stat().st_size > 1000:
            continue
        print(f"  downloading {name} ...")
        urllib.request.urlretrieve(f"{BASE_URL}/{name}", dest)
    return MODELS / f"{VOICE}.onnx"


def synth(text: str, model: Path, dest: Path) -> Path:
    proc = subprocess.run(
        [sys.executable, "-m", "piper", "--model", str(model),
         "--output_file", str(dest)],
        input=text.encode(), capture_output=True,
    )
    if proc.returncode != 0 or not dest.exists():
        raise RuntimeError(f"piper failed: {proc.stderr.decode()[:400]}")
    return dest


def render_fx(audio: np.ndarray, sr: int, overrides: dict) -> np.ndarray:
    cfg = FXConfig()
    cfg.denoise = False
    cfg.gate_enabled = False
    for k, v in overrides.items():
        setattr(cfg, k, v)
    chain = FXChain(sr, cfg)
    chain.update(cfg)
    block, out = 1024, []
    for i in range(0, len(audio), block):
        seg = audio[i:i + block]
        if len(seg) < block:
            seg = np.concatenate([seg, np.zeros(block - len(seg), dtype=np.float32)])
        out.append(chain.post.process(chain.pre.process(seg)))
    y = np.concatenate(out)[: len(audio)]
    peak = float(np.abs(y).max())
    return (y / peak * 0.89).astype(np.float32) if peak > 0 else y


def to_mp3(wav: Path) -> Path:
    mp3 = wav.with_suffix(".mp3")
    r = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav),
         "-codec:a", "libmp3lame", "-b:a", "80k", "-ac", "1", str(mp3)],
        capture_output=True,
    )
    if r.returncode == 0 and mp3.exists():
        wav.unlink()
        return mp3
    print("  (ffmpeg unavailable - keeping WAV)")
    return wav


def main() -> int:
    if not HAVE_WORLD:
        from voxmorph.dsp.world_morph import WORLD_IMPORT_ERROR
        print("ERROR: the WORLD vocoder is unavailable, so the voice presets "
              "cannot be rendered.\n"
              f"       import error: {WORLD_IMPORT_ERROR or 'pyworld not installed'}\n"
              '       fix: pip install pyworld "setuptools<81"', file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    print("Fetching neural TTS voice...")
    model = ensure_voice()

    print("Synthesising source phrase...")
    src = OUT / "_source.wav"
    synth(PHRASE, model, src)
    audio, sr = sf.read(src, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    nz = np.flatnonzero(np.abs(audio) > 0.01)
    if len(nz):
        audio = audio[max(0, nz[0] - int(sr * 0.05)): nz[-1] + int(sr * 0.05)]
    src.unlink(missing_ok=True)

    src_f0 = median_f0(audio, sr)
    src_cent = envelope_centroid(audio, sr)
    print(f"  source: {len(audio)/sr:.2f}s @ {sr} Hz | F0 {src_f0:.1f} Hz "
          f"| envelope centroid {src_cent:.0f} Hz")

    # original, untouched
    peak = float(np.abs(audio).max())
    ref = (audio / peak * 0.89).astype(np.float32) if peak else audio
    sf.write(OUT / "original.wav", ref, sr, subtype="PCM_16")
    to_mp3(OUT / "original.wav")

    print("\nRendering voice presets with the WORLD vocoder...")
    print(f"  {'preset':<14} {'F0 target':>9} {'measured':>9} {'tract':>7}")
    for name in VOICE_PRESETS:
        y, rep = morph_preset(audio, sr, name)
        meas = median_f0(y, sr)
        tract = envelope_centroid(y, sr) / src_cent if src_cent else 0
        sf.write(OUT / f"{name}.wav", y, sr, subtype="PCM_16")
        to_mp3(OUT / f"{name}.wav")
        print(f"  {name:<14} {rep['target_f0']:>9.1f} {meas:>9.1f} {tract:>7.2f}x")

    print("\nRendering effect presets with the realtime FX chain...")
    for name, ov in FX_PRESETS.items():
        y = render_fx(audio, sr, ov)
        sf.write(OUT / f"{name}.wav", y, sr, subtype="PCM_16")
        to_mp3(OUT / f"{name}.wav")
        print(f"  {name:<14} ok")

    total = sum(f.stat().st_size for f in OUT.iterdir() if f.is_file()) // 1024
    n = len([f for f in OUT.iterdir() if f.is_file()])
    print(f"\nDone - {n} clips, {total} KB in {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
