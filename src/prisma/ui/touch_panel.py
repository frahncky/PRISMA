"""Painel touch em tela cheia no estilo de um medidor inteligente.

Abas grandes na parte de baixo: Visão geral (tela inicial, tudo numa tela),
Valores, Formas de onda, Fasores e harmônicas, Energia e demanda e Tendências.
Tocar num bloco dos Valores ou num gráfico da Visão geral abre a aba com o
detalhe. Alertas (THD, desequilíbrio, sequência inversa) aparecem em todas as abas.
Sem dados novos da placa (conexão caída ou placa calada), uma faixa amarela avisa
que os valores na tela são os últimos recebidos.

No modo quiosque (tela dedicada, ``kiosk=True``) o botão Sair só age com toque
longo, para ninguém fechar o medidor sem querer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QButtonGroup, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from prisma.core.measurement import (LIMIT_THD_PERCENT, LIMIT_UNBALANCE_PERCENT, Measurement, MeterStats,
                                     load_nature, sequence_components, totals)
from prisma.core.query import alerts
from prisma.ui import theme


@dataclass
class PanelData:
    """O que o painel precisa a cada atualização."""
    result: Measurement | None
    mode: str = ""
    stats: MeterStats | None = None
    t: np.ndarray | None = None          # instantes das últimas amostras (s)
    voltages: np.ndarray | None = None   # N × 3
    currents: np.ndarray | None = None   # N × 3 ou None
    age_s: float | None = None           # segundos desde o último dado da placa (None: sem placa)


PanelSource = Callable[[], PanelData]
SUMMARY_KEYS = ("vA", "vB", "vC", "iA", "iB", "iC", "power", "pf", "freq", "energy", "thd", "unb")
# Do geral para o detalhe; a Visão geral é a tela inicial.
PAGES = ("Visão geral", "Valores", "Formas de onda", "Fasores e harmônicas", "Energia e demanda", "Tendências")
ALL, SUMMARY, WAVES, PHASORS, ENERGY, TRENDS = range(len(PAGES))

TOUCH_STYLE = f"""
QWidget#touchPanel {{ background: {theme.BG}; }}
QPushButton#tile {{ background: {theme.SURFACE}; border: 1px solid {theme.BORDER}; border-radius: 18px;
    text-align: left; padding: 0; }}
QPushButton#tile:pressed {{ background: #14304a; border-color: {theme.ACCENT}; }}
QLabel#tileCaption {{ color: {theme.MUTED}; font-size: 19px; font-weight: 600; }}
QLabel#tileValue {{ font-size: 50px; font-weight: 700; }}
QLabel#tileHint {{ color: {theme.MUTED}; font-size: 16px; }}
QLabel#touchTitle {{ font-size: 24px; font-weight: 800; letter-spacing: 4px; color: #ffffff; }}
QLabel#pill {{ font-size: 15px; padding: 6px 16px; border-radius: 15px; }}
QLabel#touchClock {{ color: {theme.TEXT}; font-size: 20px; font-weight: 600; }}
QLabel#touchAlert {{ background: #3a1e22; color: #ffd0d3; border: 1px solid {theme.DANGER}; border-radius: 14px;
    padding: 12px 18px; font-size: 18px; font-weight: 600; }}
QLabel#touchLink {{ background: #3a3018; color: #ffe2a8; border: 1px solid {theme.WARNING}; border-radius: 14px;
    padding: 12px 18px; font-size: 20px; font-weight: 700; }}
QLabel#plotLegend {{ font-size: 17px; font-weight: 700; }}
QLabel#plotTitle {{ color: {theme.MUTED}; font-size: 17px; font-weight: 700; }}
QWidget#plotCard {{ background: {theme.SURFACE}; border: 1px solid {theme.BORDER}; border-radius: 18px; }}
QLabel#ovHead {{ color: {theme.MUTED}; font-size: 18px; font-weight: 700; }}
QLabel#ovRow {{ color: {theme.MUTED}; font-size: 19px; }}
QLabel#ovCell {{ color: {theme.TEXT}; font-size: 28px; font-weight: 700; }}
QLabel#ovTotal {{ color: #ffffff; font-size: 28px; font-weight: 800; }}
QLabel#kpiCaption {{ color: {theme.MUTED}; font-size: 16px; font-weight: 600; }}
QLabel#kpiValue {{ font-size: 31px; font-weight: 700; }}
QPushButton#touchButton {{ font-size: 18px; font-weight: 600; min-height: 60px; min-width: 64px;
    padding: 0 22px; border-radius: 14px; }}
QPushButton#navTab {{ font-size: 19px; font-weight: 600; min-height: 64px; border-radius: 14px;
    background: {theme.SURFACE}; color: {theme.MUTED}; }}
