"""Atualização de firmware pelo bootloader serial PRISMA (firmware/include/prisma_boot.h).

Fluxo: INFO → ERASE das páginas da imagem → WRITE em blocos de até 128 bytes
→ COMMIT (o bootloader recalcula o CRC-32 e só então grava o descritor) → RUN.
Uma atualização interrompida deixa a placa no bootloader: basta repetir.

As respostas perdidas são tratadas sem regravar às cegas: um WRITE repetido que
volta "destino não apagado" é conferido pelo CRC do próprio bloco, e um COMMIT
repetido que volta erro é conferido pelo INFO (aplicação válida).
"""
from __future__ import annotations

from dataclasses import dataclass
import queue
import struct
import threading
import time
import zlib
from pathlib import Path
from typing import Callable, Protocol

from .protocol import CommandReply, REPLY_STATUS, StreamDecoder, encode_command

CMD_ENTER_BOOT = 0x04  # aplicação (firmware com bootloader): reinicia no bootloader
CMD_BOOT_INFO = 0x20
CMD_BOOT_ERASE = 0x21
CMD_BOOT_WRITE = 0x22
CMD_BOOT_CRC = 0x23
CMD_BOOT_COMMIT = 0x24
CMD_BOOT_RUN = 0x25
REPLY_RANGE, REPLY_FLASH, REPLY_IMAGE = 0x03, 0x04, 0x05
BOOT_STATUS = {**REPLY_STATUS, REPLY_RANGE: "fora da área, desalinhado ou na faixa reservada",
               REPLY_FLASH: "erro de gravação na flash", REPLY_IMAGE: "imagem inválida (CRC)"}
BOOT_INFO = struct.Struct("<BBHIIHBBII")
BOOT_MAX_ARGS = 138  # PRISMA_CMD_MAX_PAYLOAD 140 − id − código


class BootError(RuntimeError):
    pass


@dataclass(frozen=True)
class BootInfo:
    revision: int
    app_valid: bool
    page_size: int
    app_start: int
    app_limit: int        # fim exclusivo da área gravável (o descritor começa aqui)
    max_chunk: int
    flash_error: int
    hole_start: int       # faixa que o bootloader nunca grava (configuração do bloco de flash)
    hole_end: int


def parse_boot_info(data: bytes) -> BootInfo:
    rev, valid, page, start, limit, chunk, err, _, hole_start, hole_end = BOOT_INFO.unpack_from(data)
    return BootInfo(rev, bool(valid), page, start, limit, chunk, err, hole_start, hole_end)


def crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# S-record (o CodeWarrior gera bin/Project.abs.S19)
# ---------------------------------------------------------------------------
def parse_srec(text: str) -> dict[int, int]:
    """Bytes de dados do S19 por endereço; confere checksum e endereços repetidos."""
    memory: dict[int, int] = {}
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if len(line) < 4 or line[0] != "S" or line[1] not in "0123456789":
            raise ValueError(f"Linha {number}: não é um S-record")
        try:
            raw = bytes.fromhex(line[2:])
        except ValueError as exc:
            raise ValueError(f"Linha {number}: hexadecimal inválido") from exc
        if not raw or raw[0] != len(raw) - 1:
            raise ValueError(f"Linha {number}: tamanho não confere")
        if (sum(raw) & 0xFF) != 0xFF:
            raise ValueError(f"Linha {number}: checksum inválido")
        kind = line[1]
        if kind in "123":
            width = {"1": 2, "2": 3, "3": 4}[kind]
            address = int.from_bytes(raw[1:1 + width], "big")
            for offset, value in enumerate(raw[1 + width:-1]):
                if address + offset in memory:
                    raise ValueError(f"Linha {number}: endereço 0x{address + offset:X} repetido")
                memory[address + offset] = value
    if not memory:
        raise ValueError("S19 sem dados")
    return memory


@dataclass(frozen=True)
class FlashImage:
    start: int
    data: bytes           # de start até o último byte usado, alinhado a 4, lacunas em 0xFF

    @property
    def end(self) -> int:
        return self.start + len(self.data)

    @property
    def crc(self) -> int:
        return crc32(self.data)


