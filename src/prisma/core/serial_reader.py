"""Thread isolada para telemetria (serial ou gateway na rede); comandos à placa só quando a interface pede."""
import queue
import threading
import time
from PySide6.QtCore import QThread, Signal
from .link import NETWORK_IDLE_S, link_label, network_address, open_link
from .protocol import CommandReply, HardwareStatus, MeterSummary, Sample, SampleBlock, StreamDecoder, parse_message

RECONNECT_S = 2.0


class SerialReader(QThread):
    connected = Signal()
    sample_received = Signal(object)
    status_received = Signal(object)
    block_received = Signal(object)
    summary_received = Signal(object)
    reply_received = Signal(object)
    message = Signal(str)
    disconnected = Signal()
    reconnecting = Signal()  # rede: a sessão caiu e a thread vai tentar de novo

    def __init__(self, port: str, baudrate: int = 115200, parent=None, parser=parse_message) -> None:
        super().__init__(parent)
        self.port = port
        self.baudrate = baudrate
        self.parser = parser
        self.network = network_address(port) is not None
        self.persistent = self.network  # serial também reconecta quando True (modo quiosque)
        self.idle_timeout = NETWORK_IDLE_S
        self.reconnect_delay = RECONNECT_S
        self._stop = threading.Event()
        self._outgoing: queue.SimpleQueue[bytes] = queue.SimpleQueue()

    def stop(self) -> None:
        self._stop.set()

    def send(self, data: bytes) -> None:
        """Enfileira bytes para a placa; a thread da serial escreve entre leituras."""
        self._outgoing.put(bytes(data))

    def _flush_outgoing(self, handle) -> None:
        while True:
            try:
                data = self._outgoing.get_nowait()
            except queue.Empty:
                return
            handle.write(data)

    def run(self) -> None:
        """Serial: uma sessão (ou reconecta, com ``persistent``). Rede: reconecta sozinho até ``stop``."""
        label = link_label(self.port)
        try:
            while not self._stop.is_set():
                try:
                    self._session(label)
                except Exception as exc:
                    self.message.emit(f"Erro de comunicação em {label}: {exc}")
                if not self.persistent or self._stop.is_set():
                    break
                self.reconnecting.emit()
                self.message.emit(f"Reconectando a {label} em {self.reconnect_delay:g} s…")
                self._stop.wait(self.reconnect_delay)
        finally:
            self.disconnected.emit()

    def _session(self, label: str) -> None:
        with open_link(self.port, self.baudrate) as handle:
            self.connected.emit()
            self.message.emit(f"Gateway {label} conectado." if self.network
                              else f"Porta {self.port} aberta a {self.baudrate} baud.")
            invalid_count = 0
            decoder = StreamDecoder(self.parser)
            last_data = time.monotonic()
            while not self._stop.is_set():
                self._flush_outgoing(handle)
                chunk = handle.read()
                if not chunk:
                    if self.network and time.monotonic() - last_data > self.idle_timeout:
                        raise ConnectionError(f"nenhum dado há {self.idle_timeout:g} s")
                    continue
                last_data = time.monotonic()
                for item in decoder.feed(chunk):
                    if isinstance(item, Exception):
                        invalid_count += 1
                        if invalid_count <= 5:
                            text = str(item)
                            self.message.emit(text if text.startswith("Linha ignorada") else f"Linha ignorada: {text}")
                    elif isinstance(item, Sample):
                        self.sample_received.emit(item)
                    elif isinstance(item, SampleBlock):
                        self.block_received.emit(item)
                    elif isinstance(item, MeterSummary):
                        self.summary_received.emit(item)
                    elif isinstance(item, CommandReply):
                        self.reply_received.emit(item)
                    elif isinstance(item, HardwareStatus):
                        self.status_received.emit(item)
                    else:
                        invalid_count += 1
                        if invalid_count <= 5:
                            self.message.emit("Linha ignorada: Plugin retornou um tipo de mensagem inválido")
