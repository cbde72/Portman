import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QTabWidget

from test_comdirect_pdf import report, legacy_report, parsed
from portfolio_v5.accounts import account_key
from pdf_plugins._comdirect_finanzreport_core import parse_finanzreport
from portfolio_v5.models import ImportBatch
from portman.comdirect_pdf_preview import ComdirectPdfPreviewDialog
from portman.repository_v09 import RepositoryV09


def cash(pages):
    return parse_finanzreport(ImportBatch('report.pdf', 'hash', source_sheet='PDF'),
                             pages, b'', bookings_only=True)


@pytest.mark.parametrize('heading', ['Girokonto Dispositionskreditgirocard Tages-/Wochenlimit',
                                   'Girokonto ec Tages-/WochenlimitDispositionskreditEUR 500,-'])
def test_old_headings_and_amount_followed_by_payee(heading):
    pages = report()
    pages[0] = pages[0].replace('\nGirokonto\n', '\n' + heading + '\n')
    pages[0] = pages[0].replace('Überweisung Von Gegenkonto +20,00', 'Überweisung +20,000614 EDEKA')
    batch = cash(pages)
    assert len(batch.transactions) == 2
    assert batch.transactions[0].amount == '20.00'
    assert '0614 EDEKA' in batch.transactions[0].purpose
    assert not batch.snapshots


def test_legacy_embedded_payee_and_dated_balances():
    pages = [p.replace('+10,00', '+10,000614 EDEKA')
             .replace('Alter Saldo ', 'Alter Saldo 01.09.2007 ')
             .replace('Neuer Saldo ', 'Neuer Saldo 03.10.2007 ') for p in legacy_report()]
    batch = cash(pages)
    assert len(batch.transactions) == 2
    assert '0614 EDEKA' in batch.transactions[0].purpose


def test_zero_balance_without_sign_does_not_absorb_card_bookings():
    pages = report()
    pages[0] = pages[0].replace('Girokonto DE89', 'Verrechnungskonto DE12500105170648489890 0,00\nGirokonto DE89')
    pages[1] += ('\nVerrechnungskonto\nBuchungstag Valuta\nAlter Saldo 31.12.2020 0,00\n'
                 'Neuer Saldo 01.02.2021 0,00\nVisa-Karte 1234\nBuchungstag Valuta\n'
                 'Alter Saldo 31.12.2020 +10,00\n01.02.2021 Einkauf -10,00\nNeuer Saldo 01.02.2021 0,00')
    batch = cash(pages)
    assert len(batch.transactions) == 2
    assert len(batch.account_names) == 2
    assert [b.value for b in batch.balances][-2:] == ['0.00', '0.00']


def test_counterparty_product_and_iban_cannot_change_owner():
    pages = report()
    pages[0] = pages[0].replace('Referenz erster Teil', 'Girokonto DE12500105170648489890 +999,00\nGirokonto')
    batch = cash(pages)
    assert batch.account_names == ['IBAN DE89370400440532013000']
    assert all(t.account == batch.account_names[0] for t in batch.transactions)


def test_missing_iban_is_not_invented_from_counterparty():
    pages = report()
    pages[0] = pages[0].replace('Kundennummer 102 1234567', 'Ihre Kontonummer: 1234567')
    pages[0] = pages[0].replace('Girokonto DE89 3704 0044 0532 0130 00 +110,00', 'Girokonto +110,00')
    batch = cash(pages)
    assert batch.account_names == ['comdirect Girokonto (Stammkonto 1234567)']


def test_unreadable_depot_does_not_block_cash_but_bad_cash_still_does():
    pages = [p.replace('ABC123 / Girosammelverwahrung', 'ABC123 / Unbekannt') for p in report()]
    assert len(cash(pages).transactions) == 2
    with pytest.raises(ValueError, match='Saldenprüfung'):
        cash([p.replace('+110,00', '+111,00') for p in pages])


