"""Processamento AC: frequência, fasores, harmônicas e potência por fase."""
from collections import deque
from dataclasses import dataclass, field
import math
import numpy as np
from .protocol import Sample

PHASES = ("A", "B", "C")


@dataclass(frozen=True)
class Power:
    active_w: float
    reactive_fundamental_var: float
    apparent_va: float
    power_factor: float | None


@dataclass(frozen=True)
class Measurement:
    rms: dict[str, float]
    phasors: dict[str, complex]
    harmonic_percent: list[float]
    frequency_hz: float = 60.0
    thd_percent: float | None = None
    current_rms: dict[str, float] = field(default_factory=dict)
    power: dict[str, Power] = field(default_factory=dict)
    window: str = "rectangular"


class SignalBuffer:
    def __init__(self, maxlen: int = 4000) -> None:
        self._samples: deque[Sample] = deque(maxlen=maxlen)

    def clear(self) -> None:
        self._samples.clear()

    def add(self, sample: Sample) -> None:
        if not all(math.isfinite(value) for value in (sample.t, sample.va, sample.vb, sample.vc)):
            raise ValueError("Amostras devem ser finitas")
        currents = (sample.ia, sample.ib, sample.ic)
        if any(value is not None for value in currents) and not all(
                value is not None and math.isfinite(value) for value in currents):
            raise ValueError("Correntes devem conter os três canais finitos")
        if self._samples and sample.t <= self._samples[-1].t:
            raise ValueError("O tempo das amostras deve ser estritamente crescente")
        self._samples.append(sample)

    def _recent(self, duration_s: float) -> list[Sample]:
        if not self._samples:
            return []
        latest = self._samples[-1].t
        return [s for s in self._samples if s.t >= latest - duration_s]

    def arrays(self, duration_s: float = 0.25) -> tuple[np.ndarray, np.ndarray]:
        data = self._recent(duration_s)
        return (np.array([s.t for s in data], dtype=float),
                np.array([[s.va, s.vb, s.vc] for s in data], dtype=float).reshape(-1, 3))

    def currents(self, duration_s: float = 0.25) -> np.ndarray | None:
        data = self._recent(duration_s)
        if not data or any(s.ia is None for s in data):
            return None
        return np.array([[s.ia, s.ib, s.ic] for s in data], dtype=float)


def estimate_frequency(t: np.ndarray, signal: np.ndarray) -> float:
    """Mediana dos períodos entre cruzamentos ascendentes interpolados.

    Requer pelo menos três cruzamentos; rejeita sinal constante e temporização
    inválida. A faixa suportada pela estimativa automática é 40–70 Hz.
    """
    if t.ndim != 1 or signal.shape != t.shape or len(t) < 12:
        raise ValueError("A estimação requer ao menos 12 amostras")
    if not np.all(np.isfinite(t)) or not np.all(np.isfinite(signal)) or np.any(np.diff(t) <= 0):
        raise ValueError("Dados inválidos para estimação de frequência")
    y = signal - np.mean(signal)
    if np.ptp(y) < 1e-9:
        raise ValueError("Sinal insuficiente para estimar frequência")
    indices = np.flatnonzero((y[:-1] <= 0) & (y[1:] > 0))
    if len(indices) < 3:
        raise ValueError("Janela insuficiente para estimar frequência")
    crossings = t[indices] - y[indices] * (t[indices + 1] - t[indices]) / (y[indices + 1] - y[indices])
    periods = np.diff(crossings)
    frequency = float(1 / np.median(periods))
    if not 40 <= frequency <= 70 or np.std(periods) / np.mean(periods) > 0.05:
        raise ValueError("Frequência fora de 40–70 Hz ou sinal instável")
    return frequency


