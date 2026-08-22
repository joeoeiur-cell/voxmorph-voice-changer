"""Custom Qt widgets: meters, spectrum, HUD, update banner, and the
Voicemod-style controls (big power switch, voice tiles, icon buttons)."""
from __future__ import annotations

import math
from typing import List, Optional

from PySide6.QtCore import (Property, QEasingCurve, QPropertyAnimation, QRectF,
                            QSize, Qt, Signal)
from PySide6.QtGui import (QColor, QFont, QLinearGradient, QPainter, QPainterPath,
                           QPen)
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from .theme import COLORS


# ---------------------------------------------------------------- power switch
class ToggleSwitch(QWidget):
    """Large animated on/off switch - the single most important control."""

    toggled = Signal(bool)

    def __init__(self, parent=None, width: int = 92, height: int = 44):
        super().__init__(parent)
        self._checked = False
        self._pos = 0.0
        self.setFixedSize(width, height)
        self.setCursor(Qt.PointingHandCursor)
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.setToolTip("Turn the voice changer on or off")

    def getKnob(self) -> float:
        return self._pos

    def setKnob(self, v: float) -> None:
        self._pos = v
        self.update()

    knob = Property(float, getKnob, setKnob)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, on: bool, emit: bool = False) -> None:
        on = bool(on)
        if on == self._checked:
            return
        self._checked = on
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()
        if emit:
            self.toggled.emit(on)

    def mousePressEvent(self, _e) -> None:
        self.setChecked(not self._checked, emit=True)

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.setChecked(not self._checked, emit=True)
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = r.height() / 2

        off = QColor(COLORS["surface2"])
        on = QColor(COLORS["accent"])
        track = QColor(
            int(off.red() + (on.red() - off.red()) * self._pos),
            int(off.green() + (on.green() - off.green()) * self._pos),
            int(off.blue() + (on.blue() - off.blue()) * self._pos),
        )
        p.setPen(QPen(QColor(COLORS["accent"] if self._checked else COLORS["border"]), 1.5))
        p.setBrush(track)
        p.drawRoundedRect(r, radius, radius)

        d = r.height() - 8
        x = r.left() + 4 + self._pos * (r.width() - d - 8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#06202a" if self._checked else COLORS["text_dim"]))
        p.drawEllipse(QRectF(x, r.top() + 4, d, d))

        p.setPen(QColor("#06202a") if self._checked else QColor(COLORS["text_dim"]))
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        f.setBold(True)
        p.setFont(f)
        label = "ON" if self._checked else "OFF"
        box = (QRectF(r.left() + 10, r.top(), r.width() / 2, r.height()) if self._checked
               else QRectF(r.left() + r.width() / 2 - 6, r.top(), r.width() / 2, r.height()))
        p.drawText(box, Qt.AlignCenter, label)
        p.end()


# ------------------------------------------------------------------ voice tile
class VoiceTile(QPushButton):
    """A voice as a card, not a list row."""

    GLYPHS = {
        "Masculine": "\u25c6", "Feminine": "\u25cf", "Character": "\u2726",
        "Broadcast": "\u25a0", "Neutral": "\u25cb", "My Voices": "\u2605",
        "Identity": "\u2b1f",
    }

    def __init__(self, preset, parent=None):
        super().__init__(parent)
        self.preset = preset
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(104)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip(preset.description or preset.name)
        self._locked = preset.needs_download
        self.setObjectName("voiceTile")

    @staticmethod
    def _draw_elided(p: QPainter, box: QRectF, text: str, max_lines: int = 2) -> None:
        """Word-wrap into at most max_lines, adding an ellipsis on the last one.

        Qt's TextWordWrap alone clips the overflow mid-word, which is what made
        several tiles read as truncated nonsense.
        """
        if not text:
            return
        fm = p.fontMetrics()
        line_h = fm.height()
        lines: list[str] = []
        cur = ""
        for word in text.split():
            trial = f"{cur} {word}".strip()
            if fm.horizontalAdvance(trial) <= box.width() or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
                if len(lines) == max_lines:
                    break
        if cur and len(lines) < max_lines:
            lines.append(cur)

        if " ".join(lines).rstrip() != text.rstrip() and lines:
            lines[-1] = fm.elidedText(lines[-1] + "\u2026", Qt.ElideRight,
                                      int(box.width()))
        for i, line in enumerate(lines[:max_lines]):
            y = box.top() + i * line_h
            if y + line_h > box.bottom() + 2:
                break
            p.drawText(QRectF(box.left(), y, box.width(), line_h),
                       Qt.AlignLeft | Qt.AlignVCenter, line)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        sel = self.isChecked()
        hover = self.underMouse()

        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)

        if sel:
            g = QLinearGradient(r.left(), r.top(), r.right(), r.bottom())
            g.setColorAt(0.0, QColor(14, 116, 144, 130))
            g.setColorAt(1.0, QColor(34, 211, 238, 45))
            p.fillPath(path, g)
            p.setPen(QPen(QColor(COLORS["accent"]), 1.6))
        else:
            p.fillPath(path, QColor(COLORS["surface2"] if hover else COLORS["surface"]))
            p.setPen(QPen(QColor(COLORS["accent"] if hover else COLORS["border"]),
                          1.4 if hover else 1.0))
        p.drawPath(path)

        # glyph badge
        badge = QRectF(r.left() + 12, r.top() + 12, 30, 30)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(34, 211, 238, 40) if sel else QColor(COLORS["surface2"]))
        p.drawRoundedRect(badge, 9, 9)
        p.setPen(QColor(COLORS["accent"]) if sel else QColor(COLORS["text_dim"]))
        gf = QFont(self.font())
        gf.setPointSizeF(13)
        p.setFont(gf)
        p.drawText(badge, Qt.AlignCenter, self.GLYPHS.get(self.preset.category, "\u25cf"))

        # name
        nf = QFont(self.font())
        nf.setPointSizeF(10.5)
        nf.setBold(True)
        p.setFont(nf)
        p.setPen(QColor(COLORS["text"] if not self._locked else COLORS["text_dim"]))
        p.drawText(QRectF(r.left() + 52, r.top() + 12, r.width() - 64, 20),
                   Qt.AlignVCenter | Qt.AlignLeft, self.preset.name)

        # category / lock
        sf = QFont(self.font())
        sf.setPointSizeF(7.5)
        p.setFont(sf)
        p.setPen(QColor(COLORS["text_dim"]))
        tag = (f"{self.preset.size_mb:.0f} MB download" if self._locked
               else self.preset.category.upper())
        p.drawText(QRectF(r.left() + 52, r.top() + 30, r.width() - 64, 16),
                   Qt.AlignVCenter | Qt.AlignLeft, tag)

        # description
        # description - wrapped to at most two lines, elided rather than clipped
        df = QFont(self.font())
        df.setPointSizeF(8)
        p.setFont(df)
        p.setPen(QColor(COLORS["text_dim"]))
        box = QRectF(r.left() + 14, r.top() + 56, r.width() - 28, r.height() - 64)
        self._draw_elided(p, box, self.preset.description or "", max_lines=2)

        if self.preset.is_identity:
            w = 58
            pill = QRectF(r.right() - w - 12, r.top() + 13, w, 16)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(34, 211, 238, 34))
            p.drawRoundedRect(pill, 8, 8)
            p.setPen(QColor(COLORS["accent"]))
            pf = QFont(self.font())
            pf.setPointSizeF(6.5)
            pf.setBold(True)
            p.setFont(pf)
            p.drawText(pill, Qt.AlignCenter, "IDENTITY")
        p.end()


