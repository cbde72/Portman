from decimal import Decimal
from datetime import date, timedelta

import pytest

from portfolio_v5.models import ImportBatch, Snapshot, Position
from portman.performance_service import PerformanceService
from portman.benchmark_service import benchmark_daily_index
from portman.repository_v09 import RepositoryV09


@pytest.fixture
def repo(tmp_path):
    repository = RepositoryV09(tmp_path / 'benchmark.sqlite', backups=False)
    yield repository
    repository.close()


def seed_benchmark_prices(repo, symbol='MSFT', start='2026-01-01', end='2026-01-10',
                          daily_growth=Decimal('1.01'), key='BENCH'):
    prices = []
    day = date.fromisoformat(start)
    last_day = date.fromisoformat(end)
    close = Decimal(100)
    while day <= last_day:
        prices.append({'date': day.isoformat(), 'close': float(close)})
        close *= daily_growth
        day += timedelta(days=1)
    repo.market.save_result(dict(
        security_key=key, status='ok', attempted_at=start, message='OK',
        symbol=symbol, currency='EUR', prices=prices))


def portfolio_result(repo, values, benchmark=None):
    snapshots = [Snapshot('A', day[:7], day, 'test', [Position('X', 'X', quantity='1',
        value=str(value), currency='EUR')]) for day, value in values]
    repo.commit_batches([ImportBatch('test', 'test', snapshots=snapshots)])
    return PerformanceService(repo).analyze('A', values[0][0], values[-1][0], benchmark)


def test_benchmark_index_carries_prices_forward(repo):
    seed_benchmark_prices(repo, end='2026-01-10')
    index = benchmark_daily_index(repo, 'MSFT', date(2026, 1, 1), date(2026, 1, 10))
    assert index is not None
    assert index[0] == {'date': '2026-01-01', 'index': Decimal(100)}
    assert len(index) == 10  # every calendar day covered by carried close
    assert abs(Decimal(index[-1]['index']) - 100 * Decimal('1.01') ** 9) < Decimal('1e-9')


def test_benchmark_index_unknown_symbol_is_none(repo):
    assert benchmark_daily_index(repo, 'UNKNOWN', date(2026, 1, 1), date(2026, 1, 10)) is None


def test_analyze_with_benchmark_active_return_and_tracking_error(repo):
    seed_benchmark_prices(repo, end='2026-01-11', daily_growth=Decimal('1.003'))
    # Portfolio grows 100 -> 108; benchmark compounds 0.3 % daily over 10 days.
    result = portfolio_result(repo, [('2026-01-01', '100'), ('2026-01-11', '108')], 'MSFT')
    benchmark = result['benchmark']
    assert benchmark['symbol'] == 'MSFT'
    assert benchmark['index'] and benchmark['index'][0]['date'] == '2026-01-01'
    comparison = benchmark['comparison']
    assert comparison['common_start'] == '2026-01-01' and comparison['common_end'] == '2026-01-11'
    expected_benchmark = Decimal('1.003') ** 10 - 1
    assert abs(comparison['benchmark_return'] - expected_benchmark) < Decimal('1e-9')
    assert abs(comparison['portfolio_return'] - Decimal('0.08')) < Decimal('1e-9')
    assert abs(comparison['active_return'] - (Decimal('1.08') / (Decimal('1.003') ** 10) - 1)) < Decimal('1e-8')
    assert abs(comparison['tracking_error_annualized'] - 0) < Decimal('1e-9')


def test_analyze_without_benchmark_has_none_result(repo):
    result = portfolio_result(repo, [('2026-01-01', '100'), ('2026-01-11', '108')])
    assert result['benchmark'] is None


def test_analyze_with_benchmark_without_data_in_window_is_safe(repo):
    # Benchmark prices end before the portfolio period starts.
    seed_benchmark_prices(repo, end='2025-12-31', start='2025-12-01', daily_growth=Decimal('1.01'))
    result = portfolio_result(repo, [('2026-01-01', '100'), ('2026-01-11', '108')], 'MSFT')
    assert result['benchmark'] is None
    assert any('keine Kursdaten' in item['title'] for item in result['issues'])


def test_analyze_with_benchmark_tracking_error_on_diverging_paths(repo):
    # Benchmark falls while the portfolio rises: tracking error is clearly above zero.
    seed_benchmark_prices(repo, end='2026-01-10', daily_growth=Decimal('0.997'))
    result = portfolio_result(repo, [('2026-01-01', '100'), ('2026-01-11', '108')], 'MSFT')
    comparison = result['benchmark']['comparison']
    assert comparison['benchmark_return'] < 0
    assert comparison['active_return'] > 0
    assert comparison['tracking_error_annualized'] is not None
    assert comparison['tracking_error_annualized'] > 0