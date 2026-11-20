"""Paleta, folha de estilo e ícones vetoriais do PRISMA."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# Paleta (fundo escuro, um acento ciano e as três cores de fase).
BG = "#080f19"
SURFACE = "#101a29"
SURFACE_2 = "#17243a"
BORDER = "#24344d"
TEXT = "#edf4fc"
MUTED = "#9aabc1"
SUBTLE = "#71839c"
ACCENT = "#43d3ed"
SUCCESS = "#4fd18b"
WARNING = "#f2b84b"
DANGER = "#ef6b73"
PHASE = {"A": "#3ec6e0", "B": "#f2b84b", "C": "#e27eaf"}
PLOT_BG = SURFACE

# Ícones em traço (24×24), desenhados para o PRISMA.
_ICONS = {
    "scope": '<path d="M3 12h3l2-6 4 12 3-9 2 3h4"/>',
    "analysis": '<circle cx="12" cy="12" r="8"/><path d="M12 12l5-3M12 4v8"/>',
    "chip": '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/>',
    "code": '<path d="M9 7l-5 5 5 5M15 7l5 5-5 5"/>',
    "build": '<path d="M14 6l4 4-8 8H6v-4z"/><path d="M12 8l4 4"/>',
    "plug": '<path d="M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4"/>',
    "unplug": '<path d="M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4M4 4l16 16"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/>',
    "pause": '<path d="M9 6v12M15 6v12"/>',
    "play": '<path d="M8 5l11 7-11 7z"/>',
    "camera": '<rect x="3" y="7" width="18" height="13" rx="2"/><circle cx="12" cy="13.5" r="3.5"/><path d="M9 7l1.5-3h3L15 7"/>',
    "wave": '<path d="M3 12c2-6 4-6 6 0s4 6 6 0 4-6 6 0"/>',
    "terminal": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M12 15h5"/>',
    "open": '<path d="M3 7h6l2 2h10v10H3z"/>',
    "save": '<path d="M5 4h11l3 3v13H5z"/><path d="M8 4v5h7V4M8 20v-6h8v6"/>',
    "flash": '<path d="M13 3L5 14h6l-1 7 8-11h-6z"/>',
    "report": '<path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5M9 17v-3M12 17v-6M15 17v-2"/>',
    "record": '<circle cx="12" cy="12" r="6"/>',
}


def icon(name: str, color: str = TEXT, size: int = 20) -> QIcon:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">{_ICONS[name]}</svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    result = QIcon()
    for scale in (1, 2):
        pixmap = QPixmap(QSize(size * scale, size * scale))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        pixmap.setDevicePixelRatio(scale)
        result.addPixmap(pixmap)
    return result


STYLE = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-family: 'Segoe UI', 'DejaVu Sans', Arial; font-size: 13px; }}
QLabel {{ background: transparent; }}
QToolTip {{ background: {SURFACE_2}; color: {TEXT}; border: 1px solid #38506f; border-radius: 6px; padding: 6px 8px; }}

QFrame#rail {{ background: #0d1624; border-right: 1px solid {BORDER}; }}
QLabel#brand {{ font-size: 19px; font-weight: 800; letter-spacing: 4px; color: #ffffff; }}
QLabel#brandSub {{ color: {ACCENT}; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; }}
QLabel#railSection {{ color: {MUTED}; font-size: 10px; font-weight: 600; letter-spacing: 0.6px; }}
QPushButton#nav {{ text-align: left; background: transparent; border: 1px solid transparent; border-radius: 9px;
    padding: 10px 12px; color: {MUTED}; font-size: 13px; }}
QPushButton#nav:hover {{ background: {SURFACE_2}; color: {TEXT}; border-color: {BORDER}; }}
QPushButton#nav:checked {{ background: #10364b; color: #ffffff; border-color: #1d5269; font-weight: 600; }}

QFrame#topbar {{ background: #0b1320; border-bottom: 1px solid {BORDER}; }}
QLabel#pageTitle {{ font-size: 20px; font-weight: 700; color: #ffffff; }}
QLabel#pageDescription {{ color: {MUTED}; font-size: 12px; padding-bottom: 2px; }}
QLabel#pill {{ border-radius: 11px; padding: 3px 11px; font-weight: 600; font-size: 11px; }}

QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}
QLabel#cardCaption {{ color: {MUTED}; font-size: 12px; font-weight: 600; }}
QLabel#cardValue {{ font-size: 25px; font-weight: 700; }}
QLabel#cardHint {{ color: {SUBTLE}; font-size: 11px; }}
QLabel#meterHead {{ color: {MUTED}; font-size: 12px; font-weight: 700; padding-bottom: 5px; }}
QLabel#meterRow {{ color: {MUTED}; font-size: 13px; }}
QLabel#meterCell {{ color: {TEXT}; font-size: 15px; font-weight: 600; }}
QLabel#meterTotal {{ color: #ffffff; font-size: 15px; font-weight: 700; }}
QLabel#meterCell, QLabel#meterTotal, QLabel#meterRow {{ padding: 3px 4px; border-radius: 4px; }}
QLabel[alternateRow="true"] {{ background: #142033; }}
QLabel#meterTotal {{ background: transparent; border-left: 1px solid #27445c; }}
QLabel#meterTotal[alternateRow="true"] {{ background: #16283a; }}
QLabel#notice {{ background: #2a2110; border: 1px solid #5a4519; border-radius: 10px; padding: 8px 12px; color: {TEXT}; }}
QLabel#panelTitle {{ color: {MUTED}; font-size: 11px; font-weight: 700; letter-spacing: 1px; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#section {{ color: {SUBTLE}; font-size: 10px; font-weight: 700; letter-spacing: 1.4px; }}

QPushButton {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 9px; padding: 8px 13px; }}
QPushButton:hover {{ background: #1d304d; border-color: #3a5274; }}
QPushButton:pressed {{ background: #14203a; }}
QPushButton:focus {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {SUBTLE}; background: {SURFACE}; border-color: {BORDER}; }}
QPushButton#primary {{ background: #087f9a; border-color: #24bad6; color: #ffffff; font-weight: 700; }}
QPushButton#primary:hover {{ background: #0b96b4; border-color: {ACCENT}; }}
QPushButton#primary:disabled {{ background: {SURFACE}; border-color: {BORDER}; color: {SUBTLE}; font-weight: 400; }}
QPushButton#primary[connected="true"] {{ background: #1d4a36; border-color: #2f7a57; color: #c8f5dc; }}
QPushButton#icon {{ padding: 6px; min-width: 20px; }}
QPushButton#icon:checked {{ background: #3a2c10; border-color: #b8862b; }}
QPushButton#ghost {{ background: transparent; border: none; color: {MUTED}; padding: 4px 8px; }}
QPushButton#ghost:hover {{ color: {TEXT}; }}
QPushButton#ghost:checked {{ color: {ACCENT}; }}

QLineEdit, QDoubleSpinBox {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 10px; selection-background-color: #1c5268; }}
QLineEdit:focus, QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
QComboBox {{ background: {SURFACE_2}; border: 1px solid {BORDER}; padding: 7px 28px 7px 10px; border-radius: 8px; min-height: 18px; }}
QComboBox:hover {{ border-color: #2c3f5e; }}
QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {SURFACE_2}; border: 1px solid {BORDER}; selection-background-color: #1c3552; }}
QTabWidget::pane {{ border: none; }}
QPlainTextEdit {{ background: #080d16; color: #d7e3f0; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px;
    selection-background-color: #1c3552; }}
QPlainTextEdit#code {{ font-family: 'Cascadia Mono', Consolas, monospace; font-size: 13px; }}
QPlainTextEdit#log {{ font-family: 'Cascadia Mono', Consolas, monospace; font-size: 11px; }}
QToolButton {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 26px 7px 12px; }}
QToolButton:hover {{ background: #1c2c47; }}
QToolButton::menu-indicator {{ subcontrol-position: right center; right: 6px; }}
QTableWidget {{ background: {SURFACE}; alternate-background-color: #131e2f; gridline-color: {BORDER};
    border: 1px solid {BORDER}; border-radius: 10px; }}
QHeaderView::section {{ background: {SURFACE_2}; color: {MUTED}; border: none; padding: 7px; font-weight: 600; }}
QTableWidget::item {{ padding: 5px 8px; }}
QTableWidget::item:selected {{ background: #16435a; color: #ffffff; }}
QTableCornerButton::section {{ background: {SURFACE_2}; border: none; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 10px; margin-top: 16px; padding: 16px 12px 12px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {MUTED}; }}
QSpinBox {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 10px; }}
QSpinBox:focus {{ border-color: {ACCENT}; }}
QTabBar::tab {{ background: {SURFACE}; color: {MUTED}; padding: 9px 14px; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {ACCENT}; border-bottom-color: {ACCENT}; background: {SURFACE_2}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:hover {{ background: {ACCENT}; }}
QToolButton:focus {{ border-color: {ACCENT}; }}
QMenuBar {{ background: {BG}; color: {MUTED}; }}
QMenuBar::item {{ padding: 5px 10px; }}
QMenuBar::item:selected {{ background: {SURFACE_2}; color: {TEXT}; }}
QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: #1c3552; }}
QStatusBar {{ background: {SURFACE}; color: {MUTED}; border-top: 1px solid {BORDER}; }}
QStatusBar::item {{ border: none; }}
QCheckBox {{ spacing: 7px; color: {MUTED}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; }}
QCheckBox:focus {{ color: {ACCENT}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #26364f; border-radius: 4px; min-height: 24px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #26364f; border-radius: 4px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QProgressBar {{ background: {SURFACE_2}; border: none; border-radius: 5px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
"""


def phase_legend(symbol: str, phases="ABC") -> str:
    """Legenda colorida "━ Va  ━ Vb  ━ Vc" (ou Ia/Ib/Ic) em HTML, só com as fases ligadas."""
    return "&nbsp;&nbsp;&nbsp;".join(
        f"<span style='color:{PHASE[p]}'>━ {symbol}{p.lower()}</span>" for p in phases)


def pill_style(kind: str) -> str:
    fg, bg, border = {
        "real": (SUCCESS, "#10291e", "#1f5a3d"),
        "demo": (WARNING, "#2a2110", "#5a4519"),
        "idle": (MUTED, SURFACE_2, BORDER),
        "pause": ("#ffd890", "#3a2c10", "#b8862b"),
    }[kind]
    return f"color: {fg}; background: {bg}; border: 1px solid {border};"
