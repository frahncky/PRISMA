"""Realce de sintaxe C para o editor de firmware."""
from __future__ import annotations

import re

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

KEYWORDS = (
    "auto break case char const continue default do double else enum extern float for goto if "
    "inline int long register restrict return short signed sizeof static struct switch typedef "
    "union unsigned void volatile while byte word bool uint8_t uint16_t uint32_t int8_t int16_t int32_t"
).split()


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if bold:
        fmt.setFontWeight(QFont.Weight.DemiBold)
    fmt.setFontItalic(italic)
    return fmt


class CHighlighter(QSyntaxHighlighter):
    def __init__(self, document) -> None:
        super().__init__(document)
        self.rules = [
            (re.compile(r"\b(" + "|".join(KEYWORDS) + r")\b"), _fmt("#7aa7ff", bold=True)),
            (re.compile(r"^\s*#\s*\w+.*$"), _fmt("#c792ea")),
            (re.compile(r"\b(0[xX][0-9A-Fa-f]+[uUlL]*|\d+(\.\d+)?[uUlLfF]*)\b"), _fmt("#f2b84b")),
            (re.compile(r'"(\\.|[^"\\])*"|\'(\\.|[^\'\\])*\''), _fmt("#8bd49c")),
            (re.compile(r"\b[A-Za-z_]\w*(?=\s*\()"), _fmt("#3ec6e0")),
            (re.compile(r"//.*$"), _fmt("#5d6e86", italic=True)),
        ]
        self.comment = _fmt("#5d6e86", italic=True)

    def highlightBlock(self, text: str) -> None:
        for pattern, fmt in self.rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)
        # Comentários de bloco /* ... */, inclusive em várias linhas.
        self.setCurrentBlockState(0)
        start = 0 if self.previousBlockState() == 1 else text.find("/*")
        while start >= 0:
            end = text.find("*/", start + (0 if self.previousBlockState() == 1 and start == 0 else 2))
            if end < 0:
                self.setCurrentBlockState(1)
                self.setFormat(start, len(text) - start, self.comment)
                break
            self.setFormat(start, end + 2 - start, self.comment)
            start = text.find("/*", end + 2)
