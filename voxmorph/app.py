"""Application controller.

Deliberately UI-free: the Qt window, the CLI and any future headless service
all drive this same object. It owns config, engine lifecycle, the audio
pipeline, presets, profiles, hotkeys, the soundboard, recording and updates.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, List, Optional

from . import __version__
from .audio.devices import (default_input, find_virtual_cable,
                            negotiate_samplerate, setup_advice)
from .audio.recorder import Recorder
from .audio.stream import AudioPipeline
from .config import Config
from .engines.base import ConversionParams, EngineError, VoiceEngine
from .engines.registry import create_engine, describe_device
from .hotkeys import HotkeyManager
from .logging_setup import get_logger
from .metrics import Metrics
from .presets.manager import Preset, PresetManager
from .presets.profiles import ProfileStore, VoiceProfile
from .soundboard import Soundboard
from .updater.updater import UpdateInfo, Updater

log = get_logger("app")

Notify = Callable[[str, str], None]  # (level, message)


class VoxMorphApp:
    def __init__(self, cfg: Optional[Config] = None):
        self.cfg = cfg or Config.load()
        self.metrics = Metrics()
        self.presets = PresetManager()
        self.profiles = ProfileStore()
        self.updater = Updater()
        self.hotkeys = HotkeyManager()
        self.soundboard = Soundboard(self.cfg.audio.samplerate)
        self.recorder = Recorder(self.cfg.audio.samplerate)

        self.engine: Optional[VoiceEngine] = None
        self.pipeline: Optional[AudioPipeline] = None
        self.update_info: Optional[UpdateInfo] = None
        self.notify: Optional[Notify] = None
        self.status: str = "Starting up"
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ boot
    def initialise(self) -> None:
        """First-run device selection, engine creation, warmup."""
        self._autoconfigure_devices()
        self._build_engine()
        self._build_pipeline()
        self.apply_hotkeys()
        threading.Thread(target=self._warmup, name="voxmorph-warmup", daemon=True).start()
        if self.cfg.updates.check_on_launch:
            self.check_for_updates_async()

    def _warmup(self) -> None:
        try:
            from .dsp.kernels import warmup
            warmup()
        except Exception:
            pass
        if self.engine:
            self.engine.warmup()
        log.info("Warmup complete")

    def _autoconfigure_devices(self) -> None:
        a = self.cfg.audio
        changed = False
        if a.input_device is None:
            mic = default_input()
            if mic:
                a.input_device = mic.index
                changed = True
                log.info("Input device -> %s", mic.name)
        if a.output_device is None:
            cable = find_virtual_cable()
            if cable:
                a.output_device = cable.index
                changed = True
                log.info("Output device -> %s (virtual cable auto-detected)", cable.name)
            else:
                self._emit("warn", "No virtual audio cable found - install VB-CABLE so "
                                   "other apps can hear your converted voice.")
        sr = negotiate_samplerate(a.input_device, a.output_device, a.samplerate)
        if sr != a.samplerate:
            log.info("Sample rate negotiated to %d Hz", sr)
            a.samplerate = sr
            changed = True
        if changed:
            self.cfg.save()

    def _build_engine(self) -> None:
        self.engine, msg = create_engine(self.cfg)
        self.status = msg
        self.metrics.set_status(engine=self.engine.caps.display_name,
                                device=describe_device(self.cfg.engine.device))
        log.info(msg)
        preset = self.presets.get(self.cfg.engine.preset_id)
        if preset is None:
            preset = self.presets.get("dsp_natural") or self.presets.list()[0]
        self.load_preset(preset.id, restart=False)

    def _build_pipeline(self) -> None:
        assert self.engine is not None
        self.pipeline = AudioPipeline(self.cfg, self.engine, self.metrics)
        self.soundboard.attach(self.pipeline)
        self.pipeline.on_status = lambda m: self._emit("info", m)
        self.pipeline.apply_config()

    def _emit(self, level: str, message: str) -> None:
        self.status = message
        if self.notify:
            try:
                self.notify(level, message)
            except Exception:
                pass

    # --------------------------------------------------------------- presets
    def load_preset(self, preset_id: str, restart: bool = True) -> bool:
        preset = self.presets.get(preset_id)
        if preset is None:
            self._emit("error", f"Unknown preset '{preset_id}'")
            return False

        if preset.needs_download:
            self._emit("warn", f"'{preset.name}' is not installed yet - download it first.")
            return False

        # An identity preset needs a neural engine; a character preset needs DSP.
        wanted = "rvc" if preset.kind == "rvc" else ("seedvc" if preset.kind == "seedvc" else "dsp")
        if self.engine is None or self.engine.caps.name != wanted:
            self.cfg.engine.backend = wanted
            engine, msg = create_engine(self.cfg)
            self.status = msg
            if self.pipeline is not None:
                self.pipeline.swap_engine(engine)
            self.engine = engine

        try:
            self.engine.load(preset)
        except EngineError as exc:
            self._emit("error", f"Could not load '{preset.name}': {exc}")
            return False

        # apply the preset's recommended tuning + its FX defaults
        rec = preset.recommended or {}
        e = self.cfg.engine
        e.preset_id = preset.id
        e.index_rate = float(rec.get("index_rate", e.index_rate))
        e.protect = float(rec.get("protect", e.protect))
        e.f0_method = rec.get("f0_method", e.f0_method)
        for key, value in (preset.fx or {}).items():
            if hasattr(self.cfg.fx, key):
                setattr(self.cfg.fx, key, value)

        params = ConversionParams(
            pitch_shift=e.pitch_shift, formant_shift=e.formant_shift,
            index_rate=e.index_rate, protect=e.protect, rms_mix_rate=e.rms_mix_rate,
            f0_method=e.f0_method, auto_pitch=e.auto_pitch_match,
            target_f0=preset.target_f0,
        )
        self.engine.set_params(params)

        if self.pipeline is not None:
            dsp = preset.dsp or {}
            self.pipeline.apply_config(
                formant_semis=float(dsp.get("formant", 0.0)) if preset.kind == "dsp" else 0.0,
                pitch_semis=0.0,
            )
        self.cfg.save()
        self._emit("info", f"Voice: {preset.name}")
        return True

    def cycle_preset(self, step: int = 1) -> Optional[Preset]:
        items = [p for p in self.presets.list() if p.installed]
        if not items:
            return None
        ids = [p.id for p in items]
        try:
            idx = ids.index(self.cfg.engine.preset_id)
        except ValueError:
            idx = 0
        nxt = items[(idx + step) % len(items)]
        self.load_preset(nxt.id)
        return nxt

    def download_preset(self, preset_id: str,
                        progress: Optional[Callable[[str, float], None]] = None) -> bool:
        return self.presets.download(preset_id, progress)

    # -------------------------------------------------------------- profiles
    def save_profile(self, name: str, notes: str = "") -> Path:
        prof = VoiceProfile.capture(name, self.cfg.engine.preset_id,
                                    self.cfg.engine, self.cfg.fx, notes)
        return self.profiles.save(prof)

    def apply_profile(self, name: str) -> bool:
        prof = self.profiles.load(name)
        if prof is None:
            return False
        prof.apply(self.cfg.engine, self.cfg.fx)
        self.cfg.save()
        ok = self.load_preset(prof.preset_id)
        if self.pipeline:
            self.pipeline.apply_config()
        return ok

    # ------------------------------------------------------------- transport
    def start(self) -> bool:
        if self.pipeline is None:
            self._build_pipeline()
        assert self.pipeline is not None
        ok = self.pipeline.start()
        if ok:
            self._emit("info", "Live")
        return ok

    def stop(self) -> None:
        if self.pipeline:
            self.pipeline.stop()
        self._emit("info", "Stopped")

    def toggle(self) -> bool:
        if self.pipeline and self.pipeline.running:
            self.stop()
            return False
        return self.start()

    @property
    def running(self) -> bool:
        return bool(self.pipeline and self.pipeline.running)

    def toggle_bypass(self) -> bool:
        if self.pipeline:
            self.pipeline.bypass = not self.pipeline.bypass
            self._emit("info", "Bypassed" if self.pipeline.bypass else "Voice active")
            return self.pipeline.bypass
        return False

    def toggle_mute(self) -> bool:
        if self.pipeline:
            self.pipeline.muted = not self.pipeline.muted
            self._emit("info", "Muted" if self.pipeline.muted else "Unmuted")
            return self.pipeline.muted
        return False

    def panic(self) -> None:
        """Immediate silence + stop. Bound to a hotkey for obvious reasons."""
        if self.pipeline:
            self.pipeline.muted = True
        self.soundboard.stop_all()
        self.stop()
        self._emit("warn", "Panic stop - output muted and stream halted.")

    def apply_settings(self, restart_audio: bool = False) -> None:
        self.cfg.save()
        if self.pipeline:
            self.pipeline.apply_config()
            if restart_audio:
                self.pipeline.restart()

    # --------------------------------------------------------------- hotkeys
    def apply_hotkeys(self) -> None:
        actions = {
            "toggle_bypass": self.toggle_bypass,
            "toggle_mute": self.toggle_mute,
            "next_preset": lambda: self.cycle_preset(1),
            "prev_preset": lambda: self.cycle_preset(-1),
            "panic_stop": self.panic,
        }
        ptt = None
        if self.cfg.hotkeys.push_to_talk:
            ptt = (lambda: self._set_ptt(True), lambda: self._set_ptt(False))
            self._set_ptt(False)
        self.hotkeys.apply(self.cfg.hotkeys, actions, ptt)
        for combo, clip_id in self.soundboard.hotkey_map().items():
            self.hotkeys.bind(combo, lambda cid=clip_id: self.soundboard.play(cid))

    def _set_ptt(self, active: bool) -> None:
        if self.pipeline:
            self.pipeline.ptt_active = active

    # -------------------------------------------------------------- recording
    def toggle_recording(self) -> bool:
        if self.recorder.recording:
            path = self.recorder.stop()
            self.recorder.detach(self.pipeline) if self.pipeline else None
            self._emit("info", f"Saved recording: {path.name if path else '?'}")
            return False
        self.recorder.start()
        if self.pipeline:
            self.recorder.attach(self.pipeline)
        self._emit("info", "Recording")
        return True

    # ---------------------------------------------------------------- updates
    def check_for_updates_async(self, force: bool = False) -> None:
        u = self.cfg.updates
        if not force and not self.updater.should_check(u.last_check_iso, u.check_interval_hours):
            log.info("Skipping update check (checked recently).")
            return

        def done(info: Optional[UpdateInfo]) -> None:
            self.cfg.updates.last_check_iso = self.updater.stamp_now()
            self.cfg.save()
            if info and info.version != self.cfg.updates.skipped_version:
                self.update_info = info
                tag = "AI-generated build" if info.ai_generated else "Update"
                self._emit("update", f"{tag} available: v{info.version} "
                                     f"({info.size_mb:.0f} MB)")
            elif not info:
                log.info("No update available (running %s).", __version__)

        self.updater.check_async(u.channel, done)

    def install_update(self, progress: Optional[Callable[[str, float], None]] = None) -> bool:
        if not self.update_info:
            return False
        path = self.updater.download(self.update_info, progress)
        if path is None:
            self._emit("error", self.updater.last_error or "Update download failed.")
            return False
        self.stop()
        return self.updater.install(path)

    def skip_update(self) -> None:
        if self.update_info:
            self.cfg.updates.skipped_version = self.update_info.version
            self.cfg.save()
            self.update_info = None

    # ----------------------------------------------------------------- misc
    def routing_advice(self) -> List[str]:
        return setup_advice()

    def shutdown(self) -> None:
        log.info("Shutting down")
        try:
            self.hotkeys.unbind_all()
        except Exception:
            pass
        if self.recorder.recording:
            self.recorder.stop()
        self.stop()
        if self.engine:
            self.engine.unload()
        self.cfg.save()
        self.updater.cleanup()