def build_image(memory: dict[int, int], info: BootInfo) -> FlashImage:
    """Imagem contínua da área da aplicação, recusando o que o bootloader não pode gravar."""
    outside = sorted(a for a in memory if not info.app_start <= a < info.app_limit)
    if outside:
        raise ValueError(f"S19 tem {len(outside)} byte(s) fora da área da aplicação "
                         f"(0x{info.app_start:X}–0x{info.app_limit - 1:X}), ex.: 0x{outside[0]:X}. "
                         "Use o firmware ligado para rodar com o bootloader.")
    end = (max(memory) + 4) & ~3
    data = bytearray(b"\xff" * (end - info.app_start))
    for address, value in memory.items():
        data[address - info.app_start] = value
    hole_words = range(info.hole_start & ~3, (info.hole_end + 3) & ~3)
    used = [a for a in hole_words if info.app_start <= a < end and data[a - info.app_start] != 0xFF]
    if used:
        raise ValueError(f"S19 grava 0x{used[0]:X}, na faixa reservada 0x{info.hole_start:X}–"
                         f"0x{info.hole_end - 1:X} (configuração do bloco de flash)")
    # O CRC do bootloader pula a faixa reservada: na imagem ela fica de fora também.
    return FlashImage(info.app_start, bytes(data))


def image_crc(image: FlashImage, info: BootInfo) -> int:
    """CRC-32 como o bootloader calcula: sem os bytes da faixa reservada."""
    lo = max(info.hole_start, image.start) - image.start
    hi = min(info.hole_end, image.end) - image.start
    if lo >= hi:
        return image.crc
    return crc32(image.data[:lo] + image.data[hi:])


# ---------------------------------------------------------------------------
# Transporte e cliente
# ---------------------------------------------------------------------------
class Transport(Protocol):
    def write(self, data: bytes) -> None: ...
    def read(self, timeout: float) -> bytes: ...


class SerialTransport:
    def __init__(self, port: str, baudrate: int = 115200) -> None:
        import serial
        self.handle = serial.Serial(port, baudrate, timeout=0.05)

    def write(self, data: bytes) -> None:
        self.handle.write(data)

    def read(self, timeout: float) -> bytes:
        self.handle.timeout = timeout
        return self.handle.read(max(1, self.handle.in_waiting))

    def close(self) -> None:
        self.handle.close()


class StreamTransport:
    """Transporte sobre um par de fluxos binários (ex.: processo simulador), com thread de leitura."""

    def __init__(self, reader, writer) -> None:
        self.writer = writer
        self.chunks: queue.Queue[bytes] = queue.Queue()
        self.thread = threading.Thread(target=self._pump, args=(reader,), daemon=True)
        self.thread.start()

    def _pump(self, reader) -> None:
        while True:
            data = reader.read1(4096) if hasattr(reader, "read1") else reader.read(1)
            if not data:
                return
            self.chunks.put(data)

    def write(self, data: bytes) -> None:
        self.writer.write(data)
        self.writer.flush()

    def read(self, timeout: float) -> bytes:
        try:
            return self.chunks.get(timeout=timeout)
        except queue.Empty:
            return b""


