from decimal import Decimal

import pytest

from portman_parsers.api import CashStatus, PdfDocument, PdfPage
from portman_parsers.plugins import DekaQuartalsberichtPlugin
from portman_parsers.registry.registry import default_registry
from portman_parsers.validation import validate_parsed_document


ISIN = "DE000A0AAAA0"


def document(total="100,00", amount="10,00", include_turnover=True):
    overview = (
        "Deka\nQuartalsbericht per 31.03.2026\nDepot: 12345678\n"
        "Depotübersicht\n"
        f"{ISIN} 01 Musterfonds {total} +0,00\n"
        f"Gesamt in EUR {total} +0,00\n"
    )
    turnover = (
        "Umsatzübersicht\n"
        f"ISIN: {ISIN} Unterdepot: 01\n"
        "Bestand am 31.03.2026 100,00 10,000 10,000\n"
        "Bewertung mit dem Rücknahmepreis vom 31.03.2026\n"
        f"Ausschüttung / Kauf aus Ertrag {amount} 10,000 +1,000 20.03.2026 21.03.2026\n"
    )
    pages = (PdfPage(1, overview), PdfPage(2, turnover)) if include_turnover else (PdfPage(1, overview),)
    return PdfDocument("deka-test", "a" * 64, pages, "Deka.pdf")


def test_registry_detect_and_reconcile_snapshot():
    source = document()
    registry = default_registry()
    detection = registry.select(source)
    assert detection.plugin_id == "user.deka-quartalsbericht"
    result = registry.parse(source, detection)
    assert len(result.depots) == 1
    assert result.depot_snapshots[0].total_value.value == Decimal("100.00")
    assert result.depot_snapshots[0].positions[0].quantity.value == Decimal("10.000")
    assert not validate_parsed_document(result)


def test_distribution_and_reinvestment_do_not_book_actual_cash():
    plugin = DekaQuartalsberichtPlugin()
    source = document()
    result = plugin.parse(source, plugin.detect(source)[0])
    assert [event.kind for event in result.events] == ["DIVIDEND", "REINVESTMENT"]
    cash = [event.cash_movements[0] for event in result.events]
    assert [movement.status for movement in cash] == [CashStatus.EXPECTED] * 2
    assert all(movement.account_id is None for movement in cash)
    assert sum((movement.amount for movement in cash), Decimal(0)) == 0
    assert result.events[1].security_movements[0].quantity == Decimal("1.000")
    assert not validate_parsed_document(result)


def test_mismatched_overview_is_rejected():
    plugin = DekaQuartalsberichtPlugin()
    source = document(total="110,00")
    with pytest.raises(ValueError, match="do not reconcile"):
        plugin.parse(source, plugin.detect(source)[0])


def test_unknown_quantity_is_not_invented():
    plugin = DekaQuartalsberichtPlugin()
    source = document(include_turnover=False)
    result = plugin.parse(source, plugin.detect(source)[0])
    assert result.depot_snapshots[0].positions[0].quantity.value == "UNKNOWN"
    assert any(issue.code == "DEKA_QUANTITY_UNVERIFIED" for issue in result.issues)
    assert not result.events