def test_simple_preview_no_writes_on_cancel_and_iban_persisted_on_import(tmp_path):
    QApplication.instance() or QApplication([])
    repo = RepositoryV09(tmp_path / 'test.sqlite', backups=False)
    try:
        original = parsed()
        before = deepcopy(original)
        dialog = ComdirectPdfPreviewDialog(repo, [original])
        assert not dialog.findChildren(QTabWidget)
        assert len(dialog.choices) == 2  # Own cash account and depot; no counterparties.
        assert not repo.account_records() and not repo.imports()
        selected = dialog.selected_batches()
        assert selected[0].snapshots[0].positions[0].value == '20.00'
        assert dialog.files.item(0, 3).text() == '20,00'
        assert dialog.positions.rowCount() == 1
        assert original == before
        dialog.reject()
        assert not repo.account_records() and not repo.imports()
        result = repo.commit_batches(selected)[0]
        assert result['status'] == 'imported'
        details = json.loads(next(r for r in repo.account_records() if r['name'].startswith('IBAN '))['details'])
        assert details['iban'] == 'DE89370400440532013000'
        assert details['number'] == '0532013000'
        assert repo.commit_batches(selected)[0]['status'] == 'duplicate'
        assert len(repo.transactions()) == 2
        # A copied report with another file hash still adds no duplicate bookings.
        copied = deepcopy(selected[0])
        copied.file_hash = 'another-file'
        copied.path = 'copy.pdf'
        assert repo.commit_batches([copied])[0]['status'] == 'imported'
        assert len(repo.transactions()) == 2
        dialog.close()
    finally:
        repo.close()


def test_ambiguous_iban_requires_one_choice_and_errors_can_be_skipped(tmp_path):
    QApplication.instance() or QApplication([])
    repo = RepositoryV09(tmp_path / 'test.sqlite', backups=False)
    try:
        for name in ['Giro A', 'Giro B']:
            repo.save_account(name, {'iban': 'DE89370400440532013000'})
        good = parsed()
        bad = ImportBatch('broken.pdf', 'bad', document_type='comdirect Finanzreport', errors=['Fehler'])
        dialog = ComdirectPdfPreviewDialog(repo, [good, bad])
        combo = dialog.choices[account_key('IBAN DE89370400440532013000')]
        assert combo.currentData() is None
        button = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
        assert not button.isEnabled()
        combo.setCurrentIndex(combo.findData(account_key('Giro B')))
        assert button.isEnabled()
        selected = dialog.selected_batches()
        assert len(selected) == 1
        assert repo.commit_batches(selected)[0]['status'] == 'imported'
        assert len(repo.transactions('Giro B')) == 2
        for choice in dialog.choices.values():
            choice.setCurrentIndex(choice.findData('__skip__'))
        assert not dialog.selected_batches() and not button.isEnabled()
        assert dialog.bookings.rowCount() == 0
        dialog.close()
    finally:
        repo.close()


def test_comdirect_preview_marks_urgent_review_and_copies_status(tmp_path):
    QApplication.instance() or QApplication([])
    repo = RepositoryV09(tmp_path / 'warning.sqlite', backups=False)
    try:
        batch = parsed()
        warning = 'PRÜFUNG ERFORDERLICH: Zinsabschluss weicht ab.'
        batch.warnings.append(warning)
        batch.transactions[0].field_sources['interest_reconciliation'] = warning
        dialog = ComdirectPdfPreviewDialog(repo, [batch])

        assert dialog.files.item(0, 4).font().bold()
        assert dialog.files.item(0, 4).foreground().color().name().lower() == '#dc2626'
        assert dialog.bookings.item(0, 0).font().bold()
        dialog.copy_status()
        copied = QApplication.clipboard().text()
        assert warning in copied
        assert 'report.pdf' in copied
        dialog.close()
    finally:
        repo.close()


def test_sparse_text_account_appendix_with_logo_needs_no_ocr(tmp_path, monkeypatch):
    from portfolio_v5 import pdf_importer, pdf_ocr
    appendix = ('comdirect\nFinanzreport Nr. 1 per 01.02.2021\n'
                'Übersicht Ihrer Kontodaten\nGirokonto: DE89 3704 0044 0532 0130 00')
    pages = [SimpleNamespace(extract_text=lambda text=text, **kw: text, images=[object()])
             for text in report() + [appendix]]
    monkeypatch.setattr(pdf_importer, 'PdfReader', lambda path: SimpleNamespace(is_encrypted=False, pages=pages))
    def unexpected_ocr(*args):
        pytest.fail('Text account appendix must not run OCR on its logo')
    monkeypatch.setattr(pdf_ocr, 'ocr_page', unexpected_ocr)
    path = tmp_path / 'report.pdf'
    path.write_bytes(b'test')
    batch = pdf_importer.parse_pdf(path)
    assert not batch.errors
    assert len(batch.transactions) == 2


