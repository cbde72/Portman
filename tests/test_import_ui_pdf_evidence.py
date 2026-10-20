import sys
from types import SimpleNamespace

import pytest
from PIL import Image
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from portfolio_v5.models import BankTransaction, ImportBatch, SecurityInfo
from portman.import_preview import security_display_names
from portman.import_ui_v09 import render_pdf_evidence


class Resource:
    def __init__(self, log, name):
        self.log, self.name = log, name

    def close(self):
        self.log.append(self.name)


def fake_pdfium(log, *, fail_search=False):
    class Search(Resource):
        def get_next(self):
            if fail_search:
                raise RuntimeError('search failed')
            return 0, 1

    class TextPage(Resource):
        def search(self, *_args, **_kwargs):
            return Search(log, 'search')

        def get_charbox(self, _index):
            return 1, 1, 5, 5

    class Bitmap(Resource):
        def to_pil(self):
            return Image.new('RGB', (20, 20), 'white')

    class Page(Resource):
        def render(self, **_kwargs):
            return Bitmap(log, 'bitmap')

        def get_textpage(self):
            return TextPage(log, 'textpage')

        def get_height(self):
            return 20

    class Document(Resource):
        def __init__(self, _path):
            super().__init__(log, 'document')

        def __len__(self):
            return 2

        def __getitem__(self, index):
            log.append(f'open-page-{index}')
            return Page(log, f'page-{index}')

    return SimpleNamespace(PdfDocument=Document)


def test_pdf_evidence_repeated_pages_release_all_pdfium_resources(monkeypatch):
    log = []
    monkeypatch.setitem(sys.modules, 'pypdfium2', fake_pdfium(log))

    first = render_pdf_evidence('sample.pdf', 1, 'Buchung')
    second = render_pdf_evidence('sample.pdf', 2, 'Buchung', [
        {'text': 'Buchung markiert', 'box': (1, 1, 5, 5)}])

    assert not first.isNull() and not second.isNull()
    assert log.count('search') == log.count('textpage') == log.count('bitmap') == 2
    assert log.count('page-0') == log.count('page-1') == 1
    assert log.count('document') == 2


def test_pdf_evidence_releases_resources_when_text_search_fails(monkeypatch):
    log = []
    monkeypatch.setitem(sys.modules, 'pypdfium2', fake_pdfium(log, fail_search=True))

    with pytest.raises(RuntimeError, match='search failed'):
        render_pdf_evidence('sample.pdf', 1, 'Buchung')

    assert {'search', 'textpage', 'bitmap', 'page-0', 'document'} <= set(log)


def test_ls9avx_preview_uses_batch_security_name_without_mutating_transaction():
    class Repository:
        @staticmethod
        def metadata():
            return {}

    tx = BankTransaction(
        'Depot', 'trade', '2026-06-01', 'BUY', '-21.98', 'EUR',
        security='DE000LS9AVX3', purpose='Originaler Buchungstext')
    batch = ImportBatch('trade.pdf', 'hash', source_sheet='PDF', transactions=[tx], securities=[
        SecurityInfo('DE000LS9AVX3', isin='DE000LS9AVX3', wkn='LS9AVX',
                     name='LANG+SCHWARZ O.E. INDEX')])

    names = security_display_names(Repository(), [batch])

    assert names['DE000LS9AVX3'] == names['LS9AVX'] == 'LANG+SCHWARZ O.E. INDEX'
    assert tx.security == 'DE000LS9AVX3'
    assert tx.purpose == 'Originaler Buchungstext'


def test_preview_prefers_valid_existing_master_name_and_falls_back_to_identifier():
    class Repository:
        @staticmethod
        def metadata():
            return {'master': {'security_key': 'master', 'isin': 'DE000LS9AVX3', 'wkn': 'LS9AVX',
                               'canonical_name': 'Geprüfter Stammdatenname'}}

    named = ImportBatch('trade.pdf', 'hash', securities=[
        SecurityInfo('DE000LS9AVX3', isin='DE000LS9AVX3', wkn='LS9AVX', name='Importname')])
    unnamed = ImportBatch('other.pdf', 'other', securities=[
        SecurityInfo('DE0000000001', isin='DE0000000001', name='DE0000000001')])

    names = security_display_names(Repository(), [named, unnamed])

    assert names['DE000LS9AVX3'] == 'Geprüfter Stammdatenname'
    assert names.get('DE0000000001', 'DE0000000001') == 'DE0000000001'


def test_import_wizard_double_click_renders_original_page(tmp_path, monkeypatch):
    import portman.import_ui_v09 as ui
    from portman.repository_v09 import RepositoryV09

    QApplication.instance() or QApplication([])
    database = tmp_path / 'preview.sqlite'
    repository = RepositoryV09(database, backups=False)
    try:
        tx = BankTransaction(
            'Depot 1', 'trade', '2026-06-01', 'BUY', '-21.98', 'EUR',
            security='DE000LS9AVX3', purpose='Originaler Buchungstext')
        batch = ImportBatch(
            'sample.pdf', 'hash', source_sheet='PDF', transactions=[tx],
            securities=[SecurityInfo('DE000LS9AVX3', isin='DE000LS9AVX3', wkn='LS9AVX',
                                     name='LANG+SCHWARZ O.E. INDEX')],
            pdf_booking_evidence=[{'page': 1, 'text': 'Originaler Buchungstext'}],
            account_names=['Depot 1'])
        session = SimpleNamespace(decisions={}, batches=[batch], live_path=str(database))
        calls = []

        def render(*args):
            calls.append(args)
            return QImage(10, 10, QImage.Format.Format_RGB888)

        monkeypatch.setattr(ui, 'render_pdf_evidence', render)
        wizard = ui.ImportWizard(repository, session, [repository.preview_summary(batch)])
        wizard.pdf_bookings_table.cellDoubleClicked.emit(0, 6)

        assert len(calls) == 1
        assert calls[0][1:3] == (1, 'Originaler Buchungstext')
        assert wizard.security_display_name(tx.security) == 'LANG+SCHWARZ O.E. INDEX'
        wizard.close()
    finally:
        repository.close()
