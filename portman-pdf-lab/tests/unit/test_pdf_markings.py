"""Evidence-driven PDF marking tests (no Qt widgets required)."""

from __future__ import annotations

from portman_pdf_lab.field_catalog import CatalogStore
from portman_pdf_lab.ui.pdf_markings import (
    ORIGIN_PARSER, ORIGIN_RULE, ORIGIN_USER, MarkingSpec, PdfMarking,
    _coordinate_quads, collect_marking_specs, group_at_anchor,
    resolve_marking_specs, text_layer_markers, value_terms,
)
from portman_pdf_lab.ui.result_view import RecognitionStatus


class _Point:
    def __init__(self, x, y):
        self._x, self._y = float(x), float(y)

    def x(self):
        return self._x

    def y(self):
        return self._y


class _Selection:
    """Minimal stand-in for the parts of QPdfSelection the resolver uses."""

    def __init__(self, quads):
        self._quads = quads

    def isValid(self):
        return True

    def bounds(self):
        return [[_Point(*point) for point in polygon] for polygon in self._quads]


def _provider(record=None, quads=(((0, 0), (10, 0), (10, 5), (0, 5)),)):
    def provide(page, start, length):
        if record is not None:
            record.append((page, start, length))
        return _Selection(quads)
    return provide


def _spec(value="", excerpt="", *, status=RecognitionStatus.RECOGNIZED, origin=ORIGIN_PARSER,
          page=1, terms=None, field="field", note="", forced=(), forced_text=""):
    return MarkingSpec(field, "Feld", value, status, origin, "parser.one", "", "ev", page,
                       (excerpt,) if excerpt else (), value_terms(value, excerpt) if terms is None else terms,
                       note, forced, forced_text)


def _report(result, evidence=(), **extra):
    payload = {"plugin_id": "parser.one", "evidence": list(evidence), **result}
    report = {"result": payload, "detection": {"plugin_id": "parser.one"}}
    report.update(extra)
    return report


# -- coordinate resolution --------------------------------------------------

def test_unique_value_is_green_with_pdf_quads():
    record = []
    markers = resolve_marking_specs(
        [_spec("126,50", "Zu Ihren Lasten EUR 126,50")],
        {1: "Kopf\nZu Ihren Lasten EUR 126,50\nFuß"}, _provider(record))
    assert len(markers) == 1
    marker = markers[0]
    assert marker.status == RecognitionStatus.RECOGNIZED and not marker.ambiguous
    assert marker.text == "126,50" and marker.quads and not marker.fallback
    assert record and record[0][0] == 1 and record[0][2] - record[0][1] == len("126,50")


def test_whitespace_normalization_and_printed_number_date_variants():
    normalized = resolve_marking_specs(
        [_spec("", "Zu Ihren Lasten EUR 126,50", status=RecognitionStatus.REVIEW)],
        {1: "Zu Ihren Lasten\r\nEUR 126,50"}, None)[0]
    assert normalized.text.replace("\r\n", " ") == "Zu Ihren Lasten EUR 126,50"
    assert not normalized.ambiguous and normalized.fallback

    deferred = resolve_marking_specs(
        [_spec("126.50", "Zu Ihren Lasten EUR 126,50")],
        {1: "Zu Ihren Lasten\r\nEUR 126,50"}, None)[0]
    assert deferred.text == "126,50" and not deferred.ambiguous and deferred.fallback

    date = resolve_marking_specs(
        [_spec("2026-02-04", "Valuta 04.02.2026")],
        {1: "Valuta 04.02.2026"}, None)[0]
    assert date.text == "04.02.2026" and date.status == RecognitionStatus.RECOGNIZED


def test_printed_absolute_amount_matches_signed_parser_value():
    marker = resolve_marking_specs(
        [_spec("-126.50", "Zu Ihren Lasten EUR 126,50")],
        {1: "Zu Ihren Lasten EUR 126,50"}, None)[0]
    assert marker.text == "126,50" and not marker.ambiguous