@pytest.mark.parametrize('position', [
    'ABC123 2,000 STK 10,000 USD 20,0018,00 +2,00',
    'ABC123 / Girosammelverwahrung 2,000 10,000 USD 20,0018,00 +2,00TEST FONDS',
])
def test_depot_layouts_have_values_and_names(position):
    pages = report()
    pages[1] = pages[1].replace('ABC123 / Girosammelverwahrung 2,000 10,000 USD 20,0018,00 +2,00', position)
    batch = parse_finanzreport(ImportBatch('report.pdf', 'hash'), pages, b'')
    value = batch.snapshots[0].positions[0]
    assert (value.quantity, value.value, value.cost) == ('2', '20.00', '18.00')
    assert value.name.startswith('TEST FONDS')


def test_depot_unknown_cost_and_zero_snapshot():
    pages = report()
    pages[1] = pages[1].replace('20,0018,00 +2,00', '0,00 ----- -----').replace('20,00 18,00 +2,00', '0,00 0,00 +0,00')
    batch = parse_finanzreport(ImportBatch('report.pdf', 'hash'), pages, b'')
    assert batch.snapshots[0].positions[0].cost is None
    assert batch.snapshots[0].positions[0].value == '0.00'
    pages = report()
    pages[0] = pages[0].replace('Girokonto DE89', 'Depot 0,00\nGirokonto DE89')
    pages[1] = pages[1].split('\nDepot\n')[0]
    batch = parse_finanzreport(ImportBatch('report.pdf', 'hash'), pages, b'')
    assert batch.snapshots[0].complete and not batch.snapshots[0].positions


def test_fast_reader_uses_native_text_and_preserves_values(tmp_path, monkeypatch):
    import pymupdf
    from portfolio_v5 import pdf_importer
    path = tmp_path / 'native.pdf'
    with pymupdf.open() as document:
        for text in report():
            page = document.new_page()
            for line, value in enumerate(text.splitlines()):
                page.insert_text((30, 30 + line * 12), value, fontsize=8)
        document.save(path)
    def unexpected_slow_reader(*args):
        pytest.fail('A fully readable report must use the native fast reader')
    monkeypatch.setattr(pdf_importer, 'PdfReader', unexpected_slow_reader)
    batch = pdf_importer.parse_pdf(path)
    assert not batch.errors
    assert [t.amount for t in batch.transactions] == ['20.00', '-10.00']
    assert batch.snapshots[0].positions[0].value == '20.00'


def test_fast_reader_defers_image_page_with_selectable_letterhead():
    import pymupdf
    from pdf_plugins._comdirect_fast import try_fast_finanzreport
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((30, 30), 'comdirect Finanzreport Nr. 1 per 01.02.2021')
        picture = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 200), False)
        picture.clear_with(255)
        page.insert_image(pymupdf.Rect(30, 60, 550, 750), pixmap=picture)
        content = document.tobytes()
    assert try_fast_finanzreport('scan.pdf', content) is None


def test_fast_reader_assigns_exact_comdirect_booking_columns():
    from pdf_plugins._comdirect_fast import booking_columns
    from portfolio_v5.models import BankTransaction
    tx = BankTransaction('IBAN DE89370400440532013000', 'id', '2026-09-30',
                         'BANK_BOOKING', '125.00', 'EUR',
                         purpose='Unstrukturierter Originaltext', raw_text='Unstrukturierter Originaltext')
    def span(x, value):
        return {'origin': (x, 10), 'text': value}
    lines = [
        [span(20, '30.09.2026'), span(110, 'Überweisungsgutschr.'),
         span(220, 'Beispiel GmbH'), span(350, 'Rechnung 42'), span(520, '+125,00')],
        [span(20, '30.09.2026'), span(110, 'REF 123/45-AB'),
         span(220, 'DE12 5001 0517 0648 4898 90 / COBADEFFXXX'),
         span(350, 'Kundennummer 987')],
    ]

    booking_columns(tx, lines, (100, 200, 330, 500))

    assert tx.operation == 'Überweisungsgutschr.'
    assert tx.counterparty == 'Beispiel GmbH'
    assert tx.booking_text == 'Rechnung 42\nKundennummer 987'
    assert tx.bank_reference == 'REF 123/45-AB'
    assert tx.counterparty_iban == 'DE12500105170648489890'
    assert tx.counterparty_bic == 'COBADEFFXXX'
    assert tx.purpose == ('Vorgang: Überweisungsgutschr. · Gegenpartei: Beispiel GmbH · '
        'Verwendungszweck: Rechnung 42 Kundennummer 987 · Referenz: REF 123/45-AB · '
        'Gegenkonto-IBAN: DE12500105170648489890 · Gegenkonto-BIC: COBADEFFXXX')


