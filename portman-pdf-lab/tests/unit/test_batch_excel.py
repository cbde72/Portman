"""Tests für den automatischen, versionierten Excel-Export bei „Run On Folder“."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from openpyxl import load_workbook

from portman_pdf_lab.application.batch_excel import (
    EXCEL_PREFIX, export_batch_excel, next_excel_path, sheet_name_for_report,
)


def purchase_report(tmp_path: Path, name: str = "kauf.pdf") -> dict:
    return {
        "source": str(tmp_path / name),
        "detection": {"document_type": "comdirect Wertpapierkauf", "handler_id": "wertpapierkauf",
                      "plugin_id": "user.comdirect-ertraege"},
        "result": {
            "plugin_id": "user.comdirect-ertraege",
            "events": [{
                "kind": "WERTPAPIERKAUF",
                "event_date": "2026-02-04",
                "security_name": "Beispiel ETF",
                "security_isin": "DE0008474511",
                "security_wkn": "ABC123",
                "trades": [{"quantity": "0.125", "trade_date": "2026-02-04",
                            "value_date": "2026-02-06", "price": "1012.00"}],
                "cash_movements": [{"amount": "-126.50", "currency": "EUR", "status": "ACTUAL"}],
                "fee_events": [],
                "tax_events": [],
            }],
        },
    }


def financial_report(tmp_path: Path, bookings: int = 3) -> dict:
    events = [{
        "kind": "ZINSERTRAG",
        "event_date": "2026-01-0" + str(index + 1),
        "cash_movements": [{"amount": f"-{index + 1}.10", "currency": "EUR",
                            "status": "ACTUAL", "movement_type": "INTEREST_CREDIT"}],
    } for index in range(bookings)]
    return {
        "source": str(tmp_path / "finanzreport.pdf"),
        "detection": {"document_type": "comdirect Finanzreport", "handler_id": "finanzreport"},
        "result": {"plugin_id": "comdirect.finanzreport", "events": events},
    }


def dividend_report(tmp_path: Path) -> dict:
    return {
        "source": str(tmp_path / "dividende.pdf"),
        "detection": {"document_type": "comdirect Dividendengutschrift", "handler_id": "dividendengutschrift"},
        "result": {
            "plugin_id": "user.comdirect-ertraege",
            "events": [{
                "security_name": "SAP SE",
                "security_isin": "DE0007164600",
                "security_wkn": "716460",
                "trades": [{"quantity": "0.733"}],
                "cash_movements": [{"amount": "1.61", "currency": "EUR", "status": "ACTUAL"}],
                "tax_events": [{"actually_withheld_tax": "0"}],
            }],
        },
    }


def broken_report(tmp_path: Path) -> dict:
    return {"source": str(tmp_path / "kaputt.pdf"), "error": "PDF_DAMAGED",
            "message": "Unreadable PDF", "issues": [{"code": "PDF_DAMAGED", "message": "Unreadable PDF"}]}


def read_sheet(path: Path, name: str):
    workbook = load_workbook(path, read_only=True)
    try:
        return list(workbook[name].iter_rows(values_only=True))
    finally:
        workbook.close()


def test_sheet_names_follow_document_types(tmp_path):
    assert sheet_name_for_report(purchase_report(tmp_path)) == "Wertpapierkauf"
    assert sheet_name_for_report(financial_report(tmp_path)) == "Finanzreport"
    assert sheet_name_for_report(dividend_report(tmp_path)) == "Dividendengutschrift"
    assert sheet_name_for_report(broken_report(tmp_path)) == "Nicht erkannt"


def test_export_creates_versioned_workbook_per_document_type(tmp_path):
    reports = [purchase_report(tmp_path), financial_report(tmp_path),
               dividend_report(tmp_path), broken_report(tmp_path)]
    result = export_batch_excel(reports, tmp_path)
    path = result["path"]
    assert path == tmp_path / f"{EXCEL_PREFIX}_v01.xlsx"
    assert result["errors"] == []
    assert set(result["sheets"]) == {"Wertpapierkauf", "Finanzreport", "Dividendengutschrift", "Nicht erkannt"}

    purchase = read_sheet(path, "Wertpapierkauf")
    assert purchase[0][0] == "Datei"
    assert "ISIN" in purchase[0] and "Stückzahl" in purchase[0]
    values = purchase[1]
    assert "DE0008474511" in values
    assert "0.125" in values
    assert "-126.50" in values
    # Fehlende Felder bleiben leere Zellen statt Platzhaltern.
    assert "None" not in values and "NOT_FOUND" not in values

    unrecognized = read_sheet(path, "Nicht erkannt")
    assert unrecognized[1][1] == "PDF_DAMAGED"
    assert "PDF_DAMAGED" in unrecognized[1][3]


def test_financial_report_writes_one_row_per_booking(tmp_path):
    reports = [financial_report(tmp_path, bookings=3)]
    result = export_batch_excel(reports, tmp_path)
    rows = read_sheet(result["path"], "Finanzreport")
    assert len(rows) == 4  # Kopfzeile + drei Buchungen
    # Spalte „Buchungsbetrag“ (Index 8) enthält jede Buchung in eigener Zeile.
    assert [row[8] for row in rows[1:]] == ["-1.10", "-2.10", "-3.10"]


def test_valid_zero_is_exported_and_missing_values_stay_empty(tmp_path):
    reports = [dividend_report(tmp_path)]
    result = export_batch_excel(reports, tmp_path)
    rows = read_sheet(result["path"], "Dividendengutschrift")
    values = rows[1]
    # Eine tatsächlich erkannte Steuer von 0,00 bleibt erhalten …
    assert "0" in values
    # … nicht erkannte Felder (hier Bemessungsgrundlage) sind leere Zellen;
    # openpyxl liest eine leere Zelle als None.
    assert None in values
    assert "None" not in values and "NOT_FOUND" not in values


def test_version_number_increments_and_never_overwrites(tmp_path):
    first = export_batch_excel([purchase_report(tmp_path)], tmp_path)["path"]
    assert first.name == f"{EXCEL_PREFIX}_v01.xlsx"
    second = export_batch_excel([purchase_report(tmp_path)], tmp_path)["path"]
    assert second.name == f"{EXCEL_PREFIX}_v02.xlsx"
    assert first.exists() and second.exists()
    assert next_excel_path(tmp_path).name == f"{EXCEL_PREFIX}_v03.xlsx"


def test_locked_workbook_uses_next_version(tmp_path, monkeypatch):
    from openpyxl.workbook import Workbook

    first = export_batch_excel([purchase_report(tmp_path)], tmp_path)["path"]
    original = Workbook.save
    calls = {"count": 0}

    def refusing_save(self, path):
        calls["count"] += 1
        if calls["count"] == 1:
            raise PermissionError(f"locked: {path}")
        return original(self, path)

    monkeypatch.setattr(Workbook, "save", refusing_save)
    result = export_batch_excel([purchase_report(tmp_path)], tmp_path)
    monkeypatch.undo()
    assert result["path"].name == f"{EXCEL_PREFIX}_v02.xlsx"
    assert result["path"].exists()
    assert first.exists()


def test_export_error_is_reported_not_raised(tmp_path, monkeypatch):
    from openpyxl.workbook import Workbook

    def broken_save(self, path):
        raise RuntimeError("boom")

    monkeypatch.setattr(Workbook, "save", broken_save)
    result = export_batch_excel([purchase_report(tmp_path)], tmp_path)
    assert result["path"] is None
    assert any("Excel-Export fehlgeschlagen" in error for error in result["errors"])
