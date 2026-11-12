"""Perfis de placas declarativos; carregar um perfil não executa código."""
from dataclasses import dataclass
import json
from importlib.metadata import entry_points
from pathlib import Path
import re
from serial.tools import list_ports
from .protocol import parse_message


@dataclass(frozen=True)
class DeviceProfile:
    name: str
    baudrate: int = 115200
    protocol: str = "prisma-json-v1"

    @classmethod
    def load(cls, path: Path) -> "DeviceProfile":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("Perfil requer version=1")
        name, baud = data.get("name"), data.get("baudrate", 115200)
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError("Perfil requer nome")
        if isinstance(baud, bool) or not isinstance(baud, int) or not 1200 <= baud <= 3000000:
            raise ValueError("Baudrate inválido")
        protocol = data.get("protocol", "prisma-json-v1")
        if not isinstance(protocol, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,79}", protocol):
            raise ValueError("Identificador de protocolo inválido")
        return cls(name, baud, protocol)


def load_protocol(name: str):
    if name == "prisma-json-v1":
        return parse_message
    matches = [point for point in entry_points(group="prisma.protocols") if point.name == name]
    if len(matches) != 1:
        raise ValueError(f"Protocolo {name}: instale exatamente um plugin com esse identificador")
    parser = matches[0].load()
    if not callable(parser):
        raise ValueError("Plugin não exporta um parser chamável")
    return parser


def serial_inventory() -> list[dict]:
    return [{"port": p.device, "description": p.description,
             "vid": f"{p.vid:04X}" if p.vid is not None else None,
             "pid": f"{p.pid:04X}" if p.pid is not None else None,
             "serial_number": p.serial_number, "manufacturer": p.manufacturer,
             "location": p.location} for p in list_ports.comports()]
