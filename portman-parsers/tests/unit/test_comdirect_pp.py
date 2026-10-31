"""Synthetic behavioral tests inspired by the public PP comdirect test categories.

No Portfolio Performance fixture or source code is copied into this test module.
"""
from decimal import Decimal

from portman_parsers.api import MissingValue, PdfDocument, PdfPage
from portman_parsers.plugins import ComdirectPPPlugin


def document(identity, body):
    return PdfDocument(identity, identity[0] * 64, (PdfPage(1, "comdirect bank\n" + body),))


def parse(body, identity="pp-test"):
    plugin = ComdirectPPPlugin()
    source = document(identity, body)
    detection = plugin.detect(source)[0]
    return detection, plugin.parse(source, detection)


def test_partial_buy_preserves_pp_security_row_price_fees_and_settlement():
    detection, result = parse("""Wertpapierkauf
Stk. 0,125 Beispiel ETF, WKN / ISIN: ABC123 / DE0008474511
Geschäftstag 01.02.2026
Ausführungskurs EUR 1.000,00
Kurswert EUR 125,00
Provision EUR 1,50-
Die Belastung erfolgt mit Valuta 04.02.2026
Zu Ihren Lasten EUR 126,50""")
    event = result.events[0]
    assert detection.handler_id == "wertpapierkauf"
    assert event.security_movements[0].quantity == Decimal("0.125")
    assert event.cash_movements[0].amount == Decimal("-126.50")
    assert event.trades[0].security_name == "Beispiel ETF"
    assert event.trades[0].wkn == "ABC123" and event.trades[0].price == Decimal("1000.00")
    assert event.fee_events[0].amount == Decimal("1.50")


def test_sale_taxes_and_multiple_fee_categories_are_unsigned_components():
    _, result = parse("""Wertpapierverkauf
Stk. 2,500 Beispiel AG, WKN / ISIN: XYZ789 / DE0008474511
Valuta 03.03.2026
Kurs EUR 50,00
Kurswert EUR 125,00
Kapitalertragsteuer EUR 2,50-
Solidaritätszuschlag EUR 0,13-
Fremde Spesen EUR 1,00-
Maklercourtage EUR 0,50-
Zu Ihren Gunsten EUR 120,87""", "sale")
    event = result.events[0]
    assert event.security_movements[0].quantity == Decimal("-2.500")
    assert event.cash_movements[0].amount == Decimal("120.87")
    assert [x.amount for x in event.tax_events[0].components] == [Decimal("2.50"), Decimal("0.13")]
    assert {x.subcategory for x in event.fee_events} == {"foreign_expenses", "brokerage"}


def test_dividend_and_earnings_are_credits_without_duplicate_tax_cash():
    for title in ("Dividendengutschrift", "Ertragsgutschrift"):
        detection, result = parse(f"""{title}
Stk. 10,000 Beispiel Fonds, WKN / ISIN: ABC123 / DE0008474511
Kapitalertragsteuer EUR 2,00-
Zu Ihren Gunsten EUR 18,00""", "d" + str(len(title)))
        event = result.events[0]
        assert detection.handler_id in {"dividendengutschrift", "ertragsgutschrift"}
        assert len(event.cash_movements) == 1 and event.cash_movements[0].amount == Decimal("18.00")
        assert len(event.tax_events) == 1


def test_tax_notices_and_advance_tax_are_cash_neutral():
    cases = (
        ("Steuerliche Behandlung: Investment-Ausschüttung", "investment_ausschuettung"),
        ("Steuerliche Behandlung: Inländische Dividende", "dividende_steuer_inland"),
        ("Steuerliche Behandlung: Vorabpauschale", "vorabpauschale"),
    )
    for index, (title, handler) in enumerate(cases):
        detection, result = parse(f"""{title}
ISIN DE0008474511
Vorabpauschale EUR 10,00
Steuerbemessungsgrundlage EUR 7,00
Kapitalertragsteuer EUR 1,75-
Zufluss 02.01.2026""", f"t{index}")
        assert detection.handler_id == handler
        assert not result.events[0].cash_movements
        if handler == "vorabpauschale":
            assert len(result.tax_calculations) == 1


def test_financial_report_signed_rows_and_duplicates():
    _, result = parse("""Finanzreport Nr. 1
01.01.2026 Überweisung +100,00 EUR
02.01.2026 Kontoführungsentgelt -4,90 EUR
02.01.2026 Kontoführungsentgelt -4,90 EUR""", "report")
    assert [x.cash_movements[0].amount for x in result.events] == [Decimal("100.00"), Decimal("-4.90")]
    assert any(x.code == "PP_DUPLICATE_BOOKING" for x in result.issues)


def test_missing_trade_fields_are_explicit_and_no_value_is_invented():
    _, result = parse("Wertpapierkauf", "missing")
    assert {x.code for x in result.issues} == {"PP_SECURITY_MISSING", "PP_QUANTITY_MISSING", "PP_SETTLEMENT_MISSING"}
    trade = result.events[0].trades[0]
    assert trade.isin == MissingValue.NOT_FOUND and trade.settlement_amount == MissingValue.NOT_FOUND


def test_pp_variant_has_provenance_and_no_portman_plugin_delegation():
    _, result = parse("Dividendengutschrift\nZu Ihren Gunsten EUR 1,00", "origin")
    assert result.attributes["source_license"] == "EPL-1.0"
    assert "c08d5053" in result.attributes["rule_origin"]
