"""Modo quiosque: painel dedicado sem demonstração, aviso de dados parados, saída por toque longo."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from prisma.main import parse_args
from prisma.ui.touch_panel import HoldButton, PanelData, TouchPanel, link_problem
from test_query import _measurement


@pytest.mark.parametrize("mode, age, expected", [
    ("DEMONSTRAÇÃO — SINAIS SINTÉTICOS", None, ""),
    ("AQUISIÇÃO SERIAL REAL — COM3", 0.8, ""),
    ("AQUISIÇÃO SERIAL REAL — COM3", 12.0, "Sem dados novos da placa há 12 s: valores congelados"),
    ("AQUISIÇÃO SERIAL REAL — COM3", 600.0, "Sem dados novos da placa há 10 min: valores congelados"),
    ("RECONECTANDO A prisma.local:3333 (rede) — DADOS RETIDOS", None,
     "Conexão perdida: reconectando a prisma.local:3333 (rede)…  (valores congelados)"),
    ("CONECTANDO A COM3 — SEM DADOS", None, "Aguardando dados da placa…"),
    ("SERIAL COM3 — AGUARDANDO AMOSTRAS", None, "Aguardando dados da placa…"),
    ("DESCONECTADO — NENHUMA PORTA CONFIGURADA", None, "Sem conexão com a placa: nenhuma porta configurada"),
    ("SERIAL DESCONECTADA — DADOS RETIDOS", None, "Sem conexão com a placa: dados retidos"),
])
def test_aviso_de_conexao(mode, age, expected):
    assert link_problem(mode, age) == expected


def test_painel_mostra_faixa_quando_os_dados_param(app):
    state = {"age": 0.5}
    panel = TouchPanel(lambda: PanelData(_measurement(), "AQUISIÇÃO SERIAL REAL — COM3", age_s=state["age"]))
    assert panel.link_banner.isHidden()
    state["age"] = 7.0
    panel.refresh()
    assert not panel.link_banner.isHidden() and "7 s" in panel.link_banner.text()
    panel.close()


def test_sair_no_quiosque_so_com_toque_longo(app):
    panel = TouchPanel(lambda: PanelData(None, "DESCONECTADO — NENHUMA PORTA CONFIGURADA"), kiosk=True)
    closed = []
    panel.closed.connect(lambda: closed.append(1))
    panel.show()
    button = panel.close_button
    assert isinstance(button, HoldButton) and "segure" in button.text()
    button.click()  # toque curto: nada acontece
    app.processEvents()
    assert panel.isVisible() and not closed
    button.pressed.emit()
    assert button._timer.isActive()
    button._timer.timeout.emit()  # segurou o tempo todo
    app.processEvents()
    assert not panel.isVisible() and closed == [1]


def test_quiosque_esconde_a_janela_e_nao_mostra_demonstracao(app, monkeypatch):
    from prisma.ui import kiosk
    from prisma.ui.main_window import MainWindow
    calls = []
    monkeypatch.setattr(kiosk, "keep_display_on", lambda on: calls.append(on) or True)
    window = MainWindow()
    window.show()
    panel = window.enter_kiosk(hide_cursor=False)
    try:
        assert window.kiosk and not window.isVisible() and panel.kiosk and panel.isVisible()
        assert window.mode.startswith("DESCONECTADO") and window.data_age() is None
        window._tick()  # sem demonstração: o buffer continua vazio
        assert window.buffer.arrays(duration_s=1.0)[0].size == 0
        assert not panel.link_banner.isHidden()
        assert calls == [True]
        panel.close()  # saída (toque longo) leva à manutenção
        app.processEvents()
        assert not window.kiosk and window.isVisible() and calls == [True, False]
    finally:
        window.close()


def test_quiosque_reconecta_a_serial(app, monkeypatch):
    from prisma.ui import kiosk
    from prisma.ui.main_window import MainWindow
    monkeypatch.setattr(kiosk, "keep_display_on", lambda on: True)
    window = MainWindow()
    window.enter_kiosk(hide_cursor=False)
    window.port_combo.insertItem(0, "COM99 (aguardando)", "COM99")
    window.port_combo.setCurrentIndex(0)
    started = []
    monkeypatch.setattr("prisma.core.serial_reader.SerialReader.start", lambda self: started.append(self))
    try:
        window.connect_serial()
        assert started and started[0].persistent and not started[0].network
        window.exit_kiosk()
        assert not started[0].persistent
    finally:
        window.reader = None
        window.close()


def test_argumentos_do_quiosque():
    args = parse_args(["--quiosque", "--port", "prisma.local"])
    assert args.quiosque and args.port == "prisma.local" and not args.cursor
