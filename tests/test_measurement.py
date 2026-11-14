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


def test_frequencia_automatica_usa_canal_com_sinal_quando_fase_a_zera():
    import numpy as np
    from prisma.core.measurement import analyze

    t = np.arange(500) / 1995.5
    values = np.column_stack([np.zeros_like(t), np.zeros_like(t), 20000 * np.sin(2 * np.pi * 51.9 * t)])
    result = analyze(t, values, fundamental_hz=None)
    assert abs(result.frequency_hz - 51.9) < 0.1
    assert result.rms["A"] == 0 and result.rms["C"] > 10000
    assert result.thd_percent is None


def test_sequence_components_balanced_and_unbalanced():
    import cmath
    from prisma.core.measurement import sequence_components
    a = cmath.rect(1, -2 * cmath.pi / 3)
    seq = sequence_components({"A": 10, "B": 10 * a, "C": 10 * a * a})
    assert abs(seq.positive - 10) < 1e-9 and seq.negative < 1e-9 and seq.zero < 1e-9
    assert seq.unbalance_percent < 1e-9
    seq = sequence_components({"A": 10, "B": 10 * a * a, "C": 10 * a})  # sequência invertida
    assert seq.positive < 1e-9 and abs(seq.negative - 10) < 1e-9
    assert sequence_components({"A": 0, "B": 0, "C": 0}).unbalance_percent is None


def test_line_voltages_balanced_are_sqrt3_phase():
    import cmath
    from prisma.core.measurement import line_voltages
    a = cmath.rect(1, -2 * cmath.pi / 3)
    lines = line_voltages({"A": 127, "B": 127 * a, "C": 127 * a * a})
    for v in lines.values():
        assert abs(abs(v) - 127 * 3 ** 0.5) < 1e-9
    assert abs(cmath.phase(lines["AB"]) - cmath.pi / 6) < 1e-9


def test_phase_rotation():
    import cmath
    from prisma.core.measurement import sequence_components
    a = cmath.rect(1, -2 * cmath.pi / 3)
    assert sequence_components({"A": 1, "B": a, "C": a * a}).rotation == "ABC"
    assert sequence_components({"A": 1, "B": a * a, "C": a}).rotation == "ACB"
    assert sequence_components({"A": 1, "B": 1, "C": 1}).rotation is None


def test_crest_factor_sine_and_flat():
    import numpy as np
    from prisma.core.measurement import crest_factors
    t = np.arange(1000) / 1000
    values = np.column_stack((np.sin(2 * np.pi * 10 * t), np.ones(1000), np.sign(np.sin(2 * np.pi * 10 * t + 0.1))))
    cf = crest_factors(values)
    assert abs(cf[0] - 2 ** 0.5) < 1e-3 and cf[1] is None and abs(cf[2] - 1) < 0.05


def test_report_flags_values_above_prodist_limits(tmp_path):
    import cmath
    from prisma.core.measurement import Measurement
    from prisma.core.reports import write_report
    a = cmath.rect(1, -2 * cmath.pi / 3)
    result = Measurement({"A": 1, "B": 1, "C": 1}, {"A": 1, "B": 0.5 * a, "C": a * a}, [100, 20], 60.0, 20.0)
    path = tmp_path / "r.html"
    write_report(path, result, "teste", "nenhuma", 0, 1)
    assert path.read_text(encoding="utf-8").count("acima do limite") == 2
