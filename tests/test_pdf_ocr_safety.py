import builtins

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from portfolio_v5.pdf_importer import needs_ocr, parse_pdf, text_is_damaged


def make_pdf(path, texts):
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=600, height=800)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
            DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(('BT /F1 12 Tf 50 700 Td (' + text + ') Tj ET').encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    writer.write(path)
    return path


OCR_STATEMENT = '''Konto-Nr.: 12345678
EUR-Konto
01.09. Einzahlung 25,00 H'''


def test_needs_ocr_only_for_damaged_or_image_backed_pages():
    assert not needs_ocr('Datum Betrag\n01.01.2026 10,00' * 30)
    assert needs_ocr('', layout_review=False, has_images=False)
    # pypdf now reports the layout of complete comdirect statements for review.
    # That hint alone must not trigger OCR.
    assert not needs_ocr('Datum Betrag\n01.01.2026 10,00' * 30, layout_review=True)
    assert needs_ocr('Kurzer Text', has_images=True)
    assert needs_ocr('Text \ufffd\ufffd\ufffd\ufffd' * 10)
    assert not needs_ocr('Kurzer Text')
    appendix = ('comdirect Finanzreport Nr. 1 Übersicht Ihrer Kontodaten '
                'IBAN DE84 2004 1133 0476 4924 00')
    assert not needs_ocr(appendix, has_images=True)


def test_long_letter_runs_indicate_broken_font_mapping():
    native = 'Wertpapierabrechnung\nISIN DE000LS9AVX3\nKurswert 24,92 EUR\n' * 20
    assert not text_is_damaged(native)
    assert not text_is_damaged('Trennlinie ' + '_' * 60)
    assert not text_is_damaged('Normaler Text ' + 'A' * 19)
    for filler in ('z', 'R', '\u00fc'):
        assert text_is_damaged('Kauf\n' + filler * 80 + '\nEndbetrag 24,92 EUR')
    assert needs_ocr('Kauf\n' + 'z' * 80, layout_review=True)


def test_parse_pdf_forwards_allow_ocr_to_plugins(tmp_path):
    from portfolio_v5.models import ImportBatch
    from portfolio_v5.pdf_plugins import Detection

    seen = {}

    class RecordingPlugin:
        plugin_id = 'test.recording'
        bank_name = 'Testbank'
        version = '1.0'

        def detect(self, document):
            return [Detection(1.0, 'Testdokument', 'test', 'erkannt')]

        def parse(self, document, detection, context):
            seen.update(context.options)
            return ImportBatch(document.path, document.file_hash, source_sheet='PDF')

    path = make_pdf(tmp_path / 'plugin.pdf', ['Datum Betrag\n01.01.2026 10,00' * 30])
    parse_pdf(path, allow_ocr=False, plugin_catalog=([RecordingPlugin()], []))
    assert seen == {'allow_ocr': False}
    parse_pdf(path, allow_ocr=True, plugin_catalog=([RecordingPlugin()], []))
    assert seen == {'allow_ocr': True}


def test_low_confidence_ocr_is_not_used_for_bookings(tmp_path, monkeypatch):
    from portfolio_v5 import pdf_ocr
    pdf_ocr.clear_cache()
    monkeypatch.setattr(pdf_ocr, 'ocr_page', lambda *args: (OCR_STATEMENT, 0.42))
    batch = parse_pdf(make_pdf(tmp_path / 'scan.pdf', ['']))
    assert not batch.errors
    assert batch.documents
    assert not batch.transactions
    assert any('geringer Sicherheit' in warning and '42%' in warning for warning in batch.warnings)


def test_low_confidence_ocr_keeps_usable_native_text(tmp_path, monkeypatch):
    from portfolio_v5 import pdf_importer, pdf_ocr
    pdf_ocr.clear_cache()
    native = 'Konto: 12345678\n' + 'Buchungstext ' * 40
    monkeypatch.setattr(pdf_importer, 'needs_ocr', lambda *args, **kwargs: True)
    monkeypatch.setattr(pdf_ocr, 'ocr_page', lambda *args: ('Konto: 99999999', 0.10))
    batch = parse_pdf(make_pdf(tmp_path / 'native.pdf', [native]))
    assert not batch.errors
    assert any('Konto 12345678' in document.account for document in batch.documents)
    assert not any('Konto 99999999' in document.account for document in batch.documents)
    assert any('nicht übernommen' in warning for warning in batch.warnings)


def test_missing_ocr_packages_are_reported_instead_of_crashing(tmp_path, monkeypatch):
    from portfolio_v5 import pdf_ocr
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in {'rapidocr', 'onnxruntime'} or name.startswith('rapidocr.'):
            raise ImportError('simuliert: Paket fehlt')
        return real_import(name, *args, **kwargs)

    pdf_ocr.engine.cache_clear()
    monkeypatch.setattr(builtins, '__import__', fake_import)
    with pytest.raises(RuntimeError, match='rapidocr'):
        pdf_ocr.engine()
    pdf_ocr.engine.cache_clear()

    monkeypatch.setattr(pdf_ocr, 'engine', lambda: (_ for _ in ()).throw(
        RuntimeError('simuliert: Raketentreibstoff fehlt')))
    batch = parse_pdf(make_pdf(tmp_path / 'scan.pdf', ['']))
    assert not batch.errors
    assert batch.documents
    assert not batch.transactions
    assert any('OCR fehlgeschlagen' in warning for warning in batch.warnings)


def test_ocr_engine_exception_keeps_document(tmp_path, monkeypatch):
    from portfolio_v5 import pdf_ocr
    pdf_ocr.clear_cache()
    monkeypatch.setattr(pdf_ocr, 'engine', lambda: (_ for _ in ()).throw(
        RuntimeError('Engine-Initialisierung fehlgeschlagen')))
    batch = parse_pdf(make_pdf(tmp_path / 'scan.pdf', ['']))
    assert not batch.errors
    assert batch.documents
    assert not batch.transactions
    assert any('Engine-Initialisierung' in warning for warning in batch.warnings)


def test_text_is_reliable_requires_text_and_confidence():
    from portfolio_v5.pdf_ocr import MIN_SAFE_CONFIDENCE, text_is_reliable
    assert text_is_reliable('Text', MIN_SAFE_CONFIDENCE)
    assert not text_is_reliable('', 0.99)
    assert not text_is_reliable('   ', 0.99)
    assert not text_is_reliable('Text', None)
    assert not text_is_reliable('Text', MIN_SAFE_CONFIDENCE - .01)


def test_seed_model_cache_handles_missing_source(tmp_path):
    from portfolio_v5.pdf_ocr import seed_model_cache
    target = tmp_path / 'cache'
    assert seed_model_cache(tmp_path / 'missing', target) == target
    assert target.is_dir()
    assert not list(target.iterdir())
