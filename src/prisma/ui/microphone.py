"""Escuta uma pergunta pelo microfone e devolve o texto reconhecido.

Captura PCM 16 kHz, 16 bits, mono pelo Qt Multimedia e alimenta o reconhecedor
offline (``prisma.core.speech``). Termina sozinho quando o locutor faz uma
pausa ou depois de ``MAX_SECONDS``.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from prisma.core.speech import SAMPLE_RATE, SpeechUnavailable, Transcriber, open_transcriber

MAX_SECONDS = 8


class MicListener(QObject):
    partial = Signal(str)
    final = Signal(str)     # texto reconhecido ("" se nada foi entendido)
    failed = Signal(str)    # motivo legível (sem Vosk, sem modelo, sem microfone)
    listening = Signal(bool)

    def __init__(self, parent: QObject | None = None,
                 transcriber_factory: Callable[[], Transcriber] = open_transcriber) -> None:
        super().__init__(parent)
        self._factory = transcriber_factory
        self._transcriber: Transcriber | None = None
        self._source = None
        self._device = None
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._finish)

    @property
    def active(self) -> bool:
        return self._transcriber is not None

    def start(self) -> bool:
        if self.active:
            return True
        try:
            self._transcriber = self._factory()
        except SpeechUnavailable as exc:
            self.failed.emit(str(exc))
            return False
        if not self._open_audio():
            self._transcriber = None
            return False
        self._timeout.start(MAX_SECONDS * 1000)
        self.listening.emit(True)
        return True

    def _open_audio(self) -> bool:
        try:
            from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices
        except ImportError:
            self.failed.emit("Qt Multimedia indisponível para capturar o microfone.")
            return False
        device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            self.failed.emit("Nenhum microfone encontrado.")
            return False
        audio_format = QAudioFormat()
        audio_format.setSampleRate(SAMPLE_RATE)
        audio_format.setChannelCount(1)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(audio_format):
            self.failed.emit(f"O microfone '{device.description()}' não aceita 16 kHz mono.")
            return False
        self._source = QAudioSource(device, audio_format, self)
        self._device = self._source.start()
        if self._device is None:
            self.failed.emit("Não foi possível abrir o microfone (permissão do Windows?).")
            self._source = None
            return False
        self._device.readyRead.connect(lambda: self.feed(bytes(self._device.readAll().data()))
                                       if self._device is not None else None)
        return True

    def feed(self, pcm: bytes) -> None:
        """Entrega áudio ao reconhecedor (público para testes e outras fontes)."""
        if self._transcriber is None or not pcm:
            return
        text = self._transcriber.accept(pcm)
        if text is None:
            partial = self._transcriber.partial()
            if partial:
                self.partial.emit(partial)
        elif text:
            self._stop()
            self.final.emit(text)

    def _finish(self) -> None:
        text = self._transcriber.finish() if self._transcriber is not None else ""
        self._stop()
        self.final.emit(text)

    def cancel(self) -> None:
        self._stop()

    def _stop(self) -> None:
        self._timeout.stop()
        if self._source is not None:
            self._source.stop()
        self._source = None
        self._device = None
        was_active = self._transcriber is not None
        self._transcriber = None
        if was_active:
            self.listening.emit(False)
