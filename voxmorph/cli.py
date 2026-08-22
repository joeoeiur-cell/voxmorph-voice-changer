"""Command line interface.

Useful for headless boxes, scripting batch conversions, and diagnosing audio
problems without the GUI in the way.

    voxmorph                          launch the GUI
    voxmorph devices                  list audio devices
    voxmorph voices                   list preset voices
    voxmorph run --preset dsp_deep_male
    voxmorph convert in.wav out.wav --preset local_myvoice
    voxmorph check-update
    voxmorph doctor                   diagnose the install
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import __version__


def _cmd_devices(_args) -> int:
    from .audio.devices import list_devices, find_virtual_cable, setup_advice
    print(f"{'#':>3}  {'in':>3} {'out':>3}  {'rate':>6}  name")
    print("-" * 78)
    for d in list_devices():
        flag = "*" if d.is_virtual_cable else " "
        print(f"{d.index:>3}{flag} {d.max_input:>3} {d.max_output:>3}  "
              f"{d.default_samplerate:>6.0f}  {d.name}  [{d.hostapi}]")
    cable = find_virtual_cable()
    print(f"\nVirtual cable: {cable.name if cable else 'NOT FOUND'}")
    for tip in setup_advice():
        print("  -", tip)
    return 0


def _cmd_voices(_args) -> int:
    from .presets.manager import PresetManager
    pm = PresetManager()
    print(f"{'id':<26} {'kind':<8} {'category':<12} {'state':<12} name")
    print("-" * 88)
    for p in pm.list():
        state = "installed" if p.installed else f"{p.size_mb:.0f} MB dl"
        print(f"{p.id:<26} {p.kind:<8} {p.category:<12} {state:<12} {p.name}")
    print(f"\n{len(pm.list())} voice(s). Identity voices sound the same for every "
          f"speaker; character voices transform your own voice.")
    return 0


def _cmd_run(args) -> int:
    from .app import VoxMorphApp
    from .logging_setup import setup_logging
    setup_logging()

    app = VoxMorphApp()
    app.notify = lambda lvl, msg: print(f"[{lvl}] {msg}")
    app.initialise()
    if args.preset:
        if not app.load_preset(args.preset):
            return 2
    if args.input is not None:
        app.cfg.audio.input_device = args.input
    if args.output is not None:
        app.cfg.audio.output_device = args.output
    if not app.start():
        print("Failed to start audio.", file=sys.stderr)
        return 1

    print("Running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1.0)
            s = app.metrics.get()
            print(f"\rlatency {s.total_latency_ms:5.0f} ms | load "
                  f"{s.realtime_factor * 100:4.0f}% | drops {s.dropouts:3d} | "
                  f"f0 {s.f0_hz:5.0f} Hz", end="", flush=True)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        app.shutdown()
    return 0


def _cmd_convert(args) -> int:
    """Offline file conversion at full quality."""
    from .config import Config
    from .engines.registry import create_engine
    from .presets.manager import PresetManager
    from .logging_setup import setup_logging
    setup_logging()

    pm = PresetManager()
    preset = pm.get(args.preset)
    if preset is None:
        print(f"Unknown preset '{args.preset}'.", file=sys.stderr)
        return 2

    cfg = Config.load()
    cfg.engine.backend = "rvc" if preset.kind == "rvc" else "dsp"
    engine, msg = create_engine(cfg)
    print(msg)
    engine.load(preset)

    if hasattr(engine, "convert_file") and preset.kind == "rvc":
        engine.convert_file(args.src, args.dst)
        print(f"Wrote {args.dst}")
        return 0

    # DSP path: stream the file through the same chain used live
    import numpy as np
    import soundfile as sf
    from .dsp.chain import FXChain

    data, sr = sf.read(args.src, dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    chain = FXChain(sr, cfg.fx)
    dsp = preset.dsp or {}
    chain.update(cfg.fx, formant_semis=dsp.get("formant", 0.0),
                 pitch_semis=dsp.get("pitch", 0.0))
    block = 4096
    out = []
    for i in range(0, len(data), block):
        seg = data[i:i + block]
        out.append(chain.post.process(chain.pre.process(seg)))
    sf.write(args.dst, np.concatenate(out), sr)
    print(f"Wrote {args.dst}")
    return 0


def _cmd_morph(args) -> int:
    """Offline high-quality voice morphing via the WORLD vocoder.

    Separate from `convert` because this path is not realtime: it analyses the
    whole file into F0 / spectral envelope / aperiodicity, transforms each
    independently, and resynthesises. Slower, but markedly more natural than
    the realtime phase vocoder - measurably higher harmonics-to-noise ratio.
    """
    import numpy as np
    import soundfile as sf

    from .dsp.world_morph import HAVE_WORLD, PRESETS, morph_preset
    from .dsp.pitch import median_f0
    from .logging_setup import setup_logging
    setup_logging()

    if not HAVE_WORLD:
        print("This command needs the WORLD vocoder:\n  pip install pyworld",
              file=sys.stderr)
        return 2

    if args.preset not in PRESETS:
        print(f"Unknown preset '{args.preset}'.\nAvailable: "
              f"{', '.join(sorted(PRESETS))}", file=sys.stderr)
        return 2

    data, sr = sf.read(args.src, dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)

    print(f"source: {len(data)/sr:.2f}s @ {sr} Hz  F0 {median_f0(data, sr):.1f} Hz")
    out, report = morph_preset(data, sr, args.preset)
    sf.write(args.dst, out, sr)

    print(f"preset: {PRESETS[args.preset].name}")
    for k, v in report.items():
        print(f"  {k:<15} {v}")
    print(f"wrote {args.dst}")
    return 0


def _cmd_morph_list(_args) -> int:
    from .dsp.world_morph import PRESETS
    print(f"{'id':<16} {'F0':>7}  {'tract':>6}  {'tilt':>6}  description")
    print("-" * 92)
    for pid, s in sorted(PRESETS.items()):
        f0 = f"{s.target_f0:.0f}Hz" if s.target_f0 else "keep"
        print(f"{pid:<16} {f0:>7}  {s.formant_ratio:>6.2f}  "
              f"{s.tilt_db_oct:>+5.1f}dB  {s.description}")
    return 0


def _cmd_check_update(args) -> int:
    from .updater.updater import Updater
    u = Updater()
    info = u.check(args.channel)
    if info is None:
        print(f"Up to date (v{__version__}). {u.last_error}".strip())
        return 0
    print(f"Update available: v{info.version}  ({info.size_mb:.1f} MB)")
    print(f"  asset:    {info.asset_name}")
    print(f"  verified: {'sha256 published' if info.sha256 else 'NO CHECKSUM'}")
    print(f"  ai build: {info.ai_generated}")
    print(f"\n{info.short_notes}")
    return 0


def _cmd_doctor(_args) -> int:
    """Diagnose the installation."""
    print(f"VoxMorph {__version__}\n" + "=" * 40)
    ok = True

    def check(label, fn):
        nonlocal ok
        try:
            result = fn()
            print(f"  [ok]   {label}: {result}")
        except Exception as exc:
            ok = False
            print(f"  [FAIL] {label}: {exc}")

    print("\nCore:")
    check("python", lambda: sys.version.split()[0])
    check("numpy", lambda: __import__("numpy").__version__)
    check("scipy", lambda: __import__("scipy").__version__)
    check("numba (JIT DSP)", lambda: __import__("numba").__version__)

    print("\nAudio:")
    check("sounddevice", lambda: __import__("sounddevice").__version__)
    check("soundfile", lambda: __import__("soundfile").__version__)

    def devices():
        from .audio.devices import input_devices, output_devices, find_virtual_cable
        c = find_virtual_cable()
        return (f"{len(input_devices())} in / {len(output_devices())} out, "
                f"cable: {c.name if c else 'none'}")
    check("devices", devices)

    print("\nNeural backends:")
    def torch_info():
        import torch
        dev = "CUDA " + torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU only"
        return f"{torch.__version__} ({dev})"
    check("torch", torch_info)
    check("rvc-python", lambda: __import__("rvc_python") and "installed")

    print("\nUI / extras:")
    check("PySide6", lambda: __import__("PySide6").__version__)
    check("keyboard (hotkeys)", lambda: __import__("keyboard") and "installed")

    print("\nPresets:")
    def presets():
        from .presets.manager import PresetManager
        pm = PresetManager()
        ident = sum(1 for p in pm.list() if p.is_identity)
        return f"{len(pm.list())} total, {ident} identity voice(s)"
    check("catalog", presets)

    print("\n" + ("All core checks passed." if ok else
                  "Some checks failed - see above. The app will still run in "
                  "reduced mode where possible."))
    return 0 if ok else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="voxmorph",
                                     description="VoxMorph realtime voice changer")
    parser.add_argument("--version", action="version", version=f"VoxMorph {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("devices", help="list audio devices").set_defaults(fn=_cmd_devices)
    sub.add_parser("voices", help="list preset voices").set_defaults(fn=_cmd_voices)
    sub.add_parser("doctor", help="diagnose the installation").set_defaults(fn=_cmd_doctor)

    p_run = sub.add_parser("run", help="run headless")
    p_run.add_argument("--preset")
    p_run.add_argument("--input", type=int)
    p_run.add_argument("--output", type=int)
    p_run.set_defaults(fn=_cmd_run)

    p_conv = sub.add_parser("convert", help="convert an audio file")
    p_conv.add_argument("src")
    p_conv.add_argument("dst")
    p_conv.add_argument("--preset", required=True)
    p_conv.set_defaults(fn=_cmd_convert)

    p_morph = sub.add_parser("morph", help="high-quality offline voice morph (WORLD)")
    p_morph.add_argument("src")
    p_morph.add_argument("dst")
    p_morph.add_argument("--preset", required=True,
                         help="see: voxmorph morphs")
    p_morph.set_defaults(fn=_cmd_morph)

    sub.add_parser("morphs", help="list WORLD morph presets").set_defaults(fn=_cmd_morph_list)

    p_up = sub.add_parser("check-update", help="check for a new release")
    p_up.add_argument("--channel", default="stable", choices=["stable", "ai-nightly"])
    p_up.set_defaults(fn=_cmd_check_update)

    args = parser.parse_args(argv)
    if not getattr(args, "fn", None):
        from .ui import run_gui
        return run_gui()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
