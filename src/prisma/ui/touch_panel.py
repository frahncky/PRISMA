"""Painel touch em tela cheia: valores grandes, alertas e perguntas com resposta falada.

Tocar num bloco faz a pergunta correspondente ("qual a corrente da fase A?") e
a resposta aparece embaixo e, com a voz ligada, é falada. As perguntas passam
por ``prisma.core.query``: a futura entrada por microfone usa o mesmo caminho.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from prisma.core.measurement import LIMIT_THD_PERCENT, LIMIT_UNBALANCE_PERCENT, Measurement, sequence_components
from prisma.core.query import alerts, answer
from prisma.ui import theme

MeasurementSource = Callable[[], tuple[Measurement | None, str]]

TOUCH_STYLE = f"""
QWidget#touchPanel {{ background: {theme.BG}; }}
QPushButton#tile {{ background: {theme.SURFACE}; border: 1px solid {theme.BORDER}; border-radius: 18px;
    text-align: left; padding: 0; }}
QPushButton#tile:pressed {{ background: #14304a; border-color: {theme.ACCENT}; }}
QLabel#tileCaption {{ color: {theme.MUTED}; font-size: 17px; font-weight: 600; }}
QLabel#tileValue {{ font-size: 46px; font-weight: 700; }}
QLabel#tileHint {{ color: {theme.SUBTLE}; font-size: 14px; }}
QLabel#touchTitle {{ font-size: 24px; font-weight: 800; letter-spacing: 4px; color: #ffffff; }}
QLabel#touchMode {{ color: {theme.MUTED}; font-size: 16px; }}
QLabel#touchAlert {{ background: #3a1e22; color: #ffd0d3; border: 1px solid {theme.DANGER}; border-radius: 14px;
    padding: 12px 18px; font-size: 18px; font-weight: 600; }}
QLabel#touchAnswer {{ background: {theme.SURFACE}; border: 1px solid {theme.BORDER}; border-radius: 14px;
    padding: 14px 18px; font-size: 22px; color: #ffffff; }}
QPushButton#touchButton {{ font-size: 18px; font-weight: 600; min-height: 64px; min-width: 64px;
    padding: 0 22px; border-radius: 14px; }}
