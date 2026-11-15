"""Janela do PRISMA: instrumentos virtuais, editor C e aquisição serial."""
from __future__ import annotations

from pathlib import Path
import json
import time
from dataclasses import replace
import sqlite3
import numpy as np
import pyqtgraph as pg

from PySide6.QtCore import QSize, QTimer, Qt
from PySide6.QtGui import QAction, QFont, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTabWidget,
    QVBoxLayout, QWidget, QGridLayout,
    QTableWidgetItem,
)

from prisma import __version__
from prisma.core.measurement import (summary_measurement, LIMIT_THD_PERCENT, LIMIT_UNBALANCE_PERCENT, MeterStats, SignalBuffer, analyze,
                                     sequence_components)
from prisma.core.protocol import CMD_INFO, Sample
from prisma.core.recording import CsvRecorder
from prisma.core.link import link_label, network_url
from prisma.core.serial_reader import SerialReader
from prisma.core.history import SqliteRecorder
from prisma.ui import theme
from prisma.ui.editor import CodeEditor, EditorPanel
from prisma.ui.features import FeaturesMixin
from prisma.ui.meter import MeterTable, degrees as _degrees, si

COLORS = theme.PHASE
# DEMOEM: ADC de 16 bits com VREFH = VDD do regulador de 3,3 V (confirmar com multímetro).
ADC_VREF_V = 3.3
ADC_FULL_SCALE = 65535
CURRENT_CHANNELS = ("ia", "ib", "ic")


def nominal_gain(channel: str) -> float:
    """Volts no pino por contagem, sem calibração.

    Tensões: entrada simples, 0..65535 = 0..Vref. Correntes: entrada diferencial
    (complemento de 2, ±Vref) que o firmware manda em binário deslocado, então
    cada contagem vale Vref / 32768 (o dobro).
    """
    return ADC_VREF_V / 32768 if channel in CURRENT_CHANNELS else ADC_VREF_V / ADC_FULL_SCALE
ICON_PATH = Path(__file__).with_name("assets") / "prisma.svg"


def app_icon() -> QIcon:
    return QIcon(str(ICON_PATH))

FIRMWARE_SKELETON = """/* PRISMA - exemplo ilustrativo (NÃO é firmware pronto para gravação).
 * Alvo planejado: Freescale MCF51EM256 / ColdFire V1.
 * Configurar relógio, SCI, ADC e GPIO com as ferramentas da DEMOEM.
 * O firmware real deverá emitir JSON conforme docs/protocolo.md.
 */
#include <stdint.h>

int main(void)
{
    /* TODO: inicializar hardware e configurar SCI e ADC. */
    while (1) {
        /* TODO: ler sinais e transmitir amostras por SCI. */
    }
    return 0;
}
"""

STYLE = theme.STYLE


