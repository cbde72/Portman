from decimal import Decimal

import pytest

from pdf_plugins._baader_core import parse_baader_portfolio
from portfolio_v5.models import ImportBatch, transaction_validation
from portman.performance_service import PerformanceService
from portman.repository_v09 import RepositoryV09


TEMPLATE = '''Baader Bank AG
Depot-Nr.: {depot}
Referenz-Nr.: {reference}
Wertpapierabrechnung: {kind}
ISIN: DE000BASF111 WKN: BASF11
STK {quantity}  BASF SE  EUR {price}
Kurswert EUR {gross}
{deductions}{direction} Konto 1234567005 Valuta: 03.07.2026 EUR {net}
Details zur Ausführung:
Handelsdatum Handelsuhrzeit
01.07.2026 10:00:00
Verwahrart: Girosammelverwahrung
'''


def trade(*, kind='Kauf', gross='120,00', net='120,00', quantity='2', price='60,00',
          deductions='', depot='1234567890', reference='12345'):
    text = TEMPLATE.format(
        depot=depot, reference=reference, kind=kind, quantity=quantity, price=price,
        gross=gross, deductions=deductions,
        direction='Zu Lasten' if kind == 'Kauf' else 'Zu Gunsten', net=net)
    batch = ImportBatch('test.pdf', reference, source_sheet='PDF')
    return parse_baader_portfolio(batch, [text], b'%PDF-test')


@pytest.mark.parametrize(('kwargs', 'expected'), [
    ({}, ('BUY', '-120.00', '120.00', '0', '0')),
    ({'deductions': 'Mindermengenzuschlag Finanzen.net EUR 1,00\n', 'net': '121,00'},
     ('BUY', '-121.00', '120.00', '1.00', '0')),
    ({'deductions': 'Kapitalertragsteuer EUR 25,00\n', 'net': '145,00'},
     ('BUY', '-145.00', '120.00', '0', '25.00')),
    ({'kind': 'Verkauf'}, ('SELL', '120.00', '120.00', '0', '0')),
    ({'kind': 'Verkauf', 'deductions': 'Mindermengenzuschlag Finanzen.net EUR 1,00\n',
      'net': '119,00'}, ('SELL', '119.00', '120.00', '1.00', '0')),
    ({'kind': 'Verkauf', 'deductions': 'Kapitalertragsteuer EUR 25,00\n',
      'net': '95,00'}, ('SELL', '95.00', '120.00', '0', '25.00')),
])
def test_trade_net_amounts_follow_cashflow_semantics(kwargs, expected):
    tx = trade(**kwargs).transactions[0]
    assert (tx.kind, tx.amount, tx.gross_amount, tx.fees, tx.taxes) == expected
    assert tx.affects_cash is False
    assert transaction_validation(tx) == ([], [])


def test_cent_equation_quantity_and_cost_basis_survive(tmp_path):
    batch = trade(gross='100,01', net='101,00', quantity='3', price='33,3366666667',
                  deductions='Mindermengenzuschlag Finanzen.net EUR 0,99\n')
    tx = batch.transactions[0]
    assert (tx.quantity, tx.gross_amount, tx.amount) == ('3', '100.01', '-101.00')
    batch.documents = []
    repo = RepositoryV09(tmp_path / 'cent.sqlite', backups=False)
    try:
        assert repo.commit_batches([batch])[0]['status'] == 'imported'
        position = repo.holdings()[0]
        assert (position['quantity'], position['cost']) == ('3', '101.00')
        flow = PerformanceService(repo)._transactions('Baader Depot 1234567890', '2026-01-01', '2026-12-31')[0]
        assert Decimal(flow['amount']) == Decimal('-101.00')
    finally:
        repo.close()


def test_buy_sale_idempotency_and_depot_isolation(tmp_path):
    first = trade(depot='1111111111', reference='1')
    sale = trade(kind='Verkauf', depot='1111111111', reference='2')
    other = trade(depot='2222222222', reference='1')
    for batch in (first, sale, other):
        batch.documents = []
    repo = RepositoryV09(tmp_path / 'depots.sqlite', backups=False)
    try:
        results = repo.commit_batches([first, sale, other])
        assert [result['status'] for result in results] == ['imported'] * 3
        assert repo.commit_batches([first])[0]['status'] == 'duplicate'
        assert repo.holdings(account='Baader Depot 1111111111') == []
        position = repo.holdings(account='Baader Depot 2222222222')[0]
        assert (position['quantity'], position['cost']) == ('2', '120.00')
    finally:
        repo.close()


@pytest.mark.parametrize(('old', 'new', 'message'), [
    ('Zu Lasten', 'Zu Gunsten', 'Belastung/Gutschrift'),
    ('EUR 120,00\nDetails', 'EUR 120,01\nDetails', 'Gebühren'),
    ('Wertpapierabrechnung: Kauf', 'Wertpapierabrechnung: Storno Kauf', 'Stornobeleg'),
])
def test_inconsistent_or_cancelled_documents_stay_rejected(old, new, message):
    text = TEMPLATE.format(
        depot='1234567890', reference='12345', kind='Kauf', quantity='2', price='60,00',
        gross='120,00', deductions='', direction='Zu Lasten', net='120,00').replace(old, new)
    with pytest.raises(ValueError, match=message):
        parse_baader_portfolio(ImportBatch('test.pdf', 'hash'), [text], b'%PDF-test')
