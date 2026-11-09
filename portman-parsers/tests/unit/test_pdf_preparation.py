from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
from pathlib import Path
import sys
import threading
import time
import types

import pytest

from portman_parsers.extraction import PREPARATION_VERSION, extract_pdf, prepare_pdf
from portman_parsers.extraction.preparation import _normalize


def simple_pdf(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 11 Tf 40 750 Td ({escaped}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    data = bytearray(b"%PDF-1.4\n"); offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data)); data.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data); data.extend(f"xref\n0 {len(objects)+1}\n".encode()); data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]: data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def test_normalization_is_unicode_safe_and_preserves_business_numbers():
    text, diagnostics = _normalize("Wert 0,733 EUR 2,20 Betrag 1,61 ISIN DE0007164600")
    assert text == "Wert 0,733 EUR 2,20 Betrag 1,61 ISIN DE0007164600"
    assert "REPEATED_TOKEN_REMOVED_WITH_CONTEXT" not in diagnostics


def test_repeated_glyph_token_is_removed_but_identifiers_are_not():
    text, diagnostics = _normalize(
        "SP010000 SP010000 SAP DE0007164600 DE0007164600 WKN 716460 U U U")
    assert "SP010000" not in text
    assert "DE0007164600" in text
    assert "REPEATED_TOKEN_REMOVED_WITH_CONTEXT" in diagnostics
    assert "U U U" in text


def test_long_at_glyph_run_is_removed_without_global_at_replacement():
    text, diagnostics = _normalize("Hinweis @@@@ @@@@@@@@@@@@@@@@@@@ Wert @x")
    assert "@@@@@@@@@@@@@@@@@@@" not in text
    assert "@@@@" in text
    assert "@x" in text
    assert "REPEATED_AT_GLYPH_RUN_REMOVED_WITH_CONTEXT" in diagnostics


def test_prepare_pdf_keeps_original_and_page_blocks():
    prepared = prepare_pdf(
        "fixture.pdf", ["Zeile 1\r\n0,733 EUR\r\n"], "a" * 64)
    page = prepared.pages[0]
    assert page.original_text == "Zeile 1\r\n0,733 EUR\r\n"
    assert page.normalized_text == "Zeile 1\n0,733 EUR\n"
    assert page.extractor_id == "pypdf"
    assert page.blocks and page.blocks[0].text == "Zeile 1"
    assert prepared.preparation_version == PREPARATION_VERSION


def test_extract_pdf_documents_preparation_version(tmp_path):
    path = tmp_path / "normal.pdf"
    path.write_bytes(simple_pdf("SAP DE0007164600 0,733 EUR 2,20"))
    document = extract_pdf(path)
    assert document.metadata["text_preparation_version"] == PREPARATION_VERSION
    assert document.metadata["text_extractors"] == "pypdf"
    assert document.metadata["text_quality"] == "ok"


def test_isolated_long_u_glyph_line_removed_without_altering_valid_values():
    text, diagnostics = _normalize(
        "SAP SE\nUUUUUUUUUUUUUUUUUUUUUUUUUUUUUU\n0,733 STK\nU.S. Treasury\nU U U")
    assert "UUUUUUUUUUUUUUUU" not in text
    assert "SAP SE" in text and "0,733 STK" in text
    assert "U.S. Treasury" in text and "U U U" in text
    assert "ISOLATED_REPEATED_U_GLYPH_LINE_REMOVED" in diagnostics


def test_embedded_u_letters_are_not_removed():
    value = "KUNDENNUMMER UUUUUUUUUUUUUUUUU 716460"
    text, diagnostics = _normalize(value)
    assert text == value
    assert "ISOLATED_REPEATED_U_GLYPH_LINE_REMOVED" not in diagnostics


def test_baader_uses_selected_pdfium_page_for_layout_and_evidence(monkeypatch, tmp_path):
    from portman_parsers.extraction import pdf as extraction
    from portman_parsers.extraction import preparation
    from portman_parsers.plugins import BaaderPlugin

    header = "Baader Bank AG\nDepot-Nr.: 1234567890\nQuartalsaufstellung\nMIFID II per 30.06.2026\n"
    corrected = "Stück 10 WKN: BASF11 EUR 50,000 500,00 EUR\nISIN: DE000BASF111\nBASF SE\nDepotwert 500,00 EUR\n"
    damaged = corrected.replace("DE000BASF111", "DE000BASF1\ufffd1")

    class Page:
        def __init__(self, value):
            self.value = value

        def extract_text(self, **_kwargs):
            return self.value

    class Reader:
        is_encrypted = False
        pages = (Page(header), Page(damaged))

    path = tmp_path / "baader-fallback.pdf"
    path.write_bytes(b"synthetic PDF bytes")
    monkeypatch.setattr(extraction, "PdfReader", lambda *_args, **_kwargs: Reader())
    monkeypatch.setattr(preparation, "_pdfium_page", lambda _path, page: (corrected, (), "test-pdfium") if page == 2 else None)

    document = extract_pdf(path)
    assert document.pages[0].extraction_method == "pypdf:ok"
    assert document.pages[1].extraction_method == "pdfium:ok"
    assert "DE000BASF111" in document.pages[1].text
    assert "\ufffd" not in document.pages[1].text
    selected = json.loads(document.metadata["text_preparation_json"])["pages"][1]
    assert selected["extractor_id"] == "pdfium"
    assert selected["layout_text"] == document.pages[1].text
    plugin = BaaderPlugin()
    result = plugin.parse(document, plugin.detect(document)[0])
    assert result.depot_snapshots[0].positions[0].security_id.value == "DE000BASF111"
    assert all(item.excerpt in document.pages[item.page_number - 1].text for item in result.evidence)
    assert any(item.page_number == 2 and item.field == "depot_position" for item in result.evidence)


