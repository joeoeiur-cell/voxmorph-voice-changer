#!/usr/bin/env python3
"""Render the website's demo audio.

The source clip is neural TTS (Piper) so the "before" sounds like an actual
person, and every "after" clip is produced by the *shipping* VoxMorph DSP
chain — the same PreChain/PostChain the realtime app uses. What visitors hear
is genuinely what the software does, not a mock-up.

Run from the repo root:
    python website/build_audio.py

Requires: pip install piper-tts soundfile numpy scipy numba
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

from voxmorph.config import FXConfig            # noqa: E402
from voxmorph.dsp.chain import FXChain          # noqa: E402

OUT = ROOT / "website" / "audio"
MODELS = ROOT / ".cache" / "piper"
VOICE = "en_US-ryan-medium"
BASE_URL = ("https://huggingface.co/rhasspy/piper-voices/resolve/main"
            "/en/en_US/ryan/medium")

PHRASE = ("Hey, this is my voice running through VoxMorph in real time. "
          "Same words, completely different person.")

# name -> (pitch semitones, formant semitones, FXConfig overrides)
PRESETS: dict[str, tuple[float, float, dict]] = {
    "original":     (0.0,   0.0,  {}),
    "deep_male":    (-4.0, -2.5,  {"eq_low_db": 2.5, "eq_high_db": -1.0}),
    "giant":        (-8.0, -6.0,  {"character": "monster", "eq_low_db": 4.0, "reverb": 0.18}),
    "radio_host":   (-1.5, -1.0,  {"eq_low_db": 3.0, "eq_high_db": 2.5,
                                   "comp_threshold_db": -26.0, "comp_ratio": 4.5}),
    "young_female": (4.5,   3.0,  {"eq_high_db": 1.5}),
    "kid":          (7.0,   5.5,  {"eq_high_db": 2.0}),
    "demon":        (-10.0, -7.0, {"character": "monster", "reverb": 0.32, "eq_low_db": 5.0}),
    "robot":        (0.0,   0.0,  {"character": "robot"}),
    "telephone":    (0.0,   0.0,  {"character": "telephone"}),
}


def ensure_voice() -> Path:
    MODELS.mkdir(parents=True, exist_ok=True)
    onnx = MODELS / f"{VOICE}.onnx"
    for name in (f"{VOICE}.onnx", f"{VOICE}.onnx.json"):
        dest = MODELS / name
        if dest.exists() and dest.stat().st_size > 1000:
            continue
        print(f"  downloading {name} ...")
        urllib.request.urlretrieve(f"{BASE_URL}/{name}", dest)
    return onnx


def synth(text: str, model: Path, dest: Path) -> Path:
    proc = subprocess.run(
        [sys.executable, "-m", "piper", "--model", str(model),
         "--output_file", str(dest)],
        input=text.encode(), capture_output=True,
    )
    if proc.returncode != 0 or not dest.exists():
        raise RuntimeError(f"piper failed: {proc.stderr.decode()[:400]}")
    return dest


def convert(audio: np.ndarray, sr: int, pitch: float, formant: float,
            overrides: dict) -> np.ndarray:
    """Stream through the real DSP chain, block by block, as the app would."""
    cfg = FXConfig()
    cfg.denoise = False        # TTS is already clean
    cfg.gate_enabled = False   # no room tone to gate
    for key, value in overrides.items():
        setattr(cfg, key, value)

    chain = FXChain(sr, cfg)
    chain.update(cfg, formant_semis=formant, pitch_semis=pitch)

    block, out = 1024, []
    for i in range(0, len(audio), block):
        seg = audio[i:i + block]
        if len(seg) < block:
            seg = np.concatenate([seg, np.zeros(block - len(seg), dtype=np.float32)])
        out.append(chain.post.process(chain.pre.process(seg)))

    y = np.concatenate(out)[: len(audio) + block]
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
    print("  (ffmpeg unavailable — keeping WAV)")
    return wav


def main() -> int:
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
    print(f"  source: {len(audio) / sr:.2f}s @ {sr} Hz")

    print("Rendering presets through the VoxMorph DSP engine...")
    for name, (pitch, formant, ov) in PRESETS.items():
        if name == "original":
            y = (audio / max(float(np.abs(audio).max()), 1e-9) * 0.89).astype(np.float32)
        else:
            y = convert(audio, sr, pitch, formant, ov)
        wav = OUT / f"{name}.wav"
        sf.write(wav, y, sr, subtype="PCM_16")
        final = to_mp3(wav)
        print(f"  {name:<14} {final.name:<20} {final.stat().st_size // 1024:>4} KB")

    total = sum(f.stat().st_size for f in OUT.iterdir() if f.is_file()) // 1024
    print(f"\nDone — {total} KB in {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
