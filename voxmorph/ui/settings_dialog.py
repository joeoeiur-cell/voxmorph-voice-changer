"""Settings dialog.

Everything that is not "pick a voice and turn it on" lives here, so the main
window can stay a single uncluttered screen.
"""
from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QSlider,
                               QTabWidget, QVBoxLayout, QWidget)

from .. import __version__
from ..audio.devices import input_devices, output_devices
from ..config import LATENCY_PROFILES
from ..paths import DATA_DIR, LOG_DIR, MODELS_DIR, RECORDINGS_DIR
from .theme import COLORS


def _slider(lo: int, hi: int, val: int) -> QSlider:
    s = QSlider(Qt.Horizontal)
    s.setRange(lo, hi)
    s.setValue(val)
    return s


class SettingsDialog(QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self._building = True
        self.setWindowTitle("VoxMorph Settings")
        self.setMinimumSize(620, 560)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        tabs = QTabWidget()
        tabs.addTab(self._tab_audio(), "Audio")
        tabs.addTab(self._tab_effects(), "Effects")
        tabs.addTab(self._tab_hotkeys(), "Hotkeys")
        tabs.addTab(self._tab_about(), "Updates")
        root.addWidget(tabs, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("Done")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        root.addLayout(row)

        self._building = False
        self._sync()

    # ------------------------------------------------------------------ tabs
    def _tab_audio(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setSpacing(10)

        self.in_combo = QComboBox()
        self.out_combo = QComboBox()
        self.mon_combo = QComboBox()
        for d in input_devices():
            self.in_combo.addItem(d.label, d.index)
        for d in output_devices():
            self.out_combo.addItem(d.label, d.index)
            self.mon_combo.addItem(d.label, d.index)
        for c in (self.in_combo, self.out_combo, self.mon_combo):
            c.currentIndexChanged.connect(self._devices_changed)

        form.addRow("Microphone", self.in_combo)
        form.addRow("Output (virtual cable)", self.out_combo)
        form.addRow("Monitor (your headphones)", self.mon_combo)

        self.mon_vol = _slider(-40, 6, -6)
        self.mon_vol_lbl = QLabel("-6 dB")
        self.mon_vol.valueChanged.connect(self._gains_changed)
        form.addRow("Monitor volume", self._with(self.mon_vol, self.mon_vol_lbl))

        self.latency_combo = QComboBox()
        for key, prof in LATENCY_PROFILES.items():
            self.latency_combo.addItem(prof["label"], key)
        self.latency_combo.currentIndexChanged.connect(self._devices_changed)
        form.addRow("Latency profile", self.latency_combo)

        self.in_gain = _slider(-24, 24, 0)
        self.in_gain_lbl = QLabel("0 dB")
        self.in_gain.valueChanged.connect(self._gains_changed)
        form.addRow("Input gain", self._with(self.in_gain, self.in_gain_lbl))

        self.out_gain = _slider(-24, 24, 0)
        self.out_gain_lbl = QLabel("0 dB")
        self.out_gain.valueChanged.connect(self._gains_changed)
        form.addRow("Output gain", self._with(self.out_gain, self.out_gain_lbl))

        self.exclusive_chk = QCheckBox("WASAPI exclusive mode (lowest latency)")
        self.exclusive_chk.stateChanged.connect(self._devices_changed)
        form.addRow("", self.exclusive_chk)

        advice = QLabel("\n".join("• " + t for t in self.app.routing_advice()))
        advice.setObjectName("hint")
        advice.setWordWrap(True)
        form.addRow("Routing", advice)
        return w

    def _tab_effects(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self.fx_enabled = QCheckBox("Enable the effects rack")
        self.fx_enabled.stateChanged.connect(self._fx_changed)
        form.addRow("", self.fx_enabled)

        self.character_combo = QComboBox()
        self.character_combo.addItems(
            ["none", "robot", "telephone", "megaphone", "monster", "alien", "cave", "radio"])
        self.character_combo.currentTextChanged.connect(self._fx_changed)
        form.addRow("Character", self.character_combo)

        self.fx_sliders: Dict[str, QSlider] = {}
        self.fx_labels: Dict[str, QLabel] = {}
        for key, label, lo, hi, dv, suf in (
            ("denoise_strength", "Noise removal", 0, 100, 55, "%"),
            ("reverb", "Reverb", 0, 100, 0, "%"),
            ("echo", "Echo", 0, 100, 0, "%"),
            ("chorus", "Chorus", 0, 100, 0, "%"),
            ("eq_low_db", "EQ low", -12, 12, 0, " dB"),
            ("eq_mid_db", "EQ mid", -12, 12, 0, " dB"),
            ("eq_high_db", "EQ high", -12, 12, 0, " dB"),
            ("gate_threshold_db", "Gate threshold", -80, -20, -48, " dB"),
        ):
            s = _slider(lo, hi, dv)
            lbl = QLabel(f"{dv}{suf}")
            s.valueChanged.connect(self._fx_changed)
            self.fx_sliders[key] = s
            self.fx_labels[key] = lbl
            form.addRow(label, self._with(s, lbl))

        row = QHBoxLayout()
        self.comp_chk = QCheckBox("Compressor")
        self.deess_chk = QCheckBox("De-esser")
        self.limit_chk = QCheckBox("Limiter")
        self.gate_chk = QCheckBox("Noise gate")
        for c in (self.comp_chk, self.deess_chk, self.limit_chk, self.gate_chk):
            c.stateChanged.connect(self._fx_changed)
            row.addWidget(c)
        holder = QWidget()
        holder.setLayout(row)
        form.addRow("Processing", holder)
        return w

    def _tab_hotkeys(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.hotkey_fields: Dict[str, QLineEdit] = {}
        for field, label in (
            ("push_to_talk", "Push to talk"),
            ("toggle_mute", "Mute"),
            ("toggle_bypass", "Bypass"),
            ("next_preset", "Next voice"),
            ("prev_preset", "Previous voice"),
            ("panic_stop", "Panic stop"),
        ):
            le = QLineEdit()
            le.setPlaceholderText("e.g. ctrl+alt+m")
            le.editingFinished.connect(self._hotkeys_changed)
            self.hotkey_fields[field] = le
            form.addRow(label, le)

        if not self.app.hotkeys.enabled:
            note = QLabel("Global hotkeys are unavailable. Install the `keyboard` "
                          "package and run VoxMorph as administrator.")
            note.setObjectName("hint")
            note.setWordWrap(True)
            form.addRow("", note)
        return w

    def _tab_about(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self.update_chk = QCheckBox("Check for updates on launch")
        self.update_chk.stateChanged.connect(self._settings_changed)
        form.addRow("", self.update_chk)

        self.channel_combo = QComboBox()
        self.channel_combo.addItem("Stable", "stable")
        self.channel_combo.addItem("AI nightly (automated builds)", "ai-nightly")
        self.channel_combo.currentIndexChanged.connect(self._settings_changed)
        form.addRow("Update channel", self.channel_combo)

        btn = QPushButton("Check now")
        btn.clicked.connect(lambda: self.app.check_for_updates_async(force=True))
        form.addRow("", btn)

        self.device_combo = QComboBox()
        self.device_combo.addItems(["auto", "cuda", "directml", "cpu"])
        self.device_combo.currentTextChanged.connect(self._settings_changed)
        form.addRow("Compute device", self.device_combo)

        self.tray_chk = QCheckBox("Minimise to the system tray")
        self.tray_chk.stateChanged.connect(self._settings_changed)
        form.addRow("", self.tray_chk)

        folders = QHBoxLayout()
        for label, path in (("Data", DATA_DIR), ("Models", MODELS_DIR),
                            ("Recordings", RECORDINGS_DIR), ("Logs", LOG_DIR)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, p=path: self._open(p))
            folders.addWidget(b)
        holder = QWidget()
        holder.setLayout(folders)
        form.addRow("Open folder", holder)

        ver = QLabel(f"VoxMorph {__version__}")
        ver.setObjectName("hint")
        form.addRow("", ver)
        return w

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _with(widget, label) -> QWidget:
        holder = QWidget()
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        label.setMinimumWidth(56)
        label.setObjectName("stat")
        lay.addWidget(widget, 1)
        lay.addWidget(label)
        return holder

    @staticmethod
    def _open(path: Path) -> None:
        try:
            webbrowser.open(Path(path).as_uri())
        except Exception:
            pass

    # -------------------------------------------------------------- handlers
    def _devices_changed(self) -> None:
        if self._building:
            return
        a = self.app.cfg.audio
        a.input_device = self.in_combo.currentData()
        a.output_device = self.out_combo.currentData()
        a.monitor_device = self.mon_combo.currentData()
        a.exclusive_wasapi = self.exclusive_chk.isChecked()
        a.latency_profile = self.latency_combo.currentData()
        self.app.apply_settings(restart_audio=True)

    def _gains_changed(self) -> None:
        if self._building:
            return
        a = self.app.cfg.audio
        a.input_gain_db = self.in_gain.value()
        a.output_gain_db = self.out_gain.value()
        a.monitor_volume_db = self.mon_vol.value()
        self.in_gain_lbl.setText(f"{a.input_gain_db:+d} dB")
        self.out_gain_lbl.setText(f"{a.output_gain_db:+d} dB")
        self.mon_vol_lbl.setText(f"{a.monitor_volume_db:+d} dB")
        self.app.apply_settings()

    def _fx_changed(self) -> None:
        if self._building:
            return
        fx = self.app.cfg.fx
        fx.enabled = self.fx_enabled.isChecked()
        fx.character = self.character_combo.currentText()
        fx.denoise_strength = self.fx_sliders["denoise_strength"].value() / 100.0
        fx.denoise = fx.denoise_strength > 0.01
        fx.reverb = self.fx_sliders["reverb"].value() / 100.0
        fx.echo = self.fx_sliders["echo"].value() / 100.0
        fx.chorus = self.fx_sliders["chorus"].value() / 100.0
        fx.eq_low_db = self.fx_sliders["eq_low_db"].value()
        fx.eq_mid_db = self.fx_sliders["eq_mid_db"].value()
        fx.eq_high_db = self.fx_sliders["eq_high_db"].value()
        fx.gate_threshold_db = self.fx_sliders["gate_threshold_db"].value()
        fx.compressor = self.comp_chk.isChecked()
        fx.deesser = self.deess_chk.isChecked()
        fx.limiter = self.limit_chk.isChecked()
        fx.gate_enabled = self.gate_chk.isChecked()
        for k in ("denoise_strength", "reverb", "echo", "chorus"):
            self.fx_labels[k].setText(f"{self.fx_sliders[k].value()}%")
        for k in ("eq_low_db", "eq_mid_db", "eq_high_db", "gate_threshold_db"):
            self.fx_labels[k].setText(f"{self.fx_sliders[k].value():+d} dB")
        self.app.apply_settings()

    def _hotkeys_changed(self) -> None:
        if self._building:
            return
        for field, le in self.hotkey_fields.items():
            setattr(self.app.cfg.hotkeys, field, le.text().strip())
        self.app.cfg.save()
        self.app.apply_hotkeys()

    def _settings_changed(self) -> None:
        if self._building:
            return
        u = self.app.cfg.updates
        u.check_on_launch = self.update_chk.isChecked()
        u.channel = self.channel_combo.currentData()
        self.app.cfg.ui.minimize_to_tray = self.tray_chk.isChecked()
        new_dev = self.device_combo.currentText()
        changed = new_dev != self.app.cfg.engine.device
        self.app.cfg.engine.device = new_dev
        self.app.cfg.save()
        if changed:
            QMessageBox.information(self, "Restart required",
                                    "Restart VoxMorph to switch compute device.")

    # ------------------------------------------------------------------ sync
    def _sync(self) -> None:
        self._building = True
        c = self.app.cfg
        for combo, val in ((self.in_combo, c.audio.input_device),
                           (self.out_combo, c.audio.output_device),
                           (self.mon_combo, c.audio.monitor_device)):
            if val is not None:
                i = combo.findData(val)
                if i >= 0:
                    combo.setCurrentIndex(i)
        i = self.latency_combo.findData(c.audio.latency_profile)
        self.latency_combo.setCurrentIndex(max(0, i))
        self.in_gain.setValue(int(c.audio.input_gain_db))
        self.out_gain.setValue(int(c.audio.output_gain_db))
        self.mon_vol.setValue(int(c.audio.monitor_volume_db))
        self.exclusive_chk.setChecked(c.audio.exclusive_wasapi)

        self.fx_enabled.setChecked(c.fx.enabled)
        self.character_combo.setCurrentText(c.fx.character)
        self.fx_sliders["denoise_strength"].setValue(int(c.fx.denoise_strength * 100))
        self.fx_sliders["reverb"].setValue(int(c.fx.reverb * 100))
        self.fx_sliders["echo"].setValue(int(c.fx.echo * 100))
        self.fx_sliders["chorus"].setValue(int(c.fx.chorus * 100))
        self.fx_sliders["eq_low_db"].setValue(int(c.fx.eq_low_db))
        self.fx_sliders["eq_mid_db"].setValue(int(c.fx.eq_mid_db))
        self.fx_sliders["eq_high_db"].setValue(int(c.fx.eq_high_db))
        self.fx_sliders["gate_threshold_db"].setValue(int(c.fx.gate_threshold_db))
        self.comp_chk.setChecked(c.fx.compressor)
        self.deess_chk.setChecked(c.fx.deesser)
        self.limit_chk.setChecked(c.fx.limiter)
        self.gate_chk.setChecked(c.fx.gate_enabled)

        self.update_chk.setChecked(c.updates.check_on_launch)
        i = self.channel_combo.findData(c.updates.channel)
        self.channel_combo.setCurrentIndex(max(0, i))
        self.tray_chk.setChecked(c.ui.minimize_to_tray)
        self.device_combo.setCurrentText(c.engine.device)
        for field, le in self.hotkey_fields.items():
            le.setText(getattr(c.hotkeys, field, ""))
        self._building = False
