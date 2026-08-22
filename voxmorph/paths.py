"""Filesystem locations. All user data lives outside Program Files so the
frozen .exe never needs write access to its own install directory."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _base_data_dir() -> Path:
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(root) / "VoxMorph"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "VoxMorph"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "voxmorph"


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def app_root() -> Path:
    """Directory containing bundled read-only resources."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


DATA_DIR = _base_data_dir()
MODELS_DIR = DATA_DIR / "models"          # downloaded RVC / seed-vc checkpoints
PROFILES_DIR = DATA_DIR / "profiles"      # user-saved voice profiles
RECORDINGS_DIR = DATA_DIR / "recordings"
SOUNDBOARD_DIR = DATA_DIR / "soundboard"
CACHE_DIR = DATA_DIR / "cache"
UPDATE_DIR = CACHE_DIR / "updates"
LOG_DIR = DATA_DIR / "logs"
CONFIG_FILE = DATA_DIR / "config.json"

_ALL = (DATA_DIR, MODELS_DIR, PROFILES_DIR, RECORDINGS_DIR,
        SOUNDBOARD_DIR, CACHE_DIR, UPDATE_DIR, LOG_DIR)


def ensure_dirs() -> None:
    for d in _ALL:
        d.mkdir(parents=True, exist_ok=True)


def resource(*parts: str) -> Path:
    """Path to a bundled resource (icons, catalog.json, ...)."""
    return app_root().joinpath(*parts)
