from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest

from portfolio_v5.models import (AccountInfo, AccountStatement, BankTransaction, CorporateEvent,
    CostItem, CostReport, FeeItem, ImportBatch, Kind, SecurityInfo, Snapshot, TaxEvent, TaxItem,
    Transaction, check_transaction, number, parse_decimal, parse_money, parse_quantity)
from portman.import_v09 import decode_batch
from portman.repository_v09 import RepositoryV09


def test_withholding_metadata_is_promoted_and_rate_is_calculated():
    documented = BankTransaction('Cash', 'tax-1', '2026-10-11', Kind.DIVIDEND, '85', 'EUR',
        security='US0378331005', gross_amount='100', document_reference='REF-42',
        tax_items=[TaxItem('quellensteuer', '15', rate='15', country='US')])
    assert documented.withholding_tax == '15.00'
    assert documented.withholding_tax_rate == '15'
    assert documented.withholding_country == 'US'
    assert documented.tax_rate == '15.00'
    assert documented.transaction_reference == 'REF-42'
    assert documented.field_sources['withholding_tax_rate'] == 'Steuersatz im Beleg'
    assert documented.field_sources['withholding_country'] == 'Quellenstaat im Beleg'

    calculated = BankTransaction('Cash', 'tax-2', '2026-10-11', Kind.DIVIDEND, '80', 'EUR',
        security='CA135087D457', gross_amount='100', withholding_tax='20')
    assert calculated.withholding_tax_rate == '20.00'
    assert calculated.withholding_country == ''
    assert calculated.field_sources['withholding_tax_rate'].startswith('Berechnet:')


def test_vorabpauschale_is_not_inferred_from_unstructured_booking_text():
    unstructured = BankTransaction('Cash', 'advance-text', '2026-01-15', Kind.BANK_BOOKING, '-7.91', 'EUR',
        security='DE000A0F5UH1', purpose='Abrechnung Vorabpauschale 31,64 EUR; Kapitalertragsteuer 7,91 EUR')
    assert unstructured.advance_tax_base is None
    assert unstructured.advance_tax_currency == ''

    tx = BankTransaction('Cash', 'advance-structured', '2026-01-15', Kind.BANK_BOOKING, '-7.91', 'EUR',
        security='DE000A0F5UH1', purpose='Abrechnung Vorabpauschale',
        advance_tax_base='31.64', advance_tax_currency='EUR',
        field_sources={'advance_tax_base': 'comdirect.vorabpauschale:Steuermitteilung'})
    assert tx.advance_tax_base == '31.64'
    assert tx.advance_tax_currency == 'EUR'
    assert tx.taxes is None
    assert tx.field_sources['advance_tax_base'] == 'comdirect.vorabpauschale:Steuermitteilung'

    incomplete = BankTransaction('Cash', 'advance-incomplete', '2026-01-15', Kind.BANK_BOOKING,
        '0', 'EUR', advance_tax_base='31.64')
    assert any('explizite Währung' in problem for problem in check_transaction(incomplete))


def test_gross_net_validation_covers_trades_refunds_and_reversals():
    cases = [
        Transaction('Depot', 'buy', '2026-01-01', Kind.BUY, '-112', 'EUR',
                    gross_amount='100', fees='2', taxes='10'),
        Transaction('Depot', 'sell', '2026-01-01', Kind.SELL, '88', 'EUR',
                    gross_amount='100', fees='2', taxes='10'),
        Transaction('Depot', 'refund', '2026-01-01', Kind.TAX_REFUND, '10', 'EUR',
                    gross_amount='10'),
        Transaction('Depot', 'reversal', '2026-01-01', Kind.DIVIDEND, '-85', 'EUR',
                    gross_amount='100', taxes='15', is_reversal=True),
        Transaction('Depot', 'signed-reversal', '2026-01-01', Kind.DIVIDEND, '-85', 'EUR',
                    gross_amount='-100', taxes='-15', is_reversal=True),
        Transaction('Depot', 'generic-reversal', '2026-01-01', Kind.REVERSAL, '112', 'EUR',
                    gross_amount='100', fees='2', taxes='10'),
        Transaction('Depot', 'tax-refund-components', '2026-01-01', Kind.TAX_REFUND, '10', 'EUR',
                    gross_amount='0', taxes='-10'),
    ]
    assert all(check_transaction(tx) == [] for tx in cases)
    wrong_buy = Transaction('Depot', 'wrong', '2026-01-01', Kind.BUY, '-102', 'EUR',
                            gross_amount='100', fees='2', taxes='10')
    assert any('Brutto/Netto' in problem for problem in check_transaction(wrong_buy))


