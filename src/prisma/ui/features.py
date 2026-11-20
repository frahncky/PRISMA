"""Ferramentas de aquisição, análise, histórico e desenvolvimento."""
from collections import deque
from datetime import datetime
import time
import json
from pathlib import Path
import sqlite3

from PySide6.QtCore import QBuffer, QIODevice, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy,
    QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from prisma.core.calibration import Calibration, delays_from_resistive_load, fit_adc, gains_from_reference
from prisma.core.protocol import (
    CMD_ADC_CAL, CMD_BURST, CMD_INFO, COMMAND_NAMES, adc_cal_text, encode_command, parse_board_info,
)
import numpy as np
import pyqtgraph as pg

from prisma.ui import theme

TREND_POINTS = 3600  # 30 min a 2 pontos/s
CAL_CHANNELS = ("va", "vb", "vc", "ia", "ib", "ic")
from prisma.core.devices import DeviceProfile, load_protocol, serial_inventory
from prisma.core.history import export_session, list_sessions
from prisma.core.reports import write_report
from prisma.core.measurement import sequence_components, three_phase
from prisma.core.toolchain import CommandRunner, DebugSession, Project, artifact_digest


class FeaturesMixin:
    def _build_features(self) -> None:
        self.calibration = Calibration()
        self.block_count = 0        # rajadas recebidas (o assistente do ADC espera uma nova por ponto)
        self.block_names = ("ad4", "ad5", "ad6")
        self.last_block_stats = {}  # canal → (média, desvio, saturado) da última rajada bruta
        self.settings = QSettings("PRISMA", "PRISMA")
        self.device_profile = DeviceProfile("DEMOEM / PRISMA JSON")
        self.sample_parser = load_protocol(self.device_profile.protocol)
        self.project = None
        self.build_digest = None
        self.last_analysis = None
        self.operation = ""
        self.runner = CommandRunner(self)
        self.runner.output.connect(self._build_output)
        self.runner.done.connect(self._operation_done)
        self.debugger = DebugSession(self)
        self.debugger.output.connect(self._debug_output)
        self.console.setMaximumBlockCount(2000)
        acquisition_menu = self.menuBar().addMenu("Dados e dispositivos")
        self.sqlite_action = QAction("Iniciar histórico SQLite…", self)
        self.sqlite_action.triggered.connect(lambda: self.toggle_recording(backend="sqlite"))
        acquisition_menu.addAction(self.sqlite_action)
        for label, handler in (
            ("Consultar histórico SQLite…", self.open_history),
            ("Exportar relatório HTML…", self.export_report),
            ("Salvar diagnóstico serial/USB…", self.save_inventory),
            ("Carregar perfil de dispositivo…", self.load_device),
            ("Calibrar ADC com tensão DC…", self.calibrate_adc),
            ("Perfis de sensor…", self.configure_sensors),
            ("Calibrar com multímetro…", self.calibrate_from_reference),
            ("Calibrar fase com carga resistiva…", self.calibrate_phase),
            ("Carregar calibração…", self.load_calibration),
            ("Restaurar calibração identidade", self.reset_calibration),
        ):
            action = QAction(label, self)
            action.triggered.connect(handler)
            acquisition_menu.addAction(action)

        analysis = QWidget()
        page = QVBoxLayout(analysis)
        page.setContentsMargins(20, 12, 20, 12)
        page.setSpacing(10)
        self.frequency_combo = QComboBox()
        self.frequency_combo.addItems(["60 Hz", "50 Hz", "Automática (40–70 Hz)"])
        self.window_combo = QComboBox()
        self.window_combo.addItems(["Retangular", "Hann"])
        self.phasor_reference = QComboBox()
        self.phasor_reference.addItems(["Absoluta", "Fase A", "Fase B", "Fase C"])
        self.phasor_reference.setCurrentIndex(1)  # fase A em 0°, como nos medidores e no painel touch
        for combo in (self.frequency_combo, self.window_combo, self.phasor_reference):
            combo.setFixedWidth(240)
        self.selected_phasor = QLabel("Clique na ponta de um fasor para inspecionar.")
        self.selected_phase = None
        self.calibration_label = QLabel("Identidade · sem ajuste")
        self.profile_label = QLabel(self.device_profile.name)
        for label in (self.selected_phasor, self.calibration_label, self.profile_label):
            label.setStyleSheet("color: #e6edf5;")

        def card(title: str) -> tuple[QFrame, QFormLayout]:
            frame = QFrame()
            frame.setObjectName("card")
            outer = QVBoxLayout(frame)
            outer.setContentsMargins(18, 10, 18, 12)
            outer.setSpacing(8)
            outer.addWidget(self._section(title))
            form = QFormLayout()
            form.setVerticalSpacing(6)
            form.setHorizontalSpacing(24)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
            outer.addLayout(form)
            return frame, form

        cards = QHBoxLayout()
        cards.setSpacing(10)
        settings, form = card("PARÂMETROS DA ANÁLISE")
        form.addRow(self._muted("Frequência fundamental"), self.frequency_combo)
        form.addRow(self._muted("Janela do ajuste harmônico"), self.window_combo)
        form.addRow(self._muted("Referência dos fasores"), self.phasor_reference)
        cards.addWidget(settings, stretch=1)
        status, form = card("FONTE E CALIBRAÇÃO")
        form.addRow(self._muted("Dispositivo"), self.profile_label)
        form.addRow(self._muted("Calibração"), self.calibration_label)
        calibrate_adc = QPushButton("1 · ADC com tensão DC…")
        calibrate_adc.setToolTip("Só a DEMOEM: tensões DC conhecidas (0–3,3 V) no pino levam contagens a volts.")
        calibrate_adc.clicked.connect(self.calibrate_adc)
        calibrate = QPushButton("2 · Sensores com multímetro…")
        calibrate.setToolTip("Com os sensores ligados: informe tensões e correntes RMS medidas; "
                             "o PRISMA calcula o ganho de cada canal.")
        calibrate.clicked.connect(self.calibrate_from_reference)
        sensors = QPushButton("Sensores…")
        sensors.setToolTip("Módulo ligado em cada canal (SCT-013, TC + resistor, transformador, ZMPT101B): "
                           "V e A aproximados pela relação nominal, antes da etapa 2.")
        sensors.clicked.connect(lambda _=False: self.configure_sensors())
        steps = QHBoxLayout()
        steps.setSpacing(8)
        steps.addWidget(calibrate_adc)
        steps.addWidget(sensors)
        steps.addWidget(calibrate)
        form.addRow(self._muted("Calibrar"), steps)
        form.addRow(self._muted("Fasor selecionado"), self.selected_phasor)
        cards.addWidget(status, stretch=1)
        page.addLayout(cards)

        power_card = QFrame()
        power_card.setObjectName("card")
        power_layout = QVBoxLayout(power_card)
        power_layout.setContentsMargins(18, 10, 18, 12)
        power_layout.setSpacing(6)
        power_layout.addWidget(self._section("POTÊNCIAS POR FASE"))
        self.power_view = QTableWidget(3, 6)
        self.power_view.setHorizontalHeaderLabels(["Fase", "I RMS (A)", "P (W)", "Q1 (var)", "S (VA)", "FP"])
        self.power_view.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.power_view.verticalHeader().setVisible(False)
        self.power_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.power_view.setShowGrid(False)
        rows = self.power_view.verticalHeader()
        rows.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        rows.setMinimumSectionSize(24)
        rows.setDefaultSectionSize(26)
        self.power_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.power_view.setFixedHeight(36 + 3 * 26 + 4)  # cabeçalho + 3 fases, sem rolagem
        power_layout.addWidget(self.power_view)
        note = self._muted("Requer ia, ib e ic sincronizadas com va, vb e vc · Q1 = reativa da fundamental · "
                           "RMS, P e S usam os sinais AC.")
        note.setToolTip("Uma calibração carregada não certifica a cadeia de medição.")
        power_layout.addWidget(note)
        page.addWidget(power_card)

        trend_card = QFrame()
        trend_card.setObjectName("card")
        trend_layout = QVBoxLayout(trend_card)
        trend_layout.setContentsMargins(18, 10, 18, 12)
        trend_head = QHBoxLayout()
        trend_head.addWidget(self._section("TENDÊNCIA DA SESSÃO"))
        trend_head.addStretch(1)
        clear_trend = QPushButton("Limpar")
        clear_trend.setObjectName("ghost")
        clear_trend.clicked.connect(self.clear_trend)
        trend_head.addWidget(clear_trend)
        trend_layout.addLayout(trend_head)
        trend_plots = QHBoxLayout()
        self.trend_rms = self._plot("RMS por fase")
        self.trend_rms.setLabel("bottom", "Tempo", units="s")
        self.trend_curves = {phase: self.trend_rms.plot(pen=pg.mkPen(theme.PHASE[phase], width=2), name=phase)
                             for phase in "ABC"}
        self.trend_freq = self._plot("Frequência (Hz) e desequilíbrio (%)")
        self.trend_freq.setLabel("bottom", "Tempo", units="s")
        self.trend_freq_curve = self.trend_freq.plot(pen=pg.mkPen(theme.ACCENT, width=2))
        self.trend_unb_curve = self.trend_freq.plot(pen=pg.mkPen(theme.WARNING, width=2, style=Qt.PenStyle.DashLine))
        for plot in (self.trend_rms, self.trend_freq):
            plot.setMinimumHeight(135)
            trend_plots.addWidget(plot)
        trend_layout.addLayout(trend_plots)
        page.addWidget(trend_card, stretch=1)
        self.trend = deque(maxlen=TREND_POINTS)
        self._trend_t0 = None
        analysis = self._scrollable(analysis)
        self.tabs.addTab(analysis, "Análise")

        hardware = QWidget()
        hw_layout = QVBoxLayout(hardware)
        hw_layout.setContentsMargins(20, 8, 20, 8)
        hw_layout.setSpacing(6)
        self.hardware_summary = QLabel("Sem telemetria da placa. Conecte a serial para ver os canais do ADC.")
        self.hardware_summary.setObjectName("muted")
        hw_layout.addWidget(self.hardware_summary)
        self.continuous_label = QLabel("Medição contínua: aguardando resumos da placa (firmware com PRISMA_CONTINUOUS).")
        self.continuous_label.setObjectName("muted")
        self.continuous_label.setTextFormat(Qt.TextFormat.RichText)
        hw_layout.addWidget(self.continuous_label)
        # Uma linha cada, sem quebra: rótulo com quebra dentro de QScrollArea faz a
        # página assumir a altura "ideal" e rolar à toa. Texto longo é cortado na borda.
        # Comandos à placa (firmware rev ≥ 3, fio CH340 TXD → J6 PTC0/RX3).
        commands = QHBoxLayout()
        commands.setSpacing(8)
        self.b_board_info = QPushButton("Identificar placa")
        self.b_board_info.clicked.connect(lambda: self.send_board_command(CMD_INFO))
        self.burst_combo = QComboBox()
        for text, every in (("Rajada a cada janela", 1), ("Rajada a cada 5 janelas", 5),
                            ("Rajada a cada 30 janelas", 30), ("Sem rajadas", 0)):
            self.burst_combo.addItem(text, every)
        self.burst_combo.setToolTip("Forma de onda para gráficos, fasores e harmônicas. Menos rajadas deixam a "
                                    "serial livre; os resumos (energia, RMS, frequência) seguem a cada janela.")
        self.burst_combo.activated.connect(
            lambda _: self.send_board_command(CMD_BURST, bytes((self.burst_combo.currentData(),))))
        self.b_adc_selfcal = QPushButton("Autocalibrar ADC")
        self.b_adc_selfcal.setToolTip("Autocalibração de hardware dos três ADCs (alguns ms, perde uma janela). "
                                      "Muda levemente o ganho: refaça a etapa 1 da calibração depois.")
        self.b_adc_selfcal.clicked.connect(lambda: self.send_board_command(CMD_ADC_CAL))
        self.board_label = QLabel("Comandos: conecte a serial (precisa do fio CH340 TXD → J6 PTC0/RX3).")
        self.board_label.setObjectName("muted")
        for widget in (self.b_board_info, self.burst_combo, self.b_adc_selfcal):
            commands.addWidget(widget)
        commands.addWidget(self.board_label, stretch=1)
        hw_layout.addLayout(commands)
        self._command_id = 0
        self._pending_commands: dict[int, int] = {}
        self._board_info_asked = False
        self.board_info = None

        for label in (self.hardware_summary, self.continuous_label, self.board_label):
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            label.setMinimumWidth(1)

        # Última rajada: forma de onda bruta e estatística por canal.
        burst_card = QFrame()
        burst_card.setObjectName("card")
        burst_layout = QVBoxLayout(burst_card)
        burst_layout.setContentsMargins(14, 12, 14, 12)
        burst_layout.addWidget(self._section("ÚLTIMA RAJADA · CONTAGENS BRUTAS DO ADC"))
        self.raw_plot = pg.PlotWidget()
        self.raw_plot.setBackground(theme.PLOT_BG)
        self.raw_plot.showGrid(x=True, y=True, alpha=0.12)
        self.raw_plot.setMenuEnabled(False)
        self.raw_plot.setLabel("left", "Contagens")
        self.raw_plot.setLabel("bottom", "Tempo", units="s")
        self.raw_plot.setYRange(0, 65535, padding=0.02)
        self.raw_plot.addItem(pg.InfiniteLine(pos=65535, angle=0, pen=pg.mkPen(theme.DANGER, width=1, style=Qt.PenStyle.DashLine)))
        self.raw_plot.setMinimumHeight(90)
        self.raw_curves = [self.raw_plot.plot(pen=pg.mkPen(color, width=1.6))
                           for color in theme.PHASE.values()]
        self.raw_curves += [self.raw_plot.plot(pen=pg.mkPen(color, width=1.2, style=Qt.PenStyle.DashLine))
                            for color in theme.PHASE.values()]  # correntes, tracejadas
        burst_layout.addWidget(self.raw_plot, stretch=1)
        self.burst_table = QTableWidget(0, 7)
        self.burst_table.setHorizontalHeaderLabels(
            ["Canal", "Mín", "Máx", "Média", "Pico no pino", "Uso da escala", "Saturadas"])
        self.burst_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.burst_table.verticalHeader().setVisible(False)
        self.burst_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.burst_table.setShowGrid(False)
        # Mínimo antes do padrão: o padding do tema faria o mínimo do cabeçalho ~30 px
        # e o padrão seria limitado por ele (6 canais não caberiam em 1360×768).
        self.burst_table.verticalHeader().setMinimumSectionSize(18)
        self.burst_table.verticalHeader().setDefaultSectionSize(20)
        self.burst_table.horizontalHeader().setFixedHeight(30)
        self.burst_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.burst_table.setFixedHeight(30 + 3 * 20 + 4)
        burst_layout.addWidget(self.burst_table)
        hw_layout.addWidget(burst_card, stretch=3)

        lower = QHBoxLayout()
        lower.setSpacing(12)
        status_card = QFrame()
        status_card.setObjectName("card")
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(14, 12, 14, 12)
        status_layout.addWidget(self._section("ESTADOS INFORMADOS PELO FIRMWARE"))
        self.adc_table = QTableWidget(0, 3)
        self.adc_table.setHorizontalHeaderLabels(["Canal ADC", "Valor", "Nível"])
        self.adc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.adc_table.verticalHeader().setVisible(False)
        self.adc_table.horizontalHeader().setStretchLastSection(True)
        self.adc_table.setShowGrid(False)
        self.adc_table.setColumnWidth(0, 150)
        self.adc_table.setColumnWidth(1, 90)
        self.adc_table.setMinimumHeight(40)
        status_layout.addWidget(self.adc_table)
        lower.addWidget(status_card, stretch=1)
        json_card = QFrame()
        json_card.setObjectName("card")
        json_layout = QVBoxLayout(json_card)
        json_layout.setContentsMargins(14, 12, 14, 12)
        json_layout.addWidget(self._section("ÚLTIMA MENSAGEM DE ESTADO (JSON)"))
        self.hardware_view = QPlainTextEdit()
        self.hardware_view.setReadOnly(True)
        self.hardware_view.setObjectName("log")
        self.hardware_view.setMinimumHeight(40)
        self.hardware_view.setPlainText("Demonstração: nenhum estado físico recebido.")
        json_layout.addWidget(self.hardware_view)
        lower.addWidget(json_card, stretch=1)
        hw_layout.addLayout(lower, stretch=2)
        hardware = self._scrollable(hardware)
        self.tabs.addTab(hardware, "Hardware / ADC")

        development = QWidget()
        layout = QVBoxLayout(development)
        layout.setContentsMargins(20, 16, 20, 12)
        layout.setSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(8)
        open_project = QPushButton("Abrir projeto…")
        open_project.setIcon(theme.icon("open"))
        open_project.clicked.connect(self.load_project)
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.runner.cancel)
        self.btn_compile.setObjectName("primary")
        for widget in (open_project, self.btn_compile, self.btn_flash, cancel):
            row.addWidget(widget)
        row.addStretch(1)
        debug = QToolButton()
        debug.setText("Depuração GDB")
        debug.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        debug.setToolTip("Requer GDB e servidor remoto compatíveis com o alvo (não disponíveis para ColdFire V1 na bancada).")
        menu = QMenu(debug)
        for label, handler in (
            ("Iniciar depuração", self.start_debug), ("Breakpoint…", self.add_breakpoint),
            ("Registradores", lambda: self.debug_command("registers")),
            ("Continuar", lambda: self.debug_command("-exec-continue")),
            ("Pausar", lambda: self.debug_command("-exec-interrupt --all")),
            ("Encerrar depuração", self.debugger.close),
        ):
            menu.addAction(label, handler)
        debug.setMenu(menu)
        row.addWidget(debug)
        layout.addLayout(row)
        project_card = QFrame()
        project_card.setObjectName("card")
        project_layout = QVBoxLayout(project_card)
        project_layout.setContentsMargins(16, 12, 16, 12)
        project_layout.addWidget(self._section("PROJETO"))
        self.project_label = QLabel("Nenhum projeto aberto. Use “Abrir projeto…” e escolha um JSON em examples/projects.")
        self.project_label.setWordWrap(True)
        self.project_label.setTextFormat(Qt.TextFormat.RichText)
        project_layout.addWidget(self.project_label)
        layout.addWidget(project_card)
        layout.addWidget(self._section("SAÍDA DA TOOLCHAIN"))
        self.build_view = QPlainTextEdit()
        self.build_view.setReadOnly(True)
        self.build_view.setMaximumBlockCount(5000)
        self.build_view.setObjectName("log")
        layout.addWidget(self.build_view)
        self.map_view = QPlainTextEdit()
        self.map_view.setReadOnly(True)
        self.map_view.setObjectName("log")
        layout.addWidget(self._section("MAPA DE MEMÓRIA"))
        layout.addWidget(self.map_view)
        self.tabs.addTab(development, "Build / depuração")
        self._add_nav("Análise", analysis, "analysis")
        self._add_nav("Hardware / ADC", hardware, "chip")
        self._add_nav("Build e gravação", development, "build")
        self.btn_compile.setToolTip("Abra um projeto antes de compilar.")
        self.btn_flash.setToolTip("Requer build válido, gravador configurado e confirmação.")
        self.btn_compile.clicked.connect(self.build_project)
        self.btn_flash.clicked.connect(self.flash_project)

    @staticmethod
    def _scrollable(widget: QWidget) -> QScrollArea:
        """Página que rola na vertical quando a tela é baixa demais, em vez de cortar o conteúdo."""
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return scroll

    @staticmethod
    def _muted(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("muted")
        return label

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("panelTitle")
        return label

    def load_device(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Perfil de dispositivo", "", "JSON (*.json)")
        if not filename:
            return
        if self.reader and self.reader.isRunning():
            QMessageBox.information(self, "Perfil", "Desconecte a serial antes de trocar o perfil.")
            return
        try:
            self.apply_profile(Path(filename))
        except (OSError, ValueError, TypeError, ImportError) as exc:
            QMessageBox.critical(self, "Perfil inválido", str(exc))

    def apply_profile(self, path: Path) -> None:
        """Carrega um perfil de dispositivo e o memoriza para a próxima sessão."""
        profile = DeviceProfile.load(path)
        parser = load_protocol(profile.protocol)
        self.device_profile = profile
        self.sample_parser = parser
        self.board_label.setText(profile.name)
        self.profile_label.setText(f"{profile.name} · {profile.baudrate} baud")
        self.settings.setValue("last_profile", str(path.resolve()))
        self._log(f"Perfil carregado: {profile.name} · {profile.baudrate} baud · protocolo {profile.protocol}")

    def _default_gain(self, channel: str) -> float:
        """Ganho implícito de um canal sem coeficiente: escala nominal só em rajada sem calibração."""
        from prisma.ui.main_window import nominal_gain
        return nominal_gain(channel) if self.raw_counts and not self.calibration.channels else 1.0

    def _calibration_base(self) -> dict[str, dict]:
        """Coeficientes que levam a entrada de cada canal ao valor exibido hoje."""
        return {ch: dict(self.calibration.channels.get(ch, {"gain": self._default_gain(ch), "offset": 0.0}))
                for ch in CAL_CHANNELS}

    def calibrate_adc(self, points: dict[str, list[tuple[float, float]]] | None = None,
                      filename: str | None = None) -> None:
        """Etapa 1: reta contagem → volts no pino, com tensões DC medidas no multímetro.

        ``points``/``filename`` permitem executar sem diálogos (testes).
        """
        if points is None:
            if not self.raw_counts:
                QMessageBox.information(self, "Calibrar ADC",
                                        "Conecte a DEMOEM: a calibração do ADC usa as rajadas brutas da placa.")
                return
            from prisma.ui.adc_calibration import AdcCalibrationDialog
            dialog = AdcCalibrationDialog(self, lambda: (self.block_count, self.last_block_stats), self.block_names)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            points = dialog.points
        from prisma.ui.main_window import ADC_FULL_SCALE, ADC_VREF_V
        fits = {}
        for channel, pairs in points.items():
            if not pairs:
                continue
            try:
                fits[channel] = fit_adc(pairs)
            except ValueError as exc:
                QMessageBox.warning(self, "Calibrar ADC", f"{channel.upper()}: {exc}")
                return
        if not fits:
            QMessageBox.warning(self, "Calibrar ADC", "Nenhum canal com pontos registrados.")
            return
        # Canais sem pontos ficam na escala nominal, para todos saírem em volts no pino.
        channels = {ch: {"gain": ADC_VREF_V / ADC_FULL_SCALE, "offset": 0.0} for ch in ("va", "vb", "vc")}
        for channel, fit in fits.items():
            channels[channel] = {"gain": fit.gain, "offset": fit.offset}
        for channel, cfg in self.calibration.channels.items():
            if "delay_us" in cfg and channel in channels:
                channels[channel]["delay_us"] = cfg["delay_us"]
        calibration = Calibration(channels, f"ADC {datetime.now():%Y-%m-%d %H:%M}", pin_volts=True)
        self._save_calibration(calibration, filename, "calibracao-adc-demoem.json")
        self._set_calibration(calibration)
        self._log("ADC calibrado: " + "; ".join(
            f"{ch} = {fit.gain * 1e6:.3f} µV/contagem, offset {fit.offset * 1000:+.1f} mV, "
            f"maior desvio {fit.max_error_v * 1000:.1f} mV ({fit.points} pontos)" for ch, fit in fits.items()))

    def _pin_map(self) -> dict[str, tuple[float, float]]:
        """Volts no pino = g × contagem + o, por canal (correntes: tensão diferencial DADP − DADM).

        Tensões usam a etapa 1 (ADC calibrado) se houver; senão, a escala nominal.
        Correntes: binário deslocado, então o zero diferencial fica em 32768 contagens.
        """
        from prisma.ui.main_window import ADC_VREF_V, nominal_gain
        adc = self.calibration.channels if self.calibration.pin_volts else {}
        pin = {}
        for channel in ("va", "vb", "vc"):
            cfg = adc.get(channel)
            pin[channel] = (cfg["gain"], cfg["offset"]) if cfg else (nominal_gain(channel), 0.0)
        for channel in ("ia", "ib", "ic"):
            pin[channel] = (nominal_gain(channel), -ADC_VREF_V)
        return pin

    def configure_sensors(self, choices: dict | None = None, filename: str | None = None) -> None:
        """Perfis de sensor: V e A aproximados pela relação nominal de cada módulo.

        Canais sem sensor ficam em volts no pino. Os atrasos de fase calibrados
        são mantidos. ``choices``/``filename`` permitem executar sem diálogos (testes).
        """
        from prisma.core.measurement import WIRINGS
        from prisma.core.sensors import SensorChoice, sensor_channels
        saved = {}
        try:
            saved = {ch: SensorChoice.from_dict(c)
                     for ch, c in json.loads(str(self.settings.value("sensors", "{}"))).items()}
        except (ValueError, TypeError, KeyError):
            saved = {}
        if choices is None:
            from prisma.ui.sensor_dialog import SensorDialog
            phases = WIRINGS[getattr(self, "wiring", "tri")]
            channels = tuple(f"v{p.lower()}" for p in phases) + tuple(f"i{p.lower()}" for p in phases)
            dialog = SensorDialog(self, channels, saved)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            choices = dialog.choices()
        if not choices:
            QMessageBox.information(self, "Perfis de sensor", "Nenhum canal com sensor escolhido.")
            return
        pin = self._pin_map()
        try:
            channels = sensor_channels(choices, pin)
        except ValueError as exc:
            QMessageBox.warning(self, "Perfis de sensor", str(exc))
            return
        # Canais sem sensor ficam em volts no pino (sem polarização descontada).
        for channel, (g, o) in pin.items():
            channels.setdefault(channel, {"gain": g, "offset": o})
        for channel, cfg in self.calibration.channels.items():
            if "delay_us" in cfg:
                channels[channel]["delay_us"] = cfg["delay_us"]
        calibration = Calibration(channels, f"Sensores nominais {datetime.now():%Y-%m-%d %H:%M}")
        self._save_calibration(calibration, filename, "calibracao-sensores.json")
        self._set_calibration(calibration)
        self.settings.setValue("sensors", json.dumps({**{ch: c.to_dict() for ch, c in saved.items()},
                                                      **{ch: c.to_dict() for ch, c in choices.items()}}))
        self._log("Perfis de sensor: " + "; ".join(
            f"{ch} = {c.ratio(ch):.4g} {'A' if ch.startswith('i') else 'V'}/V, polarização {c.bias_v:.3f} V"
            for ch, c in choices.items()) + ". Valores aproximados: refine com o multímetro (etapa 2).")

    def _save_calibration(self, calibration: Calibration, filename: str | None, suggestion: str) -> None:
        if filename is None:
            filename, _ = QFileDialog.getSaveFileName(self, "Salvar calibração", suggestion, "JSON (*.json)")
        if filename:
            try:
                calibration.save(Path(filename))
                self._log(f"Calibração salva: {filename}")
            except OSError as exc:
                QMessageBox.critical(self, "Calibração", str(exc))

    def calibrate_from_reference(self, measured: dict[str, float] | None = None,
                                 filename: str | None = None) -> None:
        if self.last_analysis is None:
            QMessageBox.information(self, "Calibração", "Aguarde uma análise válida (sinal estável na tela).")
            return
        result = self.last_analysis[0]
        shown = {"va": result.rms["A"], "vb": result.rms["B"], "vc": result.rms["C"]}
        shown.update({ch: result.current_rms[phase] for ch, phase in zip(("ia", "ib", "ic"), "ABC")
                      if phase in result.current_rms})
        if measured is None:
            dialog = QDialog(self)
            dialog.setWindowTitle("Calibrar com multímetro")
            layout = QVBoxLayout(dialog)
            intro = QLabel("Com os sensores ligados, meça a tensão RMS de cada fase (e a corrente, com alicate "
                           "amperímetro) num instrumento de referência e informe abaixo. Deixe 0 para não alterar "
                           "um canal. Mantenha a carga estável durante a medição.")
            intro.setWordWrap(True)
            layout.addWidget(intro)
            form = QFormLayout()
            spins = {}
            rows = [(ch, f"V{ph.lower()}", "V") for ch, ph in zip(("va", "vb", "vc"), "ABC")]
            rows += [(ch, f"I{ph.lower()}", "A") for ch, ph in zip(("ia", "ib", "ic"), "ABC") if ch in shown]
            for channel, name, unit in rows:
                spin = QDoubleSpinBox()
                spin.setRange(0, 100000)
                spin.setDecimals(3)
                spin.setSuffix(f" {unit}")
                spin.setFixedWidth(160)
                spins[channel] = spin
                form.addRow(self._muted(f"{name} · exibido {shown[channel]:.3f} {unit} · medido"), spin)
            layout.addLayout(form)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Calibrar")
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            measured = {channel: spin.value() for channel, spin in spins.items()}
        base = self._calibration_base()
        try:
            gains = gains_from_reference({ch: cfg["gain"] for ch, cfg in base.items()}, shown, measured)
        except ValueError as exc:
            QMessageBox.warning(self, "Calibração", str(exc))
            return
        channels = {ch: dict(cfg) for ch, cfg in self.calibration.channels.items()}
        for channel in ("va", "vb", "vc", *(ch for ch in ("ia", "ib", "ic") if ch in shown)):
            channels.setdefault(channel, base[channel])
        for channel, gain in gains.items():
            # valor = entrada × ganho + offset: multiplicar o valor por k multiplica os dois
            ratio = gain / channels[channel]["gain"]
            channels[channel]["gain"] = gain
            channels[channel]["offset"] = channels[channel]["offset"] * ratio
        calibration = Calibration(channels, f"Bancada {datetime.now():%Y-%m-%d %H:%M}")
        self._save_calibration(calibration, filename, "calibracao-demoem.json")
        self._set_calibration(calibration)
        self._log("Ganhos calibrados: " + ", ".join(f"{ch} = {g:.6g}" for ch, g in gains.items()))

    def calibrate_phase(self, confirm: bool | None = None, filename: str | None = None) -> None:
        """Assistente: com carga resistiva (FP = 1), mede o atraso de cada corrente.

        O atraso residual medido soma ao ``delay_us`` já ativo, porque a análise
        corrente já está compensada por ele. ``confirm``/``filename`` permitem
        executar sem diálogos (testes).
        """
        if self.last_analysis is None:
            QMessageBox.information(self, "Calibração de fase", "Aguarde uma análise válida (sinal estável na tela).")
            return
        result = self.last_analysis[0]
        if not result.current_phasors:
            QMessageBox.information(self, "Calibração de fase",
                                    "A calibração de fase requer correntes ia, ib e ic sincronizadas com as tensões.")
            return
        try:
            residual = delays_from_resistive_load(result.phasors, result.current_phasors, result.frequency_hz)
        except ValueError as exc:
            QMessageBox.warning(self, "Calibração de fase", str(exc))
            return
        current = {ch: self.calibration.channels.get(ch, {}).get("delay_us", 0.0) for ch in residual}
        delays = {ch: current[ch] + residual[ch] for ch in residual}
        if confirm is None:
            dialog = QDialog(self)
            dialog.setWindowTitle("Calibrar fase com carga resistiva")
            layout = QVBoxLayout(dialog)
            intro = QLabel("Ligue uma carga puramente resistiva (lâmpada incandescente, resistor de potência ou "
                           "chuveiro), sem motor nem fonte chaveada. Com FP = 1, tensão e corrente deveriam estar "
                           "em fase: a diferença medida vira o atraso de cada canal de corrente.")
            intro.setWordWrap(True)
            layout.addWidget(intro)
            table = QTableWidget(len(delays), 4)
            table.setHorizontalHeaderLabels(["Canal", "Defasagem medida", "Atraso atual", "Novo atraso"])
            table.verticalHeader().setVisible(False)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            for row, channel in enumerate(delays):
                degrees = residual[channel] * 1e-6 * 360 * result.frequency_hz
                for column, text in enumerate((channel.upper(), f"{degrees:+.2f}°",
                                               f"{current[channel]:+.1f} µs", f"{delays[channel]:+.1f} µs")):
                    table.setItem(row, column, QTableWidgetItem(text))
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setFixedHeight(table.horizontalHeader().height()
                                 + sum(table.rowHeight(r) for r in range(table.rowCount())) + 4)
            layout.addWidget(table)
            note = QLabel(f"Frequência da análise: {result.frequency_hz:.2f} Hz. Repita até a defasagem ficar perto de 0°.")
            note.setStyleSheet(f"color: {theme.MUTED}")
            layout.addWidget(note)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Aplicar")
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            confirm = dialog.exec() == QDialog.DialogCode.Accepted
        if not confirm:
            return
        base = self._calibration_base()
        channels = {ch: dict(cfg) for ch, cfg in self.calibration.channels.items()}
        for channel, delay in delays.items():
            channels.setdefault(channel, base[channel])["delay_us"] = round(delay, 2)
        calibration = Calibration(channels, f"Fase {datetime.now():%Y-%m-%d %H:%M}", self.calibration.pin_volts)
        self._save_calibration(calibration, filename, "calibracao-fase.json")
        self._set_calibration(calibration)
        self._log("Atrasos calibrados: " + ", ".join(f"{ch} = {d:+.1f} µs" for ch, d in delays.items()))

    def load_calibration(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Calibração", "", "JSON (*.json)")
        if not filename:
            return
        try:
            calibration = Calibration.load(Path(filename))
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.critical(self, "Calibração inválida", str(exc))
            return
        self._set_calibration(calibration)

    def reset_calibration(self) -> None:
        self._set_calibration(Calibration())

    def _set_calibration(self, calibration: Calibration) -> None:
        self.stop_recording()
        self.buffer.clear()
        self._invalidate_analysis()
        self.calibration = calibration
        stage = " · volts no pino" if calibration.pin_volts else ""
        self.calibration_label.setText(calibration.name + stage)
        self._apply_units()
        # A calibração ativa volta na próxima abertura do app.
        if calibration.channels:
            self.settings.setValue("calibration", json.dumps(calibration.to_dict(), ensure_ascii=False))
        else:
            self.settings.remove("calibration")
        self._log(f"Calibração ativa: {calibration.name}{stage}; buffer reiniciado.")

    def _invalidate_analysis(self) -> None:
        self.last_analysis = None
        self.details.setText("Aguardando nova janela de amostras...")
        self.frequency_label.setText("--- Hz")
        self.selected_phasor.setText("Aguardando análise válida.")
        self.power_view.clearContents()
        self.meter.clear()
        self.phasor.clear()
        self.harmonics.clear()
        for curve in self.curves.values():
            curve.setData([], [])

    def save_inventory(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(self, "Diagnóstico serial/USB", "diagnostico.json", "JSON (*.json)")
        if filename:
            try:
                Path(filename).write_text(json.dumps({"ports": serial_inventory(),
                    "note": "VID/PID e COM observados neste computador; BDM e pinagem não validados."},
                    indent=2, ensure_ascii=False), encoding="utf-8")
                self._log(f"Diagnóstico salvo: {filename}")
            except OSError as exc:
                QMessageBox.critical(self, "Diagnóstico", str(exc))

    COMMAND_TIMEOUT_MS = 2000  # cabe uma rajada de 6 canais (~0,5 s) na frente da resposta

    def send_board_command(self, code: int, args: bytes = b"", *, quiet: bool = False) -> bool:
        """Envia um comando à placa; a resposta chega por ``_on_command_reply``."""
        if self.reader is None or not self.reader.isRunning():
            if not quiet:
                self.board_label.setText("Comandos: conecte a serial primeiro.")
            return False
        self._command_id = (self._command_id + 1) & 0xFF
        command_id = self._command_id
        self._pending_commands[command_id] = code
        self.reader.send(encode_command(command_id, code, args))
        if not quiet:
            self.board_label.setText(f"Comando {COMMAND_NAMES[code]} enviado; aguardando a placa…")
        QTimer.singleShot(self.COMMAND_TIMEOUT_MS, lambda: self._command_timeout(command_id, quiet))
        return True

    def _command_timeout(self, command_id: int, quiet: bool) -> None:
        code = self._pending_commands.pop(command_id, None)
        if code is None:
            return
        if quiet:  # identificação automática: só informa, sem log
            self.board_label.setText("Comandos: a placa não respondeu à identificação (fio CH340 TXD → "
                                     "J6 PTC0/RX3 ausente ou firmware anterior à rev 3).")
            return
        self.board_label.setText(
            f"Sem resposta a {COMMAND_NAMES[code]}: confira o fio CH340 TXD → J6 PTC0/RX3 (J10 no PTC0) "
            "e se a placa tem o firmware rev 3 ou mais novo.")
        self._log(f"Placa não respondeu ao comando {COMMAND_NAMES[code]}.")

    def _on_command_reply(self, reply) -> None:
        code = self._pending_commands.pop(reply.command_id, None)
        if code is None or code != reply.code:
            return  # resposta atrasada ou de outro pedido
        name = COMMAND_NAMES[code]
        if not reply.ok:
            self.board_label.setText(f"Placa recusou {name}: {reply.status_text}.")
            return
        if code == CMD_INFO:
            info = self.board_info = parse_board_info(reply)
            every = "sem rajadas" if info.burst_every == 0 else (
                "rajada a cada janela" if info.burst_every == 1 else f"rajada a cada {info.burst_every} janelas")
            index = self.burst_combo.findData(info.burst_every)
            if index >= 0:
                self.burst_combo.setCurrentIndex(index)
            errors = info.rx_errors + info.command_errors
            self.board_label.setText(
                f"Placa: firmware rev {info.firmware_rev} · {info.channels} canais · {info.fs_hz:.1f} Hz · "
                f"{every} · autocalibração do ADC {info.adc_cal_text}"
                + (f" · {errors} erro(s) de recepção" if errors else ""))
        elif code == CMD_BURST:
            every = reply.data[0] if reply.data else 0
            index = self.burst_combo.findData(every)
            if index >= 0:
                self.burst_combo.setCurrentIndex(index)
            self.board_label.setText("Placa: " + ("rajadas desligadas (só resumos)." if every == 0 else
                                                  f"uma rajada a cada {every} janela(s)."))
        elif code == CMD_ADC_CAL:
            mask = reply.data[0] if reply.data else 0xFF
            text = adc_cal_text(mask)
            self.board_label.setText(f"Autocalibração do ADC: {text}."
                                     + (" Refaça a etapa 1 da calibração (ADC com tensão DC)." if mask == 0 else ""))
            self._log(f"Autocalibração do ADC na placa: {text}.")

    def _show_block(self, block, vref: float, full_scale: int) -> None:
        """Mostra a rajada bruta (antes de calibração) na página Hardware / ADC."""
        from prisma.ui.main_window import nominal_gain
        t = [s.t - block.samples[0].t for s in block.samples]
        six = block.samples[0].ia is not None
        columns = list(zip(*((s.va, s.vb, s.vc, *((s.ia, s.ib, s.ic) if six else ())) for s in block.samples)))
        self.block_count += 1
        self.block_names = tuple(block.channels)
        self.last_block_stats = {
            ch: (float(np.mean(values)), float(np.std(values)), bool(min(values) <= 0 or max(values) >= full_scale))
            for ch, values in zip(("va", "vb", "vc"), columns)}
        for index, curve in enumerate(self.raw_curves):
            curve.setData(t, columns[index]) if index < len(columns) else curve.setData([], [])
        if self.burst_table.rowCount() != len(block.channels):
            self.burst_table.setRowCount(len(block.channels))
            self.burst_table.setFixedHeight(30 + len(block.channels) * 20 + 4)
        for row, (name, values) in enumerate(zip(block.channels, columns)):
            # Correntes: diferencial em binário deslocado, zero em 32768 e ±Vref nas pontas.
            zero = 32768 if row >= 3 else 0
            peak = max(values)
            swing = max(abs(peak - zero), abs(min(values) - zero))
            span = 32768 if row >= 3 else full_scale
            saturated = sum(v >= full_scale or (row >= 3 and v <= 0) for v in values)
            usage = QProgressBar()
            usage.setRange(0, 1000)
            usage.setValue(int(1000 * min(swing / span, 1.0)))
            usage.setFormat(f"{100 * swing / span:.0f} %")
            usage.setMaximumHeight(16)
            usage.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cells = (name.upper(), f"{min(values):.0f}", f"{peak:.0f}", f"{sum(values) / len(values):.0f}",
                     f"{(peak - zero) * (nominal_gain('ia') if row >= 3 else vref / full_scale):.3f} V",
                     None, f"{saturated}")
            for column, text in enumerate(cells):
                if text is None:
                    self.burst_table.setCellWidget(row, column, usage)
                    continue
                item = QTableWidgetItem(text)
                if column == 0:
                    item.setForeground(QColor(list(theme.PHASE.values())[row % 3]))
                if column == 6 and saturated:
                    item.setForeground(QColor(theme.DANGER))
                self.burst_table.setItem(row, column, item)
        warn = f" · ⚠ timeout ADC {block.timeout_mask}" if block.timeout_mask else ""
        self.hardware_summary.setText(
            f"Rajada {block.seq}: {len(block.samples)} amostras por canal a {block.fs_hz:.1f} Hz "
            f"({len(block.samples) / block.fs_hz * 1000:.0f} ms){warn}. Pico no pino = contagem × {vref} V / {full_scale}"
            + (f"; correntes (diferenciais) = (contagem − 32768) × {vref} V / 32768." if six else "."))

    def _on_hardware_status(self, status) -> None:
        self._mark_data()
        message = getattr(status, "message", "")
        diagnostics = getattr(status, "diagnostics", {})
        self.hardware_view.setPlainText("TELEMETRIA SERIAL · estados informados pelo firmware\n\n" +
            json.dumps({"message": message, "leds": status.leds, "gpio": status.gpio, "adc": status.adc,
                        "lcd": status.lcd, "diagnostics": diagnostics}, indent=2, ensure_ascii=False))
        problems = [f"{name} = {int(value)}" for name, value in diagnostics.items() if value]
        summary = f"Mensagem: {message or '—'}"
        if diagnostics:
            summary += " · " + ("⚠ " + ", ".join(problems) if problems else "diagnósticos OK")
        self.hardware_summary.setText(summary)
        if not status.adc:
            return
        self.adc_table.setRowCount(len(status.adc))
        for row, (name, value) in enumerate(sorted(status.adc.items())):
            # Palavras brutas de 16 bits; valores com sinal ocupam ±32768.
            span = 32768.0 if name.endswith("_signed") else 65535.0
            level = min(1.0, abs(value) / span)
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(int(level * 1000))
            bar.setTextVisible(False)
            bar.setMaximumHeight(14)
            bar.setStyleSheet("QProgressBar { background: #17263a; border: none; border-radius: 5px; }"
                              "QProgressBar::chunk { background: #24bace; border-radius: 5px; }")
            self.adc_table.setItem(row, 0, QTableWidgetItem(name))
            self.adc_table.setItem(row, 1, QTableWidgetItem(f"{value:.0f}"))
            self.adc_table.setCellWidget(row, 2, bar)

    @staticmethod
    def _png(widget) -> bytes:
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        widget.grab().save(buffer, "PNG")
        return bytes(buffer.data())

    def export_report(self, filename: str | None = None) -> None:
        if self.last_analysis is None:
            QMessageBox.information(self, "Relatório", "Aguarde uma análise válida.")
            return
        if filename is None:
            default = f"relatorio-prisma-{datetime.now():%Y%m%d-%H%M%S}.html"
            filename, _ = QFileDialog.getSaveFileName(self, "Relatório HTML", default, "HTML (*.html)")
        if filename:
            images = {"Osciloscópio": self._png(self.wave), "Fasores (referência: fase A)": self._png(self.phasor),
                      "Harmônicas da fase A": self._png(self.harmonics)}
            try:
                write_report(Path(filename), *self.last_analysis, images=images)
                self._log(f"Relatório salvo: {filename}")
            except OSError as exc:
                QMessageBox.critical(self, "Relatório", str(exc))

    def open_history(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Histórico SQLite", "", "SQLite (*.sqlite *.db)")
        if not filename:
            return
        try:
            sessions = list_sessions(Path(filename))
        except (OSError, sqlite3.Error) as exc:
            QMessageBox.critical(self, "Histórico inválido", str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Histórico de aquisições · horários UTC")
        dialog.resize(950, 500)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(len(sessions), 5)
        table.setHorizontalHeaderLabels(["Sessão", "Início UTC", "Origem", "Amostras", "Fim UTC"])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        for row, session in enumerate(sessions):
            for col, value in enumerate(session):
                table.setItem(row, col, QTableWidgetItem(str(value or "")))
        table.resizeColumnsToContents()
        layout.addWidget(table)
        filters = QHBoxLayout()
        enabled = QCheckBox("Filtrar tempo (s)")
        start, end = QDoubleSpinBox(), QDoubleSpinBox()
        for widget, value in ((start, 0), (end, 1)):
            widget.setRange(-1e12, 1e12)
            widget.setDecimals(6)
            widget.setValue(value)
        filters.addWidget(enabled)
        filters.addWidget(start)
        filters.addWidget(end)
        layout.addLayout(filters)
        button = QPushButton("Exportar sessão selecionada para CSV…")
        layout.addWidget(button)

        def export():
            row = table.currentRow()
            if row < 0:
                return
            if enabled.isChecked() and start.value() > end.value():
                QMessageBox.warning(dialog, "Filtro", "O início deve ser menor ou igual ao fim.")
                return
            output, _ = QFileDialog.getSaveFileName(dialog, "Exportar sessão", "sessao.csv", "CSV (*.csv)")
            if output:
                try:
                    count = export_session(Path(filename), sessions[row][0], Path(output),
                        start.value() if enabled.isChecked() else None, end.value() if enabled.isChecked() else None)
                    self._log(f"Histórico exportado: {count} amostras | {output}")
                except (OSError, sqlite3.Error, ValueError) as exc:
                    QMessageBox.critical(dialog, "Erro de exportação", str(exc))
        button.clicked.connect(export)
        dialog.exec()

    def load_project(self) -> None:
        if self.runner.running:
            return
        filename, _ = QFileDialog.getOpenFileName(self, "Projeto PRISMA", "", "JSON (*.json)")
        if not filename:
            return
        try:
            project = Project.load(Path(filename))
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.critical(self, "Projeto inválido", str(exc))
            return
        self.project, self.build_digest = project, None
        def cmd(parts):
            return " ".join(parts) if parts else "<i>não configurado</i>"
        rows = (("Nome", project.name), ("Alvo", project.target), ("Pasta", str(project.directory)),
                ("Build", cmd(project.build)), ("Gravação", cmd(project.flash)), ("Depurador", cmd(project.debugger)))
        self.project_label.setText("<table cellpadding='2'>" + "".join(
            f"<tr><td style='color:#8a9ab0; padding-right:14px'>{k}</td><td>{v}</td></tr>" for k, v in rows) + "</table>")
        self.btn_compile.setEnabled(True)
        self.btn_flash.setEnabled(False)
        self.build_view.clear()
        self.map_view.clear()
        self.tabs.setCurrentWidget(self.build_view.parentWidget())

    def build_project(self) -> None:
        if self.project is None or self.runner.running:
            return
        if self.editor.document().isModified():
            QMessageBox.information(self, "Código modificado", "Salve o código antes de compilar o projeto em disco.")
            return
        self.build_digest = None
        self.btn_flash.setEnabled(False)
        self.map_view.clear()
        self._run_operation("build")

    def _run_operation(self, operation: str) -> None:
        try:
            if operation == "flash" and artifact_digest(self.project.artifact) != self.build_digest:
                raise ValueError("Artefato alterado após a confirmação. Compile novamente.")
            command = self.project.command(operation)
            self.operation = operation
            self.build_view.appendPlainText(f"\n{operation}: {command}\n")
            self.runner.start(command, self.project.directory)
            self.btn_compile.setEnabled(False)
            self.btn_flash.setEnabled(False)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Toolchain", str(exc))

    def _build_output(self, text: str) -> None:
        self.build_view.appendPlainText(text)

    def _debug_output(self, text: str) -> None:
        self.build_view.appendPlainText("GDB/MI: " + text)

    def _operation_done(self, success: bool) -> None:
        self.build_view.appendPlainText("Operação concluída." if success else "Operação falhou ou foi cancelada.")
        self.btn_compile.setEnabled(self.project is not None)
        if success and self.operation == "build":
            try:
                self.build_digest = artifact_digest(self.project.artifact)
                self.build_view.appendPlainText("SHA-256: " + self.build_digest)
                if self.project.map_file and self.project.map_file.is_file():
                    with self.project.map_file.open("r", encoding="utf-8", errors="replace") as handle:
                        self.map_view.setPlainText(handle.read(2_000_000))
            except (OSError, ValueError) as exc:
                self.build_digest = None
                self.build_view.appendPlainText(str(exc))
        self.btn_flash.setEnabled(bool(self.build_digest and self.project.flash))

    def flash_project(self) -> None:
        if self.project is None or not self.build_digest or self.runner.running:
            return
        if self.reader is not None and self.reader.isRunning():
            QMessageBox.information(self, "Gravação", "Desconecte a aquisição serial antes de gravar o firmware.")
            return
        try:
            if artifact_digest(self.project.artifact) != self.build_digest:
                raise ValueError("Artefato alterado após o build. Compile novamente.")
            command = self.project.command("flash")
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Gravação", str(exc))
            return
        answer = QMessageBox.question(self, "Confirmar gravação Flash",
            f"Alvo: {self.project.target}\nArquivo: {self.project.artifact}\n"
            f"SHA-256: {self.build_digest}\nComando: {command}\n\n"
            "A gravação pode substituir o firmware da placa. Confirma a placa e a ferramenta selecionadas?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self._run_operation("flash")

    def start_debug(self) -> None:
        if self.project is None or not self.build_digest:
            QMessageBox.information(self, "Depuração", "Abra um projeto e conclua o build antes de depurar.")
            return
        try:
            if artifact_digest(self.project.artifact) != self.build_digest:
                raise ValueError("Artefato alterado após o build")
            self.debugger.start(self.project)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Depuração", str(exc))

    def add_breakpoint(self) -> None:
        location, ok = QInputDialog.getText(self, "Breakpoint", "Arquivo:linha (ex.: main.c:42)")
        if ok:
            try:
                self.debugger.breakpoint(location)
            except ValueError as exc:
                QMessageBox.warning(self, "Breakpoint", str(exc))

    def debug_command(self, command: str) -> None:
        try:
            if command == "registers":
                self.debugger.registers()
            else:
                self.debugger.send(command)
        except ValueError as exc:
            QMessageBox.warning(self, "Depuração", str(exc))

    def record_trend(self, result) -> None:
        """Acrescenta um ponto ao histórico (no máximo um a cada 0,5 s)."""
        now = time.monotonic()
        if self._trend_t0 is None:
            self._trend_t0 = now
        t = now - self._trend_t0
        if self.trend and t - self.trend[-1][0] < 0.5:
            return
        unbalance = sequence_components(result.phasors).unbalance_percent if three_phase(result) else None
        self.trend.append((t, *(result.rms[p] if p in result.phases else float("nan") for p in "ABC"),
                           result.frequency_hz,
                           float("nan") if unbalance is None else unbalance))
        data = np.array(self.trend)
        for i, phase in enumerate("ABC", 1):
            self.trend_curves[phase].setData(data[:, 0], data[:, i], connect="finite")
        self.trend_freq_curve.setData(data[:, 0], data[:, 4])
        self.trend_unb_curve.setData(data[:, 0], data[:, 5], connect="finite")

    def clear_trend(self) -> None:
        self.trend.clear()
        self._trend_t0 = None
        for curve in (*self.trend_curves.values(), self.trend_freq_curve, self.trend_unb_curve):
            curve.setData([], [])
