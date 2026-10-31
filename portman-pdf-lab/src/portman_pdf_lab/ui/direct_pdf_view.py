"""Coordinate-accurate PDF page rendering and direct text selection using Qt PDF."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
import logging
import math
from typing import Any

from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QMouseEvent, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication, QMenu, QScrollArea, QToolTip, QWidget

from .pdf_markings import PdfMarking, _coordinate_quads, group_at_anchor

logger = logging.getLogger(__name__)


def _as_point(value: Any) -> QPointF | None:
    """Normalize a PDF/screen point from Qt, tuple/list or mapping data.

    Persisted annotation quads are plain ``[[x, y], ...]`` lists, while Qt
    selections expose ``QPointF``.  Both reach the same canvas methods, so all
    coordinate consumers go through this single validator.  Non-finite values,
    booleans and malformed sequences are rejected instead of raising later.
    """

    x = y = None
    if isinstance(value, QPointF):
        x, y = value.x(), value.y()
    elif isinstance(value, (list, tuple)):
        if len(value) >= 2:
            x, y = value[0], value[1]
    elif hasattr(value, "x") and hasattr(value, "y"):
        try:
            x, y = value.x(), value.y()
            if callable(x):
                x = x()
            if callable(y):
                y = y()
        except (TypeError, ValueError, RuntimeError):
            return None
    elif isinstance(value, dict):
        x, y = value.get("x"), value.get("y")
    if x is None or y is None or isinstance(x, bool) or isinstance(y, bool):
        return None
    try:
        x, y = float(x), float(y)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(x) or not math.isfinite(y):
        return None
    return QPointF(x, y)


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
    zoomRequested = Signal(float, object)

    def __init__(self, parent=None):
        super().__init__(parent); self.document = None; self.page_index = 0; self.zoom = 1.0
        self.pixmap = QPixmap(); self.anchor = None; self.selection = None; self.saved_coordinates = []
        self.page_rotations = {}
        self.markings: list[PdfMarking] = []
        self.markings_enabled = True
        self.marking_scope = "all"
        self.selected_field_path = ""
        self.scroll_area = None
        self._pressed_groups = None
        self._hovered_key = None
        self._page_size = None
        self._polygon_cache: dict[int, list[QPolygonF]] = {}
        self._space_pressed = False
        self._panning = False
        self._pan_origin = None
        self._pan_scroll = (0, 0)
        self.setMouseTracking(True); self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setFocusPolicy(Qt.StrongFocus)
        self.customContextMenuRequested.connect(self._menu)

    def set_document(self, document):
        self.document = document; self._invalidate_geometry(); self.render_page()

    def set_page(self, page_index):
        self.page_index = page_index; self.selection = None
        self._invalidate_geometry(); self.render_page()

    def set_zoom(self, factor):
        self.zoom = max(0.25, min(8.0, factor))
        self._invalidate_geometry(); self.render_page()

    def set_markings(self, markings):
        self.markings = list(markings)
        self._hovered_key = None
        self._polygon_cache.clear()
        self.update()

    def set_marking_options(self, enabled=True, scope="all", field_path=""):
        self.markings_enabled = bool(enabled)
        self.marking_scope = scope
        self.selected_field_path = field_path or ""
        self.update()

    def _invalidate_geometry(self):
        self._page_size = None
        self._polygon_cache.clear()

    def resizeEvent(self, event):
        # Page geometry is mapped against the pixmap, but a widget resize is a
        # cheap and safe point to drop any stale screen polygons.
        self._polygon_cache.clear()
        super().resizeEvent(event)

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

    def _current_page_size(self):
        if self._page_size is not None:
            return self._page_size if not self._page_size.isEmpty() else None
        if not self.document:
            return None
        try:
            size = self.document.pagePointSize(self.page_index)
        except (RuntimeError, AttributeError):
            return None
        if size is None or size.width() <= 0 or size.height() <= 0:
            return None
        self._page_size = size
        return size

    def render_page(self):
        try:
            if not self.document or self.document.pageCount() <= self.page_index: return
        except RuntimeError:  # QObject teardown may race a final status signal
            return
        points = self.document.pagePointSize(self.page_index)
        size = QSize(max(1, round(points.width() * self.zoom)), max(1, round(points.height() * self.zoom)))
        self.pixmap = QPixmap.fromImage(self.document.render(self.page_index, size))
        self._page_size = points if points.width() > 0 and points.height() > 0 else None
        self._polygon_cache.clear()
        self.resize(self.pixmap.size()); self.setMinimumSize(self.pixmap.size()); self.update()

    def _valid_geometry(self):
        size = self._current_page_size()
        if size is None or self.pixmap.isNull() or self.pixmap.width() <= 0 or self.pixmap.height() <= 0:
            return None
        return size

    def _pdf_point(self, point):
        geometry = self._valid_geometry()
        candidate = _as_point(point)
        if geometry is None or candidate is None:
            return QPointF()
        return QPointF(candidate.x() * geometry.width() / self.pixmap.width(),
                       candidate.y() * geometry.height() / self.pixmap.height())

    def _polygon(self, quad, context=""):
        """Validate a quad and return PDF-point vertices, or ``None``."""
        if isinstance(quad, QPolygonF):
            values = list(quad)
        elif isinstance(quad, (list, tuple)):
            values = list(quad)
        else:
            logger.warning("Invalid PDF polygon %s: unsupported type %s", context or "-", type(quad).__name__)
            return None
        if len(values) < 3:
            logger.warning("Invalid PDF polygon %s: %d point(s)", context or "-", len(values))
            return None
        points = []
        for item in values:
            point = _as_point(item)
            if point is None:
                logger.warning("Invalid PDF polygon %s: bad point %r", context or "-", item)
                return None
            points.append(point)
        return points

    def _screen_polygon(self, quad, context=""):
        """Map PDF-point quad to widget coordinates using one validator.

        ``QPdfDocument.pagePointSize`` already reports the rotated page size and
        ``QPdfSelection.bounds``/stored quads use that same display coordinate
        space, so zoom, rotation, page size and DPI all reduce to this single
        pixmap scale.  Invalid quads never raise and never get an invented box.
        """
        geometry = self._valid_geometry()
        if geometry is None:
            return QPolygonF()
        points = self._polygon(quad, context)
        if points is None:
            return QPolygonF()
        return QPolygonF([QPointF(point.x() * self.pixmap.width() / geometry.width(),
                                  point.y() * self.pixmap.height() / geometry.height())
                          for point in points])

    def _screen_point(self, point, context=""):
        candidate = _as_point(point)
        geometry = self._valid_geometry()
        if candidate is None:
            logger.warning("Invalid PDF point %s: %r", context or "-", point)
            return None
        if geometry is None:
            return None
        return QPointF(candidate.x() * self.pixmap.width() / geometry.width(),
                       candidate.y() * self.pixmap.height() / geometry.height())

    def _screen_points(self, point, context=""):
        """Backward-compatible point mapper returning an empty point on error."""
        return self._screen_point(point, context) or QPointF()

    def _marking_polygons(self, marking):
        """Cached screen polygons shared by painting and hit testing."""
        cached = self._polygon_cache.get(id(marking))
        if cached is not None:
            return cached
        polygons = []
        for index, quad in enumerate(marking.quads):
            polygon = self._screen_polygon(
                quad, f"page {marking.page_number}, field {marking.field_path}, quad {index}")
            if not polygon.isEmpty():
                polygons.append(polygon)
        self._polygon_cache[id(marking)] = polygons
        return polygons

    def _serialize(self, selection, page_size):
        quads = [[[point.x(), point.y()] for point in polygon] for polygon in selection.bounds()]
        return {"coordinate_system": "PDF_POINTS", "quads": quads,
                "page_width": page_size.width(), "page_height": page_size.height(),
                "rotation": int(self.page_rotations.get(self.page_index + 1, 0)) % 360,
                "start_index": selection.startIndex(), "end_index": selection.endIndex()}

    def markings_at(self, position, page_number=None):
        """Return all fields whose visible highlight contains the screen point."""
        point = _as_point(position)
        if point is None or not self.document or self.pixmap.isNull():
            return []
        page_number = self.page_index + 1 if page_number is None else page_number
        hits = []
        for marking in self.page_markings(page_number):
            for polygon in self._marking_polygons(marking):
                if polygon.containsPoint(point, Qt.OddEvenFill):
                    hits.append(marking)
                    break
        if not hits:
            return []
        first = hits[0]
        return group_at_anchor(hits, first.page_number, first.start, first.end) if first.start < first.end else hits

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MiddleButton or (
                event.button() == Qt.LeftButton and self._space_pressed):
            self._begin_pan(event.position())
            event.accept()
            return
        if event.button() == Qt.LeftButton and self.document:
            groups = self.markings_at(event.position())
            if groups:
                self._pressed_groups = groups
                event.accept()
                return
            self.anchor = self._pdf_point(event.position()); self.selection = None; self.update(); event.accept(); return
        super().mousePressEvent(event)

    def _begin_pan(self, position):
        self._panning = True
        self._pan_origin = _as_point(position)
        area = self.scroll_area
        self._pan_scroll = (area.horizontalScrollBar().value(),
                            area.verticalScrollBar().value()) if area is not None else (0, 0)
        self.setCursor(Qt.ClosedHandCursor)

    def _pan_to(self, position):
        if not self._panning or self._pan_origin is None or self.scroll_area is None:
            return False
        current = _as_point(position)
        if current is None:
            return True
        delta = current - self._pan_origin
        self.scroll_area.horizontalScrollBar().setValue(
            int(self._pan_scroll[0] - delta.x()))
        self.scroll_area.verticalScrollBar().setValue(
            int(self._pan_scroll[1] - delta.y()))
        return True

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._panning and event.buttons() & (Qt.MiddleButton | Qt.LeftButton):
            self._pan_to(event.position())
            event.accept(); return
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
        if self._panning:
            self._panning = False
            self._pan_origin = None
            self.unsetCursor()
            event.accept(); return
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

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_pressed = True
            if not self._panning:
                self.setCursor(Qt.OpenHandCursor)
            event.accept(); return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_pressed = False
            if not self._panning:
                self.unsetCursor()
            event.accept(); return
        super().keyReleaseEvent(event)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta:
            self.zoomRequested.emit(1.2 if delta > 0 else 1 / 1.2, event.position())
            event.accept(); return
        super().wheelEvent(event)

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
        if isinstance(coordinates, Mapping):
            system = str(coordinates.get("coordinate_system") or "").upper()
            if system and system != "PDF_POINTS":
                logger.warning("Ignoring saved annotation on page %s with unknown coordinate system %r",
                               page_number, coordinates.get("coordinate_system"))
                return
        quads = _coordinate_quads(coordinates)
        if not quads:
            logger.warning("Ignoring saved annotation on page %s: no valid PDF-point quads", page_number)
            return
        self.saved_coordinates.append((page_number, {
            "coordinate_system": "PDF_POINTS",
            "quads": [[[point[0], point[1]] for point in quad] for quad in quads],
        }))
        self.update()

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
            for polygon in self._marking_polygons(marking):
                painter.drawPolygon(polygon)

        painter.setPen(QPen(QColor("#f9a825"), 1)); painter.setBrush(QColor(255, 213, 79, 100))
        polygons = list(self.selection.bounds()) if self.selection and self.selection.isValid() else []
        for page, coordinates in self.saved_coordinates:
            if page == self.page_index + 1 and isinstance(coordinates, Mapping) \
                    and coordinates.get("coordinate_system") == "PDF_POINTS":
                # Keep stored lists raw; _screen_polygon validates each point.
                polygons.extend(coordinates.get("quads", ()))
        for polygon in polygons:
            screen = self._screen_polygon(polygon, "saved coordinate selection")
            if not screen.isEmpty():
                painter.drawPolygon(screen)

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
        self.canvas.scroll_area = self
        self.setAlignment(Qt.AlignCenter); self.canvas.actionRequested.connect(self.actionRequested)
        self.canvas.selectionChanged.connect(self.selectionChanged)
        self.canvas.markingActivated.connect(self.markingActivated)
        self.canvas.zoomRequested.connect(self._zoom_at)

    def setDocument(self, document): self.canvas.set_document(document)
    def setPage(self, page_index): self.canvas.set_page(page_index)
    def zoomFactor(self): return self.canvas.zoom
    def setZoomFactor(self, factor): self.canvas.set_zoom(factor)

    def _zoom_at(self, factor, position):
        """Zoom around the mouse position while keeping that point stable."""
        old_zoom = max(1e-9, float(self.canvas.zoom))
        new_zoom = max(0.25, min(8.0, old_zoom * float(factor)))
        if abs(new_zoom - old_zoom) < 1e-9:
            return
        point = _as_point(position) or QPointF()
        viewport_point = self.canvas.mapTo(self.viewport(), point.toPoint())
        self.canvas.set_zoom(new_zoom)
        ratio = new_zoom / old_zoom
        target = QPointF(point.x() * ratio, point.y() * ratio)
        self.horizontalScrollBar().setValue(int(target.x() - viewport_point.x()))
        self.verticalScrollBar().setValue(int(target.y() - viewport_point.y()))
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
        polygons = self.canvas._marking_polygons(current)
        if polygons:
            center = polygons[0].boundingRect().center()
            self.horizontalScrollBar().setValue(int(center.x() - self.viewport().width() / 2))
            self.verticalScrollBar().setValue(int(center.y() - self.viewport().height() / 2))
        return True
