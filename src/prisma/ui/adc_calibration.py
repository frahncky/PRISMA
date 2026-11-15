"""Assistente de calibração do ADC (contagens → volts no pino) com tensões DC conhecidas."""
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from prisma.core.calibration import fit_adc
from prisma.ui import theme

CHANNELS = ("va", "vb", "vc")


def br(value: float, fmt: str) -> str:
    """Número com vírgula decimal, como no multímetro e nos campos de entrada."""
    return format(value, fmt).replace(".", ",")

INSTRUCTIONS = (
    "<b>Como fazer</b><ol style='margin-left:-20px'>"
    "<li>Abra o <b>J38</b> para desligar o gerador QE8 das entradas do ADC.</li>"
    "<li>Ligue um potenciômetro de 10 kΩ entre o <b>3,3 V e o GND da própria DEMOEM</b> e leve o cursor, "
    "por um resistor de 1 kΩ, aos pinos do J38 <b>do lado do microcontrolador</b> (confira no esquema qual "
    "fileira). Pode ligar as três entradas juntas.</li>"
    "<li>Para cada ponto: ajuste o potenciômetro, meça a tensão na entrada com o multímetro (preto no GND da "
    "placa), digite o valor e clique em <b>Registrar ponto</b>.</li>"
    "<li>Registre 3 pontos ou mais espalhados pela faixa, por exemplo 0,3 V, 1,6 V e 3,0 V.</li></ol>"
    "<span style='color:%s'>Nunca aplique menos de 0 V nem mais que 3,3 V nas entradas. Nada da rede elétrica "
    "aqui: esta etapa é só da placa.</span>" % theme.WARNING
)


