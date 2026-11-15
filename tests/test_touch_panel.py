"""Painel touch (medidor inteligente): valores, abas, gráficos e energia, sem tela."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime

import numpy as np

from prisma.core.measurement import MeterStats
from prisma.ui.touch_panel import ALL, ENERGY, PAGES, PHASORS, TRENDS, WAVES, PanelData, TouchPanel
from test_query import _measurement


def _waves(currents=True):
    t = np.arange(480) / 2400.0
    phases = np.array([0, -2 * np.pi / 3, 2 * np.pi / 3])
    v = 127 * np.sqrt(2) * np.sin(2 * np.pi * 60 * t[:, None] + phases)
    i = 5 * np.sqrt(2) * np.sin(2 * np.pi * 60 * t[:, None] + phases - np.arccos(0.9)) if currents else None
    return t, v, i


def _stats(result, minutes=60):
    stats = MeterStats()
    for minute in range(minutes + 1):  # passos de 60 s: 1 h a 1714,5 W
        stats.update(60.0 * minute, result, now=datetime(2026, 11, 14, 10, minute % 60))
    return stats


def _panel(app, result, stats=None, mode="DEMONSTRAÇÃO — SINAIS SINTÉTICOS", currents=True):
    t, v, i = _waves(currents)
    return TouchPanel(lambda: PanelData(result, mode, stats, t, v, i))


def test_resumo_mostra_valores_de_medidor(app):
    panel = _panel(app, _measurement())
    assert panel.tiles["vA"].value.text() == "127,0 V"
    assert panel.tiles["iB"].value.text() == "5,00 A"
    assert panel.tiles["freq"].value.text() == "60,00 Hz"
    assert panel.tiles["pf"].value.text().startswith("0,900") and "Indut." in panel.tiles["pf"].value.text()
    assert panel.tiles["pf"].hint.text() == "carga indutiva"
    assert panel.tiles["power"].value.text().endswith("kW")
    assert panel.tiles["energy"].value.text() == "---"  # sem contadores
    assert panel.mode_label.text() == "Demonstração"
    assert panel.alert_label.isHidden()
    panel.close()


def test_sem_voz_no_painel(app):
    panel = _panel(app, _measurement())
    texts = {button.text() for button in panel.findChildren(type(panel.nav.button(0)))}
    assert not texts & {"Falar", "Perguntar", "Voz ligada", "Está tudo bem?"}
    panel.close()


def test_toque_no_bloco_abre_a_aba_do_detalhe(app):
    panel = _panel(app, _measurement(), _stats(_measurement()))
    panel.tiles["vA"].click()
    assert panel.pages.currentIndex() == WAVES
    assert panel.nav.button(WAVES).isChecked()
    assert len(panel.wave_v_curves["A"].getData()[0]) > 50
    assert len(panel.wave_i_curves["B"].getData()[0]) > 50
    panel.tiles["energy"].click()
    assert panel.pages.currentIndex() == ENERGY
    panel.close()


def test_fasores_harmonicas_e_tendencias(app):
    result = _measurement()
    panel = _panel(app, result, _stats(result))
    panel.show_page(PHASORS)
    assert panel.phasor_title.text() == "FASORES"
    assert "THD" in panel.harmonic_title.text()
    panel.show_page(TRENDS)
    x, y = panel.trend_p_curve.getData()
    assert len(x) == 61 and x[-1] == 0 and np.isclose(y[-1], 1.7145, atol=1e-3)
    assert panel.trend_p_title.text() == "POTÊNCIA" and "TRACEJADO" not in panel.trend_p_title.text()
    panel.close()


def test_energia_demanda_e_minimos_maximos(app):
    result = _measurement()
    panel = _panel(app, result, _stats(result))
    assert panel.tiles["energy"].value.text() == "1,71 kWh"
    assert panel.tiles["e_imp"].value.text() == "1,71 kWh"
    assert panel.tiles["e_exp"].value.text() == "0 Wh"
    assert panel.tiles["demand"].value.text() == "1,71 kW"
    assert panel.tiles["demand_max"].hint.text().startswith("em 14/11")
    assert panel.tiles["elapsed"].value.text() == "1:00:00"
    assert panel.tiles["mmA"].value.text() == "127 – 127 V"
    assert "corrente máx 5,00 A" in panel.tiles["mmA"].hint.text()
    panel.close()


def test_visao_geral_mostra_valores_e_graficos(app):
    result = _measurement()
    panel = _panel(app, result, _stats(result))
    panel.nav.button(ALL).click()
    assert PAGES[ALL] == "Visão geral" and panel.pages.currentIndex() == ALL
    assert panel.ov_cells[("v", "A")].text() == "127,0"
    assert panel.ov_cells[("i", "B")].text() == "5,00"
    assert panel.ov_cells[("pf", "T")].text().startswith("0,900") and "Indut." in panel.ov_cells[("pf", "T")].text()
    assert "kW" in panel.ov_cells[("p", "T")].text() and "soma" in panel.ov_cells[("p", "T")].text()
    assert "média" in panel.ov_cells[("v", "T")].text()
    assert panel.ov_kpis["freq"].text() == "60,00 Hz"
    assert panel.ov_kpis["energy"].text() == "1,71 kWh"
    assert panel.ov_kpis["demand_max"].text() == "1,71 kW"
    assert len(panel.ov_wave_curves["A"].getData()[0]) > 50
    assert panel.ov_harmonic.getPlotItem().items  # barras desenhadas
    panel.close()


def test_alerta_e_sem_correntes(app):
    panel = _panel(app, _measurement(currents=False, unbalanced=True), currents=False)
    assert not panel.alert_label.isHidden() and "Desequilíbrio" in panel.alert_label.text()
    assert panel.tiles["iA"].value.text() == "---" and panel.tiles["iA"].hint.text() == "sem correntes"
    assert "PRODIST" in panel.tiles["unb"].hint.text()
    panel.show_page(WAVES)
    assert "sem canais de corrente" in panel.wave_i_title.text()
    panel.show_page(PHASORS)
    assert panel.phasor_title.text().startswith("FASORES DE TENSÃO")
    panel.close()


def test_sem_medicao(app):
    panel = TouchPanel(lambda: PanelData(None))
    assert panel.tiles["vA"].value.text() == "---"
    assert panel.tiles["demand"].hint.text() == "sem contadores"
    for page in range(len(PAGES)):
        panel.show_page(page)  # nenhuma aba quebra sem dados
    panel.close()


def test_menu_abre_painel_da_janela_principal(app, tmp_path):
    from PySide6.QtCore import QSettings
    from prisma.ui.main_window import MainWindow

    window = MainWindow()
    window.timer.stop()
    window.settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    for _ in range(12):
        window._generate_demo_batch()
        window._draw_signals()
    panel = window.open_touch_panel(fullscreen=False)
    panel.refresh()
    assert panel.tiles["vB"].value.text() == "127,0 V"
    assert panel.tiles["energy"].value.text().endswith("Wh")
    panel.show_page(WAVES)
    assert len(panel.wave_v_curves["C"].getData()[0]) > 50
    panel.close()
    window.close()


def test_eixos_mostram_mv_e_nao_fator_de_escala(app):
    t, v, i = _waves()
    panel = TouchPanel(lambda: PanelData(_measurement(), "Aquisição serial real", None, t, v * 1e-4, i))
    panel.resize(1360, 768)
    panel.show()
    panel.show_page(WAVES)
    panel.refresh()
    app.processEvents()
    label = panel.wave_v.getAxis("left").labelString()
    assert "Tensão" in label and "(mV)" in label and "x0.001" not in label
    assert "(A)" in panel.wave_i.getAxis("left").labelString()
    assert not panel.trend_p.getAxis("left").autoSIPrefix  # "kW" já é a unidade
    panel.close()
