"""Reproducible off-screen benchmark for PortMan's V09 GUI shell.

Run from the repository root with::

    python benchmarks/benchmark_gui_startup.py --runs 5

Each run uses a fresh empty portfolio and a fresh Python process.  The report
therefore separates module imports, database creation, window construction,
workspace navigation and a scope refresh without touching production data.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
from time import perf_counter

ROOT = Path(os.environ.get('PORTMAN_BENCHMARK_ROOT', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))


def worker() -> dict[str, float | int]:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    started = perf_counter()
    from PySide6.QtWidgets import QApplication
    from portman.repository_v09 import RepositoryV09
    from Gui.PortMan_V09 import MainWindow
    imported = perf_counter()

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix='portman-gui-benchmark-') as folder:
        path = Path(folder)
        init_started = perf_counter()
        seed = RepositoryV09(path / 'portfolio.sqlite')
        seed.close()
        initialized = perf_counter()

        window_started = perf_counter()
        window = MainWindow(portfolio_folder=path)
        window_created = perf_counter()
        queries = 0

        def trace(statement):
            nonlocal queries
            if not statement.lstrip().upper().startswith(('BEGIN', 'COMMIT', 'ROLLBACK')):
                queries += 1

        window.repository.db.set_trace_callback(trace)
        switch_started = perf_counter()
        for name in ('accounts', 'holdings', 'analysis', 'dashboard'):
            window.show_workspace(name)
            app.processEvents()
        switched = perf_counter()
        refresh_started = perf_counter()
        window.reload_portfolio(visible_only=True)
        app.processEvents()
        refreshed = perf_counter()
        style_started = perf_counter()
        window.select_gui_style('nord')
        window.select_gui_style('light')
        app.processEvents()
        styled = perf_counter()
        window.close()
        app.processEvents()

    return {
        'imports_ms': (imported - started) * 1000,
        'database_init_ms': (initialized - init_started) * 1000,
        'window_start_ms': (window_created - window_started) * 1000,
        'four_workspace_switches_ms': (switched - switch_started) * 1000,
        'visible_refresh_ms': (refreshed - refresh_started) * 1000,
        'two_theme_switches_ms': (styled - style_started) * 1000,
        'measured_sql_statements': queries,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker()))
        return
    runs = []
    for _ in range(args.runs):
        result = subprocess.run(
            [sys.executable, __file__, '--worker'], check=True, capture_output=True,
            text=True, env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
        )
        runs.append(json.loads(result.stdout.strip().splitlines()[-1]))
    summary = {
        key: round(statistics.median(run[key] for run in runs), 2)
        for key in runs[0]
    }
    print(json.dumps({'runs': runs, 'median': summary}, indent=2))


if __name__ == '__main__':
    main()
