import pytest

from portfolio_v5.models import ImportBatch, TaxDetailRecord, TaxEvent
from portman.repository_v09 import RepositoryV09


def event(identifier='tax-1', account='Depot A', taxable='10.00', related=''):
    return TaxEvent(identifier, account, 'dividende_inland', '2026-04-01',
                    tax_year='2026', security_ref='DE000TEST001', taxable_income=taxable,
                    related_transaction_id=related)


def detail(identifier='detail-1', account='Depot A', taxable='10,00', **links):
    return TaxDetailRecord(identifier, 'Testbank', account, 'test-csv',
                           {'Steuerjahr': '2026', 'Steuerpflichtig': taxable}, **links)


@pytest.fixture
def repo(tmp_path):
    repository = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    repository.save_account('Depot A', {'kind': 'Depot', 'institution': 'Testbank'})
    repository.save_account('Depot B', {'kind': 'Depot', 'institution': 'Andere Bank'})
    yield repository
    repository.close()


def test_identical_tax_event_id_is_idempotent(repo):
    first = ImportBatch('tax.pdf', 'same-source', tax_events=[event(related='cash-old')])
    duplicate = ImportBatch('tax.pdf', 'same-source', tax_events=[event(related='cash-new')])
    assert repo.store.import_batch(first)['status'] == 'imported'
    assert repo.store.import_batch(duplicate)['status'] == 'duplicate'
    assert len(repo.tax_events()) == 1


def test_conflicting_tax_event_id_is_rejected_globally(repo):
    repo.store.import_batch(ImportBatch('first.pdf', 'first', tax_events=[event()]))
    with pytest.raises(ValueError, match='bereits mit abweichenden Daten'):
        repo.store.import_batch(ImportBatch('changed.pdf', 'changed', tax_events=[event(taxable='11.00')]))
    with pytest.raises(ValueError, match='bereits mit abweichenden Daten'):
        repo.store.import_batch(ImportBatch('other-bank.pdf', 'other', tax_events=[event(account='Depot B')]))
    assert len(repo.tax_events()) == 1


def test_duplicate_tax_event_ids_inside_reimport_are_rejected(repo):
    repo.store.import_batch(ImportBatch('first.pdf', 'same-source', tax_events=[event()]))
    duplicate_rows = ImportBatch('first.pdf', 'same-source', tax_events=[event(), event()])
    with pytest.raises(ValueError, match='eindeutige externe ID'):
        repo.store.import_batch(duplicate_rows)


def test_identical_tax_detail_id_is_idempotent_despite_new_link_state(repo):
    first = ImportBatch('tax.csv', 'same-source', tax_details=[detail(match_status='unmatched')])
    duplicate = ImportBatch('tax.csv', 'same-source', tax_details=[detail(
        linked_tax_event_id='event-1', match_status='matched')])
    assert repo.store.import_batch(first)['status'] == 'imported'
    assert repo.store.import_batch(duplicate)['status'] == 'duplicate'
    assert len(repo.tax_detail_records()) == 1


def test_conflicting_tax_detail_id_is_rejected_globally(repo):
    repo.store.import_batch(ImportBatch('first.csv', 'first', tax_details=[detail()]))
    with pytest.raises(ValueError, match='bereits mit abweichenden Daten'):
        repo.store.import_batch(ImportBatch('changed.csv', 'changed', tax_details=[detail(taxable='12,00')]))
    with pytest.raises(ValueError, match='bereits mit abweichenden Daten'):
        repo.store.import_batch(ImportBatch('other.csv', 'other', tax_details=[detail(account='Depot B')]))
    assert len(repo.tax_detail_records()) == 1
