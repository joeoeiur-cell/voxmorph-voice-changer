# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for VoxMorph.

Produces a ONEDIR build (not onefile) on purpose:
  * onefile unpacks ~1 GB of torch DLLs to %TEMP% on every launch, adding
    10-30 s of startup and breaking the updater's file replacement.
  * onedir starts in ~2 s and lets Inno Setup patch individual files.

Build:  pyinstaller build/voxmorph.spec --noconfirm --clean
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))

block_cipher = None

datas = [
    (str(ROOT / "voxmorph" / "presets" / "catalog.json"), "voxmorph/presets"),
    (str(ROOT / "version.json"), "."),
]
if (ROOT / "assets").exists():
    datas.append((str(ROOT / "assets"), "assets"))

hiddenimports = [
    "sounddevice", "soundfile", "_soundfile_data",
    "scipy.signal", "scipy.special", "scipy._lib.array_api_compat.numpy.fft",
    "numba", "llvmlite",
    "voxmorph.engines.rvc_engine", "voxmorph.engines.seedvc_engine",
    "voxmorph.engines.dsp_engine",
]
hiddenimports += collect_submodules("voxmorph")

# Torch / RVC are optional at build time: if they are installed in the build
# environment we bundle them, otherwise we ship the DSP-only build.
try:
    import torch  # noqa: F401
    hiddenimports += ["torch", "torchaudio", "rvc_python", "faiss", "fairseq"]
    datas += collect_data_files("rvc_python", include_py_files=False)
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

excludes = [
    "tkinter", "matplotlib", "pytest", "IPython", "notebook",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.Qt3DCore", "PySide6.QtQuick3D", "PySide6.QtMultimedia",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf",
]
if not HAS_TORCH:
    excludes += ["torch", "torchaudio", "rvc_python"]

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

icon = ROOT / "assets" / "voxmorph.ico"

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VoxMorph",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # UPX corrupts some torch DLLs - leave it off
    console=False,          # windowed app; use VoxMorph-cli.exe for the CLI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon) if icon.exists() else None,
    version=str(ROOT / "build" / "file_version_info.txt")
    if (ROOT / "build" / "file_version_info.txt").exists() else None,
)

# A second console entry point so `VoxMorph-cli.exe doctor` works for support.
exe_cli = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VoxMorph-cli",
    debug=False,
    strip=False,
    upx=False,
    console=True,
    icon=str(icon) if icon.exists() else None,
)

coll = COLLECT(
    exe,
    exe_cli,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="VoxMorph",
)
