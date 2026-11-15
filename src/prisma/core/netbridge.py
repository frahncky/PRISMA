"""Ponte serial → TCP no PC (scripts/ponte_tcp.py), com as mesmas regras do gateway ESP32-S3.

- Os bytes da placa vão intactos para o cliente TCP (um por vez; um novo substitui o anterior).
- Do cliente para a placa só passam comandos ``0x10`` inteiros, com CRC válido e
  código da lista ``REMOTE_COMMANDS`` (identificar, rajadas, autocalibração).
  Pela rede ninguém leva a placa ao bootloader nem grava flash: isso fica com a
  USB (acesso físico) e com o ``POST /api/ota`` do gateway, que exige token.
- ``demo_stream`` gera resumos ``0x02`` e rajadas ``0x01`` de 6 canais como os da
  DEMOEM, para testar o app pela rede sem placa.
"""
from __future__ import annotations

import math
import socket
import struct
import threading
import time
from typing import Callable, Iterator

from .protocol import (
    FRAME_COMMAND, MeterSummary, SYNC, crc16_ccitt, encode_burst, encode_summary,
)

REMOTE_COMMANDS = frozenset({0x01, 0x02, 0x03})  # INFO, RAJADA, ADC_CAL (prisma_command.h)
MAX_COMMAND_PAYLOAD = 16


class CommandGate:
    """Recorta comandos completos do fluxo vindo da rede e devolve só os permitidos."""

    def __init__(self, allowed=REMOTE_COMMANDS) -> None:
        self.allowed = frozenset(allowed)
        self._buffer = bytearray()
        self.accepted = 0
        self.rejected = 0

    def feed(self, data: bytes) -> list[bytes]:
        buf = self._buffer
        buf.extend(data)
        out: list[bytes] = []
        while True:
            start = buf.find(SYNC)
            if start < 0:
                del buf[:-1 if buf.endswith(SYNC[:1]) else len(buf)]
                return out
            del buf[:start]
            if len(buf) < 5:
                return out
            frame_type, length = struct.unpack_from("<BH", buf, 2)
            if frame_type != FRAME_COMMAND or not 2 <= length <= MAX_COMMAND_PAYLOAD:
                self.rejected += 1
                del buf[:2]
                continue
            total = 5 + length + 2
            if len(buf) < total:
                return out
            frame = bytes(buf[:total])
            del buf[:total]
            (crc,) = struct.unpack_from("<H", frame, 5 + length)
            if crc != crc16_ccitt(frame[2:5 + length]) or frame[6] not in self.allowed:
                self.rejected += 1
                continue
            self.accepted += 1
            out.append(frame)


def demo_window(seq: int, fs_hz: float = 1995.487, freq: float = 60.0, cycles: int = 60) -> tuple[MeterSummary, list]:
    """Uma janela de ciclos inteiros (somas do resumo) e as primeiras 500 amostras (rajada)."""
    n = round(cycles * fs_hz / freq)
    drift = 0.004 * math.sin(seq / 7)  # variação lenta para os gráficos de tendência
    rows = []
    for t in range(n):
        angle = 2 * math.pi * freq * t / fs_hz
        v = [round(32768 + 20000 * (1 + drift) * math.sin(angle - k * 2 * math.pi / 3)) for k in range(3)]
        i = [round(32768 + 6000 * (1 - drift) * math.sin(angle - k * 2 * math.pi / 3 - math.radians(25)))
             for k in range(3)]
        rows.append(tuple(v + i))
    sums = tuple(sum(r[c] for r in rows) for c in range(6))
    sumsq = tuple(sum(r[c] ** 2 for r in rows) for c in range(6))
    sumvi = tuple(sum(r[p] * r[p + 3] for r in rows) for p in range(3))
    period_q8 = round((cycles - 1) * fs_hz / freq * 256)
    summary = MeterSummary(seq, fs_hz, n, ("va", "vb", "vc", "ia", "ib", "ic"), sums, sumsq, sumvi,
                           cycles, period_q8)
    return summary, rows[:500]


def demo_stream(start_seq: int = 1) -> Iterator[bytes]:
    """Quadros de uma DEMOEM de 6 canais: um resumo e uma rajada por janela (~1 s)."""
    seq = start_seq
    yield b'{"type":"status","source":"DEMOEM","message":"DEMONSTRACAO PELA REDE"}\r\n'
    while True:
        summary, rows = demo_window(seq)
        yield encode_summary(summary) + encode_burst(seq, summary.fs_hz, rows)
        seq += 1


class BridgeServer:
    """Servidor TCP de um cliente por vez entre uma fonte de bytes e a rede.

    ``read_source()`` devolve bytes da placa (ou b"" sem dados); ``write_source(data)``
    recebe os comandos permitidos. ``serve_forever`` roda até ``stop``.
    """

    def __init__(self, host: str, port: int, read_source: Callable[[], bytes],
                 write_source: Callable[[bytes], None] | None, log: Callable[[str], None] = print) -> None:
        self.server = socket.create_server((host, port))
        self.server.settimeout(0.2)
        self.address = self.server.getsockname()[:2]
        self.read_source = read_source
        self.write_source = write_source
        self.log = log
        self.gate = CommandGate()
        self._stop = threading.Event()
        self._client: socket.socket | None = None
        self.sent_bytes = 0

    def stop(self) -> None:
        self._stop.set()

    def _accept(self) -> None:
        try:
            client, peer = self.server.accept()
        except socket.timeout:
            return
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        client.settimeout(0)
        if self._client is not None:
            self.log("Novo cliente: o anterior foi desconectado.")
            self._client.close()
        self._client = client
        self.gate = CommandGate()
        self.log(f"Cliente {peer[0]}:{peer[1]} conectado.")

    def _drop(self, reason: str) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self.log(f"Cliente desconectado ({reason}).")

    def poll(self) -> None:
        if self._client is None:
            self._accept()
        data = self.read_source()
        if data and self._client is not None:
            try:
                self._client.settimeout(2.0)
                self._client.sendall(data)
                self._client.settimeout(0)
                self.sent_bytes += len(data)
            except OSError as exc:
                self._drop(str(exc))
        if self._client is None:
            return
        try:
            incoming = self._client.recv(512)
        except (BlockingIOError, socket.timeout):
            return
        except OSError as exc:
            self._drop(str(exc))
            return
        if not incoming:
            self._drop("fechou")
            return
        for frame in self.gate.feed(incoming):
            if self.write_source is not None:
                self.write_source(frame)

    def serve_forever(self) -> None:
        try:
            while not self._stop.is_set():
                self.poll()
        finally:
            self._drop("ponte encerrada")
            self.server.close()


def paced(stream: Iterator[bytes], period_s: float = 1.0) -> Callable[[], bytes]:
    """Fonte de bytes que libera um item de ``stream`` por ``period_s``."""
    state = {"next": time.monotonic()}

    def read() -> bytes:
        now = time.monotonic()
        if now < state["next"]:
            time.sleep(min(0.02, state["next"] - now))
            return b""
        state["next"] += period_s
        return next(stream)
    return read
