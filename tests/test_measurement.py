import numpy as np
import pytest
from prisma.core.measurement import SignalBuffer, analyze
from prisma.core.protocol import Sample

def test_rms_e_fasores_trifasicos():
    t = np.arange(0, 0.5, 1 / 3000)
    r = 127.0
    v = np.sqrt(2) * r
    x = np.column_stack([
        v * np.sin(2 * np.pi * 60 * t),
        v * np.sin(2 * np.pi * 60 * t - 2 * np.pi / 3),
        v * np.sin(2 * np.pi * 60 * t + 2 * np.pi / 3),
    ])
    m = analyze(t, x)
    assert all(abs(m.rms[k] - r) < 1 for k in ("A", "B", "C"))
    assert abs(m.phasors["A"]) == pytest.approx(r, abs=1)
    assert m.harmonic_percent[0] == pytest.approx(100.0)
    assert m.harmonic_percent[2] < 1.0

def test_buffer_descarta_timestamps_repetidos():
    b = SignalBuffer()
    b.add(Sample(0.0, 0.0, 0.0, 0.0))
    with pytest.raises(ValueError):
        b.add(Sample(0.0, 1.0, 1.0, 1.0))


def three_phase_signal(t):
    return np.column_stack([
        np.sqrt(2) * 127 * np.sin(2 * np.pi * 60 * t + phase)
        for phase in (0, -2 * np.pi / 3, 2 * np.pi / 3)
    ])


def test_harmonicas_limitadas_por_nyquist():
    t = np.arange(400) / 800
    result = analyze(t, three_phase_signal(t))
    # h7 = 420 Hz não pode ser medida a 800 amostras/s.
    assert len(result.harmonic_percent) == 6
    assert max(result.harmonic_percent[1:]) < 0.01


def test_demo_mede_terceira_harmonica_sem_alias():
    t = np.arange(600) / 2400
    values = three_phase_signal(t)
    values[:, 0] += np.sqrt(2) * 127 * 0.025 * np.sin(2 * np.pi * 180 * t)
    result = analyze(t, values)
    assert len(result.harmonic_percent) == 15
    assert result.harmonic_percent[2] == pytest.approx(2.5, abs=0.01)
    assert max(result.harmonic_percent[3:]) < 0.01


def test_taxa_permite_apenas_fundamental():
    t = np.arange(100) / 200
    result = analyze(t, three_phase_signal(t))
    assert result.harmonic_percent == pytest.approx([100])


def test_rejeita_fundamental_no_limite_de_nyquist():
    t = np.arange(60) / 120
    with pytest.raises(ValueError, match="Taxa de amostragem insuficiente"):
        analyze(t, three_phase_signal(t))


@pytest.mark.parametrize("invalid", [np.nan, np.inf, -np.inf])
def test_rejeita_amostras_nao_finitas(invalid):
    t = np.arange(120) / 2400
    values = three_phase_signal(t)
    values[3, 0] = invalid
    with pytest.raises(ValueError, match="valores finitos"):
        analyze(t, values)
    values = three_phase_signal(t)
    t[3] = invalid
    with pytest.raises(ValueError, match="valores finitos"):
        analyze(t, values)


def test_ganho_de_calibracao_por_referencia(tmp_path):
    import pytest
    from prisma.core.calibration import Calibration, gains_from_reference

    gains = gains_from_reference({"va": 3.3 / 65535, "vb": 1.0}, {"va": 0.75, "vb": 100.0}, {"va": 127.0, "vb": 0.0})
    assert gains == {"va": pytest.approx(3.3 / 65535 * 127.0 / 0.75)}
    with pytest.raises(ValueError):
        gains_from_reference({"va": 1.0}, {"va": 0.0}, {"va": 10.0})
    with pytest.raises(ValueError):
        gains_from_reference({"va": 1.0}, {"va": 1.0}, {"va": 0.0})
    cal = Calibration({"va": {"gain": 2.0, "offset": 0.0}}, "Bancada")
    cal.save(tmp_path / "c.json")
    assert Calibration.load(tmp_path / "c.json").channels == cal.channels
