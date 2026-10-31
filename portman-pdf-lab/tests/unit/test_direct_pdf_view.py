"""Regression tests for PDF overlay geometry and pointer interaction."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPixmap, QWheelEvent
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QApplication
from pypdf import PdfWriter

import portman_pdf_lab.ui.direct_pdf_view as direct_pdf_view
from portman_pdf_lab.synthetic_pdf import create_demo_pdf
from portman_pdf_lab.ui.direct_pdf_view import DirectPdfView, PdfMarking, PdfPageCanvas, _as_point
from portman_pdf_lab.ui.pdf_markings import ORIGIN_PARSER
from portman_pdf_lab.ui.result_view import RecognitionStatus

TEXT = """comdirect
Wertpapierkauf
WKN / ISIN: ABC123 / DE0008474511
Valuta 04.02.2026
Zu Ihren Lasten EUR 126,50"""

QUAD = ((100.0, 100.0), (220.0, 100.0), (220.0, 115.0), (100.0, 115.0))


def app():
    return QApplication.instance() or QApplication([])


def load_document(path):
    document = QPdfDocument()
    document.load(str(path))
    assert document.pageCount() >= 1
    return document


def marker(quad=QUAD, page=1, status=RecognitionStatus.RECOGNIZED,
           field="events[0].trades[0].isin", label="ISIN", value="DE0008474511"):
    return PdfMarking(field, label, value, status, ORIGIN_PARSER, "parser.one", "", "ev",
                      page, 1, 2, value, (quad,), False, False, "", 1, 1)


def canvas_for(document, page=0):
    application = app()
    canvas = PdfPageCanvas()
    canvas.set_document(document)
    if page:
        canvas.set_page(page)
    application.processEvents()
    return canvas


@pytest.fixture
def demo_pdf(tmp_path):
    return create_demo_pdf(tmp_path / "demo.pdf", TEXT)


def mouse_event(kind, position, button=Qt.NoButton, buttons=Qt.NoButton):
    point = QPointF(*position) if not isinstance(position, QPointF) else position
    return QMouseEvent(kind, point, point, button, buttons, Qt.NoModifier)


class RecordingToolTip:
    shown = []

    @staticmethod
    def showText(_position, text, _widget=None):
        RecordingToolTip.shown.append(text)

    @staticmethod
    def hideText():
        pass


# -- coordinate normalization ------------------------------------------------

def test_point_conversion_accepts_qt_tuples_and_lists():
    assert _as_point(QPointF(1.5, 2.5)) == QPointF(1.5, 2.5)
    assert _as_point(QPoint(3, 4)) == QPointF(3.0, 4.0)
    assert _as_point((5, 6)) == QPointF(5.0, 6.0)
    assert _as_point([7.5, 8.5]) == QPointF(7.5, 8.5)
    assert _as_point({"x": 9, "y": 10}) == QPointF(9.0, 10.0)


@pytest.mark.parametrize("value", [
    None, "1,2", (1,), [1], (1, "bad"), (float("nan"), 2), (2, float("inf")),
    (True, 2), object(),
])
def test_point_conversion_rejects_invalid_and_non_finite_values(value):
    assert _as_point(value) is None


def test_four_point_quad_is_scaled_to_screen(demo_pdf):
    canvas = canvas_for(load_document(demo_pdf))
    polygon = canvas._screen_polygon([(10, 20), (30, 20), (30, 40), (10, 40)])
    assert polygon.count() == 4
    assert polygon[0] == QPointF(10.0, 20.0)
    assert polygon[2] == QPointF(30.0, 40.0)


def test_invalid_quads_are_rejected_without_drawing_or_hit_testing(demo_pdf, caplog):
    canvas = canvas_for(load_document(demo_pdf))
    for bad in (None, [(1, 2)], [(1, 2), (3, 4)],
                [(1, 2), (3, 4), (float("nan"), 6)], [object(), (1, 2), (3, 4)]):
        assert canvas._screen_polygon(bad).isEmpty()

    bad_marker = PdfMarking("field", "Feld", "Wert", RecognitionStatus.RECOGNIZED,
                            ORIGIN_PARSER, page_number=1, quads=(((1, 2), (3, 4), ("x", 6)),))
    canvas.set_markings([bad_marker])
    assert canvas.markings_at((2, 3)) == []
    with caplog.at_level("WARNING"):
        canvas._marking_polygons(bad_marker)
    assert "Invalid PDF polygon" in caplog.text


def test_saved_annotation_coordinates_are_validated_and_do_not_break_painting(demo_pdf, caplog):
    canvas = canvas_for(load_document(demo_pdf))
    canvas.add_saved_coordinates(1, [[10, 20, 30, 40]])
    canvas.add_saved_coordinates(1, {"coordinate_system": "SCREEN_PIXELS", "quads": [[[0, 0]]]})
    canvas.add_saved_coordinates(1, "broken")
    assert len(canvas.saved_coordinates) == 1
    with caplog.at_level("WARNING"):
        canvas.add_saved_coordinates(1, {"coordinate_system": "PDF_POINTS",
                                         "quads": [[(1, 2), (3, 4), (float("inf"), 6)]]})
    assert "no valid PDF-point quads" in caplog.text
    pixmap = QPixmap(canvas.size())
    canvas.render(pixmap)  # legacy [x, y, width, height] is converted, never crashes


# -- pointer interaction -----------------------------------------------------

def test_mouse_move_over_recognized_value_shows_tooltip(demo_pdf, monkeypatch):
    canvas = canvas_for(load_document(demo_pdf))
    canvas.set_markings([marker()])
    RecordingToolTip.shown = []
    monkeypatch.setattr(direct_pdf_view, "QToolTip", RecordingToolTip)
    canvas.mouseMoveEvent(mouse_event(QEvent.MouseMove, (150, 108)))
    assert canvas.cursor().shape() == Qt.PointingHandCursor
    assert RecordingToolTip.shown
    assert "Feld: ISIN" in RecordingToolTip.shown[-1]
    assert "Wert: DE0008474511" in RecordingToolTip.shown[-1]
    assert "Seite: 1" in RecordingToolTip.shown[-1]


def test_clicking_green_marker_activates_field(demo_pdf):
    canvas = canvas_for(load_document(demo_pdf))
    expected = marker()
    canvas.set_markings([expected])
    activated = []
    canvas.markingActivated.connect(activated.append)
    canvas.mousePressEvent(mouse_event(QEvent.MouseButtonPress, (150, 108), Qt.LeftButton, Qt.LeftButton))
    canvas.mouseReleaseEvent(mouse_event(QEvent.MouseButtonRelease, (150, 108), Qt.LeftButton, Qt.NoButton))
    assert activated == [[expected]]


def test_clicking_outside_marker_starts_text_selection_instead(demo_pdf):
    canvas = canvas_for(load_document(demo_pdf))
    canvas.set_markings([marker()])
    activated = []
    canvas.markingActivated.connect(activated.append)
    canvas.mousePressEvent(mouse_event(QEvent.MouseButtonPress, (400, 400), Qt.LeftButton, Qt.LeftButton))
    canvas.mouseReleaseEvent(mouse_event(QEvent.MouseButtonRelease, (400, 400), Qt.LeftButton, Qt.NoButton))
    assert activated == []
    assert canvas.anchor is None


# -- zoom, resize and rotation ----------------------------------------------

def test_selection_geometry_follows_zoom_and_resize(demo_pdf):
    document = load_document(demo_pdf)
    canvas = canvas_for(document)
    text = document.getAllText(0).text()
    start = text.index("DE0008474511")
    assert canvas.set_selection_by_index(1, start, len("DE0008474511"))
    selection = canvas.current_selection()
    assert selection is not None
    original = canvas._screen_polygon(selection.coordinates["quads"][0])
    assert not original.isEmpty()

    canvas.set_zoom(2.0)
    canvas.resize(300, 200)
    zoomed = canvas.current_selection()
    assert zoomed is not None
    scaled = canvas._screen_polygon(zoomed.coordinates["quads"][0])
    assert not scaled.isEmpty()
    assert scaled[0].x() == pytest.approx(original[0].x() * 2, abs=1.5)
    assert scaled[0].y() == pytest.approx(original[0].y() * 2, abs=1.5)


def test_rotated_page_coordinates_are_hit_and_drawn(tmp_path):
    source = create_demo_pdf(tmp_path / "rotated-source.pdf", TEXT)
    writer = PdfWriter(clone_from=str(source))
    for page in writer.pages:
        page.rotate(90)
    rotated = tmp_path / "rotated.pdf"
    with open(rotated, "wb") as stream:
        writer.write(stream)

    document = load_document(rotated)
    size = document.pagePointSize(0)
    assert size.width() > size.height()  # /Rotate 90 swaps the display size
    text = document.getAllText(0).text()
    start = text.index("DE0008474511")
    selection = document.getSelectionAtIndex(0, start, len("DE0008474511"))
    quad = tuple((point.x(), point.y()) for point in selection.bounds()[0])
    canvas = canvas_for(document)
    rotated_marker = marker(quad=quad)
    canvas.set_markings([rotated_marker])

    polygon = canvas._screen_polygon(quad)
    assert not polygon.isEmpty()
    assert polygon.boundingRect().right() <= canvas.pixmap.width()
    assert polygon.boundingRect().bottom() <= canvas.pixmap.height()
    center = polygon.boundingRect().center()
    assert canvas.markings_at((center.x(), center.y())) == [rotated_marker]


def test_markings_on_multiple_pages_are_page_bound(tmp_path):
    source = create_demo_pdf(tmp_path / "pages-source.pdf", TEXT)
    writer = PdfWriter(clone_from=str(source))
    writer.add_blank_page(width=612, height=792)
    multi = tmp_path / "pages.pdf"
    with open(multi, "wb") as stream:
        writer.write(stream)

    document = load_document(multi)
    assert document.pageCount() == 2
    canvas = canvas_for(document)
    second = marker(page=2, field="events[0].trades[0].wkn", label="WKN", value="ABC123")
    canvas.set_markings([marker(), second])
    assert [item.field_path for item in canvas.page_markings(1)] == ["events[0].trades[0].isin"]
    assert [item.field_path for item in canvas.page_markings(2)] == ["events[0].trades[0].wkn"]
    assert canvas.markings_at((150, 108)) == [marker()]

    canvas.set_page(1)
    assert canvas.markings_at((150, 108)) == [second]
    assert not canvas._screen_polygon(second.quads[0]).isEmpty()


# -- zoom and pan keep selection behaviour intact -----------------------------

def test_wheel_zoom_is_anchored_at_cursor_and_keeps_left_selection(demo_pdf):
    application = app()
    view = DirectPdfView()
    view.resize(500, 400)
    view.setDocument(load_document(demo_pdf))
    application.processEvents()
    before = view.zoomFactor()
    event = QWheelEvent(QPointF(120, 90), QPointF(120, 90), QPoint(0, 0), QPoint(0, 120),
                        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    view.canvas.wheelEvent(event)
    application.processEvents()
    assert view.zoomFactor() > before
    # Wheel zoom never starts a text selection or consumes the left button.
    assert view.canvas.anchor is None
    out = QWheelEvent(QPointF(120, 90), QPointF(120, 90), QPoint(0, 0), QPoint(0, -120),
                      Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    view.canvas.wheelEvent(out)
    assert view.zoomFactor() == pytest.approx(before, abs=1e-6)


class _Bar:
    def __init__(self):
        self._value = 0

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = int(value)


class _Area:
    def __init__(self):
        self.horizontal = _Bar()
        self.vertical = _Bar()

    def horizontalScrollBar(self):
        return self.horizontal

    def verticalScrollBar(self):
        return self.vertical


def test_middle_button_and_space_left_pan_scroll_instead_of_selecting(demo_pdf):
    canvas = canvas_for(load_document(demo_pdf))
    area = _Area()
    canvas.scroll_area = area

    canvas.mousePressEvent(mouse_event(QEvent.MouseButtonPress, (100, 100),
                                       Qt.MiddleButton, Qt.MiddleButton))
    canvas.mouseMoveEvent(mouse_event(QEvent.MouseMove, (140, 130),
                                      Qt.NoButton, Qt.MiddleButton))
    canvas.mouseReleaseEvent(mouse_event(QEvent.MouseButtonRelease, (140, 130),
                                         Qt.MiddleButton, Qt.NoButton))
    assert (area.horizontal.value(), area.vertical.value()) == (-40, -30)
    assert canvas.anchor is None

    area.horizontal.setValue(0)
    area.vertical.setValue(0)
    canvas._space_pressed = True
    canvas.mousePressEvent(mouse_event(QEvent.MouseButtonPress, (200, 200),
                                       Qt.LeftButton, Qt.LeftButton))
    canvas.mouseMoveEvent(mouse_event(QEvent.MouseMove, (170, 180),
                                      Qt.LeftButton, Qt.LeftButton))
    canvas.mouseReleaseEvent(mouse_event(QEvent.MouseButtonRelease, (170, 180),
                                         Qt.LeftButton, Qt.NoButton))
    assert (area.horizontal.value(), area.vertical.value()) == (30, 20)
    assert canvas.anchor is None

