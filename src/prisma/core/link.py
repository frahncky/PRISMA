"""Enlace com a placa: porta serial (COMx, /dev/tty…) ou gateway na rede (TCP).

O gateway ESP32-S3 (gateway/esp32s3) e a ponte do PC (scripts/ponte_tcp.py) servem
os mesmos bytes da serial da DEMOEM numa porta TCP. O app usa o mesmo
decodificador nos dois casos; só muda como os bytes chegam.

Endereços de rede aceitos: ``tcp://host:porta``, ``socket://host:porta``,
``host:porta``, um IP ou um nome com ponto (``prisma.local``), com a porta padrão 3333.
"""
from __future__ import annotations

import re
import socket

DEFAULT_TCP_PORT = 3333
NETWORK_IDLE_S = 10.0  # a placa manda um resumo por segundo: 10 s sem nada = enlace morto
_SERIAL_NAME = re.compile(r"^(COM\d+|/dev/.+|\\\\\.\\.+)$", re.IGNORECASE)
_HOST = re.compile(r"^[A-Za-z0-9.\-]+$")


def network_address(text: str | None) -> tuple[str, int] | None:
    """(host, porta) se ``text`` é um endereço de rede; None se é uma porta serial."""
    if not text:
        return None
    value = str(text).strip()
    explicit = False
    for prefix in ("tcp://", "socket://"):
        if value.lower().startswith(prefix):
            value, explicit = value[len(prefix):].rstrip("/"), True
    if not explicit and _SERIAL_NAME.match(value):
        return None
    host, sep, port_text = value.rpartition(":")
    if sep:
        if not port_text.isdigit() or not host:
            raise ValueError(f"Endereço de rede inválido: {text!r} (use host:porta)")
        port = int(port_text)
    elif explicit or "." in value:
        host, port = value, DEFAULT_TCP_PORT
    else:
        return None
    if not _HOST.match(host) or not 0 < port < 65536:
        raise ValueError(f"Endereço de rede inválido: {text!r}")
    return host, port


def network_url(text: str) -> str | None:
    address = network_address(text)
    return None if address is None else f"tcp://{address[0]}:{address[1]}"


def link_label(port: str) -> str:
    address = network_address(port)
    return port if address is None else f"{address[0]}:{address[1]} (rede)"


class SerialLink:
    """Porta serial com leitura do que já chegou (até 4 KiB), como antes."""

    def __init__(self, port: str, baudrate: int) -> None:
        import serial
        self.handle = serial.Serial(port, baudrate, timeout=0.2)

    def __enter__(self):
        self.handle.__enter__()
        return self

    def __exit__(self, *args):
        return self.handle.__exit__(*args)

    def read(self) -> bytes:
        return self.handle.read(max(1, min(self.handle.in_waiting, 4096)))

    def write(self, data: bytes) -> None:
        self.handle.write(data)


class TcpLink:
    """Conexão TCP com o gateway; ``read`` devolve b"" a cada 0,2 s sem dados."""

    def __init__(self, host: str, port: int, connect_timeout: float = 5.0) -> None:
        self.sock = socket.create_connection((host, port), timeout=connect_timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self.sock.settimeout(0.2)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.sock.close()
        return False

    def read(self) -> bytes:
        try:
            data = self.sock.recv(4096)
        except socket.timeout:
            return b""
        if not data:
            raise ConnectionError("o gateway fechou a conexão")
        return data

    def write(self, data: bytes) -> None:
        self.sock.sendall(data)


def open_link(port: str, baudrate: int):
    address = network_address(port)
    return SerialLink(port, baudrate) if address is None else TcpLink(*address)
