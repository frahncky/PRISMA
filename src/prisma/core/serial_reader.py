"""Thread isolada para telemetria serial: não modifica firmware."""
import threading
from PySide6.QtCore import QThread, Signal
from .protocol import HardwareStatus, Sample, SampleBlock, parse_message

class SerialReader(QThread):
    connected = Signal()
    sample_received = Signal(object)
    status_received = Signal(object)
    block_received = Signal(object)
    message = Signal(str)
    disconnected = Signal()

    def __init__(self, port: str, baudrate: int = 115200, parent=None, parser=parse_message) -> None:
        super().__init__(parent)
        self.port = port
        self.baudrate = baudrate
        self.parser = parser
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        try:
            import serial
            with serial.Serial(self.port, self.baudrate, timeout=0.2) as handle:
                self.connected.emit()
                self.message.emit(f"Porta {self.port} aberta a {self.baudrate} baud (somente leitura).")
                invalid_count = 0
                pending = bytearray()
                discarding = False
                while not self._stop.is_set():
                    chunk = handle.read(max(1, min(handle.in_waiting, 4096)))
                    if not chunk:
                        continue
                    for byte in chunk:
                        if byte == 10:
                            if discarding:
                                discarding = False
                                continue
                            line = bytes(pending)
                            pending.clear()
                            try:
                                sample = self.parser(line)
                                if not isinstance(sample, (Sample, HardwareStatus, SampleBlock)):
                                    raise ValueError("Plugin retornou um tipo de mensagem inválido")
                            except (ValueError, UnicodeDecodeError, KeyError) as exc:
                                invalid_count += 1
                                if invalid_count <= 5:
                                    self.message.emit(f"Linha ignorada: {exc}")
                                continue
                            if isinstance(sample, Sample):
                                self.sample_received.emit(sample)
                            elif isinstance(sample, SampleBlock):
                                self.block_received.emit(sample)
                            else:
                                self.status_received.emit(sample)
                        elif not discarding:
                            pending.append(byte)
                            if len(pending) > 16384:
                                pending.clear()
                                discarding = True
                                invalid_count += 1
                                if invalid_count <= 5:
                                    self.message.emit("Linha ignorada: excede 16384 bytes")
        except Exception as exc:
            self.message.emit(f"Erro de comunicação em {self.port}: {exc}")
        finally:
            self.disconnected.emit()
