"""Fixed-capacity float32 ring buffer for audio hand-off between the
device callbacks (realtime priority) and the processing thread.

Audio callbacks must never block or allocate, so the buffer never grows: on
overflow it drops the oldest samples and increments a counter the UI can show.
"""
from __future__ import annotations

import threading

import numpy as np


class RingBuffer:
    def __init__(self, capacity: int):
        self.capacity = int(capacity)
        self._buf = np.zeros(self.capacity, dtype=np.float32)
        self._read = 0
        self._write = 0
        self._count = 0
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self.overflows = 0
        self.underflows = 0

    def __len__(self) -> int:
        with self._lock:
            return self._count

    @property
    def free(self) -> int:
        with self._lock:
            return self.capacity - self._count

    def clear(self) -> None:
        with self._lock:
            self._read = self._write = self._count = 0

    def write(self, data: np.ndarray) -> int:
        data = np.asarray(data, dtype=np.float32).reshape(-1)
        n = len(data)
        if n == 0:
            return 0
        with self._not_empty:
            if n > self.capacity:
                # a single write larger than the whole buffer is itself an
                # overflow - keep only the newest samples
                data = data[-self.capacity:]
                n = self.capacity
                self.overflows += 1
                self._read = self._write = self._count = 0
            overflow = self._count + n - self.capacity
            if overflow > 0:
                # drop oldest
                self._read = (self._read + overflow) % self.capacity
                self._count -= overflow
                self.overflows += 1
            first = min(n, self.capacity - self._write)
            self._buf[self._write:self._write + first] = data[:first]
            rest = n - first
            if rest:
                self._buf[:rest] = data[first:]
            self._write = (self._write + n) % self.capacity
            self._count += n
            self._not_empty.notify()
        return n

    def read(self, n: int, partial_fill: bool = True) -> np.ndarray:
        """Read exactly n samples. Missing samples are zero-filled (and counted
        as an underflow) when partial_fill is True."""
        out = np.zeros(n, dtype=np.float32)
        with self._lock:
            avail = min(n, self._count)
            if avail < n:
                self.underflows += 1
                if not partial_fill:
                    return out
            first = min(avail, self.capacity - self._read)
            out[:first] = self._buf[self._read:self._read + first]
            rest = avail - first
            if rest:
                out[first:avail] = self._buf[:rest]
            self._read = (self._read + avail) % self.capacity
            self._count -= avail
        return out

    def wait_read(self, n: int, timeout: float = 0.5) -> np.ndarray | None:
        """Block until n samples are available, then read them."""
        with self._not_empty:
            if self._count < n:
                self._not_empty.wait_for(lambda: self._count >= n, timeout=timeout)
            if self._count < n:
                return None
        return self.read(n)
