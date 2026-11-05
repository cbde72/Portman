from decimal import Decimal

import pytest

from portman_parsers.api import CashStatus, PdfDocument, PdfPage
from portman_parsers.plugins import BaaderPlugin
from portman_parsers.registry.registry import default_registry
from portman_parsers.validation import validate_parsed_document


def document(text, identity="baader"):
    return PdfDocument(identity, "a" * 64, (PdfPage(1, text),), identity + ".pdf")


TRADE = """Baader Bank AG
Depot-Nr.: 1234567890
Referenz-Nr.: 12345
Wertpapierabrechnung: {kind}
ISIN: DE000BASF111 WKN: BASF11
STK 2  BASF SE  EUR 60,00
Kurswert EUR 120,00
{costs}{direction} Konto 1234567005 Valuta: 03.07.2026 EUR {net}
Details zur Ausführung:
Handelsdatum Handelsuhrzeit
01.07.2026 10:00:00
Verwahrart: Girosammelverwahrung
"""


def trade(kind="Kauf", costs="", net="120,00"):
    return TRADE.format(kind=kind, costs=costs, direction="Zu Lasten" if kind == "Kauf" else "Zu Gunsten", net=net)


def test_registry_trade_preserves_cash_security_fee_tax_and_idempotency():
    source = document(trade(costs="Mindermengenzuschlag Finanzen.net EUR 1,00\nKapitalertragsteuer EUR 25,00\n", net="146,00"))
    registry = default_registry()
    detection = registry.select(source)
    result = registry.parse(source, detection)
    event = result.events[0]
    assert (detection.handler_id, event.kind, event.event_date.isoformat()) == ("wertpapierabrechnung", "BUY", "2026-07-01")
    assert event.cash_movements[0].amount == Decimal("-146.00")
    assert event.cash_movements[0].status is CashStatus.EXPECTED
    assert event.security_movements[0].quantity == Decimal("2")
    assert event.fee_events[0].amount == Decimal("1.00")
    assert event.tax_events[0].actually_withheld_tax == Decimal("25.00")
    assert event.trades[0].value_date.isoformat() == "2026-07-03"
    again = registry.parse(source, detection)
    assert result.to_json() == again.to_json()
    assert not validate_parsed_document(result)


def test_sale_direction_and_zero_settlement_remain_supported():
    plugin = BaaderPlugin()
    source = document(trade("Verkauf"))
    event = plugin.parse(source, plugin.detect(source)[0]).events[0]
    assert event.cash_movements[0].amount == Decimal("120.00")
    assert event.security_movements[0].quantity == Decimal("-2")
    zero = trade("Verkauf", "Mindermengenzuschlag Finanzen.net EUR 120,00\n", "0,00")
    zero = zero.replace("Zu Gunsten Konto 1234567005", "Total")
    event = plugin.parse(document(zero, "zero"), plugin.detect(document(zero, "zero"))[0]).events[0]
    assert event.cash_movements[0].amount == 0


def test_quarter_snapshot_reconciles_positions_and_total():
    text = """Baader Bank AG
Depot-Nr.: 1234567890
Quartalsaufstellung
MIFID II per 30.06.2026
Aktien und aktienähnliche
Stück 10 WKN: BASF11 EUR 50,000 500,00 EUR
ISIN: DE000BASF111
BASF SE
Depotwert 500,00 EUR
"""
    plugin = BaaderPlugin()
    source = document(text)
    snapshot = plugin.parse(source, plugin.detect(source)[0]).depot_snapshots[0]
    assert snapshot.as_of.value.isoformat() == "2026-06-30"
    assert snapshot.positions[0].quantity.value == Decimal("10")
    assert snapshot.total_value.value == Decimal("500.00")
    with pytest.raises(ValueError, match="Positionssumme"):
        changed = document(text.replace("Depotwert 500,00", "Depotwert 501,00"), "changed")
        plugin.parse(changed, plugin.detect(changed)[0])


def test_dividend_reversal_is_linked_and_unverified_change_rejected():
    template = """Baader Bank AG
Depot-Nr.: 3128164001
Vorgangs-Nr.: 26172813
Referenz-Nr.: {reference}
Dividendenabrechnung {storno}
Nominale ISIN: US0378331005 WKN: 865985 Ausschüttung
STK 4,125 Apple Inc.  USD 0,24 p.STK
US-Quellensteuer EUR 0,14 -
Zu Gunsten Konto 3128164005 Valuta: 15.02.2024 EUR 0,78
"""
    plugin = BaaderPlugin()
    original = document(template.format(reference="524443206", storno=""), "original")
    reversal = document(template.format(reference="526758625", storno="STORNO"), "reversal")
    first = plugin.parse(original, plugin.detect(original)[0]).events[0]
    second = plugin.parse(reversal, plugin.detect(reversal)[0]).events[0]
    assert first.cash_movements[0].amount == Decimal("0.78")
    assert second.cash_movements[0].amount == Decimal("-0.78")
    assert second.reversal_of_event_id == first.event_id
    changed = document(template.format(reference="526758625", storno="STORNO").replace("4,125", "4,126"), "changed")
    with pytest.raises(ValueError, match="keinem vollständig geprüften"):
        plugin.parse(changed, plugin.detect(changed)[0])


def test_transfer_has_only_documented_security_effect():
    text = """Baader Bank AG
Depot-Nr.: 1234567890
Depoteinlieferung
Nominale ISIN: DE000BASF111 WKN: BASF11 Lieferung
STK 2 BASF SE
Lagerstelle: 123 Valuta: 01.07.2026
EINLIEFERUNG-123.45
"""
    plugin = BaaderPlugin()
    source = document(text)
    event = plugin.parse(source, plugin.detect(source)[0]).events[0]
    assert event.kind == "TRANSFER_IN" and event.security_movements[0].quantity == 2
    assert not event.cash_movements


def test_krypto_document_is_not_selected():
    source = document("Baader Bank AG\nDepot-Nr.: 1234567890\nWertpapierabrechnung: Kauf\nBitcoin")
    assert not BaaderPlugin().detect(source)


def test_trade_rejects_unverified_storno_and_preserves_wkn():
    plugin = BaaderPlugin()
    source = document(trade())
    event = plugin.parse(source, plugin.detect(source)[0]).events[0]
    assert event.security_wkn == "BASF11"
    storno = document(trade().replace("Wertpapierabrechnung: Kauf", "Wertpapierabrechnung: Kauf Storno"), "storno")
    with pytest.raises(ValueError, match="Stornobeleg"):
        plugin.parse(storno, plugin.detect(storno)[0])


def test_advance_tax_rejects_unreconciled_components():
    source = document("""Baader Bank AG
Depot-Nr.: 1234567890
Vorabpauschale
Referenz-Nr.: 12345
Nominale ISIN: DE000BASF111 WKN: BASF11
STK 2 BASF SE
Kapitalertragsteuer EUR 1,00
Zu Lasten Konto 1234567005 Valuta: 03.07.2026 EUR 2,00
""")
    plugin = BaaderPlugin()
    with pytest.raises(ValueError, match="Steuerkomponenten"):
        plugin.parse(source, plugin.detect(source)[0])
