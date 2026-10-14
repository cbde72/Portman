"""Independent read-only repository, without migrations or startup writes."""
import sqlite3
from pathlib import Path
from portfolio_v5.storage import Store
from .market_data import MarketDataStore
from .chart_holdings import reuse_chart_holdings
from .chart_balances import reuse_chart_balances, reuse_chart_balances_at


def open_chart_reader(path, repository_type, interrupted):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=1)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    db.set_progress_handler(lambda: int(interrupted()), 2000)
    repo = object.__new__(repository_type)
    repo.store = object.__new__(Store)
    repo.store.path, repo.store.db = Path(path), db
    repo.market = object.__new__(MarketDataStore)
    repo.market.db = db
    repo.chart_cancelled = interrupted
    # Long chart walks re-query many distinct days; keep the read caches warm
    # instead of letting the small default limits evict shared results.
    repo.store._read_cache_cap = 4096
    repo._read_cache_cap = 4096
    repo._v8_cache_cap = 512
    reuse_chart_holdings(repo)
    reuse_chart_balances(repo)
    reuse_chart_balances_at(repo)
    return repo
