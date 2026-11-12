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
