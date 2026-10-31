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