class IconButton(QPushButton):
    """Square, checkable, glyph-only button for the header."""

    def __init__(self, glyph: str, tooltip: str, parent=None, checkable: bool = True):
        super().__init__(glyph, parent)
        self.setCheckable(checkable)
        self.setToolTip(tooltip)
        self.setFixedSize(QSize(40, 40))
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("iconBtn")


class QuickSlider(QWidget):
    """Labelled slider with a live value read-out."""

    valueChanged = Signal(int)

    def __init__(self, label: str, lo: int, hi: int, value: int = 0,
                 suffix: str = "", parent=None):
        from PySide6.QtWidgets import QSlider
        super().__init__(parent)
        self.suffix = suffix
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self.name = QLabel(label)
        self.name.setStyleSheet(
            f"color:{COLORS['text_dim']};font-size:10px;font-weight:600;"
            f"letter-spacing:0.6px;")
        self.value = QLabel("0")
        self.value.setObjectName("stat")
        self.value.setAlignment(Qt.AlignRight)
        top.addWidget(self.name)
        top.addStretch(1)
        top.addWidget(self.value)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(lo, hi)
        self.slider.setValue(value)
        self.slider.valueChanged.connect(self._on_change)

        lay.addLayout(top)
        lay.addWidget(self.slider)
        self._render(value)

    def _on_change(self, v: int) -> None:
        self._render(v)
        self.valueChanged.emit(v)

    def _render(self, v: int) -> None:
        self.value.setText(f"{v:+d}{self.suffix}" if self.suffix else str(v))

    def setValue(self, v: int) -> None:
        self.slider.setValue(v)

    def getValue(self) -> int:
        return self.slider.value()


