from decimal import Decimal
from datetime import date, timedelta

import pytest

from test_crypto_wallet_import import write_csv
from portfolio_v5.models import ImportBatch, Snapshot, Position, BankTransaction
from portman.crypto_wallet_import import read_wallet_csv, save_wallet
from portman.performance_service import PerformanceService
from portman.repository_v09 import RepositoryV09


@pytest.fixture
def repo(tmp_path):
    repository = RepositoryV09(tmp_path / 'dietz.sqlite', backups=False)
    yield repository
    repository.close()


def analyze(repo, values, transactions=(), currency='EUR'):
    snapshots = [Snapshot('A', day[:7], day, 'test', [Position('X', 'X', quantity='1',
        value=str(value), currency=currency)]) for day, value in values]
    repo.commit_batches([ImportBatch('test', 'test', snapshots=snapshots, transactions=list(transactions))])
    return PerformanceService(repo).analyze('A', values[0][0], values[-1][0])


@pytest.mark.parametrize('day,closing,expected', [
    ('2026-01-06', '1650', Decimal('0.12')),
    ('2026-01-11', '1600', Decimal('0.10')),
])
def test_purchase_daily_weight_and_end_day(repo, day, closing, expected):
    result = analyze(repo, [('2026-01-01', 1000), ('2026-01-11', closing)], [
        BankTransaction('A', 'buy', day, 'BUY', '-500', 'EUR')])
    assert result['twr'] == expected
    assert result['net_contributions'] == 500


def test_sale_and_opening_day_are_handled_once(repo):
    result = analyze(repo, [('2026-01-01', 1000), ('2026-01-11', 900)], [
        BankTransaction('A', 'opening', '2026-01-01', 'BUY', '-1000', 'EUR'),
        BankTransaction('A', 'sell', '2026-01-06', 'SELL', '200', 'EUR')])
    assert abs(result['twr'] - Decimal(100) / Decimal(900)) < Decimal('1e-25')
    assert result['profit'] == 100
    assert result['net_contributions'] == -200


def test_geometric_linking_and_cash_account_deposit_excluded(repo):
    result = analyze(repo, [('2026-01-01', 100), ('2026-01-06', 110), ('2026-01-11', 99)], [
        BankTransaction('A', 'cash', '2026-01-04', 'DEPOSIT', '500', 'EUR')])
    assert result['twr'] == Decimal('-.01')


def test_dividend_is_security_portfolio_receipt(repo):
    result = analyze(repo, [('2026-01-01', 100), ('2026-01-11', 95)], [
        BankTransaction('A', 'div', '2026-01-11', 'DIVIDEND', '10', 'EUR')])
    assert result['twr'] == Decimal('.05')
    assert result['profit'] == 5


@pytest.mark.parametrize('currency,tx_currency', [('USD', 'EUR'), ('EUR', 'USD')])
def test_foreign_values_are_not_summed_as_eur(repo, currency, tx_currency):
    result = analyze(repo, [('2026-01-01', 100), ('2026-01-11', 200)], [
        BankTransaction('A', 'buy', '2026-01-06', 'BUY', '-100', tx_currency)], currency)
    assert 'EUR' in result['error']


def test_zero_capital_is_not_a_return(repo):
    assert 'Kapitalbasis' in analyze(repo, [('2026-01-01', 0), ('2026-01-11', 100)])['error']


def test_total_loss_can_be_annualized(repo):
    result = analyze(repo, [('2026-01-01', 100), ('2026-01-11', 0)])
    assert result['twr'] == -1
    assert result['twr_annualized'] == -1
    assert result['total_return'] == -1
    assert result['total_return_annualized'] == -1
    assert result['daily_total_return_series'][-1]['index'] == 0
    assert result['daily_total_return_series'][-1]['return'] == -1


def test_changing_depot_coverage_is_not_profit(repo):
    repo.commit_batches([ImportBatch('coverage', 'coverage', snapshots=[
        Snapshot('A', '2026-01', '2026-01-01', 'test', [Position('X', 'X', value='100')]),
        Snapshot('B', '2026-01', '2026-01-11', 'test', [Position('Y', 'Y', value='200')])])])
    result = PerformanceService(repo).analyze(None, '2026-01-01', '2026-01-11')
    assert 'Depotabdeckung' in result['error']


def test_invalid_trade_sign_is_rejected(repo):
    result = analyze(repo, [('2026-01-01', 100), ('2026-01-11', 200)], [
        BankTransaction('A', 'buy', '2026-01-06', 'BUY', '100', 'EUR')])
    assert 'Vorzeichen' in result['error']
    assert result['issues'][0]['level'] == 'error'
    assert 'Käufe als negative' in result['issues'][0]['action']