QPushButton#navTab:checked {{ background: #12324a; border-color: {theme.ACCENT}; color: #ffffff; }}
"""


def _br(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


def _si(value: float, unit: str) -> str:
    """Valor com prefixo k/M e vírgula decimal."""
    if abs(value) >= 1e6:
        return f"{_br(value / 1e6, 2)} M{unit}"
    if abs(value) >= 1000:
        return f"{_br(value / 1000, 2)} k{unit}"
    return f"{value:.0f} {unit}" if abs(value) >= 10 or value == 0 else f"{_br(value, 2)} {unit}"


def _how(text: str, word: str) -> str:
    """Valor da coluna Trifásico com o modo de cálculo em letra pequena ("média" ou "soma")."""
    return f"{text} <span style='color:{theme.MUTED}; font-size:15px; font-weight:400'>{word}</span>"


def _series_legend(series) -> str:
    """Legenda colorida em HTML: ((traço, nome, cor), ...), ex.: ━ Potência  ┅ Demanda."""
    return "&nbsp;&nbsp;&nbsp;".join(f"<span style='color:{color}'>{mark} {name}</span>" for mark, name, color in series)


def _pf(value: float, reactive: float, suffix_px: int) -> str:
    """FP com a natureza em letra menor ao lado: "0,900 Indut." (rich text)."""
    nature = load_nature(reactive)
    text = _br(value, 3)
    return f"{text} <span style='font-size:{suffix_px}px'>{nature}</span>" if nature else text


def _duration(seconds: float) -> str:
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:d}:{minutes:02d}:{sec:02d}"


def _ago(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h".replace(".", ",")


class Tile(QPushButton):
    """Bloco tocável com legenda, valor grande e dica."""

    def __init__(self, caption: str, color: str = theme.TEXT) -> None:
        super().__init__()
        self.setObjectName("tile")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(110)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 14, 22, 14)
        layout.setSpacing(2)
        self.caption = QLabel(caption)
        self.caption.setObjectName("tileCaption")
        self.value = QLabel("---")
        self.value.setObjectName("tileValue")
        self.value.setStyleSheet(f"color: {color}")
        self.hint = QLabel("")
        self.hint.setObjectName("tileHint")
        for label in (self.caption, self.value, self.hint):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(label)
        layout.addStretch(1)

    def set_value(self, value: str, hint: str = "", warn: bool = False) -> None:
        self.value.setText(value)
        self.hint.setText(hint)
        self.hint.setStyleSheet(f"color: {theme.WARNING}" if warn else "")


SI_UNITS = {"V": "Tensão", "A": "Corrente"}


def _touch_plot(left: str = "", bottom: str = "") -> pg.PlotWidget:
    plot = pg.PlotWidget()
    plot.setBackground(theme.SURFACE)
    plot.showGrid(x=True, y=True, alpha=0.15)
    plot.setMenuEnabled(False)
    plot.setMouseEnabled(x=False, y=False)
    plot.hideButtons()
    font = QFont("Segoe UI", 14)
    for axis in ("left", "bottom"):
        item = plot.getAxis(axis)
        item.setPen(pg.mkPen(theme.BORDER))
        item.setTextPen(pg.mkPen(theme.MUTED))
        item.setTickFont(font)
    plot.getAxis("left").setWidth(64)  # cabe "-200" na fonte grande (senão o rótulo some)
    plot.getAxis("bottom").setHeight(56 if bottom else 34)  # números + rótulo sem sobrepor
    style = {"color": theme.MUTED, "font-size": "13pt"}
    for axis, text in (("left", left), ("bottom", bottom)):
        if text in SI_UNITS:
            # Com a unidade separada, o pyqtgraph troca o prefixo sozinho: mV, V, kV.
            plot.setLabel(axis, SI_UNITS[text], units=text, **style)
        elif text:
            # Unidade já no texto (kW, ms, %): sem fator "(x0.001)" ao lado.
            plot.setLabel(axis, text, **style)
            plot.getAxis(axis).enableAutoSIPrefix(False)
    return plot


def _plot_card(title: str, plot: pg.PlotWidget, legend: str = "") -> tuple[QWidget, QLabel]:
    """``legend`` é HTML pronto: ``theme.phase_legend("V")`` ou ``_series_legend(...)``."""
    """Card com título e, à direita, a legenda das fases (fora da área das curvas)."""
    card = QWidget()
    card.setObjectName("plotCard")
    card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 12, 16, 10)
    head = QHBoxLayout()
    label = QLabel(title)
    label.setObjectName("plotTitle")
    head.addWidget(label)
    head.addStretch(1)
    if legend:
        key = QLabel(legend)
        key.setObjectName("plotLegend")
        head.addWidget(key)
    layout.addLayout(head)
    layout.addWidget(plot, stretch=1)
    return card, label


STALE_S = 3.0  # a placa manda um resumo por segundo
HOLD_TO_EXIT_MS = 2000


def link_problem(mode: str, age_s: float | None) -> str:
    """Texto da faixa de aviso quando não chegam dados novos da placa; "" se está tudo bem."""
    if mode.startswith("DEMONSTRAÇÃO"):
        return ""
    if mode.startswith("AQUISIÇÃO SERIAL REAL"):
        if age_s is not None and age_s > STALE_S:
            return f"Sem dados novos da placa há {_ago(age_s)}: valores congelados"
        return ""
    if mode.startswith("RECONECTANDO"):
        target = mode.split(" — ")[0].removeprefix("RECONECTANDO A ")
        return f"Conexão perdida: reconectando a {target}…  (valores congelados)"
    if mode.startswith(("CONECTANDO", "SERIAL ")) and "DESCONECTADA" not in mode:
        return "Aguardando dados da placa…"
    return "Sem conexão com a placa" + (f": {mode.split(' — ', 1)[1].lower()}" if " — " in mode else "")


class HoldButton(QPushButton):
    """Botão que só dispara ``held`` depois de segurado por ``hold_ms``."""
    held = Signal()

    def __init__(self, text: str, hold_ms: int = HOLD_TO_EXIT_MS) -> None:
        super().__init__(text)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(hold_ms)
        self._timer.timeout.connect(self.held)
        self.pressed.connect(self._timer.start)
        self.released.connect(self._timer.stop)


class TouchPanel(QWidget):
    closed = Signal()

    def __init__(self, source: PanelSource, parent: QWidget | None = None, kiosk: bool = False) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.kiosk = kiosk
        self.setObjectName("touchPanel")
        self.setWindowTitle("PRISMA · Painel")
        self.setStyleSheet(theme.STYLE + TOUCH_STYLE)
        self.source = source
        self._stats: MeterStats | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(12)
        root.addLayout(self._build_header())
        self.link_banner = QLabel("")
        self.link_banner.setObjectName("touchLink")
        self.link_banner.setWordWrap(True)
        self.link_banner.hide()
        root.addWidget(self.link_banner)
        self.alert_label = QLabel("")
        self.alert_label.setObjectName("touchAlert")
        self.alert_label.setWordWrap(True)
        self.alert_label.hide()
        root.addWidget(self.alert_label)

        self.pages = QStackedWidget()
        builders = {ALL: self._build_all, SUMMARY: self._build_summary, WAVES: self._build_waves,
                    PHASORS: self._build_phasors, ENERGY: self._build_energy, TRENDS: self._build_trends}
        for index in range(len(PAGES)):
            self.pages.addWidget(builders[index]())
        root.addWidget(self.pages, stretch=1)

        nav = QHBoxLayout()
        nav.setSpacing(10)
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        for index, name in enumerate(PAGES):
            button = QPushButton(name)
            button.setObjectName("navTab")
            button.setCheckable(True)
            self.nav.addButton(button, index)
            nav.addWidget(button)
        self.nav.idClicked.connect(self.show_page)
        self.nav.button(ALL).setChecked(True)
        self.pages.setCurrentIndex(ALL)
        root.addLayout(nav)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(250)
        self.refresh()

    # --- construção ---------------------------------------------------------
    def _build_header(self) -> QHBoxLayout:
        from prisma.ui.main_window import app_icon
        top = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(QSize(48, 48)))
        top.addWidget(logo)
        top.addSpacing(6)
        title = QLabel("PRISMA")
        title.setObjectName("touchTitle")
        top.addWidget(title)
        top.addSpacing(18)
        self.mode_label = QLabel("")
        self.mode_label.setObjectName("pill")
        top.addWidget(self.mode_label, alignment=Qt.AlignmentFlag.AlignVCenter)
        top.addStretch(1)
        self.clock = QLabel("")
        self.clock.setObjectName("touchClock")
        top.addWidget(self.clock)
        top.addSpacing(18)
        if self.kiosk:
            close = HoldButton("Sair (segure)")
            close.setToolTip("Segure por 2 s para sair do painel e abrir a janela de manutenção")
            close.held.connect(self.close)
        else:
            close = QPushButton("Sair")
            close.clicked.connect(self.close)
        close.setObjectName("touchButton")
        self.close_button = close
        top.addWidget(close)
        return top

    def _grid(self, spec, columns: int = 3) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        for index, (key, caption, color, target) in enumerate(spec):
            tile = Tile(caption, color)
            if target is not None:
                tile.clicked.connect(lambda _=False, page=target: self.show_page(page))
            grid.addWidget(tile, index // columns, index % columns)
            self.tiles[key] = tile
        return page

    def _build_summary(self) -> QWidget:
        self.tiles: dict[str, Tile] = {}
        waves, phasors, trends, energy = WAVES, PHASORS, TRENDS, ENERGY
        return self._grid((
            ("vA", "Tensão · fase A", theme.PHASE["A"], waves),
            ("vB", "Tensão · fase B", theme.PHASE["B"], waves),
            ("vC", "Tensão · fase C", theme.PHASE["C"], waves),
            ("iA", "Corrente · fase A", theme.PHASE["A"], waves),
            ("iB", "Corrente · fase B", theme.PHASE["B"], waves),
            ("iC", "Corrente · fase C", theme.PHASE["C"], waves),
            ("power", "Potência ativa total", theme.TEXT, trends),
            ("pf", "Fator de potência total", theme.TEXT, phasors),
            ("freq", "Frequência", theme.ACCENT, waves),
            ("energy", "Energia ativa", theme.SUCCESS, energy),
            ("thd", "THD tensão · fase A", theme.TEXT, phasors),
            ("unb", "Desequilíbrio de tensão", theme.TEXT, phasors),
        ))

    def _build_all(self) -> QWidget:
        """Visão geral numa tela: tabela por fase, indicadores e três gráficos em miniatura."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(12)
        table = QWidget()
        table.setObjectName("plotCard")
        table.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        grid = QGridLayout(table)
        grid.setContentsMargins(20, 12, 20, 12)
        grid.setHorizontalSpacing(16)
        grid.setColumnStretch(0, 3)
        for column, name in enumerate(("A", "B", "C", "T"), start=1):
            grid.setColumnStretch(column, 3 if name == "T" else 2)
            head = QLabel("Trifásico" if name == "T" else f"Fase {name}")
            head.setObjectName("ovHead")
            head.setAlignment(Qt.AlignmentFlag.AlignRight)
            if name != "T":
                head.setStyleSheet(f"color: {theme.PHASE[name]}")
            grid.addWidget(head, 0, column)
        self.ov_cells: dict[tuple[str, str], QLabel] = {}
        rows = (("v", "Tensão (V)"), ("i", "Corrente (A)"), ("p", "Potência ativa"), ("pf", "Fator de potência"))
        for row, (key, caption) in enumerate(rows, start=1):
            label = QLabel(caption)
            label.setObjectName("ovRow")
            grid.addWidget(label, row, 0)
            for column, name in enumerate(("A", "B", "C", "T"), start=1):
                cell = QLabel("---")
                cell.setObjectName("ovTotal" if name == "T" else "ovCell")
                cell.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                grid.addWidget(cell, row, column)
                self.ov_cells[(key, name)] = cell
        top.addWidget(table, stretch=3)
        kpis = QGridLayout()
        kpis.setSpacing(12)
        self.ov_kpis: dict[str, QLabel] = {}
        for index, (key, caption, color) in enumerate((
                ("freq", "Frequência", theme.ACCENT), ("energy", "Energia ativa", theme.SUCCESS),
                ("thd", "THD tensão A", theme.TEXT), ("demand", "Demanda 15 min", theme.WARNING),
                ("unb", "Desequilíbrio", theme.TEXT), ("demand_max", "Demanda máxima", theme.WARNING))):
            card = QWidget()
            card.setObjectName("plotCard")
            card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            box = QVBoxLayout(card)
            box.setContentsMargins(16, 8, 16, 8)
            box.setSpacing(0)
            title = QLabel(caption)
            title.setObjectName("kpiCaption")
            value = QLabel("---")
            value.setObjectName("kpiValue")
            value.setStyleSheet(f"color: {color}")
            box.addWidget(title)
            box.addWidget(value)
            kpis.addWidget(card, index // 2, index % 2)
            self.ov_kpis[key] = value
        top.addLayout(kpis, stretch=2)
        layout.addLayout(top, stretch=5)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        self.ov_wave = _touch_plot()
        self.ov_wave_curves = {p: self.ov_wave.plot(pen=pg.mkPen(theme.PHASE[p], width=2), name=f"V{p.lower()}")
                               for p in "ABC"}
        self.ov_phasor = _touch_plot()
        _phasor_axes(self.ov_phasor)
        self.ov_harmonic = _touch_plot()
        self.ov_harmonic.showGrid(x=False, y=True, alpha=0.15)
        # A forma de onda ganha mais largura; o diagrama fasorial é quadrado.
        for title, plot, target, stretch, legend in (("TENSÕES", self.ov_wave, WAVES, 4, theme.phase_legend("V")),
                                                     ("FASORES", self.ov_phasor, PHASORS, 3, ""),
                                                     ("HARMÔNICAS", self.ov_harmonic, PHASORS, 3, "")):
            card, _ = _plot_card(title, plot, legend)
            # Tocar num gráfico em miniatura abre a aba com ele em tamanho grande.
            plot.scene().sigMouseClicked.connect(lambda _event, page=target: self.show_page(page))
            bottom.addWidget(card, stretch=stretch)
        layout.addLayout(bottom, stretch=6)
        return page

    def _build_waves(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.wave_v = _touch_plot("V", "ms")
        self.wave_i = _touch_plot("A", "ms")
        self.wave_v_curves = {p: self.wave_v.plot(pen=pg.mkPen(theme.PHASE[p], width=3), name=f"V{p.lower()}")
                              for p in "ABC"}
        self.wave_i_curves = {p: self.wave_i.plot(pen=pg.mkPen(theme.PHASE[p], width=3), name=f"I{p.lower()}")
                              for p in "ABC"}
        card, _ = _plot_card("TENSÕES", self.wave_v, theme.phase_legend("V"))
        layout.addWidget(card, stretch=1)
        card, self.wave_i_title = _plot_card("CORRENTES", self.wave_i, theme.phase_legend("I"))
        layout.addWidget(card, stretch=1)
        return page

    def _build_phasors(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.phasor_plot = _touch_plot()
        _phasor_axes(self.phasor_plot)
        card, self.phasor_title = _plot_card("FASORES", self.phasor_plot)
        layout.addWidget(card, stretch=4)
        self.harmonic_plot = _touch_plot("% da fundamental")
        self.harmonic_plot.showGrid(x=False, y=True, alpha=0.15)
        card, self.harmonic_title = _plot_card("HARMÔNICAS · TENSÃO FASE A", self.harmonic_plot)
        layout.addWidget(card, stretch=5)
        return page

    def _build_trends(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.trend_v = _touch_plot("V", "minutos")
        self.trend_p = _touch_plot("kW", "minutos")
        self.trend_v_curves = {p: self.trend_v.plot(pen=pg.mkPen(theme.PHASE[p], width=3)) for p in "ABC"}
        self.trend_p_curve = self.trend_p.plot(pen=pg.mkPen(theme.SUCCESS, width=3),
                                               fillLevel=0, brush=pg.mkBrush(79, 209, 139, 40))
        self.trend_d_curve = self.trend_p.plot(pen=pg.mkPen(theme.WARNING, width=3, style=Qt.PenStyle.DashLine))
        card, _ = _plot_card("TENSÃO POR FASE", self.trend_v, theme.phase_legend("V"))
        layout.addWidget(card, stretch=1)
        card, self.trend_p_title = _plot_card(
            "POTÊNCIA", self.trend_p,
            _series_legend((("━", "Potência ativa total", theme.SUCCESS), ("┅", "Demanda 15 min", theme.WARNING))))
        layout.addWidget(card, stretch=1)
        return page

    def _build_energy(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._grid((
            ("e_imp", "Energia ativa importada", theme.SUCCESS, None),
            ("e_exp", "Energia ativa exportada", theme.TEXT, None),
            ("e_q", "Energia reativa", theme.TEXT, None),
            ("demand", "Demanda ativa · 15 min", theme.WARNING, TRENDS),
            ("demand_max", "Demanda máxima", theme.WARNING, TRENDS),
            ("elapsed", "Tempo de medição", theme.TEXT, None),
            ("mmA", "Tensão mín – máx · fase A", theme.PHASE["A"], None),
            ("mmB", "Tensão mín – máx · fase B", theme.PHASE["B"], None),
            ("mmC", "Tensão mín – máx · fase C", theme.PHASE["C"], None),
        )), stretch=1)
        row = QHBoxLayout()
        row.addStretch(1)
        reset = QPushButton("Zerar energia, demanda e mín/máx")
        reset.setObjectName("touchButton")
        reset.clicked.connect(self._confirm_reset)
        row.addWidget(reset)
        layout.addLayout(row)
        return page

    # --- navegação ------------------------------------------------------------
    def show_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.nav.button(index).setChecked(True)
        self.refresh()

    def _confirm_reset(self) -> None:
        if self._stats is None:
            return
        answer = QMessageBox.question(self, "Zerar medidores",
                                      "Zerar energia, demanda máxima e valores mínimos/máximos?")
        if answer == QMessageBox.StandardButton.Yes:
            self._stats.reset()
            self.refresh()

    # --- atualização --------------------------------------------------------
    def refresh(self) -> None:
        data = self.source()
        self._stats = data.stats
        self.clock.setText(datetime.now().strftime("%d/%m/%Y   %H:%M:%S"))
        kind = "real" if data.mode.startswith("AQUISIÇÃO SERIAL REAL") else (
            "demo" if data.mode.startswith("DEMONSTRAÇÃO") else "idle")
        self.mode_label.setText(data.mode.split(" — ")[0].capitalize() or "Sem dados")
        self.mode_label.setToolTip(data.mode)
        self.mode_label.setStyleSheet(theme.pill_style(kind))
        problem = link_problem(data.mode, data.age_s)
        self.link_banner.setText("⚠  " + problem)
        self.link_banner.setVisible(bool(problem))
        result = data.result
        found = alerts(result) if result is not None else []
        self.alert_label.setText("⚠  " + "   ·   ".join(found))
        self.alert_label.setVisible(bool(found))
        self._refresh_summary(result, data.stats)
        self._refresh_energy(data.stats)
        page = self.pages.currentIndex()
        if page == ALL:
            self._refresh_all(data)
        elif page == WAVES:
            self._refresh_waves(data)
        elif page == PHASORS:
            self._refresh_phasors(result)
        elif page == TRENDS:
            self._refresh_trends(data.stats)

    def _refresh_summary(self, result: Measurement | None, stats: MeterStats | None) -> None:
        if result is None:
            for key in SUMMARY_KEYS:
                self.tiles[key].set_value("---", "aguardando sinal")
            return
        for phase in "ABC":
            self.tiles[f"v{phase}"].set_value(f"{_br(result.rms[phase], 1)} V")
            current = result.current_rms.get(phase)
            self.tiles[f"i{phase}"].set_value("---" if current is None else f"{_br(current, 2)} A",
                                              "" if current is not None else "sem correntes")
        self.tiles["freq"].set_value(f"{_br(result.frequency_hz, 2)} Hz")
        total = totals(result)
        if total is not None:
            self.tiles["power"].set_value(_si(total.active_w, "W"), f"aparente {_si(total.apparent_va, 'VA')}")
            pf = total.power_factor
            hint = {"Indut.": "carga indutiva", "Capac.": "carga capacitiva"}.get(load_nature(total.reactive_var), "")
            self.tiles["pf"].set_value("---" if pf is None else _pf(pf, total.reactive_var, 28), hint)
            self.tiles["energy"].set_value("---" if stats is None else _si(stats.energy.active_wh, "Wh"),
                                           "" if stats is None else f"reativa {_si(stats.energy.reactive_varh, 'varh')}")
        else:
            for key in ("power", "pf", "energy"):
                self.tiles[key].set_value("---", "sem correntes")
        if result.thd_percent is None:
            self.tiles["thd"].set_value("---")
        else:
            over = result.thd_percent > LIMIT_THD_PERCENT
            self.tiles["thd"].set_value(f"{_br(result.thd_percent, 1)} %",
                                        f"acima de {LIMIT_THD_PERCENT:.0f} % (PRODIST)" if over else "", warn=over)
        unbalance = sequence_components(result.phasors).unbalance_percent
        if unbalance is None:
            self.tiles["unb"].set_value("---")
        else:
            over = unbalance > LIMIT_UNBALANCE_PERCENT
            self.tiles["unb"].set_value(f"{_br(unbalance, 2)} %",
                                        f"acima de {LIMIT_UNBALANCE_PERCENT:.0f} % (PRODIST)" if over else "", warn=over)

    def _refresh_energy(self, stats: MeterStats | None) -> None:
        if stats is None:
            for key in ("e_imp", "e_exp", "e_q", "demand", "demand_max", "elapsed", "mmA", "mmB", "mmC"):
                self.tiles[key].set_value("---", "sem contadores")
            return
        energy = stats.energy
        self.tiles["e_imp"].set_value(_si(energy.import_wh, "Wh"), "consumida da rede")
        self.tiles["e_exp"].set_value(_si(energy.export_wh, "Wh"), "injetada na rede")
        self.tiles["e_q"].set_value(_si(energy.reactive_varh, "varh"), "fundamental")
        demand = stats.demand_w
        self.tiles["demand"].set_value("---" if demand is None else _si(demand, "W"), "média móvel de P")
        if stats.max_demand_w is None:
            self.tiles["demand_max"].set_value("---")
        else:
            self.tiles["demand_max"].set_value(_si(stats.max_demand_w, "W"),
                                               f"em {stats.max_demand_at:%d/%m %H:%M:%S}")
        self.tiles["elapsed"].set_value(_duration(energy.seconds), "desde o último zeramento")
        for phase in "ABC":
            tile = self.tiles[f"mm{phase}"]
            if phase not in stats.v_min:
                tile.set_value("---")
                continue
            i_max = stats.i_max.get(phase)
            tile.set_value(f"{stats.v_min[phase]:.0f} – {stats.v_max[phase]:.0f} V",
                           "" if i_max is None else f"corrente máx {_br(i_max, 2)} A")

    def _refresh_all(self, data: PanelData) -> None:
        result, stats = data.result, data.stats
        cells, kpis = self.ov_cells, self.ov_kpis
        for cell in cells.values():
            cell.setText("---")
        for label in kpis.values():
            label.setText("---")
        if stats is not None:
            kpis["energy"].setText(_si(stats.energy.active_wh, "Wh"))
            if stats.demand_w is not None:
                kpis["demand"].setText(_si(stats.demand_w, "W"))
            if stats.max_demand_w is not None:
                kpis["demand_max"].setText(_si(stats.max_demand_w, "W"))
        _draw_waves(data, self.ov_wave_curves, self.ov_wave)
        _draw_phasors(self.ov_phasor, result, labels=False)
        _draw_harmonics(self.ov_harmonic, result)
        if result is None:
            return
        for phase in "ABC":
            cells[("v", phase)].setText(_br(result.rms[phase], 1))
        cells[("v", "T")].setText(_how(_br(sum(result.rms.values()) / 3, 1), "média"))
        cells[("v", "T")].setToolTip("Média das três fases")
        total = totals(result)
        if total is not None:
            for phase in "ABC":
                power = result.power[phase]
                cells[("i", phase)].setText(_br(result.current_rms[phase], 2))
                cells[("p", phase)].setText(_si(power.active_w, "W"))
                cells[("pf", phase)].setText("---" if power.power_factor is None
                                             else _pf(power.power_factor, power.reactive_fundamental_var, 17))
            cells[("i", "T")].setText(_how(_br(sum(result.current_rms.values()) / 3, 2), "média"))
            cells[("p", "T")].setText(_how(_si(total.active_w, "W"), "soma"))
            cells[("pf", "T")].setText("---" if total.power_factor is None
                                       else _pf(total.power_factor, total.reactive_var, 17))
        kpis["freq"].setText(f"{_br(result.frequency_hz, 2)} Hz")
        if result.thd_percent is not None:
            kpis["thd"].setText(f"{_br(result.thd_percent, 1)} %")
        unbalance = sequence_components(result.phasors).unbalance_percent
        if unbalance is not None:
            kpis["unb"].setText(f"{_br(unbalance, 2)} %")

    def _refresh_waves(self, data: PanelData) -> None:
        _draw_waves(data, self.wave_v_curves, self.wave_v, self.wave_i_curves, self.wave_i)
        has_i = (data.currents is not None and data.voltages is not None
                 and data.currents.shape == data.voltages.shape)
        self.wave_i_title.setText("CORRENTES" if has_i else "CORRENTES · sem canais de corrente")

    def _refresh_phasors(self, result: Measurement | None) -> None:
        with_currents = _draw_phasors(self.phasor_plot, result)
        self.phasor_title.setText("FASORES" if with_currents else "FASORES DE TENSÃO")
        thd = _draw_harmonics(self.harmonic_plot, result)
        self.harmonic_title.setText("HARMÔNICAS · taxa de amostragem insuficiente" if thd is None
                                    else f"HARMÔNICAS · TENSÃO FASE A · THD {_br(thd, 1)} %")

    def _refresh_trends(self, stats: MeterStats | None) -> None:
        points = list(stats.trend) if stats is not None else []
        _draw_power_trend(self.trend_p, self.trend_p_curve, self.trend_d_curve, stats)
        if not points:
            for curve in self.trend_v_curves.values():
                curve.setData([], [])
            return
        x = np.array([(p.t - points[-1].t) / 60 for p in points])
        volts = np.array([p.voltage for p in points])
        for i, phase in enumerate("ABC"):
            self.trend_v_curves[phase].setData(x, volts[:, i])
        # Faixa mínima de ±5 % da média: ruído de décimos de volt não parece oscilação.
        low, high = float(volts.min()), float(volts.max())
        half = max((high - low) / 2 * 1.2, 0.05 * abs(volts.mean()), 1e-3)
        self.trend_v.setYRange((low + high) / 2 - half, (low + high) / 2 + half, padding=0)
        self.trend_v.setXRange(min(x[0], -1.0), 0.0, padding=0.01)

    def keyPressEvent(self, event) -> None:  # Esc sai do painel (útil com teclado)
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self.timer.stop()
        super().closeEvent(event)
        self.closed.emit()


def _rising_edge(t: np.ndarray, values: np.ndarray, span: float) -> int:
    """Primeira subida da fase com mais sinal que ainda deixa ``span`` segundos à frente."""
    channel = int(np.argmax(np.ptp(values, axis=0)))
    y = values[:, channel] - values[:, channel].mean()
    level = 0.1 * np.ptp(y)
    rising = np.flatnonzero((y[:-1] < level) & (y[1:] >= level)) + 1
    rising = rising[t[rising] + span <= t[-1]]
    if rising.size:
        return int(rising[0])
    return int(np.searchsorted(t, t[-1] - span))


def _phasor_axes(plot: pg.PlotWidget) -> None:
    plot.setAspectLocked(True)
    plot.hideAxis("left")
    plot.hideAxis("bottom")


def _draw_waves(data: PanelData, curves_v, plot_v, curves_i=None, plot_i=None) -> None:
    """Dois ciclos a partir de uma subida: a forma de onda fica parada na tela."""
    t, v = data.t, data.voltages
    if t is None or v is None or len(t) < 12:
        for curve in (*curves_v.values(), *(curves_i or {}).values()):
            curve.setData([], [])
        return
    frequency = data.result.frequency_hz if data.result is not None else 60.0
    span = 2 / frequency
    start = _rising_edge(t, v, span)
    keep = (t >= t[start]) & (t <= t[start] + span)
    x = (t[keep] - t[start]) * 1000
    for i, phase in enumerate("ABC"):
        curves_v[phase].setData(x, v[keep, i])
    plot_v.setXRange(0, span * 1000, padding=0)
    _symmetric(plot_v, v[keep])
    if curves_i is not None:
        currents = data.currents
        has_i = currents is not None and currents.shape == v.shape
        for i, phase in enumerate("ABC"):
            curves_i[phase].setData(x if has_i else [], currents[keep, i] if has_i else [])
        plot_i.setXRange(0, span * 1000, padding=0)
        if has_i:
            _symmetric(plot_i, currents[keep])


def _draw_phasors(plot: pg.PlotWidget, result: Measurement | None, labels: bool = True) -> bool:
    """Tensão (cheio) e corrente em escala (tracejado), fase A em 0°. Devolve se há correntes."""
    plot.clear()
    if result is None:
        return False
    reference = np.exp(-1j * np.angle(result.phasors["A"]))
    radius = max(abs(p) for p in result.phasors.values()) or 1.0
    plot.addItem(pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen(theme.BORDER)))
    plot.addItem(pg.InfiniteLine(pos=0, angle=90, pen=pg.mkPen(theme.BORDER)))
    circle = np.exp(1j * np.linspace(0, 2 * np.pi, 120)) * radius
    plot.plot(circle.real, circle.imag, pen=pg.mkPen(theme.BORDER, style=Qt.PenStyle.DotLine))
    i_peak = max((abs(p) for p in result.current_phasors.values()), default=0.0)
    i_scale = 0.65 * radius / i_peak if i_peak > 1e-12 else None
    for phase in "ABC":
        color = theme.PHASE[phase]
        v = result.phasors[phase] * reference
        plot.plot([0, v.real], [0, v.imag], pen=pg.mkPen(color, width=5 if labels else 3),
                  symbol="o", symbolSize=10 if labels else 6, symbolBrush=color, symbolPen=None)
        _tag(plot, f"V{phase.lower()}", color, v * 1.16, 14 if labels else 11)
        if i_scale is not None:
            current = result.current_phasors[phase] * reference * i_scale
            plot.plot([0, current.real], [0, current.imag],
                      pen=pg.mkPen(color, width=3 if labels else 2, style=Qt.PenStyle.DashLine))
            _tag(plot, f"I{phase.lower()}", color, current * 1.22, 13 if labels else 10)
    limit = radius * 1.3
    plot.setXRange(-limit, limit, padding=0)
    plot.setYRange(-limit, limit, padding=0)
    return i_scale is not None


def _draw_harmonics(plot: pg.PlotWidget, result: Measurement | None) -> float | None:
    """Barras h2…hN da tensão da fase A (amarelas acima do limite). Devolve o THD."""
    plot.clear()
    if result is None or result.thd_percent is None or len(result.harmonic_percent) < 2:
        return None
    heights = np.array(result.harmonic_percent[1:])
    orders = np.arange(2, len(result.harmonic_percent) + 1)
    over = result.thd_percent > LIMIT_THD_PERCENT
    plot.addItem(pg.BarGraphItem(x=orders, height=heights, width=0.6,
                                 brush=theme.WARNING if over else theme.ACCENT, pen=None))
    plot.setXRange(1.4, orders[-1] + 0.6, padding=0)
    plot.getAxis("bottom").setTicks([[(int(k), str(k)) for k in orders if k % 2]])  # ímpares: as relevantes
    plot.setYRange(0, max(5.0, float(heights.max()) * 1.3), padding=0)
    return result.thd_percent


def _draw_power_trend(plot: pg.PlotWidget, p_curve, d_curve, stats: MeterStats | None) -> None:
    """Potência ativa total (área) e demanda de 15 min (tracejado), em kW por minuto."""
    points = list(stats.trend) if stats is not None else []
    if not points:
        p_curve.setData([], [])
        d_curve.setData([], [])
        return
    x = np.array([(p.t - points[-1].t) / 60 for p in points])
    power = np.array([np.nan if p.active_w is None else p.active_w / 1000 for p in points])
    demand = np.array([np.nan if p.demand_w is None else p.demand_w / 1000 for p in points])
    p_curve.setData(x, power, connect="finite")
    d_curve.setData(x, demand, connect="finite")
    plot.setXRange(min(x[0], -1.0), 0.0, padding=0.01)


def _symmetric(plot: pg.PlotWidget, values: np.ndarray) -> None:
    """Eixo vertical simétrico em torno do zero, com folga de 15 % sobre o pico."""
    peak = float(np.abs(values).max()) if values.size else 0.0
    if peak > 0:
        plot.setYRange(-1.15 * peak, 1.15 * peak, padding=0)


def _tag(plot: pg.PlotWidget, text: str, color: str, position: complex, size: int) -> None:
    """Rótulo na ponta de um fasor."""
    tag = pg.TextItem(text, color=color, anchor=(0.5, 0.5))
    tag.setFont(QFont("Segoe UI", size, QFont.Weight.Bold))
    tag.setPos(position.real, position.imag)
    plot.addItem(tag)
