"""Custom Qt widgets: VU meters, spectrum analyser, latency HUD, update banner."""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from .theme import COLORS


class VUMeter(QWidget):
    """Horizontal level meter with peak-hold. dBFS scale, -60 to 0."""

    def __init__(self, label: str = "", parent=None):
        super().__init__(parent)
        self.label = label
        self.level_db = -90.0
        self.peak_db = -90.0
        self._hold = 0
        self.setMinimumHeight(20)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_level(self, rms_db: float, peak_db: float) -> None:
        self.level_db = max(-60.0, min(0.0, rms_db))
        p = max(-60.0, min(0.0, peak_db))
        if p >= self.peak_db or self._hold <= 0:
            self.peak_db = p
            self._hold = 25
        else:
            self._hold -= 1
            self.peak_db -= 0.6
        self.update()

    @staticmethod
    def _norm(db: float) -> float:
        return max(0.0, min(1.0, (db + 60.0) / 60.0))

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(0, 0, -1, -1)

        bar = QRectF(r)
        if self.label:
            bar.setLeft(46)
            p.setPen(QColor(COLORS["text_dim"]))
            p.drawText(QRectF(0, 0, 42, r.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, self.label)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(COLORS["surface2"]))
        p.drawRoundedRect(bar, 4, 4)

        w = bar.width() * self._norm(self.level_db)
        if w > 1:
            grad = QLinearGradient(bar.left(), 0, bar.right(), 0)
            grad.setColorAt(0.0, QColor(COLORS["good"]))
            grad.setColorAt(0.75, QColor(COLORS["accent"]))
            grad.setColorAt(0.92, QColor(COLORS["warn"]))
            grad.setColorAt(1.0, QColor(COLORS["bad"]))
            p.setBrush(grad)
            p.drawRoundedRect(QRectF(bar.left(), bar.top(), w, bar.height()), 4, 4)

        if self.peak_db > -59:
            x = bar.left() + bar.width() * self._norm(self.peak_db)
            p.setPen(QPen(QColor(COLORS["text"]), 2))
            p.drawLine(int(x), int(bar.top() + 2), int(x), int(bar.bottom() - 2))
        p.end()


class SpectrumView(QWidget):
    """Log-spaced band spectrum of the converted output."""

    def __init__(self, bands: int = 32, parent=None):
        super().__init__(parent)
        self.bands = bands
        self.values: List[float] = [-90.0] * bands
        self._smooth: List[float] = [-90.0] * bands
        self.setMinimumHeight(84)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_values(self, vals: List[float]) -> None:
        if not vals:
            return
        self.values = vals
        for i, v in enumerate(vals[: len(self._smooth)]):
            prev = self._smooth[i]
            # fast attack, slow release reads better than raw values
            self._smooth[i] = v if v > prev else prev * 0.82 + v * 0.18
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(COLORS["surface"]))
        p.drawRoundedRect(r, 8, 8)

        n = len(self._smooth)
        if not n:
            return
        gap = 2.0
        bw = (r.width() - 16 - gap * (n - 1)) / n
        grad = QLinearGradient(0, r.bottom(), 0, r.top())
        grad.setColorAt(0.0, QColor(COLORS["accent_dk"]))
        grad.setColorAt(1.0, QColor(COLORS["accent"]))
        p.setBrush(grad)
        for i, db in enumerate(self._smooth):
            frac = max(0.0, min(1.0, (db + 80.0) / 80.0))
            h = frac * (r.height() - 16)
            if h < 1:
                continue
            x = 8 + i * (bw + gap)
            p.drawRoundedRect(QRectF(x, r.bottom() - 8 - h, bw, h), 2, 2)
        p.end()


