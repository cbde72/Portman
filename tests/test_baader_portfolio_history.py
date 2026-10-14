import os
from decimal import Decimal
import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from portfolio_v5.models import ImportBatch, Position, Snapshot, BankTransaction
from portfolio_v5.baader_pdf import parse_baader_portfolio
from portman.repository_v09 import RepositoryV09

ACCOUNT = 'Baader Depot 1234567890'
KEY = 'DE000BASF111'
QUARTER = '''Baader Bank AG
Depot-Nr.: 1234567890
Quartalsaufstellung
MIFID II per 30.06.2026
Aktien und aktienähnliche
Stück 10 WKN: BASF11 EUR 50,000 500,00 EUR
ISIN: DE000BASF111
BASF SE
Namens-Aktien
Stück 2 Offene Lieferung CA b.a.w.
Depotwert 500,00 EUR
'''
TRADE = '''Baader Bank AG
Depot-Nr.: 1234567890
Referenz-Nr.: 12345
Wertpapierabrechnung: Kauf
ISIN: DE000BASF111 WKN: BASF11
STK 2  BASF SE  EUR 60,00
Kurswert EUR 120,00
Mindermengenzuschlag Finanzen.net EUR 1,00
Zu Lasten Konto 1234567005 Valuta: 03.07.2026 EUR 121,00
Details zur Ausführung:
Handelsdatum Handelsuhrzeit
01.07.2026 10:00:00
Verwahrart: Girosammelverwahrung
'''


def parsed(text):
    batch = ImportBatch('test.pdf', 'hash', source_sheet='PDF')
    return parse_baader_portfolio(batch, [text], b'%PDF-test')


def test_quarter_checks_total_and_retains_statement_date():
    b = parsed(QUARTER)
    assert b.snapshots[0].as_of == '2026-06-30'
    assert len(b.snapshots[0].positions) == 1
    assert b.snapshots[0].positions[0].quantity == '10'
    assert b.snapshots[0].complete
    with pytest.raises(ValueError, match='Positionssumme'):
        parsed(QUARTER.replace('Depotwert 500,00', 'Depotwert 501,00'))
    with pytest.raises(ValueError, match='Bestandszeile'):
        parsed(QUARTER.replace('Offene Lieferung CA', 'Unbekannt'))


def test_trade_uses_execution_day_net_amount_and_fees():
    tx = parsed(TRADE).transactions[0]
    assert (tx.date, tx.value_date, tx.kind, tx.quantity, tx.amount, tx.fees) == (
        '2026-07-01', '2026-07-03', 'BUY', '2', '121.00', '1.00')
    assert not tx.affects_cash
    assert 'Nominale STK 2' in tx.booking_text and 'Kurswert EUR 120.00' in tx.booking_text
    split_header = TRADE.replace('Handelsdatum Handelsuhrzeit\n01.07.2026 10:00:00',
        'Handels- Handels-\ndatum uhrzeit\nSTK 2 EUR 60,00 GETTEX 01.07.2026 10:00:00')
    assert parsed(split_header).transactions[0].date == '2026-07-01'
    with pytest.raises(ValueError, match='Gebühren'):
        parsed(TRADE.replace('EUR 121,00', 'EUR 122,00'))


def test_zero_cash_sale_is_still_a_security_movement():
    text = TRADE.replace('Kauf', 'Verkauf').replace('Zu Lasten Konto 1234567005', 'Total')
    text = text.replace('EUR 1,00', 'EUR 120,00 -').replace('EUR 121,00', 'EUR 0,00')
    tx = parsed(text).transactions[0]
    assert tx.kind == 'SELL' and Decimal(tx.amount) == 0 and tx.quantity == '2'


