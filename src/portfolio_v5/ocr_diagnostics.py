"""Read-only OCR diagnostics for the local PortMan environment.

The checks never install packages and never modify source PDFs.  They are used by
``tools/check_ocr_windows.py`` and by regression tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import importlib
import importlib.metadata
import json
import platform
import re
import sys
import tempfile
import time
from pathlib import Path

PASS, WARN, FAIL = 'PASS', 'WARN', 'FAIL'
_STATUS_RANK = {PASS: 0, WARN: 1, FAIL: 2}
_OCR_PACKAGES = ('rapidocr', 'onnxruntime', 'pypdfium2', 'pypdf')
_EXPECTED_ISIN = {'LS9AVX': 'DE000LS9AVX3', 'A2H57N': 'LU1681041973',
                  'LYX05A': 'LU2090063673'}


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    hint: str = ''


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def add(self, name, status, detail, hint=''):
        assert status in _STATUS_RANK
        self.checks.append(Check(name, status, detail, hint))
        return self.checks[-1]

    @property
    def status(self):
        return max((check.status for check in self.checks),
                   key=_STATUS_RANK.get, default=PASS)

    @property
    def counts(self):
        return {status: sum(check.status == status for check in self.checks)
                for status in (PASS, WARN, FAIL)}

    def as_dict(self):
        return {'status': self.status, 'counts': self.counts,
                'metadata': self.metadata,
                'checks': [check.__dict__ for check in self.checks]}


def project_root():
    return Path(__file__).resolve().parents[2]


def parse_requirements(path):
    """Return ``{normalized package: version specifier}`` without installing anything."""
    result = {}
    path = Path(path)
    if not path.is_file():
        return result
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line or line.startswith('-'):
            continue
        match = re.match(r'^(?P<name>[A-Za-z0-9_.-]+)(?:\[[^]]*\])?\s*(?P<spec>.*)$', line)
        if match:
            result[match.group('name').lower().replace('_', '-')] = match.group('spec').strip()
    return result


def version_tuple(value):
    parts = []
    for piece in re.split(r'[.+-]', str(value)):
        number = re.match(r'\d+', piece)
        parts.append(int(number.group()) if number else 0)
    return tuple(parts)


def version_satisfies(version, specifier):
    """Small, dependency-free check for the operators used in requirements.txt."""
    if not specifier:
        return True
    try:
        from packaging.requirements import Requirement
        return Requirement(f'x{specifier}').specifier.contains(str(version), prereleases=True)
    except Exception:
        current = version_tuple(version)
        for clause in (item.strip() for item in specifier.split(',')):
            match = re.match(r'^(<=|>=|==|!=|<|>)\s*([0-9][0-9A-Za-z.+-]*)$', clause)
            if not match:
                continue
            operator, target = match.groups()
            wanted = version_tuple(target)
            comparisons = {'<': current < wanted, '<=': current <= wanted,
                           '>': current > wanted, '>=': current >= wanted,
                           '==': current == wanted, '!=': current != wanted}
            if not comparisons.get(operator, True):
                return False
        return True


def package_check(name, requirement=''):
    """Return (status, detail) for one installed distribution."""
    try:
        version = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return FAIL, f'{name} ist nicht installiert' + (f' (benötigt {requirement})' if requirement else '')
    if not version_satisfies(version, requirement):
        return WARN, f'{name} {version} erfüllt nicht {requirement}'
    return PASS, f'{name} {version}' + (f' (Anforderung {requirement})' if requirement else '')


def check_python(report):
    executable = Path(sys.executable)
    detail = (f'Python {platform.python_version()} · {platform.architecture()[0]} · '
              f'{platform.platform()} · {executable}')
    if sys.version_info < (3, 10):
        report.add('Python', FAIL, detail, 'Python 3.10 oder neuer wird benötigt.')
    elif executable.parent.name.lower() == 'scripts' and executable.parent.parent.name == '.venv':
        report.add('Python', PASS, detail, 'Projekt-.venv wird verwendet.')
    else:
        report.add('Python', WARN, detail,
                   'Für die Anwendung das Projekt-.venv verwenden (start_v09.bat).')


def check_packages(report, root=None):
    specs = parse_requirements((root or project_root()) / 'requirements.txt')
    for name in _OCR_PACKAGES:
        status, detail = package_check(name, specs.get(name.lower(), ''))
        report.add(f'Paket {name}', status, detail,
                   'requirements.txt im Projekt-.venv installieren.' if status == FAIL else '')
    for name in ('numpy', 'Pillow', 'PyMuPDF', 'opencv-python-headless'):
        status, detail = package_check(name, specs.get(name.lower(), ''))
        if status == PASS:
            report.add(f'Paket {name}', PASS, detail)


def _model_files(directory):
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob('*.onnx') if path.is_file())


def check_models(report):
    try:
        import rapidocr
        from portfolio_v5.pdf_ocr import persistent_model_dir
    except Exception as error:
        report.add('OCR-Modelle', FAIL, f'rapidocr oder OCR-Modul nicht importierbar: {error}')
        return
    package_models = _model_files(Path(rapidocr.__file__).resolve().parent / 'models')
    names = [item.name for item in package_models]
    has_det = any('det' in name.lower() for name in names)
    has_rec = any('rec' in name.lower() for name in names)
    if not package_models:
        report.add('OCR-Modelle', FAIL, 'Im rapidocr-Paket wurden keine .onnx-Modelle gefunden.',
                   'rapidocr erneut aus requirements.txt installieren (keine automatische Installation durch Portman).')
        return
    if not (has_det and has_rec):
        report.add('OCR-Modelle', FAIL,
                   f'Detektor/Erkenner fehlen: {", ".join(names) or "keine Modelle"}')
        return
    total_mb = sum(item.stat().st_size for item in package_models) / 1024 / 1024
    detail = f'{len(package_models)} Modelle, {total_mb:.1f} MiB: {", ".join(names)}'
    cache = persistent_model_dir()
    cached = _model_files(cache)
    if not cache.is_dir():
        report.add('Modell-Cache', WARN, f'{cache} existiert noch nicht',
                   'Wird beim ersten OCR-Lauf automatisch aus dem rapidocr-Paket befüllt.')
    elif not cached:
        report.add('Modell-Cache', WARN, f'{cache} ist leer',
                   'Wird beim ersten OCR-Lauf automatisch aus dem rapidocr-Paket befüllt.')
    else:
        cache_sizes = {item.name: item.stat().st_size for item in cached}
        missing = [item.name for item in package_models if item.name not in cache_sizes]
        stale = [item.name for item in package_models
                 if item.name in cache_sizes and cache_sizes[item.name] != item.stat().st_size]
        if missing or stale:
            report.add('Modell-Cache', WARN,
                       f'{cache}: fehlend={missing or "keine"}, abweichend={stale or "keine"}',
                       'Der Cache wird beim nächsten OCR-Start abgeglichen.')
        else:
            report.add('Modell-Cache', PASS, f'{cache} · {len(cached)} Modelle stimmen mit dem Paket überein.')
    report.add('OCR-Modelle', PASS, detail)


def check_onnx_providers(report):
    try:
        import onnxruntime
    except Exception as error:
        report.add('ONNX-Provider', FAIL, f'onnxruntime nicht importierbar: {error}')
        return
    try:
        providers = list(onnxruntime.get_available_providers())
        device = onnxruntime.get_device()
    except Exception as error:
        report.add('ONNX-Provider', FAIL, f'Provider-Abfrage fehlgeschlagen: {error}')
        return
    detail = f'onnxruntime {onnxruntime.__version__} · device={device} · {", ".join(providers) or "keine"}'
    if 'CPUExecutionProvider' in providers:
        report.add('ONNX-Provider', PASS, detail)
    else:
        report.add('ONNX-Provider', FAIL, detail,
                   'CPUExecutionProvider fehlt; OCR kann nicht rechnen.')


def check_pdfium_rendering(report):
    try:
        import pypdfium2 as pdfium
        from PIL import Image
        from pypdf import PdfWriter
        pdfium_version = importlib.metadata.version('pypdfium2')
    except Exception as error:
        report.add('PDF-Rendering', FAIL, f'Rendering-Abhängigkeit fehlt: {error}')
        return
    try:
        with tempfile.TemporaryDirectory(prefix='portman-ocr-render-') as directory:
            path = Path(directory) / 'render.pdf'
            writer = PdfWriter()
            writer.add_blank_page(width=300, height=200)
            with path.open('wb') as handle:
                writer.write(handle)
            started = time.perf_counter()
            with pdfium.PdfDocument(str(path)) as document:
                page = document[0]
                try:
                    width, height = page.get_size()
                    bitmap = page.render(scale=2)
                    try:
                        image = bitmap.to_pil().convert('RGB')
                        try:
                            size = image.size
                            assert isinstance(image, Image.Image)
                        finally:
                            image.close()
                    finally:
                        bitmap.close()
                finally:
                    page.close()
            elapsed = time.perf_counter() - started
        if size[0] < width or size[1] < height:
            raise ValueError(f'unerwartete Bildgröße {size} für Seite {width:.0f}x{height:.0f}')
        report.add('PDF-Rendering', PASS,
                   f'pypdfium2 {pdfium_version} · '
                   f'{width:.0f}x{height:.0f} pt → {size[0]}x{size[1]} px in {elapsed:.2f}s')
    except Exception as error:
        report.add('PDF-Rendering', FAIL, f'PDFium-Rendering fehlgeschlagen: {error}')


def check_ocr_engine(report):
    try:
        from portfolio_v5.pdf_ocr import engine
        engine.cache_clear()
        started = time.perf_counter()
        instance = engine()
        elapsed = time.perf_counter() - started
        if instance is None:
            raise RuntimeError('Engine-Objekt ist None')
        report.add('OCR-Engine', PASS, f'RapidOCR initialisiert in {elapsed:.2f}s')
    except Exception as error:
        report.add('OCR-Engine', FAIL, f'Initialisierung fehlgeschlagen: {error}',
                   'Pakete, ONNX-Provider und Modelle prüfen; Portman startet auch ohne OCR.')


def check_ocr_recognition(report):
    try:
        from PIL import Image, ImageDraw, ImageFont
        from portfolio_v5.pdf_ocr import MIN_SAFE_CONFIDENCE, ocr_page, ocr_page_regions
    except Exception as error:
        report.add('OCR-Texterkennung', FAIL, f'Testabhängigkeit fehlt: {error}')
        return
    try:
        with tempfile.TemporaryDirectory(prefix='portman-ocr-smoke-') as directory:
            path = Path(directory) / 'ocr-smoke.pdf'
            image = Image.new('RGB', (1500, 900), 'white')
            draw = ImageDraw.Draw(image)
            try:
                font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 42)
            except OSError:
                font = ImageFont.load_default()
            lines = ['comdirect OCR Test', 'WKN LS9AVX', 'ISIN DE000LS9AVX3',
                     '0,006 Stueck 24,92 EUR']
            for index, line in enumerate(lines):
                draw.text((80, 100 + index * 90), line, fill='black', font=font)
            image.save(path, 'PDF', resolution=150)
            image.close()
            started = time.perf_counter()
            recognized, confidence = ocr_page(path, 0)
            elapsed = time.perf_counter() - started
            regions = ocr_page_regions(path, 0)
        compact = re.sub(r'\s+', '', recognized.upper())
        tokens = ('COMDIRECT', 'LS9AVX', 'DE000LS9AVX3')
        found = [token for token in tokens if token in compact]
        detail = (f'{len(recognized)} Zeichen, {len(regions)} Boxen, '
                  f'Konfidenz {confidence:.2f}, {elapsed:.2f}s, Treffer {"/".join(found) or "keine"}')
        if len(found) < 2:
            report.add('OCR-Texterkennung', FAIL, detail,
                       'Synthetischer Beleg wurde nicht ausreichend erkannt.')
        elif confidence < MIN_SAFE_CONFIDENCE or len(found) < len(tokens):
            report.add('OCR-Texterkennung', WARN, detail,
                       f'Unter der sicheren Schwelle {MIN_SAFE_CONFIDENCE:.0%} bzw. nicht alle Testwörter erkannt.')
        else:
            report.add('OCR-Texterkennung', PASS, detail)
        if recognized and '\ufffd' in recognized:
            report.add('OCR-Zeichenqualität', WARN,
                       f'{recognized.count(chr(0xFFFD))} Ersatzzeichen im synthetischen Ergebnis')
    except Exception as error:
        report.add('OCR-Texterkennung', FAIL, f'Testerkennung fehlgeschlagen: {error}')


def _wkn_from_name(name):
    for token in re.findall(r'(?<![A-Za-z0-9])[A-Z0-9]{6}(?![A-Za-z0-9])', name):
        if any(char.isdigit() for char in token) and any(char.isalpha() for char in token):
            return token
    return ''


def _positive(value):
    number = _number(value)
    return number if number is not None and number > 0 else None


def _number(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _transaction_problems(tx, expected_isin='', validate_isin=None):
    """Validate the fields that matter for an OCR-assisted trade."""
    problems = []
    if tx.security and expected_isin and tx.security != expected_isin:
        problems.append(f'ISIN {tx.security} statt {expected_isin}')
    if tx.security and validate_isin and not validate_isin(tx.security):
        problems.append(f'ungültige ISIN {tx.security}')
    quantity, price = _positive(tx.quantity), _positive(tx.price)
    gross = _positive(tx.gross_amount)
    if quantity is None or price is None:
        problems.append('Stückzahl oder Kurs fehlt/ungültig')
    elif gross is not None and abs(quantity * price - gross) > Decimal('0.02'):
        problems.append(f'{quantity} × {price} passt nicht zu Kurswert {gross}')
    amount = _number(tx.amount)
    if amount is None or amount == 0:
        problems.append('Betrag fehlt/ungültig')
    if tx.kind == 'BUY' and amount is not None and amount >= 0:
        problems.append('Kaufbetrag ist nicht negativ')
    return problems


def check_real_pdf(report, path):
    """Render/OCR only damaged pages of one PDF and validate the parsed batch."""
    path = Path(path)
    name = path.name
    if not path.is_file():
        report.add(f'Beleg {name}', FAIL, 'Datei nicht gefunden')
        return
    try:
        from pypdf import PdfReader
        from portfolio_v5.models import valid_isin
        from portfolio_v5.pdf_importer import needs_ocr, parse_pdf
        from portfolio_v5.pdf_text import extract_page_text
        from portfolio_v5.pdf_ocr import ocr_page
    except Exception as error:
        report.add(f'Beleg {name}', FAIL, f'Import für Belegprüfung fehlgeschlagen: {error}')
        return
    try:
        reader = PdfReader(path)
        damaged = []
        page_times = []
        confidences = []
        for index, page in enumerate(reader.pages):
            extracted, layout_review = extract_page_text(page)
            if needs_ocr(extracted, layout_review=layout_review, has_images=bool(page.images)):
                started = time.perf_counter()
                text, confidence = ocr_page(path, index)
                page_times.append(time.perf_counter() - started)
                confidences.append(confidence)
                damaged.append((index + 1, len(text), confidence))
        started = time.perf_counter()
        batch = parse_pdf(path)
        parse_time = time.perf_counter() - started
        expected_wkn = _wkn_from_name(name)
        expected_isin = _EXPECTED_ISIN.get(expected_wkn)
        problems = []
        if batch.errors:
            problems.extend(batch.errors)
        for tx in batch.transactions:
            problems.extend(_transaction_problems(tx, expected_isin, valid_isin))
        for event in batch.tax_events:
            if expected_isin and event.security_ref and event.security_ref != expected_isin:
                problems.append(f'Steuer-ISIN {event.security_ref} statt {expected_isin}')
        if not (batch.transactions or batch.tax_events or batch.documents):
            problems.append('keine Buchung, kein Steuerereignis und kein Dokument erzeugt')
        min_confidence = min(confidences) if confidences else None
        ocr_seconds = sum(page_times)
        detail = (f'{len(reader.pages)} Seiten · OCR-Seiten {len(damaged)} · '
                  f'OCR {ocr_seconds:.1f}s · Parser {parse_time:.1f}s · '
                  f'min. Konfidenz {"-" if min_confidence is None else f"{min_confidence:.2f}"} · '
                  f'{batch.document_type or "unbekannt"} · '
                  f'{len(batch.transactions)} Buchung(en), {len(batch.tax_events)} Steuerereignis(se)')
        if problems:
            report.add(f'Beleg {name}', FAIL, detail + ' · ' + '; '.join(problems))
        elif not damaged:
            report.add(f'Beleg {name}', PASS, detail,
                       'Native Textextraktion vollständig; OCR war für diesen Beleg nicht nötig.')
        elif ocr_seconds > 40 or parse_time > 60:
            report.add(f'Beleg {name}', WARN, detail, 'Laufzeit über dem Richtwert; Seiten gezielt prüfen.')
        else:
            report.add(f'Beleg {name}', PASS, detail,
                       'OCR nur auf beschädigten Seiten; Betrag, Stückzahl, Kurs und ISIN validiert.')
    except Exception as error:
        report.add(f'Beleg {name}', FAIL, f'Belegprüfung fehlgeschlagen: {error}')


def run_diagnostics(pdf_paths=(), root=None, run_recognition=True):
    root = Path(root) if root else project_root()
    report = Report(metadata={
        'python': platform.python_version(),
        'executable': sys.executable,
        'platform': platform.platform(),
        'project_root': str(root),
        'pdf_files': [str(Path(item)) for item in pdf_paths],
    })
    check_python(report)
    check_packages(report, root)
    check_models(report)
    check_onnx_providers(report)
    check_pdfium_rendering(report)
    check_ocr_engine(report)
    if run_recognition:
        check_ocr_recognition(report)
    for path in pdf_paths:
        check_real_pdf(report, path)
    if not pdf_paths:
        report.add('Reale comdirect-Belege', WARN, 'Keine PDFs übergeben',
                   'Mit --pdf <Datei> die Familien LS9AVX, A2H57N und LYX05A prüfen.')
    return report


def format_report(report):
    lines = ['Portman OCR-Diagnose (Windows)', '=' * 32,
             f'Python: {report.metadata.get("python", "?")} · {report.metadata.get("executable", "?")}',
             f'Projekt: {report.metadata.get("project_root", "?")}', '']
    for check in report.checks:
        lines.append(f'[{check.status}] {check.name}: {check.detail}')
        if check.hint:
            lines.append(f'         Hinweis: {check.hint}')
    counts = report.counts
    lines.extend(['', f'Ergebnis: {report.status} · PASS {counts[PASS]} · '
                      f'WARN {counts[WARN]} · FAIL {counts[FAIL]}'])
    return '\n'.join(lines)


def report_json(report):
    return json.dumps(report.as_dict(), ensure_ascii=False, indent=2)
