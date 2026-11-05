from pathlib import Path
from decimal import Decimal

from portman_parsers.api import CashStatus, PdfDocument, PdfPage
from portman_parsers.plugins import FnzFinvestoPlugin
from portman_parsers.validation import validate_parsed_document

FIXTURES = Path(__file__).parents[1] / "fixtures" / "fnz"


def document(name):
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return PdfDocument("doc-" + name, "a" * 64, (PdfPage(1, text),), name)


def test_turnover_detects_and_parses_dividend_reinvestment_and_buy():
    plugin = FnzFinvestoPlugin(); source = document("turnover.txt")
    detection = plugin.detect(source)[0]
    result = plugin.parse(source, detection)
    assert detection.handler_id == "umsatzabrechnung"
    assert [event.kind for event in result.events] == ["DIVIDEND", "REINVESTMENT", "BUY"]
    assert all(m.status is CashStatus.EXPECTED for e in result.events for m in e.cash_movements)
    assert all(m.account_id is None for e in result.events for m in e.cash_movements)
    assert result.events[2].fee_events[0].subcategory == "transaction_fee"
    assert not result.events[0].security_movements
    assert result.events[1].security_movements[0].quantity == Decimal("0.100")
    assert result.depot_snapshots[0].total_value.value == 560
    assert not validate_parsed_document(result)


def test_dividend_and_reinvestment_are_two_linked_economic_effects_not_actual_cash():
    result = FnzFinvestoPlugin().parse(document("turnover.txt"),
                                       FnzFinvestoPlugin().detect(document("turnover.txt"))[0])
    dividend, reinvestment = result.events[:2]
    assert dividend.cash_movements[0].amount == 10
    assert reinvestment.cash_movements[0].amount == -10
    assert sum((e.cash_movements[0].amount for e in (dividend, reinvestment)), 0) == 0


def test_depot_statement_creates_snapshot_without_transactions():
    plugin = FnzFinvestoPlugin(); source = document("depot_statement.txt")
    result = plugin.parse(source, plugin.detect(source)[0])
    assert not result.events
    assert len(result.depot_snapshots) == 1
    assert result.depot_snapshots[0].positions[0].quantity.value == Decimal("5.600")
    assert result.depot_snapshots[0].total_value.value == 560


def test_unknown_settlement_account_is_not_invented():
    plugin = FnzFinvestoPlugin(); source = document("turnover.txt")
    result = plugin.parse(source, plugin.detect(source)[0])
    assert not result.accounts
    assert not result.depot_account_links


def test_foreign_currency_tax_components_reconcile_to_documented_total():
    text = (FIXTURES / "turnover.txt").read_text(encoding="utf-8")
    text = text.replace("DE0008474511 5,000 2,0000 USD 10,00 USD", "DE0008474511 5,000 0,5960 USD 2,98 USD", 1)
    text = text.replace(
        "Zahlungsbetrag 10,00 USD",
        "Kapitalertragsteuer Solidaritätszuschlag Kirchensteuer Devisenkurs abzgl. Steuern\n"
        "0,45 EUR 0,02 EUR 0,00 EUR 1,153077 0,54 USD\nZahlungsbetrag 2,44 USD", 1)
    source = PdfDocument("taxed", "b" * 64, (PdfPage(1, text),), "taxed.pdf")
    plugin = FnzFinvestoPlugin()
    result = plugin.parse(source, plugin.detect(source)[0])
    dividend = result.events[0]
    assert dividend.cash_movements[0].amount == Decimal("2.44")
    assert dividend.tax_events[0].actually_withheld_tax == Decimal("0.54")
    assert [(item.kind, item.amount, item.currency) for item in dividend.tax_events[0].components] == [
        ("CAPITAL_GAINS_TAX", Decimal("0.52"), "USD"),
        ("SOLIDARITY_SURCHARGE", Decimal("0.02"), "USD"),
        ("CHURCH_TAX", Decimal("0.00"), "USD"),
    ]


def test_vertical_depot_position_and_evidence_page_are_preserved():
    text = """FNZ Bank SE
Depotauszug für Ihr finvesto Depot bei der FNZ Bank
Depot-Nr. 12345678901
Bestand
Depotpositionen
02
DE0008474511
5
,600
100
,0000 USD
30.09.2026
1
,0000
560
,00 EUR
"""
    source = PdfDocument("vertical", "c" * 64, (PdfPage(1, "Hinweis"), PdfPage(2, text)), "vertical.pdf")
    plugin = FnzFinvestoPlugin()
    result = plugin.parse(source, plugin.detect(source)[0])
    position = result.depot_snapshots[0].positions[0]
    assert (position.quantity.value, position.price.value, position.market_value.value) == (
        Decimal("5.600"), Decimal("100.0000"), Decimal("560.00"))
    assert result.depots[0].depot_number.page_number == 2
    assert position.quantity.page_number == 2
    assert all(item.page_number == 2 for item in result.evidence)
