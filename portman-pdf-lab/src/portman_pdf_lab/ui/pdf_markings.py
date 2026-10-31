"""Evidence-driven PDF marking model and text-coordinate resolver.

The parser API intentionally does not contain bounding boxes.  This module
therefore treats page numbers and evidence excerpts as the authoritative
source and only creates a geometric highlight when a unique text span can be
matched.  Repeated or missing text never results in an invented green box.

The resolver is deliberately independent from Qt widgets.  ``MainWindow``
feeds it the text returned by ``QPdfDocument.getAllText`` (whose character
indices are valid for ``getSelectionAtIndex``) together with a callback that
returns the selection quads.  Tests can supply a plain page-text mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Callable, Iterable, Mapping, Sequence

from .result_view import (
    DisplayRow,
    RecognitionStatus,
    enrich_rows,
    flatten_result,
    scalar_text,
    _is_missing,
)

ORIGIN_PARSER = "Bestehender Parser"
ORIGIN_RULE = "Optionale Regelkonfiguration"
ORIGIN_USER = "Benutzerbestätigte Annotation"

STATUS_COLORS = {
    RecognitionStatus.RECOGNIZED: "#2e7d32",
    RecognitionStatus.MISSING: "#c62828",
    RecognitionStatus.REVIEW: "#b26a00",
    RecognitionStatus.NOT_APPLICABLE: "#707070",
}

STATUS_LABELS = {
    RecognitionStatus.RECOGNIZED: "Erkannt",
    RecognitionStatus.MISSING: "Fehlend / ungültig",
    RecognitionStatus.REVIEW: "Prüfen",
    RecognitionStatus.NOT_APPLICABLE: "Nicht anwendbar",
}

_CONFLICT_NOTE = "Widersprüchliche Werte in STANDARD und EXTENDED – fachliche Prüfung erforderlich."
_AMBIGUOUS_NOTE = "Mehrdeutige Textstelle – keine eindeutige Zuordnung möglich."


@dataclass(frozen=True)
class MarkingSpec:
    """A field/value that should be located in the PDF text."""

    field_path: str
    label: str
    value: str
    status: RecognitionStatus
    origin: str
    parser_id: str = ""
    rule_id: str = ""
    evidence_id: str = ""
    page_number: int = 0
    excerpts: tuple[str, ...] = ()
    value_terms: tuple[str, ...] = ()
    note: str = ""
    forced_quads: tuple[tuple[tuple[float, float], ...], ...] = ()
    forced_text: str = ""


@dataclass(frozen=True)
class PdfMarking:
    """One resolved highlight.  Coordinates are stored in PDF points."""

    field_path: str
    label: str
    value: str
    status: RecognitionStatus
    origin: str
    parser_id: str = ""
    rule_id: str = ""
    evidence_id: str = ""
    page_number: int = 1
    start: int = 0
    end: int = 0
    text: str = ""
    quads: tuple[tuple[tuple[float, float], ...], ...] = ()
    fallback: bool = False
    ambiguous: bool = False
    note: str = ""
    occurrence: int = 0
    total_occurrences: int = 0

    @property
    def color(self) -> str:
        return STATUS_COLORS.get(self.status, "#707070")

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status.value)

    @property
    def key(self) -> tuple:
        return (self.field_path, self.origin, self.page_number, self.start, self.end,
                self.quads, self.value)

    def tooltip_lines(self) -> list[str]:
        lines = [f"Feld: {self.label} ({self.field_path})", f"Wert: {self.value or '—'}",
                 f"Status: {self.status_label}", f"Herkunft: {self.origin}"]
        if self.parser_id:
            lines.append(f"Parser: {self.parser_id}")
        if self.rule_id:
            lines.append(f"Regel: {self.rule_id}")
        lines.append(f"Seite: {self.page_number}")
        if self.fallback:
            lines.append("Darstellung: Textlayer-Fallback (keine PDF-Bounding-Box)")
        if self.note:
            lines.append(f"Hinweis: {self.note}")
        if self.total_occurrences > 1:
            lines.append(f"Fundstelle: {self.occurrence} von {self.total_occurrences}")
        return lines


@dataclass(frozen=True)
class _Span:
    start: int
    end: int
    text: str
    ambiguous: bool = False


def _first(mapping: Mapping[str, Any], *keys, default=""):
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def _coordinate_quads(coordinates: Any) -> tuple[tuple[tuple[float, float], ...], ...]:
    """Accept persisted PDF-point quads as well as legacy x/y/w/h rectangles."""
    if not coordinates:
        return ()

    def point(value):
        if isinstance(value, Mapping):
            return float(value.get("x", 0)), float(value.get("y", 0))
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return float(value[0]), float(value[1])
        return None

    def polygon(values):
        points = [point(item) for item in values]
        if len(points) >= 3 and all(item is not None for item in points):
            return tuple(points)
        return None

    raw = coordinates.get("quads") if isinstance(coordinates, Mapping) else coordinates
    if not raw:
        return ()
    result = []
    for item in raw:
        if not isinstance(item, (list, tuple)):
            continue
        points = polygon(item)
        if points:
            result.append(points)
            continue
        # Legacy repository examples use [x, y, width, height].
        if len(item) == 4 and all(isinstance(value, (int, float)) for value in item):
            x, y, width, height = map(float, item)
            result.append(((x, y), (x + width, y), (x + width, y + height), (x, y + height)))
    return tuple(result)


def _number(text: str) -> Decimal | None:
    candidate = str(text).strip().replace(" ", "")
    if not candidate:
        return None
    if "," in candidate and "." in candidate:
        candidate = candidate.replace(".", "").replace(",", ".")
    else:
        candidate = candidate.replace(",", ".")
    try:
        return Decimal(candidate)
    except (InvalidOperation, ValueError):
        return None


def _date(text: str) -> date | None:
    value = str(text).strip()
    for pattern in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    return None


def _printed_equivalent(value: str, text: str) -> list[str]:
    """Find the printed spelling of a normalized parser value in an excerpt."""
    value = value.strip()
    if not value or not text:
        return []
    number = _number(value)
    if number is not None:
        matches = []
        for token in re.findall(r"[-+]?\d[\d., ]*\d|[-+]?\d", text):
            candidate = _number(token)
            if candidate is not None and candidate == number:
                matches.append(token.strip())
        return matches
    parsed_date = _date(value)
    if parsed_date is not None:
        matches = []
        for token in re.findall(r"\b\d{1,4}[./-]\d{1,2}[./-]\d{1,4}\b", text):
            if _date(token) == parsed_date:
                matches.append(token)
        return matches
    if value in text:
        return [value]
    if value.casefold() in text.casefold():
        start = text.casefold().find(value.casefold())
        return [text[start:start + len(value)]]
    return []


def value_terms(value: Any, excerpt: str = "") -> tuple[str, ...]:
    """Return presentation-only spellings used to locate a parsed value."""
    if _is_missing(value):
        return ()
    text = scalar_text(value).strip()
    if not text:
        return ()
    terms = {text}
    number = _number(text)
    if number is not None:
        candidates = [number]
        if number < 0:
            # Financial parsers use signed amounts while the statement prints
            # the absolute debit/credit amount.
            candidates.append(-number)
        for candidate_value in candidates:
            for candidate in (format(candidate_value, "f"), format(candidate_value, "f").replace(".", ",")):
                terms.add(candidate)
                if "." in candidate:
                    terms.add(candidate.rstrip("0").rstrip("."))
                    terms.add(candidate.replace(".", ",").rstrip("0").rstrip(","))
    parsed_date = _date(text)
    if parsed_date is not None:
        terms.add(parsed_date.strftime("%d.%m.%Y"))
        terms.add(parsed_date.strftime("%d.%m.%y"))
    terms.update(_printed_equivalent(text, excerpt))
    return tuple(sorted((item for item in terms if item), key=len, reverse=True))


def _normalized(text: str):
    chars, positions = [], []
    pending_space = False
    for index, char in enumerate(text):
        if char.isspace():
            pending_space = bool(chars)
            continue
        if pending_space:
            chars.append(" ")
            positions.append(index)
            pending_space = False
        chars.append(char.casefold())
        positions.append(index)
    return "".join(chars), positions


def find_occurrences(text: str, needle: str) -> list[tuple[int, int]]:
    """Locate exact and whitespace/case-normalized occurrences without regex."""
    if not text or not needle:
        return []
    found: list[tuple[int, int]] = []
    start = 0
    while True:
        index = text.find(needle, start)
        if index < 0:
            break
        found.append((index, index + len(needle)))
        start = index + max(1, len(needle))
    if found:
        return sorted(set(found))
    normalized, positions = _normalized(text)
    target = re.sub(r"\s+", " ", needle.casefold()).strip()
    if not target or len(target) > len(normalized):
        return []
    start = 0
    while True:
        index = normalized.find(target, start)
        if index < 0:
            break
        if index < len(positions) and index + len(target) - 1 < len(positions):
            found.append((positions[index], positions[index + len(target) - 1] + 1))
        start = index + max(1, len(target))
    return sorted(set(found))


def _intersects(left: _Span, right: _Span) -> bool:
    return left.start < right.end and right.start < left.end


def _merge_spans(spans: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for start, end in sorted(set(spans)):
        for cluster in merged:
            if (cluster[0] <= start and end <= cluster[1]) or (start <= cluster[0] and cluster[1] <= end):
                cluster[0], cluster[1] = min(cluster[0], start), max(cluster[1], end)
                break
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _narrow(span: _Span, terms: Sequence[str]) -> _Span | None:
    matches = []
    for term in terms:
        for start, end in find_occurrences(span.text, term):
            matches.append((span.start + start, span.start + end))
    # Presentation variants such as ``126,5`` and ``126,50`` overlap at the
    # same printed location.  Merge nested/overlapping variants into one
    # cluster; two distinct clusters still mean the value is ambiguous.
    merged = _merge_spans(matches)
    if len(merged) == 1:
        start, end = merged[0]
        return _Span(start, end, span.text[start - span.start:end - span.start])
    return None


def _locate(spec: MarkingSpec, text: str) -> list[_Span]:
    excerpt_spans: list[tuple[int, int]] = []
    for excerpt in spec.excerpts:
        excerpt_spans.extend(find_occurrences(text, excerpt))
    excerpt_spans = sorted(set(excerpt_spans))
    value_spans: list[tuple[int, int]] = []
    for term in spec.value_terms:
        value_spans.extend(find_occurrences(text, term))
    value_spans = _merge_spans(value_spans)

    def value_marker():
        start, end = value_spans[0]
        return _Span(start, end, text[start:end])

    if excerpt_spans:
        if len(excerpt_spans) == 1:
            span = _Span(excerpt_spans[0][0], excerpt_spans[0][1], text[excerpt_spans[0][0]:excerpt_spans[0][1]])
            if not spec.value_terms:
                # A missing value anchored in one unique evidence excerpt has a
                # real text location and may be shown in red.
                return [span]
            narrowed = _narrow(span, spec.value_terms)
            if narrowed is not None:
                return [narrowed]
            # The value may be printed elsewhere on the same page (for example
            # an ISIN while the evidence excerpt covers the whole booking line).
            if len(value_spans) == 1:
                return [value_marker()]
            # The value is not present; do not invent a box at the evidence
            # anchor.  The table still shows the field as review-worthy.
            return []
        # Repeated excerpts can still be disambiguated by a value that occurs
        # exactly once on the page.
        if len(value_spans) == 1:
            return [value_marker()]
        if not spec.value_terms:
            return [_Span(start, end, text[start:end], ambiguous=True) for start, end in excerpt_spans]
        return []

    if value_spans:
        if len(value_spans) == 1:
            return [value_marker()]
        return [_Span(start, end, text[start:end], ambiguous=True) for start, end in value_spans]
    return []


def _resolve_spec(spec: MarkingSpec, page_texts: Mapping[int, str],
                  quad_provider: Callable[[int, int, int], Any] | None) -> list[PdfMarking]:
    if spec.forced_quads:
        return [PdfMarking(
            spec.field_path, spec.label, spec.value, spec.status, spec.origin, spec.parser_id,
            spec.rule_id, spec.evidence_id, max(1, spec.page_number), 0, 0,
            spec.forced_text or spec.value, spec.forced_quads, False, False, spec.note, 1, 1)]

    pages = [spec.page_number] if spec.page_number in page_texts else sorted(page_texts)
    located: list[tuple[int, _Span]] = []
    for page in pages:
        text = page_texts.get(page, "")
        if not text:
            continue
        for span in _locate(spec, text):
            located.append((page, span))
    if not located:
        return []

    # An evidence-free rule value may occur on several pages.  Only a single
    # real page occurrence is treated as a reliable assignment.
    cross_page_ambiguous = spec.page_number not in page_texts and len({page for page, _ in located}) > 1
    markers = []
    total = len(located)
    for index, (page, span) in enumerate(located, 1):
        ambiguous = span.ambiguous or cross_page_ambiguous
        status = spec.status
        if ambiguous:
            status = RecognitionStatus.REVIEW
        quads = ()
        fallback = True
        if quad_provider is not None:
            try:
                selection = quad_provider(page, span.start, span.end)
                if selection is not None and selection.isValid():
                    serialized = tuple(
                        tuple((float(point.x()), float(point.y())) for point in polygon)
                        for polygon in selection.bounds())
                    if serialized:
                        quads = serialized
                        fallback = False
            except Exception:
                quads, fallback = (), True
        note = spec.note
        if ambiguous:
            note = " ".join(item for item in (note, _AMBIGUOUS_NOTE) if item)
        markers.append(PdfMarking(
            spec.field_path, spec.label, spec.value, status, spec.origin, spec.parser_id,
            spec.rule_id, spec.evidence_id, page, span.start, span.end, span.text,
            quads, fallback, ambiguous, note, index, total))
    return markers


def resolve_marking_specs(specs: Iterable[MarkingSpec], page_texts: Mapping[int, str],
                          quad_provider: Callable[[int, int, int], Any] | None = None) -> list[PdfMarking]:
    markers: list[PdfMarking] = []
    for spec in specs:
        markers.extend(_resolve_spec(spec, page_texts, quad_provider))
    return _deduplicate(markers)


def _deduplicate(markers: Iterable[PdfMarking]) -> list[PdfMarking]:
    unique, seen = [], set()
    for marker in markers:
        if marker.key in seen:
            continue
        seen.add(marker.key)
        unique.append(marker)
    return unique


def _label(catalog, path: str, fallback: str) -> str:
    definition = catalog.field(path) if catalog else None
    return definition.label if definition else (fallback or path.rsplit(".", 1)[-1])


def _row_lookup(rows: Sequence[DisplayRow]) -> dict[str, DisplayRow]:
    return {row.path: row for row in rows}


def _spec_for_row(row: DisplayRow, parser_id: str, catalog=None, status: RecognitionStatus | None = None,
                  origin: str = ORIGIN_PARSER, value: Any = None, note: str = "",
                  rule_id: str = "") -> MarkingSpec | None:
    evidence = row.evidence or {}
    page = int(evidence.get("page_number") or 0)
    excerpt = str(evidence.get("excerpt") or "")
    final_value = row.value if value is None else value
    if _is_missing(final_value) and not excerpt:
        return None
    label = _label(catalog, row.path, row.name)
    terms = value_terms(final_value, excerpt)
    if not terms and not excerpt:
        return None
    return MarkingSpec(
        row.path, label, "" if _is_missing(final_value) else scalar_text(final_value),
        status or row.status, origin, parser_id, rule_id, str(evidence.get("evidence_id") or ""),
        page, (excerpt,) if excerpt else (), terms, note)


def collect_marking_specs(report: Mapping[str, Any], catalog=None, mode: str | None = None,
                          annotations: Iterable[Mapping[str, Any]] = ()) -> list[MarkingSpec]:
    """Turn parser result, rules and user annotations into locatable specs."""
    result = report.get("result") or {}
    detection = report.get("detection") or {}
    parser_id = str(_first(result, "plugin_id", default=_first(detection, "plugin_id", default="")))
    mode = str(mode or report.get("rule_mode_requested") or report.get("rule_mode_effective") or "STANDARD").upper()
    evidence = {str(item.get("evidence_id")): item for item in result.get("evidence", [])}
    rows = flatten_result(result, evidence)
    if catalog:
        rows = enrich_rows(rows, catalog, result)
    by_path = _row_lookup(rows)
    specs: list[MarkingSpec] = []
    used_evidence: set[str] = set()

    for row in rows:
        if row.status == RecognitionStatus.NOT_APPLICABLE:
            continue
        if row.evidence is None:
            # A missing value without a real text location must not produce an
            # artificial box.  The table still shows it in red/grey.
            continue
        if _is_missing(row.value) and row.requirement not in {"REQUIRED", "CONDITIONAL"}:
            # The catalog did not classify this field as required.  Purely
            # missing optional/technical values never get a PDF mark.
            continue
        spec = _spec_for_row(row, parser_id, catalog)
        if spec:
            specs.append(spec)
            if spec.evidence_id:
                used_evidence.add(spec.evidence_id)

    # Evidence fields not referenced by a result row are still real parser
    # findings (for example a printed title or an optional venue).
    for evidence_id, item in evidence.items():
        if evidence_id in used_evidence:
            continue
        excerpt = str(item.get("excerpt") or "")
        if not excerpt:
            continue
        field = str(item.get("field") or "evidence")
        page = int(item.get("page_number") or 0)
        definition = catalog.field(field) if catalog else None
        label = definition.label if definition else field.replace("_", " ").title()
        specs.append(MarkingSpec(field, label, excerpt, RecognitionStatus.RECOGNIZED,
                                 ORIGIN_PARSER, parser_id, "", evidence_id, page,
                                 (excerpt,), value_terms(excerpt, excerpt)))

    decisions = list(report.get("rule_decisions") or [])
    comparison = list(report.get("rule_comparison") or [])
    if mode in {"EXTENDED", "COMPARE"} and not comparison:
        comparison = [{"field": item.get("field_path"), "standard": item.get("standard_value"),
                       "extended": item.get("effective_value"), "rule": item.get("rule_value"),
                       "conflict": item.get("conflict"), "rule_id": item.get("rule_id")}
                      for item in decisions]
    if mode == "EXTENDED":
        for item in decisions:
            path = str(item.get("field_path") or "")
            value = item.get("effective_value")
            if not path or _is_missing(value):
                continue
            row = by_path.get(path)
            status = RecognitionStatus.REVIEW if item.get("conflict") else RecognitionStatus.RECOGNIZED
            if row is not None:
                spec = _spec_for_row(row, parser_id, catalog, status, ORIGIN_RULE, value,
                                     "Wert aus freigegebenem Regelprofil." if not item.get("conflict") else _CONFLICT_NOTE,
                                     str(item.get("rule_id") or ""))
            else:
                spec = MarkingSpec(path, _label(catalog, path, path), scalar_text(value), status,
                                   ORIGIN_RULE, parser_id, str(item.get("rule_id") or ""), "", 0,
                                   (), value_terms(value), "Wert aus freigegebenem Regelprofil.")
            if spec:
                specs.append(spec)
    elif mode == "COMPARE":
        seen_conflicts = set()
        for item in comparison:
            path = str(item.get("field") or "")
            if not path:
                continue
            standard = item.get("standard")
            extended = item.get("extended")
            conflict = bool(item.get("conflict"))
            rule_id = str(item.get("rule_id") or "")
            row = by_path.get(path)
            note = _CONFLICT_NOTE if conflict else "Vergleich STANDARD/EXTENDED."
            if conflict:
                seen_conflicts.add(path)
                if not _is_missing(standard):
                    if row is not None:
                        spec = _spec_for_row(row, parser_id, catalog, RecognitionStatus.REVIEW,
                                             ORIGIN_PARSER, standard, note)
                    else:
                        spec = MarkingSpec(path, _label(catalog, path, path), scalar_text(standard),
                                           RecognitionStatus.REVIEW, ORIGIN_PARSER, parser_id,
                                           "", "", 0, (), value_terms(standard), note)
                    if spec:
                        specs.append(spec)
                if not _is_missing(extended):
                    specs.append(MarkingSpec(path, _label(catalog, path, path), scalar_text(extended),
                                             RecognitionStatus.REVIEW, ORIGIN_RULE, parser_id,
                                             rule_id, "", 0, (), value_terms(extended), note))
            elif _is_missing(standard) and not _is_missing(extended):
                specs.append(MarkingSpec(path, _label(catalog, path, path), scalar_text(extended),
                                         RecognitionStatus.RECOGNIZED, ORIGIN_RULE, parser_id,
                                         rule_id, "", 0, (), value_terms(extended),
                                         "Nur durch das freigegebene Regelprofil erkannt."))
        # Existing parser markers for a conflicting field must not stay green.
        specs = [replace(spec, status=RecognitionStatus.REVIEW,
                         note=" ".join(filter(None, (spec.note, _CONFLICT_NOTE))))
                 if spec.origin == ORIGIN_PARSER and spec.field_path in seen_conflicts else spec
                 for spec in specs]

    for annotation in annotations:
        if annotation.get("active", 1) in (0, False):
            continue
        page = int(annotation.get("page_number") or 0)
        text = str(annotation.get("original_text") or "")
        field = str(annotation.get("field_path") or "")
        if not field or (not text and not annotation.get("coordinates")):
            continue
        reference = annotation.get("reference_value")
        decision = str(annotation.get("decision") or "").upper()
        review = str(annotation.get("review_status") or "").upper()
        status = RecognitionStatus.RECOGNIZED if decision in {"CONFIRMED", "CORRECTED"} or review == "APPROVED" else RecognitionStatus.REVIEW
        quads = _coordinate_quads(annotation.get("coordinates"))
        specs.append(MarkingSpec(field, _label(catalog, field, field),
                                 "" if _is_missing(reference) else scalar_text(reference),
                                 status, ORIGIN_USER, parser_id, "", "", page,
                                 (text,) if text else (), value_terms(reference, text),
                                 "Vom Benutzer bestätigte Fundstelle.", quads, text))

    return _deduplicate_specs(specs)


def _deduplicate_specs(specs: Iterable[MarkingSpec]) -> list[MarkingSpec]:
    unique, seen = [], set()
    for spec in specs:
        key = (spec.field_path, spec.origin, spec.page_number, spec.value,
               spec.excerpts, spec.forced_quads)
        if key in seen:
            continue
        seen.add(key)
        unique.append(spec)
    return unique


def group_at_anchor(markers: Iterable[PdfMarking], page: int, start: int, end: int) -> list[PdfMarking]:
    """All fields that share (or overlap) one visual text location."""
    return [item for item in markers if item.page_number == page
            and item.start < end and start < item.end]


def text_layer_markers(specs: Iterable[MarkingSpec], page_texts: Mapping[int, str]) -> list[PdfMarking]:
    """Fallback positions for the synchronised text layer (no coordinates)."""
    markers = resolve_marking_specs(specs, page_texts, None)
    return [replace(item, fallback=True, quads=()) for item in markers]
