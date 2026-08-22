"""Semantic version parsing and comparison.

Handles the tag shapes CI actually produces: 'v1.2.3', '1.2.3',
'1.2.3-nightly.4', '1.2.3+build.77'. Pre-release versions sort *below* the
same release version, per semver, so a nightly never masks a stable release.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_RE = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<pre>[0-9A-Za-z.\-]+))?"
    r"(?:\+(?P<build>[0-9A-Za-z.\-]+))?$"
)


@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int
    pre: Optional[str] = None
    build: Optional[str] = None

    def __str__(self) -> str:
        s = f"{self.major}.{self.minor}.{self.patch}"
        if self.pre:
            s += f"-{self.pre}"
        return s

    @property
    def is_prerelease(self) -> bool:
        return self.pre is not None

    @classmethod
    def parse(cls, text: str) -> Optional["Version"]:
        if not text:
            return None
        m = _RE.match(text.strip())
        if not m:
            return None
        return cls(int(m["major"]), int(m["minor"]), int(m["patch"]),
                   m["pre"], m["build"])

    # ------------------------------------------------------------ comparison
    def _key(self):
        return (self.major, self.minor, self.patch)

    @staticmethod
    def _pre_key(pre: Optional[str]):
        # no pre-release outranks any pre-release
        if pre is None:
            return (1,)
        parts = []
        for chunk in pre.split("."):
            if chunk.isdigit():
                parts.append((0, int(chunk), ""))
            else:
                parts.append((1, 0, chunk))
        return (0, tuple(parts))

    def __lt__(self, other: "Version") -> bool:
        if self._key() != other._key():
            return self._key() < other._key()
        a, b = self._pre_key(self.pre), self._pre_key(other.pre)
        if a[0] != b[0]:
            return a[0] < b[0]
        return a[1:] < b[1:]

    def __le__(self, other: "Version") -> bool:
        return self < other or self == other

    def __gt__(self, other: "Version") -> bool:
        return other < self

    def __ge__(self, other: "Version") -> bool:
        return other <= self


def is_newer(candidate: str, current: str) -> bool:
    """True when `candidate` is a strictly newer version than `current`."""
    c, cur = Version.parse(candidate), Version.parse(current)
    if c is None or cur is None:
        return False
    return c > cur
