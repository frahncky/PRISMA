"""Thread isolada para telemetria serial: não modifica firmware."""
import threading
from PySide6.QtCore import QThread, Signal
from .protocol import parse_sample

class SerialReader(QThread):
    connected = Signal()
    sample_received = Signal(object)
    message = Signal(str)
    disconnected = Signal()

    def __init__(self, port: str, baudrate: int = 115200, parent=None) -> None:
        super().__init__(parent)
        self.port = port
        self.baudrate = baudrate
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
                while not self._stop.is_set():
                    line = handle.readline()
                    if not line:
                        continue
                    try:
                        sample = parse_sample(line)
                    except (ValueError, UnicodeDecodeError, KeyError) as exc:
                        invalid_count += 1
                        if invalid_count <= 5:
                            self.message.emit(f"Linha ignorada: {exc}")
                        continue
                    self.sample_received.emit(sample)
        except Exception as exc:
            self.message.emit(f"Erro de comunicação em {self.port}: {exc}")
        finally:
            self.disconnected.emit()
