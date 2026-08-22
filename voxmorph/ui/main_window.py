"""Main window.

Layout intent: the two things you touch constantly (the big Start button and
the voice list) are always visible; everything else lives behind tabs.
"""
from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMenu, QMessageBox, QPushButton,
                               QSlider, QSplitter, QSystemTrayIcon, QTabWidget,
                               QVBoxLayout, QWidget)

from .. import __version__
from ..app import VoxMorphApp
from ..audio.devices import input_devices, output_devices
from ..config import LATENCY_PROFILES
from ..logging_setup import get_logger
from ..paths import DATA_DIR, LOG_DIR, MODELS_DIR, RECORDINGS_DIR
from .theme import COLORS, STYLESHEET
from .widgets import Badge, LatencyHUD, SpectrumView, StatCard, UpdateBanner, VUMeter

log = get_logger("ui")


def _slider(lo: int, hi: int, val: int, step: int = 1) -> QSlider:
    s = QSlider(Qt.Horizontal)
    s.setRange(lo, hi)
    s.setValue(val)
    s.setSingleStep(step)
    return s


class MainWindow(QMainWindow):
    notify_signal = Signal(str, str)

    def __init__(self, app: VoxMorphApp):
        super().__init__()
        self.app = app
        self.setWindowTitle(f"VoxMorph {__version__}")
        self.resize(1080, 720)
        self.setMinimumSize(880, 600)
        self.setStyleSheet(STYLESHEET)

        self._building = True
        self._build_ui()
        self._building = False

        self.app.notify = lambda lvl, msg: self.notify_signal.emit(lvl, msg)
        self.notify_signal.connect(self._on_notify)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(50)

        self._refresh_presets()
        self._sync_from_config()

    # ------------------------------------------------------------------ build
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        # ---- update banner -------------------------------------------------
        self.banner = UpdateBanner()
        self.banner.install_clicked.connect(self._install_update)
        self.banner.dismiss_clicked.connect(self._dismiss_update)
        self.banner.notes_clicked.connect(self._show_notes)
        root.addWidget(self.banner)

        # ---- header --------------------------------------------------------
        header = QHBoxLayout()
        title = QLabel("VoxMorph")
        title.setObjectName("h1")
        self.engine_lbl = QLabel("")
        self.engine_lbl.setObjectName("hint")
        self.start_btn = QPushButton("Start")
        self.start_btn.setObjectName("primary")
        self.start_btn.setMinimumWidth(120)
        self.start_btn.clicked.connect(self._toggle_stream)
        self.bypass_btn = QPushButton("Bypass")
        self.bypass_btn.setCheckable(True)
        self.bypass_btn.clicked.connect(lambda: self.app.toggle_bypass())
        self.mute_btn = QPushButton("Mute")
        self.mute_btn.setCheckable(True)
        self.mute_btn.clicked.connect(lambda: self.app.toggle_mute())
        header.addWidget(title)
        header.addWidget(self.engine_lbl)
        header.addStretch(1)
        header.addWidget(self.bypass_btn)
        header.addWidget(self.mute_btn)
        header.addWidget(self.start_btn)
        root.addLayout(header)

        # ---- HUD -----------------------------------------------------------
        self.hud = LatencyHUD()
        root.addWidget(self.hud)

        # ---- body ----------------------------------------------------------
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._build_voice_panel())
        split.addWidget(self._build_tabs())
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 4)
        root.addWidget(split, 1)

        # ---- meters + status ------------------------------------------------
        meters = QGroupBox("Levels")
        ml = QVBoxLayout(meters)
        self.in_meter = VUMeter("IN")
        self.out_meter = VUMeter("OUT")
        self.spectrum = SpectrumView()
        ml.addWidget(self.in_meter)
        ml.addWidget(self.out_meter)
        ml.addWidget(self.spectrum)
        root.addWidget(meters)

        self.status_lbl = QLabel("Ready")
        self.status_lbl.setObjectName("hint")
        root.addWidget(self.status_lbl)

        self._build_tray()

    def _build_voice_panel(self) -> QWidget:
        box = QGroupBox("Voices")
        lay = QVBoxLayout(box)

        filt = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search voices...")
        self.search.textChanged.connect(self._refresh_presets)
        self.cat_filter = QComboBox()
        self.cat_filter.currentIndexChanged.connect(self._refresh_presets)
        filt.addWidget(self.search, 2)
        filt.addWidget(self.cat_filter, 1)
        lay.addLayout(filt)

        self.preset_list = QListWidget()
        self.preset_list.setMinimumHeight(260)   # keep the library scannable
        self.preset_list.itemSelectionChanged.connect(self._on_preset_selected)
        lay.addWidget(self.preset_list, 1)

        self.preset_desc = QLabel("")
        self.preset_desc.setObjectName("hint")
        self.preset_desc.setWordWrap(True)
        self.preset_desc.setMinimumHeight(34)
        lay.addWidget(self.preset_desc)

        btns = QHBoxLayout()
        self.download_btn = QPushButton("Download")
        self.download_btn.clicked.connect(self._download_preset)
        self.download_btn.setVisible(False)
        import_btn = QPushButton("Import .pth")
        import_btn.clicked.connect(self._import_model)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_remote)
        btns.addWidget(self.download_btn)
        btns.addWidget(import_btn)
        btns.addWidget(refresh_btn)
        lay.addLayout(btns)
        return box

    def _build_tabs(self) -> QWidget:
        tabs = QTabWidget()
        tabs.addTab(self._tab_voice(), "Voice")
        tabs.addTab(self._tab_fx(), "Effects")
        tabs.addTab(self._tab_audio(), "Audio")
        tabs.addTab(self._tab_extras(), "Extras")
        tabs.addTab(self._tab_settings(), "Settings")
        return tabs

    # ------------------------------------------------------------------ tabs
    def _tab_voice(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setSpacing(10)

        self.pitch_slider = _slider(-24, 24, 0)
        self.pitch_val = QLabel("0 st")
        self.pitch_slider.valueChanged.connect(self._on_voice_change)
        form.addRow("Pitch", self._with_label(self.pitch_slider, self.pitch_val))

        self.formant_slider = _slider(-12, 12, 0)
        self.formant_val = QLabel("0 st")
        self.formant_slider.valueChanged.connect(self._on_voice_change)
        form.addRow("Formant", self._with_label(self.formant_slider, self.formant_val))

        self.autopitch_chk = QCheckBox("Auto-match pitch to the target voice")
        self.autopitch_chk.setToolTip(
            "Measures your natural pitch and shifts it to the preset's range.\n"
            "This is the single biggest realism factor for identity voices.")
        self.autopitch_chk.stateChanged.connect(self._on_voice_change)
        form.addRow("", self.autopitch_chk)

        self.index_slider = _slider(0, 100, 60)
        self.index_val = QLabel("0.60")
        self.index_slider.valueChanged.connect(self._on_voice_change)
        self.index_slider.setToolTip(
            "How strongly to pull timbre from the model's retrieval index.\n"
            "Too high smears consonants; too low loses the target identity.")
        form.addRow("Timbre strength", self._with_label(self.index_slider, self.index_val))

        self.protect_slider = _slider(0, 50, 33)
        self.protect_val = QLabel("0.33")
        self.protect_slider.valueChanged.connect(self._on_voice_change)
        self.protect_slider.setToolTip("Protects breathy/unvoiced consonants from artefacts.")
        form.addRow("Consonant protect", self._with_label(self.protect_slider, self.protect_val))

        self.f0_combo = QComboBox()
        self.f0_combo.addItems(["rmvpe", "fcpe", "crepe-tiny", "harvest"])
        self.f0_combo.setToolTip("rmvpe = best balance. fcpe = fastest. harvest = slow.")
        self.f0_combo.currentTextChanged.connect(self._on_voice_change)
        form.addRow("Pitch engine", self.f0_combo)

        self.latency_combo = QComboBox()
        for key, prof in LATENCY_PROFILES.items():
            self.latency_combo.addItem(prof["label"], key)
        self.latency_combo.currentIndexChanged.connect(self._on_latency_change)
        form.addRow("Latency profile", self.latency_combo)
        return w

    def _tab_fx(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self.fx_enabled = QCheckBox("Enable effects rack")
        self.fx_enabled.stateChanged.connect(self._on_fx_change)
        form.addRow("", self.fx_enabled)

        self.character_combo = QComboBox()
        self.character_combo.addItems(
            ["none", "robot", "telephone", "megaphone", "monster", "alien", "cave", "radio"])
        self.character_combo.currentTextChanged.connect(self._on_fx_change)
        form.addRow("Character", self.character_combo)

        self.fx_sliders: Dict[str, QSlider] = {}
        self.fx_labels: Dict[str, QLabel] = {}
        for key, label, lo, hi, default in (
            ("denoise_strength", "Noise removal", 0, 100, 55),
            ("reverb", "Reverb", 0, 100, 0),
            ("echo", "Echo", 0, 100, 0),
            ("chorus", "Chorus", 0, 100, 0),
        ):
            s = _slider(lo, hi, default)
            lbl = QLabel("0%")
            s.valueChanged.connect(self._on_fx_change)
            self.fx_sliders[key] = s
            self.fx_labels[key] = lbl
            form.addRow(label, self._with_label(s, lbl))

        for key, label, lo, hi, default in (
            ("eq_low_db", "EQ low", -12, 12, 0),
            ("eq_mid_db", "EQ mid", -12, 12, 0),
            ("eq_high_db", "EQ high", -12, 12, 0),
            ("gate_threshold_db", "Gate threshold", -80, -20, -48),
        ):
            s = _slider(lo, hi, default)
            lbl = QLabel("0 dB")
            s.valueChanged.connect(self._on_fx_change)
            self.fx_sliders[key] = s
            self.fx_labels[key] = lbl
            form.addRow(label, self._with_label(s, lbl))

        row = QHBoxLayout()
        self.comp_chk = QCheckBox("Compressor")
        self.deess_chk = QCheckBox("De-esser")
        self.limit_chk = QCheckBox("Limiter")
        self.gate_chk = QCheckBox("Noise gate")
        for c in (self.comp_chk, self.deess_chk, self.limit_chk, self.gate_chk):
            c.stateChanged.connect(self._on_fx_change)
            row.addWidget(c)
        holder = QWidget()
        holder.setLayout(row)
        form.addRow("Processing", holder)
        return w

    def _tab_audio(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self.in_combo = QComboBox()
        self.out_combo = QComboBox()
        self._populate_devices()
        self.in_combo.currentIndexChanged.connect(self._on_device_change)
        self.out_combo.currentIndexChanged.connect(self._on_device_change)
        form.addRow("Microphone", self.in_combo)
        form.addRow("Output (virtual cable)", self.out_combo)

        self.monitor_chk = QCheckBox("Monitor (hear yourself - use headphones)")
        self.monitor_chk.stateChanged.connect(self._on_device_change)
        form.addRow("", self.monitor_chk)

        self.in_gain = _slider(-24, 24, 0)
        self.in_gain_val = QLabel("0 dB")
        self.in_gain.valueChanged.connect(self._on_fx_change)
        form.addRow("Input gain", self._with_label(self.in_gain, self.in_gain_val))

        self.out_gain = _slider(-24, 24, 0)
        self.out_gain_val = QLabel("0 dB")
        self.out_gain.valueChanged.connect(self._on_fx_change)
        form.addRow("Output gain", self._with_label(self.out_gain, self.out_gain_val))

        self.exclusive_chk = QCheckBox("WASAPI exclusive mode (lowest latency)")
        self.exclusive_chk.stateChanged.connect(self._on_device_change)
        form.addRow("", self.exclusive_chk)

        advice = QLabel("\n".join("- " + t for t in self.app.routing_advice()))
        advice.setObjectName("hint")
        advice.setWordWrap(True)
        form.addRow("Routing", advice)
        return w

    def _tab_extras(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        rec = QGroupBox("Recording")
        rl = QHBoxLayout(rec)
        self.record_btn = QPushButton("Start recording")
        self.record_btn.clicked.connect(self._toggle_record)
        open_rec = QPushButton("Open folder")
        open_rec.clicked.connect(lambda: self._open_folder(RECORDINGS_DIR))
        self.record_lbl = QLabel("Captures the original and converted voice separately.")
        self.record_lbl.setObjectName("hint")
        rl.addWidget(self.record_btn)
        rl.addWidget(open_rec)
        rl.addWidget(self.record_lbl, 1)
        lay.addWidget(rec)

        sb = QGroupBox("Soundboard")
        sl = QVBoxLayout(sb)
        self.sb_list = QListWidget()
        self.sb_list.itemDoubleClicked.connect(
            lambda it: self.app.soundboard.play(it.data(Qt.UserRole)))
        sl.addWidget(self.sb_list)
        sbb = QHBoxLayout()
        add_clip = QPushButton("Add clip")
        add_clip.clicked.connect(self._add_clip)
        play_clip = QPushButton("Play")
        play_clip.clicked.connect(self._play_clip)
        stop_clips = QPushButton("Stop all")
        stop_clips.clicked.connect(lambda: self.app.soundboard.stop_all())
        for b in (add_clip, play_clip, stop_clips):
            sbb.addWidget(b)
        sl.addLayout(sbb)
        lay.addWidget(sb)

        prof = QGroupBox("Profiles")
        pl = QHBoxLayout(prof)
        self.profile_combo = QComboBox()
        save_p = QPushButton("Save current")
        save_p.clicked.connect(self._save_profile)
        load_p = QPushButton("Load")
        load_p.clicked.connect(self._load_profile)
        pl.addWidget(self.profile_combo, 1)
        pl.addWidget(save_p)
        pl.addWidget(load_p)
        lay.addWidget(prof)
        self._refresh_profiles()
        self._refresh_clips()
        lay.addStretch(1)
        return w

    def _tab_settings(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self.update_chk = QCheckBox("Check for updates on launch")
        self.update_chk.stateChanged.connect(self._on_settings_change)
        form.addRow("", self.update_chk)

        self.channel_combo = QComboBox()
        self.channel_combo.addItem("Stable", "stable")
        self.channel_combo.addItem("AI nightly (includes automated builds)", "ai-nightly")
        self.channel_combo.currentIndexChanged.connect(self._on_settings_change)
        form.addRow("Update channel", self.channel_combo)

        check_btn = QPushButton("Check for updates now")
        check_btn.clicked.connect(lambda: self.app.check_for_updates_async(force=True))
        form.addRow("", check_btn)

        self.version_lbl = QLabel(f"Installed version: {__version__}")
        self.version_lbl.setObjectName("hint")
        form.addRow("", self.version_lbl)

        self.tray_chk = QCheckBox("Minimise to system tray")
        self.tray_chk.stateChanged.connect(self._on_settings_change)
        form.addRow("", self.tray_chk)

        self.device_combo = QComboBox()
        self.device_combo.addItems(["auto", "cuda", "directml", "cpu"])
        self.device_combo.currentTextChanged.connect(self._on_settings_change)
        form.addRow("Compute device", self.device_combo)

        hk = QGroupBox("Global hotkeys")
        hkf = QFormLayout(hk)
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
            le.editingFinished.connect(self._on_hotkey_change)
            self.hotkey_fields[field] = le
            hkf.addRow(label, le)
        if not self.app.hotkeys.enabled:
            note = QLabel("Global hotkeys unavailable (install the `keyboard` package "
                          "and run as administrator).")
            note.setObjectName("hint")
            note.setWordWrap(True)
            hkf.addRow("", note)
        form.addRow(hk)

        folders = QHBoxLayout()
        for label, path in (("Data folder", DATA_DIR), ("Models", MODELS_DIR),
                            ("Logs", LOG_DIR)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, p=path: self._open_folder(p))
            folders.addWidget(b)
        holder = QWidget()
        holder.setLayout(folders)
        form.addRow("Open", holder)
        return w

    @staticmethod
    def _with_label(widget: QWidget, label: QLabel) -> QWidget:
        holder = QWidget()
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        label.setMinimumWidth(52)
        label.setObjectName("stat")
        lay.addWidget(widget, 1)
        lay.addWidget(label)
        return holder

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self.windowIcon() or QIcon())
        menu = QMenu()
        act_show = QAction("Show VoxMorph", self)
        act_show.triggered.connect(self.showNormal)
        act_toggle = QAction("Start / Stop", self)
        act_toggle.triggered.connect(self._toggle_stream)
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self.close)
        for a in (act_show, act_toggle, act_quit):
            menu.addAction(a)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self.showNormal() if r == QSystemTrayIcon.DoubleClick else None)

    # -------------------------------------------------------------- presets
    def _refresh_presets(self) -> None:
        if self._building:
            return
        term = self.search.text().lower().strip()
        cat = self.cat_filter.currentText() if self.cat_filter.count() else "All"

        if self.cat_filter.count() == 0:
            self.cat_filter.addItem("All")
            self.cat_filter.addItems(self.app.presets.categories())

        self.preset_list.clear()
        for p in self.app.presets.list():
            if term and term not in p.name.lower() and term not in p.description.lower():
                continue
            if cat not in ("All", "") and p.category != cat:
                continue
            label = p.name
            if p.is_identity:
                label += "   [identity]"
            if p.needs_download:
                label += f"   (download {p.size_mb:.0f} MB)"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, p.id)
            if p.needs_download:
                item.setForeground(Qt.gray)
            if p.id == self.app.cfg.engine.preset_id:
                item.setSelected(True)
            self.preset_list.addItem(item)

    def _selected_preset_id(self) -> Optional[str]:
        items = self.preset_list.selectedItems()
        return items[0].data(Qt.UserRole) if items else None

    def _on_preset_selected(self) -> None:
        pid = self._selected_preset_id()
        if not pid:
            return
        p = self.app.presets.get(pid)
        if p is None:
            return
        kind = ("Identity voice - everyone who speaks sounds like this person."
                if p.is_identity else
                "Character preset - transforms your own voice.")
        self.preset_desc.setText(f"{p.description}\n{kind}")
        self.download_btn.setVisible(p.needs_download)
        if not p.needs_download and pid != self.app.cfg.engine.preset_id:
            self.app.load_preset(pid)

    def _download_preset(self) -> None:
        pid = self._selected_preset_id()
        if not pid:
            return
        self.status_lbl.setText("Downloading model...")
        ok = self.app.download_preset(
            pid, lambda m, f: self.status_lbl.setText(f"{m} {f * 100:.0f}%"))
        if ok:
            self.app.presets.load_all()
            self._refresh_presets()
            self.app.load_preset(pid)
        else:
            QMessageBox.warning(self, "Download failed",
                                "Could not download or verify this voice model. "
                                "See the log for details.")

    def _import_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import RVC model", "",
                                              "RVC model (*.pth)")
        if not path:
            return
        p = self.app.presets.import_model(Path(path))
        self._refresh_presets()
        if p:
            QMessageBox.information(self, "Imported",
                                    f"'{p.name}' is ready to use.")

    def _refresh_remote(self) -> None:
        n = self.app.presets.refresh_remote()
        self.app.presets.load_all()
        self._refresh_presets()
        self.status_lbl.setText(f"Catalog refreshed ({n} new voice(s))")

    # -------------------------------------------------------------- handlers
    def _toggle_stream(self) -> None:
        running = self.app.toggle()
        self.start_btn.setText("Stop" if running else "Start")

    def _on_voice_change(self) -> None:
        if self._building:
            return
        e = self.app.cfg.engine
        e.pitch_shift = self.pitch_slider.value()
        e.formant_shift = self.formant_slider.value()
        e.auto_pitch_match = self.autopitch_chk.isChecked()
        e.index_rate = self.index_slider.value() / 100.0
        e.protect = self.protect_slider.value() / 100.0
        e.f0_method = self.f0_combo.currentText()
        self.pitch_val.setText(f"{e.pitch_shift:+d} st")
        self.formant_val.setText(f"{e.formant_shift:+.0f} st")
        self.index_val.setText(f"{e.index_rate:.2f}")
        self.protect_val.setText(f"{e.protect:.2f}")
        self.app.apply_settings()

    def _on_fx_change(self) -> None:
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
        self.app.cfg.audio.input_gain_db = self.in_gain.value()
        self.app.cfg.audio.output_gain_db = self.out_gain.value()

        for key in ("denoise_strength", "reverb", "echo", "chorus"):
            self.fx_labels[key].setText(f"{self.fx_sliders[key].value()}%")
        for key in ("eq_low_db", "eq_mid_db", "eq_high_db", "gate_threshold_db"):
            self.fx_labels[key].setText(f"{self.fx_sliders[key].value():+d} dB")
        self.in_gain_val.setText(f"{self.in_gain.value():+d} dB")
        self.out_gain_val.setText(f"{self.out_gain.value():+d} dB")
        self.app.apply_settings()

    def _on_latency_change(self) -> None:
        if self._building:
            return
        self.app.cfg.audio.latency_profile = self.latency_combo.currentData()
        self.app.apply_settings(restart_audio=True)

    def _on_device_change(self) -> None:
        if self._building:
            return
        a = self.app.cfg.audio
        a.input_device = self.in_combo.currentData()
        a.output_device = self.out_combo.currentData()
        a.exclusive_wasapi = self.exclusive_chk.isChecked()
        if self.app.pipeline:
            self.app.pipeline.monitor_enabled = self.monitor_chk.isChecked()
        self.app.apply_settings(restart_audio=True)

    def _on_settings_change(self) -> None:
        if self._building:
            return
        u = self.app.cfg.updates
        u.check_on_launch = self.update_chk.isChecked()
        u.channel = self.channel_combo.currentData()
        self.app.cfg.ui.minimize_to_tray = self.tray_chk.isChecked()
        new_device = self.device_combo.currentText()
        changed = new_device != self.app.cfg.engine.device
        self.app.cfg.engine.device = new_device
        self.app.cfg.save()
        if changed:
            QMessageBox.information(self, "Restart required",
                                    "Restart VoxMorph to switch compute device.")

    def _on_hotkey_change(self) -> None:
        if self._building:
            return
        for field, le in self.hotkey_fields.items():
            setattr(self.app.cfg.hotkeys, field, le.text().strip())
        self.app.cfg.save()
        self.app.apply_hotkeys()

    # --------------------------------------------------------------- extras
    def _toggle_record(self) -> None:
        on = self.app.toggle_recording()
        self.record_btn.setText("Stop recording" if on else "Start recording")

    def _add_clip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Add sound clip", "", "Audio (*.wav *.mp3 *.ogg *.flac)")
        if path:
            self.app.soundboard.add(Path(path))
            self._refresh_clips()

    def _play_clip(self) -> None:
        it = self.sb_list.currentItem()
        if it:
            self.app.soundboard.play(it.data(Qt.UserRole))

    def _refresh_clips(self) -> None:
        self.sb_list.clear()
        for clip in self.app.soundboard.clips.values():
            item = QListWidgetItem(clip.name + (f"   [{clip.hotkey}]" if clip.hotkey else ""))
            item.setData(Qt.UserRole, clip.id)
            self.sb_list.addItem(item)

    def _save_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "Save profile", "Profile name:")
        if ok and name.strip():
            self.app.save_profile(name.strip())
            self._refresh_profiles()

    def _load_profile(self) -> None:
        name = self.profile_combo.currentText()
        if name and self.app.apply_profile(name):
            self._sync_from_config()
            self._refresh_presets()

    def _refresh_profiles(self) -> None:
        self.profile_combo.clear()
        self.profile_combo.addItems([p.name for p in self.app.profiles.list()])

    @staticmethod
    def _open_folder(path: Path) -> None:
        try:
            webbrowser.open(path.as_uri())
        except Exception:
            pass

    # --------------------------------------------------------------- updates
    def _install_update(self) -> None:
        info = self.app.update_info
        if not info:
            return
        ok = self.app.install_update(
            lambda m, f: self.banner.set_progress(f, f"{m} {f * 100:.0f}%"))
        if ok:
            self.close()
        else:
            QMessageBox.warning(self, "Update failed",
                                self.app.updater.last_error or "Could not install the update.")
            self.banner.install_btn.setEnabled(True)

    def _dismiss_update(self) -> None:
        self.app.skip_update()
        self.banner.setVisible(False)

    def _show_notes(self) -> None:
        info = self.app.update_info
        if not info:
            return
        if info.html_url:
            webbrowser.open(info.html_url)
        else:
            QMessageBox.information(self, f"VoxMorph v{info.version}", info.short_notes)

    # ------------------------------------------------------------------ sync
    def _populate_devices(self) -> None:
        self.in_combo.clear()
        for d in input_devices():
            self.in_combo.addItem(d.label, d.index)
        self.out_combo.clear()
        for d in output_devices():
            self.out_combo.addItem(d.label, d.index)

    def _sync_from_config(self) -> None:
        self._building = True
        c = self.app.cfg
        self.pitch_slider.setValue(int(c.engine.pitch_shift))
        self.formant_slider.setValue(int(c.engine.formant_shift))
        self.autopitch_chk.setChecked(c.engine.auto_pitch_match)
        self.index_slider.setValue(int(c.engine.index_rate * 100))
        self.protect_slider.setValue(int(c.engine.protect * 100))
        self.f0_combo.setCurrentText(c.engine.f0_method)
        idx = self.latency_combo.findData(c.audio.latency_profile)
        self.latency_combo.setCurrentIndex(max(0, idx))

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

        if c.audio.input_device is not None:
            i = self.in_combo.findData(c.audio.input_device)
            if i >= 0:
                self.in_combo.setCurrentIndex(i)
        if c.audio.output_device is not None:
            i = self.out_combo.findData(c.audio.output_device)
            if i >= 0:
                self.out_combo.setCurrentIndex(i)
        self.in_gain.setValue(int(c.audio.input_gain_db))
        self.out_gain.setValue(int(c.audio.output_gain_db))
        self.exclusive_chk.setChecked(c.audio.exclusive_wasapi)

        self.update_chk.setChecked(c.updates.check_on_launch)
        i = self.channel_combo.findData(c.updates.channel)
        self.channel_combo.setCurrentIndex(max(0, i))
        self.tray_chk.setChecked(c.ui.minimize_to_tray)
        self.device_combo.setCurrentText(c.engine.device)
        for field, le in self.hotkey_fields.items():
            le.setText(getattr(c.hotkeys, field, ""))
        self._building = False
        self._on_fx_change()

    def _tick(self) -> None:
        s = self.app.metrics.get()
        self.in_meter.set_level(s.input_rms_db, s.input_peak_db)
        self.out_meter.set_level(s.output_rms_db, s.output_peak_db)
        if s.spectrum:
            self.spectrum.set_values(s.spectrum)
        self.hud.update_from(s)
        self.engine_lbl.setText(f"{s.engine}  -  {s.device}")
        self.start_btn.setText("Stop" if self.app.running else "Start")
        if self.app.pipeline:
            self.bypass_btn.setChecked(self.app.pipeline.bypass)
            self.mute_btn.setChecked(self.app.pipeline.muted)
        if self.app.recorder.recording:
            self.record_lbl.setText(f"Recording... {self.app.recorder.duration_s:.1f}s")

    def _on_notify(self, level: str, message: str) -> None:
        colors = {"error": COLORS["bad"], "warn": COLORS["warn"],
                  "update": COLORS["update"]}
        self.status_lbl.setStyleSheet(f"color:{colors.get(level, COLORS['text_dim'])};")
        self.status_lbl.setText(message)
        if level == "update" and self.app.update_info:
            self.banner.show_update(self.app.update_info)

    # ------------------------------------------------------------------ close
    def closeEvent(self, event) -> None:
        if self.app.cfg.ui.minimize_to_tray and self.isVisible() and not self._quitting():
            pass
        self.timer.stop()
        self.app.shutdown()
        event.accept()

    @staticmethod
    def _quitting() -> bool:
        return True