def test_holdings_replay_stops_at_next_snapshot_and_undo(tmp_path):
    repo = RepositoryV09(tmp_path / 'test.sqlite', backups=False)
    try:
        base = parsed(QUARTER)
        base.path = 'quarter'; base.documents = []
        trade = parsed(TRADE)
        trade.path = 'trade'; trade.file_hash = 'trade'; trade.documents = []
        repo.commit_batches([base, trade])
        assert repo.holdings('2026-06-30')[0]['quantity'] == '10'
        p = repo.holdings('2026-07-02')[0]
        assert p['quantity'] == '12' and p['value'] == '500.00'
        assert p['date_basis'] == 'transactions'
        assert p['cost'] is None and p['known_partial_cost'] == '121.00'
        assert repo.account_overview()[0]['balance'] is None
        assert repo.commit_batches([trade])[0]['status'] == 'duplicate'
        assert repo.holdings()[0]['quantity'] == '12'
        online = ImportBatch('online', 'online', snapshots=[Snapshot(ACCOUNT, '2026-07', '2026-07-02',
            'Online Baader', [Position(KEY, 'BASF', isin='DE000BASF111', quantity='12', value='730')])])
        result = repo.commit_batches([online])[0]
        assert repo.holdings()[0]['quantity'] == '12'
        assert repo.holdings()[0]['value'] == '730'
        repo.undo_import(result['id'])
        assert repo.holdings()[0]['quantity'] == '12'
        assert repo.holdings()[0]['value'] == '500.00'
    finally:
        repo.close()


def test_existing_document_only_import_does_not_hide_new_portfolio_data(tmp_path):
    from PySide6.QtWidgets import QApplication
    from portman.import_options import ImportOptionsDialog
    QApplication.instance() or QApplication([])
    repo = RepositoryV09(tmp_path / 'test.sqlite', backups=False)
    try:
        repo.commit_batches([ImportBatch('test.pdf', 'hash', source_sheet='PDF')])
        dialog = ImportOptionsDialog(repo, [parsed(QUARTER)])
        assert dialog.duplicates == [False]
        dialog.reject()
    finally:
        repo.close()


def test_depot_only_cost_survives_online_snapshot_without_cash_or_price(tmp_path):
    from portman.performance_service import PerformanceService
    repo = RepositoryV09(tmp_path / 'test.sqlite', backups=False)
    try:
        opening = ImportBatch('empty', 'empty', snapshots=[Snapshot(ACCOUNT, '2026-06', '2026-06-30', 'Baader Quartalsaufstellung', [])])
        trade = parsed(TRADE)
        trade.path = 'trade'; trade.documents = []
        repo.commit_batches([opening, trade])
        p = repo.holdings()[0]
        assert (p['quantity'], p['cost'], p['value']) == ('2', '121.00', None)
        assert not repo.transactions()[0]['affects_cash']
        assert Decimal(repo.transactions()[0]['amount']) > 0
        assert repo.account_overview()[0]['balance'] is None
        assert PerformanceService(repo).overview()['value'] is None
        flows = PerformanceService(repo)._transactions(ACCOUNT, '2026-01-01', '2026-12-31')
        assert len(flows) == 1 and flows[0]['kind'] == 'BUY' and Decimal(flows[0]['amount']) == Decimal('-121.00')
        online = ImportBatch('online', 'online', snapshots=[Snapshot(ACCOUNT, '2026-07', '2026-07-02',
            'Online Baader', [Position(KEY, 'BASF', isin=KEY, quantity='2', value='130')])])
        repo.commit_batches([online])
        p = repo.holdings()[0]
        assert (p['quantity'], p['cost'], p['value']) == ('2', '121.00', '130')
        sale = BankTransaction(ACCOUNT, 'baader-trade-sale', '2026-07-03', 'SELL', '70', 'EUR',
            security=KEY, quantity='1', affects_cash=False)
        repo.commit_batches([ImportBatch('sale', 'sale', transactions=[sale])])
        p = repo.holdings()[0]
        assert (p['quantity'], p['cost'], p['value']) == ('1', '60.50', '130')
        assert repo.account_overview()[0]['balance'] is None
    finally:
        repo.close()