# ------------------------------------------------------------------- meters
class VUMeter(QWidget):
    """Horizontal level meter with peak-hold. dBFS scale, -60 to 0."""

    def __init__(self, label: str = "", parent=None):
        super().__init__(parent)
        self.label = label
        self.level_db = -90.0
        self.peak_db = -90.0
        self._hold = 0
        self.setMinimumHeight(14)
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
        r = QRectF(self.rect()).adjusted(0, 0, -1, -1)

        bar = QRectF(r)
        if self.label:
            bar.setLeft(34)
            p.setPen(QColor(COLORS["text_dim"]))
            f = QFont(self.font())
            f.setPointSizeF(7.5)
            f.setBold(True)
            p.setFont(f)
            p.drawText(QRectF(0, 0, 30, r.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, self.label)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(COLORS["surface2"]))
        p.drawRoundedRect(bar, 3, 3)

        w = bar.width() * self._norm(self.level_db)
        if w > 1:
            grad = QLinearGradient(bar.left(), 0, bar.right(), 0)
            grad.setColorAt(0.0, QColor(COLORS["good"]))
            grad.setColorAt(0.75, QColor(COLORS["accent"]))
            grad.setColorAt(0.92, QColor(COLORS["warn"]))
            grad.setColorAt(1.0, QColor(COLORS["bad"]))
            p.setBrush(grad)
            p.drawRoundedRect(QRectF(bar.left(), bar.top(), w, bar.height()), 3, 3)

        if self.peak_db > -59:
            x = bar.left() + bar.width() * self._norm(self.peak_db)
            p.setPen(QPen(QColor(COLORS["text"]), 2))
            p.drawLine(int(x), int(bar.top() + 1), int(x), int(bar.bottom() - 1))
        p.end()


class SpectrumView(QWidget):
    """Log-spaced band spectrum of the converted output."""

    def __init__(self, bands: int = 40, parent=None):
        super().__init__(parent)
        self.bands = bands
        self._smooth: List[float] = [-90.0] * bands
        self.setMinimumHeight(46)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_values(self, vals: List[float]) -> None:
        if not vals:
            return
        for i, v in enumerate(vals[: len(self._smooth)]):
            prev = self._smooth[i]
            self._smooth[i] = v if v > prev else prev * 0.82 + v * 0.18
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        n = len(self._smooth)
        if not n:
            return
        gap = 2.0
        bw = (r.width() - gap * (n - 1)) / n
        grad = QLinearGradient(0, r.bottom(), 0, r.top())
        grad.setColorAt(0.0, QColor(14, 116, 144, 190))
        grad.setColorAt(1.0, QColor(34, 211, 238, 235))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        for i, db in enumerate(self._smooth):
            frac = max(0.0, min(1.0, (db + 80.0) / 80.0))
            h = frac * r.height()
            if h < 1.5:
                continue
            p.drawRoundedRect(QRectF(i * (bw + gap), r.bottom() - h, bw, h), 1.5, 1.5)
        p.end()


class StatChip(QLabel):
    """Compact monospace read-out for the status bar."""

    def __init__(self, text: str = "-", parent=None):
        super().__init__(text, parent)
        self.setObjectName("chip")
        self.setAlignment(Qt.AlignCenter)

    def set(self, text: str, color: Optional[str] = None) -> None:
        self.setText(text)
        self.setStyleSheet(f"color:{color};" if color else "")


class LatencyHUD(QWidget):
    """Compact performance strip."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.latency = StatChip("- ms")
        self.load = StatChip("-")
        self.pitch = StatChip("-")
        self.drops = StatChip("0 drops")
        for w in (self.latency, self.load, self.pitch, self.drops):
            lay.addWidget(w)
        lay.addStretch(1)

    def update_from(self, s) -> None:
        self.latency.set(f"{s.total_latency_ms:.0f} ms")
        rf = s.realtime_factor
        color = (COLORS["good"] if rf < 0.5 else
                 COLORS["warn"] if rf < 0.8 else COLORS["bad"])
        self.load.set(f"load {rf * 100:.0f}%", color if s.running else None)
        self.pitch.set(f"{s.f0_hz:.0f} Hz" if s.f0_hz > 0 else "-- Hz")
        self.drops.set(f"{s.dropouts} drops",
                       COLORS["bad"] if s.dropouts else None)


class UpdateBanner(QFrame):
    """Shown at the top of the window when a newer release exists."""

    install_clicked = Signal()
    dismiss_clicked = Signal()
    notes_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        self.setObjectName("updateBanner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 9, 10, 9)
        lay.setSpacing(10)

        self.icon = QLabel("\u2b06")
        self.icon.setStyleSheet(f"color:{COLORS['update']};font-size:16px;border:none;")
        self.text = QLabel("Update available")
        self.text.setStyleSheet("font-weight:600;border:none;")
        self.text.setWordWrap(True)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setMaximumWidth(150)
        self.progress.setTextVisible(False)

        self.notes_btn = QPushButton("Notes")
        self.install_btn = QPushButton("Install")
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
    def __init__(self, text: str, color: str, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(
            f"background:{color}22;color:{color};border:1px solid {color}66;"
            f"border-radius:7px;padding:1px 7px;font-size:9px;font-weight:700;")
        self.setAlignment(Qt.AlignCenter)


# kept for compatibility with older layouts
class StatCard(QFrame):
    def __init__(self, title: str, value: str = "-", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(1)
        self.title = QLabel(title.upper())
        self.title.setStyleSheet(
            f"color:{COLORS['text_dim']};font-size:9px;font-weight:700;")
        self.value = QLabel(value)
        self.value.setStyleSheet("font-size:15px;font-weight:700;")
        lay.addWidget(self.title)
        lay.addWidget(self.value)

    def set(self, text: str, color: Optional[str] = None) -> None:
        self.value.setText(text)
