"""Janela do PRISMA: instrumentos virtuais, editor C e aquisição serial."""
from __future__ import annotations

from pathlib import Path
import json
import sqlite3
import numpy as np
import pyqtgraph as pg

from PySide6.QtCore import QSize, QTimer, Qt
from PySide6.QtGui import QAction, QFont, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
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
from prisma.ui.features import FeaturesMixin

COLORS = {"A": "#4ad6ea", "B": "#f2b84b", "C": "#e27eaf"}
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

STYLE = """
QWidget { background: #0d1522; color: #e3edf6; font-family: 'Segoe UI'; font-size: 12px; }
QMainWindow { background: #0d1522; }
QLabel#title { font-size: 26px; font-weight: 800; color: #ffffff; letter-spacing: 3px; }
QLabel { background: transparent; }
QLabel#muted { color: #8ea3b8; }
QLabel#section { color: #6f86a0; font-size: 10px; font-weight: 700; letter-spacing: 1.5px; padding-top: 6px; }
QLabel#metricValue { font-size: 26px; font-weight: 700; }
QLabel#chip { background: #3a2a10; border: 1px solid #c08a2c; border-radius: 11px; padding: 4px 10px; color: #ffd890; font-weight: 700; }
QFrame#panel { background: #142133; border: 1px solid #22344a; border-radius: 12px; }
QPushButton { background: #1a2d44; border: 1px solid #2c4560; border-radius: 7px; padding: 7px 12px; }
QPushButton:hover { background: #22405e; border-color: #3d6488; }
QPushButton:pressed { background: #163049; }
QPushButton:checked { background: #5a3d12; border-color: #c08a2c; color: #ffd890; }
QPushButton:disabled { background: #141f2d; color: #5d6f82; border-color: #1f2d3d; }
QPushButton#primary { background: #0a7f9e; border-color: #17a9c4; font-weight: 700; color: #ffffff; }
QPushButton#primary:hover { background: #0c93b6; }
QPushButton#nav { text-align: left; background: transparent; border: none; border-radius: 7px; padding: 8px 10px; color: #bed3e2; }
QPushButton#nav:hover { background: #1b2c42; color: #ffffff; }
QPushButton#nav:checked { background: #1e3b57; color: #ffffff; border-left: 3px solid #4ad6ea; }
QComboBox { background: #17263a; border: 1px solid #2c4560; padding: 6px 8px; border-radius: 6px; }
QComboBox QAbstractItemView { background: #17263a; selection-background-color: #22405e; }
QTabWidget::pane { border: 1px solid #22344a; border-radius: 10px; top: -1px; }
QTabBar::tab { background: transparent; color: #8ea3b8; padding: 9px 16px; border-bottom: 2px solid transparent; }
QTabBar::tab:hover { color: #e3edf6; }
QTabBar::tab:selected { color: #ffffff; border-bottom: 2px solid #4ad6ea; }
QPlainTextEdit { background: #09111c; color: #d8ecfc; border: 1px solid #22344a; border-radius: 8px; padding: 8px; }
QTableWidget { background: #0f1a2a; gridline-color: #22344a; border: 1px solid #22344a; border-radius: 8px; }
QHeaderView::section { background: #17263a; color: #9fb4ca; border: none; padding: 6px; font-weight: 600; }
QSplitter::handle { background: #0d1522; width: 6px; }
QMenuBar { background: #0d1522; }
QMenuBar::item:selected { background: #1b2c42; }
QMenu { background: #142133; border: 1px solid #2a3f57; }
QMenu::item:selected { background: #22405e; }
QStatusBar { background: #0a111c; color: #8ea3b8; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #2a3f57; border-radius: 5px; min-height: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
"""


