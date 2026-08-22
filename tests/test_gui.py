"""Headless GUI smoke test - builds the real window offscreen and drives it."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from voxmorph.app import VoxMorphApp
from voxmorph.metrics import Snapshot
from voxmorph.ui.main_window import MainWindow
from voxmorph.ui.settings_dialog import SettingsDialog
from voxmorph.ui.theme import STYLESHEET

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{'  ' + detail if detail else ''}")


qapp = QApplication(sys.argv)
qapp.setStyleSheet(STYLESHEET)

print("\nController")
app = VoxMorphApp()
app.initialise()
check("controller initialises without audio hardware", app.engine is not None,
      f"engine={app.engine.caps.name}")
check("falls back to a usable engine", app.engine.ready)

print("\nMain window")
win = MainWindow(app)
win.resize(960, 700)
win.show()
qapp.processEvents()
check("window constructs", win is not None)
check("voice tiles built", len(win._tiles) >= 15, f"{len(win._tiles)} tiles")
check("exactly one tile selected",
      sum(1 for t in win._tiles if t.isChecked()) == 1)

print("\nPower switch")
check("starts off", not win.power.isChecked())
win.power.setChecked(True, emit=True)
qapp.processEvents()
# no audio device in CI, so the app refuses to start - the switch must follow
check("switch reflects real pipeline state",
      win.power.isChecked() == app.running,
      f"switch={win.power.isChecked()} running={app.running}")

print("\nHear-yourself toggle")
before = app.cfg.audio.monitor_enabled
win._on_monitor()
check("monitor toggle flips persisted config",
      app.cfg.audio.monitor_enabled != before,
      f"{before} -> {app.cfg.audio.monitor_enabled}")
check("monitor button reflects state",
      win.monitor_btn.isChecked() == app.cfg.audio.monitor_enabled)
win._on_monitor()

print("\nQuick controls")
win.pitch_slider.setValue(5)
qapp.processEvents()
check("pitch writes through to config", app.cfg.engine.pitch_shift == 5,
      f"cfg={app.cfg.engine.pitch_shift}")
win.tone_slider.setValue(-3)
qapp.processEvents()
check("tone writes through to config", app.cfg.engine.formant_shift == -3,
      f"cfg={app.cfg.engine.formant_shift}")

print("\nVoice selection")
win._pick_voice("dsp_deep_male")
qapp.processEvents()
check("selecting a tile loads the voice",
      app.cfg.engine.preset_id == "dsp_deep_male", app.cfg.engine.preset_id)
check("selection is visually exclusive",
      sum(1 for t in win._tiles if t.isChecked()) == 1)

print("\nFilters")
win.search.setText("female")
qapp.processEvents()
check("search filters the grid", 0 < len(win._tiles) < 15, f"{len(win._tiles)} tiles")
win.search.setText("")
win._set_category("Masculine")
qapp.processEvents()
check("category chip filters the grid",
      all(t.preset.category == "Masculine" for t in win._tiles),
      f"{len(win._tiles)} tiles")
win._set_category("All")

print("\nSettings dialog")
dlg = SettingsDialog(app)
dlg.fx_sliders["reverb"].setValue(40)
check("settings slider writes through", abs(app.cfg.fx.reverb - 0.40) < 1e-6,
      f"cfg={app.cfg.fx.reverb}")
dlg.character_combo.setCurrentText("robot")
check("character combo writes through", app.cfg.fx.character == "robot")
dlg.mon_vol.setValue(-12)
check("monitor volume writes through", app.cfg.audio.monitor_volume_db == -12)
dlg.close()

print("\nMeters and HUD")
snap = Snapshot(input_rms_db=-18.0, input_peak_db=-9.0, output_rms_db=-14.0,
                output_peak_db=-6.0, total_latency_ms=87.0, realtime_factor=0.31,
                infer_ms=12.0, f0_hz=138.0, pitch_offset=-3.0, dropouts=0,
                running=True, engine="DSP", device="CPU", spectrum=[-40.0] * 40)
win.hud.update_from(snap)
win.in_meter.set_level(snap.input_rms_db, snap.input_peak_db)
win.spectrum.set_values(snap.spectrum)
check("HUD renders latency", "87" in win.hud.latency.text(), win.hud.latency.text())
check("HUD renders load", "31" in win.hud.load.text(), win.hud.load.text())
check("HUD renders pitch", "138" in win.hud.pitch.text(), win.hud.pitch.text())

print("\nUpdate banner")
from voxmorph.updater.updater import UpdateInfo
info = UpdateInfo(version="1.4.0", name="v1.4.0", notes="Automated build",
                  url="https://example/x.exe", size=52428800, sha256="a" * 64,
                  ai_generated=True, prerelease=True, asset_name="x.exe")
app.update_info = info
win.banner.show_update(info)
check("banner becomes visible", not win.banner.isHidden())
check("banner labels AI builds", "AI-generated build" in win.banner.text.text())

print("\nRender pass")
qapp.processEvents()
pixmap = win.grab()
check("window renders", not pixmap.isNull(), f"{pixmap.width()}x{pixmap.height()}")
out = Path(__file__).resolve().parent.parent / "docs" / "screenshot.png"
out.parent.mkdir(exist_ok=True)
pixmap.save(str(out))
check("screenshot written", out.exists() and out.stat().st_size > 5000,
      f"{out.stat().st_size // 1024} KB")

win.timer.stop()
app.shutdown()

passed = sum(1 for _, ok, _ in results if ok)
print(f"\n{'=' * 60}\n{passed}/{len(results)} GUI checks passed")
for name, ok, detail in results:
    if not ok:
        print(f"  FAILED: {name} {detail}")
sys.exit(0 if passed == len(results) else 1)
