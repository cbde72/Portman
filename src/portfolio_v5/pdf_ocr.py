"""Local OCR with bounded rendering; no document upload or cloud service."""
from functools import lru_cache
import os
from pathlib import Path
import shutil
import hashlib
from threading import Lock

_ocr_lock = Lock()
_region_cache = {}


def persistent_model_dir():
    """OCR models survive virtual-environment rebuilds and application updates."""
    base = Path(os.environ.get('LOCALAPPDATA') or (Path.home() / 'AppData' / 'Local'))
    return base / 'PortMan' / 'rapidocr-models'


def seed_model_cache(source, target):
    """Reuse already installed model files instead of downloading them again."""
    source, target = Path(source), Path(target)
    target.mkdir(parents=True, exist_ok=True)
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
                           'Bitte requirements-v05.txt installieren.') from error
    model_dir = seed_model_cache(Path(rapidocr.__file__).resolve().parent / 'models', persistent_model_dir())
    return RapidOCR(params={'Global.use_cls': False,
                            'Global.log_level': 'warning',
                            'Global.model_root_dir': str(model_dir),
                            'EngineConfig.onnxruntime.intra_op_num_threads': 2,
                            'EngineConfig.onnxruntime.inter_op_num_threads': 1})


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
        raise RuntimeError('OCR benötigt pypdfium2; bitte requirements-v05.txt installieren.') from error
    # PDFium and the shared inference engine are not used concurrently.
    with _ocr_lock:
        with pdfium.PdfDocument(str(path)) as document:
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
    if result.txts is None:
        return '', 0.0
    source=Path(path); stat=source.stat()
    key=(str(source.resolve()),stat.st_mtime_ns,stat.st_ctime_ns,stat.st_size,page_index)
    regions=[{'text':str(text),'confidence':float(score),'box':[min(float(p[0]) for p in box)/scale,min(float(p[1]) for p in box)/scale,max(float(p[0]) for p in box)/scale,max(float(p[1]) for p in box)/scale]} for box,text,score in zip(result.boxes,result.txts,result.scores)]
    if len(_region_cache)>=8: _region_cache.pop(next(iter(_region_cache)))
    _region_cache[key]=regions
    return layout_text(result.boxes, result.txts, result.scores)


def ocr_page_regions(path,page_index):
    source=Path(path); stat=source.stat()
    key=(str(source.resolve()),stat.st_mtime_ns,stat.st_ctime_ns,stat.st_size,page_index)
    if key not in _region_cache: ocr_page(path,page_index)
    return list(_region_cache.get(key,[]))
