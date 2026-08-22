"""Qt entry point."""
from __future__ import annotations

import sys


def run_gui(argv=None) -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from ..app import VoxMorphApp
    from ..logging_setup import setup_logging
    from .main_window import MainWindow
    from .theme import STYLESHEET

    setup_logging()

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qapp = QApplication(argv or sys.argv)
    qapp.setApplicationName("VoxMorph")
    qapp.setOrganizationName("VoxMorph")
    qapp.setStyleSheet(STYLESHEET)

    app = VoxMorphApp()
    app.initialise()

    win = MainWindow(app)
    if app.cfg.ui.start_minimized:
        win.showMinimized()
    else:
        win.show()
    return qapp.exec()


__all__ = ["run_gui"]
