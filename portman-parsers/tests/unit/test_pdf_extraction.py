from pathlib import Path

import pytest
from pypdf import PdfWriter

from portman_parsers.extraction import DamagedPdfError, PasswordProtectedPdfError, extract_pdf


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


def test_extracts_text_hash_and_page_reference(tmp_path):
    path = tmp_path / "statement.pdf"; path.write_bytes(simple_pdf("Bank of Scotland"))
    result = extract_pdf(path)
    assert "Bank of Scotland" in result.pages[0].text
    assert len(result.source_hash) == 64
    assert result.pages[0].source_ref == "statement.pdf#page=1"
    assert result.metadata["ocr_required"] == "false"


def test_pdf_without_text_layer_is_marked_for_ocr(tmp_path):
    path = tmp_path / "blank.pdf"; writer = PdfWriter(); writer.add_blank_page(100, 100)
    with path.open("wb") as handle: writer.write(handle)
    result = extract_pdf(path)
    assert result.pages[0].extraction_method == "ocr_required"


def test_damaged_pdf_is_controlled_error(tmp_path):
    path = tmp_path / "broken.pdf"; path.write_bytes(b"not a pdf")
    with pytest.raises(DamagedPdfError): extract_pdf(path)


def test_password_protected_pdf_is_controlled_error(tmp_path):
    path = tmp_path / "secret.pdf"; writer = PdfWriter(); writer.add_blank_page(100, 100); writer.encrypt("secret")
    with path.open("wb") as handle: writer.write(handle)
    with pytest.raises(PasswordProtectedPdfError): extract_pdf(path)
    assert extract_pdf(path, "secret").pages
