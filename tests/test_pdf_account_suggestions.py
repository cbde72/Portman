import os

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from portfolio_v5.models import ImportBatch, BankDocument
from portfolio_v5.import_accounts import rule_scope
from portman.repository import PortfolioRepository

IBAN = 'DE89370400440532013000'


@pytest.fixture
def repo(tmp_path):
    repository = PortfolioRepository(tmp_path / 'accounts.sqlite')
    yield repository
    repository.close()


def batch(*sources):
    return ImportBatch('statement.pdf', 'hash', source_sheet='PDF', documents=[
        BankDocument(source, str(i), 'statement.pdf', '', '') for i, source in enumerate(sources)])


@pytest.mark.parametrize('source,details', [
    ('IBAN ' + IBAN, {'iban': 'de89 3704 0044 0532 0130 00'}),
    ('IBAN ' + IBAN, {'number': '532013000'}),
    ('Konto 532013000', {'iban': IBAN}),
    ('Konto 00532013000', {'number': '532 013 000'}),
    ('Depot 12345678', {'number': '1234-5678'}),
])
def test_identifier_preselection(repo, source, details):
    repo.save_account('Mein Konto', details)
    suggestion = repo.import_account_suggestions(batch(source))[0]
    assert suggestion['target_key'] == 'mein konto'
    assert 'Kontodetails' in suggestion['reason']
    assert not repo.imports()


def test_ambiguity_and_inactive_accounts(repo):
    repo.save_account('A', {'number': '12345678'})
    repo.save_account('B', {'number': '12345678'})
    b = batch('Konto 12345678')
    suggestion = repo.import_account_suggestions(b)[0]
    assert suggestion['target_key'] is None
    assert 'mehreren' in suggestion['reason']
    repo.set_account_active('B', False)
    assert repo.import_account_suggestions(b)[0]['target_key'] == 'a'
    repo.set_account_active('A', False)
    assert repo.import_account_suggestions(b)[0]['target_key'] is None


def test_exact_iban_beats_number_and_conflicting_iban_is_rejected(repo):
    repo.save_account('Exakt', {'iban': IBAN})
    repo.save_account('Nur Nummer', {'number': '532013000'})
    assert repo.import_account_suggestions(batch('IBAN ' + IBAN))[0]['target_key'] == 'exakt'
    repo.set_account_active('Exakt', False)
    repo.save_account('Nur Nummer', {'number': '532013000', 'iban': 'DE81305200375884205500'}, original='Nur Nummer')
    assert repo.import_account_suggestions(batch('IBAN ' + IBAN))[0]['target_key'] is None


def test_no_partial_number_or_invalid_iban_suffix_match(repo):
    repo.save_account('A', {'number': '532013000'})
    for source in ['Konto 32013000', 'IBAN DE00370400440532013000']:
        assert repo.import_account_suggestions(batch(source))[0]['target_key'] is None


def test_saved_rule_has_priority(repo):
    repo.save_account('A', {'number': '12345678'})
    repo.save_account('B', {})
    b = batch('Konto 12345678')
    with repo.db:
        repo.db.execute('INSERT INTO import_account_rules VALUES(?,?,?)', (rule_scope(b.path), 'konto 12345678', 'b'))
    assert repo.import_account_suggestions(b)[0]['target_key'] == 'b'


@pytest.mark.parametrize('source', ['Konto 5884205500', 'IBAN DE81305200375884205500'])
def test_number_in_account_name(repo, source):
    repo.save_account('Renault Tagesgeld 5884205500', {})
    suggestion = repo.import_account_suggestions(batch(source))[0]
    assert suggestion['target_key'] == 'renault tagesgeld 5884205500'
    assert suggestion['reason'] == 'Kontonummer im Kontonamen gefunden'


def test_name_matches_only_whole_numbers_and_active_accounts(repo):
    repo.save_account('Andere 15884205500', {})
    repo.save_account('Andere 58842055001', {})
    repo.save_account('Geloescht 5884205500', {})
    repo.set_account_active('Geloescht 5884205500', False)
    assert repo.import_account_suggestions(batch('Konto 5884205500'))[0]['target_key'] is None


def test_detail_and_name_matches_on_different_accounts_are_ambiguous(repo):
    repo.save_account('Tagesgeld', {'number': '5884205500'})
    repo.save_account('Renault 5884205500', {})
    suggestion = repo.import_account_suggestions(batch('Konto 5884205500'))[0]
    assert suggestion['target_key'] is None
    assert 'mehreren' in suggestion['reason']


def test_number_in_name_preselected_in_dialog(repo):
    from PySide6.QtWidgets import QApplication
    from portman.import_preview import ImportPreviewDialog
    QApplication.instance() or QApplication([])
    repo.save_account('Renault 5884205500', {})
    dialog = ImportPreviewDialog(repo, [batch('Konto 5884205500')])
    assert dialog.mapping_rows[0][2].currentData() == 'renault 5884205500'
    dialog.reject()
    assert not repo.imports()
    dialog.close()


def test_multiple_sources_selected_in_dialog_and_cancel_is_read_only(repo):
    from PySide6.QtWidgets import QApplication
    from portman.import_preview import ImportPreviewDialog
    QApplication.instance() or QApplication([])
    repo.save_account('Tagesgeld', {'iban': IBAN})
    repo.save_account('Depot', {'number': '12345678'})
    dialog = ImportPreviewDialog(repo, [batch('IBAN ' + IBAN, 'Depot 12345678')])
    assert {source['name']: combo.currentData() for _, source, combo, _ in dialog.mapping_rows} == {
        'IBAN ' + IBAN: 'tagesgeld', 'Depot 12345678': 'depot'}
    assert dialog.selected_batches()[0].account_assignments == {'iban ' + IBAN.lower(): 'tagesgeld', 'depot 12345678': 'depot'}
    dialog.reject()
    assert not repo.imports()
    assert not repo.import_rules()
    dialog.close()
