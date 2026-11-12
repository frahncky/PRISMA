"""Protocolo serial do PRISMA v1 (uma linha JSON por amostra)."""
from dataclasses import dataclass
import json
import math

@dataclass(frozen=True)
class Sample:
    t: float
    va: float
    vb: float
    vc: float

def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"Campo '{field}' deve ser numérico")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"Campo '{field}' não pode ser infinito ou NaN")
    return result

def parse_sample(line: bytes | str) -> Sample:
    """Lê uma linha JSON, exigindo type=sample e campos t,va,vb,vc."""
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    payload = json.loads(line)
    if not isinstance(payload, dict) or payload.get("type") != "sample":
        raise ValueError("Mensagem não é uma amostra PRISMA (type=sample)")
    return Sample(**{name: _number(payload[name], name) for name in ("t", "va", "vb", "vc")})
