from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from fints.client import FinTSOperations as Op
from fints.models import Amount
from fints.formals import StatementFormat
from portman.ing_banking import BankingError, fetch_ing
from portman.ing_history import parse_transactions, fetch_history, document_from_bytes, local_document_batch
from portman.repository import PortfolioRepository
from portfolio_v5.models import ImportBatch
from test_ing_banking import FakeClient


PDF = b'%PDF-1.4\n% Synthetic transport fixture, not a rendered statement\n%%EOF\n'


def transaction(day=date(2026, 9, 12), amount='-14.50', purpose='Testbuchung'):
    return SimpleNamespace(data={'date': date(2026, 9, 13), 'guessed_entry_date': day,
        'amount': Amount(amount, 'EUR'), 'purpose': purpose, 'applicant_name': 'Testhandel', 'bank_reference': 'NONREF'})


def test_booking_date_value_date_sign_and_real_twins():
    rows = [transaction(), transaction(), transaction(amount='42.00')]
    parsed = parse_transactions(rows, 'Konto', date(2026, 9, 1), date(2026, 9, 30))
    assert len(parsed) == 3
    assert len({t.external_id for t in parsed}) == 3
    assert all(t.date == '2026-09-12' and t.value_date == '2026-09-13' for t in parsed)
    assert all(t.kind == 'BANK_BOOKING' for t in parsed)
    assert sorted(t.amount for t in parsed) == ['-14.5', '-14.5', '42']
    assert {t.external_id for t in parse_transactions(list(reversed(rows)), 'Konto', date(2026, 9, 12), date(2026, 9, 12))} == {t.external_id for t in parsed}


def test_alternate_fints_reference_is_preserved():
    row = transaction()
    row.data['bank_reference'] = ''
    row.data['end_to_end_reference'] = 'E2E-REF-42'
    parsed = parse_transactions([row], 'Konto', date(2026, 9, 1), date(2026, 9, 30))[0]
    assert parsed.bank_reference == parsed.document_reference == 'E2E-REF-42'


def test_all_available_history_requests_no_lower_bank_limit():
    from portman.bank_history_range import ALL_HISTORY_START
    client = Mock()
    client.get_transactions.return_value = [transaction(day=date(2001, 1, 2)), transaction()]
    batches = fetch_history(client, SimpleNamespace(iban='DETEST'), {Op.GET_TRANSACTIONS: True},
        'Konto', 'history.bank', lambda value: value, lambda message: None,
        start=ALL_HISTORY_START, end=date(2026, 9, 24), documents=False)
    assert client.get_transactions.call_args.kwargs['start_date'] is None
    assert [tx.date for tx in batches[0].transactions] == ['2001-01-02', '2026-09-12']
    assert any('gesamte verfügbare Historie' in warning for warning in batches[0].warnings)


def test_explicit_history_range_still_sent_to_bank():
    client = Mock()
    client.get_transactions.return_value = [transaction()]
    history(client, {Op.GET_TRANSACTIONS: True})
    assert client.get_transactions.call_args.kwargs['start_date'] == date(2026, 9, 1)


def test_malformed_transaction_rejects_batch():
    bad = transaction()
    bad.data['amount'] = None
    with pytest.raises(BankingError):
        parse_transactions([transaction(), bad], 'Konto', date(2026, 9, 1), date(2026, 9, 30))


def test_overlapping_history_import_no_duplicates(tmp_path):
    repo = PortfolioRepository(tmp_path / 'db.sqlite')
    rows = [transaction(), transaction()]
    first = ImportBatch('first.bank', 'one', transactions=parse_transactions(rows, 'ING Konto', date(2026, 9, 1), date(2026, 9, 30)))
    second = ImportBatch('second.bank', 'two', transactions=parse_transactions(rows + [transaction(day=date(2026, 9, 15))], 'ING Konto', date(2026, 9, 10), date(2026, 9, 30)))
    repo.commit_batches([first, second])
    assert len(repo.transactions()) == 3
    assert not repo.store.db.execute('SELECT * FROM coverage').fetchall()
    repo.close()


