"""Verificações estáticas dos artefatos KiCad da interface AFE-LV.

Não substitui abertura dos arquivos, ERC/DRC do KiCad ou ensaio físico.
"""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "cad" / "afe-lv"
CHANNELS = ("VA", "VB", "VC", "IA", "IB", "IC")


def _check_balanced_sexpr(text: str) -> None:
    depth = 0
    quoted = False
    escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            assert depth >= 0, "Parêntese excedente"
    assert depth == 0 and not quoted, "S-expression incompleta"


def test_kicad_syntax_and_sections():
    schematic = (BASE / "prisma_afe_lv.kicad_sch").read_text(encoding="utf-8")
    board = (BASE / "prisma_afe_lv.kicad_pcb").read_text(encoding="utf-8")
    for value in (schematic, board):
        _check_balanced_sexpr(value)
    assert schematic.startswith("(kicad_sch")
    assert board.startswith("(kicad_pcb")
    assert "(lib_symbols" in schematic
    assert '(layer "Edge.Cuts")' in board
    assert '(layer "F.Cu")' in board
    assert '(layer "B.Cu")' in board


def test_six_channels_in_schematic_and_pcb():
    sch = (BASE / "prisma_afe_lv.kicad_sch").read_text(encoding="utf-8")
    pcb = (BASE / "prisma_afe_lv.kicad_pcb").read_text(encoding="utf-8")
    assert sch.count('(lib_id "PRISMA:Conn02")') == 12
    assert sch.count('(lib_id "Device:R")') == 6
    assert sch.count('(lib_id "Device:C")') == 6
    assert sch.count('(lib_id "Connector:TestPoint")') == 6
    assert len(re.findall(r'\(footprint "Connector_PinHeader_2.54mm:', pcb)) == 12
    assert len(re.findall(r'\(footprint "Resistor_SMD:', pcb)) == 6
    assert len(re.findall(r'\(footprint "Capacitor_SMD:', pcb)) == 6
    assert len(re.findall(r'\(footprint "TestPoint:', pcb)) == 6
    for index, name in enumerate(CHANNELS):
        for net in ("IN_" + name, "ADC_" + name):
            assert f'(label "{net}"' in sch
            assert re.search(r'\(net \d+ "' + net + r'"\)', pcb)
        assert f'(property "Reference" "J{index + 1}"' in sch
        assert f'(property "Reference" "J{index + 7}"' in sch
    assert '(net 1 "GND")' in pcb


def test_bom_and_safety_notes():
    bom = (BASE / "BOM.csv").read_text(encoding="utf-8")
    docs = (BASE / "README.md").read_text(encoding="utf-8")
    for token in ("R1-R6", "C1-C6", "J1-J12", "TP1-TP6"):
        assert token in bom
    for word in ("anti-alias", "J38", "SELV", "ERC", "DRC"):
        assert word in docs
