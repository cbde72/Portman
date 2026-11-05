"""Local PDF text extraction using pypdf; OCR deliberately remains optional."""

from hashlib import sha256
import json
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from portman_parsers.api import PdfDocument, PdfPage
from portman_parsers.utilities import stable_id
from .preparation import PREPARATION_VERSION, prepare_pdf


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
        raw_pages = []
        for number, page in enumerate(reader.pages, 1):
            raw_pages.append(page.extract_text() or "")
        # Baader-Wertpapierbelege drucken Pflichtwerte in festen Tabellenspalten.
        # Der normale Textmodus zerlegt diese Spalten in eine falsche Lesereihenfolge.
        baader_layout = any("Baader Bank" in page and "Depot-Nr.:" in page for page in raw_pages)
        if baader_layout:
            raw_pages = [page.extract_text(extraction_mode="layout") or raw
                         for page, raw in zip(reader.pages, raw_pages)]
        prepared = prepare_pdf(source, raw_pages, digest, source)
        pages = []
        for page in prepared.pages:
            extraction_method = (f"{page.extractor_id}:{page.quality.lower()}"
                                 if page.normalized_text.strip() else "ocr_required")
            selected_text = ((page.layout_text or page.normalized_text) if baader_layout and page.fallback_used
                             else raw_pages[page.page_number - 1] if baader_layout else page.normalized_text)
            pages.append(PdfPage(page.page_number, selected_text,
                                 f"{source.name}#page={page.page_number}", extraction_method,
                                 1.0 if page.quality == "OK" else 0.65 if page.quality == "SUSPICIOUS" else 0.25))
    except PasswordProtectedPdfError:
        raise
    except (PdfReadError, OSError, ValueError) as exc:
        raise DamagedPdfError(f"Unreadable PDF {source.name}: {exc}") from exc
    return PdfDocument(stable_id("document", digest), digest, tuple(pages), source.name,
                       {"path": str(source.resolve()),
                        "ocr_required": str(any(page.extraction_method == "ocr_required" for page in pages)).lower(),
                        "text_preparation_version": PREPARATION_VERSION,
                        "text_extractors": ",".join(dict.fromkeys(page.extraction_method.split(":", 1)[0]
                                                            for page in pages)),
                        "text_quality": (
                            "unreliable" if any(page.extraction_method.endswith(":unreliable") for page in pages)
                            else "suspicious" if any(page.extraction_method.endswith(":suspicious") for page in pages)
                            else "ok" if pages and all(":ok" in page.extraction_method for page in pages)
                            else "no_text"),
                        "text_quality_pages": ",".join(
                            f"{page.number}:{page.extraction_method.split(':')[-1]}" for page in pages),
                        "text_preparation_json": json.dumps(prepared.to_dict(), ensure_ascii=False)})