def test_embedded_u_font_artifacts_trigger_pdfium_fallback(monkeypatch, tmp_path):
    from portman_parsers.extraction import preparation
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"test")
    original = "HerrnUUUUUUUUUUUUUUUUUUU\nChristophUBuehringUUUUUUUUUUUUUU\nDividendengutschrift"
    fallback = "Herrn\nChristoph Buehring\nDividendengutschrift\nEUR 1,61"
    monkeypatch.setattr(preparation, "_pdfium_page",
                        lambda path, page: (fallback, (), "test-pdfium"))
    prepared = preparation.prepare_pdf(pdf, [original], "a" * 64)
    page = prepared.pages[0]
    assert page.fallback_used
    assert page.extractor_id == "pdfium"
    assert "Christoph Buehring" in page.normalized_text
    assert "UUUUUUUU" not in page.normalized_text
    assert page.original_text == original


def test_comdirect_ertragsgutschrift_mit_s_glyphen_nutzt_kuerzeren_pdfium_text(monkeypatch, tmp_path):
    from portman_parsers.extraction import preparation
    from portman_parsers.registry import default_registry

    damaged = "\n".join(("comdirect", "Abrechnung Ertragsgutschrift", *("S" * 120 for _ in range(4))))
    corrected = """@@@@@@@@@@@@@@@@
comdirect
Abrechnung Ertragsgutschrift
Depotbestand Wertpapier-Bezeichnung WKN/ISIN
per 12.10.2023 716460 SAP SE
STK 5,000 DE0007164600 Inhaber-Aktien o.N.
zahlbar ab 15.10.2023
Verrechnung über Konto (IBAN) Valuta Zu Ihren Gunsten vor Steuern
DE00 0000 0000 0000 0000 01 EUR 18.10.2023 EUR 10,50
(Referenz-Nr. ABCD01234567).
"""
    path = tmp_path / "ertragsgutschrift.pdf"
    path.write_bytes(simple_pdf(damaged))
    monkeypatch.setattr(preparation, "_pdfium_page", lambda _path, _page: (corrected, (), "test-pdfium"))

    document = extract_pdf(path)
    assert document.pages[0].extraction_method == "pdfium:suspicious"
    assert "REPEATED_S_GLYPH_RUN" in document.metadata["text_preparation_json"]
    registry = default_registry()
    result = registry.parse(document, registry.select(document))
    event, = result.events
    assert (event.security_wkn, event.security_isin, event.security_name) == (
        "716460", "DE0007164600", "SAP SE Inhaber-Aktien o.N.",
    )
    assert event.bank_reference == "ABCD01234567"
    assert event.cash_movements[0].amount == Decimal("10.50")
    assert not result.issues
    assert all(item.page_number == 1 for item in result.evidence)


class _ConcurrencyTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def call(self):
        tracker = self

        class _Call:
            def __enter__(self):
                with tracker._lock:
                    tracker.active += 1
                    tracker.max_active = max(tracker.max_active, tracker.active)
                time.sleep(0.005)

            def __exit__(self, *_exc):
                with tracker._lock:
                    tracker.active -= 1
                return False

        return _Call()


def test_pdfium_calls_are_serialized_across_threads(monkeypatch):
    """PDFium is not thread-safe; concurrent fallbacks must never overlap."""
    from portman_parsers.extraction import preparation

    tracker = _ConcurrencyTracker()

    class FakeTextPage:
        def get_text_range(self):
            with tracker.call():
                return "Wert 1,00"

        def get_charbox(self, _index):
            return (0.0, 0.0, 1.0, 1.0)

        def close(self):
            pass

    class FakePage:
        def get_textpage(self):
            return FakeTextPage()

        def close(self):
            pass

    class FakeDocument:
        def __init__(self, _path):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def __getitem__(self, _index):
            return FakePage()

    fake_pdfium = types.ModuleType("pypdfium2")
    fake_pdfium.PdfDocument = FakeDocument
    fake_pdfium.__version__ = "fake"
    monkeypatch.setitem(sys.modules, "pypdfium2", fake_pdfium)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(
            lambda _index: preparation._pdfium_page(Path("fallback.pdf"), 1),
            range(24),
        ))

    assert all(result is not None for result in results)
    assert tracker.max_active == 1, "PDFium work must not run in parallel"


def test_concurrent_extraction_of_pdfium_fallback_pdfs_is_safe(tmp_path):
    """Regression for Windows heap corruption (0xc0000374) in parallel PDFium."""
    pytest.importorskip("pypdfium2")
    path = tmp_path / "fallback.pdf"
    path.write_bytes(simple_pdf("SP010000 SP010000\nSAP DE0007164600\nWert 1,00 EUR"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        documents = list(pool.map(lambda _index: extract_pdf(path), range(24)))

    assert all(document.pages for document in documents)
    assert all("pdfium" in document.metadata["text_extractors"] for document in documents)
