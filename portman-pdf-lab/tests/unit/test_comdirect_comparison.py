from portman_parsers.api import PdfDocument, PdfPage
from portman_pdf_lab.application import compare_comdirect_parsers


def test_both_comdirect_variants_execute_and_differences_are_copyable_rows():
    text="""comdirect
Wertpapierkauf
Stk. 0,125 Beispiel ETF, WKN / ISIN: ABC123 / DE0008474511
Valuta 04.02.2026
Kurs EUR 1.000,00
Kurswert EUR 125,00
Provision EUR 1,50
Zu Ihren Lasten EUR 126,50"""
    source=PdfDocument("compare","c"*64,(PdfPage(1,text),))
    report=compare_comdirect_parsers(source)
    assert report["portman_detection"].handler_id == "wertpapierkauf"
    assert report["portfolio_performance_detection"].handler_id == "wertpapierkauf"
    assert report["agreement_is_not_reference"] is True
    rows={x["field"]:x for x in report["rows"]}
    assert rows["security.quantity"]["matches"] is True
    assert rows["runtime_ns"]["is_confirmed_reference"] is False
