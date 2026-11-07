import json

from portman_parsers.api import PdfDocument, PdfPage
from portman_parsers.plugins import ComdirectPlugin
from portman_parsers.plugins.comdirect import (
    _extract_comdirect_security_identity,
    extract_comdirect_security_identity,
)


def _identity(text, layout_text=None):
    return _extract_comdirect_security_identity(text, layout_text)


def _document(*pages):
    return PdfDocument("identity-doc", "e" * 64, tuple(PdfPage(number, text) for number, text in enumerate(pages, 1)))


def _dividend(identity_lines, extra=""):
    return (
        "comdirect\nAbrechnung Dividendengutschrift\n"
        "Depotbestand Wertpapier-Bezeichnung WKN/ISIN\n"
        + identity_lines
        + "\nzahlbar ab 15.06.2026\nAbrechnung Dividendengutschrift\n"
        + "Zu Ihren Gunsten EUR 12,46\n"
        + extra
    )


def test_glued_isin_after_quantity_keeps_name_and_identifiers_apart():
    identity = _identity(
        "Wertpapier-Bezeichnung WKN/ISIN\n"
        "per 12.06.2026 A0H074iSh.DJ Asia Pa.S.D.50 U.ETF DE\n"
        "STK 26,122 DE000A0H0744Inhaber-Anteile"
    )
    assert identity.status == "RECOGNIZED"
    assert (identity.wkn, identity.isin) == ("A0H074", "DE000A0H0744")
    assert identity.name == "iSh.DJ Asia Pa.S.D.50 U.ETF Inhaber-Anteile"


def test_glued_wkn_before_name_keeps_name_and_identifier_apart():
    identity = _identity(
        "Wertpapier-Bezeichnung WKN/ISIN\n"
        "per 05.05.2026 716460SAP SE\n"
        "STK 1,794 DE0007164600Inhaber-Aktien o.N."
    )
    assert identity.status == "RECOGNIZED"
    assert (identity.wkn, identity.isin) == ("716460", "DE0007164600")
    assert identity.name == "SAP SE Inhaber-Aktien o.N."


def test_country_prefix_before_isin_is_not_part_of_the_name():
    identity = _identity(
        "Wertpapier-Bezeichnung WKN/ISIN\n"
        "per 12.06.2026 A0H074iSh.DJ Asia Pa.S.D.50 U.ETF DE\n"
        "STK 26,122 DE000A0H0744Inhaber-Anteile"
    )
    assert " U.ETF DE" not in identity.name
    assert identity.name_rows == ("iSh.DJ Asia Pa.S.D.50 U.ETF", "Inhaber-Anteile")


def test_name_fragments_before_identifiers_are_combined_in_row_order():
    identity = _identity(
        "Wertpapier-Bezeichnung            WKN/ISIN\n"
        "per 15.05.2024                        SAP SE                                  716460\n"
        "STK               0,733               Inhaber-Aktien o.N.               DE0007164600"
    )
    assert identity.name == "SAP SE Inhaber-Aktien o.N."
    assert identity.status == "RECOGNIZED"


def test_multi_line_name_continuation_between_identifier_rows_is_used():
    identity = _identity(
        "Wertpapier-Bezeichnung WKN/ISIN\n"
        "per 01.02.2025 123456 First\n"
        "Second Name\n"
        "STK 1,000 DE000A1B2C35 Third Part"
    )
    assert identity.name == "First Second Name Third Part"
    assert identity.status == "RECOGNIZED"


def test_wkn_only_block_is_partial_and_does_not_invent_an_isin():
    identity = _identity(
        "Wertpapier-Bezeichnung WKN/ISIN\n"
        "per 01.02.2025 716460 SAP SE\n"
        "STK 1,000 Inhaber-Aktien"
    )
    assert identity.status == "PARTIAL"
    assert (identity.wkn, identity.isin, identity.name) == ("716460", None, "SAP SE")


def test_isin_only_block_is_recognized_without_inventing_a_wkn():
    identity = _identity(
        "Wertpapier-Bezeichnung WKN/ISIN\n"
        "per 01.02.2025 DE0007164600 SAP SE\n"
        "STK 1,000 Inhaber-Aktien"
    )
    assert identity.status == "RECOGNIZED"
    assert (identity.wkn, identity.isin) == (None, "DE0007164600")


def test_block_without_identifiers_is_not_found():
    identity = _identity(
        "Wertpapier-Bezeichnung WKN/ISIN\n"
        "per 01.02.2025 Unbekannter Fonds\n"
        "STK 1,000 Inhaber-Anteile"
    )
    assert identity.status == "NOT_FOUND"
    assert (identity.name, identity.wkn, identity.isin) == (None, None, None)


