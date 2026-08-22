#!/usr/bin/env python3
"""VoxMorph launcher. This module is the PyInstaller entry point."""
from __future__ import annotations

import multiprocessing
import sys


def main() -> int:
    # Required so PyInstaller-frozen builds do not respawn the whole GUI
    # in every worker process.
    multiprocessing.freeze_support()

    from voxmorph.cli import main as cli_main
    return cli_main()


if __name__ == "__main__":
    sys.exit(main())
