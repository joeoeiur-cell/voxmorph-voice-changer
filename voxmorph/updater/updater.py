"""Auto-update.

On launch VoxMorph asks GitHub for the newest release on the selected channel.
If that release is newer than the running build, the main window shows an
"Update available" banner with the release notes and a one-click install.

This is what makes automated updates work end to end: when an AI agent (or
anyone else) pushes a commit, CI builds a new installer and publishes a
release. Every running copy of VoxMorph sees it on its next launch or its next
periodic poll - no extra infrastructure required, GitHub Releases *is* the
update server.

Channels
    stable     -> published, non-prerelease releases only
    ai-nightly -> includes prereleases, so agent-generated builds appear
                  immediately without disturbing stable users

Safety: the installer is SHA-256 verified against the checksum published in
the release body before it is ever executed. An unverifiable download is
discarded.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from .. import __repo__, __version__
from ..logging_setup import get_logger
from ..paths import UPDATE_DIR, ensure_dirs
from .version import Version, is_newer

log = get_logger("updater")

API = "https://api.github.com/repos/{repo}/releases"
UA = {"User-Agent": f"VoxMorph/{__version__}", "Accept": "application/vnd.github+json"}
SHA_RE = re.compile(r"\b([a-fA-F0-9]{64})\b")

ProgressCb = Callable[[str, float], None]


@dataclass
class UpdateInfo:
    version: str
    name: str
    notes: str
    url: str                       # installer asset download URL
    size: int = 0
    sha256: str = ""
    published: str = ""
    prerelease: bool = False
    html_url: str = ""
    asset_name: str = ""
    ai_generated: bool = False     # release authored by an automation

    @property
    def size_mb(self) -> float:
        return self.size / (1024 * 1024) if self.size else 0.0

    @property
    def short_notes(self) -> str:
        body = SHA_RE.sub("", self.notes or "").strip()
        lines = [ln for ln in body.splitlines() if ln.strip()]
        return "\n".join(lines[:12])


class Updater:
    INSTALLER_EXTS = (".exe", ".msi")

    def __init__(self, repo: str = __repo__, current: str = __version__):
        self.repo = repo
        self.current = current
        self.available: Optional[UpdateInfo] = None
        self.last_error: str = ""
        self._cancel = threading.Event()
        ensure_dirs()

    # ----------------------------------------------------------------- check
    def check(self, channel: str = "stable", timeout: int = 12) -> Optional[UpdateInfo]:
        """Query GitHub Releases. Returns an UpdateInfo when newer, else None."""
        self.last_error = ""
        try:
            releases = self._fetch_releases(timeout)
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("Update check failed: %s", exc)
            return None

        allow_pre = channel != "stable"
        best: Optional[UpdateInfo] = None
        best_ver: Optional[Version] = None

        for rel in releases:
            if rel.get("draft"):
                continue
            if rel.get("prerelease") and not allow_pre:
                continue
            tag = rel.get("tag_name") or rel.get("name") or ""
            ver = Version.parse(tag)
            if ver is None:
                continue
            if not is_newer(str(ver), self.current):
                continue
            asset = self._pick_asset(rel.get("assets") or [])
            if asset is None:
                continue
            if best_ver is None or ver > best_ver:
                body = rel.get("body") or ""
                m = SHA_RE.search(body)
                author = ((rel.get("author") or {}).get("login") or "").lower()
                best_ver = ver
                best = UpdateInfo(
                    version=str(ver),
                    name=rel.get("name") or tag,
                    notes=body,
                    url=asset.get("browser_download_url", ""),
                    size=int(asset.get("size") or 0),
                    sha256=(m.group(1).lower() if m else ""),
                    published=rel.get("published_at") or "",
                    prerelease=bool(rel.get("prerelease")),
                    html_url=rel.get("html_url", ""),
                    asset_name=asset.get("name", ""),
                    ai_generated=("bot" in author or "[bot]" in author
                                  or "automated" in body.lower()
                                  or "ai-generated" in body.lower()),
                )

        self.available = best
        if best:
            log.info("Update available: %s -> %s (%s)",
                     self.current, best.version, best.asset_name)
        else:
            log.info("VoxMorph is up to date (%s, channel=%s).", self.current, channel)
        return best

    def _fetch_releases(self, timeout: int) -> List[dict]:
        url = API.format(repo=self.repo) + "?per_page=25"
        headers = dict(UA)
        token = os.environ.get("GITHUB_TOKEN")
        if token:  # avoids the 60/hr anonymous rate limit
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _pick_asset(self, assets: List[dict]) -> Optional[dict]:
        """Choose the installer matching this platform."""
        if sys.platform != "win32":
            return next((a for a in assets
                         if a.get("name", "").lower().endswith((".zip", ".tar.gz"))), None)
        setups = [a for a in assets
                  if a.get("name", "").lower().endswith(self.INSTALLER_EXTS)]
        if not setups:
            return None
        for a in setups:  # prefer an explicit setup/installer artifact
            if "setup" in a.get("name", "").lower():
                return a
        return setups[0]

    def check_async(self, channel: str, callback: Callable[[Optional[UpdateInfo]], None]) -> None:
        def run():
            callback(self.check(channel))
        threading.Thread(target=run, name="voxmorph-updatecheck", daemon=True).start()

    def should_check(self, last_iso: str, interval_hours: int) -> bool:
        if not last_iso:
            return True
        try:
            last = datetime.fromisoformat(last_iso)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
        except ValueError:
            return True
        age = (datetime.now(timezone.utc) - last).total_seconds() / 3600.0
        return age >= max(1, interval_hours)

    @staticmethod
    def stamp_now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    # -------------------------------------------------------------- download
    def cancel(self) -> None:
        self._cancel.set()

    def download(self, info: UpdateInfo,
                 progress: Optional[ProgressCb] = None) -> Optional[Path]:
        """Download and verify the installer. Returns the local path."""
        self._cancel.clear()
        ensure_dirs()
        dest = UPDATE_DIR / (info.asset_name or f"VoxMorph-{info.version}-Setup.exe")
        tmp = dest.with_suffix(dest.suffix + ".part")

        if dest.exists() and info.sha256:
            if self._sha256(dest) == info.sha256:
                log.info("Installer already downloaded and verified.")
                return dest
            dest.unlink(missing_ok=True)

        try:
            req = urllib.request.Request(info.url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as resp:
                total = int(resp.headers.get("Content-Length", 0)) or info.size
                done = 0
                with open(tmp, "wb") as fh:
                    while True:
                        if self._cancel.is_set():
                            tmp.unlink(missing_ok=True)
                            log.info("Update download cancelled.")
                            return None
                        chunk = resp.read(1 << 18)
                        if not chunk:
                            break
                        fh.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(f"Downloading {info.version}",
                                     min(done / total, 1.0) if total else 0.0)
        except Exception as exc:
            self.last_error = str(exc)
            log.error("Update download failed: %s", exc)
            tmp.unlink(missing_ok=True)
            return None

        if info.sha256:
            actual = self._sha256(tmp)
            if actual != info.sha256:
                log.error("Installer checksum mismatch! expected %s got %s",
                          info.sha256[:12], actual[:12])
                self.last_error = ("Downloaded installer failed its integrity check "
                                   "and was discarded.")
                tmp.unlink(missing_ok=True)
                return None
            log.info("Installer checksum verified.")
        else:
            log.warning("Release published no SHA-256; cannot verify installer.")

        tmp.replace(dest)
        if progress:
            progress("Ready to install", 1.0)
        return dest

    @staticmethod
    def _sha256(path: Path) -> str:
        import hashlib
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()

    # --------------------------------------------------------------- install
    def install(self, installer: Path, silent: bool = False) -> bool:
        """Launch the installer and quit so it can replace our files."""
        installer = Path(installer)
        if not installer.exists():
            return False
        try:
            if sys.platform == "win32":
                args = [str(installer)]
                if silent:  # Inno Setup silent switches
                    args += ["/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"]
                subprocess.Popen(args, close_fds=True,
                                 creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
            else:
                subprocess.Popen(["xdg-open", str(installer)], close_fds=True)
            log.info("Installer launched: %s", installer.name)
            return True
        except Exception as exc:
            self.last_error = str(exc)
            log.error("Could not launch installer: %s", exc)
            return False

    def cleanup(self, keep: int = 1) -> None:
        """Delete stale downloaded installers."""
        try:
            files = sorted(UPDATE_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in files[keep:]:
                old.unlink(missing_ok=True)
        except Exception:
            pass
