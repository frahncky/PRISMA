"""Ferramentas de aquisição, análise, histórico e desenvolvimento."""
from datetime import datetime
import json
from pathlib import Path
import sqlite3

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from prisma.core.calibration import Calibration, gains_from_reference
import pyqtgraph as pg

from prisma.ui import theme
from prisma.core.devices import DeviceProfile, load_protocol, serial_inventory
from prisma.core.history import export_session, list_sessions
from prisma.core.reports import write_report
from prisma.core.toolchain import CommandRunner, DebugSession, Project, artifact_digest


class FeaturesMixin:
    def _build_features(self) -> None:
        self.calibration = Calibration()
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
            ("Calibrar com multímetro…", self.calibrate_from_reference),
            ("Carregar calibração…", self.load_calibration),
            ("Restaurar calibração identidade", self.reset_calibration),
        ):
            action = QAction(label, self)
            action.triggered.connect(handler)
            acquisition_menu.addAction(action)

        analysis = QWidget()
        page = QVBoxLayout(analysis)
        page.setContentsMargins(20, 16, 20, 16)
        page.setSpacing(14)
        self.frequency_combo = QComboBox()
        self.frequency_combo.addItems(["60 Hz", "50 Hz", "Automática (40–70 Hz)"])
        self.window_combo = QComboBox()
        self.window_combo.addItems(["Retangular", "Hann"])
        self.phasor_reference = QComboBox()
        self.phasor_reference.addItems(["Absoluta", "Fase A", "Fase B", "Fase C"])
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
            outer.setContentsMargins(18, 14, 18, 16)
            outer.setSpacing(10)
            outer.addWidget(self._section(title))
            form = QFormLayout()
            form.setVerticalSpacing(10)
            form.setHorizontalSpacing(24)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
            outer.addLayout(form)
            return frame, form

        cards = QHBoxLayout()
        cards.setSpacing(14)
        settings, form = card("PARÂMETROS DA ANÁLISE")
        form.addRow(self._muted("Frequência fundamental"), self.frequency_combo)
        form.addRow(self._muted("Janela do ajuste harmônico"), self.window_combo)
        form.addRow(self._muted("Referência dos fasores"), self.phasor_reference)
        cards.addWidget(settings, stretch=1)
        status, form = card("FONTE E CALIBRAÇÃO")
        form.addRow(self._muted("Dispositivo"), self.profile_label)
        form.addRow(self._muted("Calibração"), self.calibration_label)
        calibrate = QPushButton("Calibrar com multímetro…")
        calibrate.setToolTip("Informe a tensão RMS medida em cada fase; o PRISMA calcula o ganho dos canais.")
        calibrate.clicked.connect(self.calibrate_from_reference)
        form.addRow("", calibrate)
        form.addRow(self._muted("Fasor selecionado"), self.selected_phasor)
        cards.addWidget(status, stretch=1)
        page.addLayout(cards)

        power_card = QFrame()
        power_card.setObjectName("card")
        power_layout = QVBoxLayout(power_card)
        power_layout.setContentsMargins(18, 14, 18, 16)
        power_layout.addWidget(self._section("POTÊNCIAS POR FASE"))
        self.power_view = QTableWidget(3, 6)
        self.power_view.setHorizontalHeaderLabels(["Fase", "I RMS (A)", "P (W)", "Q1 (var)", "S (VA)", "FP"])
        self.power_view.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.power_view.verticalHeader().setVisible(False)
        self.power_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.power_view.setFixedHeight(150)
        self.power_view.setShowGrid(False)
        power_layout.addWidget(self.power_view)
        note = self._muted("Potências exigem ia, ib e ic sincronizadas com va, vb e vc. Q1 é a potência reativa "
                           "da fundamental; RMS, P e S usam os sinais AC. Uma calibração carregada não certifica "
                           "a cadeia de medição.")
        note.setWordWrap(True)
        power_layout.addWidget(note)
        page.addWidget(power_card)
        page.addStretch(1)
        self.tabs.addTab(analysis, "Análise")

        hardware = QWidget()
        hw_layout = QVBoxLayout(hardware)
        hw_layout.setContentsMargins(20, 16, 20, 12)
        hw_layout.setSpacing(12)
        self.hardware_summary = QLabel("Sem telemetria da placa. Conecte a serial para ver os canais do ADC.")
        self.hardware_summary.setObjectName("muted")
        self.hardware_summary.setWordWrap(True)
        hw_layout.addWidget(self.hardware_summary)

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
        self.raw_plot.setMinimumHeight(180)
        self.raw_curves = [self.raw_plot.plot(pen=pg.mkPen(color, width=1.6))
                           for color in theme.PHASE.values()]
        burst_layout.addWidget(self.raw_plot, stretch=1)
        self.burst_table = QTableWidget(0, 7)
        self.burst_table.setHorizontalHeaderLabels(
            ["Canal", "Mín", "Máx", "Média", "Pico no pino", "Uso da escala", "Saturadas"])
        self.burst_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.burst_table.verticalHeader().setVisible(False)
        self.burst_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.burst_table.setShowGrid(False)
        self.burst_table.setFixedHeight(128)
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
        self.hardware_view.setPlainText("Demonstração: nenhum estado físico recebido.")
        json_layout.addWidget(self.hardware_view)
        lower.addWidget(json_card, stretch=1)
        hw_layout.addLayout(lower, stretch=2)
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

    def _calibration_base_gains(self) -> dict[str, float]:
        """Ganho que leva a entrada do canal ao valor exibido hoje."""
        from prisma.ui.main_window import ADC_FULL_SCALE, ADC_VREF_V
        default = ADC_VREF_V / ADC_FULL_SCALE if self._pin_volts() else 1.0
        return {ch: self.calibration.channels.get(ch, {}).get("gain", default) for ch in ("va", "vb", "vc")}

    def calibrate_from_reference(self, measured: dict[str, float] | None = None,
                                 filename: str | None = None) -> None:
        if self.last_analysis is None:
            QMessageBox.information(self, "Calibração", "Aguarde uma análise válida (sinal estável na tela).")
            return
        result = self.last_analysis[0]
        shown = {"va": result.rms["A"], "vb": result.rms["B"], "vc": result.rms["C"]}
        if measured is None:
            dialog = QDialog(self)
            dialog.setWindowTitle("Calibrar com multímetro")
            layout = QVBoxLayout(dialog)
            intro = QLabel("Meça a tensão RMS de cada fase com um instrumento de referência e informe abaixo. "
                           "Deixe 0 para não alterar um canal. Mantenha o sinal estável durante a medição.")
            intro.setWordWrap(True)
            layout.addWidget(intro)
            form = QFormLayout()
            spins = {}
            for channel, phase in (("va", "A"), ("vb", "B"), ("vc", "C")):
                spin = QDoubleSpinBox()
                spin.setRange(0, 100000)
                spin.setDecimals(3)
                spin.setSuffix(" V")
                spin.setFixedWidth(160)
                spins[channel] = spin
                form.addRow(self._muted(f"Fase {phase} · exibido {shown[channel]:.3f} V · medido"), spin)
            layout.addLayout(form)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Calibrar")
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            measured = {channel: spin.value() for channel, spin in spins.items()}
        try:
            gains = gains_from_reference(self._calibration_base_gains(), shown, measured)
        except ValueError as exc:
            QMessageBox.warning(self, "Calibração", str(exc))
            return
        channels = {ch: dict(cfg) for ch, cfg in self.calibration.channels.items()}
        base = self._calibration_base_gains()
        for channel in ("va", "vb", "vc"):
            channels.setdefault(channel, {"gain": base[channel], "offset": 0.0})
        for channel, gain in gains.items():
            channels[channel]["gain"] = gain
        name = f"Bancada {datetime.now():%Y-%m-%d %H:%M}"
        calibration = Calibration(channels, name)
        if filename is None:
            filename, _ = QFileDialog.getSaveFileName(self, "Salvar calibração", "calibracao-demoem.json", "JSON (*.json)")
        if filename:
            try:
                calibration.save(Path(filename))
                self._log(f"Calibração salva: {filename}")
            except OSError as exc:
                QMessageBox.critical(self, "Calibração", str(exc))
        self._set_calibration(calibration)
        self._log("Ganhos calibrados: " + ", ".join(f"{ch} = {g:.6g}" for ch, g in gains.items()))

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
        self.calibration_label.setText(calibration.name)
        self._apply_units()
        self._log(f"Calibração ativa: {calibration.name}; buffer reiniciado.")

    def _invalidate_analysis(self) -> None:
        self.last_analysis = None
        self.details.setText("Aguardando nova janela de amostras...")
        self.frequency_label.setText("--- Hz")
        self.selected_phasor.setText("Aguardando análise válida.")
        self.power_view.clearContents()
        for label in self.metric_labels.values():
            label.setText("--- V")
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

    def _show_block(self, block, vref: float, full_scale: int) -> None:
        """Mostra a rajada bruta (antes de calibração) na página Hardware / ADC."""
        t = [s.t - block.samples[0].t for s in block.samples]
        columns = list(zip(*((s.va, s.vb, s.vc) for s in block.samples)))
        for curve, values in zip(self.raw_curves, columns):
            curve.setData(t, values)
        self.burst_table.setRowCount(len(block.channels))
        for row, (name, values) in enumerate(zip(block.channels, columns)):
            peak = max(values)
            saturated = sum(v >= full_scale for v in values)
            usage = QProgressBar()
            usage.setRange(0, 1000)
            usage.setValue(int(1000 * peak / full_scale))
            usage.setFormat(f"{100 * peak / full_scale:.0f} %")
            usage.setMaximumHeight(16)
            usage.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cells = (name.upper(), f"{min(values):.0f}", f"{peak:.0f}", f"{sum(values) / len(values):.0f}",
                     f"{peak * vref / full_scale:.3f} V", None, f"{saturated}")
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
            f"({len(block.samples) / block.fs_hz * 1000:.0f} ms){warn}. Pico no pino = contagem × {vref} V / {full_scale}.")

    def _on_hardware_status(self, status) -> None:
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

    def export_report(self) -> None:
        if self.last_analysis is None:
            QMessageBox.information(self, "Relatório", "Aguarde uma análise válida.")
            return
        filename, _ = QFileDialog.getSaveFileName(self, "Relatório HTML", "relatorio-prisma.html", "HTML (*.html)")
        if filename:
            try:
                write_report(Path(filename), *self.last_analysis)
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
