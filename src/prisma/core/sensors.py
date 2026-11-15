"""Perfis de sensor: escala nominal de cada canal a partir do módulo ligado na DEMOEM.

Com os módulos de saída polarizada em VCC/2 (docs/ligacoes-hardware-demoem.md, 4.5),
o valor físico de um canal é

    valor = relação × (tensão no pino − polarização)

onde a tensão no pino vem da contagem do ADC (escala nominal ou etapa 1 da
calibração) e a relação vem do sensor: TC com resistor de carga, SCT-013 com saída
de 1 V, transformador com divisor ou uma relação medida. Isso dá V e A
aproximados antes da calibração fina com multímetro (etapa 2), que continua sendo
o que vale para medição.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable

VOLTAGE_CHANNELS = ("va", "vb", "vc")
CURRENT_CHANNELS = ("ia", "ib", "ic")
DEFAULT_BIAS_V = 1.65  # VCC/2 com módulo alimentado em 3,3 V


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    default: float
    unit: str
    minimum: float = 1e-6
    maximum: float = 1e6


@dataclass(frozen=True)
class SensorModel:
    key: str
    label: str
    kind: str  # "voltage" ou "current"
    params: tuple[Param, ...]
    ratio: Callable[[dict[str, float]], float]  # grandeza física por volt no pino
    note: str


SENSORS: tuple[SensorModel, ...] = (
    SensorModel(
        "vt_divider", "Transformador + divisor", "voltage",
        (Param("primary_v", "Primário", 127.0, "V"), Param("secondary_v", "Secundário", 9.0, "V"),
         Param("r_top_kohm", "Resistor de cima", 100.0, "kΩ"), Param("r_bottom_kohm", "Resistor de baixo", 10.0, "kΩ")),
        lambda p: p["primary_v"] / p["secondary_v"] * (p["r_top_kohm"] + p["r_bottom_kohm"]) / p["r_bottom_kohm"],
        "Fonte AC-AC de tomada e divisor até o pino. A relação nominal do transformador muda com a carga: "
        "confira com multímetro."),
    SensorModel(
        "zmpt101b", "ZMPT101B (trimpot)", "voltage",
        (Param("line_v", "Tensão da rede", 127.0, "V RMS"), Param("pin_v", "Saída no pino", 0.9, "V RMS")),
        lambda p: p["line_v"] / p["pin_v"],
        "O ganho depende do trimpot: com a rede ligada, leia o RMS da saída no PRISMA (volts no pino) "
        "e a tensão da rede no multímetro."),
    SensorModel(
        "v_ratio", "Relação de tensão manual", "voltage",
        (Param("ratio", "Volts da rede por volt no pino", 100.0, "V/V"),),
        lambda p: p["ratio"], "Relação já conhecida do circuito de entrada."),
    SensorModel(
        "sct013_1v", "SCT-013 com saída de 1 V", "current",
        (Param("rated_a", "Corrente nominal", 30.0, "A"),),
        lambda p: p["rated_a"] / 1.0,
        "Modelos SCT-013-005 a 100 com resistor interno: 1 V RMS na corrente nominal."),
    SensorModel(
        "ct_burden", "TC + resistor de carga", "current",
        (Param("turns", "Relação de espiras", 2000.0, ":1"), Param("burden_ohm", "Resistor de carga", 33.0, "Ω")),
        lambda p: p["turns"] / p["burden_ohm"],
        "Ex.: SCT-013-000 (2000:1) ou ZMCT103C (1000:1) com o resistor de carga da placa de interface."),
    SensorModel(
        "i_ratio", "Relação de corrente manual", "current",
        (Param("ratio", "Ampères por volt no pino", 30.0, "A/V"),),
        lambda p: p["ratio"], "Relação já conhecida (ex.: amplificador com ganho ajustado)."),
)
BY_KEY = {sensor.key: sensor for sensor in SENSORS}


def sensors_for(channel: str) -> tuple[SensorModel, ...]:
    kind = "current" if channel in CURRENT_CHANNELS else "voltage"
    return tuple(s for s in SENSORS if s.kind == kind)


@dataclass(frozen=True)
class SensorChoice:
    """Sensor de um canal, com os parâmetros e a polarização no pino (V)."""
    sensor: str
    params: dict[str, float]
    bias_v: float = DEFAULT_BIAS_V

    def ratio(self, channel: str) -> float:
        model = BY_KEY.get(self.sensor)
        if model is None:
            raise ValueError(f"Sensor desconhecido: {self.sensor}")
        if model.kind != ("current" if channel in CURRENT_CHANNELS else "voltage"):
            raise ValueError(f"{model.label} não serve para o canal {channel}")
        values = {p.key: float(self.params.get(p.key, p.default)) for p in model.params}
        for param in model.params:
            value = values[param.key]
            if not math.isfinite(value) or not param.minimum <= value <= param.maximum:
                raise ValueError(f"{channel}: {param.label} fora da faixa ({value:g} {param.unit})")
        ratio = model.ratio(values)
        if not math.isfinite(ratio) or ratio <= 0:
            raise ValueError(f"{channel}: relação inválida")
        return ratio

    def to_dict(self) -> dict:
        return {"sensor": self.sensor, "params": dict(self.params), "bias_v": self.bias_v}

    @classmethod
    def from_dict(cls, payload: dict) -> "SensorChoice":
        return cls(str(payload["sensor"]), {k: float(v) for k, v in dict(payload.get("params", {})).items()},
                   float(payload.get("bias_v", DEFAULT_BIAS_V)))


def sensor_channels(choices: dict[str, SensorChoice], pin: dict[str, tuple[float, float]]) -> dict[str, dict]:
    """Coeficientes de calibração (contagem → grandeza física) dos canais escolhidos.

    ``pin[canal] = (g, o)``: volts no pino = g × contagem + o (correntes: tensão
    diferencial DADP − DADM). Resultado: ganho = relação × g e
    offset = relação × (o − polarização), que já centra a forma de onda em zero.
    """
    channels = {}
    for channel, choice in choices.items():
        if channel not in pin:
            raise ValueError(f"Canal desconhecido: {channel}")
        if not math.isfinite(choice.bias_v) or not 0 <= choice.bias_v <= 3.3:
            raise ValueError(f"{channel}: polarização deve ficar entre 0 e 3,3 V")
        ratio = choice.ratio(channel)
        g, o = pin[channel]
        channels[channel] = {"gain": ratio * g, "offset": ratio * (o - choice.bias_v)}
    return channels
