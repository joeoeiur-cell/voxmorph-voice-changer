"""Soundboard: hotkey-triggered clips mixed into the outgoing stream.

Clips are mixed *after* the voice model so they play back exactly as recorded
rather than being run through the conversion. Multiple clips can overlap;
each keeps its own playhead.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from .logging_setup import get_logger
from .paths import SOUNDBOARD_DIR, ensure_dirs

log = get_logger("soundboard")

AUDIO_EXTS = (".wav", ".mp3", ".ogg", ".flac", ".m4a")


@dataclass
class Clip:
    id: str
    name: str
    path: Path
    hotkey: str = ""
    volume: float = 1.0
    duration_s: float = 0.0


class _Voice:
    __slots__ = ("data", "pos", "gain")

    def __init__(self, data: np.ndarray, gain: float):
        self.data = data
        self.pos = 0
        self.gain = gain


class Soundboard:
    def __init__(self, samplerate: int = 48000, max_voices: int = 8):
        ensure_dirs()
        self.sr = samplerate
        self.max_voices = max_voices
        self.clips: Dict[str, Clip] = {}
        self._cache: Dict[str, np.ndarray] = {}
        self._voices: List[_Voice] = []
        self._lock = threading.Lock()
        self.master_volume = 0.8
        self.scan()

    # ---------------------------------------------------------------- library
    def scan(self) -> int:
        self.clips.clear()
        for path in sorted(SOUNDBOARD_DIR.iterdir()) if SOUNDBOARD_DIR.exists() else []:
            if path.suffix.lower() not in AUDIO_EXTS:
                continue
            cid = path.stem
            self.clips[cid] = Clip(id=cid, name=path.stem.replace("_", " ").title(), path=path)
        log.info("Soundboard: %d clip(s)", len(self.clips))
        return len(self.clips)

    def add(self, src: Path, hotkey: str = "") -> Optional[Clip]:
        import shutil
        src = Path(src)
        if not src.exists() or src.suffix.lower() not in AUDIO_EXTS:
            return None
        ensure_dirs()
        dest = SOUNDBOARD_DIR / src.name
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        clip = Clip(id=dest.stem, name=dest.stem.replace("_", " ").title(),
                    path=dest, hotkey=hotkey)
        self.clips[clip.id] = clip
        return clip

    def remove(self, clip_id: str) -> None:
        clip = self.clips.pop(clip_id, None)
        self._cache.pop(clip_id, None)
        if clip and clip.path.exists():
            clip.path.unlink(missing_ok=True)

    # --------------------------------------------------------------- playback
    def _load(self, clip: Clip) -> Optional[np.ndarray]:
        if clip.id in self._cache:
            return self._cache[clip.id]
        try:
            import soundfile as sf
            data, sr = sf.read(str(clip.path), dtype="float32")
        except Exception as exc:
            log.error("Cannot load %s: %s", clip.path.name, exc)
            return None
        if data.ndim > 1:
            data = data.mean(axis=1)
        if sr != self.sr:
            from math import gcd
            from scipy.signal import resample_poly
            g = gcd(int(sr), int(self.sr))
            data = resample_poly(data, self.sr // g, sr // g).astype(np.float32)
        data = data.astype(np.float32)
        clip.duration_s = len(data) / self.sr
        self._cache[clip.id] = data
        return data

    def play(self, clip_id: str) -> bool:
        clip = self.clips.get(clip_id)
        if clip is None:
            return False
        data = self._load(clip)
        if data is None:
            return False
        with self._lock:
            if len(self._voices) >= self.max_voices:
                self._voices.pop(0)
            self._voices.append(_Voice(data, clip.volume * self.master_volume))
        return True

    def stop_all(self) -> None:
        with self._lock:
            self._voices.clear()

    def mix(self, n: int) -> Optional[np.ndarray]:
        """Called from the DSP worker. Returns n samples or None if silent."""
        with self._lock:
            if not self._voices:
                return None
            out = np.zeros(n, dtype=np.float32)
            alive: List[_Voice] = []
            for v in self._voices:
                seg = v.data[v.pos:v.pos + n]
                if len(seg):
                    out[: len(seg)] += seg * v.gain
                v.pos += n
                if v.pos < len(v.data):
                    alive.append(v)
            self._voices = alive
        return out

    def attach(self, pipeline) -> None:
        pipeline.soundboard_mix = self.mix

    def hotkey_map(self) -> Dict[str, str]:
        return {c.hotkey: c.id for c in self.clips.values() if c.hotkey}
