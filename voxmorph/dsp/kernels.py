"""Hot per-sample DSP loops.

These are the only genuinely serial parts of the pipeline (they contain
feedback, so they cannot be vectorised). They are JIT-compiled with numba when
available - roughly 50-150x faster than the interpreted equivalent, which is
the difference between hitting and missing a 60 ms realtime budget.

If numba is unavailable the module transparently falls back to the plain
Python implementations so the app still runs, just with a higher CPU load.
"""
from __future__ import annotations

import numpy as np

try:  # pragma: no cover - environment dependent
    from numba import njit

    HAVE_NUMBA = True
except Exception:  # pragma: no cover
    HAVE_NUMBA = False

    def njit(*args, **kwargs):  # type: ignore[misc]
        def wrap(fn):
            return fn
        if args and callable(args[0]):
            return args[0]
        return wrap


@njit(cache=True, fastmath=True)
def env_follow(rect, env, ca, cr):
    n = rect.shape[0]
    out = np.empty(n, dtype=np.float32)
    for i in range(n):
        v = rect[i]
        c = ca if v > env else cr
        env = c * env + (1.0 - c) * v
        out[i] = env
    return out, env


@njit(cache=True, fastmath=True)
def gate_kernel(x, env, thr_open, thr_close, ca, cr, gain, hold, hold_samples, is_open):
    n = x.shape[0]
    out = np.empty(n, dtype=np.float32)
    for i in range(n):
        e = env[i]
        if e > thr_open:
            is_open = True
            hold = hold_samples
        elif is_open and e < thr_close:
            if hold > 0:
                hold -= 1
            else:
                is_open = False
        target = 1.0 if is_open else 0.0
        c = ca if target > gain else cr
        gain = c * gain + (1.0 - c) * target
        out[i] = x[i] * gain
    return out, gain, hold, is_open


@njit(cache=True, fastmath=True)
def limiter_kernel(delayed, target, gain, cr):
    n = delayed.shape[0]
    out = np.empty(n, dtype=np.float32)
    for i in range(n):
        t = target[i]
        if t < gain:
            gain = t
        else:
            gain = cr * gain + (1.0 - cr) * t
        v = delayed[i] * gain
        if v > 1.0:
            v = 1.0
        elif v < -1.0:
            v = -1.0
        out[i] = v
    return out, gain


@njit(cache=True, fastmath=True)
def comb_kernel(x, buf, size, idx, store, room, damp):
    n = x.shape[0]
    out = np.empty(n, dtype=np.float32)
    for s in range(n):
        y = buf[idx]
        out[s] = y
        store = y * (1.0 - damp) + store * damp
        buf[idx] = x[s] + store * room
        idx += 1
        if idx >= size:
            idx = 0
    return out, idx, store


@njit(cache=True, fastmath=True)
def allpass_kernel(x, buf, size, idx, g):
    n = x.shape[0]
    out = np.empty(n, dtype=np.float32)
    for s in range(n):
        bufout = buf[idx]
        out[s] = -x[s] + bufout
        buf[idx] = x[s] + bufout * g
        idx += 1
        if idx >= size:
            idx = 0
    return out, idx


def warmup() -> None:
    """Force JIT compilation at startup so the first audio block is not slow.
    Called from a background thread during splash/init."""
    if not HAVE_NUMBA:
        return
    z = np.zeros(64, dtype=np.float32)
    o = np.ones(64, dtype=np.float32)
    buf = np.zeros(32, dtype=np.float32)
    env_follow(z, 0.0, 0.5, 0.5)
    gate_kernel(z, z, 0.1, 0.05, 0.5, 0.5, 0.0, 0, 10, False)
    limiter_kernel(z, o, 1.0, 0.5)
    comb_kernel(z, buf, 32, 0, 0.0, 0.7, 0.3)
    allpass_kernel(z, buf, 32, 0, 0.5)