def analyze(t: np.ndarray, values: np.ndarray, fundamental_hz: float | None = 60.0,
            max_harmonic: int = 15, *, currents: np.ndarray | None = None,
            window: str = "rectangular") -> Measurement:
    """Ajuste harmônico por mínimos quadrados, com intercepto e janela opcional.

    Harmônicas estritamente abaixo de Nyquist (maior intervalo temporal).
    RMS e P são calculados no domínio do tempo, sem componente contínua.
    Q é a potência reativa da fundamental; S e FP incluem distorção AC.
    """
    if t.ndim != 1 or t.size < 12 or values.shape != (len(t), 3):
        raise ValueError("A análise requer no mínimo 12 amostras trifásicas")
    if not np.all(np.isfinite(t)) or not np.all(np.isfinite(values)):
        raise ValueError("Amostras devem conter apenas valores finitos")
    intervals = np.diff(t)
    if np.any(intervals <= 0):
        raise ValueError("Amostras fora da ordem temporal")
    if fundamental_hz is None:
        fundamental_hz = estimate_frequency(t, values[:, 0])
    if (not np.isfinite(fundamental_hz) or fundamental_hz <= 0
            or isinstance(max_harmonic, bool) or not isinstance(max_harmonic, int) or max_harmonic <= 0):
        raise ValueError("Frequência e número inteiro de harmônicas devem ser positivos")
    if window not in ("rectangular", "hann"):
        raise ValueError("Janela deve ser rectangular ou hann")
    nyquist_hz = 0.5 / float(intervals.max())
    if fundamental_hz >= nyquist_hz:
        raise ValueError("Taxa de amostragem insuficiente para a frequência fundamental")
    orders = [h for h in range(1, min(max_harmonic, (len(t) - 2) // 2) + 1)
              if h * fundamental_hz < nyquist_hz]
    # Tempo relativo reduz perda de precisão com timestamps absolutos grandes.
    relative_t = t - t[0]
    columns = [np.ones(len(t))]
    for h in orders:
        angle = 2 * np.pi * fundamental_hz * h * relative_t
        columns.extend((np.cos(angle), np.sin(angle)))
    design = np.column_stack(columns)
    weights = np.sqrt(np.hanning(len(t))) if window == "hann" else np.ones(len(t))
    weighted = design * weights[:, None]
    inputs = values
    if currents is not None:
        if currents.shape != values.shape or not np.all(np.isfinite(currents)):
            raise ValueError("Correntes devem ser finitas e sincronizadas com as tensões")
        inputs = np.column_stack((values, currents))
    coefficients, _, rank, _ = np.linalg.lstsq(weighted, inputs * weights[:, None], rcond=None)
    if rank != design.shape[1]:
        raise ValueError("Amostragem não permite separar as harmônicas")
    rotation = np.exp(-2j * np.pi * fundamental_hz * t[0])
    ph = (coefficients[1] - 1j * coefficients[2]) / np.sqrt(2) * rotation
    centered = values - values.mean(axis=0)
    rms = np.sqrt(np.mean(centered**2, axis=0))
    amps = np.hypot(coefficients[1::2, 0], coefficients[2::2, 0])
    valid_base = amps[0] > 1e-9
    percentages = [float(100 * a / amps[0]) for a in amps] if valid_base else [0.0] * len(amps)
    thd = float(np.linalg.norm(percentages[1:])) if valid_base and len(amps) > 1 else None
    current_rms, power = {}, {}
    if currents is not None:
        centered_i = currents - currents.mean(axis=0)
        irms = np.sqrt(np.mean(centered_i**2, axis=0))
        active = np.mean(centered * centered_i, axis=0)
        for i, phase in enumerate(PHASES):
            apparent = float(rms[i] * irms[i])
            current_rms[phase] = float(irms[i])
            power[phase] = Power(float(active[i]), float((ph[i] * ph[i + 3].conjugate()).imag),
                                 apparent, float(np.clip(active[i] / apparent, -1, 1)) if apparent > 1e-12 else None)
    return Measurement(dict(zip(PHASES, map(float, rms))), dict(zip(PHASES, map(complex, ph[:3]))),
                       percentages, float(fundamental_hz), thd, current_rms, power, window)
