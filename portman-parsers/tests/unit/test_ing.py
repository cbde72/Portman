from decimal import Decimal
from pathlib import Path

import pytest

from portman_parsers.api import CashStatus, PdfDocument, PdfPage
from portman_parsers.registry import default_registry
from portman_parsers.validation import validate_parsed_document


FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "importers" / "ing"


def source(text, identity="ing"):
    return PdfDocument(identity, "a" * 64, (PdfPage(1, text),), identity + ".pdf")


@pytest.mark.parametrize(
    "folder,kind,amount,tax",
    [
        ("verkauf", "SELL", Decimal("99.00"), Decimal(0)),
        ("vorabpauschale", "ADVANCE_TAX", Decimal("-2.63"), Decimal("2.63")),
        ("steuererstattung", "TAX_REFUND", Decimal("2.63"), Decimal("2.63")),
    ],
)
def test_v09_regression_fixtures(folder, kind, amount, tax):
    text = (FIXTURES / folder / "current-v1" / "source.txt").read_text(encoding="utf-8")
    document = source(text)
    registry = default_registry()
    detection = registry.select(document)
    result = registry.parse(document, detection)
    event = result.events[0]
    assert event.kind == kind
    assert event.cash_movements[0].amount == amount
    assert event.cash_movements[0].status is CashStatus.EXPECTED
    assert sum((item.actually_withheld_tax for item in event.tax_events), Decimal()) == tax
    assert result.to_json() == registry.parse(document, detection).to_json()
    assert not [issue for issue in validate_parsed_document(result) if issue.severity.value == "ERROR"]
    assert all(item.excerpt in document.pages[item.page_number - 1].text for item in result.evidence)


def test_trade_tax_is_not_counted_as_fee():
    text = (FIXTURES / "verkauf" / "current-v1" / "source.txt").read_text(encoding="utf-8")
    text = text.replace("Endbetrag zu Ihren Gunsten EUR 99,00", "Kapitalertragsteuer EUR 0,50\nEndbetrag zu Ihren Gunsten EUR 98,50")
    document = source(text)
    result = default_registry().parse(document, default_registry().select(document))
    event = result.events[0]
    assert event.fee_events[0].amount == Decimal("1.00")
    assert event.tax_events[0].actually_withheld_tax == Decimal("0.50")


def test_unreconciled_advance_tax_is_rejected():
    text = (FIXTURES / "vorabpauschale" / "current-v1" / "source.txt").read_text(encoding="utf-8")
    document = source(text.replace("2,63", "9,99"))
    registry = default_registry()
    with pytest.raises(ValueError, match="Steuerkomponenten"):
        registry.parse(document, registry.select(document))


def test_dividend_preserves_reinvestment_and_tax_details_without_extra_cashflow():
    document = source("""ING-DiBa
Dividendengutschrift
Direkt-Depot Nr.: 1234567890
ISIN (WKN) DE000BASF111 (BASF11)
Wertpapierbezeichnung BASF SE
Nominale 2,00 Stück
Ex-Tag 01.07.2026
Zahltag 03.07.2026
Zins-/Dividendensatz 1,0000 EUR
Brutto EUR 2,00
KapSt-pflichtiger Kapitalertrag 2,00 EUR
Sparer-Pauschbetrag vor Ertrag 100,00 EUR
Sparer-Pauschbetrag nach Ertrag 98,00 EUR
Gesamtbetrag zu Ihren Gunsten EUR 2,00
Abrechnungs-IBAN DE11 1111 1111 1111 1111 11
Valuta 03.07.2026
Ihren Ertrag haben wir für Sie automatisch wieder angelegt.
""")
    registry = default_registry()
    result = registry.parse(document, registry.select(document))
    assert result.events[0].kind == "DIVIDEND"
    assert len(result.events[0].cash_movements) == 1
    assert result.events[0].cash_movements[0].amount == Decimal("2.00")
    assert result.events[0].tax_events[0].taxable_basis == Decimal("2.00")
    assert result.attributes["ex_date"] == "01.07.2026"
    assert result.attributes["allowance_after"] == "98,00"
    assert any(issue.code == "ING_WIEDERANLAGE" for issue in result.issues)


def test_buy_is_expected_cash_and_depot_movement():
    text = (FIXTURES / "verkauf" / "current-v1" / "source.txt").read_text(encoding="utf-8")
    text = text.replace("Wertpapierabrechnung Verkauf", "Wertpapierabrechnung Kauf")
    text = text.replace("Endbetrag zu Ihren Gunsten EUR 99,00", "Endbetrag zu Ihren Lasten EUR 101,00")
    document = source(text)
    registry = default_registry()
    result = registry.parse(document, registry.select(document))
    event = result.events[0]
    assert event.kind == "BUY"
    assert event.cash_movements[0].amount == Decimal("-101.00")
    assert event.security_movements[0].quantity == Decimal("2.00")
    assert event.fee_events[0].amount == Decimal("1.00")


def test_statement_total_and_count_must_reconcile():
    text = """ING-DiBa
Jahresdepotauszug
Direkt-Depot Nr.: 1234567890
zum 31.12.2026 abgeschlossene Aufstellung
2,00 Stück BASF SE 50,00 EUR 100,00 EUR
ISIN (WKN): DE000BASF111 (BASF11)
Übertrag Kurswert 100,00 EUR
Gesamtkurswert 100,00 EUR
Anzahl Posten: 1
"""
    registry = default_registry()
    document = source(text)
    result = registry.parse(document, registry.select(document))
    assert result.depot_snapshots[0].positions[0].market_value.value == Decimal("100.00")
    wrong = source(text.replace("Gesamtkurswert 100,00", "Gesamtkurswert 101,00"), "wrong")
    with pytest.raises(ValueError, match="Positionssumme"):
        registry.parse(wrong, registry.select(wrong))
