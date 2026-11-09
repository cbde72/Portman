from decimal import Decimal
import json

from portman_parsers.api import MissingValue, PdfDocument, PdfPage, normalize_result_payload
from portman_parsers.plugins import ComdirectFinanzreportPlugin, ComdirectPlugin


def parse_report(body: str):
    text = f"""comdirect
Finanzreport Nr. 42 per 11.09.2015
Girokonto DE89 3704 0044 0532 0130 00
Alter Saldo 01.09.2015 1.000,00
{body}
Neuer Saldo 30.09.2015 769,74"""
    source = PdfDocument("synthetic-report", "a" * 64, (PdfPage(1, text),))
    plugin = ComdirectFinanzreportPlugin()
    return plugin.parse(source, plugin.detect(source)[0])


def test_finanzreport_line_end_amount_does_not_merge_following_booking():
    result = parse_report("""07.09.2015
07.09.2015
Lastschrift/Belast.
AB0123456789/CD01/12345
Supermarkt EC 0001 123456 -30,26
10.09.2015
09.09.2015
Auszahlung GAA
EUR 200,00 GEB.EUR 0,00
-200,00""")

    assert [(event.event_date.isoformat(), event.cash_movements[0].amount) for event in result.events] == [
        ("2015-09-07", Decimal("-30.26")),
        ("2015-09-10", Decimal("-200.00")),
    ]
    assert "Supermarkt EC 0001 123456" in result.evidence[1].excerpt or any(
        "Supermarkt EC 0001 123456" in evidence.excerpt for evidence in result.evidence
    )
    evidence_by_id = {item.evidence_id: item for item in result.evidence}
    first_booking = evidence_by_id[result.events[0].evidence_ids[0]].excerpt
    second_booking = evidence_by_id[result.events[1].evidence_ids[0]].excerpt
    assert "10.09.2015" not in first_booking
    assert "Lastschrift" not in second_booking
    assert not any(issue.code == "BALANCE_MISMATCH" for issue in result.issues)


def test_finanzreport_unsigned_text_amount_does_not_close_block():
    result = parse_report("""07.09.2015
07.09.2015
Auszahlung
EUR 200,00 GEB.EUR 0,00
-200,00""")

    assert len(result.events) == 1
    assert result.events[0].cash_movements[0].amount == Decimal("-200.00")
    assert any("EUR 200,00 GEB.EUR 0,00" in evidence.excerpt for evidence in result.evidence)


def test_finanzreport_incomplete_block_before_new_date_pair_has_own_evidence():
    result = parse_report("""07.09.2015
07.09.2015
Lastschrift
Händler ohne Betrag
10.09.2015
09.09.2015
Auszahlung
-200,00""")

    incomplete = [issue for issue in result.issues if issue.code == "INCOMPLETE_BOOKING"]
    assert len(incomplete) == 1
    evidence = next(item for item in result.evidence if item.evidence_id == incomplete[0].evidence_id)
    assert "Händler ohne Betrag" in evidence.excerpt
    assert "10.09.2015" not in evidence.excerpt
    assert len(result.events) == 1
    assert result.events[0].event_date.isoformat() == "2015-09-10"


def test_finanzreport_security_identity_and_bank_reference_are_structured():
    result = parse_report("""02.09.2015
03.09.2015
Wertpapiere
0MEABC123456/2
Muster ETF Welt
WPKNR: A1JX52 ISIN:
IE00B3RBWM25
-57,98""")

    event = result.events[0]
    assert event.security_name == "Muster ETF Welt"
    assert event.security_wkn == "A1JX52"
    assert event.security_isin == "IE00B3RBWM25"
    assert event.bank_reference == "0MEABC123456/2"
    assert event.bank_reference_status == "RECOGNIZED"
    fields = {item.field: item.excerpt for item in result.evidence}
    assert "Muster ETF Welt" in fields["security_identity_name"]
    assert "WPKNR" in fields["security_wkn"]
    assert "IE00B3RBWM25" in fields["security_isin"]
    assert fields["bank_reference"] == "0MEABC123456/2"
    assert not event.security_movements


def test_finanzreport_invalid_isin_is_omitted_but_wkn_retained():
    result = parse_report("""02.09.2015
03.09.2015
Wertpapiere
0MEABC123456/2
Muster ETF Welt
WPKNR: A1JX52 ISIN:
DE000A0AAAA0
-57,98""")

    event = result.events[0]
    assert event.security_wkn == "A1JX52"
    assert event.security_isin is MissingValue.UNKNOWN
    assert any(issue.code == "COMDIRECT_SECURITY_ISIN_INVALID" for issue in result.issues)


def test_finanzreport_wkn_without_isin_keeps_only_the_known_identifier():
    result = parse_report("""02.09.2015
03.09.2015
Wertpapiere
0MEABC123456/2
Muster ETF Welt
WPKNR: A1JX52 ISIN:
-57,98""")

    event = result.events[0]
    assert event.security_wkn == "A1JX52"
    assert event.security_isin is MissingValue.UNKNOWN
    assert "security_wkn" in {item.field for item in result.evidence}
    assert "security_isin" not in {item.field for item in result.evidence}


def test_finanzreport_salary_row_recognizes_reference_without_security_identity():
    result = parse_report("""01.09.2015
01.09.2015
Gehalt
AB12345678/5302
Arbeitgeber GmbH
+100,00""")

    event = result.events[0]
    assert event.bank_reference == "AB12345678/5302"
    assert event.bank_reference_status == "RECOGNIZED"
    assert event.security_wkn is MissingValue.UNKNOWN
    assert event.security_isin is MissingValue.UNKNOWN


