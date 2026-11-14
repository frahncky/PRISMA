"""Perguntas em português sobre a medição atual ("qual a corrente da fase A?").

Independe da interface: o painel touch usa por texto/botões e a entrada por
voz pode usar o mesmo ``answer`` depois de transcrever a fala. As respostas
são frases completas, prontas para exibir e para síntese de voz.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
import unicodedata

from .measurement import LIMIT_THD_PERCENT, LIMIT_UNBALANCE_PERCENT, Measurement, sequence_components

PHASES = ("A", "B", "C")


@dataclass(frozen=True)
class Answer:
    text: str
    understood: bool = True


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9%]+", " ", text).strip()
    # Fala transcrita: "fase bê", "fase cê"/"fase sê" (sem acento: be, ce, se).
    text = re.sub(r"\b(fases?|linha)\s+be\b", r"\1 b", text)
    text = re.sub(r"\b(fases?|linha)\s+[cs]e\b", r"\1 c", text)
    text = re.sub(r"\b([abc])\s+e\s+be\b", r"\1 e b", text)  # "fases a e bê"
    return re.sub(r"\b([abc])\s+e\s+[cs]e\b", r"\1 e c", text)


def _number(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


def _phases(words: str) -> tuple[str, ...]:
    """Fases citadas: "fase a", "fases a e b", "a b c"; vazio = todas."""
    found = re.findall(r"\bfases?\s+([abc](?:\s+(?:e\s+)?[abc])*)\b", words)
    phases = []
    for group in found:
        phases.extend(letter.upper() for letter in re.findall(r"[abc]", group))
    if not phases:
        phases = [letter.upper() for letter in re.findall(r"\b(?:fase|linha)?\s*([abc])\b$", words)]
    return tuple(dict.fromkeys(phases)) or PHASES


# (padrão, grandeza): o primeiro que casar vence; padrões mais específicos antes.
_QUANTITIES = (
    (r"\bfator\s+de\s+potencia\b|\bfp\b|\bcos\s*phi\b", "pf"),
    (r"\bpotencia\s+reativa\b|\breativ", "reactive"),
    (r"\bpotencia\s+aparente\b|\baparente\b", "apparent"),
    (r"\bpotencia\b|\bwatts?\b|\bconsumo\b", "active"),
    (r"\bdesequilibrio\b|\bdesbalanc", "unbalance"),
    (r"\bthd\b|\bdistorcao\b|\bharmonic", "thd"),
    (r"\bfrequencia\b|\bhertz\b|\bhz\b", "frequency"),
    (r"\bsequencia\b|\bordem\s+das\s+fases\b|\brotacao\b", "rotation"),
    (r"\bcorrentes?\b|\bamperes?\b|\bamperagem\b", "current"),
    (r"\btens(?:ao|oes)\b|\bvolts?\b|\bvoltagem\b", "voltage"),
    (r"\balertas?\b|\bproblemas?\b|\btudo\s+bem\b|\bsituacao\b|\bstatus\b|\bresumo\b", "summary"),
)


def parse(question: str) -> tuple[str | None, tuple[str, ...]]:
    words = _normalize(question)
    for pattern, quantity in _QUANTITIES:
        if re.search(pattern, words):
            return quantity, _phases(words)
    return None, PHASES


def _per_phase(name: str, phases: tuple[str, ...], values: dict[str, float], unit: str, decimals: int) -> str:
    if len(phases) == 1:
        p = phases[0]
        return f"{name} da fase {p} é {_number(values[p], decimals)} {unit}."
    parts = [f"fase {p}, {_number(values[p], decimals)}" for p in phases]
    return f"{name}: " + "; ".join(parts) + f" {unit}."


def answer(question: str, result: Measurement | None) -> Answer:
    quantity, phases = parse(question)
    if quantity is None:
        return Answer("Não entendi. Pergunte, por exemplo: qual a corrente da fase A?", understood=False)
    if result is None:
        return Answer("Ainda não há medição válida. Aguarde o sinal estabilizar.")

    if quantity == "voltage":
        return Answer(_per_phase("A tensão", phases, result.rms, "volts", 1))
    if quantity == "frequency":
        return Answer(f"A frequência é {_number(result.frequency_hz, 2)} hertz.")
    if quantity == "thd":
        if result.thd_percent is None:
            return Answer("A distorção harmônica não está disponível nesta janela.")
        over = " Acima do limite do PRODIST." if result.thd_percent > LIMIT_THD_PERCENT else ""
        return Answer(f"A distorção harmônica total da fase A é {_number(result.thd_percent, 1)} por cento.{over}")
    if quantity in ("unbalance", "rotation"):
        seq = sequence_components(result.phasors)
        if quantity == "rotation":
            order = {"ABC": "direta, A B C", "ACB": "inversa, A C B"}.get(seq.rotation or "")
            return Answer(f"A sequência de fases é {order}." if order else "A sequência de fases está indefinida.")
        if seq.unbalance_percent is None:
            return Answer("O desequilíbrio não está disponível.")
        over = " Acima do limite do PRODIST." if seq.unbalance_percent > LIMIT_UNBALANCE_PERCENT else ""
        return Answer(f"O desequilíbrio de tensão é {_number(seq.unbalance_percent, 2)} por cento.{over}")
    if quantity == "summary":
        return Answer(summary(result))

    if not result.current_rms:
        return Answer("Não há correntes medidas: só as tensões estão disponíveis.")
    if quantity == "current":
        return Answer(_per_phase("A corrente", phases, result.current_rms, "ampères", 2))
    powers = result.power
    if quantity == "pf":
        values = {p: powers[p].power_factor for p in phases}
        if any(v is None for v in values.values()):
            return Answer("O fator de potência não está disponível.")
        return Answer(_per_phase("O fator de potência", phases, values, "", 3).replace(" .", "."))
    field, name, unit = {"active": ("active_w", "A potência ativa", "watts"),
                         "reactive": ("reactive_fundamental_var", "A potência reativa", "volt-ampères reativos"),
                         "apparent": ("apparent_va", "A potência aparente", "volt-ampères")}[quantity]
    values = {p: getattr(powers[p], field) for p in phases}
    text = _per_phase(name, phases, values, unit, 0)
    if len(phases) == 3:
        text = text[:-1] + f". Total, {_number(sum(values.values()), 0)} {unit}."
    return Answer(text)


def alerts(result: Measurement) -> list[str]:
    found = []
    if result.thd_percent is not None and result.thd_percent > LIMIT_THD_PERCENT:
        found.append(f"THD da fase A em {_number(result.thd_percent, 1)} %, acima de {LIMIT_THD_PERCENT:.0f} %")
    unbalance = sequence_components(result.phasors).unbalance_percent
    if unbalance is not None and unbalance > LIMIT_UNBALANCE_PERCENT:
        found.append(f"Desequilíbrio de {_number(unbalance, 2)} %, acima de {LIMIT_UNBALANCE_PERCENT:.0f} %")
    return found


def summary(result: Measurement) -> str:
    rms = ", ".join(_number(result.rms[p], 0) for p in PHASES)
    text = f"Tensões de {rms} volts a {_number(result.frequency_hz, 1)} hertz."
    if result.current_rms and math.isfinite(sum(p.active_w for p in result.power.values())):
        total = sum(p.active_w for p in result.power.values())
        text += f" Potência total de {_number(total, 0)} watts."
    found = alerts(result)
    return text + (" Alertas: " + "; ".join(found) + "." if found else " Sem alertas.")
