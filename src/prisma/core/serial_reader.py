"""Thread isolada para telemetria serial; comandos à placa só quando a interface pede."""
import queue
import threading
from PySide6.QtCore import QThread, Signal
from .protocol import CommandReply, HardwareStatus, MeterSummary, Sample, SampleBlock, StreamDecoder, parse_message

class SerialReader(QThread):
    connected = Signal()
    sample_received = Signal(object)
    status_received = Signal(object)
    block_received = Signal(object)
    summary_received = Signal(object)
    reply_received = Signal(object)
    message = Signal(str)
    disconnected = Signal()

    def __init__(self, port: str, baudrate: int = 115200, parent=None, parser=parse_message) -> None:
        super().__init__(parent)
        self.port = port
        self.baudrate = baudrate
        self.parser = parser
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
        try:
            import serial
            with serial.Serial(self.port, self.baudrate, timeout=0.2) as handle:
                self.connected.emit()
                self.message.emit(f"Porta {self.port} aberta a {self.baudrate} baud.")
                invalid_count = 0
                decoder = StreamDecoder(self.parser)
                while not self._stop.is_set():
                    self._flush_outgoing(handle)
                    chunk = handle.read(max(1, min(handle.in_waiting, 4096)))
                    if not chunk:
                        continue
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
        except Exception as exc:
            self.message.emit(f"Erro de comunicação em {self.port}: {exc}")
        finally:
            self.disconnected.emit()