def test_invalid_isin_checksum_is_reported_as_invalid():
    identity = _identity(
        "Wertpapier-Bezeichnung WKN/ISIN\n"
        "per 01.02.2025 Generic Fund 123456\n"
        "STK 1,000 Accumulating Shares DE000A1B2C34"
    )
    assert identity.status == "INVALID"
    assert identity.isin is None


def test_multiple_distinct_wkns_are_ambiguous():
    identity = _identity(
        "Wertpapier-Bezeichnung WKN/ISIN\n"
        "per 01.02.2025 First Fund 123456 654321\n"
        "STK 1,000 First Shares DE000A1B2C35"
    )
    assert identity.status == "AMBIGUOUS"


def test_multiple_distinct_isins_are_ambiguous():
    identity = _identity(
        "Wertpapier-Bezeichnung WKN/ISIN\n"
        "per 01.02.2025 First Fund 123456\n"
        "STK 1,000 DE0007164600 DE000A0H0744"
    )
    assert identity.status == "AMBIGUOUS"


def test_repeated_identical_wkn_is_not_ambiguous():
    identity = _identity(
        "Wertpapier-Bezeichnung WKN/ISIN\n"
        "per 01.02.2025 716460 SAP SE\n"
        "STK 1,000 716460 DE0007164600 Inhaber-Aktien"
    )
    assert identity.status == "RECOGNIZED"
    assert identity.wkn == "716460"


def test_wkn_inside_isin_is_not_extracted_as_separate_identifier():
    identity = _identity(
        "Wertpapier-Bezeichnung WKN/ISIN\n"
        "per 01.02.2025 DE0007164600 SAP SE\n"
        "STK 1,000 Inhaber-Aktien"
    )
    assert identity.wkn is None
    assert identity.isin == "DE0007164600"


def test_isin_embedded_in_a_longer_digit_run_is_rejected():
    identity = _identity(
        "Wertpapier-Bezeichnung WKN/ISIN\n"
        "per 01.02.2025 123456 Fund\n"
        "STK 1,000 12345DE000A0H0744Inhaber"
    )
    assert identity.isin is None
    assert identity.status == "PARTIAL"


def test_purchase_block_with_name_before_identifiers_is_recognized():
    identity = _identity(
        "Wertpapier-Bezeichnung WPKNR/ISIN\n"
        "Lang & Schwarz AG LS9AVX\n"
        "O.END 13(13/unl.) WFUMBRELLA DE000LS9AVX3"
    )
    assert identity.status == "RECOGNIZED"
    assert (identity.wkn, identity.isin) == ("LS9AVX", "DE000LS9AVX3")
    assert identity.name == "Lang & Schwarz AG O.END 13(13/unl.) WFUMBRELLA"


def test_legal_suffix_se_is_not_removed_as_country_prefix():
    identity = _identity(
        "Wertpapier-Bezeichnung WKN/ISIN\n"
        "per 01.02.2025 123456 Some Company SE\n"
        "STK 1,000 Shares SE0000108656"
    )
    assert identity.isin == "SE0000108656"
    assert identity.name == "Some Company SE Shares"


def test_unrelated_six_digit_number_outside_the_block_is_ignored():
    identity = _identity(
        "Konto 123456\n"
        "Wertpapier-Bezeichnung WKN/ISIN\n"
        "per 01.02.2025 Unbekannter Fonds\n"
        "STK 1,000 Inhaber-Anteile\n"
        "Referenz 716460"
    )
    assert identity.status == "NOT_FOUND"
    assert (identity.wkn, identity.isin) == (None, None)


def test_spaced_glyph_name_is_repaired_around_glued_isin():
    identity = _identity(
        "Wertpapier-Bezeichnung WKN/ISIN\n"
        "per 01.02.2025 Example-ETF A1B2C3\n"
        "STK 1,000 I n h a b e r - A n t e i l e o . N . DE000A1B2C35"
    )
    assert identity.name == "Example-ETF Inhaber-Anteile o.N."
    assert identity.isin == "DE000A1B2C35"


def test_tuple_api_remains_compatible():
    text = (
        "Wertpapier-Bezeichnung WKN/ISIN\n"
        "per 12.06.2026 A0H074iSh.DJ Asia Pa.S.D.50 U.ETF DE\n"
        "STK 26,122 DE000A0H0744Inhaber-Anteile"
    )
    assert extract_comdirect_security_identity(text) == (
        "iSh.DJ Asia Pa.S.D.50 U.ETF Inhaber-Anteile",
        "A0H074",
        "DE000A0H0744",
    )


