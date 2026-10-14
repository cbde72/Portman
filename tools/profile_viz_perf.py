r"""Measure the expensive per-dock computations against a disposable DB copy.

Read-only: the real portfolio.sqlite is only copied, never opened for writing.
Run with:  PYTHONPATH=src; .venv\Scripts\python.exe tools\profile_viz_perf.py
"""
import json
import os
import shutil
import tempfile
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'data/v09/portfolio.sqlite'


def timing_run(target):
    folder = Path(tempfile.mkdtemp(prefix='portman-perf-'))
    try:
        copy = folder / 'portfolio.sqlite'
        shutil.copy2(SOURCE, copy)
        from portman.repository_v09 import RepositoryV09
        repo = RepositoryV09(copy, backups=False)
        from portman.performance_service import PerformanceService
        from portman.chart_data import prepare_chart, comparison_data
        from portman.data_quality import DataQualityService

        as_of = '9999-12-31'
        today = date.today().isoformat()
        accounts = repo.accounts()
        positions = repo.current(as_of, None)
        first_key = positions[0]['key'] if positions else None

        ops = {}

        def bench(name, fn, runs=3):
            samples = []
            for _ in range(runs):
                started = time.perf_counter()
                try:
                    fn()
                    samples.append((time.perf_counter() - started) * 1000)
                except Exception as error:
                    ops[name] = 'ERROR ' + str(error)[:120]
                    return
            ops[name] = (min(samples), sum(samples) / len(samples))

        # Historie-Dock
        bench('history.wealth_series (0,0,0, Alle)', lambda: repo.wealth_series(False, False, False, account=None))
        bench('history.wealth_series (1,1,1, Alle)', lambda: repo.wealth_series(True, True, True, account=None))
        bench('history.compare', lambda: repo.compare('2000-01-01', today, None))
        bench('history.transactions', lambda: repo.transactions(None))
        bench('history.imports', lambda: repo.imports())
        bench('history.state_history', lambda: repo.state_history(None))
        bench('history.balances', lambda: repo.balances())

        # Performance-Dock
        service = PerformanceService(repo)
        bench('performance.comparison', lambda: service.comparison(None))
        for account in accounts[:3]:
            bench(f'performance.analyze({account})', lambda a=account: service.analyze(a, '2000-01-01', today))
        bench('performance.valuation_series', lambda: service.valuation_series(None))
        bench('performance.transactions(gesamt)', lambda: service._transactions(None, '2000-01-01', today))

        # Visualisierungen (async, aber zeigt Berechnungskosten)
        for mode in range(9):
            bench(f'chart.prepare_chart(mode={mode})', lambda m=mode: prepare_chart(repo, m, as_of, None))
        bench('chart.comparison_data', lambda: comparison_data(repo, as_of, None))

        # Markt-Dock
        bench('market.current', lambda: repo.current(as_of, None))
        bench('market.records', lambda: repo.market.records())
        bench('market.mappings', lambda: repo.market.mappings())
        if first_key:
            bench('market.observation_history', lambda k=first_key: repo.market.observation_history(k))

        # Qualitäts-Dock
        quality = DataQualityService(repo)
        bench('quality.issues', lambda: quality.issues(as_of, None))

        # Roh-Kosten der Einzelbausteine hinter Overview/Transaktionen
        bench('overview.account_overview (heute)', lambda: repo.account_overview(today))
        bench('overview.account_overview (9999)', lambda: repo.account_overview(as_of))
        bench('overview.holdings (heute)', lambda: repo.holdings(today))
        bench('overview.wealth_summary (9999, Alle)', lambda: repo.wealth_summary(as_of))
        bench('overview.balance_histories', lambda: repo.store.balance_histories())
        bench('transactions.raw_decode', lambda: raw_transactions_decode(repo))

