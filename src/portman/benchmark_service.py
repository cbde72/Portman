"""Vergleichsindizes: Benchmarkindex aus Kurshistorien, aktive Rendite, Tracking Error."""
from datetime import timedelta
from decimal import Decimal

from .market_values import finite
from .price_history_store import history_rows

ZERO = Decimal(0)


def benchmark_key_and_mapping(repo, symbol):
    """Find the security key whose market feed is mapped to the given symbol."""
    lowered = symbol.strip().casefold()
    for key, mapping in repo.market.mappings().items():
        if str(mapping.get('symbol', '')).casefold() == lowered:
            return key, mapping
    return None, None


def benchmark_daily_index(repo, symbol, start, end):
    """Daily benchmark index (start 100) from stored close prices.

    Prices are carried forward (last close wins) so every calendar day in
    ``[start, end]`` with a known price level is covered. Returns ``None``
    when no symbol mapping or no usable price history exists.
    """
    key, mapping = benchmark_key_and_mapping(repo, symbol)
    if key is None:
        return None
    rows = history_rows(repo.store.db, key, mapping, start.isoformat(), end.isoformat())
    prices = {}
    for row in rows:
        close = finite(row['close'])
        if close and close > 0:
            prices[row['day']] = close
    if not prices:
        return None
    carried = []
    last = None
    day = start
    last_day = end
    while day <= last_day:
        iso = day.isoformat()
        if iso in prices:
            last = Decimal(prices[iso])
        if last is not None:
            carried.append((iso, last))
        day += timedelta(days=1)
    if len(carried) < 2:
        return None
    base = carried[0][1]
    points = [{'date': carried[0][0], 'index': Decimal(100)}]
    for iso, close in carried[1:]:
        points.append({'date': iso, 'index': Decimal(100) * (close / base)})
    return points


def compare_daily_indexes(portfolio_daily_index, benchmark_points):
    """Active return and annualized tracking error on the common window.

    Both series are aligned by calendar date; only days covered by both the
    portfolio index and the benchmark index contribute. Returns ``None`` when
    fewer than two common days exist.
    """
    portfolio = {point['date']: Decimal(point['index']) for point in portfolio_daily_index}
    benchmark = {point['date']: Decimal(point['index']) for point in benchmark_points}
    common = sorted(set(portfolio) & set(benchmark))
    if len(common) < 2:
        return None
    first, last = common[0], common[-1]
    portfolio_total = portfolio[last] / portfolio[first] - 1
    benchmark_total = benchmark[last] / benchmark[first] - 1
    active_return = (Decimal(1) + portfolio_total) / (Decimal(1) + benchmark_total) - 1
    diffs = []
    for previous, current in zip(common, common[1:]):
        portfolio_return = portfolio[current] / portfolio[previous] - 1
        benchmark_return = benchmark[current] / benchmark[previous] - 1
        diffs.append(portfolio_return - benchmark_return)
    mean = sum(diffs, ZERO) / Decimal(len(diffs))
    variance = sum((value - mean) ** 2 for value in diffs) / Decimal(len(diffs))
    tracking_error = variance.sqrt() * Decimal(365).sqrt() if variance >= 0 else None
    return {
        'common_start': first, 'common_end': last,
        'portfolio_return': portfolio_total, 'benchmark_return': benchmark_total,
        'active_return': active_return, 'tracking_error_annualized': tracking_error,
    }