"""Editor de código com números de linha, linha atual destacada e barra de busca."""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QKeySequence, QPainter, QShortcut, QTextCursor, QTextDocument, QTextFormat
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from prisma.ui import theme
from prisma.ui.highlighter import CHighlighter


class _Gutter(QWidget):
    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event) -> None:
        self.editor.paint_gutter(event)


class CodeEditor(QPlainTextEdit):
    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setObjectName("code")
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.highlighter = CHighlighter(self.document())
        self.gutter = _Gutter(self)
        self.blockCountChanged.connect(self._update_margin)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._highlight_line)
        self._update_margin()
        self._highlight_line()

    def setFont(self, font) -> None:  # noqa: N802 - API Qt
        super().setFont(font)
        self._update_margin()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        # A fonte vem da folha de estilo; ajustar tabulação e margem quando ela muda.
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))
        self._update_margin()

    def gutter_width(self) -> int:
        digits = max(3, len(str(self.blockCount())))
        return 18 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_margin(self, *_) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _update_gutter(self, rect: QRect, dy: int) -> None:
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        area = self.contentsRect()
        self.gutter.setGeometry(QRect(area.left(), area.top(), self.gutter_width(), area.height()))

    def paint_gutter(self, event) -> None:
        painter = QPainter(self.gutter)
        painter.fillRect(event.rect(), QColor("#080d16"))
        current = self.textCursor().blockNumber()
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        height = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            bottom = top + round(self.blockBoundingRect(block).height())
            if block.isVisible() and bottom >= event.rect().top():
                number = block.blockNumber()
                painter.setPen(QColor(theme.TEXT if number == current else theme.SUBTLE))
                painter.drawText(0, top, self.gutter.width() - 10, height,
                                 Qt.AlignmentFlag.AlignRight, str(number + 1))
            block = block.next()
            top = bottom

    def _highlight_line(self) -> None:
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor("#111a28"))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])
        self.gutter.update()

    def find_text(self, text: str, backward: bool = False, case: bool = False) -> bool:
        if not text:
            return False
        flags = QTextDocument.FindFlag(0)
        if backward:
            flags |= QTextDocument.FindFlag.FindBackward
        if case:
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if self.find(text, flags):
            return True
        cursor = self.textCursor()  # recomeçar do outro extremo
        cursor.movePosition(QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start)
        self.setTextCursor(cursor)
        return self.find(text, flags)

    def replace_all(self, text: str, replacement: str, case: bool = False) -> int:
        if not text:
            return 0
        count = 0
        cursor = self.textCursor()
        cursor.beginEditBlock()
        self.moveCursor(QTextCursor.MoveOperation.Start)
        flags = QTextDocument.FindFlag.FindCaseSensitively if case else QTextDocument.FindFlag(0)
        while self.find(text, flags):
            self.textCursor().insertText(replacement)
            count += 1
        cursor.endEditBlock()
        return count


class EditorPanel(QWidget):
    """Editor + barra de localizar/substituir (Ctrl+F, Ctrl+H, Esc)."""

    def __init__(self, editor: CodeEditor, parent=None) -> None:
        super().__init__(parent)
        self.editor = editor
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(editor, stretch=1)
        self.bar = QFrame()
        self.bar.setObjectName("card")
        row = QHBoxLayout(self.bar)
        row.setContentsMargins(10, 6, 10, 6)
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Localizar")
        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText("Substituir por")
        self.case = QCheckBox("Aa")
        self.case.setToolTip("Diferenciar maiúsculas/minúsculas")
        self.status = QLabel()
        self.status.setObjectName("muted")
        prev_btn, next_btn, rep_btn, rep_all, close = (QPushButton(t) for t in ("↑", "↓", "Substituir", "Todos", "✕"))
        for widget in (self.find_edit, prev_btn, next_btn, self.case, self.replace_edit, rep_btn, rep_all, self.status):
            row.addWidget(widget)
        row.addStretch(1)
        row.addWidget(close)
        layout.addWidget(self.bar)
        self.bar.hide()
        next_btn.clicked.connect(lambda: self.find_next(False))
        prev_btn.clicked.connect(lambda: self.find_next(True))
        self.find_edit.returnPressed.connect(lambda: self.find_next(False))
        rep_btn.clicked.connect(self.replace_one)
        rep_all.clicked.connect(self.replace_all)
        close.clicked.connect(self.close_bar)
        QShortcut(QKeySequence.StandardKey.Find, self, activated=lambda: self.open_bar(False))
        QShortcut(QKeySequence("Ctrl+H"), self, activated=lambda: self.open_bar(True))
        QShortcut(QKeySequence("Esc"), self, activated=self.close_bar)
        self.replace_widgets = (self.replace_edit, rep_btn, rep_all)

    def open_bar(self, replace: bool) -> None:
        for widget in self.replace_widgets:
            widget.setVisible(replace)
        selected = self.editor.textCursor().selectedText()
        if selected:
            self.find_edit.setText(selected)
        self.bar.show()
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def close_bar(self) -> None:
        self.bar.hide()
        self.editor.setFocus()

    def find_next(self, backward: bool) -> bool:
        found = self.editor.find_text(self.find_edit.text(), backward, self.case.isChecked())
        self.status.setText("" if found or not self.find_edit.text() else "Não encontrado")
        return found

    def replace_one(self) -> None:
        cursor = self.editor.textCursor()
        if cursor.hasSelection() and cursor.selectedText() == self.find_edit.text():
            cursor.insertText(self.replace_edit.text())
        self.find_next(False)

    def replace_all(self) -> None:
        count = self.editor.replace_all(self.find_edit.text(), self.replace_edit.text(), self.case.isChecked())
        self.status.setText(f"{count} substituição(ões)")
