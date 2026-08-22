"""Dual-track recorder: captures the raw mic and the converted output to
separate WAV files so you can A/B them or re-render offline at full quality."""
from __future__ import annotations

import queue
import threading
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

from ..logging_setup import get_logger
from ..paths import RECORDINGS_DIR, ensure_dirs

log = get_logger("recorder")


class Recorder:
    """Writes on a background thread so disk I/O never stalls the DSP worker."""

    def __init__(self, samplerate: int = 48000, capture_dry: bool = True):
        ensure_dirs()
        self.sr = samplerate
        self.capture_dry = capture_dry
        self._q: queue.Queue = queue.Queue(maxsize=256)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._wet: Optional[wave.Wave_write] = None
        self._dry: Optional[wave.Wave_write] = None
        self.wet_path: Optional[Path] = None
        self.dry_path: Optional[Path] = None
        self.frames = 0

    @property
    def recording(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, name: Optional[str] = None) -> Path:
        if self.recording:
            return self.wet_path  # type: ignore[return-value]
        ensure_dirs()
        stamp = name or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.wet_path = RECORDINGS_DIR / f"{stamp}_converted.wav"
        self._wet = self._open(self.wet_path)
        if self.capture_dry:
            self.dry_path = RECORDINGS_DIR / f"{stamp}_original.wav"
            self._dry = self._open(self.dry_path)
        self.frames = 0
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="voxmorph-rec", daemon=True)
        self._thread.start()
        log.info("Recording -> %s", self.wet_path.name)
        return self.wet_path

    def _open(self, path: Path) -> wave.Wave_write:
        w = wave.open(str(path), "wb")
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(self.sr)
        return w

    def feed(self, dry: np.ndarray, wet: np.ndarray) -> None:
        if not self.recording:
            return
        try:
            self._q.put_nowait((dry.copy(), wet.copy()))
        except queue.Full:
            log.warning("Recorder queue full; dropping a block.")

    def _run(self) -> None:
        while not self._stop.is_set() or not self._q.empty():
            try:
                dry, wet = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            if self._wet:
                self._wet.writeframes(self._pcm(wet))
            if self._dry:
                self._dry.writeframes(self._pcm(dry))
            self.frames += len(wet)

    @staticmethod
    def _pcm(x: np.ndarray) -> bytes:
        return (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()

    def stop(self) -> Optional[Path]:
        if not self.recording:
            return None
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        self._thread = None
        for w in (self._wet, self._dry):
            if w:
                try:
                    w.close()
                except Exception:
                    pass
        self._wet = self._dry = None
        log.info("Recording stopped (%.1f s)", self.frames / self.sr)
        return self.wet_path

    @property
    def duration_s(self) -> float:
        return self.frames / self.sr if self.sr else 0.0

    def attach(self, pipeline) -> None:
        pipeline.recorder = self

    def detach(self, pipeline) -> None:
        if pipeline.recorder is self:
            pipeline.recorder = None