def test_dates_and_exchange_rates_are_strictly_validated():
    invalid_date = Transaction('Depot', 'date', '2026-02-30', Kind.SELL, '100', 'EUR')
    assert any('gültiges ISO-Datum' in problem for problem in check_transaction(invalid_date))
    for rate in ('0', '-1', 'NaN', 'Infinity'):
        tx = Transaction('Depot', 'fx-' + rate, '2026-01-01', Kind.DIVIDEND, '90', 'EUR',
                         gross_amount='90', original_amount='100', original_currency='USD', fx_rate=rate)
        assert check_transaction(tx)
    ambiguous = Transaction('Depot', 'ambiguous', '2026-01-01', Kind.DIVIDEND, '90', 'EUR',
                            gross_amount='90', original_amount='100', fx_rate='1.111111')
    assert any('ohne Fremdwährung' in problem for problem in check_transaction(ambiguous))


def test_validation_issues_have_stable_codes_and_severities():
    invalid = Transaction('Depot', 'coded', '2026-02-30', Kind.BUY, 'NaN', 'EUR')
    issues = check_transaction(invalid)
    by_code = {issue.code: issue for issue in issues}
    assert by_code['NUMBER_INVALID'].severity == 'error'
    assert by_code['NUMBER_INVALID'].field == 'amount'
    assert by_code['DATE_INVALID'].severity == 'warning'
    assert isinstance(by_code['NUMBER_INVALID'], str)


def test_import_batch_reports_complete_partial_and_invalid_quality():
    assert ImportBatch('complete', '1').quality_status == 'valid'
    partial = ImportBatch('partial', '2', snapshots=[
        Snapshot('Depot', '2026-01', '2026-01-01', 'Test', complete=False)])
    assert partial.quality_status == 'valid'
    assert partial.completeness_status == 'partial'
    warning = ImportBatch('warning', '3', snapshots=[
        Snapshot('Depot', '2026-01', '2026-01-01', 'Test', complete=True)], warnings=['prüfen'])
    assert warning.quality_status == 'review'
    assert warning.completeness_status == 'complete'
    assert ImportBatch('invalid', '4', errors=['kaputt']).quality_status == 'invalid'


def test_exchange_rate_preserves_legacy_division_and_supports_explicit_pair():
    quote = Transaction('Depot', 'quote', '2026-01-01', Kind.DIVIDEND, '80', 'EUR',
        gross_amount='80', original_amount='100', original_currency='USD', fx_rate='1.25')
    inverse = Transaction('Depot', 'inverse', '2026-01-01', Kind.DIVIDEND, '80', 'EUR',
        gross_amount='80', original_amount='100', original_currency='USD', fx_rate='0.8',
        fx_from_currency='USD', fx_to_currency='EUR')
    assert check_transaction(quote) == []
    assert check_transaction(inverse) == []

    mismatch = Transaction('Depot', 'mismatch', '2026-01-01', Kind.DIVIDEND, '80', 'EUR',
        gross_amount='80', original_amount='100', original_currency='USD', fx_rate='0.9',
        fx_from_currency='USD', fx_to_currency='EUR')
    assert any('Originalbetrag × Kurs' in problem for problem in check_transaction(mismatch))

    incomplete = Transaction('Depot', 'incomplete', '2026-01-01', Kind.DIVIDEND, '80', 'EUR',
        gross_amount='80', original_amount='100', original_currency='USD', fx_rate='0.8',
        fx_from_currency='USD')
    assert any('Ausgangs- und Zielwährung' in problem for problem in check_transaction(incomplete))

    contradictory = Transaction('Depot', 'contradictory', '2026-01-01', Kind.DIVIDEND, '80', 'EUR',
        gross_amount='80', original_amount='100', original_currency='USD', fx_rate='0.8',
        fx_from_currency='GBP', fx_to_currency='CHF')
    contradictory_problems = check_transaction(contradictory)
    assert any('Ausgangswährung widerspricht' in problem for problem in contradictory_problems)
    assert any('Zielwährung widerspricht' in problem for problem in contradictory_problems)


