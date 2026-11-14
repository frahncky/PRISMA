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
from prisma.core.measurement import SignalBuffer, analyze
from prisma.core.protocol import Sample
from prisma.core.recording import CsvRecorder
from prisma.core.serial_reader import SerialReader
from prisma.core.history import SqliteRecorder
from prisma.ui import theme
from prisma.ui.editor import CodeEditor, EditorPanel
from prisma.ui.features import FeaturesMixin

COLORS = theme.PHASE
# DEMOEM: ADC de 16 bits com VREFH = VDD do regulador de 3,3 V (confirmar com multímetro).
ADC_VREF_V = 3.3
ADC_FULL_SCALE = 65535
ICON_PATH = Path(__file__).with_name("assets") / "prisma.svg"


def _degrees(phasor: complex, decimals: int) -> str:
    """Ângulo em graus sem "-0.0" (zero negativo de arredondamento)."""
    value = round(float(np.degrees(np.angle(phasor))), decimals) + 0.0
    return f"{value:.{decimals}f}"


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


class MainWindow(FeaturesMixin, QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"PRISMA Studio | Instrumentação e Sistemas Embarcados — v{__version__}")
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
        self.reader: SerialReader | None = None
        self.recorder: CsvRecorder | SqliteRecorder | None = None
        self.current_file: Path | None = None
        self.demo_index = 0
        self.mode = "DEMONSTRAÇÃO — SINAIS SINTÉTICOS"
        self._invalid_sample_logs = 0
        self._build_ui()
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

    def _card(self, caption: str, color: str = theme.TEXT, hint: str = "") -> tuple[QFrame, QLabel, QLabel]:
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
        layout.addWidget(title)
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
        plot.setMenuEnabled(False)
        return plot

    @staticmethod
    def _wrap(widget: QWidget) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(widget)
        return frame

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
        logo.setPixmap(app_icon().pixmap(QSize(34, 34)))
        brand_row.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        brand = QLabel("PRISMA")
        brand.setObjectName("brand")
        sub = QLabel("Programar · Medir · Analisar")
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
        section = QLabel("DISPOSITIVO")
        section.setObjectName("railSection")
        side.addWidget(section)
        self.board_label = QLabel("DEMOEM · MCF51EM256")
        self.board_label.setWordWrap(True)
        self.board_label.setStyleSheet(f"color: {theme.TEXT}; font-weight: 600;")
        side.addWidget(self.board_label)
        self.hw_status = QLabel()
        side.addWidget(self.hw_status)
        self._set_link_status("Serial desconectada", theme.SUBTLE)
        version = QLabel(f"v{__version__}")
        version.setObjectName("brandSub")
        side.addSpacing(8)
        side.addWidget(version)
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
        self.port_combo.setToolTip("Porta serial da placa")
        top.addWidget(self.port_combo)
        refresh = QPushButton()
        refresh.setObjectName("icon")
        refresh.setIcon(theme.icon("refresh"))
        refresh.setToolTip("Atualizar portas COM")
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

        # Página de instrumentação.
        dashboard = QWidget()
        dash = QVBoxLayout(dashboard)
        dash.setContentsMargins(20, 16, 20, 12)
        dash.setSpacing(12)
        metrics = QHBoxLayout()
        metrics.setSpacing(12)
        self.metric_labels = {}
        for phase in ("A", "B", "C"):
            card, value, _ = self._card(f"Fase {phase} · RMS", theme.PHASE[phase], "tensão")
            value.setText("--- V")
            metrics.addWidget(card)
            self.metric_labels[phase] = value
        card, self.frequency_label, self.frequency_hint = self._card("Frequência", hint="fundamental")
        metrics.addWidget(card)
        card, self.thd_label, self.thd_hint = self._card("THD · fase A", hint="h2 a h15")
        metrics.addWidget(card)
        dash.addLayout(metrics)

        self.wave = self._plot("Osciloscópio")
        self.wave.setLabel("left", "Tensão", units="V")
        self.wave.setLabel("bottom", "Tempo", units="s")
        self.curves = {
            phase: self.wave.plot(pen=pg.mkPen(theme.PHASE[phase], width=2), name=f"Fase {phase}")
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
        self.wave.setMinimumHeight(200)
        scope_layout.addWidget(self.wave)
        dash.addWidget(scope_card, stretch=11)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        self.phasor = self._plot("Fasores")
        self.phasor.setLabel("left", "Imaginário", units="V")
        self.phasor.setLabel("bottom", "Real", units="V")
        self.phasor.setAspectLocked(True)
        self.phasor.setXRange(-160, 160, padding=0)
        self.phasor.setYRange(-160, 160, padding=0)
        self.harmonics = self._plot("Harmônicas · fase A")
        self.harmonics.setLabel("left", "% da fundamental")
        self.harmonics.setLabel("bottom", "Ordem")
        self.harmonics.showGrid(x=False, y=True, alpha=0.12)
        self.harmonics.setXRange(1.5, 15.5, padding=0)
        details_card = QFrame()
        details_card.setObjectName("card")
        details_layout = QVBoxLayout(details_card)
        details_layout.setContentsMargins(16, 12, 16, 12)
        details_title = QLabel("RESUMO")
        details_title.setObjectName("panelTitle")
        details_layout.addWidget(details_title)
        self.details = QLabel("Aguardando amostras…")
        self.details.setObjectName("muted")
        self.details.setTextFormat(Qt.TextFormat.RichText)
        self.details.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.details.setWordWrap(True)
        details_layout.addWidget(self.details, stretch=1)
        bottom.addWidget(self._wrap(self.phasor), stretch=4)
        bottom.addWidget(self._wrap(self.harmonics), stretch=5)
        bottom.addWidget(details_card, stretch=4)
        for widget in (bottom.itemAt(i).widget() for i in range(bottom.count())):
            widget.setMaximumHeight(270)
        dash.addLayout(bottom, stretch=9)
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
        self.statusBar().showMessage(f"PRISMA v{__version__} · sinais simulados")
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

    def select_port(self, port: str) -> bool:
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
        else:
            index = self.port_combo.findData(selected)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)

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
        self._invalidate_analysis()
        self.hardware_view.setPlainText("Aguardando telemetria de estados do firmware.")
        self._invalid_sample_logs = 0
        self._set_mode(f"CONECTANDO A {port} — SEM DADOS")
        self.reader = SerialReader(port, self.device_profile.baudrate, parent=self, parser=self.sample_parser)
        reader = self.reader
        self.reader.connected.connect(lambda: self._on_connected(port) if self.reader is reader else None)
        self.reader.sample_received.connect(lambda sample: self._on_sample(sample) if self.reader is reader else None)
        self.reader.status_received.connect(lambda status: self._on_hardware_status(status) if self.reader is reader else None)
        self.reader.block_received.connect(lambda block: self._on_block(block) if self.reader is reader else None)
        self.reader.message.connect(self._log)
        self.reader.disconnected.connect(lambda: self._on_disconnected() if self.reader is reader else None)
        self.reader.start()
        self._connect_button(True)

    def _connect_button(self, connected: bool) -> None:
        self.b_connect.setText("Desconectar" if connected else "Conectar")
        self.b_connect.setIcon(theme.icon("unplug" if connected else "plug", "#c8f5dc" if connected else "#ffffff"))
        self.b_connect.setProperty("connected", connected)
        self.b_connect.style().unpolish(self.b_connect)
        self.b_connect.style().polish(self.b_connect)

    def _on_connected(self, port: str) -> None:
        self._set_link_status(f"{port} conectada", theme.SUCCESS)
        self._set_mode(f"SERIAL {port} — AGUARDANDO AMOSTRAS")

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
        if not self.mode.startswith("AQUISIÇÃO SERIAL REAL"):
            port = self.reader.port if self.reader else "COM"
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
        transmission = (n * 12 + 150) * 10 / max(1, self.device_profile.baudrate)
        start = arrival - self._session_t0 - transmission - n / block.fs_hz
        start = max(start, self._last_record_t + 1 / block.fs_hz)
        times = [start + i / block.fs_hz for i in range(n)]
        self._last_record_t = times[-1]
        return times

    def _pin_volts(self) -> bool:
        """Rajada sem calibração: valores convertidos para tensão no pino do ADC."""
        return self.raw_counts and not self.calibration.channels

    def _apply_units(self) -> None:
        label = "Tensão no pino ADC" if self._pin_volts() else "Tensão"
        self.wave.setLabel("left", label, units="V")
        self.phasor.setLabel("left", "Imaginário", units="V")
        self.phasor.setLabel("bottom", "Real", units="V")
        if self.raw_counts:
            self.phasor.enableAutoRange()

    def _on_block(self, block) -> None:
        """Rajada de taxa fixa: um reinício do firmware (seq menor) recomeça o buffer."""
        if not self.raw_counts:
            self.raw_counts = True
            self._apply_units()
            if self.frequency_combo.currentIndex() != 2:
                self.frequency_combo.setCurrentIndex(2)
            # Cada rajada começa num instante arbitrário do ciclo: só o ângulo entre fases
            # é estável, então a fase A vira a referência (0°).
            if self.phasor_reference.currentIndex() == 0:
                self.phasor_reference.setCurrentIndex(1)
            self._log(f"Rajada recebida: frequência em Automática (40–70 Hz). Sem calibração, os valores "
                      f"são a tensão no pino do ADC (contagem × {ADC_VREF_V} V / {ADC_FULL_SCALE}).")
        self._show_block(block, ADC_VREF_V, ADC_FULL_SCALE)
        last = self.buffer.arrays(duration_s=0.0)[0]
        if last.size and block.samples[0].t <= last[-1]:
            self.buffer.clear()
        scale = ADC_VREF_V / ADC_FULL_SCALE if self._pin_volts() else None
        starts = self._block_record_times(block)
        for sample, record_t in zip(block.samples, starts):
            if scale is not None:
                sample = Sample(sample.t, sample.va * scale, sample.vb * scale, sample.vc * scale)
            self._on_sample(sample, record_t)
        names = "/".join(block.channels)
        warning = f" · timeout ADC {block.timeout_mask}" if block.timeout_mask else ""
        unit = f"tensão no pino ADC (Vref {ADC_VREF_V} V)" if scale else "calibração ativa"
        self.statusBar().showMessage(
            f"Rajada {block.seq}: {len(block.samples)} amostras de {names} a {block.fs_hz:.1f} Hz · {unit}{warning}")

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
        self._invalidate_analysis()
        self.hardware_view.setPlainText("Demonstração: nenhum estado físico recebido.")
        self.demo_index = 0
        self._set_link_status("Serial desconectada", theme.SUBTLE)
        self._connect_button(False)
        self._set_mode("DEMONSTRAÇÃO — SINAIS SINTÉTICOS")
        if self.raw_counts:
            self.raw_counts = False
            self._apply_units()
            self.phasor.setXRange(-160, 160, padding=0)
            self.phasor.setYRange(-160, 160, padding=0)
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
            result = analyze(t, values, fundamental_hz=frequency, currents=self.buffer.currents(), window=window)
        except ValueError as exc:
            self.last_analysis = None
            self.frequency_label.setText("—")
            self.thd_label.setText("—")
            self.power_view.clearContents()
            for label in self.metric_labels.values():
                label.setText("--- V")
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
        self.frequency_label.setText(f"{result.frequency_hz:.2f} Hz")
        self.frequency_hint.setText(("automática" if self.frequency_combo.currentIndex() == 2 else "referência fixa"))
        for phase in ("A", "B", "C"):
            self.metric_labels[phase].setText(
                f"{result.rms[phase]:.3f} V" if self._pin_volts() else f"{result.rms[phase]:.2f} V")
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
            tag = pg.TextItem(phase, color=COLORS[phase], anchor=(0.5, 0.5))
            tag.setPos(ph.real * 1.13, ph.imag * 1.13)
            self.phasor.addItem(tag)
        self.harmonics.clear()
        heights = np.array(result.harmonic_percent[1:])
        last_harmonic = len(result.harmonic_percent)
        if heights.size and result.thd_percent is not None:
            self.harmonics.addItem(pg.BarGraphItem(
                x=np.arange(2, last_harmonic + 1), height=heights,
                width=0.6, brush=theme.ACCENT, pen=pg.mkPen(None)
            ))
            self.harmonics.setYRange(0, max(5, float(heights.max()) * 1.4), padding=0)
            self.harmonics.setTitle(f"Harmônicas · fase A · h2–h{last_harmonic}", color=theme.MUTED, size="10pt")
            self.thd_label.setText(f"{result.thd_percent:.1f} %")
            self.thd_hint.setText(f"h2 a h{last_harmonic}")
            thd = result.thd_percent
            thd_text = f"{thd:.2f} % (h2–h{last_harmonic})"
        else:
            self.harmonics.setTitle("Harmônicas · taxa insuficiente", color=theme.MUTED, size="10pt")
            self.thd_label.setText("—")
            self.harmonics.setYRange(0, 5, padding=0)
            thd_text = "THD indisponível (taxa insuficiente)"
        self.power_view.clearContents()
        rows = []
        for phase in ("A", "B", "C"):
            ph = result.phasors[phase] * rotation
            rows.append((f"<span style='color:{COLORS[phase]}'>■</span> Fasor {phase}",
                         f"{abs(ph):.3f} V ∠ {_degrees(ph, 1)}°"))
        if result.power:
            p_total = sum(p.active_w for p in result.power.values())
            q_total = sum(p.reactive_fundamental_var for p in result.power.values())
            rows.append(("ΣP / ΣQ1", f"{p_total:.1f} W / {q_total:.1f} var"))
            for row, (phase, power) in enumerate(result.power.items()):
                cells = [phase, f"{result.current_rms[phase]:.3f}", f"{power.active_w:.3f}",
                    f"{power.reactive_fundamental_var:.3f}", f"{power.apparent_va:.3f}",
                    f"{power.power_factor:.4f}" if power.power_factor is not None else "---"]
                for column, value in enumerate(cells):
                    self.power_view.setItem(row, column, QTableWidgetItem(value))
        else:
            rows.append(("Potências", "sem correntes"))
        source = ("Demonstração (sintético)" if self.mode.startswith("DEMONSTRAÇÃO")
                  else "Pino do ADC (sem calibração)" if self._pin_volts() else "Porta serial")
        rows.append(("THD fase A", thd_text))
        rows.append(("Origem", source))
        rows.append(("Calibração", self.calibration.name))
        self.details.setText(
            "<table width='100%' cellspacing='0' cellpadding='3'>"
            + "".join(f"<tr><td style='color:{theme.MUTED}'>{k}</td>"
                      f"<td align='right' style='color:{theme.TEXT}'>{v}</td></tr>" for k, v in rows)
            + f"</table><p style='color:{theme.SUBTLE}; font-size:10px'>Estimativas sem certificação metrológica.</p>")
        self.last_analysis = (result, self.mode,
            json.dumps({"name": self.calibration.name, "channels": self.calibration.channels}, ensure_ascii=False),
            float(t[0]), float(t[-1]))

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
