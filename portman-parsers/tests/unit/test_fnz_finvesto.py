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