def test_calculation_reports_missing_proofs_with_actions(repo):
    result = analyze(repo, [('2026-01-01', 100), ('2026-01-11', 110)])
    assert result['twr'] == Decimal('.1')
    assert result['issues']
    assert all(issue['title'] and issue['action'] for issue in result['issues'])
    assert any('Buchungsabdeckung' in issue['title'] for issue in result['issues'])


def test_return_below_total_loss_is_not_linked(repo):
    result = analyze(repo, [('2026-01-01', 100), ('2026-01-11', 0)], [
        BankTransaction('A', 'fee', '2026-01-11', 'FEE', '-20', 'EUR')])
    assert '−100 %' in result['error']


def test_wallet_uses_frozen_values_and_signed_trades(repo, tmp_path):
    batch = read_wallet_csv(write_csv(tmp_path, [
        {'Handelsdatum': '01.10.2026', 'Nominale_num': '1', 'Endbetrag_num': '100'},
        {'Handelsdatum': '02.10.2026', 'Nominale_num': '1', 'Endbetrag_num': '100'},
        {'Handelsdatum': '03.10.2026', 'Nominale_num': '-1', 'Endbetrag_num': '110'}]), 'Wallet', 'signed')
    save_wallet(repo, 'Wallet', {'kind': 'Krypto Wallet'}, None, batch)
    service = PerformanceService(repo)
    assert service.valuation_series('Wallet') == []
    repo.market.save_result(dict(security_key=repo.holdings()[0]['key'], status='ok',
        currency='EUR', provider='Test', attempted_at='2026-10-04T12:00:00+00:00',
        symbol='BTC-EUR', message='ok', prices=[dict(date=day, close=price) for day, price in
            [('2026-10-01', 100), ('2026-10-02', 100), ('2026-10-03', 110)]]))
    result = service.analyze('Wallet', '2026-10-01', '2026-10-03')
    assert result['twr'] == Decimal('.1')
    assert result['profit'] == 20
    assert result['net_contributions'] == -10
    assert [t['amount'] for t in result['transactions']] == ['-100', '110']
    assert all(Decimal(t['amount']) > 0 for t in repo.transactions('Wallet'))
    assert not repo.balances()


def test_analyze_scales_to_many_points_and_transactions(repo):
    start = date(2026, 1, 1)
    days = [start + timedelta(days=index) for index in range(60)]
    values = [(day.isoformat(), 1000 + index * 10) for index, day in enumerate(days)]
    transactions = [BankTransaction('A', f'buy-{day.isoformat()}', day.isoformat(), 'BUY', '-5', 'EUR')
                    for day in days[1:]]
    result = analyze(repo, values, transactions)
    assert 'error' not in result
    assert result['transaction_count'] == len(transactions)
    assert len(result['twr_series']) == 60
    assert len(result['capital_series']) == 60
    assert result['twr_series'][0]['index'] == Decimal(100)
    assert result['net_contributions'] == Decimal('5') * 59
    assert result['profit'] == result['closing'] - result['opening'] + Decimal('-5') * 59


def test_analyze_sums_fees_taxes_and_dividends(repo):
    result = analyze(repo, [('2026-01-01', 1000), ('2026-01-11', 1010)], [
        BankTransaction('A', 'fee', '2026-01-06', 'FEE', '-10', 'EUR', fees='10'),
        BankTransaction('A', 'div', '2026-01-09', 'DIVIDEND', '15', 'EUR')])
    assert 'error' not in result
    assert result['fees'] == Decimal('10')
    assert result['dividends'] == Decimal('15')
    assert result['taxes'] == Decimal('0')


def test_dividend_without_gross_income_reports_none_gross(repo):
    result = analyze(repo, [('2026-01-01', 100), ('2026-01-11', 95)], [
        BankTransaction('A', 'div', '2026-01-11', 'DIVIDEND', '10', 'EUR')])
    assert result['dividends'] == Decimal('10')
    assert result['gross_dividends'] is None
    assert result['dividends_net_complete'] is True


def test_dividend_with_gross_income_reports_gross_and_net_warning(repo):
    result = analyze(repo, [('2026-01-01', 100), ('2026-01-11', 95)], [
        BankTransaction('A', 'div', '2026-01-11', 'DIVIDEND', '10', 'EUR',
                        gross_income='12', gross_currency='EUR', income_basis='gross')])
    assert result['gross_dividends'] == Decimal('12')
    assert result['dividends'] == Decimal('10')
    assert result['dividends_net_complete'] is False
    assert any('separat abgerechneten Steuern' in issue['title'] for issue in result['issues'])


