"""Quality-aware, evidence-preserving PDF text preparation.

The parser contract still receives plain :class:`PdfPage` text.  This module
keeps the preparation metadata beside that contract so bank parsers do not
need to know which extractor was selected.  Optional PDFium support is loaded
only when a page is considered suspicious; importing the DTO package never
loads a PDF library.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import threading
import unicodedata
from pathlib import Path
from typing import Any, Iterable


PREPARATION_VERSION = "7.3.0"
# PDFium is a native library without thread synchronisation.  Parallel PDF Lab
# workers that hit the PDFium fallback used to corrupt the process heap
# (Windows 0xc0000374) while opening documents and reading text pages.  All
# PDFium calls in this module are therefore serialised with one process-wide
# lock; object creation *and* destruction stay inside the critical section.
_PDFIUM_LOCK = threading.RLock()
_REPLACEMENT = "\ufffd"
_ARTIFACT_TOKEN = re.compile(r"\b[A-Z]{1,4}\d{4,10}\b")
_AT_RUN = re.compile(r"@{8,}")
_U_RUN_LINE = re.compile(r"(?m)^[ \\t]*U{16,}[ \\t]*$")
_NUMBER = re.compile(r"[-+]?\d+(?:[,.]\d+)?")


def _safe_artifact_token(token: str) -> bool:
    """Recognise a glyph token, not an arbitrary identifier.

    Ordinary identifiers such as ISINs and WKNs may legitimately repeat on a
    page.  Removal is therefore restricted to repeated short prefixes with a
    long zero run, the characteristic shape of the broken font token, while
    the broader diagnostic still reports other suspicious repetitions.
    """
    return bool(re.fullmatch(r"[A-Z]{1,4}\d{0,3}0{3,}\d{0,4}", token))


@dataclass(frozen=True, slots=True)
class TextSpan:
    start: int
    end: int
    text: str
    quad: tuple[tuple[float, float], ...] = ()
    mapping: str = "EXACT"


@dataclass(frozen=True, slots=True)
class TextBlock:
    start: int
    end: int
    text: str
    spans: tuple[TextSpan, ...] = ()
    quality: str = "OK"
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PagePreparation:
    page_number: int
    original_text: str
    normalized_text: str
    extractor_id: str
    extractor_version: str
    quality: str
    diagnostics: tuple[str, ...] = ()
    blocks: tuple[TextBlock, ...] = ()
    mapping: str = "NONE"
    fallback_used: bool = False
    layout_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PreparedPdf:
    source_hash: str
    pages: tuple[PagePreparation, ...]
    preparation_version: str = PREPARATION_VERSION
    diagnostics: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        return "\n".join(page.normalized_text for page in self.pages)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_hash": self.source_hash,
            "preparation_version": self.preparation_version,
            "diagnostics": list(self.diagnostics),
            "pages": [page.to_dict() for page in self.pages],
        }


def _version(module: Any, fallback: str = "unknown") -> str:
    return str(getattr(module, "__version__", fallback))


def _diagnose(text: str) -> tuple[str, ...]:
    diagnostics: list[str] = []
    if _REPLACEMENT in text:
        diagnostics.append("UNICODE_REPLACEMENT_CHARACTER")
    if "SP010000" in text:
        diagnostics.append("REPEATED_SUSPICIOUS_TOKEN_SP010000")
    if _AT_RUN.search(text):
        diagnostics.append("REPEATED_AT_GLYPH_RUN")
    if _U_RUN_LINE.search(text):
        diagnostics.append("ISOLATED_REPEATED_U_GLYPH_LINE")
    if re.search(r"U{12,}", text):
        diagnostics.append("REPEATED_U_GLYPH_RUN")
    artifact_tokens = _ARTIFACT_TOKEN.findall(text)
    repeated = {token for token in artifact_tokens if artifact_tokens.count(token) >= 2}
    if repeated:
        diagnostics.append("REPEATED_ALPHANUMERIC_GLYPH_TOKEN")
    unusual = sum(1 for char in text if not char.isprintable() and char not in "\n\r\t")
    if unusual:
        diagnostics.append("UNPRINTABLE_CHARACTER_DENSITY")
    if text and (len(text) > 2000 and len(set(text)) < 12):
        diagnostics.append("LOW_CHARACTER_VARIETY")
    if text and len(_NUMBER.findall(text)) == 0:
        diagnostics.append("NO_NUMERIC_TOKENS")
    return tuple(dict.fromkeys(diagnostics))


def _quality(text: str, diagnostics: Iterable[str]) -> str:
    diagnostics = tuple(diagnostics)
    if not text.strip():
        return "NO_TEXT"
    severe = {"UNICODE_REPLACEMENT_CHARACTER", "LOW_CHARACTER_VARIETY"}
    if severe.intersection(diagnostics):
        return "UNRELIABLE"
    if "REPEATED_U_GLYPH_RUN" in diagnostics:
        return "UNRELIABLE"
    if diagnostics:
        return "SUSPICIOUS"
    return "OK"


def _quality_rank(value: str) -> int:
    return {"NO_TEXT": 0, "UNRELIABLE": 1, "SUSPICIOUS": 2, "OK": 3}.get(value, 0)


def _normalize(text: str) -> tuple[str, tuple[str, ...]]:
    """Apply only transformations that cannot alter business values."""
    original = str(text or "")
    normalized = unicodedata.normalize("NFKC", original)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\u00a0", " ").replace("\u2007", " ").replace("\u202f", " ")
    diagnostics = list(_diagnose(normalized))

    # A token is removed only when it is demonstrably repeated.  Other
    # unusual letters remain untouched; this prevents accidental corruption of
    # ISINs, WKNs, currencies, signs and decimal values.
    tokens = _ARTIFACT_TOKEN.findall(normalized)
    repeated = {token for token in tokens if tokens.count(token) >= 2 and _safe_artifact_token(token)}
    if repeated:
        for token in repeated:
            normalized = re.sub(rf"(?<!\w){re.escape(token)}(?!\w)", " ", normalized)
        diagnostics.append("REPEATED_TOKEN_REMOVED_WITH_CONTEXT")
    if _AT_RUN.search(normalized):
        normalized = _AT_RUN.sub(" ", normalized)
        diagnostics.append("REPEATED_AT_GLYPH_RUN_REMOVED_WITH_CONTEXT")
    if _U_RUN_LINE.search(normalized):
        normalized = _U_RUN_LINE.sub("", normalized)
        diagnostics.append("ISOLATED_REPEATED_U_GLYPH_LINE_REMOVED")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r" *\n *", "\n", normalized)
    return normalized, tuple(dict.fromkeys(diagnostics))


def _blocks(text: str, diagnostics: tuple[str, ...]) -> tuple[TextBlock, ...]:
    result: list[TextBlock] = []
    for match in re.finditer(r"[^\n]+", text):
        result.append(TextBlock(match.start(), match.end(), match.group(0), quality=_quality(match.group(0), diagnostics), diagnostics=diagnostics))
    return tuple(result)


def _layout_from_spans(blocks: tuple[TextBlock, ...]) -> str:
    """Reconstruct simple rows/columns from PDFium character boxes."""
    chars = [span for block in blocks for span in block.spans if span.quad and span.text not in "\r\n"]
    if not chars:
        return ""
    rows: list[list[TextSpan]] = []
    for span in sorted(chars, key=lambda item: -sum(point[1] for point in item.quad) / 4):
        y = sum(point[1] for point in span.quad) / 4
        row = next((candidate for candidate in rows
                    if abs(y - sum(point[1] for item in candidate for point in item.quad) / (4 * len(candidate))) <= 3), None)
        if row is None:
            rows.append([span])
        else:
            row.append(span)
    lines: list[str] = []
    for row in rows:
        row.sort(key=lambda item: sum(point[0] for point in item.quad) / 4)
        line = ""
        previous_right = None
        for span in row:
            left = min(point[0] for point in span.quad)
            if previous_right is not None and left - previous_right > 8:
                line += " "
            line += span.text
            previous_right = max(point[0] for point in span.quad)
        lines.append(line.rstrip())
    return "\n".join(lines)


def _pdfium_page(path: Path, page_number: int) -> tuple[str, tuple[TextBlock, ...], str] | None:
    """Best-effort PDFium text and character geometry, never a hard dependency.

    PDFium is not thread-safe.  The whole document/page/text-page lifetime is
    protected by :data:`_PDFIUM_LOCK`, including explicit closing, so native
    heap corruption cannot leak into another worker thread.
    """
    try:
        import pypdfium2 as pdfium  # optional extra: portman-parsers[pdfium]
        with _PDFIUM_LOCK:
            with pdfium.PdfDocument(str(path)) as document:
                page = document[page_number - 1]
                try:
                    textpage = page.get_textpage()
                    try:
                        text = textpage.get_text_range()
                        spans: list[TextSpan] = []
                        for index, char in enumerate(text):
                            try:
                                left, bottom, right, top = textpage.get_charbox(index)
                                quad = ((float(left), float(bottom)), (float(right), float(bottom)),
                                        (float(right), float(top)), (float(left), float(top)))
                            except (AttributeError, IndexError, TypeError, ValueError):
                                quad = ()
                            spans.append(TextSpan(index, index + 1, char, quad, "EXACT" if quad else "UNMAPPED"))
                    finally:
                        textpage.close()
                finally:
                    page.close()
            blocks = (TextBlock(0, len(text), text, tuple(spans), "OK", ()),)
        return text, blocks, _version(pdfium)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError, IndexError):
        return None


def prepare_pdf(path: str | Path, pages: Iterable[str], source_hash: str,
                source_path: str | Path | None = None) -> PreparedPdf:
    """Prepare already extracted pages and selectively use PDFium as fallback."""
    source = Path(source_path or path)
    prepared: list[PagePreparation] = []
    diagnostics: list[str] = []
    for number, original in enumerate(pages, 1):
        original = str(original or "")
        normalized, page_diagnostics = _normalize(original)
        quality = _quality(normalized, page_diagnostics)
        extractor_id, extractor_version, fallback, mapping = "pypdf", "unknown", False, "NONE"
        blocks = _blocks(normalized, page_diagnostics)
        if quality in {"UNRELIABLE", "SUSPICIOUS"} and source.exists():
            alternative = _pdfium_page(source, number)
            if alternative is not None:
                fallback_text, fallback_blocks, version = alternative
                fallback_normalized, fallback_diagnostics = _normalize(fallback_text)
                fallback_quality = _quality(fallback_normalized, fallback_diagnostics)
                use_fallback = (
                    bool(fallback_normalized.strip()) and
                    fallback_quality != "UNRELIABLE" and
                    (_quality_rank(fallback_quality) > _quality_rank(quality) or
                     (fallback_quality == quality and
                      len(fallback_normalized.strip()) >= max(1, int(len(normalized.strip()) * 0.85))))
                )
                if use_fallback:
                    normalized, blocks = fallback_normalized, fallback_blocks
                    page_diagnostics = tuple(dict.fromkeys((*page_diagnostics, "FALLBACK_SELECTED")))
                    quality = fallback_quality
                    extractor_id, extractor_version, fallback, mapping = "pdfium", version, True, "EXACT"
                    diagnostics.append(f"PAGE_{number}_FALLBACK_PDFIUM")
                else:
                    diagnostics.append(f"PAGE_{number}_FALLBACK_NOT_BETTER")
        layout_raw = _layout_from_spans(blocks) or "\n".join(block.text for block in blocks)
        layout_text = _normalize(layout_raw)[0] if layout_raw else normalized
        prepared.append(PagePreparation(number, original, normalized, extractor_id,
                                         extractor_version, quality, page_diagnostics,
                                         blocks, mapping, fallback, layout_text))
    return PreparedPdf(source_hash, tuple(prepared), diagnostics=tuple(diagnostics))
