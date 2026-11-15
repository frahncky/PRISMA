"""Ligação do experimento: monofásico (A), bifásico (A e B) e trifásico (A, B e C)."""
import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from prisma.core.measurement import (MeterStats, line_voltages, three_phase, totals, with_wiring)
from prisma.core.query import alerts, answer
from prisma.main import parse_args
from test_query import _measurement


def test_totais_somam_so_as_fases_ligadas():
    full = _measurement()
    per_phase = full.power["A"].active_w
    assert totals(with_wiring(full, "tri")).active_w == pytest.approx(3 * per_phase)
    assert totals(with_wiring(full, "bi")).active_w == pytest.approx(2 * per_phase)
    mono = totals(with_wiring(full, "mono"))
    assert mono.active_w == pytest.approx(per_phase)
    assert mono.power_factor == pytest.approx(0.9, abs=1e-3)


def test_tensoes_de_linha_por_ligacao():
    result = _measurement()
    assert set(line_voltages(result.phasors, ("A", "B", "C"))) == {"AB", "BC", "CA"}
    bi = line_voltages(result.phasors, ("A", "B"))
    assert list(bi) == ["AB"] and abs(bi["AB"]) == pytest.approx(127 * math.sqrt(3), rel=1e-3)
    assert line_voltages(result.phasors, ("A",)) == {}


def test_desequilibrio_e_sequencia_so_no_trifasico():
    unbalanced = _measurement(unbalanced=True)
    assert three_phase(unbalanced) and any("Desequilíbrio" in a for a in alerts(unbalanced))
    for wiring in ("mono", "bi"):
        result = with_wiring(unbalanced, wiring)
        assert not three_phase(result)
        assert not any("Desequilíbrio" in a or "Sequência" in a for a in alerts(result))
    assert "três fases" in answer("tem desequilíbrio?", with_wiring(unbalanced, "bi")).text


def test_perguntas_respondem_so_as_fases_ligadas():
    mono = with_wiring(_measurement(), "mono")
    text = answer("qual a tensão", mono).text
    assert "fase A" in text and "fase B" not in text and "fase C" not in text
    assert "fase A" in answer("qual a tensão da fase C", mono).text  # fase fora da ligação: responde a A


def test_estatisticas_ignoram_fases_fora_da_ligacao():
    stats = MeterStats()
    mono = with_wiring(_measurement(), "mono")
    stats.update(0.0, mono)
    stats.update(1.0, mono)
    assert set(stats.v_min) == {"A"} and set(stats.i_max) == {"A"}
    point = stats.trend[-1]
    assert not math.isnan(point.voltage[0]) and math.isnan(point.voltage[1]) and math.isnan(point.voltage[2])
    assert point.active_w == pytest.approx(totals(mono).active_w)
    assert stats.energy.active_wh == pytest.approx(totals(mono).active_w / 3600)


def test_ligacao_invalida():
    with pytest.raises(ValueError):
        with_wiring(_measurement(), "quadri")


def test_quadro_de_medicoes_por_ligacao(app):
    from prisma.ui.meter import MeterTable
    table = MeterTable()
    table.show_result(with_wiring(_measurement(), "mono"))
    assert table.heads["T"].text() == "Total"
    assert table.cells[("v", "A")].text().endswith(" V") and table.cells[("v", "B")].text() == "—"
    assert table.cells[("p", "C")].text() == "—" and table.cells[("vl", "A")].text() == "—"
    table.show_result(with_wiring(_measurement(), "bi"))
    assert table.heads["T"].text() == "Bifásico"
    assert table.cells[("vl", "A")].text().endswith(" V") and table.cells[("vl", "B")].text() == "—"
    assert table.cells[("vl", "A")].toolTip() == "Tensão de linha AB"
    table.show_result(_measurement())
    assert table.heads["T"].text() == "Trifásico" and table.cells[("vl", "C")].text().endswith(" V")


def test_painel_mostra_so_as_fases_ligadas(app):
    from prisma.ui.touch_panel import PanelData, TouchPanel
    panel = TouchPanel(lambda: PanelData(with_wiring(_measurement(unbalanced=True), "mono"),
                                         "AQUISIÇÃO SERIAL REAL — COM3", MeterStats(), age_s=0.5))
    try:
        assert panel.tiles["vA"].value.text() == "127,0 V"
        assert panel.tiles["vB"].value.text() == "—" and panel.tiles["iC"].value.text() == "—"
        assert panel.tiles["unb"].value.text() == "—"
        assert panel.alert_label.isHidden()  # o desequilíbrio da fase C não vale no monofásico
        assert panel.wiring_label.text() == "Monofásico"
        assert panel.ov_total_head.text() == "Total"
        assert panel.tiles["mmB"].value.text() == "—"
    finally:
        panel.close()


def test_janela_principal_aplica_a_ligacao(app):
    from prisma.ui.main_window import MainWindow
    window = MainWindow()
    try:
        window.set_wiring("bi", save=False)
        assert window.wiring_combo.currentData() == "bi"
        assert window.curves["A"].isVisible() and window.curves["B"].isVisible() and not window.curves["C"].isVisible()
        for _ in range(8):  # demonstração: gera amostras e analisa
            window._tick()
        result = window.last_analysis[0]
        assert result.phases == ("A", "B")
        assert window.unbalance_hint.text() == "só na ligação trifásica"
        assert window.power_view.item(2, 0) is None  # sem linha da fase C
        window.set_wiring("tri", save=False)
        assert window.curves["C"].isVisible()
    finally:
        window.close()


def test_argumento_de_ligacao():
    assert parse_args(["--ligacao", "bi"]).ligacao == "bi"
    with pytest.raises(SystemExit):
        parse_args(["--ligacao", "quadri"])


def test_legendas_acompanham_a_ligacao(app):
    from PySide6.QtWidgets import QLabel
    from prisma.ui.touch_panel import PanelData, TouchPanel
    panel = TouchPanel(lambda: PanelData(with_wiring(_measurement(), "bi"), "DEMONSTRAÇÃO — SINAIS SINTÉTICOS"))
    try:
        legends = [k.text() for k in panel.findChildren(QLabel, "plotLegend") if k.property("phaseSymbol")]
        assert legends and all("Va" in t or "Ia" in t for t in legends)
        assert not any("Vc" in t or "Ic" in t for t in legends)
    finally:
        panel.close()