def test_daily_index_covers_every_day_and_matches_twr_series(repo):
    result = analyze(repo, [('2026-01-01', '100'), ('2026-01-31', '110'), ('2026-03-15', '121')])
    start, end = date.fromisoformat(result['start']), date.fromisoformat(result['end'])
    daily = result['daily_index']
    assert len(daily) == (end - start).days + 1
    assert daily[0]['date'] == result['start'] and daily[0]['index'] == Decimal(100)
    assert daily[0]['return'] is None
    assert daily[0]['flow'] == 0
    assert daily[0]['flows'] == 0
    assert daily[-1]['date'] == end.isoformat()
    expected = {point['date']: Decimal(point['index']) for point in result['twr_series']}
    for point in daily:
        if point['date'] in expected:
            actual = Decimal(point['index'])
            assert abs(actual - expected[point['date']]) <= abs(expected[point['date']]) * Decimal('1e-9')


def test_daily_total_return_series_is_canonical_and_internally_consistent(repo):
    result = analyze(repo, [('2026-01-01', '100'), ('2026-01-06', '135'),
                            ('2026-01-11', '128')], [
        BankTransaction('A', 'buy', '2026-01-03', 'BUY', '-25', 'EUR'),
        BankTransaction('A', 'dividend', '2026-01-09', 'DIVIDEND', '8', 'EUR')])
    series = result['daily_total_return_series']
    assert series is result['daily_index']
    assert [point['date'] for point in series] == [
        (date(2026, 1, 1) + timedelta(days=offset)).isoformat() for offset in range(11)]
    product = Decimal(1)
    for previous, point in zip(series, series[1:]):
        assert point['return'] == Decimal(point['index']) / Decimal(previous['index']) - 1
        product *= Decimal(1) + point['return']
    assert abs(product - (Decimal(1) + result['total_return'])) < Decimal('1e-24')
    assert result['total_return'] == result['ttwror']
    assert result['total_return_annualized'] == result['ttwror_annualized']
    assert result['daily_returns'] == [
        {'date': point['date'], 'return': point['return']} for point in series[1:]]
    assert {point['date']: point['flow'] for point in series if point['flow']} == {
        '2026-01-03': Decimal('-25'), '2026-01-09': Decimal('8')}


def test_daily_index_spreads_interval_return_geometrically(repo):
    result = analyze(repo, [('2026-01-01', '100'), ('2026-02-01', '110')])
    daily = result['daily_index']
    assert daily[0]['date'] == '2026-01-01' and daily[0]['index'] == Decimal(100)
    assert len(daily) == 32 and daily[-1]['date'] == '2026-02-01'
    ratios = [Decimal(point['index']) / Decimal(previous['index'])
              for previous, point in zip(daily, daily[1:])]
    assert all(abs(ratio - ratios[0]) < Decimal('1e-20') for ratio in ratios)
    assert abs(Decimal(daily[-1]['index']) - Decimal('110')) < Decimal('1e-7')


def test_daily_index_constant_growth_has_zero_volatility_and_drawdown(repo):
    result = analyze(repo, [('2026-01-01', '100'), ('2026-02-01', '110')])
    assert result['volatility_annualized'] is not None
    assert result['volatility_annualized'] < Decimal('1e-6')
    assert result['max_drawdown'] == 0


def test_daily_index_risk_statistics_on_dip_and_recovery(repo):
    result = analyze(repo, [('2026-01-01', '100'), ('2026-02-01', '90'), ('2026-03-01', '108')])
    assert result['volatility_annualized'] is not None and result['volatility_annualized'] > 0
    assert abs(result['max_drawdown'] - Decimal('0.1')) < Decimal('1e-9')


def test_analyze_error_has_no_daily_index_keys(repo):
    result = analyze(repo, [('2026-01-01', '100')])
    assert result.get('error')
    assert 'daily_index' not in result and 'volatility_annualized' not in result


def test_ttwror_is_flow_independent_market_return(repo):
    # Single interval, one positive flow (SELL) mid-period. The true daily TWR
    # of the portfolio equals the market path (8 % daily compounding) alone:
    # 1000*1.08^10 - 200*1.08^5 is the observed security value after proceeds
    # have left the security portfolio.
    daily = Decimal('1.08')
    end_value = 1000 * daily ** 10 - 200 * daily ** 5
    result = analyze(repo, [('2026-01-01', '1000'), ('2026-01-11', str(end_value))], [
        BankTransaction('A', 'sell', '2026-01-06', 'SELL', '200', 'EUR')])
    assert 'error' not in result
    expected = daily ** 10 - Decimal(1)
    assert abs(result['ttwror'] - expected) < Decimal('1e-9')
    assert abs(result['twr'] - expected) > Decimal('1e-3')  # modified dietz differs
    assert result['ttwror_annualized'] is not None and result['ttwror_annualized'] > 0
    assert abs(Decimal(result['daily_index'][-1]['index']) - 100 * daily ** 10) < Decimal('1e-6')