def history(client, ops, **kwargs):
    return fetch_history(client, SimpleNamespace(iban='DETEST'), ops, 'ING Konto', 'ing-konto.bank',
                         lambda value: value, lambda message: None,
                         start=date(2026, 9, 1), end=date(2026, 9, 24), documents=True, **kwargs)


def test_unsupported_capabilities_make_no_requests():
    client = Mock()
    batches = history(client, {})
    assert len(batches) == 2 and all(b.errors for b in batches)
    assert not client.mock_calls


def test_statements_and_transactions_are_independently_previewed():
    client = Mock()
    client.get_transactions.return_value = [transaction()]
    listing = SimpleNamespace(year=2026, statement_number=9, collection_possible=True, date_created=date(2026, 9, 12))
    client.get_statements.return_value = [listing, listing]
    client.get_statement.return_value = SimpleNamespace(data=PDF, account_iban='DETEST')
    batches = history(client, {Op.GET_TRANSACTIONS: True, Op.GET_STATEMENT: True})
    assert sum(len(b.documents) for b in batches) == 1
    assert sum(len(b.transactions) for b in batches) == 1
    client.get_statement.assert_called_once()
    assert client.get_statement.call_args.kwargs['format'] == StatementFormat.PDF
    assert client.get_transactions.call_args.kwargs['include_pending'] is False


def test_document_failure_keeps_successful_history():
    client = Mock()
    client.get_transactions.return_value = [transaction()]
    client.get_statements.side_effect = RuntimeError('secret bank response')
    batches = history(client, {Op.GET_TRANSACTIONS: True, Op.GET_STATEMENT: True})
    assert batches[0].transactions and not batches[0].errors
    assert batches[1].errors
    assert 'secret' not in str(batches)


@pytest.mark.parametrize('content', [b'not PDF', b'%PDF-1.4 truncated', b'<!DOCTYPE html>'])
def test_invalid_document_never_archived(content):
    with pytest.raises(BankingError):
        document_from_bytes('ING', 'id', 'Titel', '', content)


def test_archive_duplicate_reassign_undo_delete_export(tmp_path):
    from portman.bank_archive import export_documents
    repo = PortfolioRepository(tmp_path / 'db.sqlite')
    repo.create_accounts(['Ziel A', 'Ziel B'])
    document = document_from_bytes('Quelle', '2026-1', '../Kontoauszug', '2026-01-31', PDF)
    batch = ImportBatch('doc.bank', 'hash', documents=[document], account_assignments={'quelle': 'ziel a'})
    result = repo.commit_batches([batch])[0]
    assert result['documents'] == 1
    assert repo.commit_batches([batch])[0]['status'] == 'duplicate'
    stored = repo.bank_documents('Ziel A')[0]
    assert stored['size'] == len(PDF)
    paths = export_documents(repo, [stored['id']], tmp_path)
    assert paths[0].parent == tmp_path
    assert paths[0].read_bytes() == PDF
    export_documents(repo, [stored['id']], tmp_path)
    paths[0].write_bytes(b'existing unrelated file')
    with pytest.raises(ValueError, match='gleichnamige'):
        export_documents(repo, [stored['id']], tmp_path)
    assert paths[0].read_bytes() == b'existing unrelated file'
    repo.reassign_imports([{'import_id': result['id'], 'source_key': 'quelle', 'target_key': 'ziel b'}])
    assert not repo.bank_documents('Ziel A') and len(repo.bank_documents('Ziel B')) == 1
    with pytest.raises(ValueError, match='Originaldokumente'):
        repo.correct_import(result['id'], {})
    repo.undo_import(result['id'])
    assert not repo.bank_documents()
    with pytest.raises(ValueError):
        repo.bank_document_content(stored['id'])
    repo.delete_imports([result['id']])
    assert not repo.db.execute('SELECT * FROM bank_documents').fetchall()
    repo.close()


