import numpy as np
import pytest

from prisma.core.measurement import analyze
from prisma.core.query import alerts, answer, parse


def _measurement(currents=True, unbalanced=False):
    fs, f = 2400.0, 60.0
    t = np.arange(480) / fs
    phases = np.array([0, -2 * np.pi / 3, 2 * np.pi / 3])
    amp = np.array([127, 127, 100 if unbalanced else 127]) * np.sqrt(2)
    v = amp * np.sin(2 * np.pi * f * t[:, None] + phases)
    i = 5 * np.sqrt(2) * np.sin(2 * np.pi * f * t[:, None] + phases - np.arccos(0.9)) if currents else None
    return analyze(t, v, fundamental_hz=60.0, currents=i)


@pytest.mark.parametrize("question, quantity, phases", [
    ("Qual a corrente da fase A?", "current", ("A",)),
    ("quero o valor da corrente na fase A", "current", ("A",)),
    ("Quanto está a TENSÃO da fase c", "voltage", ("C",)),
    ("tensões das fases A e B", "voltage", ("A", "B")),
    ("qual a voltagem", "voltage", ("A", "B", "C")),
    ("qual o fator de potência da fase b", "pf", ("B",)),
    ("potência reativa", "reactive", ("A", "B", "C")),
    ("quanto estou consumindo de potência", "active", ("A", "B", "C")),
    ("qual a frequência da rede", "frequency", ("A", "B", "C")),
    ("tem desequilíbrio?", "unbalance", ("A", "B", "C")),
    ("e a distorção harmônica", "thd", ("A", "B", "C")),
    ("está tudo bem?", "summary", ("A", "B", "C")),
    ("qual a sequência de fases", "rotation", ("A", "B", "C")),
])
def test_interpreta_perguntas(question, quantity, phases):
    assert parse(question) == (quantity, phases)


def test_responde_corrente_da_fase_a_em_frase_falavel():
    text = answer("quero o valor da corrente na fase A", _measurement()).text
    assert text == "A corrente da fase A é 5,00 ampères."


def test_responde_tres_fases_e_total_de_potencia():
    text = answer("qual a potência", _measurement()).text
    # 127 V × 5 A × 0,9 = 571,5 W por fase
    assert text.startswith("A potência ativa: fase A, 57") and "; fase C, 57" in text
    assert text.endswith(" watts.") and "Total, 171" in text


def test_fator_de_potencia_e_frequencia():
    m = _measurement()
    assert answer("fp da fase a", m).text == "O fator de potência da fase A é 0,900."
    assert answer("frequência", m).text == "A frequência é 60,00 hertz."


def test_sem_correntes_e_sem_medicao():
    assert "Não há correntes" in answer("corrente da fase A", _measurement(currents=False)).text
    assert "Ainda não há medição" in answer("tensão", None).text


def test_pergunta_desconhecida():
    result = answer("que horas são", _measurement())
    assert not result.understood and "Não entendi" in result.text


def test_alerta_de_desequilibrio_no_resumo():
    m = _measurement(unbalanced=True)
    assert alerts(m) and "Desequilíbrio" in alerts(m)[0]
    text = answer("está tudo bem?", m).text
    assert "Alertas:" in text and "PRODIST" not in text
    assert "Sem alertas." in answer("resumo", _measurement()).text