def test_daily_index_neutralizes_flows_on_their_day(repo):
    # BUY of -500 at end of 2026-01-05 (6 days remaining in the
    # 2026-01-01..2026-01-11 interval): the end value is 1000*1.05^10 + 500*1.05^6,
    # so the solved daily rate is exactly 5 % and the index does not jump by
    # the flow amount.
    end_value = 1000 * Decimal('1.05') ** 10 + 500 * Decimal('1.05') ** 6
    result = analyze(repo, [('2026-01-01', '1000'), ('2026-01-11', str(end_value))], [
        BankTransaction('A', 'buy', '2026-01-05', 'BUY', '-500', 'EUR')])
    daily = result['daily_index']
    flow_day = next(point for point in daily if point['date'] == '2026-01-05')
    assert flow_day['flows'] == Decimal('-500')
    assert flow_day['index'] == 100 * Decimal('1.05') ** 4  # no jump by the flow
    neighbors = [Decimal(p['index']) / Decimal(q['index']) - 1
                 for p, q in zip(daily[5:8], daily[4:7])]
    assert all(abs(rate - Decimal('0.05')) < Decimal('1e-9') for rate in neighbors)


@pytest.mark.parametrize('day', ['2026-01-02', '2026-01-06', '2026-01-11'])
@pytest.mark.parametrize('kind,amount,closing', [
    ('BUY', '-50', '150'),
    ('SELL', '50', '50'),
    ('DIVIDEND', '10', '90'),
])
def test_cashflow_neutrality_without_market_return(repo, day, kind, amount, closing):
    result = analyze(repo, [('2026-01-01', '100'), ('2026-01-11', closing)], [
        BankTransaction('A', kind.lower(), day, kind, amount, 'EUR')])
    assert abs(result['twr']) < Decimal('1e-20')
    assert abs(result['ttwror']) < Decimal('1e-20')
    assert result['xirr'] is not None and abs(result['xirr']) < 1e-12


def test_cashflow_neutrality_with_multiple_opposing_flows(repo):
    result = analyze(repo, [('2026-01-01', '100'), ('2026-01-11', '130')], [
        BankTransaction('A', 'buy', '2026-01-03', 'BUY', '-50', 'EUR'),
        BankTransaction('A', 'sell', '2026-01-08', 'SELL', '20', 'EUR')])
    assert abs(result['twr']) < Decimal('1e-20')
    assert abs(result['ttwror']) < Decimal('1e-20')
    assert result['xirr'] is not None and abs(result['xirr']) < 1e-12
    assert result['profit'] == 0
    assert result['net_contributions'] == 30


def test_ttwror_chains_across_intervals_with_flows(repo):
    # Interval 1: 1000 -> 1320 with a 200 SELL on day 5 of 10.
    # Interval 2: 1320 -> 1760 with a 100 BUY on day 3 of 8.
    g1 = Decimal('1.06')
    g2 = Decimal('1.08')
    v1 = 1000 * g1 ** 10 - 200 * g1 ** 5
    v2 = v1 * g2 ** 8 + 100 * g2 ** 5
    result = analyze(repo, [('2026-01-01', '1000'), ('2026-01-11', str(v1)), ('2026-01-19', str(v2))], [
        BankTransaction('A', 'sell', '2026-01-06', 'SELL', '200', 'EUR'),
        BankTransaction('A', 'buy', '2026-01-14', 'BUY', '-100', 'EUR')])
    expected = (g1 ** 10) * (g2 ** 8) - 1
    assert abs(result['ttwror'] - expected) < Decimal('1e-8')


def test_risk_profile_reports_semivolatility_and_drawdown_metrics(repo):
    result = analyze(repo, [('2026-01-01', '100'), ('2026-02-01', '90'), ('2026-03-01', '108')])
    assert result['volatility_annualized'] is not None and result['volatility_annualized'] > 0
    assert result['semivolatility_annualized'] is not None and result['semivolatility_annualized'] > 0
    assert abs(result['max_drawdown'] - Decimal('0.1')) < Decimal('1e-9')
    assert result['current_drawdown'] == 0  # recovered above the old peak
    assert result['longest_drawdown_days'] >= 20


def test_risk_profile_current_drawdown_and_duration_on_unrecovered_loss(repo):
    result = analyze(repo, [('2026-01-01', '100'), ('2026-02-01', '90'), ('2026-03-01', '90')])
    assert abs(result['max_drawdown'] - Decimal('0.1')) < Decimal('1e-9')
    assert abs(result['current_drawdown'] - Decimal('0.1')) < Decimal('1e-9')
    assert result['longest_drawdown_days'] >= 55
    assert result['semivolatility_annualized'] > result['volatility_annualized']
