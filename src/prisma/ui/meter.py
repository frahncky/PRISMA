"""Quadro de medições no formato de um multimedidor: grandezas × fases + total."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QSizePolicy

from prisma.core.measurement import LINE_PAIRS, Measurement, line_voltages, load_nature, totals
from prisma.ui import theme

PHASES = ("A", "B", "C")
COLUMNS = PHASES + ("T",)
# (chave, rótulo); a unidade vai em cada célula, com prefixo SI quando couber.
ROWS = (
    ("v", "Tensão"),
    ("vl", "Tensão de linha"),
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
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)
        grid.setColumnStretch(0, 3)
        for column, name in enumerate(COLUMNS, start=1):
            grid.setColumnStretch(column, 2)
            head = QLabel("Trifásico" if name == "T" else f"Fase {name}")
            head.setObjectName("meterHead")
            head.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if name != "T":
                head.setStyleSheet(f"color: {theme.PHASE[name]};")
            grid.addWidget(head, 0, column)
        self.heads = {name: grid.itemAtPosition(0, column).widget()
                      for column, name in enumerate(COLUMNS, start=1)}
        self.cells: dict[tuple[str, str], QLabel] = {}
        for row, (key, caption) in enumerate(ROWS, start=1):
            label = QLabel(caption)
            label.setObjectName("meterRow")
            label.setMinimumHeight(24)
            label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            label.setProperty("alternateRow", row % 2 == 0)
            grid.addWidget(label, row, 0)
            for column, name in enumerate(COLUMNS, start=1):
                cell = QLabel("" if key == "ang" and name == "T" else EMPTY)
                cell.setObjectName("meterTotal" if name == "T" else "meterCell")
                cell.setMinimumHeight(24)
                cell.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
                cell.setProperty("alternateRow", row % 2 == 0)
                cell.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                cell.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                grid.addWidget(cell, row, column)
                self.cells[(key, name)] = cell
        self.cells[("v", "T")].setToolTip("Média das três fases")
        for name, pair in zip(PHASES, ("AB", "BC", "CA")):
            self.cells[("vl", name)].setToolTip(f"Tensão de linha {pair}")
        self.cells[("vl", "T")].setToolTip("Média das tensões de linha")
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

    def _set_wiring(self, phases: tuple[str, ...]) -> None:
        """Cabeçalho do total e dicas conforme a ligação (fases fora dela ficam em "—")."""
        count = len(phases)
        self.heads["T"].setText({1: "Total", 2: "Bifásico"}.get(count, "Trifásico"))
        word = {1: "da fase A", 2: "das fases A e B"}.get(count, "das três fases")
        self.cells[("v", "T")].setToolTip(f"Média {word}")
        self.cells[("i", "T")].setToolTip(f"Média {word}")
        self.cells[("pf", "T")].setToolTip("FP total = P total / S total")
        for name in PHASES:
            self.cells[("vl", name)].setToolTip("")
        for name, (a, b) in zip(PHASES, LINE_PAIRS[tuple(phases)]):
            self.cells[("vl", name)].setToolTip(f"Tensão de linha {a}{b}")

    def show_result(self, result: Measurement, rotation: complex = 1, pin_volts: bool = False) -> None:
        volt = "{:.3f} V" if pin_volts else "{:.2f} V"
        amp_unit = "V" if pin_volts else "A"  # sem calibração, a corrente também é tensão no pino
        used = tuple(result.phases)
        self._set_wiring(used)
        for phase in PHASES:
            if phase in used:
                self.cells[("v", phase)].setText(volt.format(result.rms[phase]))
                self.cells[("ang", phase)].setText(f"{degrees(result.phasors[phase] * rotation)}°")
            else:
                self.cells[("v", phase)].setText("—")
                self.cells[("ang", phase)].setText("—")
        self.cells[("v", "T")].setText(_how(volt.format(sum(result.rms[p] for p in used) / len(used)), "média"))
        # Linha: trifásico AB, BC, CA nas colunas A, B, C; bifásico só AB; monofásico nenhuma.
        lines = [abs(v) for v in line_voltages(result.phasors, used).values()]
        for index, phase in enumerate(PHASES):
            self.cells[("vl", phase)].setText(volt.format(lines[index]) if index < len(lines) else "—")
        self.cells[("vl", "T")].setText(_how(volt.format(sum(lines) / len(lines)), "média") if lines else "—")
        total = totals(result)
        if total is None:
            for key in ("i", "p", "q", "s", "pf"):
                for name in COLUMNS:
                    self.cells[(key, name)].setText(EMPTY)
            self.cells[("i", "A")].setToolTip("Sem canais de corrente")
            return
        for phase in PHASES:
            if phase not in used:
                for key in ("i", "p", "q", "s", "pf"):
                    self.cells[(key, phase)].setText("—")
                continue
            power = result.power[phase]
            self.cells[("i", phase)].setText(f"{result.current_rms[phase]:.3f} {amp_unit}")
            self.cells[("p", phase)].setText(si(power.active_w, "W"))
            self.cells[("q", phase)].setText(si(power.reactive_fundamental_var, "var"))
            self.cells[("s", phase)].setText(si(power.apparent_va, "VA"))
            self.cells[("pf", phase)].setText(_pf(power.power_factor, power.reactive_fundamental_var))
        self.cells[("i", "T")].setText(_how(f"{sum(result.current_rms[p] for p in used) / len(used):.3f} {amp_unit}",
                                            "média"))
        self.cells[("p", "T")].setText(_how(si(total.active_w, "W"), "soma"))
        self.cells[("q", "T")].setText(_how(si(total.reactive_var, "var"), "soma"))
        self.cells[("s", "T")].setText(_how(si(total.apparent_va, "VA"), "soma"))
        self.cells[("pf", "T")].setText(_pf(total.power_factor, total.reactive_var))


def _how(text: str, word: str) -> str:
    """Valor da coluna Trifásico com o modo de cálculo em letra pequena ("média" ou "soma")."""
    return f"{text} <span style='color:{theme.SUBTLE}; font-size:11px; font-weight:400'>{word}</span>"


def _pf(value: float | None, reactive: float) -> str:
    """FP com a natureza da carga, como nos medidores: 0.900 Indut. / 0.950 Capac."""
    if value is None:
        return EMPTY
    return f"{value:.3f} {load_nature(reactive)}".rstrip()
