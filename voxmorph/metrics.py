"""Live performance telemetry for the latency HUD.

Realtime audio has one hard rule: the time to process a block must stay below
the block's own duration. The ratio of the two is the *realtime factor*; once
it approaches 1.0 you get dropouts. Surfacing this lets the user pick a
latency profile their hardware can actually sustain instead of guessing.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque


@dataclass
class Snapshot:
    input_rms_db: float = -90.0
    output_rms_db: float = -90.0
    input_peak_db: float = -90.0
    output_peak_db: float = -90.0
    process_ms: float = 0.0
    process_p95_ms: float = 0.0
    infer_ms: float = 0.0
    block_ms: float = 0.0
    realtime_factor: float = 0.0
    total_latency_ms: float = 0.0
    dropouts: int = 0
    blocks: int = 0
    f0_hz: float = 0.0
    pitch_offset: float = 0.0
    engine: str = ""
    device: str = ""
    running: bool = False
    spectrum: list = field(default_factory=list)


def _db(x: float) -> float:
    return 20.0 * (-4.5 if x <= 1e-9 else __import__("math").log10(x))


class Metrics:
    def __init__(self, window: int = 120):
        self._lock = threading.Lock()
        self._proc: Deque[float] = deque(maxlen=window)
        self.snap = Snapshot()
        self._t0 = time.perf_counter()

    def record_block(self, process_ms: float, block_ms: float, infer_ms: float = 0.0) -> None:
        with self._lock:
            self._proc.append(process_ms)
            s = self.snap
            s.process_ms = process_ms
            s.infer_ms = infer_ms
            s.block_ms = block_ms
            s.blocks += 1
            if self._proc:
                ordered = sorted(self._proc)
                idx = min(len(ordered) - 1, int(len(ordered) * 0.95))
                s.process_p95_ms = ordered[idx]
            s.realtime_factor = (process_ms / block_ms) if block_ms > 0 else 0.0

    def record_levels(self, in_rms: float, in_peak: float,
                      out_rms: float, out_peak: float) -> None:
        with self._lock:
            s = self.snap
            s.input_rms_db = _db(in_rms)
            s.input_peak_db = _db(in_peak)
            s.output_rms_db = _db(out_rms)
            s.output_peak_db = _db(out_peak)

    def record_latency(self, total_ms: float) -> None:
        with self._lock:
            self.snap.total_latency_ms = total_ms

    def record_pitch(self, f0_hz: float, offset: float) -> None:
        with self._lock:
            self.snap.f0_hz = f0_hz
            self.snap.pitch_offset = offset

    def record_spectrum(self, bands: list) -> None:
        with self._lock:
            self.snap.spectrum = bands

    def add_dropout(self, n: int = 1) -> None:
        with self._lock:
            self.snap.dropouts += n

    def set_status(self, engine: str = "", device: str = "",
                   running: bool | None = None) -> None:
        with self._lock:
            if engine:
                self.snap.engine = engine
            if device:
                self.snap.device = device
            if running is not None:
                self.snap.running = running

    def reset(self) -> None:
        with self._lock:
            self._proc.clear()
            keep_engine, keep_device = self.snap.engine, self.snap.device
            self.snap = Snapshot(engine=keep_engine, device=keep_device)

    def get(self) -> Snapshot:
        with self._lock:
            s = self.snap
            return Snapshot(**{k: (list(v) if isinstance(v, list) else v)
                               for k, v in s.__dict__.items()})

    @property
    def health(self) -> str:
        rf = self.snap.realtime_factor
        if not self.snap.running:
            return "idle"
        if rf < 0.5:
            return "good"
        if rf < 0.8:
            return "tight"
        return "overloaded"