def test_explicit_fx_pair_round_trips_without_changing_positional_constructor():
    tx = BankTransaction('Cash', 'fx-roundtrip', '2026-01-01', Kind.DIVIDEND, '92', 'EUR',
        gross_amount='92', original_amount='100', original_currency='USD', fx_rate='0.92',
        fx_from_currency='USD', fx_to_currency='EUR')
    decoded = decode_batch(asdict(ImportBatch('fx.json', 'hash', transactions=[tx]))).transactions[0]
    assert decoded.fx_from_currency == 'USD'
    assert decoded.fx_to_currency == 'EUR'
    assert check_transaction(decoded) == []


def test_foreign_currency_trade_price_uses_documented_exchange_rate():
    tx = Transaction('Depot', 'fnz-buy', '2024-01-01', Kind.BUY, '-161.00', 'EUR',
        quantity='2', price='100', price_currency='USD', gross_amount='160',
        fees='1', fx_rate='1.25')
    assert check_transaction(tx) == []

    missing_rate = Transaction('Depot', 'fnz-missing-fx', '2024-01-01', Kind.BUY,
        '-161.00', 'EUR', quantity='2', price='100', price_currency='USD',
        gross_amount='160', fees='1')
    issues = check_transaction(missing_rate)
    assert any(issue.code == 'FX_RATE_MISSING' for issue in issues)
    assert not any(issue.code == 'PRICE_QUANTITY_MISMATCH' for issue in issues)


def test_tax_and_fee_components_must_match_aggregates_and_cash_direction():
    inconsistent = Transaction('Depot', 'components', '2026-01-01', Kind.DIVIDEND, '84', 'EUR',
        gross_amount='100', taxes='15', fees='1', withholding_tax='16', solidarity_tax='16',
        tax_items=[TaxItem('kapst', '14')], fee_items=[FeeItem('order', '2')])
    problems = check_transaction(inconsistent)
    assert any('Steuersumme widersprüchlich' in problem for problem in problems)
    assert any('Gebührensumme widersprüchlich' in problem for problem in problems)
    assert any('Quellensteuer übersteigt' in problem for problem in problems)
    assert any('Solidaritätszuschlag übersteigt' in problem for problem in problems)
    assert any('Differenz 1.00' in problem and 'unvollständig' in problem for problem in problems)
    assert any('Differenz -1.00' in problem and 'unvollständig' in problem for problem in problems)

    assert any('negativer Geldbetrag' in problem for problem in check_transaction(
        Transaction('Cash', 'tax', '2026-01-01', Kind.TAX, '1', 'EUR')))
    assert any('positiver Geldbetrag' in problem for problem in check_transaction(
        Transaction('Cash', 'refund', '2026-01-01', Kind.TAX_REFUND, '-1', 'EUR')))
    assert any('negativer Geldbetrag' in problem for problem in check_transaction(
        Transaction('Cash', 'fee', '2026-01-01', Kind.FEE, '1', 'EUR')))


