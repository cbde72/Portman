"""Local PDF text extraction using pypdf; OCR deliberately remains optional."""

from hashlib import sha256
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from portman_parsers.api import PdfDocument, PdfPage
from portman_parsers.utilities import stable_id


class PdfExtractionError(RuntimeError):
    code = "PDF_EXTRACTION_ERROR"


class PasswordProtectedPdfError(PdfExtractionError):
    code = "PDF_PASSWORD_PROTECTED"


class DamagedPdfError(PdfExtractionError):
    code = "PDF_DAMAGED"


def extract_pdf(path: str | Path, password: str | None = None) -> PdfDocument:
    source = Path(path)
    content = source.read_bytes()
    digest = sha256(content).hexdigest()
    try:
        reader = PdfReader(source, strict=True)
        if reader.is_encrypted:
            if not password or not reader.decrypt(password):
                raise PasswordProtectedPdfError(f"PDF is password protected: {source.name}")
        pages = []
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            pages.append(PdfPage(number, text, f"{source.name}#page={number}",
                                 "text" if text.strip() else "ocr_required"))
    except PasswordProtectedPdfError:
        raise
    except (PdfReadError, OSError, ValueError) as exc:
        raise DamagedPdfError(f"Unreadable PDF {source.name}: {exc}") from exc
    return PdfDocument(stable_id("document", digest), digest, tuple(pages), source.name,
                       {"path": str(source.resolve()), "ocr_required": str(any(
                           page.extraction_method == "ocr_required" for page in pages)).lower()})