def test_depot_upgrade_after_reader_change_does_not_duplicate_bookings(tmp_path):
    repo = RepositoryV09(tmp_path / 'upgrade.sqlite', backups=False)
    try:
        original = parsed()
        original.snapshots = []
        original.documents = [d for d in original.documents if d.account.startswith('IBAN ')]
        original.account_names = [n for n in original.account_names if n.startswith('IBAN ')]
        assert repo.commit_batches([original])[0]['status'] == 'imported'
        updated = parsed()
        for tx in updated.transactions:
            tx.external_id += '-new-reader'
            tx.purpose = ' '.join(reversed(tx.purpose.split()))
        assert repo.commit_batches([updated])[0]['status'] == 'imported'
        assert len(repo.transactions()) == 2
        assert repo.holdings('2021-02-01')[0]['value'] == '20.00'
        assert repo.commit_batches([updated])[0]['status'] == 'duplicate'
        assert len(repo.transactions()) == 2
    finally:
        repo.close()


def test_commit_job_reports_progress_and_cancellation(tmp_path):
    from portman.comdirect_import import commit_reports
    path = tmp_path / 'job.sqlite'
    RepositoryV09(path, backups=False).close()
    progress = []
    job = SimpleNamespace(path=path, progress=SimpleNamespace(emit=lambda *args: progress.append(args)),
                          isInterruptionRequested=lambda: bool(progress))
    results = commit_reports(job, [parsed(), parsed()], RepositoryV09)
    assert [r['status'] for r in results] == ['imported', 'cancelled']
    assert progress == [(1, 2)]
    repo = RepositoryV09(path, backups=False)
    try:
        assert len(repo.transactions()) == 2
        assert repo.holdings('2021-02-01')
    finally:
        repo.close()


def test_import_finish_refreshes_only_visible_workspace(monkeypatch, tmp_path):
    from portman.gui.window_shell import MainWindow
    from portman import comdirect_pdf_preview, comdirect_import, jobs_v09
    calls = []
    preview = SimpleNamespace(exec=lambda: 1, selected_batches=lambda: [parsed()])
    monkeypatch.setattr(comdirect_pdf_preview, 'ComdirectPdfPreviewDialog', lambda *args: preview)
    result = [{'status': 'imported'}]
    def commit(job, selected, kind, versioned, backup=False):
        calls.append(('worker', backup)); return result
    monkeypatch.setattr(comdirect_import, 'commit_reports', commit)
    monkeypatch.setattr(jobs_v09, 'run_job', lambda parent, path, title, work: work(None))
    fake = SimpleNamespace(repository=SimpleNamespace(backups_enabled=True, store=SimpleNamespace(path=tmp_path/'db.sqlite')),
        progress_bar=SimpleNamespace(setVisible=lambda value: None), _scope_refreshers={},
        refresh_scope_choices=lambda: calls.append('scope'), reload_portfolio=lambda **kw: calls.append(kw),
        status_bar=SimpleNamespace(showMessage=lambda *args: None))
    MainWindow.finish_comdirect_pdf_import(fake, [parsed()])
    assert calls == [('worker', True), 'scope', {'visible_only': True}]
    calls.clear(); result[:] = [{'status': 'duplicate'}]
    MainWindow.finish_comdirect_pdf_import(fake, [parsed()])
    assert calls == [('worker', True)]
