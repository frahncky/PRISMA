"""Medições digitais básicas: RMS, fasores e espectro de harmônicas."""
from collections import deque
from dataclasses import dataclass
import numpy as np
from .protocol import Sample

@dataclass(frozen=True)
class Measurement:
    rms: dict[str, float]
    phasors: dict[str, complex]
    harmonic_percent: list[float]

class SignalBuffer:
    def __init__(self, maxlen: int = 4000) -> None:
        self._samples: deque[Sample] = deque(maxlen=maxlen)

    def clear(self) -> None:
        self._samples.clear()

    def add(self, sample: Sample) -> None:
        if self._samples and sample.t <= self._samples[-1].t:
            raise ValueError("O tempo das amostras deve ser estritamente crescente")
        self._samples.append(sample)

    def arrays(self, duration_s: float = 0.25) -> tuple[np.ndarray, np.ndarray]:
        if not self._samples:
            return np.array([]), np.empty((0, 3))
        data = list(self._samples)
        latest = data[-1].t
        recent = [s for s in data if s.t >= latest - duration_s]
        return (
            np.array([s.t for s in recent], dtype=float),
            np.array([[s.va, s.vb, s.vc] for s in recent], dtype=float),
        )

def analyze(t: np.ndarray, values: np.ndarray, fundamental_hz: float = 60.0,
            max_harmonic: int = 15) -> Measurement:
    """Estimativas digitais, limitadas às harmônicas abaixo de Nyquist.

    O maior intervalo entre amostras define um limite conservador para
    aquisições com pequenos desvios de temporização.
    """
    if t.ndim != 1 or t.size < 12 or values.shape != (len(t), 3):
        raise ValueError("A análise requer no mínimo 12 amostras trifásicas")
    if not np.isfinite(fundamental_hz) or fundamental_hz <= 0 or max_harmonic <= 0:
        raise ValueError("Frequência e número de harmônicas devem ser positivos")
    if not np.all(np.isfinite(t)) or not np.all(np.isfinite(values)):
        raise ValueError("Amostras devem conter apenas valores finitos")
    intervals = np.diff(t)
    if np.any(intervals <= 0):
        raise ValueError("Amostras fora da ordem temporal")
    nyquist_hz = 0.5 / float(intervals.max())
    if fundamental_hz >= nyquist_hz:
        raise ValueError("Taxa de amostragem insuficiente para a frequência fundamental")
    centered = values - values.mean(axis=0)
    rms = np.sqrt(np.mean(centered**2, axis=0))
    kernel = np.exp(-2j * np.pi * fundamental_hz * t)
    phasor_vals = (2.0 / len(t)) * (kernel @ centered) / np.sqrt(2)
    amps = []
    for harmonic in range(1, max_harmonic + 1):
        if harmonic * fundamental_hz >= nyquist_hz:
            break
        k = np.exp(-2j * np.pi * fundamental_hz * harmonic * t)
        amps.append(float(np.abs(2.0 / len(t) * (k @ centered[:, 0]))))
    base = max(amps[0], 1e-12)
    return Measurement(
        rms={key: float(val) for key, val in zip(("A", "B", "C"), rms)},
        phasors={key: complex(val) for key, val in zip(("A", "B", "C"), phasor_vals)},
        harmonic_percent=[100 * a / base for a in amps],
    )
