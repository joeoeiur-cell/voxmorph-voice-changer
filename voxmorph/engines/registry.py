"""Engine factory with automatic graceful degradation.

If the requested backend cannot start (no GPU, missing dependency, corrupt
checkpoint) the app must not die - it falls back down the chain
rvc -> seedvc -> dsp and tells the UI why.
"""
from __future__ import annotations

from typing import Dict, List, Tuple, Type

from ..config import Config
from ..logging_setup import get_logger
from .base import EngineCaps, EngineError, VoiceEngine
from .dsp_engine import DSPEngine
from .rvc_engine import RVCEngine, resolve_device
from .seedvc_engine import SeedVCEngine

log = get_logger("registry")

ENGINES: Dict[str, Type[VoiceEngine]] = {
    "rvc": RVCEngine,
    "seedvc": SeedVCEngine,
    "dsp": DSPEngine,
}

FALLBACK_ORDER = ("rvc", "seedvc", "dsp")


def available_engines() -> List[EngineCaps]:
    return [cls.caps for cls in ENGINES.values()]


def describe_device(requested: str = "auto") -> str:
    dev = resolve_device(requested)
    try:
        import torch
        if dev.startswith("cuda"):
            return f"{torch.cuda.get_device_name(0)} (CUDA)"
        if dev.startswith("privateuseone"):
            return "GPU (DirectML)"
        if dev == "mps":
            return "Apple Silicon (MPS)"
        return "CPU"
    except ImportError:
        return "CPU (PyTorch not installed)"


def create_engine(cfg: Config) -> Tuple[VoiceEngine, str]:
    """Build the configured engine. Returns (engine, status_message)."""
    name = cfg.engine.backend
    lat = cfg.latency()
    order = [name] + [e for e in FALLBACK_ORDER if e != name]
    problems: List[str] = []

    for candidate in order:
        cls = ENGINES.get(candidate)
        if cls is None:
            continue
        try:
            if candidate == "rvc":
                eng = RVCEngine(
                    samplerate=cfg.audio.samplerate,
                    device=cfg.engine.device,
                    half=cfg.engine.half_precision,
                    context_ms=lat["context_ms"],
                    crossfade_ms=lat["crossfade_ms"],
                )
            elif candidate == "seedvc":
                eng = SeedVCEngine(
                    samplerate=cfg.audio.samplerate,
                    device=cfg.engine.device,
                    context_ms=lat["context_ms"],
                    crossfade_ms=lat["crossfade_ms"],
                )
            else:
                eng = DSPEngine(samplerate=cfg.audio.samplerate)

            if candidate != name:
                msg = f"Fell back to {eng.caps.display_name}: " + "; ".join(problems)
                log.warning(msg)
                return eng, msg
            return eng, f"{eng.caps.display_name} ready on {describe_device(cfg.engine.device)}"
        except EngineError as exc:
            problems.append(f"{candidate}: {exc}")
        except Exception as exc:  # pragma: no cover
            problems.append(f"{candidate}: unexpected error {exc}")

    return DSPEngine(samplerate=cfg.audio.samplerate), "; ".join(problems) or "DSP fallback"
