"""Lokale ETF-Factsheets finden, laden und Top-Positionen extrahieren."""
from html import unescape
from functools import lru_cache
from pathlib import Path
import logging
import re
import tempfile
import urllib.parse
import urllib.request


logger = logging.getLogger(__name__)


TRUSTED_HOST_PARTS = (
    "amundi", "blackrock", "ishares", "invesco", "ssga", "state-street",
    "xtrackers", "dws.com", "ubs.com", "vanguard",
)
SECTION_STARTS = (
    r"Top\s*-?\s*10\s*-?\s*Positionen",
    r"T\s*op\s*-?\s*10\s*-?\s*Positionen",
    r"Top\s+Positionen",
    r"Top\s+10\s+(?:index constituents|benchmark holdings)",
    r"10\s+gr[oö]sste\s+Aktienpositionen",
    r"gr[oö]ßten\s+Index-Positionen",
    r"10\s+größten\s+ETF-Bestandteile",
)
SECTION_ENDS = (
    "Portfolio insgesamt", "Die Fonds-Positionen", "AUFGLIEDERUNG", "Sektorengewichtung",
    "Geografische Aufteilung", "Aufteilung nach Ländern", "Index composition", "Quelle:",
    "Total ", "Summe ", "Vorteile", "Über uns",
)


def factsheet_path(folder, isin):
    folder = Path(folder)
    matches = sorted(folder.glob(f"{isin}*.pdf"))
    return matches[0] if matches else None


@lru_cache(maxsize=128)
def _extract_text_cached(path, modified_ns, size):
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages).replace("ﬀ", "ff")


def extract_text(path):
    path = Path(path)
    stat = path.stat()
    return _extract_text_cached(str(path.resolve()), stat.st_mtime_ns, stat.st_size)


def _section(text):
    start = None
    for pattern in SECTION_STARTS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match and (start is None or match.start() < start):
            start = match.end()
    if start is None:
        return ""
    end = min((position for marker in SECTION_ENDS
               if (position := text.find(marker, start)) >= 0), default=min(len(text), start + 2500))
    return text[start:end]


def parse_holdings_text(text, source="Factsheet"):
    section = _section(text)
    if not section:
        return []
    section = re.sub(r"\s+", " ", section).strip()
    section = re.sub(r"^(?:\([^)]*\)|%[^A-Z]*)?(?:Name|Company|Wertpapier)?\s*"
                     r"(?:ISIN\s*)?(?:Gewicht(?:ung)?|Weighting|%[^A-Z]*)?\s*", "", section,
                     flags=re.IGNORECASE)
    pattern = re.compile(
        r"(?P<name>[A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ0-9&.,'’()/+\- ]{1,100}?)\s+"
        r"(?:(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)\s+)?"
        r"(?P<weight>\d{1,2}[.,]\d{1,2})\s*%?",
        re.IGNORECASE,
    )
    results = []
    for match in pattern.finditer(section):
        name = re.sub(r"\s+", " ", match.group("name")).strip(" -–:;%")
        prefixes = (r"^\([^)]*\)\s*", r"^Name Gewicht\s*", r"^Table_Captions_Title\s+Fonds\s*",
                    r"^Title Fonds\s*", r"^vom Aktiva\s*\(Index\)\s*", r"^Referenzindex\s*",
                    r"^%?\s*of assets(?:\s*\(Index\))?\s*", r"^%?\s*assets\s*", r"^Index\s*", r"^Fonds\s*")
        changed = True
        while changed:
            old = name
            for prefix in prefixes:
                name = re.sub(prefix, "", name, flags=re.IGNORECASE)
            changed = name != old
        weight = float(match.group("weight").replace(",", "."))
        if not name or not 0 < weight <= 100:
            continue
        results.append({"name": name, "isin": match.group("isin") or "",
                        "weight_pct": weight, "source": source})
        if len(results) == 10:
            break
    return results


def parse_factsheet(path, isin=""):
    path = Path(path)
    from pypdf.errors import PyPdfError
    try:
        text = extract_text(path)
        if isin and isin not in text.replace(" ", ""):
            return []
        return parse_holdings_text(text, f"Factsheet · {path.name}")
    except (OSError, ValueError, PyPdfError) as exc:
        logger.warning('Factsheet %s konnte nicht gelesen werden: %s', path.name, exc)
        return []
    except Exception:
        logger.exception('Unerwarteter Fehler beim Factsheet-Parsing: %s', path.name)
        return []


def _search_urls(isin, name=""):
    query = urllib.parse.quote_plus(f'"{isin}" ETF factsheet filetype:pdf {name[:60]}')
    request = urllib.request.Request(
        f"https://html.duckduckgo.com/html/?q={query}",
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        html = response.read().decode("utf-8", "ignore")
    urls = []
    for raw in re.findall(r'href="([^"]+)"', html, re.IGNORECASE):
        url = unescape(raw)
        parsed = urllib.parse.urlparse(url)
        if "duckduckgo.com" in parsed.netloc:
            url = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
        host = urllib.parse.urlparse(url).netloc.lower()
        is_pdf_link = ".pdf" in url.lower() or "/pdfdocuments/" in url.lower()
        if url.startswith("https://") and is_pdf_link and any(part in host for part in TRUSTED_HOST_PARTS):
            if url not in urls: urls.append(url)
    return urls[:8]


def download_factsheet(isin, name, folder):
    """Sucht nur auf bekannten Anbieter-Domains und speichert ein validiertes PDF."""
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{isin}_Factsheet.pdf"
    errors = []
    direct_urls = []
    if "amundi" in name.lower():
        direct_urls = [
            f"https://www.amundietf.de/pdfDocuments/monthly-factsheet/{isin}/DEU/DEU/RETAIL/ETF",
            f"https://www.amundietf.ch/pdfDocuments/monthly-factsheet/{isin}/ENG/CHE/INSTITUTIONNEL/ETF",
        ]
    try:
        urls = direct_urls + [url for url in _search_urls(isin, name) if url not in direct_urls]
    except Exception as exc:
        return None, f"Factsheet-Suche fehlgeschlagen: {exc}"
    for url in urls:
        try:
            request = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "application/pdf,*/*",
            })
            with urllib.request.urlopen(request, timeout=20) as response:
                data = response.read(15_000_001)
            if len(data) > 15_000_000 or not data.startswith(b"%PDF"):
                raise ValueError("Antwort ist kein gültiges PDF")
            with tempfile.NamedTemporaryFile(dir=folder, suffix=".pdf", delete=False) as temp:
                temp.write(data); temporary = Path(temp.name)
            try:
                text = extract_text(temporary)
                if isin not in text.replace(" ", ""):
                    raise ValueError("ISIN fehlt im Dokument")
                temporary.replace(target)
                return target, None
            finally:
                if temporary.exists(): temporary.unlink()
        except Exception as exc:
            errors.append(f"{urllib.parse.urlparse(url).netloc}: {exc}")
    return None, ("Kein gültiges Anbieter-Factsheet gefunden" +
                  (": " + "; ".join(errors[:3]) if errors else "."))