class AdcCalibrationDialog(QDialog):
    """Mostra a contagem média ao vivo e coleta pares (contagem, tensão medida) por canal.

    ``read_stats`` devolve ``(blocos_recebidos, {canal: (média, desvio, saturado)})``.
    Ao aceitar, ``points`` tem a lista de pares de cada canal.
    """

    def __init__(self, parent, read_stats: Callable[[], tuple[int, dict]], names: tuple[str, ...]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Calibrar ADC com tensão DC")
        self.setMinimumWidth(720)
        self.read_stats = read_stats
        self.points: dict[str, list[tuple[float, float]]] = {ch: [] for ch in CHANNELS}
        self._history: list[list[str]] = []  # canais de cada ponto, para desfazer
        self._used_block = -1
        layout = QVBoxLayout(self)
        intro = QLabel(INSTRUCTIONS)
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(intro)

        self.live = QTableWidget(len(CHANNELS), 4)
        self.live.setHorizontalHeaderLabels(["Canal", "Contagem média", "Ruído (±)", "Tensão medida"])
        self.live.verticalHeader().setVisible(False)
        self.live.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.live.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.live.setShowGrid(False)
        self.use: dict[str, QCheckBox] = {}
        self.spins: dict[str, QDoubleSpinBox] = {}
        for row, (channel, name) in enumerate(zip(CHANNELS, names)):
            check = QCheckBox(name.upper())
            check.setChecked(True)
            check.setStyleSheet(f"color: {list(theme.PHASE.values())[row]}; font-weight: 600")
            self.use[channel] = check
            self.live.setCellWidget(row, 0, check)
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 3.6)
            spin.setDecimals(3)
            spin.setSingleStep(0.01)
            spin.setSuffix(" V")
            spin.valueChanged.connect(lambda value, ch=channel: self._copy_value(ch, value))
            self.spins[channel] = spin
            self.live.setCellWidget(row, 3, spin)
        self.live.setFixedHeight(self.live.horizontalHeader().height() + 3 * 34 + 4)
        for row in range(len(CHANNELS)):
            self.live.setRowHeight(row, 34)
        layout.addWidget(self.live)

        options = QHBoxLayout()
        self.same_voltage = QCheckBox("Mesma tensão em todos os canais (entradas ligadas juntas)")
        self.same_voltage.setChecked(True)
        options.addWidget(self.same_voltage, stretch=1)
        self.record_button = QPushButton("Registrar ponto")
        self.record_button.setObjectName("primary")
        self.record_button.clicked.connect(self.record_point)
        undo = QPushButton("Remover último")
        undo.clicked.connect(self.remove_last)
        options.addWidget(undo)
        options.addWidget(self.record_button)
        layout.addLayout(options)
        self.status = QLabel("Aguardando rajada da DEMOEM…")
        self.status.setStyleSheet(f"color: {theme.MUTED}")
        layout.addWidget(self.status)

        self.table = QTableWidget(0, 1 + len(CHANNELS))
        self.table.setHorizontalHeaderLabels(["Ponto", *(name.upper() for name in names)])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(140)
        layout.addWidget(self.table, stretch=1)
        self.fit_label = QLabel("Registre ao menos 2 pontos por canal para ver a reta.")
        self.fit_label.setTextFormat(Qt.TextFormat.RichText)
        self.fit_label.setWordWrap(True)
        layout.addWidget(self.fit_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText("Aplicar e salvar")
        self.ok_button.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(300)
        self.refresh()

    def _copy_value(self, channel: str, value: float) -> None:
        if not self.same_voltage.isChecked():
            return
        for other, spin in self.spins.items():
            if other != channel and abs(spin.value() - value) > 1e-9:
                spin.blockSignals(True)
                spin.setValue(value)
                spin.blockSignals(False)

    def refresh(self) -> None:
        count, stats = self.read_stats()
        for row, channel in enumerate(CHANNELS):
            mean, noise, saturated = stats.get(channel, (None, None, False))
            texts = ("---", "---") if mean is None else (br(mean, ".1f"), br(noise, ".1f"))
            for column, text in zip((1, 2), texts):
                item = QTableWidgetItem(text + (" · saturado" if saturated and column == 1 else ""))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if saturated:
                    item.setForeground(QColor(theme.DANGER))
                self.live.setItem(row, column, item)
        if not stats:
            self.status.setText("Aguardando rajada da DEMOEM…")
        elif count == self._used_block:
            self.status.setText("Aguardando uma rajada nova depois do último ponto…")
        else:
            self.status.setText("Rajada nova recebida: confira a tensão no multímetro e registre o ponto.")
        self.record_button.setEnabled(bool(stats) and count != self._used_block)

    def record_point(self) -> bool:
        count, stats = self.read_stats()
        if not stats or count == self._used_block:
            self.status.setText("Espere uma rajada nova antes de registrar outro ponto.")
            return False
        added = []
        for channel in CHANNELS:
            if not self.use[channel].isChecked() or channel not in stats:
                continue
            mean, _noise, saturated = stats[channel]
            if saturated:
                self.status.setText(f"{self.use[channel].text()} saturado (0 ou 65535): afaste a tensão das pontas.")
                return False
            added.append((channel, mean, self.spins[channel].value()))
        if not added:
            self.status.setText("Marque ao menos um canal.")
            return False
        self._history.append([channel for channel, _mean, _volts in added])
        row = self.table.rowCount()
        self.table.insertRow(row)
        cells = {channel: f"{br(volts, '.3f')} V  ←  {br(mean, '.0f')}" for channel, mean, volts in added}
        for column, text in enumerate((str(row + 1), *(cells.get(ch, "—") for ch in CHANNELS))):
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, column, item)
        for channel, mean, volts in added:
            self.points[channel].append((mean, volts))
        self.table.scrollToBottom()
        self._used_block = count
        self._update_fit()
        self.refresh()
        return True

    def remove_last(self) -> None:
        """Desfaz o último ponto registrado (todos os canais dele)."""
        if not self._history:
            return
        for channel in self._history.pop():
            self.points[channel].pop()
        self.table.removeRow(self.table.rowCount() - 1)
        self._used_block = -1
        self._update_fit()
        self.refresh()

    def _update_fit(self) -> None:
        lines, valid = [], False
        for channel in CHANNELS:
            points = self.points[channel]
            if not points:
                continue
            name = self.use[channel].text()
            try:
                fit = fit_adc(points)
            except ValueError as exc:
                lines.append(f"<b>{name}</b>: {len(points)} ponto(s) · {exc}")
                continue
            valid = True
            vref = fit.gain * 65535 + fit.offset
            color = theme.SUCCESS if fit.max_error_v < 0.005 else theme.WARNING
            lines.append(f"<b>{name}</b>: {br(fit.gain * 1e6, '.3f')} µV/contagem · offset "
                         f"{br(fit.offset * 1000, '+.1f')} mV · fundo de escala {br(vref, '.3f')} V · "
                         f"<span style='color:{color}'>maior desvio {br(fit.max_error_v * 1000, '.1f')} mV</span> "
                         f"({fit.points} pontos)")
        self.fit_label.setText("<br>".join(lines) or "Registre ao menos 2 pontos por canal para ver a reta.")
        self.ok_button.setEnabled(valid)
