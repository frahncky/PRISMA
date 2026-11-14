"""Quadro de medições no formato de um multimedidor: grandezas × fases + total."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout

from prisma.core.measurement import Measurement, totals
from prisma.ui import theme

PHASES = ("A", "B", "C")
COLUMNS = PHASES + ("T",)
# (chave, rótulo); a unidade vai em cada célula, com prefixo SI quando couber.
ROWS = (
    ("v", "Tensão"),
    ("i", "Corrente"),
    ("p", "Potência ativa"),
    ("q", "Potência reativa"),
    ("s", "Potência aparente"),
    ("pf", "Fator de potência"),
    ("ang", "Ângulo da tensão"),
)
EMPTY = "---"


def si(value: float, unit: str) -> str:
    """Quatro algarismos significativos com prefixo k/M/m: 571.5 W, 1.714 kW."""
    magnitude = abs(value)
    for factor, prefix in ((1e6, "M"), (1e3, "k"), (1.0, ""), (1e-3, "m")):
        if magnitude >= factor:
            break
    else:
        return f"0 {unit}"
    scaled = value / factor
    decimals = max(0, 3 - int(math.floor(math.log10(abs(scaled)))))
    return f"{scaled:.{decimals}f} {prefix}{unit}"


def degrees(phasor: complex, decimals: int = 1) -> str:
    """Ângulo em graus sem "-0.0" (zero negativo de arredondamento)."""
    value = round(float(np.degrees(np.angle(phasor))), decimals) + 0.0
    return f"{value:.{decimals}f}"


class MeterTable(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)
        title = QLabel("MEDIÇÕES")
        title.setObjectName("panelTitle")
        outer.addWidget(title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(5)
        grid.setColumnStretch(0, 3)
        for column, name in enumerate(COLUMNS, start=1):
            grid.setColumnStretch(column, 2)
            head = QLabel("Trifásico" if name == "T" else f"Fase {name}")
            head.setObjectName("meterHead")
            head.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if name != "T":
                head.setStyleSheet(f"color: {theme.PHASE[name]};")
            grid.addWidget(head, 0, column)
        self.cells: dict[tuple[str, str], QLabel] = {}
        for row, (key, caption) in enumerate(ROWS, start=1):
            label = QLabel(caption)
            label.setObjectName("meterRow")
            grid.addWidget(label, row, 0)
            for column, name in enumerate(COLUMNS, start=1):
                cell = QLabel("" if key == "ang" and name == "T" else EMPTY)
                cell.setObjectName("meterTotal" if name == "T" else "meterCell")
                cell.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                grid.addWidget(cell, row, column)
                self.cells[(key, name)] = cell
        self.cells[("v", "T")].setToolTip("Média das três fases")
        self.cells[("i", "T")].setToolTip("Média das três fases")
        self.cells[("pf", "T")].setToolTip("FP trifásico = P total / S total")
        outer.addLayout(grid)
        outer.addStretch(1)
        self.clear()

    @property
    def voltage_labels(self) -> dict[str, QLabel]:
        return {phase: self.cells[("v", phase)] for phase in PHASES}

    def clear(self) -> None:
        for (key, name), cell in self.cells.items():
            if key == "v" and name != "T":
                cell.setText(f"{EMPTY} V")
            else:
                cell.setText("" if key == "ang" and name == "T" else EMPTY)

    def show_result(self, result: Measurement, rotation: complex = 1, pin_volts: bool = False) -> None:
        volt = "{:.3f} V" if pin_volts else "{:.2f} V"
        amp_unit = "V" if pin_volts else "A"  # sem calibração, a corrente também é tensão no pino
        for phase in PHASES:
            self.cells[("v", phase)].setText(volt.format(result.rms[phase]))
            self.cells[("ang", phase)].setText(f"{degrees(result.phasors[phase] * rotation)}°")
        self.cells[("v", "T")].setText(volt.format(sum(result.rms.values()) / 3))
        total = totals(result)
        if total is None:
            for key in ("i", "p", "q", "s", "pf"):
                for name in COLUMNS:
                    self.cells[(key, name)].setText(EMPTY)
            self.cells[("i", "A")].setToolTip("Sem canais de corrente")
            return
        for phase in PHASES:
            power = result.power[phase]
            self.cells[("i", phase)].setText(f"{result.current_rms[phase]:.3f} {amp_unit}")
            self.cells[("p", phase)].setText(si(power.active_w, "W"))
            self.cells[("q", phase)].setText(si(power.reactive_fundamental_var, "var"))
            self.cells[("s", phase)].setText(si(power.apparent_va, "VA"))
            self.cells[("pf", phase)].setText(_pf(power.power_factor, power.reactive_fundamental_var))
        self.cells[("i", "T")].setText(f"{sum(result.current_rms.values()) / 3:.3f} {amp_unit}")
        self.cells[("p", "T")].setText(si(total.active_w, "W"))
        self.cells[("q", "T")].setText(si(total.reactive_var, "var"))
        self.cells[("s", "T")].setText(si(total.apparent_va, "VA"))
        self.cells[("pf", "T")].setText(_pf(total.power_factor, total.reactive_var))


def _pf(value: float | None, reactive: float) -> str:
    """FP com a natureza da carga, como nos medidores: ind. (Q > 0) ou cap. (Q < 0)."""
    if value is None:
        return EMPTY
    kind = " ind" if reactive > 1e-9 else " cap" if reactive < -1e-9 else ""
    return f"{value:.3f}{kind}"