def test_individual_purchases_build_cost_and_fifo_sale_without_depot_statement(tmp_path):
    repo = RepositoryV09(tmp_path / 'purchases.sqlite', backups=False)
    try:
        first = parsed(TRADE)
        first.documents = []
        result = repo.commit_batches([first])[0]
        assert result['status'] == 'imported'
        p = repo.holdings()[0]
        assert (p['quantity'], p['cost'], p['value']) == ('2', '121.00', None)
        assert 'Teilbestand' in p['valuation_note']
        second = BankTransaction(ACCOUNT, 'baader-trade-second', '2026-07-02', 'BUY', '161', 'EUR',
                                 security=KEY, quantity='2', fees='1', affects_cash=False)
        sale = BankTransaction(ACCOUNT, 'baader-trade-sale', '2026-07-03', 'SELL', '300', 'EUR',
                               security=KEY, quantity='3', affects_cash=False)
        repo.commit_batches([ImportBatch('second', 'second', transactions=[second]),
                             ImportBatch('sale', 'sale', transactions=[sale])])
        assert repo.holdings('2026-07-02')[0]['cost'] == '282.00'
        p = repo.holdings('2026-07-03')[0]
        assert (p['quantity'], p['cost']) == ('1', '80.50')
        assert repo.account_overview()[0]['balance'] is None
        assert repo.commit_batches([first])[0]['status'] == 'duplicate'
        assert repo.holdings()[0]['quantity'] == '1'
    finally:
        repo.close()


def test_generic_depot_trades_use_fifo_and_date_without_dividends(tmp_path):
    repo = RepositoryV09(tmp_path / 'generic.sqlite', backups=False)
    try:
        trades = [
            BankTransaction('Depot A', 'buy-1', '2026-01-01', 'BUY', '-101', 'EUR', security=KEY, quantity='2', fees='1'),
            BankTransaction('Depot A', 'buy-2', '2026-01-02', 'BUY', '-202', 'EUR', security=KEY, quantity='2', fees='2'),
            BankTransaction('Depot A', 'dividend', '2026-01-03', 'DIVIDEND', '10', 'EUR', security=KEY),
            BankTransaction('Depot A', 'sell', '2026-01-04', 'SELL', '400', 'EUR', security=KEY, quantity='3'),
            BankTransaction('Depot B', 'other', '2026-01-01', 'BUY', '-999', 'EUR', security=KEY, quantity='1')]
        repo.commit_batches([ImportBatch('trades', 'trades', transactions=trades)])
        first = repo.holdings('2026-01-01', 'Depot A')[0]
        assert (first['quantity'], first['cost']) == ('2', '101.00')
        assert repo.holdings('2026-01-03', 'Depot A')[0]['cost'] == '303.00'
        last = repo.holdings('2026-01-04', 'Depot A')[0]
        assert (last['quantity'], last['cost']) == ('1', '101.00')
        assert repo.holdings('2026-01-04', 'Depot B')[0]['cost'] == '999.00'
    finally:
        repo.close()


def test_security_alias_and_currency_are_respected(tmp_path):
    repo = RepositoryV09(tmp_path / 'aliases.sqlite', backups=False)
    try:
        baseline = ImportBatch('base', 'base', snapshots=[Snapshot('Depot', '2026-01', '2026-01-02', 'Depot',
            [Position(KEY, 'BASF', isin=KEY, quantity='2', value='200')])])
        trades = ImportBatch('trades', 'trades', transactions=[
            BankTransaction('Depot', 'buy', '2026-01-01', 'BUY', '-101', 'EUR', security='ISIN:' + KEY, quantity='2'),
            BankTransaction('Depot', 'usd', '2026-01-03', 'BUY', '-999', 'USD', security=KEY, quantity='2'),
            BankTransaction('Depot', 'unclassified', '2026-01-03', 'BANK_BOOKING', '-50', 'EUR')])
        repo.commit_batches([baseline, trades])
        p = repo.holdings('2026-01-03')[0]
        assert (p['quantity'], p['cost']) == ('2', '101.00')
    finally:
        repo.close()
