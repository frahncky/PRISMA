"""Protocolo serial do PRISMA v1 (uma linha JSON por amostra)."""
from dataclasses import dataclass
import json
import math

@dataclass(frozen=True)
class Sample:
    t: float
    va: float
    vb: float
    vc: float
    ia: float | None = None
    ib: float | None = None
    ic: float | None = None


@dataclass(frozen=True)
class HardwareStatus:
    leds: dict[str, bool]
    gpio: dict[str, bool]
    adc: dict[str, float]
    lcd: list[str]


def parse_message(line: bytes | str) -> Sample | HardwareStatus:
    payload = json.loads(line)
    if not isinstance(payload, dict) or payload.get("type") != "status":
        return parse_sample(line)
    digital = []
    for group in ("leds", "gpio"):
        data = payload.get(group, {})
        if (not isinstance(data, dict) or len(data) > 64
                or any(not isinstance(key, str) or len(key) > 40 or not isinstance(value, bool)
                       for key, value in data.items())):
            raise ValueError(f"Grupo {group} inválido")
        digital.append(data)
    adc = payload.get("adc", {})
    if not isinstance(adc, dict) or len(adc) > 64 or any(len(key) > 40 for key in adc):
        raise ValueError("Grupo ADC inválido")
    lcd = payload.get("lcd", [])
    if not isinstance(lcd, list) or len(lcd) > 4 or any(not isinstance(row, str) or len(row) > 80 for row in lcd):
        raise ValueError("LCD inválido")
    return HardwareStatus(*digital, {key: _number(value, key) for key, value in adc.items()}, lcd)

def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"Campo '{field}' deve ser numérico")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"Campo '{field}' excede a faixa numérica") from exc
    if not math.isfinite(result):
        raise ValueError(f"Campo '{field}' não pode ser infinito ou NaN")
    return result

def parse_sample(line: bytes | str) -> Sample:
    """Lê uma linha JSON, exigindo type=sample e campos t,va,vb,vc."""
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    payload = json.loads(line)
    if not isinstance(payload, dict) or payload.get("type") != "sample":
        raise ValueError("Mensagem não é uma amostra PRISMA (type=sample)")
    fields = {name: _number(payload[name], name) for name in ("t", "va", "vb", "vc")}
    if any(name in payload for name in ("ia", "ib", "ic")):
        fields.update({name: _number(payload[name], name) for name in ("ia", "ib", "ic")})
    return Sample(**fields)
