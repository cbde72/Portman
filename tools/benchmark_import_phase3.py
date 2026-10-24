"""Reproducible phase-3 import benchmark; writes only temporary databases."""
import argparse
import json
import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path

from portfolio_v5.models import BankTransaction, ImportBatch, Position, Snapshot
from portman.repository_v09 import RepositoryV09


def batches(count):
    result = []
    for index in range(count):
        day = index % 28 + 1
        account = f'Depot {index % 4}'
        result.append(ImportBatch(
            f'benchmark-{index}.csv', f'benchmark-hash-{index}',
            snapshots=[Snapshot(account, '2026-01', f'2026-01-{day:02d}', 'Benchmark', [
                Position(f'SEC-{index}', f'Security {index}', quantity='1', value=str(100 + index))])],
            transactions=[BankTransaction(
                account, f'tx-{index}', f'2026-01-{day:02d}', 'BUY', str(-100 - index), 'EUR',
                security=f'SEC-{index}', quantity='1', affects_cash=False)],
        ))
    return result


def measurement(count):
    with tempfile.TemporaryDirectory(prefix='portman-phase3-') as folder:
        repository = RepositoryV09(Path(folder) / 'benchmark.sqlite', backups=False)
        statements = []
        repository.db.set_trace_callback(statements.append)
        tracemalloc.start()
        started = time.perf_counter()
        results = repository.commit_batches(batches(count))
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        persisted = sum(repository.db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                        for table in ('imports', 'snapshots', 'transactions', 'import_model_records'))
        repository.close()
    verbs = [statement.lstrip().split(' ', 1)[0].upper() for statement in statements]
    return {
        'seconds': elapsed,
        'seconds_per_batch': elapsed / count,
        'reads': verbs.count('SELECT'),
        'writes': sum(verbs.count(verb) for verb in ('INSERT', 'UPDATE', 'DELETE')),
        'peak_bytes': peak,
        'persisted_records': persisted,
        'imported': sum(result['status'] == 'imported' for result in results),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--batches', type=int, default=20)
    parser.add_argument('--repetitions', type=int, default=3)
    arguments = parser.parse_args()
    runs = [measurement(arguments.batches) for _ in range(arguments.repetitions)]
    summary = {key + '_median': statistics.median(run[key] for run in runs)
               for key in ('seconds', 'seconds_per_batch', 'reads', 'writes', 'peak_bytes',
                           'persisted_records', 'imported')}
    print(json.dumps({'batches': arguments.batches, 'runs': runs, 'summary': summary}, indent=2))


if __name__ == '__main__':
    main()
