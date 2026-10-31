"""Coordinate-accurate PDF page rendering and direct text selection using Qt PDF."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QMouseEvent, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication, QMenu, QScrollArea, QToolTip, QWidget

from .pdf_markings import PdfMarking, group_at_anchor


@dataclass(frozen=True)
class PdfCoordinateSelection:
    page_number: int
    text: str
    start_index: int
    end_index: int
    coordinates: dict
    field_path: str = ""
    markings: tuple = field(default_factory=tuple)


class PdfPageCanvas(QWidget):
    actionRequested = Signal(str, object)
    selectionChanged = Signal(object)
    markingActivated = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent); self.document = None; self.page_index = 0; self.zoom = 1.0
        self.pixmap = QPixmap(); self.anchor = None; self.selection = None; self.saved_coordinates = []
        self.page_rotations = {}
        self.markings: list[PdfMarking] = []
        self.markings_enabled = True
        self.marking_scope = "all"
        self.selected_field_path = ""
        self._pressed_groups = None
        self._hovered_key = None
        self.setMouseTracking(True); self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def set_document(self, document):
        self.document = document; self.render_page()

    def set_page(self, page_index):
        self.page_index = page_index; self.selection = None; self.render_page()

    def set_zoom(self, factor):
        self.zoom = max(0.25, min(8.0, factor)); self.render_page()

    def set_markings(self, markings):
        self.markings = list(markings)
        self._hovered_key = None
        self.update()

    def set_marking_options(self, enabled=True, scope="all", field_path=""):
        self.markings_enabled = bool(enabled)
        self.marking_scope = scope
        self.selected_field_path = field_path or ""
        self.update()

    def _visible_markings(self):
        if not self.markings_enabled or self.marking_scope == "off":
            return []
        if self.marking_scope == "selected":
            if not self.selected_field_path:
                return []
            return [item for item in self.markings if item.field_path == self.selected_field_path]
        return list(self.markings)

    def page_markings(self, page_number=None):
        page_number = self.page_index + 1 if page_number is None else page_number
        return [item for item in self._visible_markings()
                if item.page_number == page_number and item.quads]

    def render_page(self):
        try:
            if not self.document or self.document.pageCount() <= self.page_index: return
        except RuntimeError:  # QObject teardown may race a final status signal
            return
        points = self.document.pagePointSize(self.page_index)
        size = QSize(max(1, round(points.width() * self.zoom)), max(1, round(points.height() * self.zoom)))
        self.pixmap = QPixmap.fromImage(self.document.render(self.page_index, size))
        self.resize(self.pixmap.size()); self.setMinimumSize(self.pixmap.size()); self.update()

    def _pdf_point(self, point):
        if self.pixmap.isNull() or not self.document: return QPointF()
        size = self.document.pagePointSize(self.page_index)
        return QPointF(point.x() * size.width() / self.pixmap.width(), point.y() * size.height() / self.pixmap.height())

    def _screen_polygon(self, quad):
        size = self.document.pagePointSize(self.page_index)
        return QPolygonF([QPointF(point.x() * self.pixmap.width() / size.width(),
                                 point.y() * self.pixmap.height() / size.height()) for point in quad])

    def _screen_points(self, point):
        size = self.document.pagePointSize(self.page_index)
        return QPointF(point.x() * self.pixmap.width() / size.width(),
                       point.y() * self.pixmap.height() / size.height())

    def _serialize(self, selection, page_size):
        quads = [[[point.x(), point.y()] for point in polygon] for polygon in selection.bounds()]
        return {"coordinate_system": "PDF_POINTS", "quads": quads,
                "page_width": page_size.width(), "page_height": page_size.height(),
                "rotation": int(self.page_rotations.get(self.page_index + 1, 0)) % 360,
                "start_index": selection.startIndex(), "end_index": selection.endIndex()}

    def markings_at(self, position, page_number=None):
        """Return all fields whose visible highlight contains the screen point."""
        if not self.document or self.pixmap.isNull():
            return []
        page_number = self.page_index + 1 if page_number is None else page_number
        hits = []
        for marking in self.page_markings(page_number):
            for quad in marking.quads:
                polygon = self._screen_polygon(quad)
                if polygon.containsPoint(position, Qt.OddEvenFill):
                    hits.append(marking)
                    break
        if not hits:
            return []
        first = hits[0]
        return group_at_anchor(hits, first.page_number, first.start, first.end) if first.start < first.end else hits

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self.document:
            groups = self.markings_at(event.position())
            if groups:
                self._pressed_groups = groups
                event.accept()
                return
            self.anchor = self._pdf_point(event.position()); self.selection = None; self.update(); event.accept(); return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.anchor is not None and event.buttons() & Qt.LeftButton:
            value = self.document.getSelection(self.page_index, self.anchor, self._pdf_point(event.position()))
            if value.isValid() and value.text(): self.selection = value; self.update()
            event.accept(); return
        groups = self.markings_at(event.position())
        key = tuple(item.key for item in groups) if groups else None
        if key != self._hovered_key:
            self._hovered_key = key
            if groups:
                first = groups[0]
                lines = []
                for marking in groups:
                    if lines:
                        lines.append("")
                    lines.extend(marking.tooltip_lines())
                if len(groups) > 1:
                    lines.insert(0, f"{len(groups)} Felder an dieser Fundstelle")
                QToolTip.showText(event.globalPosition().toPoint(), "\n".join(lines), self)
                self.setCursor(Qt.PointingHandCursor)
            else:
                QToolTip.hideText()
                self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._pressed_groups is not None:
            groups = self._pressed_groups
            self._pressed_groups = None
            if groups:
                self.markingActivated.emit(groups)
            event.accept(); return
        if event.button() == Qt.LeftButton and self.anchor is not None:
            self.anchor = None
            selection = self.current_selection()
            if selection: self.selectionChanged.emit(selection)
            event.accept(); return
        super().mouseReleaseEvent(event)

    def current_selection(self):
        if not self.selection or not self.selection.isValid() or not self.selection.text(): return None
        coordinates = self._serialize(self.selection, self.document.pagePointSize(self.page_index))
        return PdfCoordinateSelection(self.page_index + 1, self.selection.text().replace("\r\n", "\n"),
                                      self.selection.startIndex(), self.selection.endIndex(), coordinates)

    def set_selection_by_index(self, page_number, start, length):
        if not self.document or page_number < 1 or page_number > self.document.pageCount(): return False
        self.set_page(page_number - 1); selection = self.document.getSelectionAtIndex(page_number - 1, start, length)
        if not selection.isValid(): return False
        self.selection = selection; self.update(); return True

    def add_saved_coordinates(self, page_number, coordinates):
        self.saved_coordinates.append((page_number, coordinates)); self.update()

    def clear_saved_coordinates(self):
        self.saved_coordinates.clear(); self.update()

    def paintEvent(self, event):
        painter = QPainter(self); painter.drawPixmap(0, 0, self.pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # Transparent, page-bound highlight overlay.  Geometry stays in PDF
        # points and is scaled only while painting, so zoom and window resize
        # never require text extraction or a new parser run.
        for marking in self.page_markings():
            color = QColor(marking.color)
            fill = QColor(color); fill.setAlpha(58 if marking.status.value == "ERKANNT" else 70)
            selected = bool(self.selected_field_path) and marking.field_path == self.selected_field_path
            pen = QPen(color, 2.2 if selected else 1.2)
            if marking.ambiguous:
                pen.setStyle(Qt.DashLine)
            painter.setPen(pen); painter.setBrush(fill)
            for quad in marking.quads:
                painter.drawPolygon(self._screen_polygon(quad))

        painter.setPen(QPen(QColor("#f9a825"), 1)); painter.setBrush(QColor(255, 213, 79, 100))
        polygons = list(self.selection.bounds()) if self.selection and self.selection.isValid() else []
        for page, coordinates in self.saved_coordinates:
            if page == self.page_index + 1 and coordinates and coordinates.get("coordinate_system") == "PDF_POINTS":
                polygons.extend(QPolygonF([QPointF(*point) for point in quad]) for quad in coordinates.get("quads", ()))
        for polygon in polygons: painter.drawPolygon(self._screen_polygon(polygon))

    def _menu(self, position):
        menu = QMenu(self)
        groups = self.markings_at(position)
        selection = self.current_selection()
        if selection is None and groups:
            first = groups[0]
            selection = PdfCoordinateSelection(
                first.page_number, first.text, first.start, first.end,
                {"coordinate_system": "PDF_POINTS", "quads": [list(map(list, quad)) for quad in first.quads]},
                first.field_path, tuple(groups))
        copy = QAction("Text kopieren", self); copy.setEnabled(selection is not None)
        copy.triggered.connect(lambda: QApplication.clipboard().setText(selection.text) if selection else None); menu.addAction(copy)
        if groups:
            menu.addSeparator()
            for marking in groups:
                label = QAction(f"{marking.label}: {marking.value or '—'} [{marking.origin}]", self)
                label.setEnabled(False); menu.addAction(label)
        for label, action in (("Parserfeld zuordnen", "map"), ("Als Referenzwert übernehmen", "reference"),
                              ("Neue Felddefinition anlegen", "new"), ("Vorhandene Zuordnung bearbeiten", "edit"),
                              ("Annotation entfernen", "remove"), ("Fundstelle hervorheben", "locate")):
            item = QAction(label, self); item.setEnabled(selection is not None or action in {"edit", "remove"})
            item.triggered.connect(lambda checked=False, name=action: self.actionRequested.emit(name, selection)); menu.addAction(item)
        menu.exec(self.mapToGlobal(position))


class DirectPdfView(QScrollArea):
    actionRequested = Signal(str, object)
    selectionChanged = Signal(object)
    markingActivated = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent); self.canvas = PdfPageCanvas(); self.setWidget(self.canvas); self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignCenter); self.canvas.actionRequested.connect(self.actionRequested)
        self.canvas.selectionChanged.connect(self.selectionChanged)
        self.canvas.markingActivated.connect(self.markingActivated)

    def setDocument(self, document): self.canvas.set_document(document)
    def setPage(self, page_index): self.canvas.set_page(page_index)
    def zoomFactor(self): return self.canvas.zoom
    def setZoomFactor(self, factor): self.canvas.set_zoom(factor)
    def currentSelection(self): return self.canvas.current_selection()
    def addSavedCoordinates(self, page, coordinates): self.canvas.add_saved_coordinates(page, coordinates)
    def clearSavedCoordinates(self): self.canvas.clear_saved_coordinates()
    def setSelectionByIndex(self, page, start, length): return self.canvas.set_selection_by_index(page, start, length)
    def setPageRotations(self, rotations): self.canvas.page_rotations = dict(rotations)

    def setMarkings(self, markings): self.canvas.set_markings(markings)
    def markings(self): return list(self.canvas.markings)
    def setMarkingOptions(self, enabled=True, scope="all", field_path=""):
        self.canvas.set_marking_options(enabled, scope, field_path)
    def pageMarkings(self, page_number=None): return self.canvas.page_markings(page_number)

    def focusMarking(self, field_path):
        matches = [item for item in self.canvas._visible_markings() if item.field_path == field_path and item.quads]
        if not matches:
            return False
        marker = matches[0]
        self.setPage(marker.page_number - 1)
        # Re-read the marker after the page switch: the canvas may have
        # re-rendered the pixmap at a different size.
        current = next((item for item in self.canvas.page_markings(marker.page_number)
                        if item.field_path == field_path), marker)
        if current.quads and not self.canvas.pixmap.isNull():
            points = [self.canvas._screen_points(QPointF(*point)) for point in current.quads[0]]
            center = QRectF(points[0], QSize(1, 1)).center()
            for point in points[1:]:
                center = (center + point) / 2
            self.horizontalScrollBar().setValue(int(center.x() - self.viewport().width() / 2))
            self.verticalScrollBar().setValue(int(center.y() - self.viewport().height() / 2))
        return True
