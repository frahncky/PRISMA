"""Perfis explícitos de calibração: ganho, offset e atraso (fase) por canal."""
from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path

import numpy as np

from .protocol import Sample

CHANNELS = ("va", "vb", "vc", "ia", "ib", "ic")


class Calibration:
    def __init__(self, channels: dict | None = None, name: str = "Identidade", pin_volts: bool = False) -> None:
        self.name = name
        self.channels = channels or {}
        # True: os coeficientes só levam contagens a volts no pino do ADC (falta a
        # escala dos sensores); False: o resultado já é a grandeza real (V, A).
        self.pin_volts = bool(pin_volts)
        if set(self.channels) - set(CHANNELS):
            raise ValueError("Canal de calibração desconhecido")
        for settings in self.channels.values():
            if (not isinstance(settings, dict) or not {"gain", "offset"} <= set(settings)
                    or set(settings) - {"gain", "offset", "delay_us"}):
                raise ValueError("Cada canal requer gain e offset (delay_us opcional)")
            for value in settings.values():
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError("Ganho e offset devem ser finitos")
            if settings["gain"] <= 0:
                raise ValueError("Ganho deve ser positivo")
            if abs(settings.get("delay_us", 0.0)) > 100_000:
                raise ValueError("Atraso deve ficar entre -100000 e 100000 µs")

    @classmethod
    def load(cls, path: Path) -> "Calibration":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    @classmethod
    def from_dict(cls, payload) -> "Calibration":
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError("Perfil de calibração requer version=1")
        if not isinstance(payload.get("name"), str) or not isinstance(payload.get("channels"), dict):
            raise ValueError("Perfil requer name e channels")
        if not isinstance(payload.get("pin_volts", False), bool):
            raise ValueError("pin_volts deve ser true ou false")
        return cls(payload["channels"], payload["name"], payload.get("pin_volts", False))

    def apply(self, sample: Sample) -> Sample:
        fields = asdict(sample)
        adjusted = {key: fields[key] * cfg["gain"] + cfg["offset"]
                    for key, cfg in self.channels.items() if fields[key] is not None}
        if any(not math.isfinite(value) for value in adjusted.values()):
            raise ValueError("Calibração produziu valor não finito")
        return replace(sample, **adjusted)

    def delays_s(self) -> dict[str, float]:
        return {ch: cfg["delay_us"] * 1e-6 for ch, cfg in self.channels.items() if cfg.get("delay_us")}

    def align(self, t: np.ndarray, values: np.ndarray,
              currents: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray | None]:
        """Compensa o atraso de cada canal por interpolação linear.

        ``delay_us`` positivo significa que o canal chega atrasado (TC, filtro,
        conversão sequencial): o valor verdadeiro em t é o lido em t + atraso.
        As bordas da janela repetem o primeiro/último valor.
        """
        delays = self.delays_s()
        if not delays or t.size < 2:
            return values, currents
        values = values.copy()
        currents = None if currents is None else currents.copy()
        for index, channel in enumerate(CHANNELS):
            target = values if index < 3 else currents
            if channel in delays and target is not None:
                column = index % 3
                target[:, column] = np.interp(t + delays[channel], t, target[:, column])
        return values, currents

    def to_dict(self) -> dict:
        payload = {"version": 1, "name": self.name, "channels": self.channels}
        if self.pin_volts:
            payload["pin_volts"] = True
        return payload

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class AdcFit:
    """Reta contagem → volts no pino de um canal do ADC."""
    gain: float          # V por contagem
    offset: float        # V em contagem zero
    max_error_v: float   # maior desvio dos pontos em relação à reta
    points: int


ADC_MIN_SPAN_COUNTS = 2000  # pontos mais próximos que isso não definem a inclinação


def fit_adc(points: list[tuple[float, float]]) -> AdcFit:
    """Mínimos quadrados de ``volts = contagem × gain + offset``.

    ``points`` são pares (contagem média, tensão medida no pino). Dois pontos
    bastam para a reta; com três ou mais, ``max_error_v`` mostra a não linearidade.
    """
    if len(points) < 2:
        raise ValueError("Registre ao menos 2 pontos (recomendado 3: perto de 0 V, do meio e do topo)")
    counts = np.array([p[0] for p in points], dtype=float)
    volts = np.array([p[1] for p in points], dtype=float)
    if not (np.all(np.isfinite(counts)) and np.all(np.isfinite(volts))):
        raise ValueError("Pontos de calibração inválidos")
    if np.ptp(counts) < ADC_MIN_SPAN_COUNTS:
        raise ValueError("Pontos muito próximos: espalhe pela faixa (ex.: 0,3 V, 1,6 V e 3,0 V)")
    gain, offset = np.polyfit(counts, volts, 1)
    if gain <= 0:
        raise ValueError("A tensão medida deve subir junto com a contagem; confira canal e ligações")
    error = float(np.max(np.abs(volts - (counts * gain + offset))))
    return AdcFit(float(gain), float(offset), error, len(points))


def gains_from_reference(base_gain: dict[str, float], shown_rms: dict[str, float],
                         measured_rms: dict[str, float]) -> dict[str, float]:
    """Ganho novo por canal a partir de uma leitura de referência (multímetro).

    O RMS exibido resulta de ``entrada × base_gain``; para que passe a valer
    ``measured_rms``, o ganho vira ``base_gain × medido / exibido``. Canais com
    medida zero ficam de fora.
    """
    result = {}
    for channel, measured in measured_rms.items():
        if measured <= 0:
            continue
        shown = shown_rms.get(channel)
        if shown is None or not math.isfinite(shown) or shown <= 0:
            raise ValueError(f"Sem leitura válida no canal {channel} para calibrar")
        result[channel] = base_gain[channel] * measured / shown
    if not result:
        raise ValueError("Informe ao menos uma tensão medida maior que zero")
    return result


def delays_from_resistive_load(voltage_phasors: dict[str, complex], current_phasors: dict[str, complex],
                               frequency_hz: float) -> dict[str, float]:
    """Atraso (µs) de cada corrente medido com carga resistiva (FP = 1).

    Com carga puramente resistiva V e I deveriam estar em fase; a diferença
    angular da fundamental vira o ``delay_us`` do canal de corrente.
    """
    if not math.isfinite(frequency_hz) or frequency_hz <= 0:
        raise ValueError("Frequência inválida para calcular atraso")
    result = {}
    for phase, channel in zip("ABC", ("ia", "ib", "ic")):
        v, i = voltage_phasors.get(phase), current_phasors.get(phase)
        if v is None or i is None or abs(v) < 1e-12 or abs(i) < 1e-12:
            continue
        angle = math.atan2((v * i.conjugate()).imag, (v * i.conjugate()).real)
        if abs(angle) > math.radians(30):
            raise ValueError(f"Fase {phase}: defasagem de {math.degrees(angle):.1f}° não parece carga resistiva")
        result[channel] = angle / (2 * math.pi * frequency_hz) * 1e6
    if not result:
        raise ValueError("Sem tensão e corrente válidas para calcular atraso")
    return result