QPushButton#touchButton:checked {{ background: #12324a; border-color: {theme.ACCENT}; color: #ffffff; }}
QLineEdit#touchInput {{ font-size: 20px; min-height: 60px; border-radius: 14px; padding: 0 18px; }}
"""


class Tile(QPushButton):
    """Bloco tocável com legenda, valor grande e dica; o toque faz uma pergunta."""

    def __init__(self, caption: str, question: str, color: str = theme.TEXT) -> None:
        super().__init__()
        self.setObjectName("tile")
        self.question = question
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(120)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 14, 22, 14)
        layout.setSpacing(2)
        self.caption = QLabel(caption)
        self.caption.setObjectName("tileCaption")
        self.value = QLabel("---")
        self.value.setObjectName("tileValue")
        self.value.setStyleSheet(f"color: {color}")
        self.hint = QLabel("")
        self.hint.setObjectName("tileHint")
        for label in (self.caption, self.value, self.hint):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(label)
        layout.addStretch(1)

    def set_value(self, value: str, hint: str = "", warn: bool = False) -> None:
        self.value.setText(value)
        self.hint.setText(hint)
        self.hint.setStyleSheet(f"color: {theme.WARNING}" if warn else "")


class TouchPanel(QWidget):
    def __init__(self, source: MeasurementSource, parent: QWidget | None = None,
                 speaker: Callable[[str], None] | None = None, listener=None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setObjectName("touchPanel")
        self.setWindowTitle("PRISMA · Painel")
        self.setStyleSheet(theme.STYLE + TOUCH_STYLE)
        self.source = source
        self._speech = None
        self.speaker = speaker or self._speak_with_qt
        self.last_answer = ""
        if listener is None:
            from prisma.ui.microphone import MicListener
            listener = MicListener(self)
        self.listener = listener
        self.listener.partial.connect(lambda text: self.answer_label.setText(f"Ouvindo… {text}"))
        self.listener.final.connect(self._heard)
        self.listener.failed.connect(self._mic_failed)
        self.listener.listening.connect(self._mic_state)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(14)

        top = QHBoxLayout()
        title = QLabel("PRISMA")
        title.setObjectName("touchTitle")
        top.addWidget(title)
        top.addSpacing(18)
        self.mode_label = QLabel("")
        self.mode_label.setObjectName("touchMode")
        top.addWidget(self.mode_label)
        top.addStretch(1)
        self.voice_button = QPushButton("Voz ligada")
        self.voice_button.setObjectName("touchButton")
        self.voice_button.setCheckable(True)
        self.voice_button.setChecked(True)
        self.voice_button.toggled.connect(lambda on: self.voice_button.setText("Voz ligada" if on else "Voz desligada"))
        top.addWidget(self.voice_button)
        summary = QPushButton("Está tudo bem?")
        summary.setObjectName("touchButton")
        summary.clicked.connect(lambda: self.ask("está tudo bem?"))
        top.addWidget(summary)
        close = QPushButton("Sair")
        close.setObjectName("touchButton")
        close.clicked.connect(self.close)
        top.addWidget(close)
        root.addLayout(top)

        self.alert_label = QLabel("")
        self.alert_label.setObjectName("touchAlert")
        self.alert_label.setWordWrap(True)
        self.alert_label.hide()
        root.addWidget(self.alert_label)

        grid = QGridLayout()
        grid.setSpacing(14)
        self.tiles: dict[str, Tile] = {}
        layout = (
            ("vA", "Tensão · fase A", "qual a tensão da fase A", theme.PHASE["A"]),
            ("vB", "Tensão · fase B", "qual a tensão da fase B", theme.PHASE["B"]),
            ("vC", "Tensão · fase C", "qual a tensão da fase C", theme.PHASE["C"]),
            ("iA", "Corrente · fase A", "qual a corrente da fase A", theme.PHASE["A"]),
            ("iB", "Corrente · fase B", "qual a corrente da fase B", theme.PHASE["B"]),
            ("iC", "Corrente · fase C", "qual a corrente da fase C", theme.PHASE["C"]),
            ("freq", "Frequência", "qual a frequência", theme.ACCENT),
            ("power", "Potência ativa total", "qual a potência", theme.TEXT),
            ("pf", "Fator de potência · A", "qual o fator de potência da fase A", theme.TEXT),
            ("thd", "THD · fase A", "qual a distorção harmônica", theme.TEXT),
            ("unb", "Desequilíbrio", "qual o desequilíbrio", theme.TEXT),
            ("seq", "Sequência de fases", "qual a sequência de fases", theme.TEXT),
        )
        for index, (key, caption, question, color) in enumerate(layout):
            tile = Tile(caption, question, color)
            tile.clicked.connect(lambda _=False, q=question: self.ask(q))
            grid.addWidget(tile, index // 3, index % 3)
            self.tiles[key] = tile
        root.addLayout(grid, stretch=1)

        ask_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setObjectName("touchInput")
        self.input.setPlaceholderText("Pergunte: qual a corrente da fase A?")
        self.input.returnPressed.connect(self._ask_typed)
        ask_row.addWidget(self.input, stretch=1)
        self.mic_button = QPushButton("Falar")
        self.mic_button.setObjectName("touchButton")
        self.mic_button.setCheckable(True)
        self.mic_button.setToolTip("Toque e faça a pergunta em voz alta")
        self.mic_button.clicked.connect(self.toggle_listening)
        ask_row.addWidget(self.mic_button)
        ask = QPushButton("Perguntar")
        ask.setObjectName("touchButton")
        ask.clicked.connect(self._ask_typed)
        ask_row.addWidget(ask)
        root.addLayout(ask_row)
        self.answer_label = QLabel("Toque num valor para ouvir a medição.")
        self.answer_label.setObjectName("touchAnswer")
        self.answer_label.setWordWrap(True)
        root.addWidget(self.answer_label)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)
        self.refresh()

    # --- perguntas e voz ---------------------------------------------------
    def _ask_typed(self) -> None:
        text = self.input.text().strip()
        if text:
            self.ask(text)
            self.input.clear()

    def ask(self, question: str) -> str:
        result, _ = self.source()
        self.last_answer = answer(question, result).text
        self.answer_label.setText(self.last_answer)
        if self.voice_button.isChecked():
            self.speaker(self.last_answer)
        return self.last_answer

    def toggle_listening(self) -> None:
        if self.listener.active:
            self.listener.cancel()
            self.answer_label.setText("Escuta cancelada.")
            return
        if self._speech is not None:
            self._speech.stop()  # não ouvir a própria resposta
        if self.listener.start():
            self.answer_label.setText("Ouvindo… pergunte, por exemplo: qual a corrente da fase A?")

    def _heard(self, text: str) -> None:
        if not text:
            self.answer_label.setText("Não ouvi nenhuma pergunta. Toque em Falar e tente de novo.")
            return
        self.input.setText(text)
        self.ask(text)
        self.input.clear()

    def _mic_state(self, on: bool) -> None:
        self.mic_button.setChecked(on)
        self.mic_button.setText("Ouvindo…" if on else "Falar")

    def _mic_failed(self, reason: str) -> None:
        self.mic_button.setChecked(False)
        self.answer_label.setText(reason)

    def _speak_with_qt(self, text: str) -> None:
        try:
            if self._speech is None:
                from PySide6.QtCore import QLocale
                from PySide6.QtTextToSpeech import QTextToSpeech
                self._speech = QTextToSpeech(self)
                self._speech.setLocale(QLocale(QLocale.Language.Portuguese, QLocale.Country.Brazil))
            self._speech.stop()
            self._speech.say(text)
        except Exception:  # sem motor de voz: a resposta continua na tela
            self.voice_button.setChecked(False)
            self.voice_button.setEnabled(False)
            self.voice_button.setText("Sem voz")

    # --- atualização --------------------------------------------------------
    def refresh(self) -> None:
        result, mode = self.source()
        self.mode_label.setText(mode)
        if result is None:
            for tile in self.tiles.values():
                tile.set_value("---", "aguardando sinal")
            self.alert_label.hide()
            return
        for phase in "ABC":
            self.tiles[f"v{phase}"].set_value(f"{result.rms[phase]:.1f} V".replace(".", ","))
            current = result.current_rms.get(phase)
            self.tiles[f"i{phase}"].set_value("---" if current is None else f"{current:.2f} A".replace(".", ","),
                                         "" if current is not None else "sem correntes")
        self.tiles["freq"].set_value(f"{result.frequency_hz:.2f} Hz".replace(".", ","))
        if result.power:
            total = sum(p.active_w for p in result.power.values())
            self.tiles["power"].set_value(_si(total, "W"))
            pf = result.power["A"].power_factor
            self.tiles["pf"].set_value("---" if pf is None else f"{pf:.3f}".replace(".", ","))
        else:
            self.tiles["power"].set_value("---", "sem correntes")
            self.tiles["pf"].set_value("---", "sem correntes")
        if result.thd_percent is None:
            self.tiles["thd"].set_value("---")
        else:
            over = result.thd_percent > LIMIT_THD_PERCENT
            self.tiles["thd"].set_value(f"{result.thd_percent:.1f} %".replace(".", ","),
                                   f"acima de {LIMIT_THD_PERCENT:.0f} % (PRODIST)" if over else "", warn=over)
        seq = sequence_components(result.phasors)
        unbalance = seq.unbalance_percent
        if unbalance is None:
            self.tiles["unb"].set_value("---")
        else:
            over = unbalance > LIMIT_UNBALANCE_PERCENT
            self.tiles["unb"].set_value(f"{unbalance:.2f} %".replace(".", ","),
                                   f"acima de {LIMIT_UNBALANCE_PERCENT:.0f} % (PRODIST)" if over else "", warn=over)
        self.tiles["seq"].set_value(seq.rotation or "---", {"ABC": "direta", "ACB": "inversa"}.get(seq.rotation or "", ""),
                               warn=seq.rotation == "ACB")
        found = alerts(result)
        self.alert_label.setText("⚠  " + "   ·   ".join(found))
        self.alert_label.setVisible(bool(found))

    def keyPressEvent(self, event) -> None:  # Esc sai do painel (útil com teclado)
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self.timer.stop()
        self.listener.cancel()
        if self._speech is not None:
            self._speech.stop()
        super().closeEvent(event)


def _si(value: float, unit: str) -> str:
    if abs(value) >= 1000:
        return f"{value / 1000:.2f} k{unit}".replace(".", ",")
    return f"{value:.0f} {unit}"