def test_finanzreport_malformed_security_reference_is_invalid_and_evidenced():
    result = parse_report("""02.09.2015
03.09.2015
Wertpapiere
BAD/2
Muster ETF Welt
WPKNR: A1JX52
-57,98""")

    event = result.events[0]
    assert event.bank_reference is MissingValue.UNKNOWN
    assert event.bank_reference_status == "INVALID"
    issue = next(item for item in result.issues if item.code == "COMDIRECT_BANK_REFERENCE_INVALID")
    assert next(item for item in result.evidence if item.evidence_id == issue.evidence_id).excerpt == "BAD/2"


def test_finanzreport_multiple_candidate_references_are_ambiguous():
    result = parse_report("""02.09.2015
03.09.2015
Wertpapiere
0MEABC123456/2
0MEABC999999/3
Muster ETF Welt
WPKNR: A1JX52
-57,98""")

    assert result.events[0].bank_reference_status == "AMBIGUOUS"
    assert result.events[0].bank_reference is MissingValue.UNKNOWN
    assert any(issue.code == "COMDIRECT_BANK_REFERENCE_AMBIGUOUS" for issue in result.issues)


def test_finanzreport_new_fields_survive_json_roundtrip():
    result = parse_report("""02.09.2015
03.09.2015
Wertpapiere
0MEABC123456/2
Muster ETF Welt
WPKNR: A1JX52 ISIN:
IE00B3RBWM25
-57,98""")
    restored = normalize_result_payload(json.loads(result.to_json()))

    event = restored["events"][0]
    assert event["security_isin"] == "IE00B3RBWM25"
    assert event["bank_reference"] == "0MEABC123456/2"
    assert {item["field"] for item in restored["evidence"]} >= {
        "booking", "bank_reference", "security_identity_name", "security_wkn", "security_isin"
    }


def test_finanzreport_document_level_balance_issue_has_balance_evidence():
    result = parse_report("""02.09.2015 02.09.2015 Gutschrift +10,00""")

    issue = next(item for item in result.issues if item.code == "BALANCE_MISMATCH")
    evidence = next(item for item in result.evidence if item.evidence_id == issue.evidence_id)
    assert evidence.field in {"opening_balance", "closing_balance"}
    assert "Saldo" in evidence.excerpt


def test_comdirect_trade_emits_directed_fx_only_for_explicit_pair():
    source = PdfDocument(
        "synthetic-trade", "b" * 64,
        (PdfPage(1, "comdirect\nWertpapierkauf\nDevisenkurs: 1 USD = 0,923456 EUR\nStk. 1,000 TEST ETF, WKN / ISIN: A1JX52 / IE00B3RBWM25\nZu Ihren Lasten EUR 100,00"),),
    )
    plugin = ComdirectPlugin()
    result = plugin.parse(source, plugin.detect(source)[0])
    rate = result.events[0].exchange_rates[0]

    assert rate.rate == Decimal("0.923456")
    assert rate.base_currency == "USD"
    assert rate.quote_currency == "EUR"
    assert rate.evidence_ids
    assert next(item for item in result.evidence if item.evidence_id == rate.evidence_ids[0]).excerpt == "Devisenkurs: 1 USD = 0,923456 EUR"


def test_comdirect_trade_does_not_turn_undirected_rate_into_fx_pair():
    source = PdfDocument(
        "synthetic-trade-legacy-rate", "c" * 64,
        (PdfPage(1, "comdirect\nWertpapierkauf\nDevisenkurs: 0,923456\nStk. 1,000 TEST ETF, WKN / ISIN: A1JX52 / IE00B3RBWM25\nZu Ihren Lasten EUR 100,00"),),
    )
    plugin = ComdirectPlugin()
    result = plugin.parse(source, plugin.detect(source)[0])

    assert not result.events[0].exchange_rates


def test_finanzreport_snapshot_keeps_usd_position_and_separates_field_sources():
    text = """comdirect
Finanzreport Nr. 7 per 31.01.2026
Depotnummer: 123456
Depot
WKN / Verwahrart
A1JX52 / Girosammelverwahrung
Muster ETF Welt
2,000 10,00 USD 20,00
Depotgesamtwert 20,00 EUR"""
    source = PdfDocument("synthetic-depot-report", "d" * 64, (PdfPage(1, text),))
    plugin = ComdirectFinanzreportPlugin()
    result = plugin.parse(source, plugin.detect(source)[0])

    position = result.depot_snapshots[0].positions[0]
    assert position.security_id.value == "A1JX52"
    assert position.custody_type.value == "Girosammelverwahrung"
    assert position.quantity.value == Decimal("2.000")
    assert position.security_name.value == "Muster ETF Welt"
    assert position.market_value.value == Decimal("20.00")
    assert position.currency.value == "EUR"
    assert position.price.value is MissingValue.UNKNOWN
    assert position.security_id.evidence_ids != position.quantity.evidence_ids
    assert position.custody_type.evidence_ids != position.security_id.evidence_ids
    assert position.quantity.evidence_ids != position.market_value.evidence_ids
    evidence_by_id = {item.evidence_id: item for item in result.evidence}
    assert "A1JX52" in evidence_by_id[position.security_id.evidence_ids[0]].excerpt
    assert "Girosammelverwahrung" in evidence_by_id[position.custody_type.evidence_ids[0]].excerpt
    assert "2,000 10,00 USD 20,00" in evidence_by_id[position.quantity.evidence_ids[0]].excerpt
