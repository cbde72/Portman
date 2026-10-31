"""Selectable, page-synchronised PDF text layer without modifying the PDF."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QApplication, QMenu, QTextEdit, QToolTip

from .pdf_markings import PdfMarking


@dataclass(frozen=True)
class TextSelection:
    page_number: int
    text: str
    start: int
    end: int
    coordinates: object = None


class PdfTextLayer(QTextEdit):
    actionRequested = Signal(str, object)
    markingActivated = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent); self.setReadOnly(True); self.setAcceptRichText(False)
        self.setPlaceholderText("PDF-Textlayer")
        self.setContextMenuPolicy(Qt.CustomContextMenu); self.customContextMenuRequested.connect(self._menu)
        self.pages: dict[int, str] = {}; self.page_number = 1; self.markings: dict[int, list[TextSelection]] = {}
        self.field_markings: list[PdfMarking] = []
        self._hovered_key = None
        self.setMouseTracking(True)

    def set_pages(self, pages: dict[int, str]):
        self.pages = pages; self.markings.clear(); self.field_markings.clear(); self.show_page(1)

    def show_page(self, page_number: int):
        self.page_number = page_number
        text = self.pages.get(page_number, "")
        self.setPlainText(text if text.strip() else "Kein Textlayer vorhanden – OCR ist nicht aktiviert.")
        self.setEnabled(bool(text.strip())); self._show_markings()

    def set_field_markings(self, markings):
        self.field_markings = list(markings); self._show_markings()

    def clear_field_markings(self):
        self.field_markings.clear(); self._show_markings()

    def markings_for_page(self, page_number=None):
        page_number = self.page_number if page_number is None else page_number
        return [item for item in self.field_markings if item.page_number == page_number]

    def selection(self):
        cursor = self.textCursor()
        if not cursor.hasSelection() or not self.isEnabled(): return None
        return TextSelection(self.page_number, cursor.selectedText().replace("\u2029", "\n"),
                             cursor.selectionStart(), cursor.selectionEnd(), None)

    def remember_selection(self):
        selection = self.selection()
        if selection and selection not in self.markings.setdefault(selection.page_number, []):
            self.markings[selection.page_number].append(selection); self._show_markings()
        return selection

    def _show_markings(self):
        extras = []
        for selection in self.markings.get(self.page_number, []):
            cursor = QTextCursor(self.document()); cursor.setPosition(selection.start); cursor.setPosition(selection.end, QTextCursor.KeepAnchor)
            extra = QTextEdit.ExtraSelection(); extra.cursor = cursor
            extra.format.setBackground(QColor("#ffd54f")); extra.format.setProperty(QTextCharFormat.FullWidthSelection, False); extras.append(extra)
        for marking in self.markings_for_page():
            if marking.end <= marking.start or marking.start < 0:
                continue
            cursor = QTextCursor(self.document())
            cursor.setPosition(marking.start)
            cursor.setPosition(marking.end, QTextCursor.KeepAnchor)
            extra = QTextEdit.ExtraSelection(); extra.cursor = cursor
            color = QColor(marking.color); color.setAlpha(72)
            extra.format.setBackground(color)
            extra.format.setProperty(QTextCharFormat.FullWidthSelection, False)
            if marking.fallback:
                # A visible, explicit fallback marker instead of pretending to
                # have exact PDF coordinates.
                extra.format.setUnderlineStyle(QTextCharFormat.DotLine)
                extra.format.setUnderlineColor(QColor(marking.color))
            extras.append(extra)
        self.setExtraSelections(extras)

    def _markings_at(self, position):
        cursor = self.cursorForPosition(position)
        index = cursor.position()
        hits = [item for item in self.markings_for_page()
                if item.start <= index < item.end and item.end > item.start]
        if not hits:
            return []
        first = hits[0]
        return [item for item in hits if item.start < first.end and first.start < item.end]

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            groups = self._markings_at(event.position().toPoint())
            if groups:
                self.markingActivated.emit(groups)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        groups = self._markings_at(event.position().toPoint())
        key = tuple(item.key for item in groups) if groups else None
        if key != self._hovered_key:
            self._hovered_key = key
            if groups:
                lines = []
                for marking in groups:
                    if lines:
                        lines.append("")
                    lines.extend(marking.tooltip_lines())
                QToolTip.showText(event.globalPosition().toPoint(), "\n".join(lines), self)
            else:
                QToolTip.hideText()
        super().mouseMoveEvent(event)

    def highlight_text(self, text: str):
        if not text: return False
        start = self.toPlainText().find(text)
        if start < 0: return False
        cursor = self.textCursor(); cursor.setPosition(start); cursor.setPosition(start + len(text), QTextCursor.KeepAnchor)
        self.setTextCursor(cursor); self.ensureCursorVisible(); return True

    def focus_field(self, field_path):
        matches = [item for item in self.markings_for_page() if item.field_path == field_path]
        if not matches:
            return False
        marker = matches[0]
        cursor = self.textCursor(); cursor.setPosition(marker.start); cursor.setPosition(marker.end, QTextCursor.KeepAnchor)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        return True

    def _menu(self, position):
        menu = QMenu(self); selection = self.selection()
        groups = self._markings_at(position)
        copy = QAction("Text kopieren", self); copy.setEnabled(selection is not None)
        copy.triggered.connect(lambda: QApplication.clipboard().setText(selection.text) if selection else None); menu.addAction(copy)
        if groups:
            menu.addSeparator()
            for marking in groups:
                label = QAction(f"{marking.label}: {marking.value or '—'} [{marking.origin}]", self)
                label.setEnabled(False); menu.addAction(label)
        for label, action in (("Feld zuordnen", "map"), ("Neues Feld definieren", "new"),
                              ("Als Referenzwert übernehmen", "reference"), ("Fundstelle anzeigen", "locate")):
            item = QAction(label, self); item.setEnabled(selection is not None)
            item.triggered.connect(lambda checked=False, name=action: self._request(name)); menu.addAction(item)
        menu.exec(self.viewport().mapToGlobal(position))

    def _request(self, action):
        selection = self.remember_selection()
        if selection: self.actionRequested.emit(action, selection)
