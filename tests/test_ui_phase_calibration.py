"""Assistente de calibração de fase com carga resistiva, sem hardware."""
import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from prisma.core.calibration import Calibration
from prisma.ui.main_window import MainWindow


@pytest.fixture
def window(app, tmp_path):
    from PySide6.QtCore import QSettings

    widget = MainWindow()
    widget.timer.stop()
    widget.settings = QSettings(str(tmp_path / "prisma-test.ini"), QSettings.Format.IniFormat)
    yield widget
    widget.close()


def _analyze_demo(window):
    window.buffer.clear()
    for _ in range(6):
        window._generate_demo_batch()
    window._draw_signals()
    return window.last_analysis[0]


def test_calibracao_de_fase_leva_fp_a_um_e_preserva_ganhos(window, tmp_path):
    window._set_calibration(Calibration({"va": {"gain": 1.0, "offset": 0.0},
                                         "ia": {"gain": 2.0, "offset": 0.0}}, "Ganhos"))
    before = _analyze_demo(window)
    assert before.power["A"].power_factor == pytest.approx(0.9, abs=0.002)

    target = tmp_path / "fase.json"
    window.calibrate_phase(confirm=True, filename=str(target))
    saved = Calibration.load(target)
    expected_us = math.acos(0.9) / (2 * math.pi * 60) * 1e6  # ≈ 1196 µs
    for channel in ("ia", "ib", "ic"):
        assert saved.channels[channel]["delay_us"] == pytest.approx(expected_us, rel=0.01)
    assert saved.channels["ia"]["gain"] == 2.0  # ganho anterior mantido

    after = _analyze_demo(window)
    for phase in "ABC":
        assert after.power[phase].power_factor == pytest.approx(1.0, abs=0.003)

    # Segunda passada: o atraso residual é pequeno e soma ao atual.
    window.calibrate_phase(confirm=True, filename=str(target))
    again = Calibration.load(target).channels["ia"]["delay_us"]
    assert again == pytest.approx(saved.channels["ia"]["delay_us"], abs=20)


def test_calibracao_de_fase_cancelada_nao_altera_nada(window, tmp_path):
    _analyze_demo(window)
    original = window.calibration
    window.calibrate_phase(confirm=False, filename=str(tmp_path / "x.json"))
    assert window.calibration is original
    assert not (tmp_path / "x.json").exists()


def test_calibracao_de_fase_sem_correntes_avisa(window, monkeypatch):
    from types import SimpleNamespace
    shown = []
    monkeypatch.setattr("prisma.ui.features.QMessageBox.information", lambda *a: shown.append(a[2]))
    window.last_analysis = (SimpleNamespace(current_phasors={}),)
    window.calibrate_phase(confirm=True)
    assert shown and "correntes" in shown[0]
