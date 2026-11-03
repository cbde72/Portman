"""Automatischer, versionierter Excel-Export für „Run On Folder“-Batchläufe.

Der Export liest ausschließlich die vorhandenen Batch-Berichte (DTO-Dicts) und
schreibt je erkanntem Dokumenttyp ein eigenes Tabellenblatt.  Fehlende Werte
bleiben leere Zellen; Platzhalter wie ``None``, ``NOT_FOUND`` oder ``0`` werden
nicht erzeugt.  Es gibt keine erneute PDF-Analyse, keine Zwischen-CSV und keine
Schreibzugriffe auf SQLite, Referenzwerte oder Trainingsdaten.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from portman_pdf_lab.application.batch_csv import _is_missing, flatten_evidence_values

EXCEL_PREFIX = "Portman_Parser_Kompakt"
MAX_SHEET_NAME_LENGTH = 31
_INVALID_SHEET_CHARS = re.compile(r"[\[\]\:\*\?\/\\]")

# Fachliche Spalten je Dokumenttyp: (deutsche Überschrift, DTO-Pfade).
# Die Pfade sind relativ zum Parserergebnis; die erste Auflösung gewinnt.
_BASE_COLUMNS = (("Datei", ("source",)), ("Dokumenttyp", ("detection.document_type",)))

_SECURITY_COLUMNS = (
    ("Wertpapiername", ("events[0].security_name",)),
    ("ISIN", ("events[0].security_isin", "events[0].trades[0].isin")),
    ("WKN", ("events[0].security_wkn", "events[0].trades[0].wkn")),
)

_TYPE_COLUMNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "Wertpapierkauf": _SECURITY_COLUMNS + (
        ("Stückzahl", ("events[0].trades[0].quantity",)),
        ("Geschäftsdatum", ("events[0].trades[0].trade_date",)),
        ("Valuta", ("events[0].trades[0].value_date",)),
        ("Kurs", ("events[0].trades[0].price",)),
        ("Kurswert", ("events[0].trades[0].market_value",)),
        ("Bruttobetrag", ("events[0].trades[0].gross_amount",)),
        ("Belastung/Belastungsbetrag", ("events[0].cash_movements[0].amount",)),
        ("Währung", ("events[0].cash_movements[0].currency",)),
        ("Cashflowstatus", ("events[0].cash_movements[0].status",)),
        ("Gebührenbetrag", ("events[0].fee_events[0].amount",)),
        ("Einbehaltene Steuer", ("events[0].tax_events[0].actually_withheld_tax",)),
    ),
    "Wertpapierverkauf": _SECURITY_COLUMNS + (
        ("Stückzahl", ("events[0].trades[0].quantity",)),
        ("Geschäftsdatum", ("events[0].trades[0].trade_date",)),
        ("Valuta", ("events[0].trades[0].value_date",)),
        ("Kurs", ("events[0].trades[0].price",)),
        ("Kurswert", ("events[0].trades[0].market_value",)),
        ("Gutschriftsbetrag", ("events[0].cash_movements[0].amount",)),
        ("Währung", ("events[0].cash_movements[0].currency",)),
        ("Cashflowstatus", ("events[0].cash_movements[0].status",)),
        ("Gebührenbetrag", ("events[0].fee_events[0].amount",)),
        ("Einbehaltene Steuer", ("events[0].tax_events[0].actually_withheld_tax",)),
    ),
    "Ertragsgutschrift": _SECURITY_COLUMNS + (
        ("Stückzahl", ("events[0].trades[0].quantity", "events[0].security_movements[0].quantity")),
        ("Buchungsdatum", ("events[0].event_date",)),
        ("Bruttobetrag", ("events[0].cash_movements[0].amount",)),
        ("Währung", ("events[0].cash_movements[0].currency",)),
        ("Cashflowstatus", ("events[0].cash_movements[0].status",)),
        ("Bemessungsgrundlage", ("events[0].tax_events[0].assessment_basis",)),
        ("Einbehaltene Steuer", ("events[0].tax_events[0].actually_withheld_tax",)),
    ),
    "Dividendengutschrift": _SECURITY_COLUMNS + (
        ("Stückzahl", ("events[0].trades[0].quantity", "events[0].security_movements[0].quantity")),
        ("Buchungsdatum", ("events[0].event_date",)),
        ("Bruttobetrag", ("events[0].cash_movements[0].amount",)),
        ("Währung", ("events[0].cash_movements[0].currency",)),
        ("Cashflowstatus", ("events[0].cash_movements[0].status",)),
        ("Bemessungsgrundlage", ("events[0].tax_events[0].assessment_basis",)),
        ("Einbehaltene Steuer", ("events[0].tax_events[0].actually_withheld_tax",)),
    ),
    "Investment-Ausschüttung": _SECURITY_COLUMNS + (
        ("Stückzahl", ("events[0].trades[0].quantity", "events[0].security_movements[0].quantity")),
        ("Buchungsdatum", ("events[0].event_date",)),
        ("Bruttobetrag", ("events[0].cash_movements[0].amount",)),
        ("Währung", ("events[0].cash_movements[0].currency",)),
        ("Cashflowstatus", ("events[0].cash_movements[0].status",)),
        ("Bemessungsgrundlage", ("events[0].tax_events[0].assessment_basis",)),
        ("Einbehaltene Steuer", ("events[0].tax_events[0].actually_withheld_tax",)),
    ),
    "Vorabpauschale": _SECURITY_COLUMNS + (
        ("Buchungsdatum", ("events[0].event_date",)),
        ("Steuerjahr", ("events[0].tax_events[0].tax_year",)),
        ("Bemessungsgrundlage", ("events[0].tax_events[0].assessment_basis",)),
        ("Steuer vor Teilfreistellung", ("events[0].tax_events[0].advance_before_partial_exemption",)),
        ("Einbehaltene Steuer", ("events[0].tax_events[0].actually_withheld_tax",)),
        ("Währung", ("events[0].tax_events[0].currency",)),
    ),
    "Steuerinformationen": (
        ("Buchungsdatum", ("events[0].event_date",)),
        ("Vorgangsart", ("events[0].kind",)),
        ("Steuerart", ("events[0].tax_events[0].kind",)),
        ("Steuerjahr", ("events[0].tax_events[0].tax_year",)),
        ("Bemessungsgrundlage", ("events[0].tax_events[0].assessment_basis",)),
        ("Steuerpflichtiger Betrag", ("events[0].tax_events[0].taxable_amount",)),
        ("Angegebene Steuerschuld", ("events[0].tax_events[0].stated_tax_liability",)),
        ("Einbehaltene Steuer", ("events[0].tax_events[0].actually_withheld_tax",)),
        ("Währung", ("events[0].tax_events[0].currency",)),
    ),
    "MiFID-II-Kosteninformation": (
        ("Buchungsdatum", ("events[0].event_date",)),
        ("Kosteninformationstyp", ("events[0].cost_events[0].information_type",)),
        ("Kostenkategorie", ("events[0].cost_events[0].kind",)),
        ("Informationsbetrag", ("events[0].cost_events[0].amount",)),
        ("Währung", ("events[0].cost_events[0].currency",)),
        ("Nur informativ", ("events[0].cost_events[0].informational",)),
    ),
}

# Finanzreports enthalten beliebig viele Buchungen: jede Buchung (jedes
# FinancialEvent) erhält eine eigene Zeile; die Pfade sind relativ zum Event.
_FINANZREPORT_COLUMNS = (
    ("Buchungsdatum", ("event_date",)),
    ("Vorgangsart", ("kind",)),
    ("Wertpapiername", ("security_name",)),
    ("ISIN", ("security_isin",)),
    ("WKN", ("security_wkn",)),
    ("Stückzahl", ("trades[0].quantity",)),
    ("Buchungsbetrag", ("cash_movements[0].amount",)),
    ("Währung", ("cash_movements[0].currency",)),
    ("Cashflowstatus", ("cash_movements[0].status",)),
    ("Buchungsart", ("cash_movements[0].movement_type",)),
    ("Einbehaltene Steuer", ("tax_events[0].actually_withheld_tax",)),
    ("Gebührenbetrag", ("fee_events[0].amount",)),
)

_UNRECOGNIZED_COLUMNS = (
    ("Datei", ("source",)),
    ("Fehlercode", ("error",)),
    ("Fehlermeldung", ("message",)),
    ("Issues", ("issue_codes",)),
)


def sheet_name_for_report(report: Mapping[str, Any]) -> str:
    """Kanonischer Tabellenblattname je Dokumenttyp."""
    if not isinstance(report, Mapping):
        return "Nicht erkannt"
    if report.get("error") and not report.get("detection"):
        return "Nicht erkannt"
    detection = report.get("detection") if isinstance(report.get("detection"), Mapping) else {}
    document_type = str(detection.get("document_type") or "")
    handler = str(detection.get("handler_id") or "")
    value = f"{document_type} {handler}".casefold()
    if not value.strip():
        return "Nicht erkannt"
    if "finanzreport" in value or "kontoauszug" in value:
        return "Finanzreport"
    if "wertpapierkauf" in value:
        return "Wertpapierkauf"
    if "wertpapierverkauf" in value:
        return "Wertpapierverkauf"
    if "dividendengutschrift" in value or "dividende" in value:
        return "Dividendengutschrift"
    if "vorabpauschale" in value:
        return "Vorabpauschale"
    if "steuer" in value:
        return "Steuerinformationen"
    if "mifid" in value or "kosteninformation" in value:
        return "MiFID-II-Kosteninformation"
    if "ausschüttung" in value or "ausschuettung" in value:
        return "Investment-Ausschüttung"
    if "ertrag" in value:
        return "Ertragsgutschrift"
    cleaned = _INVALID_SHEET_CHARS.sub(" ", document_type).strip() or "Nicht erkannt"
    return cleaned[:MAX_SHEET_NAME_LENGTH]


def _unwrap(node: Any) -> Any:
    if isinstance(node, Mapping) and "value" in node and not isinstance(node.get("value"), Mapping):
        return node.get("value")
    return node


def _dig(root: Any, path: str) -> Any:
    """Löst einen DTO-Pfad wie ``events[0].trades[0].quantity`` auf."""
    node = root
    for part in str(path or "").split("."):
        if node is None:
            return None
        match = re.fullmatch(r"([^\[\]]+)\[(\d+)\]", part)
        if match:
            key, index = match.group(1), int(match.group(2))
            container = node.get(key) if isinstance(node, Mapping) else None
            node = container[index] if isinstance(container, Sequence) and index < len(container) else None
        else:
            node = node.get(part) if isinstance(node, Mapping) else None
        node = _unwrap(node)
    return node


def _cell_text(result: Mapping[str, Any], paths: Sequence[str]) -> Any:
    """Zellwert: erste gültige Pfadauflösung; Platzhalter bleiben leer."""
    for path in paths:
        value = _dig(result, path)
        if value is None or _is_missing(value):
            continue
        return value
    return ""


def _issue_codes(report: Mapping[str, Any]) -> str:
    issues = report.get("issues") if isinstance(report.get("issues"), list) else []
    return "; ".join(str(item.get("code") or "") for item in issues if isinstance(item, Mapping))


def next_excel_path(folder: str | Path) -> Path:
    """Nächste freie Versionsnummer; bestehende Dateien werden nie überschrieben."""
    directory = Path(folder)
    existing: set[int] = set()
    if directory.exists():
        for item in directory.glob(f"{EXCEL_PREFIX}_v*.xlsx"):
            match = re.fullmatch(rf"{EXCEL_PREFIX}_v(\d+)\.xlsx", item.name)
            if match:
                existing.add(int(match.group(1)))
    version = 1
    while version in existing:
        version += 1
    return directory / f"{EXCEL_PREFIX}_v{version:02d}.xlsx"


def _sheet_rows(report: Mapping[str, Any], sheet: str):
    """Liefert (Spaltenüberschriften, Zeilenwerte) für ein Tabellenblatt."""
    result = report.get("result") if isinstance(report.get("result"), Mapping) else {}
    if sheet == "Nicht erkannt":
        headers = [header for header, _ in _UNRECOGNIZED_COLUMNS]
        row = [str(_dig(report, "source") or ""),
               str(_dig(report, "error") or ""),
               str(_dig(report, "message") or ""),
               _issue_codes(report)]
        return headers, [row]
    if sheet == "Finanzreport":
        headers = ["Datei", "Dokumenttyp", *(header for header, _ in _FINANZREPORT_COLUMNS)]
        events = result.get("events") if isinstance(result.get("events"), list) else []
        if not events:
            events = [None]
        rows = []
        for event in events:
            scope = event if isinstance(event, Mapping) else {}
            rows.append([str(_dig(report, "source") or ""),
                         str((report.get("detection") or {}).get("document_type") or ""),
                         *[_cell_text(scope, paths) for _, paths in _FINANZREPORT_COLUMNS]])
        return headers, rows
    columns = _TYPE_COLUMNS.get(sheet)
    if columns is None:
        # Unbekannter, aber erkannter Dokumenttyp: dynamische, evidenzgestützte
        # Spalten wie im CSV-Export plus Datei und Dokumenttyp.
        values = flatten_evidence_values(result)
        headers = ["Datei", "Dokumenttyp", *values.keys()]
        rows = [[str(_dig(report, "source") or ""),
                 str((report.get("detection") or {}).get("document_type") or ""),
                 *values.values()]]
        return headers, rows
    headers = [header for header, _ in _BASE_COLUMNS] + [header for header, _ in columns]
    row = [str(_dig(report, "source") or ""),
           str((report.get("detection") or {}).get("document_type") or ""),
           *[_cell_text(result, paths) for _, paths in columns]]
    return headers, [row]


def _style_sheet(worksheet) -> None:
    worksheet.auto_filter.ref = worksheet.dimensions
    worksheet.freeze_panes = "A2"
    for column_cells in worksheet.columns:
        length = max(len(str(cell.value or "")) for cell in column_cells)
        worksheet.column_dimensions[column_cells[0].column_letter].width = max(12, min(60, length + 2))


def export_batch_excel(reports: Sequence[Mapping[str, Any]], folder: str | Path) -> dict[str, Any]:
    """Schreibt den versionierten Excel-Bericht und gibt Diagnose zurück.

    Ein Exportfehler wird als ``errors``-Eintrag gemeldet und nie ausgelöst,
    damit ein Batchlauf nicht abstützt.  Gesperrte Dateien führen automatisch
    zur nächsten Versionsnummer.
    """
    try:
        from openpyxl import Workbook
    except ImportError as exc:  # pragma: no cover - Umgebung ohne openpyxl
        return {"path": None, "sheets": [], "errors": [f"openpyxl nicht verfügbar: {exc}"]}

    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for report in reports:
        grouped.setdefault(sheet_name_for_report(report), []).append(report)

    errors: list[str] = []
    path = next_excel_path(folder)
    for _attempt in range(20):
        try:
            workbook = Workbook()
            workbook.remove(workbook.active)
            for sheet in sorted(grouped):
                worksheet = workbook.create_sheet(sheet[:MAX_SHEET_NAME_LENGTH])
                headers: list[str] = []
                rows: list[list[Any]] = []
                for report in grouped[sheet]:
                    try:
                        sheet_headers, sheet_rows = _sheet_rows(report, sheet)
                    except Exception as exc:  # ein defekter Bericht darf den Export nicht abbrechen
                        errors.append(f"{sheet}: {Path(str(report.get('source', ''))).name} – {exc}")
                        continue
                    if not headers:
                        headers = sheet_headers
                    rows.extend(sheet_rows)
                if not headers:
                    continue
                worksheet.append(headers)
                for row in rows:
                    worksheet.append([value if value not in {None} else "" for value in row])
                _style_sheet(worksheet)
            path.parent.mkdir(parents=True, exist_ok=True)
            workbook.save(path)
            return {"path": path, "sheets": sorted(grouped), "errors": errors}
        except PermissionError:
            # Datei ist geöffnet oder gesperrt: automatisch die nächste Version.
            path = next_excel_path(path.parent)
            match = re.fullmatch(rf"{EXCEL_PREFIX}_v(\d+)\.xlsx", path.name)
            if match and int(match.group(1)) > 99:
                errors.append(f"Keine freie Versionsnummer in {path.parent} erreichbar.")
                return {"path": None, "sheets": sorted(grouped), "errors": errors}
        except Exception as exc:  # keine Ausnahme darf den Batchlauf beenden
            errors.append(f"Excel-Export fehlgeschlagen: {exc}")
            return {"path": None, "sheets": sorted(grouped), "errors": errors}
    return {"path": None, "sheets": sorted(grouped), "errors": errors}
