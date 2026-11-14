"""Perfis explícitos de calibração linear, em unidades físicas."""
from dataclasses import asdict, replace
import json
import math
from pathlib import Path

from .protocol import Sample

CHANNELS = ("va", "vb", "vc", "ia", "ib", "ic")


class Calibration:
    def __init__(self, channels: dict | None = None, name: str = "Identidade") -> None:
        self.name = name
        self.channels = channels or {}
        if set(self.channels) - set(CHANNELS):
            raise ValueError("Canal de calibração desconhecido")
        for settings in self.channels.values():
            if not isinstance(settings, dict) or set(settings) != {"gain", "offset"}:
                raise ValueError("Cada canal requer gain e offset")
            for value in settings.values():
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError("Ganho e offset devem ser finitos")
            if settings["gain"] <= 0:
                raise ValueError("Ganho deve ser positivo")

    @classmethod
    def load(cls, path: Path) -> "Calibration":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError("Perfil de calibração requer version=1")
        if not isinstance(payload.get("name"), str) or not isinstance(payload.get("channels"), dict):
            raise ValueError("Perfil requer name e channels")
        return cls(payload["channels"], payload["name"])

    def apply(self, sample: Sample) -> Sample:
        fields = asdict(sample)
        adjusted = {key: fields[key] * cfg["gain"] + cfg["offset"]
                    for key, cfg in self.channels.items() if fields[key] is not None}
        if any(not math.isfinite(value) for value in adjusted.values()):
            raise ValueError("Calibração produziu valor não finito")
        return replace(sample, **adjusted)

    def to_dict(self) -> dict:
        return {"version": 1, "name": self.name, "channels": self.channels}

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def gains_from_reference(base_gain: dict[str, float], shown_rms: dict[str, float],
                         measured_rms: dict[str, float]) -> dict[str, float]:
    """Ganho novo por canal a partir de uma leitura de referência (multímetro).

    O RMS exibido resulta de ``entrada × base_gain``; para que passe a valer
    ``measured_rms``, o ganho vira ``base_gain × medido / exibido``. Canais com
    medida zero ficam de fora.
    """
    result = {}
    for channel, measured in measured_rms.items():
        if measured <= 0:
            continue
        shown = shown_rms.get(channel)
        if shown is None or not math.isfinite(shown) or shown <= 0:
            raise ValueError(f"Sem leitura válida no canal {channel} para calibrar")
        result[channel] = base_gain[channel] * measured / shown
    if not result:
        raise ValueError("Informe ao menos uma tensão medida maior que zero")
    return result
