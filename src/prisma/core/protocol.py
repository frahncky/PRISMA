"""Protocolo serial do PRISMA: JSON por linha (v1) e quadros binários com CRC (v2)."""
from dataclasses import dataclass, field
import json
import math
import struct

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
    wire_bytes: int | None = None  # tamanho na serial (None: estimar como JSON hex)


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


# ---------------------------------------------------------------------------
# Protocolo binário v2
#
#   A5 5A | tipo u8 | len u16 LE | payload[len] | CRC16 u16 LE
#
# CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) sobre tipo, len e payload.
# Rajada (tipo 0x01): seq u32, fs_mhz u32, n u16, máscara de canais u8,
# flags u8, depois n × k palavras u16 LE intercaladas por amostra.
#   máscara: bit0 va, bit1 vb, bit2 vc, bit3 ia, bit4 ib, bit5 ic (0x07 ou 0x3F)
#   flags: bits 0..2 timeout ADC1..3; bit 7 = valores int16 com sinal
# O JSON do firmware é ASCII (sem byte 0xA5), então os dois formatos convivem
# na serial. Texto não ASCII (ex.: "¥Z" = C2 A5 5A) seria confundido com quadro.
# ---------------------------------------------------------------------------
SYNC = b"\xa5\x5a"
FRAME_BURST = 0x01
BURST_HEADER = struct.Struct("<IIHBB")
FRAME_CHANNELS = ("va", "vb", "vc", "ia", "ib", "ic")
MAX_FRAME_PAYLOAD = BURST_HEADER.size + 4096 * 6 * 2
FLAG_SIGNED = 0x80


def crc16_ccitt(data: bytes, crc: int = 0xFFFF) -> int:
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def encode_frame(frame_type: int, payload: bytes) -> bytes:
    """Monta um quadro v2 (usado em testes e simuladores)."""
    body = struct.pack("<BH", frame_type, len(payload)) + payload
    return SYNC + body + struct.pack("<H", crc16_ccitt(body))


def encode_burst(seq: int, fs_hz: float, rows: list[tuple[int, ...]], *,
                 timeout_mask: int = 0, signed: bool = False) -> bytes:
    k = len(rows[0])
    mask = {3: 0x07, 6: 0x3F}[k]
    flags = (timeout_mask & 0x07) | (FLAG_SIGNED if signed else 0)
    fmt = "<" + ("h" if signed else "H") * (k * len(rows))
    payload = BURST_HEADER.pack(seq, round(fs_hz * 1000), len(rows), mask, flags)
    return encode_frame(FRAME_BURST, payload + struct.pack(fmt, *(v for row in rows for v in row)))


def parse_burst_frame(payload: bytes) -> SampleBlock:
    if len(payload) < BURST_HEADER.size:
        raise ValueError("Rajada binária truncada")
    seq, fs_mhz, n, mask, flags = BURST_HEADER.unpack_from(payload)
    if not 2 <= n <= 4096 or not 1_000 <= fs_mhz <= 1_000_000_000:
        raise ValueError("Rajada binária requer n (2..4096) e fs_mhz válidos")
    if mask not in (0x07, 0x3F):
        raise ValueError("Máscara de canais deve ser 0x07 (tensões) ou 0x3F (tensões e correntes)")
    k = 3 if mask == 0x07 else 6
    if len(payload) != BURST_HEADER.size + 2 * n * k:
        raise ValueError("Tamanho da rajada binária incompatível com n e canais")
    values = struct.unpack_from("<" + ("h" if flags & FLAG_SIGNED else "H") * (n * k), payload, BURST_HEADER.size)
    fs = fs_mhz / 1000.0
    t0 = seq * BURST_SPACING_S
    samples = tuple(Sample(t0 + i / fs, *map(float, values[i * k:(i + 1) * k])) for i in range(n))
    return SampleBlock(seq, fs, FRAME_CHANNELS[:k], samples, flags & 0x07,
                       wire_bytes=len(payload) + 7)


FRAME_SUMMARY = 0x02
SUMMARY_HEADER = struct.Struct("<IIIBBHI")
FLAG_NO_SYNC = 0x08
FLAG_OVERRUN = 0x10


@dataclass(frozen=True)
class MeterSummary:
    """Somas de uma janela contínua da placa (contagens brutas, ciclos inteiros de A).

    O firmware não faz conta em ponto flutuante: manda Σx, Σx² e Σv·i, e aqui
    saem média, RMS AC e potência com inteiros exatos (ver prisma_meter.h).
    """
    seq: int
    fs_hz: float
    n: int
    channels: tuple[str, ...]
    sums: tuple[int, ...]
    sumsq: tuple[int, ...]
    sumvi: tuple[int, ...] | None
    cycles: int
    period_q8: int
    flags: int = 0

    @property
    def duration_s(self) -> float:
        return self.n / self.fs_hz

    @property
    def timeout_mask(self) -> int:
        return self.flags & 0x07

    @property
    def synced(self) -> bool:
        return not self.flags & FLAG_NO_SYNC and self.cycles >= 2 and self.period_q8 > 0

    @property
    def overrun(self) -> bool:
        return bool(self.flags & FLAG_OVERRUN)

    @property
    def frequency_hz(self) -> float | None:
        """Ciclos entre o 1º cruzamento interno e o de fechamento (interpolados, mesmo limiar)."""
        return (self.cycles - 1) * self.fs_hz * 256 / self.period_q8 if self.synced else None

    def mean(self, index: int) -> float:
        return self.sums[index] / self.n

    def ac_rms(self, index: int) -> float:
        """RMS sem a componente contínua, em contagens."""
        n, total = self.n, self.sums[index]
        return math.sqrt(max(n * self.sumsq[index] - total * total, 0)) / n

    def active(self, phase: int) -> float | None:
        """Média de (v − v̄)(i − ī) da fase, em contagens², ou None sem correntes."""
        if self.sumvi is None:
            return None
        n = self.n
        return (n * self.sumvi[phase] - self.sums[phase] * self.sums[phase + 3]) / (n * n)