def test_repeated_value_or_repeated_excerpt_without_anchor_is_yellow():
    repeated = resolve_marking_specs([_spec("10,00")], {1: "Betrag 10,00\nBetrag 10,00"}, None)
    assert len(repeated) == 2
    assert all(item.status == RecognitionStatus.REVIEW and item.ambiguous for item in repeated)

    excerpts = resolve_marking_specs([_spec("", "Konto", status=RecognitionStatus.REVIEW)],
                                     {1: "Konto 111\nKonto 222"}, None)
    assert len(excerpts) == 2 and all(item.ambiguous for item in excerpts)


def test_repeated_excerpt_with_unique_value_is_resolved_to_the_value():
    markers = resolve_marking_specs([_spec("222", "Konto")], {1: "Konto 111\nKonto 222"}, None)
    assert len(markers) == 1
    assert markers[0].text == "222" and not markers[0].ambiguous


def test_value_not_present_in_evidence_never_creates_a_box_at_the_excerpt():
    markers = resolve_marking_specs([_spec("event-123", "Zu Ihren Lasten EUR 126,50")],
                                    {1: "Zu Ihren Lasten EUR 126,50"}, None)
    assert markers == []


def test_text_layer_fallback_is_explicitly_marked():
    markers = text_layer_markers([_spec("126,50", "Zu Ihren Lasten EUR 126,50")],
                                 {1: "Zu Ihren Lasten EUR 126,50"})
    assert len(markers) == 1 and markers[0].fallback and markers[0].quads == ()


def test_multiple_fields_at_one_location_are_grouped():
    specs = [_spec("126,50", "Zu Ihren Lasten EUR 126,50", field="a"),
             _spec("126,50", "Zu Ihren Lasten EUR 126,50", field="b")]
    markers = resolve_marking_specs(specs, {1: "Zu Ihren Lasten EUR 126,50"}, None)
    assert len(markers) == 2
    grouped = group_at_anchor(markers, 1, markers[0].start, markers[0].end)
    assert {item.field_path for item in grouped} == {"a", "b"}
    assert "Feld: Feld" in markers[0].tooltip_lines()[0]
    assert any(line.startswith("Herkunft: Bestehender Parser") for line in markers[0].tooltip_lines())


# -- collector status rules -------------------------------------------------

def test_missing_required_with_evidence_is_red_optional_missing_is_grey(tmp_path):
    catalog = CatalogStore(tmp_path).catalog(document_type="Kauf")
    evidence = [{"evidence_id": "ev", "page_number": 1, "excerpt": "Wertpapier ETF"}]
    report = _report({
        "events": [{"trades": [{"isin": "DE0008474511", "wkn": "NOT_FOUND",
                                "security_name": "NOT_FOUND", "evidence_ids": ["ev"]}]}],
    }, evidence)
    specs = collect_marking_specs(report, catalog)
    by_path = {item.field_path: item for item in specs}
    assert by_path["events[0].trades[0].security_name"].status == RecognitionStatus.MISSING
    assert "events[0].trades[0].wkn" not in by_path  # optional/not applicable: no PDF mark
    markers = resolve_marking_specs(specs, {1: "Wertpapier ETF"}, None)
    red = [item for item in markers if item.field_path == "events[0].trades[0].security_name"]
    assert red and red[0].status == RecognitionStatus.MISSING and red[0].fallback
    assert not [item for item in markers if item.field_path == "events[0].trades[0].wkn"]


def test_missing_value_without_evidence_has_no_marker(tmp_path):
    catalog = CatalogStore(tmp_path).catalog(document_type="Kauf")
    report = _report({"events": [{"trades": [{"security_name": "NOT_FOUND"}]}]})
    specs = collect_marking_specs(report, catalog)
    assert specs == []
    assert resolve_marking_specs(specs, {1: "irgendein Text"}, None) == []


