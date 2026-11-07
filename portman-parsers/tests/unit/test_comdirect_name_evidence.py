"""Regression: Namens-Evidence muss Originaltext der richtigen PDF-Seite sein.

Ursache des Fehlers ``evidence excerpt does not occur in any PDF page``: Der
Wertpapiername wird aus dem Layouttext gelesen (Zeichenabstände, andere
Spaltenfolge); dieser Ausschnitt kommt im Seitentext nicht vor.
"""
import json

from portman_parsers.api import MissingValue, PdfDocument, PdfPage
from portman_parsers.plugins.comdirect import ComdirectPlugin

HEAD = "Gutschrift fälliger Wertpapier-Erträge\n{title}\nDepotbestand Wertpapier-Bezeichnung WKN/ISIN\n"
TAIL = chr(10).join(("comdirect bank", "Abrechnung Ertragsgutschrift", "Emissionsland: DEUTSCHLAND", "Bruttobetrag: EUR 4,81",
                  "DE71 2004 1133 0476 4924 40 EUR 15.06.2016 EUR 4,81", ""))


def _doc(pages, layout=None, title="Ertragsgutschrift"):
    meta = {}
    if layout is not None:
        meta["text_preparation_json"] = json.dumps({"pages": [{"layout_text": layout}]})
    return PdfDocument("doc-name", "a" * 64, tuple(PdfPage(n, t) for n, t in pages.items()), metadata=meta)


def _parse(doc):
    plugin = ComdirectPlugin()
    return plugin.parse(doc, plugin.detect(doc)[0])


def _assert_evidence_on_own_page(doc, result):
    pages = {p.number: p.text for p in doc.pages}
    assert result.evidence
    for item in result.evidence:
        assert item.excerpt in pages[item.page_number], (item.field_name if hasattr(item, "field_name") else item, item.page_number)


def _name_evidence(result):
    return [e for e in result.evidence if "name" in str(getattr(e, "field_name", getattr(e, "field", "")))]


def test_etf_spaced_layout_name_uses_original_page_text():
    page = HEAD.format(title="Ertragsgutschrift") + "per 14.06.2016 A0H074 iSh.DJ Asia Pa.S.D.30 U.ETF DE\nSTK 11,333 DE000A0H0744 Inhaber-Anteile\n" + TAIL
    layout = HEAD.format(title="Ertragsgutschrift") + "p er 14.06.2016 iSh.DJ Asia Pa.S.D.30 U.ETF DE A0H074\nS TK 11,333 Inhaber-Anteile DE000A0H0744\n" + TAIL
    doc = _doc({1: page}, layout)
    result = _parse(doc)
    event = result.events[0]
    assert event.security_wkn == "A0H074" and event.security_isin == "DE000A0H0744"
    assert "Asia Pa.S.D.30" in str(event.security_name)
    _assert_evidence_on_own_page(doc, result)


def test_dividend_with_different_layout_order_does_not_abort():
    page = HEAD.format(title="Dividendengutschrift") + "per 01.03.2019 723610 Musterwerk AG\nSTK 10 DE0007236101 Inhaber-Aktien\n" + TAIL
    layout = HEAD.format(title="Dividendengutschrift") + "p er 01.03.2019 Musterwerk AG 723610\nS TK 10 Inhaber-Aktien DE0007236101\n" + TAIL
    doc = _doc({1: page}, layout, "Dividendengutschrift")
    result = _parse(doc)
    assert result.events[0].security_wkn == "723610"
    _assert_evidence_on_own_page(doc, result)


def test_name_with_line_break_is_located_with_original_span():
    page = HEAD.format(title="Ertragsgutschrift") + "per 14.06.2016 A0H074 iSh.DJ Asia\nPa.S.D.30 U.ETF DE\nSTK 11,333 DE000A0H0744 Inhaber-Anteile\n" + TAIL
    layout = HEAD.format(title="Ertragsgutschrift") + "p er 14.06.2016 iSh.DJ Asia Pa.S.D.30 U.ETF DE A0H074\nS TK 11,333 Inhaber-Anteile DE000A0H0744\n" + TAIL
    doc = _doc({1: page}, layout)
    result = _parse(doc)
    _assert_evidence_on_own_page(doc, result)


def test_unlocatable_name_yields_issue_and_empty_field_not_substitute():
    page = HEAD.format(title="Ertragsgutschrift") + "per 14.06.2016 A0H074\nSTK 11,333 DE000A0H0744\n" + TAIL
    layout = HEAD.format(title="Ertragsgutschrift") + "p er 14.06.2016 Voellig Anderer Name A0H074\nS TK 11,333 DE000A0H0744\n" + TAIL
    doc = _doc({1: page}, layout)
    result = _parse(doc)
    event = result.events[0]
    assert event.security_name is MissingValue.UNKNOWN  # kein Ersatzname
    assert "COMDIRECT_SECURITY_NAME_UNVERIFIED" in {issue.code for issue in result.issues}
    assert event.security_wkn == "A0H074"
    _assert_evidence_on_own_page(doc, result)


def test_multipage_name_evidence_points_to_the_page_that_contains_it():
    page1 = "Seite eins ohne Wertpapier\nDepotnr.: 476492400\n"
    page2 = HEAD.format(title="Ertragsgutschrift") + "per 14.06.2016 A0H074 iSh.DJ Asia Pa.S.D.30 U.ETF DE\nSTK 11,333 DE000A0H0744 Inhaber-Anteile\n" + TAIL
    layout = HEAD.format(title="Ertragsgutschrift") + "p er 14.06.2016 iSh.DJ Asia Pa.S.D.30 U.ETF DE A0H074\nS TK 11,333 Inhaber-Anteile DE000A0H0744\n" + TAIL
    doc = _doc({1: page1, 2: page2}, layout)
    result = _parse(doc)
    _assert_evidence_on_own_page(doc, result)
    for item in result.evidence:
        if "Asia Pa" in item.excerpt:
            assert item.page_number == 2