def test_missing_component_lists_remain_unknown_instead_of_zero():
    tx = Transaction('Depot', 'aggregate-only', '2026-01-01', Kind.DIVIDEND, '75', 'EUR',
        gross_amount='100', taxes='25', fees='0')
    assert tx.tax_items == []
    assert not any('Steuersumme widersprüchlich' in problem for problem in check_transaction(tx))

    detailed = Transaction('Depot', 'partial-details', '2026-01-01', Kind.DIVIDEND, '75', 'EUR',
        gross_amount='100', taxes='25',
        tax_items=[TaxItem('kapitalertragsteuer', '20'), TaxItem('solidaritaetszuschlag', '1.10')])
    assert detailed.taxes == '25'
    assert detailed._component_consistency_problems == [
        'Steuersumme widersprüchlich: Gesamt 25.00, dokumentierte Einzelpositionen 21.10, '
        'Differenz 3.90; Einzelpositionen können unvollständig oder die Gesamtsumme kann falsch sein']
    assert detailed.tax_items[0].amount == '20'


def test_nested_component_numbers_are_validated_without_reinterpretation():
    tx = Transaction('Depot', 'nested', '2026-01-01', Kind.DIVIDEND, '10', 'EUR')
    # Also cover legacy/deserialized mappings, not only current dataclass items.
    tx.tax_items = [{'kind': 'kapst', 'amount': '1,23'}]
    tx.fee_items = [{'kind': 'fee', 'amount': 'NaN'}]
    problems = check_transaction(tx)
    assert any('tax_items[1].amount' in problem for problem in problems)
    assert any('fee_items[1].amount' in problem for problem in problems)


def test_ambiguous_number_requires_an_explicit_source_format():
    for value in ('1.234', '1,234', '-12.345', '-12,345'):
        with pytest.raises(ValueError, match='Uneindeutiges Zahlenformat'):
            number(value)
    assert number('1.234', number_format='de') == '1234'
    assert number('1,234', number_format='de') == '1.234'
    assert number('1.234', number_format='en') == '1.234'
    assert number('1,234', number_format='en') == '1234'
    assert number('1.234', number_format='canonical') == '1.234'


def test_number_auto_mode_only_accepts_unambiguous_text():
    assert number('1234') == '1234'
    assert number('1234,56') == '1234.56'
    assert number('1234.56') == '1234.56'
    assert number('1.234,56') == '1234.56'
    assert number('1,234.56') == '1234.56'
    with pytest.raises(ValueError, match='Tausendergruppen'):
        number('12.34.567', number_format='de')


def test_domain_specific_number_parsers_require_source_context():
    assert parse_decimal('1.234', locale='de_DE') == '1234'
    assert parse_decimal('1.234', locale='en_US') == '1.234'
    with pytest.raises(ValueError, match='Uneindeutiges Zahlenformat'):
        parse_decimal('1.234', locale='auto')

    assert parse_money('1.234,567', 'KWD', locale='de_DE') == '1234.567'
    assert parse_money('1234,5', 'JPY', locale='de_DE') == '1234'
    assert parse_money('0,123456789', 'BTC', locale='de_DE') == '0.12345679'

    assert parse_quantity('0,123456789012', locale='de_DE') == '0.123456789012'
    with pytest.raises(ValueError, match='maximal 12'):
        parse_quantity('0,1234567890123', locale='de_DE')


def test_advance_lump_sum_is_informational_not_cash_or_paid_tax():
    valid = BankTransaction('Cash', 'advance', '2026-01-01', Kind.ADVANCE_LUMP_SUM,
                            '0', 'EUR', advance_tax_base='31.64', advance_tax_currency='EUR', affects_cash=False)
    assert check_transaction(valid) == []
    invalid = BankTransaction('Cash', 'advance-paid', '2026-01-01', Kind.ADVANCE_LUMP_SUM,
                              '-7.91', 'EUR', taxes='7.91', advance_tax_base='31.64',
                              advance_tax_currency='EUR')
    problems = check_transaction(invalid)
    assert any('keine zusätzliche Geldbuchung' in problem for problem in problems)
    assert any('nicht als tatsächlich gezahlte Steuer' in problem for problem in problems)
    assert any('Geldbestand nicht verändern' in problem for problem in problems)


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
