"""Perfis de sensor: relação nominal de cada módulo, centragem na polarização e uso na janela."""
import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from prisma.core.calibration import Calibration
from prisma.core.protocol import MeterSummary
from prisma.core.sensors import SensorChoice, sensor_channels

VREF = 3.3
V_PIN = VREF / 65535   # volts no pino por contagem (tensões)
I_PIN = VREF / 32768   # volts diferenciais por contagem (correntes, binário deslocado)
NOMINAL = {**{ch: (V_PIN, 0.0) for ch in ("va", "vb", "vc")}, **{ch: (I_PIN, -VREF) for ch in ("ia", "ib", "ic")}}


@pytest.mark.parametrize("channel, choice, ratio", [
    ("va", SensorChoice("vt_divider", {"primary_v": 127, "secondary_v": 9, "r_top_kohm": 100, "r_bottom_kohm": 10}),
     127 / 9 * 11),
    ("vb", SensorChoice("zmpt101b", {"line_v": 127, "pin_v": 0.9}), 127 / 0.9),
    ("vc", SensorChoice("v_ratio", {"ratio": 200}), 200),
    ("ia", SensorChoice("sct013_1v", {"rated_a": 30}), 30),
    ("ib", SensorChoice("ct_burden", {"turns": 2000, "burden_ohm": 33}), 2000 / 33),
    ("ic", SensorChoice("i_ratio", {"ratio": 5}), 5),
])
def test_relacao_nominal(channel, choice, ratio):
    assert choice.ratio(channel) == pytest.approx(ratio)


def test_sensor_errado_ou_fora_da_faixa():
    with pytest.raises(ValueError, match="não serve"):
        SensorChoice("sct013_1v", {"rated_a": 30}).ratio("va")
    with pytest.raises(ValueError, match="fora da faixa"):
        SensorChoice("ct_burden", {"turns": 2000, "burden_ohm": 0}).ratio("ia")
    with pytest.raises(ValueError, match="desconhecido"):
        SensorChoice("xyz", {}).ratio("va")
    with pytest.raises(ValueError, match="polarização"):
        sensor_channels({"va": SensorChoice("v_ratio", {"ratio": 100}, bias_v=5.0)}, NOMINAL)


def test_polarizacao_vira_zero_e_escala_vira_grandeza():
    channels = sensor_channels({"va": SensorChoice("zmpt101b", {"line_v": 127, "pin_v": 0.9}),
                                "ia": SensorChoice("sct013_1v", {"rated_a": 30})}, NOMINAL)
    va, ia = channels["va"], channels["ia"]
    assert va["gain"] * 32768 + va["offset"] == pytest.approx(0, abs=0.01)  # VCC/2 no pino = 0 V
    one_volt = 65535 / VREF  # +1 V no pino acima da polarização
    assert va["gain"] * (32768 + one_volt) + va["offset"] == pytest.approx(127 / 0.9, rel=1e-3)
    # Corrente: DADP em 1,65 V e DADM no GND dão 49152 contagens no binário deslocado.
    assert ia["gain"] * 49152 + ia["offset"] == pytest.approx(0, abs=1e-6)
    assert ia["gain"] * (49152 + 32768 / VREF) + ia["offset"] == pytest.approx(30, rel=1e-6)


def test_escolha_vai_e_volta_em_json():
    choice = SensorChoice("ct_burden", {"turns": 1000, "burden_ohm": 100}, 1.6)
    assert SensorChoice.from_dict(choice.to_dict()) == choice


@pytest.fixture
def window(app, tmp_path):
    from PySide6.QtCore import QSettings
    from prisma.ui.main_window import MainWindow

    widget = MainWindow()
    widget.timer.stop()
    widget.settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    yield widget
    widget.close()


def _summary(v_amp_counts: float, i_amp_counts: float, n: int = 2000, fs: float = 1995.487) -> MeterSummary:
    t = np.arange(n) / fs
    angle = 2 * np.pi * 60 * t
    rows = [np.round(32768 + v_amp_counts * np.sin(angle - k * 2.0944)).astype(np.int64) for k in range(3)]
    rows += [np.round(49152 + i_amp_counts * np.sin(angle - k * 2.0944)).astype(np.int64) for k in range(3)]
    return MeterSummary(1, fs, n, ("va", "vb", "vc", "ia", "ib", "ic"),
                        tuple(int(r.sum()) for r in rows), tuple(int((r * r).sum()) for r in rows),
                        tuple(int((rows[p] * rows[p + 3]).sum()) for p in range(3)), 59, round(58 / 60 * fs * 256))


def test_janela_aplica_perfis_e_mostra_volts_e_amperes(window, tmp_path):
    window._set_calibration(Calibration({"ia": {"gain": I_PIN, "offset": 0.0, "delay_us": -40.0}}, "fase"))
    choices = {ch: SensorChoice("zmpt101b", {"line_v": 127, "pin_v": 0.9}) for ch in ("va", "vb", "vc")}
    choices.update({ch: SensorChoice("sct013_1v", {"rated_a": 30}) for ch in ("ia", "ib", "ic")})
    window.configure_sensors(choices, filename=str(tmp_path / "sensores.json"))
    cal = window.calibration
    assert cal.name.startswith("Sensores nominais") and not cal.pin_volts
    assert cal.channels["ia"]["delay_us"] == -40.0  # atraso calibrado preservado
    assert (tmp_path / "sensores.json").exists()
    # 0,9 V RMS no pino → 127 V; 0,1 V RMS diferencial → 3 A.
    window.raw_counts = True
    window._on_summary(_summary(0.9 * math.sqrt(2) / V_PIN, 0.1 * math.sqrt(2) / I_PIN))
    point = window.stats.trend[-1]
    assert point.voltage[0] == pytest.approx(127, rel=2e-3)
    assert point.current[2] == pytest.approx(3, rel=2e-3)
    saved = window.settings.value("sensors")
    assert "zmpt101b" in saved and "sct013_1v" in saved


def test_usa_a_reta_do_adc_quando_existe(window, tmp_path):
    adc = Calibration({ch: {"gain": 5.1e-5, "offset": -0.002} for ch in ("va", "vb", "vc")}, "ADC", pin_volts=True)
    window._set_calibration(adc)
    window.configure_sensors({"va": SensorChoice("v_ratio", {"ratio": 100})}, filename=str(tmp_path / "s.json"))
    va, vb = window.calibration.channels["va"], window.calibration.channels["vb"]
    assert va["gain"] == pytest.approx(100 * 5.1e-5)
    assert va["offset"] == pytest.approx(100 * (-0.002 - 1.65))
    assert vb == {"gain": 5.1e-5, "offset": -0.002}  # sem sensor: continua em volts no pino


def test_dialogo_mostra_relacao_e_devolve_escolhas(app):
    from prisma.ui.sensor_dialog import SensorDialog
    dialog = SensorDialog(None, ("va", "ia"), {"ia": SensorChoice("ct_burden", {"turns": 2000, "burden_ohm": 33})})
    try:
        assert dialog.rows["ia"]["ratio"].text() == "60.61 A/V"
        assert dialog.rows["va"]["ratio"].text() == "volts no pino"
        combo = dialog.rows["va"]["combo"]
        combo.setCurrentIndex(combo.findData("zmpt101b"))
        assert dialog.rows["va"]["ratio"].text() == "141.1 V/V"
        choices = dialog.choices()
        assert set(choices) == {"va", "ia"} and choices["va"].params == {"line_v": 127.0, "pin_v": 0.9}
        assert "trimpot" in dialog.note.text()
    finally:
        dialog.close()