class StatCard(QFrame):
    """One labelled number in the HUD."""

    def __init__(self, title: str, value: str = "-", parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background:{COLORS['surface2']};border:1px solid {COLORS['border']};"
            f"border-radius:8px;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(1)
        self.title = QLabel(title.upper())
        self.title.setStyleSheet(
            f"color:{COLORS['text_dim']};font-size:9px;letter-spacing:1px;font-weight:700;")
        self.value = QLabel(value)
        self.value.setStyleSheet("font-size:15px;font-weight:700;")
        lay.addWidget(self.title)
        lay.addWidget(self.value)

    def set(self, text: str, color: Optional[str] = None) -> None:
        self.value.setText(text)
        self.value.setStyleSheet(
            f"font-size:15px;font-weight:700;color:{color or COLORS['text']};")


class LatencyHUD(QWidget):
    """Live performance readout - the honest answer to 'is this fast enough?'"""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.latency = StatCard("Latency", "-")
        self.load = StatCard("RT Load", "-")
        self.infer = StatCard("Model", "-")
        self.pitch = StatCard("Pitch", "-")
        self.drops = StatCard("Dropouts", "0")
        for w in (self.latency, self.load, self.infer, self.pitch, self.drops):
            lay.addWidget(w)

    def update_from(self, s) -> None:
        self.latency.set(f"{s.total_latency_ms:.0f} ms")
        rf = s.realtime_factor
        color = (COLORS["good"] if rf < 0.5 else
                 COLORS["warn"] if rf < 0.8 else COLORS["bad"])
        self.load.set(f"{rf * 100:.0f}%", color if s.running else None)
        self.infer.set(f"{s.infer_ms:.0f} ms" if s.infer_ms else "-")
        if s.f0_hz > 0:
            off = f" {s.pitch_offset:+.0f}st" if s.pitch_offset else ""
            self.pitch.set(f"{s.f0_hz:.0f} Hz{off}")
        else:
            self.pitch.set("-")
        self.drops.set(str(s.dropouts),
                       COLORS["bad"] if s.dropouts else COLORS["text_dim"])


class UpdateBanner(QFrame):
    """Shown at the top of the window when a newer release exists."""

    install_clicked = Signal()
    dismiss_clicked = Signal()
    notes_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        self.setStyleSheet(
            f"QFrame{{background:{COLORS['surface2']};"
            f"border:1px solid {COLORS['update']};border-radius:10px;}}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 12, 10)
        lay.setSpacing(10)

        self.icon = QLabel("\u2b06")
        self.icon.setStyleSheet(f"color:{COLORS['update']};font-size:17px;border:none;")
        self.text = QLabel("Update available")
        self.text.setStyleSheet("font-weight:600;border:none;")
        self.text.setWordWrap(True)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setMaximumWidth(160)
        self.progress.setTextVisible(False)

        self.notes_btn = QPushButton("Release notes")
        self.install_btn = QPushButton("Install now")
        self.install_btn.setObjectName("primary")
        self.later_btn = QPushButton("Later")

        self.notes_btn.clicked.connect(self.notes_clicked.emit)
        self.install_btn.clicked.connect(self.install_clicked.emit)
        self.later_btn.clicked.connect(self.dismiss_clicked.emit)

        lay.addWidget(self.icon)
        lay.addWidget(self.text, 1)
        lay.addWidget(self.progress)
        lay.addWidget(self.notes_btn)
        lay.addWidget(self.install_btn)
        lay.addWidget(self.later_btn)

    def show_update(self, info) -> None:
        tag = "AI-generated build" if getattr(info, "ai_generated", False) else "Update"
        pre = " (pre-release)" if getattr(info, "prerelease", False) else ""
        self.text.setText(
            f"<b>{tag} available - v{info.version}{pre}</b> &nbsp; "
            f"<span style='color:{COLORS['text_dim']}'>{info.size_mb:.0f} MB</span>")
        self.setVisible(True)

    def set_progress(self, frac: float, message: str = "") -> None:
        self.progress.setVisible(True)
        self.progress.setValue(int(frac * 100))
        if message:
            self.text.setText(message)
        self.install_btn.setEnabled(False)


class Badge(QLabel):
    """Small coloured pill, used for 'IDENTITY' vs 'CHARACTER' preset tags."""

    def __init__(self, text: str, color: str, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(
            f"background:{color}22;color:{color};border:1px solid {color}66;"
            f"border-radius:7px;padding:1px 7px;font-size:9px;font-weight:700;"
            f"letter-spacing:0.5px;")
        self.setAlignment(Qt.AlignCenter)
