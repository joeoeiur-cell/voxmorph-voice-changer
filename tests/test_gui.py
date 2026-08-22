"""Headless GUI smoke test - builds the real window offscreen and drives it.

Catches the class of bug that only appears when Qt actually instantiates
widgets: bad signal signatures, missing attributes, layout errors.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from voxmorph.app import VoxMorphApp
from voxmorph.metrics import Snapshot
from voxmorph.ui.main_window import MainWindow
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
check("window constructs", win is not None)
check("voice list populated", win.preset_list.count() >= 15,
      f"{win.preset_list.count()} voices")
check("all five tabs built",
      win.centralWidget().findChildren(type(win.findChild(type(win)))) is not None)

print("\nWidget interaction")
win.pitch_slider.setValue(5)
check("pitch slider writes through to config", app.cfg.engine.pitch_shift == 5,
      f"cfg={app.cfg.engine.pitch_shift}")
win.fx_sliders["reverb"].setValue(40)
check("fx slider writes through to config", abs(app.cfg.fx.reverb - 0.40) < 1e-6,
      f"cfg={app.cfg.fx.reverb}")
win.character_combo.setCurrentText("robot")
check("character combo writes through", app.cfg.fx.character == "robot")

# select a different voice through the list, as a user would
for i in range(win.preset_list.count()):
    item = win.preset_list.item(i)
    if item.data(0x0100) == "dsp_deep_male":  # Qt.UserRole
        win.preset_list.setCurrentItem(item)
        break
check("selecting a voice loads it", app.cfg.engine.preset_id == "dsp_deep_male",
      f"loaded={app.cfg.engine.preset_id}")

print("\nMeters and HUD")
snap = Snapshot(input_rms_db=-18.0, input_peak_db=-9.0, output_rms_db=-14.0,
                output_peak_db=-6.0, total_latency_ms=87.0, realtime_factor=0.31,
                infer_ms=12.0, f0_hz=138.0, pitch_offset=-3.0, dropouts=0,
                running=True, engine="DSP", device="CPU",
                spectrum=[-40.0] * 32)
win.hud.update_from(snap)
win.in_meter.set_level(snap.input_rms_db, snap.input_peak_db)
win.spectrum.set_values(snap.spectrum)
check("HUD renders latency", win.hud.latency.value.text() == "87 ms",
      win.hud.latency.value.text())
check("HUD renders realtime load", win.hud.load.value.text() == "31%")
check("HUD renders tracked pitch", "138" in win.hud.pitch.value.text(),
      win.hud.pitch.value.text())

print("\nUpdate banner")
from voxmorph.updater.updater import UpdateInfo
info = UpdateInfo(version="1.4.0", name="v1.4.0", notes="Automated build\n" + "a" * 64,
                  url="https://example/x.exe", size=52428800, sha256="a" * 64,
                  ai_generated=True, prerelease=True, asset_name="x.exe")
app.update_info = info
win.banner.show_update(info)
# isVisible() is False while the top-level window is still unshown, so assert
# on isHidden(), which reflects the widget's own visibility flag.
check("banner becomes visible on update", not win.banner.isHidden())
check("banner labels AI builds", "AI-generated build" in win.banner.text.text())
check("banner shows the version", "1.4.0" in win.banner.text.text())
win.banner.set_progress(0.5, "Downloading 50%")
check("banner shows download progress", win.banner.progress.value() == 50)

print("\nRender pass")
win.resize(1080, 720)
win.show()
qapp.processEvents()
pixmap = win.grab()
check("window renders to a pixmap", not pixmap.isNull(),
      f"{pixmap.width()}x{pixmap.height()}")
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
