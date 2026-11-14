"""Painel touch: valores, alertas e perguntas faladas, sem tela nem som."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from prisma.ui.touch_panel import TouchPanel
from test_query import _measurement


@pytest.fixture
def spoken():
    return []


def _panel(app, result, spoken, mode="DEMONSTRAÇÃO"):
    return TouchPanel(lambda: (result, mode), speaker=spoken.append)


def test_painel_mostra_valores_grandes(app, spoken):
    panel = _panel(app, _measurement(), spoken)
    assert panel.tiles["vA"].value.text() == "127,0 V"
    assert panel.tiles["iB"].value.text() == "5,00 A"
    assert panel.tiles["freq"].value.text() == "60,00 Hz"
    assert panel.tiles["pf"].value.text() == "0,900"
    assert panel.tiles["power"].value.text().endswith("kW")
    assert panel.tiles["pf"].hint.text() == "indutivo"
    assert panel.tiles["energy"].value.text() == "---"  # sem contador de energia
    assert panel.alert_label.isHidden()
    panel.close()


def test_toque_no_bloco_pergunta_e_fala(app, spoken):
    panel = _panel(app, _measurement(), spoken)
    panel.tiles["iA"].click()
    assert spoken == ["A corrente da fase A é 5,00 ampères."]
    assert panel.answer_label.text() == spoken[0]
    panel.voice_button.click()  # desliga a voz: só mostra
    panel.input.setText("qual a frequência?")
    panel._ask_typed()
    assert len(spoken) == 1 and "60,00 hertz" in panel.answer_label.text()
    panel.close()


def test_alerta_e_sem_correntes(app, spoken):
    panel = _panel(app, _measurement(currents=False, unbalanced=True), spoken)
    assert not panel.alert_label.isHidden() and "Desequilíbrio" in panel.alert_label.text()
    assert panel.tiles["iA"].value.text() == "---" and panel.tiles["iA"].hint.text() == "sem correntes"
    assert "PRODIST" in panel.tiles["unb"].hint.text()
    panel.close()


def test_energia_acumulada_no_painel(app, spoken):
    from prisma.core.measurement import EnergyCounter

    result = _measurement()
    counter = EnergyCounter()
    for minute in range(61):  # 1 h a 1714,5 W, em passos de 60 s
        counter.update(60.0 * minute, result)
    panel = TouchPanel(lambda: (result, "DEMONSTRAÇÃO"), speaker=spoken.append, energy=lambda: counter)
    assert panel.tiles["energy"].value.text() == "1,71 kWh"
    panel.tiles["energy"].click()
    assert spoken == ["A energia ativa acumulada é 1,71 quilowatts-hora."]
    panel.close()


def test_sem_medicao(app, spoken):
    panel = _panel(app, None, spoken)
    assert panel.tiles["vA"].value.text() == "---"
    assert "Ainda não há medição" in panel.ask("tensão da fase A")
    panel.close()


def test_menu_abre_painel_da_janela_principal(app, tmp_path):
    from PySide6.QtCore import QSettings
    from prisma.ui.main_window import MainWindow

    window = MainWindow()
    window.timer.stop()
    window.settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    for _ in range(6):
        window._generate_demo_batch()
    window._draw_signals()
    panel = window.open_touch_panel(fullscreen=False)
    panel.speaker = lambda text: None
    panel.refresh()
    assert panel.tiles["vB"].value.text() == "127,0 V"
    assert "corrente da fase C" in panel.ask("corrente fase C")
    panel.close()
    window.close()
