"""Automatischer, versionierter Excel-Export für „Run On Folder“-Batchläufe.

Der Export liest ausschließlich die vorhandenen Batch-Berichte (DTO-Dicts) und
schreibt je erkanntem Dokumenttyp ein eigenes Tabellenblatt.  Die Spalte „Datei“
enthält nur den Dateinamen als Hyperlink; der vollständige Pfad steht in der
letzten Spalte „Pfad“.  Fehlende Werte bleiben leere Zellen; Platzhalter wie
``None``, ``NOT_FOUND`` oder ``0`` werden nicht erzeugt.  Es gibt keine erneute
PDF-Analyse, keine Zwischen-CSV und keine Schreibzugriffe auf SQLite,
Referenzwerte oder Trainingsdaten.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from portman_pdf_lab.application.batch_csv import _is_missing, flatten_evidence_values

EXCEL_PREFIX = "Portman_Parser_Kompakt"
MAX_SHEET_NAME_LENGTH = 31
_INVALID_SHEET_CHARS = re.compile(r"[\[\]\:\*\?\/\\]")

# Fachliche Spalten je Dokumenttyp: (deutsche Überschrift, DTO-Pfade relativ
# zum einzelnen FinancialEvent).  Jedes Ereignis wird zu einer eigenen Zeile;
# die erste gültige Pfadauflösung gewinnt.
_BASE_HEADERS = ("Datei", "Dokumenttyp")

_SECURITY_COLUMNS = (
    ("Wertpapiername", ("security_name",)),
    ("ISIN", ("security_isin", "trades[0].isin")),
    ("WKN", ("security_wkn", "trades[0].wkn")),
)

_TYPE_COLUMNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "Finanzreport": (
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
    ),
    "Wertpapierkauf": _SECURITY_COLUMNS + (
        ("Stückzahl", ("trades[0].quantity",)),
        ("Geschäftsdatum", ("trades[0].trade_date",)),
        ("Valuta", ("trades[0].value_date",)),
        ("Kurs", ("trades[0].price",)),
        ("Kurswert", ("trades[0].market_value",)),
        ("Bruttobetrag", ("trades[0].gross_amount",)),
        ("Belastung/Belastungsbetrag", ("cash_movements[0].amount",)),
        ("Währung", ("cash_movements[0].currency",)),
        ("Cashflowstatus", ("cash_movements[0].status",)),
        ("Gebührenbetrag", ("fee_events[0].amount",)),
        ("Einbehaltene Steuer", ("tax_events[0].actually_withheld_tax",)),
    ),
    "Wertpapierverkauf": _SECURITY_COLUMNS + (
        ("Stückzahl", ("trades[0].quantity",)),
        ("Geschäftsdatum", ("trades[0].trade_date",)),
        ("Valuta", ("trades[0].value_date",)),
        ("Kurs", ("trades[0].price",)),
        ("Kurswert", ("trades[0].market_value",)),
        ("Gutschriftsbetrag", ("cash_movements[0].amount",)),
        ("Währung", ("cash_movements[0].currency",)),
        ("Cashflowstatus", ("cash_movements[0].status",)),
        ("Gebührenbetrag", ("fee_events[0].amount",)),
        ("Einbehaltene Steuer", ("tax_events[0].actually_withheld_tax",)),
    ),
    "Ertragsgutschrift": _SECURITY_COLUMNS + (
        ("Stückzahl", ("trades[0].quantity", "security_movements[0].quantity")),
        ("Buchungsdatum", ("event_date",)),
        ("Bruttobetrag", ("cash_movements[0].amount",)),
        ("Währung", ("cash_movements[0].currency",)),
        ("Cashflowstatus", ("cash_movements[0].status",)),
        ("Bemessungsgrundlage", ("tax_events[0].assessment_basis",)),
        ("Einbehaltene Steuer", ("tax_events[0].actually_withheld_tax",)),
    ),
    "Dividendengutschrift": _SECURITY_COLUMNS + (
        ("Stückzahl", ("trades[0].quantity", "security_movements[0].quantity")),
        ("Buchungsdatum", ("event_date",)),
        ("Bruttobetrag", ("cash_movements[0].amount",)),
        ("Währung", ("cash_movements[0].currency",)),
        ("Cashflowstatus", ("cash_movements[0].status",)),
        ("Bemessungsgrundlage", ("tax_events[0].assessment_basis",)),
        ("Einbehaltene Steuer", ("tax_events[0].actually_withheld_tax",)),
    ),
    "Investment-Ausschüttung": _SECURITY_COLUMNS + (
        ("Stückzahl", ("trades[0].quantity", "security_movements[0].quantity")),
        ("Buchungsdatum", ("event_date",)),
        ("Bruttobetrag", ("cash_movements[0].amount",)),
        ("Währung", ("cash_movements[0].currency",)),
        ("Cashflowstatus", ("cash_movements[0].status",)),
        ("Bemessungsgrundlage", ("tax_events[0].assessment_basis",)),
        ("Einbehaltene Steuer", ("tax_events[0].actually_withheld_tax",)),
    ),
    "Vorabpauschale": _SECURITY_COLUMNS + (
        ("Buchungsdatum", ("event_date",)),
        ("Steuerjahr", ("tax_events[0].tax_year",)),
        ("Bemessungsgrundlage", ("tax_events[0].assessment_basis",)),
        ("Steuer vor Teilfreistellung", ("tax_events[0].advance_before_partial_exemption",)),
        ("Einbehaltene Steuer", ("tax_events[0].actually_withheld_tax",)),
        ("Währung", ("tax_events[0].currency",)),
    ),
    "Steuerinformationen": (
        ("Buchungsdatum", ("event_date",)),
        ("Vorgangsart", ("kind",)),
        ("Steuerart", ("tax_events[0].kind",)),
        ("Steuerjahr", ("tax_events[0].tax_year",)),
        ("Bemessungsgrundlage", ("tax_events[0].assessment_basis",)),
        ("Steuerpflichtiger Betrag", ("tax_events[0].taxable_amount",)),
        ("Angegebene Steuerschuld", ("tax_events[0].stated_tax_liability",)),
        ("Einbehaltene Steuer", ("tax_events[0].actually_withheld_tax",)),
        ("Währung", ("tax_events[0].currency",)),
    ),
    "MiFID-II-Kosteninformation": (
        ("Buchungsdatum", ("event_date",)),
        ("Kosteninformationstyp", ("cost_events[0].information_type",)),
        ("Kostenkategorie", ("cost_events[0].kind",)),
        ("Informationsbetrag", ("cost_events[0].amount",)),
        ("Währung", ("cost_events[0].currency",)),
        ("Nur informativ", ("cost_events[0].informational",)),
    ),
}

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


def _source_parts(report: Mapping[str, Any]) -> tuple[str, str]:
    """Liefert (Dateiname, vollständiger Pfad) des Quelldokuments."""
    raw = _dig(report, "source")
    if raw is None or _is_missing(raw):
        return "", ""
    text = str(raw)
    return Path(text).name, text


def _file_uri(report: Mapping[str, Any]) -> str | None:
    """Datei-URI für den Excel-Hyperlink, oder ``None`` ohne Quellpfad."""
    _, text = _source_parts(report)
    if not text:
        return None
    try:
        return Path(text).resolve().as_uri()
    except (OSError, ValueError):
        return None


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
    """Liefert (Spaltenüberschriften, Zeilenwerte) für ein Tabellenblatt.

    Jedes FinancialEvent erzeugt eine Zeile; Dokumentangaben (Datei,
    Dokumenttyp) werden je Zeile wiederholt.  Ein Bericht ohne Ereignisse
    erhält eine Zeile mit leeren fachlichen Zellen.
    """
    result = report.get("result") if isinstance(report.get("result"), Mapping) else {}
    filename, source_path = _source_parts(report)
    if sheet == "Nicht erkannt":
        headers = [header for header, _ in _UNRECOGNIZED_COLUMNS] + ["Pfad"]
        row = [filename,
               str(_dig(report, "error") or ""),
               str(_dig(report, "message") or ""),
               _issue_codes(report),
               source_path]
        return headers, [row]
    columns = _TYPE_COLUMNS.get(sheet)
    if columns is None:
        # Unbekannter, aber erkannter Dokumenttyp: dynamische, evidenzgestützte
        # Spalten wie im CSV-Export plus Datei und Dokumenttyp.
        values = flatten_evidence_values(result)
        headers = [*_BASE_HEADERS, *values.keys(), "Pfad"]
        rows = [[filename,
                 str((report.get("detection") or {}).get("document_type") or ""),
                 *values.values(),
                 source_path]]
        return headers, rows
    headers = [*_BASE_HEADERS, *(header for header, _ in columns), "Pfad"]
    events = result.get("events") if isinstance(result.get("events"), list) else []
    rows = []
    for event in events or [{}]:
        scope = event if isinstance(event, Mapping) else {}
        rows.append([filename,
                     str((report.get("detection") or {}).get("document_type") or ""),
                     *[_cell_text(scope, paths) for _, paths in columns],
                     source_path])
    return headers, rows


def _style_sheet(worksheet) -> None:
    """Zentriert alle Zellen, formatiert den Kopf und optimiert die Größen."""
    from openpyxl.styles import Alignment, Font

    alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for cell in worksheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = alignment
    for row in worksheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = alignment

    # Spaltenbreite: längster Zellinhalt, begrenzt, damit lange Pfade umbrechen.
    for column_cells in worksheet.columns:
        longest = max((len(str(cell.value or "")) for cell in column_cells), default=0)
        width = min(max(10, longest + 2), 40)
        worksheet.column_dimensions[column_cells[0].column_letter].width = width

    # Zeilenhöhe: Anzahl der durch den Umbruch entstehenden Zeilen.
    for row_index, row in enumerate(worksheet.iter_rows(), start=1):
        lines = 1
        for cell in row:
            text = str(cell.value or "")
            if not text:
                continue
            width = worksheet.column_dimensions[cell.column_letter].width or 10
            wrapped = sum(max(1, math.ceil(len(part) / max(1, width - 1)))
                          for part in text.split("\n"))
            lines = max(lines, wrapped)
        worksheet.row_dimensions[row_index].height = 15 * lines + 3

    worksheet.auto_filter.ref = worksheet.dimensions
    worksheet.freeze_panes = "A2"


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
                row_reports: list[Mapping[str, Any]] = []
                for report in grouped[sheet]:
                    try:
                        sheet_headers, sheet_rows = _sheet_rows(report, sheet)
                    except Exception as exc:  # ein defekter Bericht darf den Export nicht abbrechen
                        errors.append(f"{sheet}: {Path(str(report.get('source', ''))).name} – {exc}")
                        continue
                    if not headers:
                        headers = sheet_headers
                    rows.extend(sheet_rows)
                    row_reports.extend([report] * len(sheet_rows))
                if not headers:
                    continue
                worksheet.append(headers)
                for report, row in zip(row_reports, rows):
                    worksheet.append([value if value is not None else "" for value in row])
                    cell = worksheet.cell(row=worksheet.max_row, column=1)
                    uri = _file_uri(report)
                    if uri:
                        cell.hyperlink = uri
                        cell.style = "Hyperlink"
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
