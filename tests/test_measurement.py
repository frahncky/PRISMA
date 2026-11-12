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
