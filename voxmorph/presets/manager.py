"""Preset discovery, download and verification.

Sources, merged in priority order:
  1. Bundled catalog.json (character presets - always available offline)
  2. Remote catalog (identity presets published by you)
  3. Local models folder (any .pth the user dropped in, auto-paired with .index)

Downloads are resumable, SHA-256 verified, and written atomically so a killed
download can never leave a half-written checkpoint that crashes the loader.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from ..logging_setup import get_logger
from ..paths import MODELS_DIR, CACHE_DIR, ensure_dirs, resource

log = get_logger("presets")

ProgressCb = Callable[[str, float], None]  # (message, 0..1)


@dataclass
class Preset:
    id: str
    name: str
    kind: str = "dsp"                 # dsp | rvc | seedvc
    category: str = "Character"
    description: str = ""
    dsp: Dict = field(default_factory=dict)
    fx: Dict = field(default_factory=dict)
    model_url: str = ""
    model_sha256: str = ""
    index_url: str = ""
    index_sha256: str = ""
    size_mb: float = 0.0
    target_f0: float = 0.0
    recommended: Dict = field(default_factory=dict)
    license: str = ""
    reference_path: str = ""
    _local_model: Optional[Path] = None
    _local_index: Optional[Path] = None

    # ------------------------------------------------------------------ paths
    @property
    def model_path(self) -> str:
        if self._local_model:
            return str(self._local_model)
        return str(MODELS_DIR / f"{self.id}.pth") if self.model_url else ""

    @property
    def index_path(self) -> str:
        if self._local_index:
            return str(self._local_index)
        p = MODELS_DIR / f"{self.id}.index"
        return str(p) if self.index_url and p.exists() else ""

    @property
    def needs_download(self) -> bool:
        if self.kind == "dsp":
            return False
        mp = self.model_path
        return not (mp and Path(mp).exists())

    @property
    def installed(self) -> bool:
        return not self.needs_download

    @property
    def is_identity(self) -> bool:
        """True when the output voice is the same regardless of who speaks."""
        return self.kind in ("rvc", "seedvc")

    @classmethod
    def from_dict(cls, d: Dict) -> "Preset":
        known = {f for f in cls.__dataclass_fields__ if not f.startswith("_")}
        return cls(**{k: v for k, v in d.items() if k in known})


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


class PresetManager:
    def __init__(self) -> None:
        ensure_dirs()
        self.presets: Dict[str, Preset] = {}
        self._lock = threading.Lock()
        self.remote_url: str = ""
        self.load_all()

    # ------------------------------------------------------------- discovery
    def load_all(self) -> None:
        with self._lock:
            self.presets.clear()
            self._load_bundled()
            self._load_cached_remote()
            self._scan_local_models()
        log.info("Loaded %d presets (%d identity, %d character)",
                 len(self.presets),
                 sum(1 for p in self.presets.values() if p.is_identity),
                 sum(1 for p in self.presets.values() if not p.is_identity))

    def _load_bundled(self) -> None:
        path = resource("voxmorph", "presets", "catalog.json")
        if not path.exists():
            path = Path(__file__).with_name("catalog.json")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.error("Bundled catalog unreadable: %s", exc)
            return
        self.remote_url = data.get("remote_catalog_url", "")
        for entry in data.get("presets", []):
            p = Preset.from_dict(entry)
            self.presets[p.id] = p

    def _load_cached_remote(self) -> None:
        cache = CACHE_DIR / "remote_catalog.json"
        if not cache.exists():
            return
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            for entry in data.get("presets", []):
                p = Preset.from_dict(entry)
                self.presets[p.id] = p
        except Exception as exc:
            log.warning("Cached remote catalog ignored: %s", exc)

    def _scan_local_models(self) -> None:
        """Any .pth the user drops into the models folder becomes a preset.
        A same-named .index is paired automatically."""
        for pth in sorted(MODELS_DIR.glob("*.pth")):
            pid = f"local_{pth.stem}"
            if pid in self.presets:
                continue
            index = next((c for c in (pth.with_suffix(".index"),
                                      MODELS_DIR / f"{pth.stem}.index") if c.exists()), None)
            meta = pth.with_suffix(".json")
            target_f0 = 0.0
            desc = "Imported local RVC model."
            if meta.exists():
                try:
                    m = json.loads(meta.read_text(encoding="utf-8"))
                    target_f0 = float(m.get("target_f0", 0.0))
                    desc = m.get("description", desc)
                except Exception:
                    pass
            p = Preset(id=pid, name=pth.stem.replace("_", " ").title(), kind="rvc",
                       category="My Voices", description=desc, target_f0=target_f0)
            p._local_model = pth
            p._local_index = index
            self.presets[pid] = p

    # ---------------------------------------------------------------- access
    def get(self, preset_id: str) -> Optional[Preset]:
        return self.presets.get(preset_id)

    def list(self, kind: Optional[str] = None,
             installed_only: bool = False) -> List[Preset]:
        items = list(self.presets.values())
        if kind:
            items = [p for p in items if p.kind == kind]
        if installed_only:
            items = [p for p in items if p.installed]
        return sorted(items, key=lambda p: (p.category, p.name))

    def categories(self) -> List[str]:
        return sorted({p.category for p in self.presets.values()})

    # ------------------------------------------------------------- remote io
    def refresh_remote(self, timeout: int = 15) -> int:
        """Fetch the published identity-voice catalog. Returns count added."""
        if not self.remote_url:
            return 0
        import urllib.request
        try:
            req = urllib.request.Request(self.remote_url,
                                         headers={"User-Agent": "VoxMorph"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            log.warning("Remote catalog fetch failed: %s", exc)
            return 0

        (CACHE_DIR / "remote_catalog.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8")
        added = 0
        with self._lock:
            for entry in data.get("presets", []):
                p = Preset.from_dict(entry)
                if p.id not in self.presets:
                    added += 1
                self.presets[p.id] = p
        log.info("Remote catalog refreshed (+%d)", added)
        return added

    # ------------------------------------------------------------- downloads
    def download(self, preset_id: str, progress: Optional[ProgressCb] = None,
                 cancel: Optional[threading.Event] = None) -> bool:
        p = self.get(preset_id)
        if p is None or p.kind == "dsp":
            return True
        ok = True
        if p.model_url:
            ok &= self._fetch(p.model_url, MODELS_DIR / f"{p.id}.pth",
                              p.model_sha256, f"{p.name} model", progress, cancel)
        if ok and p.index_url:
            ok &= self._fetch(p.index_url, MODELS_DIR / f"{p.id}.index",
                              p.index_sha256, f"{p.name} index", progress, cancel)
        return ok

    def _fetch(self, url: str, dest: Path, expect_sha: str, label: str,
               progress: Optional[ProgressCb], cancel: Optional[threading.Event]) -> bool:
        import urllib.request

        if dest.exists() and expect_sha:
            if sha256_file(dest) == expect_sha.lower():
                log.info("%s already present and verified.", label)
                return True
            log.warning("%s failed checksum; re-downloading.", label)
            dest.unlink(missing_ok=True)

        tmp = dest.with_suffix(dest.suffix + ".part")
        resume = tmp.stat().st_size if tmp.exists() else 0
        headers = {"User-Agent": "VoxMorph"}
        if resume:
            headers["Range"] = f"bytes={resume}-"

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                total = int(resp.headers.get("Content-Length", 0)) + resume
                mode = "ab" if resume and resp.status == 206 else "wb"
                if mode == "wb":
                    resume = 0
                done = resume
                with open(tmp, mode) as fh:
                    while True:
                        if cancel is not None and cancel.is_set():
                            log.info("%s download cancelled.", label)
                            return False
                        chunk = resp.read(1 << 18)
                        if not chunk:
                            break
                        fh.write(chunk)
                        done += len(chunk)
                        if progress and total:
                            progress(f"Downloading {label}", min(done / total, 1.0))
        except Exception as exc:
            log.error("%s download failed: %s", label, exc)
            return False

        if expect_sha:
            actual = sha256_file(tmp)
            if actual != expect_sha.lower():
                log.error("%s checksum mismatch (expected %s, got %s)",
                          label, expect_sha[:12], actual[:12])
                tmp.unlink(missing_ok=True)
                return False

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp), str(dest))   # atomic within the same filesystem
        if progress:
            progress(f"{label} installed", 1.0)
        log.info("%s installed -> %s", label, dest.name)
        return True

    def delete(self, preset_id: str) -> None:
        p = self.get(preset_id)
        if p is None or p.kind == "dsp":
            return
        for path in (MODELS_DIR / f"{p.id}.pth", MODELS_DIR / f"{p.id}.index"):
            path.unlink(missing_ok=True)
        log.info("Removed preset files for %s", preset_id)

    def import_model(self, src: Path, name: Optional[str] = None) -> Optional[Preset]:
        """Copy a user-supplied .pth (and sibling .index) into the models dir."""
        src = Path(src)
        if not src.exists() or src.suffix != ".pth":
            return None
        stem = (name or src.stem).replace(" ", "_")
        dest = MODELS_DIR / f"{stem}.pth"
        shutil.copy2(src, dest)
        sib = src.with_suffix(".index")
        if sib.exists():
            shutil.copy2(sib, MODELS_DIR / f"{stem}.index")
        self.load_all()
        return self.get(f"local_{stem}")