class BootClient:
    def __init__(self, transport: Transport, timeout: float = 1.0, retries: int = 4) -> None:
        self.transport = transport
        self.timeout = timeout
        self.retries = retries
        self.decoder = StreamDecoder()
        self._id = 0
        self.resends = 0

    def _exchange(self, code: int, args: bytes, timeout: float) -> CommandReply | None:
        self._id = (self._id + 1) & 0xFF
        command_id = self._id
        self.transport.write(encode_command(command_id, code, args, max_args=BOOT_MAX_ARGS))
        deadline = time.monotonic() + timeout
        while (left := deadline - time.monotonic()) > 0:
            for item in self.decoder.feed(self.transport.read(min(left, 0.1))):
                # Resumos, rajadas e texto da aplicação podem vir misturados: só a resposta casa.
                if isinstance(item, CommandReply) and item.command_id == command_id and item.code == code:
                    return item
        return None

    def request(self, code: int, args: bytes = b"", *, timeout: float | None = None,
                accept=lambda reply: reply.ok) -> CommandReply:
        """Envia e espera a resposta; repete se ela não vier. Devolve a última resposta recebida."""
        reply = None
        for attempt in range(self.retries + 1):
            if attempt:
                self.resends += 1
            reply = self._exchange(code, args, timeout or self.timeout)
            if reply is not None:
                return reply
        raise BootError(f"Sem resposta do bootloader ao comando 0x{code:02X} depois de {self.retries + 1} tentativas")

    def info(self) -> BootInfo:
        reply = self.request(CMD_BOOT_INFO)
        if not reply.ok:
            raise BootError(f"INFO recusado: {BOOT_STATUS.get(reply.status, reply.status)}")
        return parse_boot_info(reply.data)

    def crc(self, address: int, length: int) -> int:
        reply = self.request(CMD_BOOT_CRC, struct.pack("<II", address, length))
        if not reply.ok:
            raise BootError(f"CRC recusado: {BOOT_STATUS.get(reply.status, reply.status)}")
        return struct.unpack("<I", reply.data)[0]

    def _check(self, reply: CommandReply, what: str) -> None:
        if not reply.ok:
            raise BootError(f"{what}: {BOOT_STATUS.get(reply.status, f'estado {reply.status}')}")

    def write_chunk(self, address: int, chunk: bytes) -> None:
        for attempt in range(self.retries + 1):
            reply = self._exchange(CMD_BOOT_WRITE, struct.pack("<I", address) + chunk, self.timeout)
            if reply is None:
                self.resends += 1
                continue
            if reply.status == REPLY_FLASH and attempt and self.crc(address, len(chunk)) == crc32(chunk):
                return  # a primeira tentativa gravou; só a resposta se perdeu
            self._check(reply, f"Gravação em 0x{address:X}")
            return
        raise BootError(f"Sem resposta ao gravar 0x{address:X}")

    def flash(self, image: FlashImage, info: BootInfo | None = None, *, run: bool = True,
              progress: Callable[[str, int, int], None] | None = None) -> BootInfo:
        info = info or self.info()
        report = progress or (lambda *_: None)
        if image.start != info.app_start or image.end > info.app_limit:
            raise BootError("Imagem fora da área do bootloader")
        pages = -(-len(image.data) // info.page_size)
        report("apagando", 0, pages)
        self._check(self.request(CMD_BOOT_ERASE, struct.pack("<IH", info.app_start, pages),
                                 timeout=max(self.timeout, 0.05 * pages)), "Apagamento")
        chunks = []
        step = min(info.max_chunk, 128)
        for offset in range(0, len(image.data), step):
            address = image.start + offset
            end = min(address + step, image.end)
            # Corta o bloco na faixa reservada (palavras inteiras).
            hole_lo, hole_hi = info.hole_start & ~3, (info.hole_end + 3) & ~3
            for lo, hi in ((address, min(end, hole_lo)), (max(address, hole_hi), end)):
                if lo < hi:
                    piece = image.data[lo - image.start:hi - image.start]
                    if piece.strip(b"\xff"):  # página apagada já vale 0xFF
                        chunks.append((lo, piece))
        for index, (address, piece) in enumerate(chunks):
            report("gravando", index, len(chunks))
            self.write_chunk(address, piece)
        report("gravando", len(chunks), len(chunks))
        crc = image_crc(image, info)
        reply = self.request(CMD_BOOT_COMMIT, struct.pack("<II", len(image.data), crc), timeout=max(self.timeout, 2.0))
        if not reply.ok and not (reply.status == REPLY_FLASH and self.info().app_valid):
            computed = struct.unpack("<I", reply.data)[0] if len(reply.data) == 4 else None
            raise BootError(f"Confirmação recusada: {BOOT_STATUS.get(reply.status, reply.status)}"
                            + (f" (placa calculou 0x{computed:08X}, esperado 0x{crc:08X})" if computed is not None else ""))
        final = self.info()
        if not final.app_valid:
            raise BootError("Gravação terminou mas a placa não reconhece a aplicação como válida")
        if run:
            self._check(self.request(CMD_BOOT_RUN), "Partida da aplicação")
        report("pronto", 1, 1)
        return final


def load_image(path: Path, info: BootInfo) -> FlashImage:
    return build_image(parse_srec(Path(path).read_text(encoding="ascii")), info)
