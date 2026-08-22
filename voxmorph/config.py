"""Typed, versioned, crash-safe configuration."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict

from .logging_setup import get_logger
from .paths import CONFIG_FILE, ensure_dirs

log = get_logger("config")

CONFIG_SCHEMA = 3

# name -> (block_frames, left_context_frames, crossfade_frames) at 16 kHz feature rate
LATENCY_PROFILES: Dict[str, Dict[str, float]] = {
    "ultra":    {"block_ms": 60,  "context_ms": 900,  "crossfade_ms": 20, "label": "Ultra-Low (~55 ms)"},
    "low":      {"block_ms": 96,  "context_ms": 1400, "crossfade_ms": 32, "label": "Low (~90 ms)"},
    "balanced": {"block_ms": 160, "context_ms": 2000, "crossfade_ms": 48, "label": "Balanced (~150 ms)"},
    "quality":  {"block_ms": 260, "context_ms": 2800, "crossfade_ms": 64, "label": "Max Quality (~250 ms)"},
}


@dataclass
class AudioConfig:
    input_device: int | None = None
    output_device: int | None = None
    monitor_device: int | None = None     # "hear yourself" device (headphones)
    monitor_enabled: bool = False
    monitor_volume_db: float = -6.0
    samplerate: int = 48000
    channels: int = 1
    latency_profile: str = "low"
    exclusive_wasapi: bool = False        # lowest latency on Windows
    input_gain_db: float = 0.0
    output_gain_db: float = 0.0


@dataclass
class EngineConfig:
    backend: str = "rvc"                  # rvc | seedvc | dsp
    device: str = "auto"                  # auto | cuda | directml | cpu
    preset_id: str = "dsp_natural"
    f0_method: str = "rmvpe"              # rmvpe | fcpe | crepe-tiny | harvest
    pitch_shift: int = 0                  # semitones, applied to the source f0
    index_rate: float = 0.60              # timbre retrieval strength
    protect: float = 0.33                 # protect unvoiced consonants
    rms_mix_rate: float = 0.25            # envelope follow of source loudness
    formant_shift: float = 0.0            # independent of pitch
    half_precision: bool = True
    auto_pitch_match: bool = True         # auto-estimate semitones to target voice
    reference_clip: str = ""              # seed-vc zero-shot reference wav


@dataclass
class FXConfig:
    enabled: bool = True
    denoise: bool = True
    denoise_strength: float = 0.55
    gate_enabled: bool = True
    gate_threshold_db: float = -48.0
    compressor: bool = True
    comp_threshold_db: float = -20.0
    comp_ratio: float = 3.0
    deesser: bool = True
    eq_low_db: float = 0.0
    eq_mid_db: float = 0.0
    eq_high_db: float = 0.0
    limiter: bool = True
    reverb: float = 0.0
    echo: float = 0.0
    chorus: float = 0.0
    autotune: float = 0.0
    character: str = "none"               # none|robot|telephone|megaphone|monster|alien|cave


@dataclass
class HotkeyConfig:
    enabled: bool = True
    push_to_talk: str = ""
    push_to_mute: str = ""
    toggle_bypass: str = "ctrl+alt+b"
    toggle_mute: str = "ctrl+alt+m"
    next_preset: str = "ctrl+alt+right"
    prev_preset: str = "ctrl+alt+left"
    panic_stop: str = "ctrl+alt+p"


@dataclass
class UpdateConfig:
    check_on_launch: bool = True
    channel: str = "stable"               # stable | ai-nightly
    auto_download: bool = False
    check_interval_hours: int = 6
    last_check_iso: str = ""
    skipped_version: str = ""


@dataclass
class UIConfig:
    theme: str = "dark"
    show_spectrum: bool = True
    show_latency_hud: bool = True
    start_minimized: bool = False
    minimize_to_tray: bool = True
    launch_on_startup: bool = False


@dataclass
class Config:
    schema: int = CONFIG_SCHEMA
    audio: AudioConfig = field(default_factory=AudioConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)
    fx: FXConfig = field(default_factory=FXConfig)
    hotkeys: HotkeyConfig = field(default_factory=HotkeyConfig)
    updates: UpdateConfig = field(default_factory=UpdateConfig)
    ui: UIConfig = field(default_factory=UIConfig)

    # ------------------------------------------------------------------ io
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Config":
        cfg = cls()
        sub = {f.name: f.type for f in fields(cls)}
        for key, value in (raw or {}).items():
            if key == "schema" or key not in sub:
                continue
            section = getattr(cfg, key)
            if not isinstance(value, dict):
                continue
            valid = {f.name for f in fields(section)}
            for k, v in value.items():
                if k in valid:
                    setattr(section, k, v)
        return cfg

    def save(self, path=CONFIG_FILE) -> None:
        """Atomic write - a crash mid-save can never corrupt the config."""
        ensure_dirs()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path=CONFIG_FILE) -> "Config":
        if not path.exists():
            cfg = cls()
            cfg.save(path)
            return cfg
        try:
            return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:  # corrupt file -> quarantine, start clean
            log.warning("Config unreadable (%s); regenerating defaults.", exc)
            try:
                path.replace(path.with_suffix(".json.corrupt"))
            except OSError:
                pass
            cfg = cls()
            cfg.save(path)
            return cfg

    # -------------------------------------------------------------- helpers
    def latency(self) -> Dict[str, float]:
        return LATENCY_PROFILES.get(self.audio.latency_profile, LATENCY_PROFILES["low"])
