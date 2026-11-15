"""Diálogo "Perfis de sensor": o módulo ligado em cada canal da DEMOEM e seus parâmetros."""
from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QGridLayout, QHBoxLayout,
                               QLabel, QVBoxLayout, QWidget)

from prisma.core.sensors import (BY_KEY, CURRENT_CHANNELS, DEFAULT_BIAS_V, SensorChoice, sensors_for)
from prisma.ui import theme

NONE = ""


class SensorDialog(QDialog):
    """Uma linha por canal das fases ligadas: sensor, parâmetros, polarização e relação."""

    def __init__(self, parent, channels: tuple[str, ...], current: dict[str, SensorChoice]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Perfis de sensor")
        self.setMinimumWidth(820)
        layout = QVBoxLayout(self)
        intro = QLabel("Escolha o módulo ligado em cada canal. O PRISMA calcula V e A <b>aproximados</b> pela "
                       "relação nominal do sensor e centra a forma de onda na polarização medida no pino (padrão "
                       + f"{DEFAULT_BIAS_V:.2f}".replace(".", ",")
                       + " V; com módulo em 5 V e divisor ×2/3, ~1,67 V). Depois, refine com "
                       "<b>2 · Sensores com multímetro</b>.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        for column, title in enumerate(("Canal", "Sensor", "Parâmetros", "Polarização", "Relação")):
            head = QLabel(title)
            head.setStyleSheet(f"color: {theme.MUTED}; font-weight: 700;")
            grid.addWidget(head, 0, column)
        self.rows: dict[str, dict] = {}
        for row, channel in enumerate(channels, start=1):
            name = QLabel(channel.upper())
            phase = channel[1].upper()
            name.setStyleSheet(f"color: {theme.PHASE[phase]}; font-weight: 700;")
            combo = QComboBox()
            combo.addItem("— sem sensor (volts no pino) —", NONE)
            for model in sensors_for(channel):
                combo.addItem(model.label, model.key)
            params = QWidget()
            params_layout = QHBoxLayout(params)
            params_layout.setContentsMargins(0, 0, 0, 0)
            bias = QDoubleSpinBox()
            bias.setRange(0.0, 3.3)
            bias.setDecimals(3)
            bias.setSuffix(" V")
            ratio = QLabel("—")
            ratio.setMinimumWidth(110)
            grid.addWidget(name, row, 0)
            grid.addWidget(combo, row, 1)
            grid.addWidget(params, row, 2)
            grid.addWidget(bias, row, 3)
            grid.addWidget(ratio, row, 4)
            entry = {"combo": combo, "params": params, "layout": params_layout, "spins": {}, "bias": bias,
                     "ratio": ratio}
            self.rows[channel] = entry
            choice = current.get(channel)
            bias.setValue(choice.bias_v if choice else DEFAULT_BIAS_V)
            index = combo.findData(choice.sensor if choice else NONE)
            combo.setCurrentIndex(max(index, 0))
            self._build_params(channel, choice.params if choice else {})
            combo.currentIndexChanged.connect(lambda _=0, ch=channel: self._build_params(ch, {}))
            bias.valueChanged.connect(lambda _=0.0, ch=channel: self._update_ratio(ch))
        layout.addLayout(grid)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color: {theme.MUTED};")
        layout.addWidget(self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Aplicar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_note()

    def _build_params(self, channel: str, values: dict[str, float]) -> None:
        entry = self.rows[channel]
        layout = entry["layout"]
        while layout.count():
            widget = layout.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        entry["spins"] = {}
        model = BY_KEY.get(entry["combo"].currentData())
        entry["bias"].setEnabled(model is not None)
        if model is not None:
            for param in model.params:
                label = QLabel(param.label)
                label.setStyleSheet(f"color: {theme.MUTED};")
                spin = QDoubleSpinBox()
                spin.setRange(param.minimum, param.maximum)
                spin.setDecimals(3)
                spin.setSuffix(f" {param.unit}")
                spin.setValue(float(values.get(param.key, param.default)))
                spin.valueChanged.connect(lambda _=0.0, ch=channel: self._update_ratio(ch))
                layout.addWidget(label)
                layout.addWidget(spin)
                entry["spins"][param.key] = spin
        self._update_ratio(channel)
        self._update_note()

    def _choice(self, channel: str) -> SensorChoice | None:
        entry = self.rows[channel]
        key = entry["combo"].currentData()
        if not key:
            return None
        return SensorChoice(key, {k: s.value() for k, s in entry["spins"].items()}, entry["bias"].value())

    def _update_ratio(self, channel: str) -> None:
        entry = self.rows[channel]
        choice = self._choice(channel)
        if choice is None:
            entry["ratio"].setText("volts no pino")
            return
        try:
            unit = "A/V" if channel in CURRENT_CHANNELS else "V/V"
            entry["ratio"].setText(f"{choice.ratio(channel):.4g} {unit}")
        except ValueError as exc:
            entry["ratio"].setText(str(exc))

    def _update_note(self) -> None:
        if not hasattr(self, "note"):  # ainda montando as linhas
            return
        notes = {BY_KEY[c.sensor].label: BY_KEY[c.sensor].note for c in self.choices().values()}
        self.note.setText("<br>".join(f"<b>{label}:</b> {text}" for label, text in notes.items()))

    def choices(self) -> dict[str, SensorChoice]:
        return {ch: c for ch in self.rows if (c := self._choice(ch)) is not None}
