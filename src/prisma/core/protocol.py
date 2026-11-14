"""Protocolo serial do PRISMA v1 (uma linha JSON por amostra)."""
from dataclasses import dataclass, field
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
    message: str = ""
    diagnostics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class SampleBlock:
    """Bloco adquirido em rajada com taxa fixa (valores brutos do ADC, em contagens)."""
    seq: int
    fs_hz: float
    channels: tuple[str, ...]
    samples: tuple[Sample, ...]
    timeout_mask: int = 0


# Separação temporal entre blocos: cada rajada vira um trecho próprio, sem
# emendar com a anterior (o intervalo real de transmissão não é medido).
BURST_SPACING_S = 10.0


def parse_burst(payload: dict) -> SampleBlock:
    seq, n = payload.get("seq"), payload.get("n")
    fs_mhz = payload.get("fs_mhz")
    channels = payload.get("ch")
    data = payload.get("data")
    if (not isinstance(seq, int) or isinstance(seq, bool) or seq < 0
            or not isinstance(n, int) or isinstance(n, bool) or not 2 <= n <= 4096
            or not isinstance(fs_mhz, int) or isinstance(fs_mhz, bool) or not 1_000 <= fs_mhz <= 1_000_000_000):
        raise ValueError("Rajada requer seq, n (2..4096) e fs_mhz válidos")
    if (not isinstance(channels, list) or len(channels) != 3
            or any(not isinstance(c, str) or not c or len(c) > 16 for c in channels)):
        raise ValueError("Rajada requer exatamente três canais nomeados")
    if not isinstance(data, str) or len(data) != n * 12:
        raise ValueError("Tamanho de data incompatível com n")
    try:
        values = [int(data[i:i + 4], 16) for i in range(0, len(data), 4)]
    except ValueError as exc:
        raise ValueError("data deve conter apenas dígitos hexadecimais") from exc
    fs = fs_mhz / 1000.0
    t0 = seq * BURST_SPACING_S
    samples = tuple(Sample(t0 + i / fs, float(values[3 * i]), float(values[3 * i + 1]), float(values[3 * i + 2]))
                    for i in range(n))
    mask = payload.get("adc_timeout_mask", 0)
    return SampleBlock(seq, fs, tuple(channels), samples, int(_number(mask, "adc_timeout_mask")))


def parse_message(line: bytes | str) -> Sample | HardwareStatus | SampleBlock:
    payload = json.loads(line)
    if isinstance(payload, dict) and payload.get("type") == "burst":
        return parse_burst(payload)
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
    adc_values = {key: _number(value, key) for key, value in adc.items()}
    signed = payload.get("adc_signed", {})
    if not isinstance(signed, dict) or len(signed) > 64 or any(len(key) > 40 for key in signed):
        raise ValueError("Grupo adc_signed inválido")
    adc_values.update({f"{key}_signed": _number(value, key) for key, value in signed.items()})
    message = payload.get("message", "")
    if not isinstance(message, str) or len(message) > 120:
        raise ValueError("Mensagem de status inválida")
    # Campos numéricos de diagnóstico no nível raiz (ex.: adc_timeout_mask, adc_cal_fail_mask).
    diagnostics = {key: _number(value, key) for key, value in payload.items()
                   if key.endswith("_mask") and len(key) <= 40}
    return HardwareStatus(*digital, adc_values, lcd, message, diagnostics)

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
