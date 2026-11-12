"""Janela do PRISMA: instrumentos virtuais, editor C e aquisição serial."""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pyqtgraph as pg

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTabWidget,
    QVBoxLayout, QWidget, QGridLayout,
)

from prisma.core.measurement import SignalBuffer, analyze
from prisma.core.protocol import Sample
from prisma.core.recording import CsvRecorder
from prisma.core.serial_reader import SerialReader

COLORS = {"A": "#4ad6ea", "B": "#f2b84b", "C": "#e27eaf"}

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
QWidget { background: #101925; color: #e3edf6; font-family: 'Segoe UI'; font-size: 12px; }
QMainWindow { background: #101925; }
QLabel#title { font-size: 28px; font-weight: 800; color: #ffffff; }
QLabel#muted { color: #91a7bb; }
QLabel#metricValue { font-size: 26px; font-weight: 700; }
QFrame#panel { background: #182636; border: 1px solid #2a3c4f; border-radius: 10px; }
QPushButton { background: #1d364a; border: 1px solid #35506a; border-radius: 6px; padding: 8px 11px; }
QPushButton:hover { background: #28516d; }
QPushButton:disabled { background: #1a2734; color: #6c7d8e; border-color: #2a3945; }
QPushButton#primary { background: #087b9b; border-color: #13a4bf; font-weight: 700; }
QComboBox { background: #1c2b3e; border: 1px solid #36536c; padding: 7px; border-radius: 5px; }
QTabWidget::pane { border: 1px solid #2c4255; border-radius: 8px; }
QTabBar::tab { background: #152334; padding: 10px 18px; margin-right: 2px; }
QTabBar::tab:selected { background: #244157; color: #ffffff; }
QPlainTextEdit { background: #0b1521; color: #d8ecfc; border: 1px solid #274058; border-radius: 5px; padding: 8px; }
QSplitter::handle { background: #2a4155; }
QMenuBar, QMenu { background: #172638; }
"""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PRISMA Studio | Instrumentação e Sistemas Embarcados — v0.1")
        self.resize(1480, 920)
        self.setMinimumSize(1060, 700)
        self.setStyleSheet(STYLE)
        pg.setConfigOptions(antialias=True, background="#132231", foreground="#b6cad9")
        self.buffer = SignalBuffer()
        self.reader: SerialReader | None = None
        self.recorder: CsvRecorder | None = None
        self.current_file: Path | None = None
        self.demo_index = 0
        self.mode = "DEMONSTRAÇÃO — SINAIS SINTÉTICOS"
        self._invalid_sample_logs = 0
        self._build_ui()
        self._build_menu()
        self.refresh_ports()
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self._log("PRISMA v0.1 iniciado em MODO DEMONSTRAÇÃO (sem dados de hardware).")
        self._log("Gravação BDM e compilação ColdFire V1 ainda não integradas.")

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("Arquivo")
        for name, fn in (("Abrir código C…", self.open_code), ("Salvar código C…", self.save_code)):
            action = QAction(name, self)
            action.triggered.connect(fn)
            menu.addAction(action)
        info = self.menuBar().addMenu("Ajuda")
        about = QAction("Sobre o PRISMA", self)
        about.triggered.connect(lambda: QMessageBox.information(
            self, "PRISMA v0.1",
            "Plataforma de Registro, Instrumentação, Sinais, Medição e Análise.\n"
            "Os gráficos iniciais são SINTÉTICOS. BDM e firmware MCF51EM256 ainda pendentes."
        ))
        info.addAction(about)
        acquisition = self.menuBar().addMenu("Aquisição")
        self.record_action = QAction("Iniciar registro CSV…", self)
        self.record_action.triggered.connect(self.toggle_recording)
        acquisition.addAction(self.record_action)
        self.record_label = QLabel("CSV: inativo")
        self.statusBar().addPermanentWidget(self.record_label)

    def toggle_recording(self) -> None:
        if self.recorder is not None:
            self.stop_recording()
            return
        if not self.mode.startswith(("DEMONSTRAÇÃO", "AQUISIÇÃO SERIAL REAL")):
            QMessageBox.information(self, "Registro CSV", "Ative o modo demo ou aguarde amostras da serial.")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "Registrar amostras CSV", "aquisicao.csv", "CSV (*.csv)"
        )
        if not filename:
            return
        try:
            self.recorder = CsvRecorder(Path(filename), self.mode)
        except OSError as exc:
            QMessageBox.critical(self, "Erro ao iniciar registro", str(exc))
            return
        self.record_action.setText("Parar registro CSV")
        self.record_label.setText("CSV: gravando · 0 amostras")
        self._log(f"Registro CSV iniciado: {filename} | {self.mode}")

    def stop_recording(self) -> None:
        recorder = self.recorder
        self.recorder = None
        if recorder is None:
            return
        try:
            recorder.close()
        except OSError as exc:
            self._log(f"Erro ao finalizar CSV: {exc}")
        self.record_action.setText("Iniciar registro CSV…")
        self.record_label.setText("CSV: inativo")
        self._log(f"Registro CSV encerrado: {recorder.count} amostras | {recorder.path}")

    def _record_sample(self, sample: Sample) -> None:
        if self.recorder is not None:
            try:
                self.recorder.write(sample)
            except OSError as exc:
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
        title = QLabel("◈ PRISMA")
        title.setObjectName("title")
        subtitle = QLabel("PLATAFORMA DE REGISTRO, INSTRUMENTAÇÃO, SINAIS, MEDIÇÃO E ANÁLISE")
        subtitle.setObjectName("muted")
        brand.addWidget(title)
        brand.addWidget(subtitle)
        header.addLayout(brand, stretch=1)
        self.mode_label = QLabel(self.mode)
        self.mode_label.setStyleSheet(
            "color: #f4bf62; font-weight: 700; padding: 8px; background: #40351e; border-radius: 5px;"
        )
        header.addWidget(self.mode_label)
        main.addLayout(header)

        toolbar = QHBoxLayout()
        self.btn_open = QPushButton("Abrir C")
        self.btn_save = QPushButton("Salvar C")
        self.btn_compile = QPushButton("Compilar (pendente)")
        self.btn_flash = QPushButton("Gravar BDM (pendente)")
        for b in (self.btn_compile, self.btn_flash):
            b.setEnabled(False)
            b.setToolTip("Requer integração e validação da toolchain ColdFire V1/BDM.")
        self.btn_open.clicked.connect(self.open_code)
        self.btn_save.clicked.connect(self.save_code)
        for btn in (self.btn_open, self.btn_save, self.btn_compile, self.btn_flash):
            toolbar.addWidget(btn)
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
        sidebar, side = self._panel()
        sidebar.setMinimumWidth(235)
        sidebar.setMaximumWidth(320)
        side.addWidget(QLabel("HARDWARE-ALVO"))
        board = QLabel("DEMOEM\nMCF51EM256")
        board.setAlignment(Qt.AlignmentFlag.AlignCenter)
        board.setStyleSheet(
            "font-size: 23px; font-weight: 700; color: #4ad6ea;"
            "background: #102030; border-radius: 8px; padding: 24px 8px"
        )
        side.addWidget(board)
        self.hw_status = QLabel("BDM: NÃO CONECTADO\nSERIAL: NÃO CONECTADO")
        self.hw_status.setStyleSheet("color: #f5bf69;")
        side.addWidget(self.hw_status)
        side.addWidget(QLabel("INSTRUMENTOS"))
        for text in (
            "Osciloscópio · 3 canais",
            "Diagrama fasorial",
            "Análise de harmônicas",
            "Tensão RMS",
            "Editor C"
        ):
            item = QLabel("▸  " + text)
            item.setStyleSheet("color: #bed3e2; padding: 7px;")
            side.addWidget(item)
        side.addStretch(1)
        note = QLabel(
            "Primeira versão: análise demonstrativa.\n"
            "A instrumentação física depende de firmware e canal serial compatíveis."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        side.addWidget(note)
        body.addWidget(sidebar)

        self.tabs = QTabWidget()
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
            caption = QLabel("FASE " + phase + " · RMS")
            caption.setObjectName("muted")
            value = QLabel("--- V")
            value.setObjectName("metricValue")
            value.setStyleSheet(f"color: {COLORS[phase]}; font-size: 26px; font-weight: 700;")
            card_layout.addWidget(caption)
            card_layout.addWidget(value)
            metrics.addWidget(card)
            self.metric_labels[phase] = value
        info_card, info_layout = self._panel()
        caption = QLabel("FREQUÊNCIA DE REFERÊNCIA")
        caption.setObjectName("muted")
        info_layout.addWidget(caption)
        info_layout.addWidget(QLabel("60 Hz (fixa)"))
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

        console_wrap, console_lay = self._panel()
        console_lay.addWidget(QLabel("CONSOLE / LOG DE COMUNICAÇÃO"))
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumHeight(116)
        self.console.setFont(QFont("Consolas", 10))
        console_lay.addWidget(self.console)
        main.addWidget(console_wrap)
        self.statusBar().showMessage(
            "PRISMA v0.1 | Sinais simulados — nenhuma aquisição física ativa"
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
            self.reader.wait(1200)
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
        self._invalid_sample_logs = 0
        self._set_mode(f"CONECTANDO A {port} — SEM DADOS")
        self.reader = SerialReader(port, parent=self)
        self.reader.connected.connect(lambda: self._on_connected(port))
        self.reader.sample_received.connect(self._on_sample)
        self.reader.message.connect(self._log)
        self.reader.disconnected.connect(self._on_disconnected)
        self.reader.start()
        self.b_connect.setText("Desconectar")

    def _on_connected(self, port: str) -> None:
        self.hw_status.setText(f"BDM: NÃO VALIDADO\nSERIAL: {port} ABERTA")
        self._set_mode(f"SERIAL {port} — AGUARDANDO AMOSTRAS")

    def _on_sample(self, sample: Sample) -> None:
        try:
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
        self.hw_status.setText("BDM: NÃO VALIDADO\nSERIAL: DESCONECTADA")
        self.b_connect.setText("Conectar serial")
        if not self.mode.startswith("DEMONSTRAÇÃO"):
            self._set_mode("SERIAL DESCONECTADA — DADOS RETIDOS")

    def start_demo(self) -> None:
        self.stop_recording()
        if self.reader is not None and self.reader.isRunning():
            self.reader.stop()
            self.reader.wait(1200)
        self.buffer.clear()
        self.demo_index = 0
        self.hw_status.setText("BDM: NÃO CONECTADO\nSERIAL: NÃO CONECTADO")
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
                self.record_label.setText(f"CSV: gravando · {self.recorder.count} amostras")
            except OSError as exc:
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
            sample = Sample(float(tt), float(va), float(vb), float(vc))
            self.buffer.add(sample)
            self._record_sample(sample)
        self.demo_index += 120

    def _draw_signals(self) -> None:
        t, values = self.buffer.arrays(duration_s=0.25)
        if t.size < 12:
            return
        x = t - t[-1]
        for i, phase in enumerate(("A", "B", "C")):
            self.curves[phase].setData(x, values[:, i])
        self.wave.setXRange(-0.25, 0.0, padding=0)
        if (t[-1] - t[0]) < 0.12:
            return
        try:
            result = analyze(t, values, fundamental_hz=60)
        except ValueError as exc:
            for label in self.metric_labels.values():
                label.setText("--- V")
            self.phasor.clear()
            self.harmonics.clear()
            self.details.setText(f"Análise indisponível: {exc}")
            return
        for phase in ("A", "B", "C"):
            self.metric_labels[phase].setText(f"{result.rms[phase]:.2f} V")
        self.phasor.clear()
        self.phasor.addItem(pg.InfiniteLine(
            pos=0, angle=0, pen=pg.mkPen("#506579", width=1)
        ))
        self.phasor.addItem(pg.InfiniteLine(
            pos=0, angle=90, pen=pg.mkPen("#506579", width=1)
        ))
        for phase in ("A", "B", "C"):
            ph = result.phasors[phase]
            self.phasor.plot(
                [0, ph.real], [0, ph.imag],
                pen=pg.mkPen(COLORS[phase], width=3),
                symbol="o", symbolSize=7, symbolBrush=COLORS[phase]
            )
            tag = pg.TextItem(phase, color=COLORS[phase], anchor=(0.5, 0.5))
            tag.setPos(ph.real * 1.13, ph.imag * 1.13)
            self.phasor.addItem(tag)
        self.harmonics.clear()
        heights = np.array(result.harmonic_percent[1:])
        last_harmonic = len(result.harmonic_percent)
        if heights.size:
            self.harmonics.addItem(pg.BarGraphItem(
                x=np.arange(2, last_harmonic + 1), height=heights,
                width=0.65, brush="#24bace"
            ))
            self.harmonics.setYRange(0, max(5, float(heights.max()) * 1.4), padding=0)
            self.harmonics.setTitle(f"HARMÔNICAS · FASE A · h2 a h{last_harmonic}")
            thd = np.sqrt(np.sum(heights**2))
            thd_text = f"THD estimada Va (h2–h{last_harmonic}): {thd:.2f} %"
        else:
            self.harmonics.setTitle("HARMÔNICAS · TAXA DE AMOSTRAGEM INSUFICIENTE")
            self.harmonics.setYRange(0, 5, padding=0)
            thd_text = "THD indisponível: taxa insuficiente para h2."
        angles = {p: np.degrees(np.angle(result.phasors[p])) for p in ("A", "B", "C")}
        source = (
            "DADOS SINTÉTICOS\nNão representam a DEMOEM física."
            if self.mode.startswith("DEMONSTRAÇÃO")
            else "DADOS DA PORTA SERIAL\nEscala e sincronismo dependem do firmware."
        )
        self.details.setText(
            f"{source}\n\n"
            f"{thd_text}\n\n"
            f"Fasor A: {abs(result.phasors['A']):.1f} V ∠ {angles['A']:.1f}°\n"
            f"Fasor B: {abs(result.phasors['B']):.1f} V ∠ {angles['B']:.1f}°\n"
            f"Fasor C: {abs(result.phasors['C']):.1f} V ∠ {angles['C']:.1f}°\n\n"
            "Estimativas não calibradas nem certificadas."
        )

    def open_code(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Abrir código C", "", "Arquivos C (*.c *.h);;Todos (*.*)"
        )
        if not filename:
            return
        try:
            self.editor.setPlainText(Path(filename).read_text(encoding="utf-8"))
            self.current_file = Path(filename)
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
            self._log(f"Código salvo: {filename}")
        except OSError as exc:
            QMessageBox.critical(self, "Erro ao salvar", str(exc))

    def closeEvent(self, event) -> None:
        self.stop_recording()
        if self.reader is not None and self.reader.isRunning():
            self.reader.stop()
            self.reader.wait(1500)
        super().closeEvent(event)
