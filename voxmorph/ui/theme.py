"""Dark theme. Neutral slate + a single cyan accent - readable in a dim room,
which is where a voice changer actually gets used."""
from __future__ import annotations

COLORS = {
    "bg":        "#0e1116",
    "surface":   "#161b22",
    "surface2":  "#1c2330",
    "border":    "#2a3441",
    "text":      "#e6edf3",
    "text_dim":  "#8b98a5",
    "accent":    "#22d3ee",
    "accent_dk": "#0e7490",
    "good":      "#34d399",
    "warn":      "#fbbf24",
    "bad":       "#f87171",
    "update":    "#a78bfa",
}

STYLESHEET = f"""
QWidget {{
    background-color: {COLORS['bg']};
    color: {COLORS['text']};
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}}
QGroupBox {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 10px;
    margin-top: 16px;
    padding: 12px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {COLORS['text_dim']};
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 1px;
}}
QPushButton {{
    background-color: {COLORS['surface2']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
}}
QPushButton:hover  {{ border-color: {COLORS['accent']}; }}
QPushButton:pressed {{ background-color: {COLORS['border']}; }}
QPushButton:disabled {{ color: {COLORS['text_dim']}; border-color: {COLORS['border']}; }}
QPushButton#primary {{
    background-color: {COLORS['accent_dk']};
    border-color: {COLORS['accent']};
    color: #ffffff;
}}
QPushButton#primary:hover {{ background-color: {COLORS['accent']}; color: #06202a; }}
QPushButton#danger {{ background-color: #7f1d1d; border-color: {COLORS['bad']}; color: #fff; }}

QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {COLORS['surface2']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 18px;
}}
QComboBox:hover {{ border-color: {COLORS['accent']}; }}
QComboBox QAbstractItemView {{
    background-color: {COLORS['surface2']};
    border: 1px solid {COLORS['border']};
    selection-background-color: {COLORS['accent_dk']};
    outline: none;
}}
QSlider::groove:horizontal {{
    height: 4px; background: {COLORS['border']}; border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {COLORS['accent']};
    width: 14px; height: 14px; margin: -6px 0; border-radius: 7px;
}}
QSlider::sub-page:horizontal {{ background: {COLORS['accent_dk']}; border-radius: 2px; }}

QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid {COLORS['border']}; background: {COLORS['surface2']};
}}
QCheckBox::indicator:checked {{
    background: {COLORS['accent']}; border-color: {COLORS['accent']};
}}
QTabWidget::pane {{ border: 1px solid {COLORS['border']}; border-radius: 10px; top: -1px; }}
QTabBar::tab {{
    background: transparent; padding: 9px 18px; margin-right: 2px;
    border-top-left-radius: 8px; border-top-right-radius: 8px;
    color: {COLORS['text_dim']}; font-weight: 600;
}}
QTabBar::tab:selected {{ background: {COLORS['surface']}; color: {COLORS['accent']}; }}
QTabBar::tab:hover:!selected {{ color: {COLORS['text']}; }}

QListWidget {{
    background: {COLORS['surface']}; border: 1px solid {COLORS['border']};
    border-radius: 8px; outline: none; padding: 4px;
}}
QListWidget::item {{ padding: 9px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {COLORS['accent_dk']}; color: #fff; }}
QListWidget::item:hover:!selected {{ background: {COLORS['surface2']}; }}

QProgressBar {{
    background: {COLORS['surface2']}; border: 1px solid {COLORS['border']};
    border-radius: 6px; height: 8px; text-align: center;
}}
QProgressBar::chunk {{ background: {COLORS['accent']}; border-radius: 5px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {COLORS['border']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{
    background: {COLORS['surface2']}; color: {COLORS['text']};
    border: 1px solid {COLORS['accent']}; padding: 6px; border-radius: 6px;
}}
QLabel#hint {{ color: {COLORS['text_dim']}; font-size: 11px; }}
QLabel#h1 {{ font-size: 20px; font-weight: 700; }}
QLabel#stat {{ font-family: 'Consolas','JetBrains Mono',monospace; color: {COLORS['text_dim']}; }}
"""
