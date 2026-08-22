"""User voice profiles: a preset plus every tweak you made to it.

Lets you save "my Discord voice" (preset + pitch + FX + gate threshold) and
recall it in one click, or export it as a .vmprofile file to share.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..config import EngineConfig, FXConfig
from ..logging_setup import get_logger
from ..paths import PROFILES_DIR, ensure_dirs

log = get_logger("profiles")

SAFE = re.compile(r"[^A-Za-z0-9_\- ]+")


@dataclass
class VoiceProfile:
    name: str
    preset_id: str
    engine: Dict = field(default_factory=dict)
    fx: Dict = field(default_factory=dict)
    created: str = ""
    notes: str = ""

    @classmethod
    def capture(cls, name: str, preset_id: str,
                engine: EngineConfig, fx: FXConfig, notes: str = "") -> "VoiceProfile":
        return cls(
            name=name,
            preset_id=preset_id,
            engine=asdict(engine),
            fx=asdict(fx),
            created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            notes=notes,
        )

    def apply(self, engine: EngineConfig, fx: FXConfig) -> None:
        for k, v in (self.engine or {}).items():
            if hasattr(engine, k):
                setattr(engine, k, v)
        for k, v in (self.fx or {}).items():
            if hasattr(fx, k):
                setattr(fx, k, v)

    @property
    def filename(self) -> str:
        return SAFE.sub("", self.name).strip().replace(" ", "_") or "profile"


class ProfileStore:
    EXT = ".vmprofile"

    def __init__(self) -> None:
        ensure_dirs()

    def list(self) -> List[VoiceProfile]:
        out: List[VoiceProfile] = []
        for path in sorted(PROFILES_DIR.glob(f"*{self.EXT}")):
            p = self._read(path)
            if p:
                out.append(p)
        return out

    def _read(self, path: Path) -> Optional[VoiceProfile]:
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            return VoiceProfile(**{k: v for k, v in d.items()
                                   if k in VoiceProfile.__dataclass_fields__})
        except Exception as exc:
            log.warning("Skipping unreadable profile %s: %s", path.name, exc)
            return None

    def save(self, profile: VoiceProfile) -> Path:
        ensure_dirs()
        path = PROFILES_DIR / f"{profile.filename}{self.EXT}"
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(asdict(profile), indent=2), encoding="utf-8")
        tmp.replace(path)
        log.info("Saved profile '%s'", profile.name)
        return path

    def load(self, name: str) -> Optional[VoiceProfile]:
        path = PROFILES_DIR / f"{SAFE.sub('', name).strip().replace(' ', '_')}{self.EXT}"
        return self._read(path) if path.exists() else None

    def delete(self, name: str) -> bool:
        path = PROFILES_DIR / f"{SAFE.sub('', name).strip().replace(' ', '_')}{self.EXT}"
        if path.exists():
            path.unlink()
            return True
        return False

    def export(self, profile: VoiceProfile, dest: Path) -> Path:
        Path(dest).write_text(json.dumps(asdict(profile), indent=2), encoding="utf-8")
        return Path(dest)

    def import_file(self, src: Path) -> Optional[VoiceProfile]:
        p = self._read(Path(src))
        if p:
            self.save(p)
        return p
