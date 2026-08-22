"""Main window.

Deliberately one screen. The two things you touch constantly - the power
switch and the voice you want - are always visible and large. Everything
else lives behind the gear icon.
"""
from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QMainWindow, QMenu, QMessageBox, QPushButton,
                               QScrollArea, QSystemTrayIcon, QVBoxLayout, QWidget)

from .. import __version__
from ..app import VoxMorphApp
from ..logging_setup import get_logger
from .settings_dialog import SettingsDialog
from .theme import COLORS, STYLESHEET
from .widgets import (IconButton, LatencyHUD, QuickSlider, SpectrumView,
                      ToggleSwitch, UpdateBanner, VUMeter, VoiceTile)

log = get_logger("ui")

TILE_MIN_WIDTH = 228


class MainWindow(QMainWindow):
    notify_signal = Signal(str, str)

    def __init__(self, app: VoxMorphApp):
        super().__init__()
        self.app = app
        self.setWindowTitle("VoxMorph")
        self.resize(940, 680)
        self.setMinimumSize(720, 560)
        self.setStyleSheet(STYLESHEET)

        self._building = True
        self._tiles: List[VoiceTile] = []
        self._category = "All"
        self._columns = 0
        self._build_ui()
        self._building = False

        self.app.notify = lambda lvl, msg: self.notify_signal.emit(lvl, msg)
        self.notify_signal.connect(self._on_notify)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(50)

        self._rebuild_tiles()
        self._sync()
        # viewport width is only final once the window has been laid out, so
        # settle the column count on the next tick
        QTimer.singleShot(0, self._rebuild_tiles)

    # ------------------------------------------------------------------ build
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.banner = UpdateBanner()
        self.banner.install_clicked.connect(self._install_update)
        self.banner.dismiss_clicked.connect(self._dismiss_update)
        self.banner.notes_clicked.connect(self._show_notes)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(14, 10, 14, 0)
        wl.addWidget(self.banner)
        root.addWidget(wrap)

        root.addWidget(self._header())
        root.addWidget(self._filters())
        root.addWidget(self._voice_area(), 1)
        root.addWidget(self._footer())
        self._build_tray()

    def _header(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("header")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(12)

        mark = QLabel("\u25c9")
        mark.setStyleSheet(f"color:{COLORS['accent']};font-size:19px;")
        title = QLabel("VoxMorph")
        title.setObjectName("brand")
        lay.addWidget(mark)
        lay.addWidget(title)
        lay.addSpacing(8)

        self.now_playing = QLabel("")
        self.now_playing.setObjectName("hint")
        lay.addWidget(self.now_playing)
        lay.addStretch(1)

        self.power = ToggleSwitch()
        self.power.toggled.connect(self._on_power)
        lay.addWidget(self.power)

        self.monitor_btn = IconButton("\u25d1", "Hear yourself (use headphones)")
        self.monitor_btn.clicked.connect(self._on_monitor)
        self.mute_btn = IconButton("\u2298", "Mute output")
        self.mute_btn.clicked.connect(lambda: self.app.toggle_mute())
        self.record_btn = IconButton("\u25cf", "Record")
        self.record_btn.clicked.connect(self._toggle_record)
        self.settings_btn = IconButton("\u2699", "Settings", checkable=False)
        self.settings_btn.clicked.connect(self._open_settings)
        for b in (self.monitor_btn, self.mute_btn, self.record_btn, self.settings_btn):
            lay.addWidget(b)
        return bar

    def _filters(self) -> QWidget:
        bar = QWidget()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 12, 16, 8)
        lay.setSpacing(8)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search voices\u2026")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(230)
        self.search.textChanged.connect(self._rebuild_tiles)
        lay.addWidget(self.search)

        self.chip_group = QButtonGroup(self)
        self.chip_group.setExclusive(True)
        self._chip_row = QHBoxLayout()
        self._chip_row.setSpacing(6)
        self._chip_cats: List[str] = []
        lay.addLayout(self._chip_row)
        lay.addStretch(1)

        imp = QPushButton("Import .pth")
        imp.clicked.connect(self._import_model)
        lay.addWidget(imp)
        return bar

    @staticmethod
    def _clear_layout(layout, group=None) -> None:
        """Detach and destroy every child widget.

        deleteLater() alone is not enough here: the widget stays parented and
        keeps painting until the event loop runs, and any QButtonGroup keeps
        its own reference. Rebuilding on every resize therefore stacked the
        category chips on top of each other.
        """
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                if group is not None:
                    group.removeButton(w)
                w.setParent(None)
                w.deleteLater()

    def _rebuild_chips(self) -> None:
        cats = ["All"] + self.app.presets.categories()
        if cats == self._chip_cats:
            # nothing changed - just refresh which one is lit
            for b in self.chip_group.buttons():
                b.setChecked(b.text() == self._category)
            return
        self._chip_cats = cats
        self._clear_layout(self._chip_row, self.chip_group)
        for cat in cats:
            b = QPushButton(cat)
            b.setCheckable(True)
            b.setObjectName("chipBtn")
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(cat == self._category)
            b.clicked.connect(lambda _=False, c=cat: self._set_category(c))
            self.chip_group.addButton(b)
            self._chip_row.addWidget(b)

    def _set_category(self, cat: str) -> None:
        self._category = cat
        self._rebuild_tiles()

    def _voice_area(self) -> QWidget:
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        holder = QWidget()
        self.grid = QGridLayout(holder)
        self.grid.setContentsMargins(16, 4, 16, 16)
        self.grid.setSpacing(10)
        self.grid.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(holder)
        return self.scroll

    def _footer(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("footer")
        lay = QVBoxLayout(bar)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)

        controls = QHBoxLayout()
        controls.setSpacing(20)
        self.pitch_slider = QuickSlider("PITCH", -24, 24, 0, " st")
        self.pitch_slider.valueChanged.connect(self._on_quick)
        self.tone_slider = QuickSlider("TONE", -12, 12, 0, " st")
        self.tone_slider.valueChanged.connect(self._on_quick)
        self.pitch_slider.setMinimumWidth(160)
        self.tone_slider.setMinimumWidth(160)
        controls.addWidget(self.pitch_slider, 3)
        controls.addWidget(self.tone_slider, 3)

        meters = QVBoxLayout()
        meters.setSpacing(5)
        self.in_meter = VUMeter("IN")
        self.out_meter = VUMeter("OUT")
        self.in_meter.setMinimumWidth(150)
        self.out_meter.setMinimumWidth(150)
        meters.addStretch(1)
        meters.addWidget(self.in_meter)
        meters.addWidget(self.out_meter)
        meters.addStretch(1)
        controls.addLayout(meters, 3)

        self.spectrum = SpectrumView()
        self.spectrum.setMinimumWidth(120)
        self.spectrum.setMinimumHeight(44)
        controls.addWidget(self.spectrum, 2)
        lay.addLayout(controls)

        strip = QHBoxLayout()
        strip.setSpacing(8)
        self.hud = LatencyHUD()
        strip.addWidget(self.hud, 1)
        self.status_lbl = QLabel("Ready")
        self.status_lbl.setObjectName("hint")
        strip.addWidget(self.status_lbl)
        lay.addLayout(strip)
        return bar

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self.windowIcon() or QIcon())
        menu = QMenu()
        for label, fn in (("Show VoxMorph", self.showNormal),
                          ("Start / Stop", self._toggle_stream),
                          ("Quit", self.close)):
            act = QAction(label, self)
            act.triggered.connect(fn)
            menu.addAction(act)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self.showNormal() if r == QSystemTrayIcon.DoubleClick else None)

    # ------------------------------------------------------------------ tiles
    def _rebuild_tiles(self) -> None:
        if self._building:
            return
        self._rebuild_chips()
        self._clear_layout(self.grid)
        self._tiles.clear()

        term = self.search.text().lower().strip()
        active = self.app.cfg.engine.preset_id
        shown = []
        for p in self.app.presets.list():
            if self._category not in ("All", "") and p.category != self._category:
                continue
            if term and term not in p.name.lower() and term not in p.description.lower():
                continue
            shown.append(p)

        cols = self._column_count()
        self._columns = cols
        for i, p in enumerate(shown):
            tile = VoiceTile(p)
            tile.setChecked(p.id == active)
            tile.clicked.connect(lambda _=False, pid=p.id: self._pick_voice(pid))
            self.grid.addWidget(tile, i // cols, i % cols)
            self._tiles.append(tile)
        for c in range(cols):
            self.grid.setColumnStretch(c, 1)

        if not shown:
            empty = QLabel("No voices match that search.")
            empty.setObjectName("hint")
            empty.setAlignment(Qt.AlignCenter)
            self.grid.addWidget(empty, 0, 0)
            return

        # keep the active voice on screen; otherwise picking one further down
        # the list leaves the user staring at an unchanged grid
        for t in self._tiles:
            if t.isChecked():
                QTimer.singleShot(0, lambda w=t: self.scroll.ensureWidgetVisible(w, 0, 40))
                break

    def _column_count(self) -> int:
        """Fit as many tiles as the viewport allows, accounting for the grid's
        own margins and spacing rather than just dividing the raw width."""
        m = self.grid.contentsMargins()
        avail = self.scroll.viewport().width() - m.left() - m.right()
        spacing = self.grid.horizontalSpacing() or 10
        cols = max(1, (avail + spacing) // (TILE_MIN_WIDTH + spacing))
        return int(min(cols, 4))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if not self._building and self._column_count() != self._columns:
            self._rebuild_tiles()

    def _pick_voice(self, preset_id: str) -> None:
        preset = self.app.presets.get(preset_id)
        if preset is None:
            return
        if preset.needs_download:
            self.status_lbl.setText(f"Downloading {preset.name}\u2026")
            ok = self.app.download_preset(
                preset_id, lambda m, f: self.status_lbl.setText(f"{m} {f*100:.0f}%"))
            if not ok:
                QMessageBox.warning(self, "Download failed",
                                    "Could not download or verify that voice.")
                self._rebuild_tiles()
                return
            self.app.presets.load_all()
        self.app.load_preset(preset_id)
        for t in self._tiles:
            t.setChecked(t.preset.id == preset_id)
        self._sync_quick()

    def _import_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import RVC model", "",
                                              "RVC model (*.pth)")
        if not path:
            return
        p = self.app.presets.import_model(Path(path))
        self._rebuild_tiles()
        if p:
            QMessageBox.information(self, "Imported", f"'{p.name}' is ready to use.")

    # --------------------------------------------------------------- handlers
    def _on_power(self, on: bool) -> None:
        running = self.app.toggle()
        if running != on:
            self.power.setChecked(running)

    def _toggle_stream(self) -> None:
        self.power.setChecked(self.app.toggle())

    def _on_monitor(self) -> None:
        on = self.app.toggle_monitor()
        self.monitor_btn.setChecked(on)

    def _on_quick(self) -> None:
        if self._building:
            return
        self.app.cfg.engine.pitch_shift = self.pitch_slider.getValue()
        self.app.cfg.engine.formant_shift = self.tone_slider.getValue()
        self.app.apply_settings()

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.app, self)
        dlg.exec()
        self._sync()
        self._rebuild_tiles()

    def _toggle_record(self) -> None:
        on = self.app.toggle_recording()
        self.record_btn.setChecked(on)

    # ---------------------------------------------------------------- updates
    def _install_update(self) -> None:
        if not self.app.update_info:
            return
        ok = self.app.install_update(
            lambda m, f: self.banner.set_progress(f, f"{m} {f*100:.0f}%"))
        if ok:
            self.close()
        else:
            QMessageBox.warning(self, "Update failed",
                                self.app.updater.last_error or "Could not install.")
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

    # ------------------------------------------------------------------- sync
    def _sync_quick(self) -> None:
        self._building = True
        self.pitch_slider.setValue(int(self.app.cfg.engine.pitch_shift))
        self.tone_slider.setValue(int(self.app.cfg.engine.formant_shift))
        self._building = False

    def _sync(self) -> None:
        self._sync_quick()
        self.monitor_btn.setChecked(self.app.cfg.audio.monitor_enabled)
        self.power.setChecked(self.app.running)

    def _tick(self) -> None:
        s = self.app.metrics.get()
        self.in_meter.set_level(s.input_rms_db, s.input_peak_db)
        self.out_meter.set_level(s.output_rms_db, s.output_peak_db)
        if s.spectrum:
            self.spectrum.set_values(s.spectrum)
        self.hud.update_from(s)

        preset = self.app.presets.get(self.app.cfg.engine.preset_id)
        name = preset.name if preset else "-"
        self.now_playing.setText(f"{name}  \u00b7  {s.engine}")

        if self.power.isChecked() != self.app.running:
            self.power.setChecked(self.app.running)
        if self.app.pipeline:
            self.mute_btn.setChecked(self.app.pipeline.muted)
        if self.app.recorder.recording:
            self.status_lbl.setText(f"Recording {self.app.recorder.duration_s:.0f}s")

    def _on_notify(self, level: str, message: str) -> None:
        colors = {"error": COLORS["bad"], "warn": COLORS["warn"],
                  "update": COLORS["update"]}
        self.status_lbl.setStyleSheet(f"color:{colors.get(level, COLORS['text_dim'])};")
        self.status_lbl.setText(message)
        if level == "update" and self.app.update_info:
            self.banner.show_update(self.app.update_info)

    def closeEvent(self, event) -> None:
        self.timer.stop()
        self.app.shutdown()
        event.accept()
