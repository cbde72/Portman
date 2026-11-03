"""Konsistenz zwischen Parserresultat und CSV-Export (Abschnitt 7 des Auftrags).

Der Batch-Export darf keine Felder verlieren, die der Parser nachweislich aus
dem PDF erkannt hat: jeder ``flatten_evidence_values``-Pfad muss mit identischem
Wert in der CSV-Zeile stehen.  Zusätzlich werden das Semikolonformat, UTF-8-BOM,
die deterministische Spaltenreihenfolge und die Trennung von Trainingsspalten
gesichert.
"""

import csv
from decimal import Decimal

from portman_parsers.api import PdfDocument, PdfPage
from portman_parsers.plugins import ComdirectFinanzreportPlugin, ComdirectPlugin
from portman_pdf_lab.application.batch_csv import BASE_FIELDS, export_batch_csv, flatten_evidence_values


FINANZREPORT_TEXT = """comdirect
Finanzreport Nr. 7 per 31.01.2026
Kundennummer: 102 4764924
Girokonto DE00 0000 0000 0000 0000 01 +105,00
Tagesgeld PLUS-Konto DE11 0000 0000 0000 0000 11 +51,00
Girokonto Dispositionskredit 1.500 EUR
Buchungstag
Alter Saldo 01.01.2026 100,00
02.01.2026 02.01.2026 Gutschrift +10,00
03.01.2026 03.01.2026 Lastschrift -5,00
Neuer Saldo 31.01.2026 105,00
Tagesgeld PLUS-Konto
Buchungstag
Alter Saldo 01.01.2026 +50,00
05.01.2026 05.01.2026 Zinsen +1,00
Neuer Saldo 31.01.2026 +51,00
Depot
A0D8QZ / Girosammelverwahrung
ISH.S.EUR.SMALL 200 U.ETF
101,307 34,966 EUR 3.542,31
+0,00
2.735,85
+806,46
Gesamtkurswert
Stückzinsen gesamt
Gesamtwert
3.542,31
+0,00
3.542,31
2.735,85
+806,46"""

KAUF_TEXT = """comdirect
Wertpapierkauf
Depotnummer: 12345
IBAN DE00 0000 0000 0000 0000 01
Stk. 0,125 Beispiel Fonds , WKN / ISIN: ABC123 / DE0008474511
Geschäftstag 01.02.2026
Valuta 04.02.2026
Kurs EUR 1.000,00
Kurswert EUR 125,00
Provision EUR 1,50
Zu Ihren Lasten EUR 126,50
Referenz-Nummer:
14IKXK3WUKY00GUQ"""


def _report(plugin, text, name):
    document = PdfDocument("doc-" + name, ("h" * 64), (PdfPage(1, text),))
    detection = plugin.detect(document)[0]
    result = plugin.parse(document, detection)
    return {"source": name, "source_hash": document.source_hash, "document_id": document.document_id,
            "detection": {"plugin_id": detection.plugin_id, "handler_id": detection.handler_id,
                          "document_type": detection.document_type},
            "result": result.to_dict(), "timings": {"total_ns": 1}}


def _read(path):
    raw = path.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf", "CSV muss UTF-8 mit BOM sein"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        return reader.fieldnames, list(reader)


def test_csv_is_semicolon_separated_with_bom_and_stable_column_order(tmp_path):
    report = {"files": [_report(ComdirectFinanzreportPlugin(), FINANZREPORT_TEXT, "report.pdf")]}
    target = tmp_path / "parser_fields.csv"
    export_batch_csv(report, target)
    fields, rows = _read(target)
    assert fields[:7] == list(BASE_FIELDS)
    pdf_fields = fields[7:]
    assert pdf_fields == sorted(pdf_fields), "erkannte Felder müssen deterministisch sortiert sein"
    assert not any(field.startswith("training[") for field in pdf_fields)
    assert len(rows) == 1


def test_every_evidence_backed_parser_field_survives_the_csv_export(tmp_path):
    files = [_report(ComdirectFinanzreportPlugin(), FINANZREPORT_TEXT, "report.pdf"),
             _report(ComdirectPlugin(), KAUF_TEXT, "kauf.pdf")]
    report = {"files": files}
    target = tmp_path / "parser_fields.csv"
    export_batch_csv(report, target)
    _, rows = _read(target)
    by_source = {row["source"]: row for row in rows}
    for item in files:
        expected = flatten_evidence_values(item["result"])
        assert expected, "Testdokument muss nachgewiesene Felder liefern"
        row = by_source[item["source"]]
        for path, value in expected.items():
            assert path in row, f"CSV verliert das Parserfeld {path}"
            assert row[path] == value, f"CSV-Wert weicht ab für {path}: {row[path]!r} != {value!r}"


def test_depot_position_security_id_and_amounts_are_exported(tmp_path):
    report = {"files": [_report(ComdirectFinanzreportPlugin(), FINANZREPORT_TEXT, "report.pdf")]}
    target = tmp_path / "parser_fields.csv"
    export_batch_csv(report, target)
    fields, rows = _read(target)
    row = rows[0]
    assert "depot_snapshots[0].positions[0].security_id" in fields
    assert row["depot_snapshots[0].positions[0].security_id"] == "A0D8QZ"
    assert row["depot_snapshots[0].positions[0].quantity"] == str(Decimal("101.307"))
    assert row["depot_snapshots[0].positions[0].market_value"] == str(Decimal("3542.31"))
    assert row["depot_snapshots[0].total_value"] == str(Decimal("3542.31"))


def test_split_bank_reference_and_trade_values_are_exported(tmp_path):
    report = {"files": [_report(ComdirectPlugin(), KAUF_TEXT, "kauf.pdf")]}
    target = tmp_path / "parser_fields.csv"
    export_batch_csv(report, target)
    fields, rows = _read(target)
    row = rows[0]
    assert row["events[0].bank_reference"] == "14IKXK3WUKY00GUQ"
    assert row["events[0].security_wkn"] == "ABC123"
    assert row["events[0].trades[0].quantity"] == str(Decimal("0.125"))
    assert row["events[0].trades[0].price"] == str(Decimal("1000.00"))
    assert row["events[0].cash_movements[0].amount"] == str(Decimal("-126.50"))


def test_no_value_without_pdf_evidence_is_exported(tmp_path):
    report = {"files": [_report(ComdirectPlugin(), KAUF_TEXT, "kauf.pdf")]}
    target = tmp_path / "parser_fields.csv"
    export_batch_csv(report, target)
    fields, rows = _read(target)
    row = rows[0]
    result = report["files"][0]["result"]
    exported = {field for field in fields[7:] if row[field]}
    for field in exported:
        # Jede exportierte Zelle muss über ein Evidence im Parserresultat belegt sein.
        assert field in flatten_evidence_values(result) or field.startswith("training[")
