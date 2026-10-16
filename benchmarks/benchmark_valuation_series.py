"""Reproducible benchmark for PerformanceService._valuation_series()."""
import argparse
import json
import sqlite3
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from portman.performance_service import PerformanceService


SIZES = {'small': (200, 2_000), 'medium': (2_000, 20_000), 'large': (10_000, 100_000)}


class Repository:
    def __init__(self, selected, wallet_rows):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.execute('CREATE TABLE wallet_daily_values(snapshot_id INTEGER, security_key TEXT, '
                        'quantity TEXT, value TEXT, currency TEXT, PRIMARY KEY(snapshot_id,security_key))')
        self.db.executemany('INSERT INTO wallet_daily_values VALUES(?,?,?,?,?)',
            ((index, 'ASSET', '1', str(index), 'EUR') for index in range(wallet_rows)))
        payload = json.dumps({'positions': [{'key': 'ASSET', 'quantity': '1', 'value': '1', 'currency': 'EUR'}]})
        self._snapshots = [dict(id=index, as_of=f'{2000 + index // 365:04d}-{index % 12 + 1:02d}-01',
            effective_date=f'{2000 + index // 365:04d}-{index % 12 + 1:02d}-01', payload=payload,
            depot='Depot', account='Depot', complete=1) for index in range(selected)]

    def snapshots(self, account=None):
        return self._snapshots


def run(size, repetitions):
    selected, wallet_rows = SIZES[size]
    repo = Repository(selected, wallet_rows)
    service = PerformanceService(repo)
    samples = []
    for _ in range(repetitions):
        started = time.perf_counter()
        service._valuation_series('Depot')
        samples.append(time.perf_counter() - started)
    print(json.dumps({'size': size, 'selected_snapshots': selected, 'wallet_rows': wallet_rows,
                      'repetitions': repetitions, 'median_seconds': statistics.median(samples),
                      'samples_seconds': samples}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--size', choices=SIZES, default='medium')
    parser.add_argument('--repetitions', type=int, default=5)
    args = parser.parse_args()
    run(args.size, args.repetitions)