def parse_summary_frame(payload: bytes) -> MeterSummary:
    if len(payload) < SUMMARY_HEADER.size:
        raise ValueError("Resumo binário truncado")
    seq, fs_mhz, n, mask, flags, cycles, period_q8 = SUMMARY_HEADER.unpack_from(payload)
    if mask not in (0x07, 0x3F):
        raise ValueError("Máscara de canais deve ser 0x07 (tensões) ou 0x3F (tensões e correntes)")
    if n < 2 or not 1_000 <= fs_mhz <= 1_000_000_000:
        raise ValueError("Resumo binário requer n ≥ 2 e fs_mhz válido")
    k = 3 if mask == 0x07 else 6
    if len(payload) != SUMMARY_HEADER.size + 12 * k + (24 if k == 6 else 0):
        raise ValueError("Tamanho do resumo binário incompatível com os canais")
    pairs = struct.unpack_from("<" + "IQ" * k, payload, SUMMARY_HEADER.size)
    sumvi = (struct.unpack_from("<3Q", payload, SUMMARY_HEADER.size + 12 * k) if k == 6 else None)
    return MeterSummary(seq, fs_mhz / 1000.0, n, FRAME_CHANNELS[:k], pairs[0::2], pairs[1::2],
                        sumvi, cycles, period_q8, flags)


def encode_summary(summary: MeterSummary) -> bytes:
    """Quadro tipo 0x02 igual ao do firmware (testes e simuladores)."""
    k = len(summary.channels)
    payload = SUMMARY_HEADER.pack(summary.seq, round(summary.fs_hz * 1000), summary.n, {3: 0x07, 6: 0x3F}[k],
                                  summary.flags, summary.cycles, summary.period_q8)
    payload += b"".join(struct.pack("<IQ", s, q) for s, q in zip(summary.sums, summary.sumsq))
    if summary.sumvi is not None:
        payload += struct.pack("<3Q", *summary.sumvi)
    return encode_frame(FRAME_SUMMARY, payload)


FRAME_PARSERS = {FRAME_BURST: parse_burst_frame, FRAME_SUMMARY: parse_summary_frame}


class StreamDecoder:
    """Separa linhas JSON e quadros binários v2 de um fluxo serial fragmentado.

    ``feed`` devolve, em ordem, mensagens decodificadas ou exceções (ValueError)
    descrevendo o que foi descartado. Depois de um quadro inválido o
    decodificador pula o quadro (CRC) ou descarta até a próxima linha ou ``A5 5A``.
    """

    def __init__(self, line_parser=parse_message, max_line: int = 16384) -> None:
        self.line_parser = line_parser
        self.max_line = max_line
        self._buffer = bytearray()
        self._discarding = False
        self.frames = 0
        self.crc_errors = 0

    def feed(self, data: bytes) -> list:
        buf = self._buffer
        buf.extend(data)
        out: list = []
        while buf:
            sync = buf.find(SYNC)
            newline = buf.find(b"\n")
            if sync == 0:
                self._discarding = False
                if len(buf) < 5:
                    break
                frame_type, length = struct.unpack_from("<BH", buf, 2)
                if length > MAX_FRAME_PAYLOAD or frame_type not in FRAME_PARSERS:
                    out.append(ValueError(f"Quadro binário inválido (tipo {frame_type}, {length} bytes)"))
                    del buf[:2]
                    self._discarding = True  # até a próxima linha ou sincronismo
                    continue
                total = 5 + length + 2
                if len(buf) < total:
                    break
                body = bytes(buf[2:5 + length])
                (crc,) = struct.unpack_from("<H", buf, 5 + length)
                if crc != crc16_ccitt(body):
                    self.crc_errors += 1
                    out.append(ValueError("Quadro binário com CRC inválido"))
                    # O comprimento declarado é o palpite mais provável: pular o quadro
                    # inteiro evita interpretar o restante binário como texto.
                    del buf[:total]
                    continue
                del buf[:total]
                try:
                    out.append(FRAME_PARSERS[frame_type](body[3:]))
                    self.frames += 1
                except ValueError as exc:
                    out.append(exc)
                continue
            if sync > 0 and (newline == -1 or sync < newline):
                junk = bytes(buf[:sync])
                del buf[:sync]
                if not self._discarding and junk.strip():
                    out.append(ValueError(f"{len(junk)} bytes descartados antes de um quadro binário"))
                self._discarding = False
                continue
            if newline == -1:
                if len(buf) > self.max_line:
                    keep = 1 if buf[-1] == SYNC[0] else 0
                    del buf[:len(buf) - keep]
                    if not self._discarding:
                        out.append(ValueError(f"Linha ignorada: excede {self.max_line} bytes"))
                    self._discarding = True
                break
            line = bytes(buf[:newline])
            del buf[:newline + 1]
            if self._discarding:
                self._discarding = False
                continue
            if len(line) > self.max_line:
                out.append(ValueError(f"Linha ignorada: excede {self.max_line} bytes"))
                continue
            if not line.strip():
                continue
            try:
                out.append(self.line_parser(line))
            except (ValueError, UnicodeDecodeError, KeyError) as exc:
                out.append(exc if isinstance(exc, ValueError) else ValueError(str(exc)))
        return out
