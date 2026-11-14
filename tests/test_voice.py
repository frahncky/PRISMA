"""Entrada por voz sem Vosk nem microfone: reconhecedor e áudio simulados."""
import json
import os
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from prisma.core.query import parse
from prisma.core.speech import SpeechUnavailable, Transcriber, grammar, open_transcriber
from prisma.ui.microphone import MicListener
from prisma.ui.touch_panel import TouchPanel
from test_query import _measurement


class FakeRecognizer:
    """Imita o KaldiRecognizer: cada chunk b"..." vira palavras; b"" encerra a frase."""

    def __init__(self):
        self.words = []

    def AcceptWaveform(self, pcm):
        if pcm == b"<pausa>":
            return True
        self.words.append(pcm.decode())
        return False

    def Result(self):
        text, self.words = " ".join(self.words), []
        return json.dumps({"text": text})

    def PartialResult(self):
        return json.dumps({"partial": " ".join(self.words)})

    def FinalResult(self):
        return self.Result()


def _listener(app):
    listener = MicListener(transcriber_factory=lambda: Transcriber(FakeRecognizer()))
    listener._open_audio = lambda: True  # sem microfone no teste
    return listener


@pytest.mark.parametrize("spoken, expected", [
    ("qual a corrente da fase bê", ("current", ("B",))),
    ("tensão da fase cê", ("voltage", ("C",))),
    ("tensões das fases a e bê", ("voltage", ("A", "B"))),
])
def test_letras_faladas_viram_fases(spoken, expected):
    assert parse(spoken) == expected


def test_gramatica_restrita_inclui_palavras_das_perguntas():
    words = json.loads(grammar())
    assert {"corrente", "fase", "tensão", "bê", "[unk]"} <= set(words)


def test_sem_modelo_explica_como_instalar(tmp_path):
    try:
        import vosk  # noqa: F401
    except ImportError:
        with pytest.raises(SpeechUnavailable, match="pip install"):
            open_transcriber(tmp_path)
    else:
        with pytest.raises(SpeechUnavailable, match="baixar_modelo_voz"):
            open_transcriber(tmp_path)


def test_microfone_emite_parcial_e_final(app):
    listener = _listener(app)
    partial, final, states = [], [], []
    listener.partial.connect(partial.append)
    listener.final.connect(final.append)
    listener.listening.connect(states.append)
    assert listener.start()
    for chunk in (b"qual", b"a", b"corrente", b"<pausa>"):
        listener.feed(chunk)
    assert partial[-1] == "qual a corrente"
    assert final == ["qual a corrente"] and states == [True, False] and not listener.active


def test_tempo_esgotado_entrega_o_que_ouviu(app):
    listener = _listener(app)
    final = []
    listener.final.connect(final.append)
    listener.start()
    listener.feed(b"frequencia")
    listener._finish()  # o timer de 8 s dispara
    assert final == ["frequencia"]


def test_falar_no_painel_pergunta_e_responde_em_voz(app):
    listener = _listener(app)
    spoken = []
    panel = TouchPanel(lambda: (_measurement(), "DEMO"), speaker=spoken.append, listener=listener)
    panel.mic_button.click()
    assert panel.mic_button.text() == "Ouvindo…"
    for chunk in (b"corrente", b"da", b"fase", "bê".encode(), b"<pausa>"):
        listener.feed(chunk)
    assert spoken == ["A corrente da fase B é 5,00 ampères."]
    assert panel.mic_button.text() == "Falar" and not panel.mic_button.isChecked()
    panel.close()


def test_painel_sem_vosk_mostra_instrucao(app):
    def unavailable():
        raise SpeechUnavailable('Reconhecimento de voz não instalado. Rode: pip install -e ".[voz]"')
    listener = MicListener(transcriber_factory=unavailable)
    panel = TouchPanel(lambda: (None, ""), speaker=lambda t: None, listener=listener)
    panel.mic_button.click()
    assert "pip install" in panel.answer_label.text() and not panel.mic_button.isChecked()
    panel.close()


def test_extracao_do_modelo_bloqueia_caminho_fora_da_pasta(tmp_path):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "baixar", Path(__file__).resolve().parents[1] / "scripts" / "baixar_modelo_voz.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("../fora.txt", "x")
    with pytest.raises(ValueError, match="inválido"):
        module.extract(bad, tmp_path / "destino")
    assert not (tmp_path / "fora.txt").exists()