# Kalte Chart-Serie: neues Read-only-Repo wie im ChartWorker, mit Breakdown
        print(f'Datenbank: {SOURCE} ({SOURCE.stat().st_size} bytes)')
        print(f'Konten: {len(accounts)} · Positionen: {len(positions)}')
        print('-' * 60)
        for name, value in sorted(ops.items(), key=lambda kv: (kv[1][0] if isinstance(kv[1], tuple) else 0), reverse=True):
            if isinstance(value, tuple):
                print(f'{value[0]:8.1f} ms (avg {value[1]:7.1f})  {name}')
            else:
                print(f'{"ERROR":>24}  {name}')
        print('-' * 60)
        cold_breakdown(copy, as_of, None)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def raw_transactions_decode(repo):
    """Decode every active transaction incl. booking_details, no consolidation."""
    details = {r['transaction_id']: json.loads(r['payload']) for r in repo.db.execute('SELECT * FROM booking_details')}
    rows = repo.db.execute('''SELECT t.*,i.path FROM transactions t JOIN imports i ON i.id=t.import_id
                              WHERE i.active=1 AND NOT EXISTS (
                                SELECT 1 FROM bank_booking_replacements r JOIN imports newer ON newer.id=r.new_import
                                WHERE r.old_transaction=t.id AND newer.active=1) ORDER BY t.id''')
    decoded = []
    for r in rows:
        data = json.loads(r['payload'])
        data.update(details.get(r['id'], {}))
        decoded.append(data)
    return decoded


def cold_breakdown(path, as_of, account):
    """Messung mit frischem ChartWorker-Repo samt pro-Tages-Details."""
    from pathlib import Path as _Path
    from portman.chart_reader import open_chart_reader
    from portman.repository_v09 import RepositoryV09
    from portman.visualization_data import wealth_history, wealth_at

    cache = _Path(path).parent / 'chart-series-cache.json'
    if cache.exists():
        os.remove(cache)

    reader = open_chart_reader(path, RepositoryV09, lambda: False)
    timings = defaultdict(lambda: [0.0, 0])

    def track(method_name):
        original = getattr(reader, method_name)
        def wrapper(*args, **kwargs):
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                timings[method_name][0] += (time.perf_counter() - started) * 1000
                timings[method_name][1] += 1
        setattr(reader, method_name, wrapper)

    for name in ('account_overview', 'holdings', 'wealth_summary', 'balance_histories',
                 'transactions', 'snapshots', 'state_history', 'balances'):
        track(name)

    def timed(name, fn):
        started = time.perf_counter()
        try:
            result = fn()
            timings[name][0] = (time.perf_counter() - started) * 1000
            return result
        except Exception:
            timings[name][0] = -1
            return None

    started = time.perf_counter()
    series = wealth_history(reader, as_of, account)
    build_ms = (time.perf_counter() - started) * 1000
    print(f'COLD  wealth_history: {build_ms:8.1f} ms für {len(series)} Tage')
    for name in sorted(timings, key=lambda n: timings[n][0], reverse=True):
        total, calls = timings[name]
        if total <= 0:
            continue
        print(f'      {name}: {total:8.1f} ms ({calls} Aufrufe, {total/max(calls,1):.1f} ms/Aufruf) = {100*total/max(build_ms,1):.0f}% der Zeit')
    timed('wealth_at(as_of)', lambda: wealth_at(reader, as_of, account))
    if timings.get('wealth_at(as_of)') is not None and timings['wealth_at(as_of)'][0] > 0:
        print(f'      wealth_at(as_of): {timings["wealth_at(as_of)"][0]:8.1f} ms (ein Stichtag, inkl. account_overview-Cache)')

    second = open_chart_reader(path, RepositoryV09, lambda: False)
    started = time.perf_counter()
    series2 = wealth_history(second, as_of, account)
    cache_ms = (time.perf_counter() - started) * 1000
    print(f'CACHE wealth_history (2. Reader): {cache_ms:8.1f} ms für {len(series2)} Tage')
    same = series == series2
    print(f'      Reihen identisch: {same} · Cache-Datei: {cache.stat().st_size if cache.exists() else 0} bytes')
    print(f'      erste  Zeile: {series[0] if series else None}')
    print(f'      letzte Zeile: {series[-1] if series else None}')


if __name__ == '__main__':
    if not SOURCE.exists():
        raise SystemExit(f'Keine Datenbank gefunden: {SOURCE}')
    timing_run(None)