def test_standard_extended_and_compare_provenance(tmp_path):
    evidence = [{"evidence_id": "ev", "page_number": 1, "excerpt": "Betrag 126,50"}]
    result = {"events": [{"cash_movements": [{"amount": "126.50", "evidence_ids": ["ev"]}]}]}
    decisions = [{"field_path": "events[0].cash_movements[0].amount", "standard_value": "126.50",
                  "effective_value": "127.50", "rule_value": "127.50", "conflict": False, "rule_id": "r1"}]
    comparison = [{"field": "events[0].cash_movements[0].amount", "standard": "126.50",
                   "extended": "127.50", "rule": "127.50", "conflict": False, "rule_id": "r1"}]
    report = _report(result, evidence, rule_decisions=decisions, rule_comparison=comparison)
    catalog = CatalogStore(tmp_path).catalog(document_type="Kauf")

    standard = collect_marking_specs(report, catalog, "STANDARD")
    assert standard and all(item.origin == ORIGIN_PARSER for item in standard)
    assert not [item for item in standard if item.rule_id]

    extended = collect_marking_specs(report, catalog, "EXTENDED")
    rule = [item for item in extended if item.origin == ORIGIN_RULE]
    assert rule and rule[0].value == "127.50" and rule[0].rule_id == "r1"

    conflicting = [dict(decisions[0], conflict=True)]
    conflict_report = _report(result, evidence, rule_decisions=conflicting,
                              rule_comparison=[dict(comparison[0], conflict=True)])
    compared = collect_marking_specs(conflict_report, catalog, "COMPARE")
    field_specs = [item for item in compared if item.field_path == "events[0].cash_movements[0].amount"]
    assert {item.origin for item in field_specs} == {ORIGIN_PARSER, ORIGIN_RULE}
    assert all(item.status == RecognitionStatus.REVIEW for item in field_specs)
    markers = resolve_marking_specs(field_specs, {1: "Betrag 126,50\nBetrag 127,50"}, None)
    assert markers and all(item.status == RecognitionStatus.REVIEW for item in markers)


def test_compare_extended_only_value_is_recognized_as_rule(tmp_path):
    catalog = CatalogStore(tmp_path).catalog(document_type="Kauf")
    report = _report(
        {"events": [{"cash_movements": [{"currency": "EUR"}]}]},
        rule_comparison=[{"field": "events[0].cash_movements[0].amount", "standard": None,
                          "extended": "42,00", "conflict": False, "rule_id": "r9"}])
    specs = collect_marking_specs(report, catalog, "COMPARE")
    rule = [item for item in specs if item.origin == ORIGIN_RULE]
    assert rule and rule[0].value == "42,00" and rule[0].status == RecognitionStatus.RECOGNIZED


# -- annotations and persisted coordinates ---------------------------------

def test_user_annotation_uses_persisted_pdf_quads_and_provenance(tmp_path):
    annotation = {"active": 1, "page_number": 2, "original_text": "Handelsplatz: XETRA",
                  "field_path": "attributes.user_fields.trade.venue", "reference_value": "XETRA",
                  "decision": "CONFIRMED", "review_status": "APPROVED",
                  "coordinates": {"coordinate_system": "PDF_POINTS",
                                  "quads": [[[1, 2], [3, 2], [3, 4], [1, 4]]]}}
    specs = collect_marking_specs(_report({}), None, "STANDARD", [annotation])
    markers = resolve_marking_specs(specs, {}, None)
    assert len(markers) == 1
    marker = markers[0]
    assert marker.origin == ORIGIN_USER and marker.page_number == 2
    assert marker.quads and not marker.fallback and marker.status == RecognitionStatus.RECOGNIZED
    assert "Benutzerbestätigte" in marker.origin


def test_legacy_rectangle_coordinates_are_converted_to_a_polygon():
    quads = _coordinate_quads([[10, 20, 30, 40]])
    assert len(quads) == 1
    assert quads[0] == ((10.0, 20.0), (40.0, 20.0), (40.0, 60.0), (10.0, 60.0))


def test_inactive_annotations_and_invalid_forced_quads_are_ignored():
    annotation = {"active": 0, "page_number": 1, "original_text": "X", "field_path": "x",
                  "reference_value": "X", "coordinates": [[1, 2, 3, 4]]}
    assert collect_marking_specs(_report({}), None, "STANDARD", [annotation]) == []
    markers = resolve_marking_specs([_spec("X", forced=(((0, 0), (1, 0), (1, 1)),), forced_text="X")],
                                    {}, None)
    assert markers and markers[0].quads and markers[0].page_number == 1
