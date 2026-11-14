"""Reconhecimento de fala offline em português (Vosk), para perguntas ao medidor.

O Vosk é opcional (``pip install -e ".[voz]"``) e precisa de um modelo baixado
uma vez (``python scripts/baixar_modelo_voz.py``). Sem eles, ``open_transcriber``
levanta ``SpeechUnavailable`` com a instrução de instalação e o painel segue
funcionando por toque e texto.

O reconhecedor usa um vocabulário restrito às palavras das perguntas: com o
modelo pequeno isso melhora muito o acerto em frases curtas.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

MODEL_NAME = "vosk-model-small-pt-0.3"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
SAMPLE_RATE = 16000

# Palavras que as perguntas usam (com e sem acento, como o modelo pode grafar).
VOCABULARY = """
qual quais quanto quanta quantos quero saber me diga diz fala mostra o a os as da do das dos de na no nas nos
e é esta está tá ta valor valores medição tem há
tensão tensões voltagem volts volt corrente correntes ampère ampères amperagem
fase fases linha bê cê b c
potência ativa reativa aparente consumo consumindo watts fator cosseno fi
frequência hertz rede distorção harmônica harmônicas thd desequilíbrio sequência ordem rotação
tudo bem situação resumo alerta alertas problema problemas
""".split()


class SpeechUnavailable(RuntimeError):
    """Vosk ou modelo ausente; a mensagem diz como instalar."""


def default_model_dir() -> Path:
    env = os.environ.get("PRISMA_VOSK_MODEL")
    return Path(env) if env else Path.home() / ".prisma" / "modelos" / MODEL_NAME


def grammar() -> str:
    return json.dumps(VOCABULARY + ["[unk]"], ensure_ascii=False)


class Transcriber:
    """Envolve um ``vosk.KaldiRecognizer``: ``accept`` recebe PCM 16 bits mono."""

    def __init__(self, recognizer) -> None:
        self._recognizer = recognizer

    def accept(self, pcm: bytes) -> str | None:
        """Texto final quando o locutor faz uma pausa; ``None`` enquanto fala."""
        if self._recognizer.AcceptWaveform(pcm):
            return json.loads(self._recognizer.Result()).get("text", "").strip()
        return None

    def partial(self) -> str:
        return json.loads(self._recognizer.PartialResult()).get("partial", "").strip()

    def finish(self) -> str:
        return json.loads(self._recognizer.FinalResult()).get("text", "").strip()


_MODEL_CACHE: dict[Path, object] = {}


def open_transcriber(model_dir: Path | None = None, restrict: bool = True) -> Transcriber:
    try:
        import vosk
    except ImportError as exc:
        raise SpeechUnavailable('Reconhecimento de voz não instalado. Rode: pip install -e ".[voz]"') from exc
    path = model_dir or default_model_dir()
    if not (path / "am").is_dir() and not (path / "conf").is_dir():
        raise SpeechUnavailable(f"Modelo de voz não encontrado em {path}. "
                                "Rode: python scripts/baixar_modelo_voz.py")
    vosk.SetLogLevel(-1)
    model = _MODEL_CACHE.get(path)
    if model is None:
        model = _MODEL_CACHE[path] = vosk.Model(str(path))
    recognizer = (vosk.KaldiRecognizer(model, SAMPLE_RATE, grammar()) if restrict
                  else vosk.KaldiRecognizer(model, SAMPLE_RATE))
    return Transcriber(recognizer)
