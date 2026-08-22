"""Rotating file + console logging. Safe under PyInstaller --windowed where
sys.stdout can be None."""
from __future__ import annotations

import logging
import logging.handlers
import sys

from .paths import LOG_DIR, ensure_dirs

_FMT = "%(asctime)s [%(levelname)-7s] %(name)-22s %(message)s"
_configured = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    global _configured
    if _configured:
        return logging.getLogger("voxmorph")

    ensure_dirs()
    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter(_FMT, datefmt="%H:%M:%S")

    fh = logging.handlers.RotatingFileHandler(
        LOG_DIR / "voxmorph.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    if sys.stderr is not None:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        root.addHandler(sh)

    # Third-party noise control
    for noisy in ("numba", "matplotlib", "urllib3", "fairseq", "torch"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True
    return logging.getLogger("voxmorph")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"voxmorph.{name}")