class NoticeLabel(QLabel):
    """Aviso que só aparece quando há texto (sinal ausente, análise indisponível…)."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("notice")
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setWordWrap(True)
        self.hide()

    def setText(self, text: str) -> None:  # noqa: N802 (API do Qt)
        super().setText(text)
        self.setVisible(bool(text))


class MainWindow(FeaturesMixin, QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PRISMA · Analisador de energia")
        self.resize(1480, 920)
        self.setMinimumSize(1060, 700)
        self.setStyleSheet(STYLE)
        self.setWindowIcon(app_icon())
        self.paused = False
        self._session_t0: float | None = None
        self._last_record_t = float("-inf")
        self.raw_counts = False
        pg.setConfigOptions(antialias=True, background=theme.PLOT_BG, foreground=theme.MUTED)
        self.buffer = SignalBuffer()
        self.stats = MeterStats()
        self._clock = time.monotonic  # substituível nos testes
        self._energy_sample_t: float | None = None
        # Medição contínua da placa (quadros de resumo): energia sem lacunas.
        self.last_summary = None
        self._summary_clock: float | None = None  # relógio do PC na chegada do último resumo
        self._summary_t: float | None = None      # base de tempo da energia: soma das janelas
        self._last_summary_seq: int | None = None
        self.summaries_lost = 0
        self.energy = self.stats.energy
        self.reader: SerialReader | None = None
        self.kiosk = False
        self._last_data_clock: float | None = None  # chegada do último dado da placa (monotônico)
        self.recorder: CsvRecorder | SqliteRecorder | None = None
        self.current_file: Path | None = None
        self.demo_index = 0
        self.mode = "DEMONSTRAÇÃO — SINAIS SINTÉTICOS"
        self._invalid_sample_logs = 0
        self._build_ui()
        self.reset_energy()
        self._build_menu()
        self._build_features()
        self.refresh_ports()
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self._log(f"PRISMA v{__version__} iniciado em MODO DEMONSTRAÇÃO (sem dados de hardware).")
        self._log("Abra um projeto para configurar a toolchain. Integração DEMOEM ainda requer validação física.")

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("Arquivo")
        for name, fn in (("Abrir código C…", self.open_code), ("Salvar código C…", self.save_code)):
            action = QAction(name, self)
            action.triggered.connect(fn)
            menu.addAction(action)
        view = self.menuBar().addMenu("Exibir")
        for name, fn, keys in (
            ("Pausar / retomar gráficos", self.toggle_pause, "Space"),
            ("Exportar imagem dos instrumentos…", self.export_snapshot, "Ctrl+Shift+S"),
            ("Tela cheia", self.toggle_fullscreen, "F11"),
            ("Painel touch", self.open_touch_panel, "F10"),
        ):
            action = QAction(name, self)
            action.setShortcut(QKeySequence(keys))
            action.triggered.connect(lambda _=False, f=fn: f())
            view.addAction(action)
        info = self.menuBar().addMenu("Ajuda")
        about = QAction("Sobre o PRISMA", self)
        about.triggered.connect(self.show_about)
        info.addAction(about)
        acquisition = self.menuBar().addMenu("Aquisição")
        self.record_action = QAction("Iniciar registro CSV…", self)
        self.record_action.triggered.connect(self.toggle_recording)
        acquisition.addAction(self.record_action)
        self.record_label = QLabel("CSV: inativo")
        self.statusBar().addPermanentWidget(self.record_label)

    def toggle_recording(self, checked=False, *, backend: str = "csv") -> None:
        if self.recorder is not None:
            self.stop_recording()
            return
        if not self.mode.startswith(("DEMONSTRAÇÃO", "AQUISIÇÃO SERIAL REAL")):
            QMessageBox.information(self, "Registro CSV", "Ative o modo demo ou aguarde amostras da serial.")
            return
        sqlite = backend == "sqlite"
        filename, _ = QFileDialog.getSaveFileName(self, "Registrar amostras",
            "historico.sqlite" if sqlite else "aquisicao.csv",
            "SQLite (*.sqlite *.db)" if sqlite else "CSV (*.csv)")
        if not filename:
            return
        try:
            metadata = json.dumps({"name": self.calibration.name, "channels": self.calibration.channels}, ensure_ascii=False)
            source = f"{self.mode} | calibração: {metadata}"
            self.recorder = SqliteRecorder(Path(filename), source, metadata) if sqlite else CsvRecorder(Path(filename), source)
        except (OSError, sqlite3.Error) as exc:
            QMessageBox.critical(self, "Erro ao iniciar registro", str(exc))
            return
        self.record_action.setText("Parar registro")
        self.sqlite_action.setText("Parar registro")
        self.record_label.setText(f"{'SQLite' if sqlite else 'CSV'}: gravando · 0 amostras")
        self._log(f"Registro iniciado: {filename} | {self.mode}")

    def stop_recording(self) -> None:
        recorder = self.recorder
        self.recorder = None
        if recorder is None:
            return
        try:
            recorder.close()
        except (OSError, sqlite3.Error) as exc:
            self._log(f"Erro ao finalizar CSV: {exc}")
        self.record_action.setText("Iniciar registro CSV…")
        self.sqlite_action.setText("Iniciar histórico SQLite…")
        self.record_label.setText("CSV: inativo")
        self._log(f"Registro CSV encerrado: {recorder.count} amostras | {recorder.path}")

    def _record_sample(self, sample: Sample) -> None:
        if self.recorder is not None:
            try:
                self.recorder.write(sample)
            except (OSError, sqlite3.Error) as exc:
                self._log(f"Erro de escrita CSV: {exc}")
                self.stop_recording()

    def _card(self, caption: str, color: str = theme.TEXT, hint: str = "",
              action: QWidget | None = None) -> tuple[QFrame, QLabel, QLabel]:
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        title = QLabel(caption)
        title.setObjectName("cardCaption")
        value = QLabel("—")
        value.setObjectName("cardValue")
        value.setStyleSheet(f"color: {color};")
        sub = QLabel(hint)
        sub.setObjectName("cardHint")
        if action is None:
            layout.addWidget(title)
        else:
            head = QHBoxLayout()
            head.addWidget(title)
            head.addStretch(1)
            head.addWidget(action)
            layout.addLayout(head)
        layout.addWidget(value)
        layout.addWidget(sub)
        return frame, value, sub

    @staticmethod
    def _plot(title: str) -> pg.PlotWidget:
        plot = pg.PlotWidget()
        plot.setBackground(theme.PLOT_BG)
        plot.setTitle(title, color=theme.MUTED, size="10pt")
        plot.showGrid(x=True, y=True, alpha=0.12)
        for axis in ("left", "bottom"):
            plot.getAxis(axis).setPen(pg.mkPen(theme.BORDER))
            plot.getAxis(axis).setTextPen(pg.mkPen(theme.MUTED))
            plot.getAxis(axis).setTickFont(QFont("Segoe UI", 9))
        plot.getAxis("left").setWidth(52)
        plot.setMenuEnabled(False)
        return plot

    @staticmethod
    def _titled(title: str, widget: QWidget) -> tuple[QFrame, QLabel]:
        """Card com título no mesmo estilo do osciloscópio."""
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        label = QLabel(title)
        label.setObjectName("panelTitle")
        label.setMinimumHeight(28)
        layout.addWidget(label)
        layout.addWidget(widget, stretch=1)
        return frame, label

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Barra lateral: marca, navegação e estado da conexão.
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(210)
        side = QVBoxLayout(rail)
        side.setContentsMargins(14, 16, 14, 14)
        side.setSpacing(4)
        brand_row = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(QSize(42, 42)))
        brand_row.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        brand = QLabel("PRISMA")
        brand.setObjectName("brand")
        sub = QLabel("Analisador de energia")
        sub.setObjectName("brandSub")
        names.addWidget(brand)
        names.addWidget(sub)
        brand_row.addLayout(names, stretch=1)
        side.addLayout(brand_row)
        side.addSpacing(18)
        self.nav_buttons: list[tuple[QPushButton, QWidget]] = []
        self._nav_layout = QVBoxLayout()
        self._nav_layout.setSpacing(2)
        side.addLayout(self._nav_layout)
        side.addStretch(1)
        self.hw_status = QLabel()
        side.addWidget(self.hw_status)
        self.board_label = QLabel("DEMOEM · MCF51EM256")
        self.board_label.setWordWrap(True)
        self.board_label.setObjectName("brandSub")
        self.board_label.setStyleSheet(f"color: {theme.SUBTLE}; font-weight: 400; letter-spacing: 0;")
        side.addWidget(self.board_label)
        self._set_link_status("Serial desconectada", theme.SUBTLE)
        outer.addWidget(rail)

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        outer.addLayout(content, stretch=1)

        # Barra superior: título da página, estado e conexão.
        topbar = QFrame()
        topbar.setObjectName("topbar")
        top = QHBoxLayout(topbar)
        top.setContentsMargins(20, 12, 16, 12)
        top.setSpacing(8)
        self.page_title = QLabel("Instrumentação")
        self.page_title.setObjectName("pageTitle")
        top.addWidget(self.page_title)
        top.addSpacing(10)
        self.mode_label = QLabel()
        self.mode_label.setObjectName("pill")
        top.addWidget(self.mode_label)
        self.pause_chip = QLabel("Pausado")
        self.pause_chip.setObjectName("pill")
        self.pause_chip.setStyleSheet(theme.pill_style("pause"))
        self.pause_chip.setVisible(False)
        top.addWidget(self.pause_chip)
        top.addStretch(1)
        self.btn_pause = QPushButton()
        self.btn_pause.setObjectName("icon")
        self.btn_pause.setCheckable(True)
        self.btn_pause.setIcon(theme.icon("pause"))
        self.btn_pause.setToolTip("Pausar gráficos (Espaço). A aquisição e o registro continuam.")
        self.btn_pause.clicked.connect(lambda _=False: self.toggle_pause())
        self.btn_snapshot = QPushButton()
        self.btn_snapshot.setObjectName("icon")
        self.btn_snapshot.setIcon(theme.icon("camera"))
        self.btn_snapshot.setToolTip("Exportar imagem dos instrumentos (Ctrl+Shift+S)")
        self.btn_snapshot.clicked.connect(lambda _=False: self.export_snapshot())
        self.btn_report = QPushButton()
        self.btn_report.setObjectName("icon")
        self.btn_report.setIcon(theme.icon("report"))
        self.btn_report.setToolTip("Gerar relatório HTML com gráficos e tabelas da análise atual")
        self.btn_report.clicked.connect(lambda _=False: self.export_report())
        top.addWidget(self.btn_pause)
        top.addWidget(self.btn_snapshot)
        top.addWidget(self.btn_report)
        top.addSpacing(10)
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(190)
        self.port_combo.setToolTip("Porta serial da placa ou gateway na rede (Wi-Fi)")
        self.port_combo.activated.connect(self._on_port_activated)
        top.addWidget(self.port_combo)
        refresh = QPushButton()
        refresh.setObjectName("icon")
        refresh.setIcon(theme.icon("refresh"))
        refresh.setToolTip("Atualizar portas COM e gateways salvos")
        refresh.clicked.connect(self.refresh_ports)
        top.addWidget(refresh)
        self.b_connect = QPushButton("Conectar")
        self.b_connect.setObjectName("primary")
        self.b_connect.setIcon(theme.icon("plug", "#ffffff"))
        self.b_connect.clicked.connect(self.connect_serial)
        top.addWidget(self.b_connect)
        self.btn_demo = QPushButton("Demo")
        self.btn_demo.setIcon(theme.icon("wave"))
        self.btn_demo.setToolTip("Sinais trifásicos sintéticos, sem placa")
        self.btn_demo.clicked.connect(self.start_demo)
        top.addWidget(self.btn_demo)
        content.addWidget(topbar)

        # Ações que pertencem a outras páginas (posicionadas nelas).
        self.btn_open = QPushButton("Abrir")
        self.btn_open.setIcon(theme.icon("open"))
        self.btn_open.clicked.connect(self.open_code)
        self.btn_save = QPushButton("Salvar")
        self.btn_save.setIcon(theme.icon("save"))
        self.btn_save.clicked.connect(self.save_code)
        self.btn_compile = QPushButton("Compilar")
        self.btn_compile.setIcon(theme.icon("build"))
        self.btn_flash = QPushButton("Gravar")
        self.btn_flash.setIcon(theme.icon("flash"))
        for b in (self.btn_compile, self.btn_flash):
            b.setEnabled(False)

        self.tabs = QTabWidget()
        self.tabs.tabBar().hide()
        self.tabs.currentChanged.connect(self._sync_nav)
        content.addWidget(self.tabs, stretch=1)

        # Página de instrumentação: medições + indicadores em cima, gráficos embaixo.
        # Duas faixas (e não três) para caber em telas de 720 px de altura.
        dashboard = QWidget()
        dash = QVBoxLayout(dashboard)
        dash.setContentsMargins(20, 14, 20, 12)
        dash.setSpacing(12)
        self.details = NoticeLabel()
        dash.addWidget(self.details)
        metrics = QHBoxLayout()
        metrics.setSpacing(12)
        self.meter = MeterTable()
        self.metric_labels = self.meter.voltage_labels
        metrics.addWidget(self.meter, stretch=3)
        kpis = QGridLayout()
        kpis.setSpacing(10)
        card, self.frequency_label, self.frequency_hint = self._card("Frequência", theme.ACCENT, "fundamental")
        kpis.addWidget(card, 0, 0)
        card, self.thd_label, self.thd_hint = self._card("THD tensão · fase A", hint="h2–h15")
        kpis.addWidget(card, 0, 1)
        reset = QPushButton("Zerar")
        reset.setObjectName("ghost")
        reset.setToolTip("Zerar energia, demanda máxima e valores mínimos/máximos")
        reset.clicked.connect(lambda _=False: self.reset_energy())
        card, self.energy_label, self.energy_hint = self._card("Energia ativa", theme.SUCCESS, "aguardando correntes",
                                                               action=reset)
        kpis.addWidget(card, 1, 0)
        card, self.reactive_energy_label, _ = self._card("Energia reativa", hint="fundamental")
        kpis.addWidget(card, 1, 1)
        card, self.unbalance_label, self.unbalance_hint = self._card(
            "Desequilíbrio de tensão", hint=f"limite {LIMIT_UNBALANCE_PERCENT:.0f} % (PRODIST)")
        kpis.addWidget(card, 2, 0)
        card, self.sequence_label, self.sequence_hint = self._card("Sequência de fases", hint="")
        kpis.addWidget(card, 2, 1)
        metrics.addLayout(kpis, stretch=2)
        dash.addLayout(metrics)

        self.wave = self._plot("Osciloscópio")
        self.wave.setLabel("left", "Tensão", units="V")
        self.wave.setLabel("bottom", "Tempo", units="s")
        self.curves = {
            phase: self.wave.plot(pen=pg.mkPen(theme.PHASE[phase], width=2), name=f"V{phase.lower()}")
            for phase in ("A", "B", "C")
        }
        scope_card = QFrame()
        scope_card.setObjectName("card")
        scope_layout = QVBoxLayout(scope_card)
        scope_layout.setContentsMargins(10, 8, 10, 8)
        scope_head = QHBoxLayout()
        scope_title = QLabel("OSCILOSCÓPIO")
        scope_title.setObjectName("panelTitle")
        scope_head.addWidget(scope_title)
        scope_head.addSpacing(14)
        scope_legend = QLabel(theme.phase_legend("V"))
        scope_legend.setStyleSheet("font-weight: 700;")
        scope_head.addWidget(scope_legend)
        scope_head.addStretch(1)
        self.trigger_check = QCheckBox("Disparo")
        self.trigger_check.setChecked(True)
        self.trigger_check.setToolTip("Alinha a tela na subida do canal com mais sinal, mantendo a forma de onda parada.")
        scope_head.addWidget(self.trigger_check)
        scope_head.addSpacing(10)
        scope_head.addWidget(QLabel("Janela"))
        self.cycles_combo = QComboBox()
        self.cycles_combo.addItems(["2 ciclos", "4 ciclos", "8 ciclos", "250 ms"])
        self.cycles_combo.setCurrentIndex(1)
        scope_head.addWidget(self.cycles_combo)
        scope_layout.addLayout(scope_head)
        self.wave.setTitle(None)
        self.wave.setMinimumHeight(160)
        scope_layout.addWidget(self.wave)

        self.phasor = self._plot("")
        self.phasor.setTitle(None)
        self.phasor.setAspectLocked(True)
        self.phasor.getAxis("left").setStyle(showValues=False)
        self.phasor.getAxis("bottom").setStyle(showValues=False)
        self.phasor.setXRange(-185, 185, padding=0)
        self.phasor.setYRange(-185, 185, padding=0)
        self.harmonics = self._plot("")
        self.harmonics.setTitle(None)
        self.harmonics.showGrid(x=False, y=True, alpha=0.12)
        self.harmonics.setXRange(1.5, 15.5, padding=0)
        charts = QHBoxLayout()
        charts.setSpacing(12)
        charts.addWidget(scope_card, stretch=5)
        card, self.phasor_title = self._titled("FASORES", self.phasor)
        charts.addWidget(card, stretch=3)
        card, self.harmonics_title = self._titled("HARMÔNICAS · FASE A (%)", self.harmonics)
        charts.addWidget(card, stretch=3)
        dash.addLayout(charts, stretch=1)
        self.tabs.addTab(dashboard, "Instrumentação")

        # Página do editor de firmware.
        editor_page = QWidget()
        editor_layout = QVBoxLayout(editor_page)
        editor_layout.setContentsMargins(20, 16, 20, 12)
        editor_bar = QHBoxLayout()
        self.file_label = QLabel("Sem arquivo · exemplo ilustrativo")
        self.file_label.setObjectName("muted")
        editor_bar.addWidget(self.file_label)
        editor_bar.addStretch(1)
        editor_bar.addWidget(self.btn_open)
        editor_bar.addWidget(self.btn_save)
        editor_layout.addLayout(editor_bar)
        self.editor = CodeEditor(FIRMWARE_SKELETON)
        self.editor_panel = EditorPanel(self.editor)
        editor_layout.addWidget(self.editor_panel)
        self.editor_page = editor_page
        self.tabs.addTab(editor_page, "Firmware C")
        self._add_nav("Instrumentação", dashboard, "scope")
        self._add_nav("Firmware C", editor_page, "code")

        # Console recolhível.
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setObjectName("log")
        self.console.setFixedHeight(130)
        self.console.setVisible(False)
        console_wrap = QWidget()
        console_layout = QVBoxLayout(console_wrap)
        console_layout.setContentsMargins(20, 0, 20, 10)
        console_layout.addWidget(self.console)
        content.addWidget(console_wrap)
        self.btn_console = QPushButton("Console")
        self.btn_console.setObjectName("ghost")
        self.btn_console.setIcon(theme.icon("terminal", theme.MUTED, 16))
        self.btn_console.setCheckable(True)
        self.btn_console.toggled.connect(self.console.setVisible)
        self.statusBar().addPermanentWidget(self.btn_console)
        self._set_mode(self.mode)

    def _set_link_status(self, text: str, color: str) -> None:
        self.hw_status.setText(f"<span style='color:{color}'>●</span> {text}")
        self.hw_status.setStyleSheet(f"color: {theme.MUTED};")

    def _log(self, message: str) -> None:
        self.console.appendPlainText(message)

    def _set_mode(self, label: str, real: bool = False) -> None:
        self.mode = label
        short = label.split(" — ")[0].capitalize()
        kind = "real" if real else ("demo" if label.startswith("DEMONSTRAÇÃO") else "idle")
        self.mode_label.setText(("● " if real else "") + short)
        self.mode_label.setToolTip(label)
        self.mode_label.setStyleSheet(theme.pill_style(kind))
        self.statusBar().showMessage(label.capitalize())

    NETWORK_ITEM = "__network__"

    def _network_entry(self, url: str) -> int:
        """Índice do gateway ``url`` na lista, inserido antes de "Gateway na rede…" se faltar."""
        index = self.port_combo.findData(url)
        if index < 0:
            index = max(0, self.port_combo.findData(self.NETWORK_ITEM))
            self.port_combo.insertItem(index, f"Rede · {link_label(url).removesuffix(' (rede)')}", url)
        return index

    def select_port(self, port: str) -> bool:
        try:
            url = network_url(port)
        except ValueError:
            return False
        if url is not None:
            self.port_combo.setCurrentIndex(self._network_entry(url))
            return True
        index = self.port_combo.findData(port)
        if index >= 0:
            self.port_combo.setCurrentIndex(index)
        return index >= 0

    def refresh_ports(self) -> None:
        from serial.tools import list_ports
        selected = self.port_combo.currentData()
        self.port_combo.clear()
        ports = list(list_ports.comports())
        for port in ports:
            self.port_combo.addItem(f"{port.device} — {port.description}", port.device)
        if not ports:
            self.port_combo.addItem("Nenhuma porta COM", None)
        self.port_combo.addItem("Gateway na rede…", self.NETWORK_ITEM)
        saved = self.settings.value("last_network")
        if saved:
            self._network_entry(str(saved))
        if selected and selected != self.NETWORK_ITEM:
            self.select_port(selected)
        elif ports:
            self.port_combo.setCurrentIndex(0)

    def _on_port_activated(self, index: int) -> None:
        if self.port_combo.itemData(index) == self.NETWORK_ITEM:
            self.ask_network_address()

    def ask_network_address(self) -> str | None:
        """Pede IP:porta do gateway (ESP32-S3 ou scripts/ponte_tcp.py) e o seleciona."""
        from PySide6.QtWidgets import QInputDialog
        current = str(self.settings.value("last_network", "tcp://prisma.local:3333"))
        text, ok = QInputDialog.getText(
            self, "Gateway na rede",
            "Endereço do gateway (IP ou nome, porta padrão 3333):\n"
            "ex.: 192.168.0.20:3333 ou prisma.local",
            text=current.removeprefix("tcp://"))
        url = None
        if ok and text.strip():
            try:
                url = network_url(text) or network_url("tcp://" + text.strip())
            except ValueError as exc:
                QMessageBox.warning(self, "Endereço inválido", str(exc))
        if url is None:
            self.refresh_ports()
            return None
        self.settings.setValue("last_network", url)
        self.port_combo.setCurrentIndex(self._network_entry(url))
        return url

    def connect_serial(self) -> None:
        if self.reader is not None and self.reader.isRunning():
            self.stop_recording()
            self.reader.stop()
            if not self.reader.wait(1200):
                self._log("A serial ainda está encerrando.")
                return
            self.reader = None
            self._on_disconnected()
            self._set_mode("DESCONECTADO — SEM AQUISIÇÃO")
            self._connect_button(False)
            return
        port = self.port_combo.currentData()
        if port == self.NETWORK_ITEM:
            port = self.ask_network_address()
            if port is None:
                return
        if port is None:
            QMessageBox.warning(
                self, "Sem porta COM",
                "Nenhuma porta COM detectada. Confirme o driver e a configuração serial da placa."
            )
            return
        self.settings.setValue("last_port", port)
        self._session_t0, self._last_record_t = None, float("-inf")
        self.stop_recording()
        self.buffer.clear()
        self.reset_energy()
        self._invalidate_analysis()
        self.hardware_view.setPlainText("Aguardando telemetria de estados do firmware.")
        self._invalid_sample_logs = 0
        self._last_data_clock = None
        self._set_mode(f"CONECTANDO A {link_label(port)} — SEM DADOS")
        self.reader = SerialReader(port, self.device_profile.baudrate, parent=self, parser=self.sample_parser)
        self.reader.persistent = self.reader.network or self.kiosk  # o quiosque não desiste da serial
        reader = self.reader
        self.reader.connected.connect(lambda: self._on_connected(port) if self.reader is reader else None)
        self.reader.sample_received.connect(lambda sample: self._on_sample(sample) if self.reader is reader else None)
        self.reader.status_received.connect(lambda status: self._on_hardware_status(status) if self.reader is reader else None)
        self.reader.block_received.connect(lambda block: self._on_block(block) if self.reader is reader else None)
        self.reader.summary_received.connect(lambda summary: self._on_summary(summary) if self.reader is reader else None)
        self.reader.reply_received.connect(lambda reply: self._on_command_reply(reply) if self.reader is reader else None)
        self._pending_commands.clear()
        self._board_info_asked = False
        self.board_info = None
        self.reader.message.connect(self._log)
        self.reader.disconnected.connect(lambda: self._on_disconnected() if self.reader is reader else None)
        self.reader.reconnecting.connect(lambda: self._on_reconnecting(port) if self.reader is reader else None)
        self.reader.start()
        self._connect_button(True)

    def _connect_button(self, connected: bool) -> None:
        self.b_connect.setText("Desconectar" if connected else "Conectar")
        self.b_connect.setIcon(theme.icon("unplug" if connected else "plug", "#c8f5dc" if connected else "#ffffff"))
        self.b_connect.setProperty("connected", connected)
        self.b_connect.style().unpolish(self.b_connect)
        self.b_connect.style().polish(self.b_connect)

    def _on_connected(self, port: str) -> None:
        self._set_link_status(f"{link_label(port)} conectada", theme.SUCCESS)
        self._set_mode(f"SERIAL {link_label(port)} — AGUARDANDO AMOSTRAS")

    def _mark_data(self) -> None:
        self._last_data_clock = time.monotonic()

    def data_age(self) -> float | None:
        """Segundos desde o último dado da placa; None sem placa (demonstração ou nunca chegou)."""
        if self.mode.startswith("DEMONSTRAÇÃO") or self._last_data_clock is None:
            return None
        return time.monotonic() - self._last_data_clock

    def _on_sample(self, sample: Sample, record_t: float | None = None) -> None:
        try:
            sample = self.calibration.apply(sample)
            self.buffer.add(sample)
        except ValueError as exc:
            if self._invalid_sample_logs < 5:
                self._log(f"Amostra ignorada: {exc}")
                self._invalid_sample_logs += 1
            return
        self._record_sample(sample if record_t is None else replace(sample, t=record_t))
        if record_t is None:
            self._mark_data()
        if not self.mode.startswith("AQUISIÇÃO SERIAL REAL"):
            port = link_label(self.reader.port) if self.reader else "COM"
            self._set_mode(f"AQUISIÇÃO SERIAL REAL — {port}", real=True)

    def _block_record_times(self, block, arrival: float | None = None) -> list[float]:
        """Tempo real (s desde o início da sessão) de cada amostra de uma rajada.

        O bloco chega ao fim da transmissão; o início da aquisição é a chegada menos
        a transmissão (≈ 12 caracteres por amostra + cabeçalho, 10 bits por caractere)
        e menos a duração da própria rajada. Dentro do bloco o passo é 1/fs exato.
        """
        arrival = time.monotonic() if arrival is None else arrival
        if self._session_t0 is None:
            self._session_t0 = arrival
        n = len(block.samples)
        wire = block.wire_bytes if getattr(block, "wire_bytes", None) else n * 12 + 150
        transmission = wire * 10 / max(1, self.device_profile.baudrate)
        start = arrival - self._session_t0 - transmission - n / block.fs_hz
        start = max(start, self._last_record_t + 1 / block.fs_hz)
        times = [start + i / block.fs_hz for i in range(n)]
        self._last_record_t = times[-1]
        return times

    def _pin_volts(self) -> bool:
        """Rajada exibida como tensão no pino do ADC: escala nominal ou só a etapa 1 da calibração."""
        return self.raw_counts and (not self.calibration.channels or self.calibration.pin_volts)

    def _apply_units(self) -> None:
        label = "Tensão no pino ADC" if self._pin_volts() else "Tensão"
        self.wave.setLabel("left", label, units="V")
        self.phasor.setLabel("left", "Imaginário", units="V")
        self.phasor.setLabel("bottom", "Real", units="V")
        if self.raw_counts:
            self.phasor.enableAutoRange()

    def _summary_fresh(self) -> bool:
        """Chegou resumo da placa há pouco: energia e frequência vêm dele."""
        return self._summary_clock is not None and self._clock() - self._summary_clock < 3.0

    def _on_summary(self, summary) -> None:
        """Janela contínua (~1 s) da placa: energia, demanda e frequência sem lacunas.

        O tempo da energia é a soma das durações das janelas (relógio da placa),
        a partir do relógio do PC no primeiro resumo. Janela perdida (seq salta)
        não é estimada: só contada em ``summaries_lost``.
        """
        self._enter_raw_mode()
        self._mark_data()
        if not self._board_info_asked:
            # Resumo 0x02 prova firmware PRISMA contínuo: identifica sem atrapalhar outros aparelhos.
            self._board_info_asked = self.send_board_command(CMD_INFO, quiet=True)
        if self._last_summary_seq is not None and summary.seq > self._last_summary_seq + 1:
            self.summaries_lost += summary.seq - self._last_summary_seq - 1
        self._last_summary_seq = summary.seq
        self.last_summary = summary
        self._summary_clock = self._clock()
        if self._summary_t is None:
            self._summary_t = self._summary_clock
        self._summary_t += summary.duration_s
        gains = {ch: cfg["gain"] for ch, cfg in self._calibration_base().items()}
        signs = {}
        if self.last_analysis is not None:
            signs = {p: -1.0 if x.reactive_fundamental_var < 0 else 1.0 for p, x in self.last_analysis[0].power.items()}
        result = summary_measurement(summary, gains, signs, self.calibration.delays_s())
        self.stats.update(self._summary_t, result)
        self._show_continuous(summary, result)

    def _show_continuous(self, summary, result) -> None:
        pin = self._pin_volts()
        values = " · ".join(f"V{p.lower()} {result.rms[p]:.4f} V" if pin else f"V{p.lower()} {result.rms[p]:.2f} V"
                            for p in "ABC")
        if result.current_rms:
            values += " · " + " · ".join(
                f"I{p.lower()} {result.current_rms[p]:.4f} V" if pin else f"I{p.lower()} {result.current_rms[p]:.3f} A"
                for p in "ABC")
        frequency = (f"f = {summary.frequency_hz:.3f} Hz ({summary.cycles} ciclos)" if summary.synced
                     else "sem cruzamentos (sinal DC ou ausente)")
        problems = []
        if summary.timeout_mask:
            problems.append(f"timeout ADC {summary.timeout_mask}")
        if self.summaries_lost:
            problems.append(f"{self.summaries_lost} janela(s) perdida(s)")
        self.continuous_label.setText(
            f"<b>Medição contínua</b> · janela {summary.seq}: {summary.n} amostras ({summary.duration_s:.3f} s) · "
            f"{frequency} · RMS {values}" + (f" · <span style='color:{theme.WARNING}'>⚠ {', '.join(problems)}</span>"
                                             if problems else ""))
        if summary.synced:
            self.frequency_label.setText(f"{summary.frequency_hz:.3f} Hz")
            self.frequency_hint.setText("medição contínua · janela de ~1 s")

    def _enter_raw_mode(self) -> None:
        """Primeira rajada ou resumo da placa: unidades de contagem e frequência automática."""
        if not self.raw_counts:
            self.raw_counts = True
            self._apply_units()
            if self.frequency_combo.currentIndex() != 2:
                self.frequency_combo.setCurrentIndex(2)
            # Cada rajada começa num instante arbitrário do ciclo: só o ângulo entre fases
            # é estável, então a fase A vira a referência (0°).
            if self.phasor_reference.currentIndex() == 0:
                self.phasor_reference.setCurrentIndex(1)
            if not self.calibration.channels:
                self._log(f"Dados da placa recebidos: frequência em Automática (40–70 Hz). Sem calibração, os valores "
                          f"são a tensão no pino do ADC (contagem × {ADC_VREF_V} V / {ADC_FULL_SCALE}).")
            else:
                self._log(f"Dados da placa recebidos: frequência em Automática (40–70 Hz). Calibração ativa: "
                          f"{self.calibration.name}.")

    def _on_block(self, block) -> None:
        """Rajada de taxa fixa: um reinício do firmware (seq menor) recomeça o buffer."""
        self._enter_raw_mode()
        self._mark_data()
        self._show_block(block, ADC_VREF_V, ADC_FULL_SCALE)
        last = self.buffer.arrays(duration_s=0.0)[0]
        if last.size and block.samples[0].t <= last[-1]:
            self.buffer.clear()
        # Sem calibração, escala nominal; com calibração, os coeficientes partem das contagens.
        scale = nominal_gain("va") if not self.calibration.channels else None
        scale_i = nominal_gain("ia")
        starts = self._block_record_times(block)
        for sample, record_t in zip(block.samples, starts):
            if scale is not None:
                currents = (sample.ia, sample.ib, sample.ic)
                sample = Sample(sample.t, sample.va * scale, sample.vb * scale, sample.vc * scale,
                                *(None if c is None else c * scale_i for c in currents))
            self._on_sample(sample, record_t)
        names = "/".join(block.channels)
        warning = f" · timeout ADC {block.timeout_mask}" if block.timeout_mask else ""
        unit = (f"tensão no pino ADC (nominal, Vref {ADC_VREF_V} V)" if scale
                else "tensão no pino ADC (ADC calibrado)" if self.calibration.pin_volts else "calibração ativa")
        self.statusBar().showMessage(
            f"Rajada {block.seq}: {len(block.samples)} amostras de {names} a {block.fs_hz:.1f} Hz · {unit}{warning}")

    def _on_reconnecting(self, port: str) -> None:
        """Gateway na rede caiu: a thread tenta de novo; os dados já recebidos ficam."""
        self._set_link_status(f"{link_label(port)} — reconectando…", theme.WARNING)
        self._set_mode(f"RECONECTANDO A {link_label(port)} — DADOS RETIDOS")
        self._board_info_asked = False

    def _on_disconnected(self) -> None:
        self.stop_recording()
        self._set_link_status("Serial desconectada", theme.SUBTLE)
        self._connect_button(False)
        if not self.mode.startswith("DEMONSTRAÇÃO"):
            self._set_mode("SERIAL DESCONECTADA — DADOS RETIDOS")

    def start_demo(self) -> None:
        self.stop_recording()
        if self.reader is not None and self.reader.isRunning():
            self.reader.stop()
            if not self.reader.wait(1200):
                self._log("Aguardando encerramento da serial antes de trocar a origem.")
                return
        self.reader = None
        self.buffer.clear()
        self.reset_energy()
        self._invalidate_analysis()
        self.hardware_view.setPlainText("Demonstração: nenhum estado físico recebido.")
        self.last_summary = None
        self._summary_clock = None
        self.demo_index = 0
        self._set_link_status("Serial desconectada", theme.SUBTLE)
        self._connect_button(False)
        self._set_mode("DEMONSTRAÇÃO — SINAIS SINTÉTICOS")
        if self.raw_counts:
            self.raw_counts = False
            self._apply_units()
            self.phasor.setXRange(-185, 185, padding=0)
            self.phasor.setYRange(-185, 185, padding=0)
        self._log("Modo demonstração ativado. Dados não provêm da placa.")

    def _tick(self) -> None:
        if self.mode.startswith("DEMONSTRAÇÃO"):
            self._generate_demo_batch()
        self._draw_signals()
        if self.recorder is not None:
            try:
                self.recorder.flush()
                kind = "SQLite" if isinstance(self.recorder, SqliteRecorder) else "CSV"
                self.record_label.setText(f"{kind}: gravando · {self.recorder.count} amostras")
            except (OSError, sqlite3.Error) as exc:
                self._log(f"Erro de escrita CSV: {exc}")
                self.stop_recording()

    def _generate_demo_batch(self) -> None:
        # 2400 amostras/s: Nyquist de 1200 Hz permite analisar até h15 (900 Hz).
        indices = np.arange(self.demo_index, self.demo_index + 120, dtype=float)
        t = indices / 2400.0
        phases = (0.0, -2 * np.pi / 3, 2 * np.pi / 3)
        for tt in t:
            va = np.sqrt(2) * 127 * (
                np.sin(2 * np.pi * 60 * tt + phases[0])
                + 0.025 * np.sin(2 * np.pi * 180 * tt)
            )
            vb = np.sqrt(2) * 127 * np.sin(2 * np.pi * 60 * tt + phases[1])
            vc = np.sqrt(2) * 127 * np.sin(2 * np.pi * 60 * tt + phases[2])
            currents = [float(np.sqrt(2) * 5 * np.sin(2 * np.pi * 60 * tt + phase - np.arccos(0.9))) for phase in phases]
            try:
                sample = self.calibration.apply(Sample(float(tt), float(va), float(vb), float(vc), *currents))
                self.buffer.add(sample)
            except ValueError as exc:
                if self._invalid_sample_logs < 5:
                    self._log(f"Amostra demo ignorada: {exc}")
                    self._invalid_sample_logs += 1
                continue
            self._record_sample(sample)
        self.demo_index += 120

    def _draw_signals(self) -> None:
        if self.paused:
            return
        t, values = self.buffer.arrays(duration_s=0.25)
        if t.size < 12:
            self.last_analysis = None
            return
        span = self._scope_span()
        trigger = self._trigger_index(t, values, span)
        if trigger is None:
            x = t - t[-1]
            keep = x >= -span
            self.wave.setXRange(-span, 0.0, padding=0)
        else:
            # Disparo na subida do canal de referência: a forma de onda fica parada na tela.
            x = t - t[trigger]
            keep = (x >= 0) & (x <= span)
            self.wave.setXRange(0.0, span, padding=0)
        for i, phase in enumerate(("A", "B", "C")):
            self.curves[phase].setData(x[keep], values[keep, i])
        if (t[-1] - t[0]) < 0.12:
            return
        try:
            frequency = (60.0, 50.0, None)[self.frequency_combo.currentIndex()]
            window = ("rectangular", "hann")[self.window_combo.currentIndex()]
            values, currents = self.calibration.align(t, values, self.buffer.currents())
            result = analyze(t, values, fundamental_hz=frequency, currents=currents, window=window)
        except ValueError as exc:
            self.last_analysis = None
            self.frequency_label.setText("—")
            self.thd_label.setText("—")
            self.unbalance_label.setText("—")
            self.sequence_label.setText("—")
            self.sequence_hint.setText("")
            self.power_view.clearContents()
            self.meter.clear()
            self.phasor.clear()
            self.harmonics.clear()
            weak = "estimar frequência" in str(exc) or "instável" in str(exc)
            if weak:
                # Sem ciclos suficientes: o RMS por fase ainda vale e ajuda a ver qual canal sumiu.
                rms = np.sqrt(np.mean((values - values.mean(axis=0)) ** 2, axis=0))
                fmt = "{:.3f} V" if self._pin_volts() else "{:.2f} V"
                for label, value in zip(self.metric_labels.values(), rms):
                    label.setText(fmt.format(value))
                silent = [p for p, v in zip("ABC", np.ptp(values, axis=0)) if v < 1e-6 or v < 0.02 * np.ptp(values).max()]
                self.frequency_label.setText("Sem sinal")
                self.frequency_hint.setText("ciclos insuficientes no bloco")
                self.details.setText(
                    f"<b style='color:{theme.WARNING}'>Sinal ausente ou fraco</b><br>"
                    f"<span style='color:{theme.MUTED}'>Fases sem sinal: {', '.join(silent) or 'nenhuma'}. "
                    f"Não há ciclos suficientes para medir frequência, fasores e harmônicas. "
                    f"Na DEMOEM isso ocorre quando o gerador QE8 corta as saídas (por exemplo, ao girar os potenciômetros).</span>")
            else:
                self.details.setText(f"Análise indisponível: {exc}")
            return
        self._last_frequency = result.frequency_hz
        if self._summary_fresh() and self.last_summary.synced:
            self.frequency_label.setText(f"{self.last_summary.frequency_hz:.3f} Hz")
            self.frequency_hint.setText("medição contínua · janela de ~1 s")
        else:
            self.frequency_label.setText(f"{result.frequency_hz:.2f} Hz")
            self.frequency_hint.setText(("automática" if self.frequency_combo.currentIndex() == 2 else "referência fixa"))
        self.phasor.clear()
        self.phasor.addItem(pg.InfiniteLine(
            pos=0, angle=0, pen=pg.mkPen(theme.BORDER, width=1)
        ))
        self.phasor.addItem(pg.InfiniteLine(
            pos=0, angle=90, pen=pg.mkPen(theme.BORDER, width=1)
        ))
        reference = self.phasor_reference.currentIndex()
        rotation = np.exp(-1j * np.angle(result.phasors[("A", "B", "C")[reference - 1]])) if reference else 1
        for phase in ("A", "B", "C"):
            ph = result.phasors[phase] * rotation
            item = self.phasor.plot(
                [0, ph.real], [0, ph.imag],
                pen=pg.mkPen(COLORS[phase], width=5 if self.selected_phase == phase else 3),
                symbol="o", symbolSize=7, symbolBrush=COLORS[phase]
            )
            item.sigPointsClicked.connect(lambda item, points, event, p=phase: self._select_phasor(p))
            if self.selected_phase == phase:
                self.selected_phasor.setText(f"Fase {phase}: {abs(ph):.3f} V ∠ {_degrees(ph, 2)}°")
            tag = pg.TextItem(f"V{phase.lower()}", color=COLORS[phase], anchor=(0.5, 0.5))
            tag.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            tag.setPos(ph.real * 1.25, ph.imag * 1.25)
            self.phasor.addItem(tag)
        # Correntes tracejadas, em escala (65 % do maior fasor de tensão): o que importa é o ângulo.
        v_peak = max(abs(p) for p in result.phasors.values())
        i_peak = max((abs(p) for p in result.current_phasors.values()), default=0.0)
        if i_peak > 1e-12:
            scale = 0.65 * v_peak / i_peak
            for phase in ("A", "B", "C"):
                current = result.current_phasors[phase] * rotation * scale
                self.phasor.plot([0, current.real], [0, current.imag],
                                 pen=pg.mkPen(COLORS[phase], width=2, style=Qt.PenStyle.DashLine))
                tag = pg.TextItem(f"I{phase.lower()}", color=COLORS[phase], anchor=(0.5, 0.5))
                tag.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                tag.setPos(current.real * 1.3, current.imag * 1.3)
                self.phasor.addItem(tag)
        self.phasor_title.setText("FASORES" if i_peak > 1e-12 else "FASORES DE TENSÃO")
        self.harmonics.clear()
        heights = np.array(result.harmonic_percent[1:])
        last_harmonic = len(result.harmonic_percent)
        if heights.size and result.thd_percent is not None:
            self.harmonics.addItem(pg.BarGraphItem(
                x=np.arange(2, last_harmonic + 1), height=heights,
                width=0.6, brush=theme.ACCENT, pen=pg.mkPen(None)
            ))
            self.harmonics.setYRange(0, max(5, float(heights.max()) * 1.4), padding=0)
            self.harmonics_title.setText(f"HARMÔNICAS · FASE A (%) · h2–h{last_harmonic}")
            self.thd_label.setText(f"{result.thd_percent:.1f} %")
            over = result.thd_percent > LIMIT_THD_PERCENT
            self.thd_label.setStyleSheet(f"color:{theme.WARNING}" if over else "")
            self.thd_hint.setText(f"h2–h{last_harmonic}" + (f" · acima de {LIMIT_THD_PERCENT:.0f} % (PRODIST)" if over else ""))
        else:
            self.harmonics_title.setText("HARMÔNICAS · taxa insuficiente")
            self.thd_label.setText("—")
            self.harmonics.setYRange(0, 5, padding=0)
            self.thd_hint.setText("THD indisponível (taxa insuficiente)")
        self.meter.show_result(result, rotation, self._pin_volts())
        self._show_energy(result, float(t[-1]))
        self.power_view.clearContents()
        for row, (phase, power) in enumerate(result.power.items()):
            cells = [phase, f"{result.current_rms[phase]:.3f}", f"{power.active_w:.3f}",
                f"{power.reactive_fundamental_var:.3f}", f"{power.apparent_va:.3f}",
                f"{power.power_factor:.4f}" if power.power_factor is not None else "---"]
            for column, value in enumerate(cells):
                self.power_view.setItem(row, column, QTableWidgetItem(value))
        seq = sequence_components(result.phasors)
        unbalance = seq.unbalance_percent
        over = unbalance is not None and unbalance > LIMIT_UNBALANCE_PERCENT
        self.unbalance_label.setText("—" if unbalance is None else f"{unbalance:.1f} %")
        self.unbalance_label.setStyleSheet(f"color:{theme.WARNING}" if over else "")
        self.sequence_label.setText(seq.rotation or "—")
        self.sequence_label.setStyleSheet(f"color:{theme.WARNING}" if seq.rotation == "ACB" else "")
        self.sequence_hint.setText({"ABC": "direta", "ACB": "⚠ inversa"}.get(seq.rotation or "", "indefinida"))
        self.details.setText("")
        self.record_trend(result)
        self.last_analysis = (result, self.mode,
            json.dumps({"name": self.calibration.name, "channels": self.calibration.channels}, ensure_ascii=False),
            float(t[0]), float(t[-1]))

    def _show_energy(self, result, t_end: float) -> None:
        """Acumula energia, demanda e tendência pelo relógio do computador.

        O tempo das amostras não serve: em rajada cada bloco fica em seq × 10 s
        (ver BURST_SPACING_S), o que multiplicaria a energia. Só conta quando
        chegou amostra nova; a mesma janela reanalisada a cada 50 ms não soma
        de novo, e uma serial parada não acumula valor antigo.
        """
        # Com resumos da placa a energia já vem deles (_on_summary), sem lacunas.
        if t_end != self._energy_sample_t and not self._summary_fresh():
            self._energy_sample_t = t_end
            self.stats.update(self._clock(), result)
        if not result.power:
            self.energy_label.setText("---")
            self.reactive_energy_label.setText("---")
            self.energy_hint.setText("sem canais de corrente")
            return
        self.energy_label.setText(si(self.energy.active_wh, "Wh"))
        self.reactive_energy_label.setText(si(self.energy.reactive_varh, "varh"))
        minutes, seconds = divmod(int(self.energy.seconds), 60)
        hours, minutes = divmod(minutes, 60)
        self.energy_hint.setText(f"acumulada em {hours:d}:{minutes:02d}:{seconds:02d}")

    def reset_energy(self) -> None:
        self.stats.reset()
        self._energy_sample_t = None
        self._summary_t = None
        self._last_summary_seq = None
        self.summaries_lost = 0
        if hasattr(self, "energy_label"):
            self.energy_label.setText("0 Wh")
            self.reactive_energy_label.setText("0 varh")
            self.energy_hint.setText("acumulada em 0:00:00")

    def _trigger_index(self, t: np.ndarray, values: np.ndarray, span: float) -> int | None:
        """Primeira subida do canal com mais sinal que ainda deixa `span` segundos à frente."""
        if not self.trigger_check.isChecked():
            return None
        channel = int(np.argmax(np.ptp(values, axis=0)))
        y = values[:, channel] - values[:, channel].mean()
        if np.ptp(y) <= 0:
            return None
        level = 0.1 * np.ptp(y)  # histerese contra ruído e degraus
        rising = np.flatnonzero((y[:-1] < level) & (y[1:] >= level)) + 1
        rising = rising[t[rising] + span <= t[-1]]
        return int(rising[0]) if rising.size else None

    def _scope_span(self) -> float:
        index = self.cycles_combo.currentIndex()
        if index == 3:
            return 0.25
        frequency = getattr(self, "_last_frequency", None) or 60.0
        return min(0.25, (2, 4, 8)[index] / frequency)

    def _add_nav(self, label: str, widget: QWidget, icon_name: str = "scope") -> None:
        button = QPushButton("  " + label)
        button.setIcon(theme.icon(icon_name, theme.MUTED))
        button.setIconSize(QSize(18, 18))
        button.setProperty("title", label)
        button.setObjectName("nav")
        button.setCheckable(True)
        button.clicked.connect(lambda _=False, w=widget: (self.tabs.setCurrentWidget(w), self._sync_nav()))
        self._nav_layout.addWidget(button)
        self.nav_buttons.append((button, widget))
        self._sync_nav()

    def _sync_nav(self, index: int | None = None) -> None:
        current = self.tabs.currentWidget()
        for button, widget in self.nav_buttons:
            button.setChecked(widget is current)
            if widget is current and hasattr(self, "page_title"):
                self.page_title.setText(button.property("title"))

    def enter_kiosk(self, screen=None, hide_cursor: bool = True):
        """Medidor na tela dedicada: só o painel, sem demonstração; sair leva à manutenção."""
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QApplication
        from prisma.ui.kiosk import keep_display_on
        self.kiosk = True
        if self.mode.startswith("DEMONSTRAÇÃO"):
            # Um medidor nunca mostra valores sintéticos: limpa e espera a placa.
            self.buffer.clear()
            self.reset_energy()
            self._invalidate_analysis()
            self._set_mode("DESCONECTADO — NENHUMA PORTA CONFIGURADA")
        if not keep_display_on(True):
            self._log("Quiosque: a tela pode apagar sozinha (ajuste a energia do sistema; ver docs/quiosque.md).")
        if hide_cursor:
            QApplication.setOverrideCursor(QCursor(Qt.CursorShape.BlankCursor))
        self._kiosk_cursor = hide_cursor
        self.hide()
        panel = self.open_touch_panel(screen=screen, kiosk=True)
        panel.closed.connect(self.exit_kiosk)
        return panel

    def exit_kiosk(self) -> None:
        if not self.kiosk:
            return
        from PySide6.QtWidgets import QApplication
        from prisma.ui.kiosk import keep_display_on
        self.kiosk = False
        if self.reader is not None:
            self.reader.persistent = self.reader.network
        keep_display_on(False)
        if getattr(self, "_kiosk_cursor", False):
            QApplication.restoreOverrideCursor()
            self._kiosk_cursor = False
        self._log("Quiosque encerrado: janela de manutenção aberta (F10 volta ao painel).")
        self.showMaximized()

    def open_touch_panel(self, fullscreen: bool = True, screen=None, kiosk: bool = False):
        """Abre o painel touch (medidor inteligente em tela cheia) sobre a medição atual.

        ``screen`` fixa o monitor; sem ele, usa o da janela principal.
        """
        from prisma.ui.touch_panel import PanelData, TouchPanel

        def data() -> PanelData:
            t, voltages = self.buffer.arrays(duration_s=0.12)
            currents = self.buffer.currents(duration_s=0.12)
            return PanelData(self.last_analysis[0] if self.last_analysis else None, self.mode, self.stats,
                             t, voltages, currents, self.data_age())
        panel = getattr(self, "touch_panel", None)
        if panel is None or not panel.isVisible() or panel.kiosk != kiosk:
            if panel is not None and panel.isVisible():
                panel.close()
            panel = TouchPanel(data, self, kiosk=kiosk)
            panel.setWindowIcon(self.windowIcon())
            self.touch_panel = panel
        screen = screen or self.screen()
        if screen is not None:
            # Posiciona antes de mostrar: em tela cheia o Windows usa o monitor onde a janela está.
            panel.setScreen(screen)
            panel.setGeometry(screen.availableGeometry())
        panel.showFullScreen() if fullscreen else panel.show()
        panel.raise_()
        panel.activateWindow()
        return panel

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        self.btn_pause.setChecked(self.paused)
        self.btn_pause.setIcon(theme.icon("play" if self.paused else "pause"))
        self.btn_pause.setToolTip("Retomar gráficos (Espaço)" if self.paused else "Pausar gráficos (Espaço)")
        self.pause_chip.setVisible(self.paused)
        self._log("Gráficos pausados; aquisição e registro continuam." if self.paused else "Gráficos retomados.")

    def export_snapshot(self, filename: str | None = None) -> None:
        if filename is None:
            filename, _ = QFileDialog.getSaveFileName(self, "Exportar imagem", "prisma-instrumentos.png", "PNG (*.png)")
        if not filename:
            return
        if not self.tabs.widget(0).grab().save(filename, "PNG"):
            QMessageBox.critical(self, "Imagem", f"Não foi possível salvar {filename}.")
            return
        self._log(f"Imagem salva: {filename}")

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def show_about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Sobre o PRISMA")
        box.setIconPixmap(app_icon().pixmap(QSize(72, 72)))
        box.setText(f"<h3>PRISMA v{__version__}</h3>"
                    "Plataforma de Registro, Instrumentação, Sinais, Medição e Análise.<br>"
                    "<i>Programar · Medir · Analisar</i>")
        box.setInformativeText("Os gráficos iniciais são sintéticos. As medições não têm certificação metrológica.")
        box.exec()

    def _select_phasor(self, phase: str) -> None:
        self.selected_phase = phase

    def open_code(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Abrir código C", "", "Arquivos C (*.c *.h);;Todos (*.*)"
        )
        if not filename:
            return
        try:
            self.editor.setPlainText(Path(filename).read_text(encoding="utf-8"))
            self.current_file = Path(filename)
            self.editor.document().setModified(False)
            self.tabs.setCurrentWidget(self.editor_page)
            self.file_label.setText(filename)
            self._log(f"Código aberto: {filename}")
        except OSError as exc:
            QMessageBox.critical(self, "Erro ao abrir", str(exc))

    def save_code(self) -> None:
        name = str(self.current_file) if self.current_file else "main.c"
        filename, _ = QFileDialog.getSaveFileName(
            self, "Salvar código C", name, "Arquivos C (*.c *.h);;Todos (*.*)"
        )
        if not filename:
            return
        try:
            Path(filename).write_text(self.editor.toPlainText(), encoding="utf-8")
            self.current_file = Path(filename)
            self.editor.document().setModified(False)
            self.file_label.setText(filename)
            self._log(f"Código salvo: {filename}")
        except OSError as exc:
            QMessageBox.critical(self, "Erro ao salvar", str(exc))

    def closeEvent(self, event) -> None:
        self.runner.close()
        self.debugger.close()
        self.stop_recording()
        if self.reader is not None and self.reader.isRunning():
            self.reader.stop()
            if not self.reader.wait(1500):
                event.ignore()
                return
        super().closeEvent(event)
