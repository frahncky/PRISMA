"""Calibração em duas etapas: ADC (contagens → volts no pino) e sensores (multímetro)."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from prisma.core.calibration import Calibration, fit_adc
from prisma.core.protocol import Sample, SampleBlock

FS = 1995.487
GAIN = 3.28 / 65535   # ADC "real" desta placa simulada: fundo de escala 3,28 V
OFFSET = -0.004


def _volts_to_counts(volts):
    return (np.asarray(volts) - OFFSET) / GAIN


def _dc_block(seq, volts):
    counts = float(_volts_to_counts(volts))
    rng = np.random.default_rng(seq)
    samples = tuple(Sample(i / FS, *(counts + rng.normal(0, 3) for _ in range(3))) for i in range(500))
    return SampleBlock(seq, FS, ("ad4", "ad5", "ad6"), samples)


def _sine_block(seq, amplitude_v=1.0, bias_v=1.6):
    t = np.arange(500) / FS
    rows = [_volts_to_counts(bias_v + amplitude_v * np.sin(2 * np.pi * 60 * t + k * 2.0944)) for k in range(3)]
    return SampleBlock(seq, FS, ("ad4", "ad5", "ad6"),
                       tuple(Sample(float(t[i]), *(float(r[i]) for r in rows)) for i in range(500)))


@pytest.fixture
def window(app, tmp_path):
    from PySide6.QtCore import QSettings
    from prisma.ui.main_window import MainWindow

    widget = MainWindow()
    widget.timer.stop()
    widget.settings = QSettings(str(tmp_path / "prisma-test.ini"), QSettings.Format.IniFormat)
    yield widget
    widget.close()


def test_reta_do_adc_com_tres_pontos():
    points = [(float(_volts_to_counts(v)), v) for v in (0.3, 1.6, 3.0)]
    fit = fit_adc(points)
    assert fit.gain == pytest.approx(GAIN, rel=1e-9)
    assert fit.offset == pytest.approx(OFFSET, abs=1e-9)
    assert fit.max_error_v < 1e-9 and fit.points == 3
    bent = points[:2] + [(points[2][0], 3.01)]  # 10 mV fora da reta no topo
    assert fit_adc(bent).max_error_v > 0.003


@pytest.mark.parametrize("points, message", [
    ([(1000.0, 0.05)], "ao menos 2"),
    ([(30000.0, 1.5), (30500.0, 1.53)], "muito próximos"),
    ([(5000.0, 3.0), (60000.0, 0.3)], "subir junto"),
])
def test_reta_do_adc_recusa_pontos_ruins(points, message):
    with pytest.raises(ValueError, match=message):
        fit_adc(points)


def test_perfil_marca_volts_no_pino(tmp_path):
    cal = Calibration({"va": {"gain": GAIN, "offset": OFFSET}}, "ADC", pin_volts=True)
    cal.save(tmp_path / "adc.json")
    assert json.loads((tmp_path / "adc.json").read_text(encoding="utf-8"))["pin_volts"] is True
    loaded = Calibration.load(tmp_path / "adc.json")
    assert loaded.pin_volts and loaded.channels == cal.channels
    assert "pin_volts" not in Calibration({"va": {"gain": 2.0, "offset": 0.0}}).to_dict()
    with pytest.raises(ValueError, match="pin_volts"):
        Calibration.from_dict({"version": 1, "name": "x", "channels": {}, "pin_volts": "sim"})


def test_rajada_guarda_media_e_saturacao(window):
    window._on_block(_dc_block(1, 1.6))
    mean, noise, saturated = window.last_block_stats["va"]
    assert mean == pytest.approx(_volts_to_counts(1.6), abs=1.0) and 1 < noise < 6 and not saturated
    assert window.block_count == 1 and window.block_names == ("ad4", "ad5", "ad6")
    top = SampleBlock(2, FS, ("ad4", "ad5", "ad6"), tuple(Sample(i / FS, 65535.0, 100.0, 0.0) for i in range(50)))
    window._on_block(top)
    assert window.last_block_stats["va"][2] and not window.last_block_stats["vb"][2] and window.last_block_stats["vc"][2]


def test_etapa_1_adc_e_etapa_2_multimetro(window, tmp_path):
    points = {ch: [(float(_volts_to_counts(v)), v) for v in (0.3, 1.6, 3.0)] for ch in ("va", "vb")}
    window._on_block(_sine_block(0))
    window.calibrate_adc(points, str(tmp_path / "adc.json"))
    saved = Calibration.load(tmp_path / "adc.json")
    assert saved.pin_volts
    assert saved.channels["va"]["gain"] == pytest.approx(GAIN) and saved.channels["va"]["offset"] == pytest.approx(OFFSET)
    assert saved.channels["vc"]["gain"] == pytest.approx(3.3 / 65535)  # sem pontos: escala nominal
    assert "volts no pino" in window.calibration_label.text()
    assert json.loads(window.settings.value("calibration"))["pin_volts"] is True

    for seq in range(1, 4):
        window._on_block(_sine_block(seq))
    window._draw_signals()
    assert window._pin_volts()
    assert window.last_analysis[0].rms["A"] == pytest.approx(1 / np.sqrt(2), rel=2e-3)  # 1 V de pico real
    assert window.wave.getAxis("left").labelText == "Tensão no pino ADC"

    # Etapa 2: com o sensor, 0,707 V no pino correspondem a 127 V na rede.
    window.calibrate_from_reference({"va": 127.0, "vb": 0.0, "vc": 0.0}, str(tmp_path / "rede.json"))
    final = Calibration.load(tmp_path / "rede.json")
    assert not final.pin_volts and not window._pin_volts()
    ratio = 127.0 / (1 / np.sqrt(2))
    assert final.channels["va"]["gain"] == pytest.approx(GAIN * ratio, rel=3e-3)
    assert final.channels["va"]["offset"] == pytest.approx(OFFSET * ratio, rel=3e-3)
    for seq in range(4, 7):
        window._on_block(_sine_block(seq))
    window._draw_signals()
    assert window.last_analysis[0].rms["A"] == pytest.approx(127.0, rel=1e-3)
    window.reset_calibration()
    assert window.settings.value("calibration") is None


def test_multimetro_calibra_correntes(window, tmp_path):
    for _ in range(6):
        window._generate_demo_batch()
    window._draw_signals()
    window.calibrate_from_reference({"va": 0.0, "vb": 0.0, "vc": 0.0, "ib": 10.0}, str(tmp_path / "i.json"))
    assert Calibration.load(tmp_path / "i.json").channels["ib"]["gain"] == pytest.approx(2.0, rel=0.01)
    window.buffer.clear()
    for _ in range(6):
        window._generate_demo_batch()
    window._draw_signals()
    assert window.last_analysis[0].current_rms["B"] == pytest.approx(10.0, rel=0.01)
    assert window.last_analysis[0].current_rms["A"] == pytest.approx(5.0, rel=0.01)


def test_assistente_registra_um_ponto_por_rajada(app):
    from prisma.ui.adc_calibration import AdcCalibrationDialog

    state = {"count": 0, "stats": {}}
    dialog = AdcCalibrationDialog(None, lambda: (state["count"], state["stats"]), ("ad4", "ad5", "ad6"))
    assert not dialog.record_button.isEnabled() and not dialog.ok_button.isEnabled()

    def block(volts, saturated=False):
        state["count"] += 1
        state["stats"] = {ch: (float(_volts_to_counts(volts)), 2.5, saturated) for ch in ("va", "vb", "vc")}
        dialog.refresh()

    block(0.3)
    dialog.spins["va"].setValue(0.3)
    assert dialog.spins["vc"].value() == pytest.approx(0.3)  # mesma tensão nos três
    dialog.use["vc"].setChecked(False)
    assert dialog.record_point()
    assert not dialog.record_point()  # mesma rajada não vira dois pontos
    block(3.0)
    dialog.spins["va"].setValue(3.0)
    assert dialog.record_point()
    assert dialog.ok_button.isEnabled() and "µV/contagem" in dialog.fit_label.text()
    assert len(dialog.points["va"]) == 2 and not dialog.points["vc"]
    block(3.3, saturated=True)
    assert not dialog.record_point() and "saturado" in dialog.status.text()
    dialog.remove_last()
    assert len(dialog.points["va"]) == len(dialog.points["vb"]) == 1 and not dialog.ok_button.isEnabled()
    assert dialog.table.rowCount() == 1 and dialog.record_button.isEnabled()
    assert dialog.table.item(0, 1).text().startswith("0,300 V") and dialog.table.item(0, 3).text() == "—"
    dialog.close()
