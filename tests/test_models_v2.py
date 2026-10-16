from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock, patch

from portfolio_v5.models import (AccountInfo, AccountStatement, BankTransaction, CorporateEvent,
    CostItem, CostReport, FeeItem, ImportBatch, Kind, SecurityInfo, TaxEvent, TaxItem,
    check_transaction, number)
from portman.import_v09 import decode_batch
from portman.repository_v09 import RepositoryV09


def test_withholding_metadata_is_promoted_and_rate_is_calculated():
    documented = BankTransaction('Cash', 'tax-1', '2026-10-11', Kind.DIVIDEND, '85', 'EUR',
        security='US0378331005', gross_amount='100', document_reference='REF-42',
        tax_items=[TaxItem('quellensteuer', '15', rate='15')])
    assert documented.withholding_tax == '15.00'
    assert documented.withholding_tax_rate == '15'
    assert documented.withholding_country == 'US'
    assert documented.tax_rate == '15.00'
    assert documented.transaction_reference == 'REF-42'
    assert documented.field_sources['withholding_tax_rate'] == 'Steuersatz im Beleg'
    assert documented.field_sources['withholding_country'] == 'Aus ISIN-Ländercode abgeleitet'

    calculated = BankTransaction('Cash', 'tax-2', '2026-10-11', Kind.DIVIDEND, '80', 'EUR',
        security='CA135087D457', gross_amount='100', withholding_tax='20')
    assert calculated.withholding_tax_rate == '20.00'
    assert calculated.withholding_country == 'CA'
    assert calculated.field_sources['withholding_tax_rate'].startswith('Berechnet:')


def test_vorabpauschale_is_extracted_as_tax_basis_not_tax_paid():
    tx = BankTransaction('Cash', 'advance-tax', '2026-01-15', Kind.BANK_BOOKING, '-7.91', 'EUR',
        security='DE000A0F5UH1', purpose='Abrechnung Vorabpauschale 31,64 EUR; Kapitalertragsteuer 7,91 EUR')
    assert tx.advance_tax_base == '31.64'
    assert tx.advance_tax_currency == 'EUR'
    assert tx.taxes is None
    assert tx.field_sources['advance_tax_base'] == 'Vorabpauschale im Importbeleg'


def test_extended_model_is_compatible_and_decodes_nested_values():
    tx = BankTransaction('Cash', 'tx', '2026-10-11', Kind.DIVIDEND, '8.50', 'EUR',
        gross_amount='10', tax_items=[TaxItem('kapst', '1')], fee_items=[FeeItem('fee', '.5')],
        security_ref='DE0000000001', review_state='geprueft', performance_depot_key='depot')
    batch = ImportBatch('online', 'hash', transactions=[tx],
        securities=[SecurityInfo('DE0000000001', name='Test')],
        accounts=[AccountInfo('cash', iban='DE89370400440532013000')],
        statements=[AccountStatement('cash', closing_balance='8.50')],
        tax_events=[TaxEvent('tax', 'cash', 'steueroptimierung', '2026-10-11')],
        cost_reports=[CostReport('cost', 'depot', '2026-01-01', '2026-12-31', items=[CostItem('DE0000000001', total='1')])],
        events=[CorporateEvent('event', 'depot', 'hauptversammlung')])
    decoded = decode_batch(asdict(batch))
    assert isinstance(decoded.transactions[0].tax_items[0], TaxItem)
    assert isinstance(decoded.cost_reports[0].items[0], CostItem)
    assert decoded.transactions[0].performance_depot_key == 'depot'
    assert decoded.transactions[0].taxes == '1.00'
    assert decoded.transactions[0].fees == '0.50'
    assert check_transaction(decoded.transactions[0]) == []
    assert number('0,0000005') == '0.0000005'


def test_extended_import_records_are_persisted_and_undoable(tmp_path):
    repo = RepositoryV09(tmp_path / 'model.sqlite', backups=False)
    try:
        batch = ImportBatch('model', 'hash', securities=[SecurityInfo('TEST', name='Test')],
                            statements=[AccountStatement('Cash', closing_balance='100')])
        result = repo.commit_batches([batch])[0]
        records = repo.model_records(result['id'])
        assert result['model_records'] == 2
        assert {row['kind'] for row in records} == {'securities', 'statements'}
        repo.undo_import(result['id'])
        assert repo.model_records(result['id']) == []
    finally:
        repo.close()


def test_online_sync_uses_modeless_fetch_and_background_atomic_commit(tmp_path):
    from portman.gui.online_sync import OnlineSyncMixin
    repository = SimpleNamespace(store=SimpleNamespace(path=tmp_path / 'portfolio.sqlite'))
    window = SimpleNamespace(repository=repository, status_bar=Mock(), market_widget=Mock(),
        banking_directory=lambda: tmp_path, refresh_scope_choices=Mock(), reload_portfolio=Mock(), job_center=Mock())
    window.sync_online_accounts = OnlineSyncMixin.sync_online_accounts.__get__(window)
    window._online_sync_fetched = OnlineSyncMixin._online_sync_fetched.__get__(window)
    window._online_sync_closed = OnlineSyncMixin._online_sync_closed.__get__(window)
    window._online_sync_saved = OnlineSyncMixin._online_sync_saved.__get__(window)
    window._online_sync_complete = OnlineSyncMixin._online_sync_complete.__get__(window)
    accepted = []
    dialog = Mock(); dialog.results = [('ING', ['raw'])]
    dialog.accepted.connect.side_effect = accepted.append
    dialog.status_message.connect.side_effect = lambda callback: None
    dialog.log.toPlainText.return_value = ''; dialog.has_errors = False
    result = {'status': 'imported', 'errors': []}

    class Signal:
        def __init__(self): self.callbacks = []
        def connect(self, callback): self.callbacks.append(callback)
        def emit(self, value=None):
            for callback in self.callbacks:
                callback() if value is None else callback(value)

    class Job:
        def __init__(self, path, function, parent):
            self.path, self.function = path, function
            self.result, self.failed, self.finished = Signal(), Signal(), Signal()
        def start(self):
            self.result.emit([result])
            self.finished.emit()
        def deleteLater(self): pass

    with patch('portman.bank_sync_dialog.BankSyncDialog', return_value=dialog), \
         patch('portman.automatic_bank_import.prepare_known_batches', return_value=(['prepared'], [])), \
         patch('portman.import_jobs.DatabaseJob', Job), \
         patch('portman.import_jobs.commit_atomic'):
        window.sync_online_accounts()
        dialog.show.assert_not_called()
        dialog.exec.assert_not_called()
        accepted[0]()
    window.job_center.register.assert_called_once()
    assert window.job_center.register.call_args.args[1] == 'Online-Daten werden gespeichert'
    window.refresh_scope_choices.assert_called_once()
    window.reload_portfolio.assert_called_once()
    window.market_widget.start.assert_called_once_with(incremental=True)