def test_document_import_atomic_on_bad_document(tmp_path):
    repo = PortfolioRepository(tmp_path / 'db.sqlite')
    good = document_from_bytes('ING', 'ok', 'OK', '', PDF)
    bad = document_from_bytes('ING', 'bad', 'Bad', '', PDF)
    bad.content_b64 = 'not valid base64!'
    results = repo.commit_batches([ImportBatch('docs.bank', 'hash', documents=[good, bad])])
    assert results[0]['status'] == 'error'
    assert not repo.bank_documents() and not repo.imports()
    repo.close()


def test_manual_document_import_and_restart(tmp_path):
    path = tmp_path / 'Steuerbescheinigung.pdf'
    path.write_bytes(PDF)
    batch = local_document_batch(path, 'ING')
    repo = PortfolioRepository(tmp_path / 'db.sqlite')
    repo.commit_batches([batch])
    repo.close()
    repo = PortfolioRepository(tmp_path / 'db.sqlite')
    stored = repo.bank_documents()[0]
    assert stored['title'] == path.name and stored['date'] == ''
    assert repo.bank_document_content(stored['id']) == PDF
    repo.close()


def test_fetch_ing_history_options_and_date_validation(tmp_path):
    fake = FakeClient()
    info = fake.get_information()
    info['accounts'][0]['supported_operations'][Op.GET_TRANSACTIONS] = True
    fake.get_information = lambda: info
    fake.get_transactions = Mock(return_value=[transaction()])
    batches = fetch_ing('user', 'secret', 'id', source_root=tmp_path,
        history_start=date(2026, 9, 1), history_end=date(2026, 9, 24), fetch_documents=True,
        today=date(2026, 9, 24), client_factory=lambda *args: fake)
    assert sum(len(b.transactions) for b in batches) == 1
    assert any('nicht freigegeben' in ' '.join(b.errors) for b in batches)
    factory = Mock()
    with pytest.raises(BankingError):
        fetch_ing('user', 'secret', 'id', source_root=tmp_path,
            history_start=date(2026, 10, 1), today=date(2026, 9, 24), client_factory=factory)
    factory.assert_not_called()


def test_archive_widget_filters_and_unknown_document_dates(tmp_path):
    from PySide6.QtWidgets import QApplication
    from portman.bank_archive import BankArchiveWidget
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'db.sqlite')
    batch = ImportBatch('bank.bank', 'hash', transactions=parse_transactions([transaction()], 'ING', date(2026, 9, 1), date(2026, 9, 30)),
        documents=[document_from_bytes('ING', 'doc', 'Kontoauszug', '', PDF)])
    repo.commit_batches([batch])
    widget = BankArchiveWidget(repo, lambda: None)
    assert widget.bookings.rowCount() == 1 and widget.documents.rowCount() == 1
    widget.search.setText('Testhandel')
    assert widget.bookings.rowCount() == 1 and widget.documents.rowCount() == 0
    widget.search.setText('Kontoauszug')
    assert widget.bookings.rowCount() == 0 and widget.documents.rowCount() == 1
    widget.close()
    repo.close()


def test_successful_empty_history_advances_only_after_import(tmp_path):
    from portman.bank_history_range import last_history_date
    client = Mock()
    client.get_transactions.return_value = []
    repo = PortfolioRepository(tmp_path / 'empty.sqlite')
    try:
        for end in (date(2026, 9, 23), date(2026, 9, 24)):
            batches = fetch_history(client, SimpleNamespace(iban='DETEST'), {Op.GET_TRANSACTIONS: True},
                'ING Konto', 'ing-konto.bank', lambda value: value, lambda message: None,
                start=last_history_date(repo, 'ING'), end=end, documents=False)
            assert not batches[0].errors
            assert last_history_date(repo, 'ING') != end
            result = repo.commit_batches(batches)[0]
            assert result['status'] == 'imported'
            assert last_history_date(repo, 'ING') == end
        repo.undo_import(result['id'])
        assert last_history_date(repo, 'ING') == date(2026, 9, 23)
    finally:
        repo.close()


def test_old_statements_are_not_downloaded():
    client = Mock()
    client.get_statements.return_value = [SimpleNamespace(year=2025, statement_number=12,
        collection_possible=True, date_created=date(2025, 12, 31))]
    history(client, {Op.GET_STATEMENT: True})
    client.get_statement.assert_not_called()