def test_dividend_parses_glued_identity_without_missing_issue():
    text = _dividend(
        "per 12.06.2026 A0H074iSh.DJ Asia Pa.S.D.50 U.ETF DE\n"
        "STK 26,122 DE000A0H0744Inhaber-Anteile"
    )
    plugin = ComdirectPlugin()
    document = _document(text)
    result = plugin.parse(document, plugin.detect(document)[0])
    event = result.events[0]
    assert event.kind == "DIVIDEND"
    assert (event.security_name, event.security_wkn, event.security_isin) == (
        "iSh.DJ Asia Pa.S.D.50 U.ETF Inhaber-Anteile",
        "A0H074",
        "DE000A0H0744",
    )
    assert not any(issue.code == "COMDIRECT_SECURITY_MISSING" for issue in result.issues)
    assert not event.trades and not event.security_movements


def test_dividend_with_wkn_only_has_identity_and_no_missing_issue():
    text = _dividend(
        "per 01.02.2025 716460 SAP SE\n"
        "STK 1,000 Inhaber-Aktien"
    )
    plugin = ComdirectPlugin()
    document = _document(text)
    result = plugin.parse(document, plugin.detect(document)[0])
    event = result.events[0]
    assert event.security_wkn == "716460"
    assert str(event.security_isin) == "UNKNOWN"
    assert not any(issue.code == "COMDIRECT_SECURITY_MISSING" for issue in result.issues)


def test_dividend_with_isin_only_has_identity_and_no_missing_issue():
    text = _dividend(
        "per 01.02.2025 DE0007164600 SAP SE\n"
        "STK 1,000 Inhaber-Aktien"
    )
    plugin = ComdirectPlugin()
    document = _document(text)
    result = plugin.parse(document, plugin.detect(document)[0])
    event = result.events[0]
    assert event.security_isin == "DE0007164600"
    assert str(event.security_wkn) == "UNKNOWN"
    assert not any(issue.code == "COMDIRECT_SECURITY_MISSING" for issue in result.issues)


def test_ambiguous_identity_creates_warning_and_no_auto_assignment():
    text = _dividend(
        "per 01.02.2025 123456 First Fund 654321\n"
        "STK 1,000 DE0007164600 DE000A0H0744"
    )
    plugin = ComdirectPlugin()
    document = _document(text)
    result = plugin.parse(document, plugin.detect(document)[0])
    event = result.events[0]
    assert any(issue.code == "COMDIRECT_SECURITY_AMBIGUOUS" for issue in result.issues)
    assert str(event.security_isin) == "UNKNOWN"


def test_invalid_identity_creates_warning_and_no_auto_assignment():
    text = _dividend(
        "per 01.02.2025 123456 Generic Fund\n"
        "STK 1,000 DE000A1B2C34Accumulating Shares"
    )
    plugin = ComdirectPlugin()
    document = _document(text)
    result = plugin.parse(document, plugin.detect(document)[0])
    event = result.events[0]
    assert any(issue.code == "COMDIRECT_SECURITY_INVALID" for issue in result.issues)
    assert str(event.security_isin) == "UNKNOWN"


def test_dividend_identity_evidence_uses_the_real_source_page():
    page1 = "comdirect\nAbrechnung Dividendengutschrift\nDepotnummer: 12345"
    page2 = (
        "Depotbestand Wertpapier-Bezeichnung WKN/ISIN\n"
        "per 12.06.2026 A0H074iSh.DJ Asia Pa.S.D.50 U.ETF DE\n"
        "STK 26,122 DE000A0H0744Inhaber-Anteile\n"
        "zahlbar ab 15.06.2026\nZu Ihren Gunsten EUR 12,46"
    )
    plugin = ComdirectPlugin()
    document = _document(page1, page2)
    result = plugin.parse(document, plugin.detect(document)[0])
    event = result.events[0]
    evidence = {item.evidence_id: item for item in result.evidence}
    identity_evidence = [evidence[item] for item in event.security_identity_evidence_ids]
    assert {item.page_number for item in identity_evidence} == {2}
    assert any(item.field == "security_name" and "A0H074iSh.DJ" in item.excerpt for item in identity_evidence)