class MainWindow(FeaturesMixin, QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"PRISMA Studio | Instrumentação e Sistemas Embarcados — v{__version__}")
        self.resize(1480, 920)
        self.setMinimumSize(1060, 700)
        self.setStyleSheet(STYLE)
        self.setWindowIcon(app_icon())
        self.paused = False
        pg.setConfigOptions(antialias=True, background="#132231", foreground="#b6cad9")
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

    @staticmethod
    def _panel() -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(9)
        return frame, layout

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setSpacing(11)
        main.setContentsMargins(16, 12, 16, 12)

        header = QHBoxLayout()
        brand = QVBoxLayout()
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(QSize(46, 46)))
        header.addWidget(logo)
        header.addSpacing(6)
        title = QLabel("PRISMA")
        title.setObjectName("title")
        subtitle = QLabel("Plataforma de Registro, Instrumentação, Sinais, Medição e Análise")
        subtitle.setObjectName("muted")
        brand.addWidget(title)
        brand.addWidget(subtitle)
        header.addLayout(brand, stretch=1)
        self.mode_label = QLabel(self.mode)
        self.mode_label.setStyleSheet(
            "color: #f4bf62; font-weight: 700; padding: 8px; background: #40351e; border-radius: 5px;"
        )
        self.pause_chip = QLabel("GRÁFICOS PAUSADOS")
        self.pause_chip.setObjectName("chip")
        self.pause_chip.setVisible(False)
        header.addWidget(self.pause_chip)
        header.addSpacing(6)
        header.addWidget(self.mode_label)
        main.addLayout(header)

        toolbar = QHBoxLayout()
        self.btn_open = QPushButton("Abrir C")
        self.btn_save = QPushButton("Salvar C")
        self.btn_compile = QPushButton("Compilar")
        self.btn_flash = QPushButton("Gravar BDM")
        for b in (self.btn_compile, self.btn_flash):
            b.setEnabled(False)
            b.setToolTip("Requer integração e validação da toolchain ColdFire V1/BDM.")
        self.btn_open.clicked.connect(self.open_code)
        self.btn_save.clicked.connect(self.save_code)
        self.btn_pause = QPushButton("Pausar")
        self.btn_pause.setCheckable(True)
        self.btn_pause.setToolTip("Congela os gráficos sem interromper a aquisição ou o registro (Espaço).")
        self.btn_pause.clicked.connect(lambda _=False: self.toggle_pause())
        self.btn_snapshot = QPushButton("Exportar imagem")
        self.btn_snapshot.setToolTip("Salva os instrumentos como PNG (Ctrl+Shift+S).")
        self.btn_snapshot.clicked.connect(lambda _=False: self.export_snapshot())
        for btn in (self.btn_open, self.btn_save, self.btn_compile, self.btn_flash):
            toolbar.addWidget(btn)
        toolbar.addSpacing(12)
        toolbar.addWidget(self.btn_pause)
        toolbar.addWidget(self.btn_snapshot)
        toolbar.addStretch(1)
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(150)
        toolbar.addWidget(self.port_combo)
        refresh = QPushButton("Atualizar COM")
        refresh.clicked.connect(self.refresh_ports)
        toolbar.addWidget(refresh)
        self.b_connect = QPushButton("Conectar serial")
        self.b_connect.setObjectName("primary")
        self.b_connect.clicked.connect(self.connect_serial)
        toolbar.addWidget(self.b_connect)
        demo_button = QPushButton("Modo demo")
        demo_button.clicked.connect(self.start_demo)
        toolbar.addWidget(demo_button)
        main.addLayout(toolbar)

        body = QSplitter(Qt.Orientation.Horizontal)
        self.nav_buttons: list[QPushButton] = []
        self._nav_layout = QVBoxLayout()
        self._nav_layout.setSpacing(2)
        sidebar, side = self._panel()
        sidebar.setMinimumWidth(235)
        sidebar.setMaximumWidth(320)
        hw_title = QLabel("HARDWARE-ALVO")
        hw_title.setObjectName("section")
        side.addWidget(hw_title)
        board = QLabel("DEMOEM\nMCF51EM256")
        self.board_label = board
        board.setWordWrap(True)
        board.setAlignment(Qt.AlignmentFlag.AlignCenter)
        board.setStyleSheet(
            "font-size: 20px; font-weight: 700; color: #4ad6ea;"
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #10243a, stop:1 #0c1828);"
            "border: 1px solid #1f3a55; border-radius: 10px; padding: 20px 8px"
        )
        side.addWidget(board)
        self.hw_status = QLabel("● Serial: não conectada")
        self.hw_status.setStyleSheet("color: #f5bf69;")
        side.addWidget(self.hw_status)
        nav_title = QLabel("NAVEGAÇÃO")
        nav_title.setObjectName("section")
        side.addWidget(nav_title)
        side.addLayout(self._nav_layout)
        side.addStretch(1)
        note = QLabel("Medições sem certificação metrológica.\nDados reais dependem de firmware e calibração.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        side.addWidget(note)
        body.addWidget(sidebar)

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._sync_nav)
        body.addWidget(self.tabs)
        body.setStretchFactor(1, 1)
        main.addWidget(body, stretch=1)

        dashboard = QWidget()
        dash_layout = QVBoxLayout(dashboard)
        dash_layout.setContentsMargins(10, 11, 10, 10)
        metrics = QHBoxLayout()
        self.metric_labels = {}
        for phase in ("A", "B", "C"):
            card, card_layout = self._panel()
            caption = QLabel("FASE " + phase + " · TENSÃO RMS")
            caption.setObjectName("muted")
            value = QLabel("--- V")
            value.setObjectName("metricValue")
            value.setStyleSheet(f"color: {COLORS[phase]}; font-size: 26px; font-weight: 700;")
            card_layout.addWidget(caption)
            card_layout.addWidget(value)
            metrics.addWidget(card)
            self.metric_labels[phase] = value
        info_card, info_layout = self._panel()
        caption = QLabel("FREQUÊNCIA")
        caption.setObjectName("muted")
        info_layout.addWidget(caption)
        self.frequency_label = QLabel("60 Hz (referência)")
        self.frequency_label.setStyleSheet("font-size: 22px; font-weight: 700; color: #ffffff;")
        info_layout.addWidget(self.frequency_label)
        metrics.addWidget(info_card)
        dash_layout.addLayout(metrics)

        charts = QGridLayout()
        charts.setSpacing(10)
        self.wave = pg.PlotWidget(title="OSCILOSCÓPIO · Va / Vb / Vc")
        self.wave.setLabel("left", "Tensão", units="V")
        self.wave.setLabel("bottom", "Tempo", units="s")
        self.wave.showGrid(x=True, y=True, alpha=0.18)
        self.wave.addLegend(offset=(10, 10))
        self.curves = {
            phase: self.wave.plot(pen=pg.mkPen(COLORS[phase], width=2), name=phase)
            for phase in ("A", "B", "C")
        }
        self.wave.setMinimumHeight(225)

        self.phasor = pg.PlotWidget(title="DIAGRAMA FASORIAL · 60 Hz")
        self.phasor.setLabel("left", "Imaginário", units="V")
        self.phasor.setLabel("bottom", "Real", units="V")
        self.phasor.showGrid(x=True, y=True, alpha=0.2)
        self.phasor.setAspectLocked(True)
        self.phasor.setXRange(-160, 160, padding=0)
        self.phasor.setYRange(-160, 160, padding=0)
        self.phasor.setMinimumHeight(225)

        self.harmonics = pg.PlotWidget(title="HARMÔNICAS · FASE A · h2 a h15")
        self.harmonics.setLabel("left", "% da fundamental")
        self.harmonics.setLabel("bottom", "Ordem harmônica")
        self.harmonics.showGrid(x=False, y=True, alpha=0.2)
        self.harmonics.setXRange(1.5, 15.5, padding=0)
        self.harmonics.setMinimumHeight(225)

        details, details_layout = self._panel()
        details_layout.addWidget(QLabel("ANÁLISE ELÉTRICA"))
        self.details = QLabel("Aguardando amostras...")
        self.details.setObjectName("muted")
        self.details.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.details.setWordWrap(True)
        details_layout.addWidget(self.details)
        details_layout.addStretch(1)
        charts.addWidget(self.wave, 0, 0)
        charts.addWidget(self.phasor, 0, 1)
        charts.addWidget(self.harmonics, 1, 0)
        charts.addWidget(details, 1, 1)
        charts.setColumnStretch(0, 1)
        charts.setColumnStretch(1, 1)
        dash_layout.addLayout(charts, stretch=1)
        self.tabs.addTab(dashboard, "Instrumentação")

        self.editor = QPlainTextEdit(FIRMWARE_SKELETON)
        self.editor.setFont(QFont("Consolas", 12))
        self.tabs.addTab(self.editor, "Firmware C (editor)")
        self._add_nav("Instrumentação", dashboard)
        self._add_nav("Firmware C", self.editor)

        console_wrap, console_lay = self._panel()
        console_title = QLabel("CONSOLE")
        console_title.setObjectName("section")
        console_lay.addWidget(console_title)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumHeight(116)
        self.console.setFont(QFont("Consolas", 10))
        console_lay.addWidget(self.console)
        main.addWidget(console_wrap)
        self.statusBar().showMessage(
            f"PRISMA v{__version__} | Sinais simulados — nenhuma aquisição física ativa"
        )

    def _log(self, message: str) -> None:
        self.console.appendPlainText(message)

    def _set_mode(self, label: str, real: bool = False) -> None:
        self.mode = label
        self.mode_label.setText(label)
        fg, bg = ("#b9f9c5", "#1c533a") if real else ("#f4bf62", "#40351e")
        self.mode_label.setStyleSheet(
            f"color:{fg};background:{bg};font-weight:700;padding:8px;border-radius:5px"
        )
        self.statusBar().showMessage(label)

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
            self.b_connect.setText("Conectar serial")
            return
        port = self.port_combo.currentData()
        if port is None:
            QMessageBox.warning(
                self, "Sem porta COM",
                "Nenhuma porta COM detectada. Confirme o driver e a configuração serial da placa."
            )
            return
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
        self.reader.message.connect(self._log)
        self.reader.disconnected.connect(lambda: self._on_disconnected() if self.reader is reader else None)
        self.reader.start()
        self.b_connect.setText("Desconectar")

    def _on_connected(self, port: str) -> None:
        self.hw_status.setText(f"● Serial: {port} aberta")
        self.hw_status.setStyleSheet("color: #7fe0a0;")
        self._set_mode(f"SERIAL {port} — AGUARDANDO AMOSTRAS")

    def _on_sample(self, sample: Sample) -> None:
        try:
            sample = self.calibration.apply(sample)
            self.buffer.add(sample)
        except ValueError as exc:
            if self._invalid_sample_logs < 5:
                self._log(f"Amostra ignorada: {exc}")
                self._invalid_sample_logs += 1
            return
        self._record_sample(sample)
        if not self.mode.startswith("AQUISIÇÃO SERIAL REAL"):
            port = self.reader.port if self.reader else "COM"
            self._set_mode(f"AQUISIÇÃO SERIAL REAL — {port}", real=True)

    def _on_disconnected(self) -> None:
        self.stop_recording()
        self.hw_status.setText("● Serial: desconectada")
        self.hw_status.setStyleSheet("color: #f5bf69;")
        self.b_connect.setText("Conectar serial")
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
        self.hw_status.setText("● Serial: não conectada")
        self.hw_status.setStyleSheet("color: #f5bf69;")
        self.b_connect.setText("Conectar serial")
        self._set_mode("DEMONSTRAÇÃO — SINAIS SINTÉTICOS")
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
        x = t - t[-1]
        for i, phase in enumerate(("A", "B", "C")):
            self.curves[phase].setData(x, values[:, i])
        self.wave.setXRange(-0.25, 0.0, padding=0)
        if (t[-1] - t[0]) < 0.12:
            return
        try:
            frequency = (60.0, 50.0, None)[self.frequency_combo.currentIndex()]
            window = ("rectangular", "hann")[self.window_combo.currentIndex()]
            result = analyze(t, values, fundamental_hz=frequency, currents=self.buffer.currents(), window=window)
        except ValueError as exc:
            self.last_analysis = None
            self.frequency_label.setText("Indisponível")
            self.power_view.clearContents()
            for label in self.metric_labels.values():
                label.setText("--- V")
            self.phasor.clear()
            self.harmonics.clear()
            self.details.setText(f"Análise indisponível: {exc}")
            return
        self.frequency_label.setText(f"{result.frequency_hz:.3f} Hz")
        self.phasor.setTitle(f"DIAGRAMA FASORIAL · {result.frequency_hz:.3f} Hz")
        for phase in ("A", "B", "C"):
            self.metric_labels[phase].setText(f"{result.rms[phase]:.2f} V")
        self.phasor.clear()
        self.phasor.addItem(pg.InfiniteLine(
            pos=0, angle=0, pen=pg.mkPen("#506579", width=1)
        ))
        self.phasor.addItem(pg.InfiniteLine(
            pos=0, angle=90, pen=pg.mkPen("#506579", width=1)
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
                self.selected_phasor.setText(f"Fase {phase}: {abs(ph):.3f} V ∠ {np.degrees(np.angle(ph)):.2f}°")
            tag = pg.TextItem(phase, color=COLORS[phase], anchor=(0.5, 0.5))
            tag.setPos(ph.real * 1.13, ph.imag * 1.13)
            self.phasor.addItem(tag)
        self.harmonics.clear()
        heights = np.array(result.harmonic_percent[1:])
        last_harmonic = len(result.harmonic_percent)
        if heights.size and result.thd_percent is not None:
            self.harmonics.addItem(pg.BarGraphItem(
                x=np.arange(2, last_harmonic + 1), height=heights,
                width=0.65, brush="#24bace"
            ))
            self.harmonics.setYRange(0, max(5, float(heights.max()) * 1.4), padding=0)
            self.harmonics.setTitle(f"HARMÔNICAS · FASE A · h2 a h{last_harmonic}")
            thd = result.thd_percent
            thd_text = f"THD estimada Va (h2–h{last_harmonic}): {thd:.2f} %"
        else:
            self.harmonics.setTitle("HARMÔNICAS · TAXA DE AMOSTRAGEM INSUFICIENTE")
            self.harmonics.setYRange(0, 5, padding=0)
            thd_text = "THD indisponível: taxa insuficiente para h2 ou fundamental ausente."
        angles = {p: np.degrees(np.angle(result.phasors[p])) for p in ("A", "B", "C")}
        source = (
            "DADOS SINTÉTICOS\nNão representam a DEMOEM física."
            if self.mode.startswith("DEMONSTRAÇÃO")
            else "DADOS DA PORTA SERIAL\nEscala e sincronismo dependem do firmware."
        )
        power_text = "Potências indisponíveis: sem correntes sincronizadas."
        self.power_view.clearContents()
        if result.power:
            power_text = (f"ΣP {sum(p.active_w for p in result.power.values()):.1f} W · "
                f"ΣQ1 {sum(p.reactive_fundamental_var for p in result.power.values()):.1f} var\n"
                "Correntes, S e FP por fase: aba Análise.")
            for row, (phase, power) in enumerate(result.power.items()):
                cells = [phase, f"{result.current_rms[phase]:.3f}", f"{power.active_w:.3f}",
                    f"{power.reactive_fundamental_var:.3f}", f"{power.apparent_va:.3f}",
                    f"{power.power_factor:.4f}" if power.power_factor is not None else "---"]
                for column, value in enumerate(cells):
                    self.power_view.setItem(row, column, QTableWidgetItem(value))
        self.last_analysis = (result, self.mode,
            json.dumps({"name": self.calibration.name, "channels": self.calibration.channels}, ensure_ascii=False),
            float(t[0]), float(t[-1]))
        self.details.setText(
            f"{source}\n"
            f"{thd_text}\n\n"
            f"Fasor A: {abs(result.phasors['A']):.1f} V ∠ {angles['A']:.1f}°\n"
            f"Fasor B: {abs(result.phasors['B']):.1f} V ∠ {angles['B']:.1f}°\n"
            f"Fasor C: {abs(result.phasors['C']):.1f} V ∠ {angles['C']:.1f}°\n"
            f"{power_text}\nEstimativas sem certificação metrológica."
        )

    def _add_nav(self, label: str, widget: QWidget) -> None:
        button = QPushButton(label)
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

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        self.btn_pause.setChecked(self.paused)
        self.btn_pause.setText("Retomar" if self.paused else "Pausar")
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
            self.tabs.setCurrentWidget(self.editor)
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
