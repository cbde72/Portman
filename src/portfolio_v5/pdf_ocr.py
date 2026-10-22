"""Local OCR with bounded rendering; no document upload or cloud service."""
from functools import lru_cache
import os
from pathlib import Path
import shutil
import hashlib
from threading import Lock

_ocr_lock = Lock()
_region_cache = {}
_text_cache = {}
_cache_limit = 8

# OCR text replaces damaged native text only above this page-level confidence.
# Bank-specific parsers may require stricter per-field thresholds (comdirect: 0.90).
MIN_SAFE_CONFIDENCE = 0.80


def persistent_model_dir():
    """OCR models survive virtual-environment rebuilds and application updates."""
    base = Path(os.environ.get('LOCALAPPDATA') or (Path.home() / 'AppData' / 'Local'))
    return base / 'PortMan' / 'rapidocr-models'


def seed_model_cache(source, target):
    """Reuse already installed model files instead of downloading them again."""
    source, target = Path(source), Path(target)
    target.mkdir(parents=True, exist_ok=True)
    if not source.is_dir():
        return target
    for model in source.glob('*'):
        if not model.is_file() or model.name == '.gitkeep':
            continue
        cached = target / model.name
        changed = (not cached.exists() or cached.stat().st_size != model.stat().st_size)
        if not changed:
            changed = hashlib.sha256(cached.read_bytes()).digest() != hashlib.sha256(model.read_bytes()).digest()
        if changed:
            shutil.copy2(model, cached)
    return target


@lru_cache(maxsize=1)
def engine():
    try:
        import rapidocr
        from rapidocr import RapidOCR
        import onnxruntime  # noqa: F401 - fail with actionable message
    except ImportError as error:
        raise RuntimeError('OCR benötigt rapidocr, onnxruntime und pypdfium2. '
                           'Bitte requirements.txt im Projekt-.venv installieren.') from error
    try:
        model_dir = seed_model_cache(Path(rapidocr.__file__).resolve().parent / 'models', persistent_model_dir())
        return RapidOCR(params={'Global.use_cls': False,
                                'Global.log_level': 'warning',
                                'Global.model_root_dir': str(model_dir),
                                'EngineConfig.onnxruntime.intra_op_num_threads': 2,
                                'EngineConfig.onnxruntime.inter_op_num_threads': 1})
    except Exception as error:
        raise RuntimeError(f'OCR-Engine konnte nicht initialisiert werden: {error}') from error


def clear_cache():
    """Drop cached text/regions (tests and diagnostics only; never touches PDFs)."""
    with _ocr_lock:
        _region_cache.clear()
        _text_cache.clear()


def _cache_key(path, page_index):
    source = Path(path)
    stat = source.stat()
    return (str(source.resolve()), stat.st_mtime_ns, stat.st_ctime_ns,
            stat.st_size, int(page_index))


def _remember(cache, key, value):
    if len(cache) >= _cache_limit:
        cache.pop(next(iter(cache)))
    cache[key] = value


def text_is_reliable(text, confidence, minimum=MIN_SAFE_CONFIDENCE):
    """Only accept OCR text with enough confidence; callers keep native text otherwise."""
    return bool(text and text.strip()) and confidence is not None and confidence >= minimum


def layout_text(boxes, texts, scores):
    """Reassemble boxes into rows and retain horizontal amount-column positions."""
    words = []
    for box, text, score in zip(boxes, texts, scores):
        xs, ys = [float(p[0]) for p in box], [float(p[1]) for p in box]
        words.append((min(xs), (min(ys) + max(ys)) / 2, max(ys) - min(ys), str(text), float(score)))
    if not words:
        return '', 0.0
    heights = sorted(max(1, word[2]) for word in words)
    char_width = max(3, heights[len(heights) // 2] * .5)
    rows = []
    for word in sorted(words, key=lambda w: (w[1], w[0])):
        if rows and abs(rows[-1][0] - word[1]) <= max(3, word[2] * .45):
            rows[-1][1].append(word)
        else:
            rows.append((word[1], [word]))
    lines = []
    for _, row in rows:
        line = ''
        for x, _, _, text, _ in sorted(row):
            column = min(2000, int(x / char_width))
            line += ' ' * max(1 if line else 0, column - len(line)) + text
        lines.append(line)
    return '\n'.join(lines), min(word[4] for word in words)


def ocr_page(path, page_index):
    try:
        import pypdfium2 as pdfium
    except ImportError as error:
        raise RuntimeError('OCR benötigt pypdfium2; bitte requirements.txt im Projekt-.venv installieren.') from error
    path = Path(path)
    key = _cache_key(path, page_index)
    # PDFium and the shared inference engine are not used concurrently.  The
    # cache prevents the importer and a bank plugin from running OCR twice for
    # the same unchanged page.
    with _ocr_lock:
        if key in _text_cache:
            return _text_cache[key]
        with pdfium.PdfDocument(str(path)) as document:
            if page_index < 0 or page_index >= len(document):
                raise ValueError(f'PDF-Seite {page_index + 1} existiert nicht (Dokument hat {len(document)} Seiten).')
            page = document[page_index]
            try:
                width, height = page.get_size()
                scale = min(3.0, 3200 / max(width, height))
                bitmap = page.render(scale=scale)
                try:
                    image = bitmap.to_pil().convert('RGB')
                    try:
                        result = engine()(image)
                    finally:
                        image.close()
                finally:
                    bitmap.close()
            finally:
                page.close()
        if result is None or getattr(result, 'txts', None) is None:
            answer = ('', 0.0)
            _remember(_region_cache, key, [])
            _remember(_text_cache, key, answer)
            return answer
        regions = [{'text': str(text), 'confidence': float(score),
                    'box': [min(float(p[0]) for p in box) / scale, min(float(p[1]) for p in box) / scale,
                            max(float(p[0]) for p in box) / scale, max(float(p[1]) for p in box) / scale]}
                   for box, text, score in zip(result.boxes, result.txts, result.scores)]
        answer = layout_text(result.boxes, result.txts, result.scores)
        _remember(_region_cache, key, regions)
        _remember(_text_cache, key, answer)
        return answer


def ocr_page_regions(path, page_index):
    key = _cache_key(path, page_index)
    if key not in _region_cache:
        ocr_page(path, page_index)
    return list(_region_cache.get(key, []))