def test_investment_tax_notice_keeps_security_identity_and_evidence():
    page1 = (
        "comdirect\nSteuerliche Behandlung: Investment-Ausschüttung\n"
        "Depotnummer: 123456\nBruttoertrag EUR 5,00\n"
        "Kapitalertragsteuer EUR 1,00\nSteuerbemessungsgrundlage EUR 4,00"
    )
    page2 = (
        "Wertpapier-Bezeichnung WKN/ISIN\n"
        "iShares MSCI World A0H074\n"
        "Inhaber-Anteile DE000A0H0744\nSTK 16,471"
    )
    plugin = ComdirectPlugin()
    document = _document(page1, page2)
    result = plugin.parse(document, plugin.detect(document)[0])
    event = result.events[0]
    evidence = {item.evidence_id: item for item in result.evidence}
    identity_evidence = [evidence[item] for item in event.security_identity_evidence_ids]

    assert event.kind == "TAX_NOTICE"
    assert (event.security_name, event.security_wkn, event.security_isin) == (
        "iShares MSCI World Inhaber-Anteile",
        "A0H074",
        "DE000A0H0744",
    )
    assert event.tax_events[0].isin == "DE000A0H0744"
    assert {item.page_number for item in identity_evidence} == {2}
    assert {item.field for item in identity_evidence} == {"security_name", "security_wkn", "security_isin"}
    assert not event.cash_movements
    assert not event.security_movements


def test_tax_notice_does_not_restore_isin_rejected_as_ambiguous():
    page1 = "comdirect\nSteuerliche Behandlung: Inländische Dividende\nDepotnummer: 123456"
    page2 = (
        "Wertpapier-Bezeichnung WKN/ISIN\n"
        "per 01.02.2025 716460 SAP SE\n"
        "STK 1,000 DE0007164600 Inhaber-Aktien\n"
        "Weitere Position DE000A0H0744\n"
        "Kapitalertragsteuer EUR 1,00"
    )
    plugin = ComdirectPlugin()
    document = _document(page1, page2)
    result = plugin.parse(document, plugin.detect(document)[0])
    event = result.events[0]

    assert event.tax_events[0].isin is None
    assert str(event.security_isin) == "NOT_FOUND"
    assert "COMDIRECT_SECURITY_AMBIGUOUS" in {issue.code for issue in result.issues}
    evidence = {item.evidence_id: item for item in result.evidence}
    assert not any(evidence[item].field == "security_isin" for item in event.security_identity_evidence_ids)


def test_tax_notice_name_evidence_uses_page_text_when_layout_reorders_columns():
    page = (
        "comdirect\nSteuerliche Behandlung: Inländische Dividende\n"
        "Depotnummer: 123456\nWertpapier-Bezeichnung WKN/ISIN\n"
        "per 01.02.2025 716460 SAP SE\n"
        "STK 1,000 DE0007164600 Inhaber-Aktien"
    )
    layout = (
        "Wertpapier-Bezeichnung WKN/ISIN\n"
        "p er 01.02.2025 SAP SE 716460\n"
        "STK 1,000 DE0007164600 Inhaber-Aktien"
    )
    document = PdfDocument(
        "layout-identity-doc",
        "f" * 64,
        (PdfPage(1, page),),
        metadata={"text_preparation_json": json.dumps({"pages": [{"layout_text": layout}]})},
    )
    plugin = ComdirectPlugin()
    result = plugin.parse(document, plugin.detect(document)[0])
    event = result.events[0]
    evidence = {item.evidence_id: item for item in result.evidence}
    name_sources = [evidence[item] for item in event.security_identity_evidence_ids
                    if evidence[item].field == "security_name"]

    assert str(event.security_name) == "SAP SE Inhaber-Aktien"
    assert len(name_sources) == 1
    assert name_sources[0].excerpt in page
    assert "p er 01.02.2025" not in name_sources[0].excerpt


def test_conflicting_isin_elsewhere_in_document_is_ambiguous():
    text = _dividend(
        "per 01.02.2025 716460 SAP SE\n"
        "STK 1,000 DE0007164600 Inhaber-Aktien",
        extra="Weitere Position DE000A0H0744\n",
    )
    plugin = ComdirectPlugin()
    document = _document(text)
    result = plugin.parse(document, plugin.detect(document)[0])
    event = result.events[0]
    assert event.security_isin == "UNKNOWN"
    assert any(issue.code == "COMDIRECT_SECURITY_AMBIGUOUS" for issue in result.issues)


def test_existing_standard_fixture_is_unchanged():
    identity = _identity(
        "Wertpapier-Bezeichnung   WKN/ISIN\n"
        "per 01.02.2025  Example-ETF  A1B2C3\n"
        "STK 1,000  I n h a b e r - A n t e i l e o . N .  DE000A1B2C35"
    )
    assert (identity.name, identity.wkn, identity.isin) == (
        "Example-ETF Inhaber-Anteile o.N.",
        "A1B2C3",
        "DE000A1B2C35",
    )
    assert identity.status == "RECOGNIZED"
