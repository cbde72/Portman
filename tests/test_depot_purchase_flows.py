from decimal import Decimal

import pytest

from portfolio_v5.models import ImportBatch, Snapshot, Position, BankTransaction
from portman.performance_service import PerformanceService
from portman.depot_purchase_flows import purchase_flows
from test_modified_dietz import repo as repo


ISIN = 'IE00B3YCGJ38'


def prepare(repo, bank, text, extra=(), wkn_only=False):
    depot, cash = bank + ' Depot', bank + ' Girokonto'
    repo.commit_batches([ImportBatch('purchases', 'purchases', snapshots=[
        Snapshot(depot, '2026-01', day, 'test', [Position('WKN:A0YEDG' if wkn_only else ISIN,
            'ETF', isin='' if wkn_only else ISIN, wkn='A0YEDG', value=value, quantity='1')])
        for day, value in [('2026-01-01', '1000'), ('2026-01-11', '1650')]], transactions=[
        BankTransaction(cash, 'payment', '2026-01-06', 'BANK_BOOKING', '-500', 'EUR', purpose=text),
        *extra])])
    return PerformanceService(repo).analyze(depot, '2026-01-01', '2026-01-11')


@pytest.mark.parametrize('bank,text,wkn_only', [
    ('ING', 'WP.ABRECHNUNG 012345Kauf ISINIE00B3YCGJ38ETF', False),
    ('comdirect', 'Wertpapiere ETF WPKNR: A0YEDG ISIN: IE00B3YCGJ38', False),
    ('comdirect', '01ETF 02WPKNR: A0YEDG ISIN: IE00B3YCGJ38', True),
])
def test_bank_payment_neutralizes_depot_purchase(repo, bank, text, wkn_only):
    result = prepare(repo, bank, text, wkn_only=wkn_only)
    assert result['twr'] == Decimal('.12')
    assert result['net_contributions'] == 500
    assert result['transactions'][0]['cash_account'] == bank + ' Girokonto'
    assert repo.transactions(bank + ' Girokonto')[0]['kind'] == ('BUY' if bank == 'comdirect' and text.startswith('Wertpapiere') else 'BANK_BOOKING')
    assert repo.transactions(bank + ' Depot') == []
    all_result = PerformanceService(repo).analyze(None, '2026-01-01', '2026-01-11')
    assert all_result['net_contributions'] == 500


@pytest.mark.parametrize('text', [
    'Wertpapiere STORNO WPKNR: A0YEDG ISIN: IE00B3YCGJ38',
    'Kartenzahlung Einkauf',
])
def test_unrelated_payments_are_not_purchases(repo, text):
    result = prepare(repo, 'comdirect', text)
    assert result['net_contributions'] == 0


def test_custody_payment_is_classified_as_fee(repo):
    prepare(repo, 'comdirect', 'Verwahrentgelt WPKNR: A0YEDG ISIN: IE00B3YCGJ38')
    tx = repo.transactions('comdirect Girokonto')[0]
    assert (tx['kind'], tx['security'], tx['fees']) == ('FEE', ISIN, '500')


def test_direct_trade_and_cash_payment_are_counted_once(repo):
    direct = BankTransaction('ING Depot', 'trade', '2026-01-06', 'BUY', '-500', 'EUR', security=ISIN)
    result = prepare(repo, 'ING', 'WP.ABRECHNUNG 123Kauf ISINIE00B3YCGJ38', [direct])
    assert result['net_contributions'] == 500
    assert len(result['transactions']) == 1


def test_ambiguous_depot_is_not_guessed(repo):
    prepare(repo, 'ING', 'WP.ABRECHNUNG 123Kauf ISINIE00B3YCGJ38')
    repo.commit_batches([ImportBatch('other', 'other', snapshots=[
        Snapshot('ING Zweites Depot', '2026-01', '2026-01-01', 'test', [
            Position(ISIN, 'ETF', isin=ISIN, value='100', quantity='1')])])])
    assert purchase_flows(repo) == []


def test_bank_boundaries_are_respected(repo):
    prepare(repo, 'comdirect', 'Wertpapiere WPKNR: A0YEDG ISIN: IE00B3YCGJ38', [
        BankTransaction('ING Girokonto', 'other', '2026-01-06', 'BANK_BOOKING', '-500', 'EUR',
                        purpose='WP.ABRECHNUNG 123Kauf ISINIE00B3YCGJ38')])
    assert purchase_flows(repo) == []
    assert repo.transactions('ING Girokonto')[0]['kind'] == 'BANK_BOOKING'
