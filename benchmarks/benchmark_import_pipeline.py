"""Reproducible synthetic benchmark for Portman V09 CSV parse and persistence.

Run from the repository root, for example::

    python benchmarks/benchmark_import_pipeline.py --rows 1000 10000 50000 --runs 3

The generated records are deterministic and contain no personal data. Timings
measure the parser and a fresh SQLite commit separately; they are not claims
about PDF extraction or OCR performance.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import tempfile
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from portman.import_v09 import parse_profile_csv  # noqa: E402
from portman.repository_v09 import RepositoryV09  # noqa: E402


PROFILE = {
    "delimiter": ";",
    "decimal": ",",
    "thousands": ".",
    "date_format": "%d.%m.%Y",
    "columns": {
        "external_id": "id",
        "account": "account",
        "date": "date",
        "value_date": "value_date",
        "kind": "kind",
        "amount": "amount",
        "currency": "currency",
        "purpose": "purpose",
        "bank_reference": "reference",
    },
}


def create_csv(path: Path, rows: int) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(("id", "account", "date", "value_date", "kind", "amount",
                         "currency", "purpose", "reference"))
        for index in range(rows):
            day = index % 28 + 1
            writer.writerow((f"synthetic-{index}", "Benchmarkkonto", f"{day:02d}.01.2026",
                             f"{day:02d}.01.2026", "BANK_BOOKING", "-1,23", "EUR",
                             "Synthetische Benchmarkbuchung", f"REF-{index}"))


def measure(rows: int, runs: int, folder: Path) -> dict:
    source = folder / f"transactions-{rows}.csv"
    create_csv(source, rows)
    parse_samples = []
    commit_samples = []
    for run in range(runs):
        started = perf_counter()
        batch = parse_profile_csv(source, PROFILE)
        parse_samples.append((perf_counter() - started) * 1000)
        if batch.errors or len(batch.transactions) != rows:
            raise RuntimeError(f"Benchmarkdaten nicht vollständig gelesen: {batch.errors[:3]}")
        repo = RepositoryV09(folder / f"commit-{rows}-{run}.sqlite", backups=False)
        try:
            started = perf_counter()
            result = repo.commit_batches([batch])[0]
            commit_samples.append((perf_counter() - started) * 1000)
            if result.get("transactions") != rows:
                raise RuntimeError(f"Benchmarkdaten nicht vollständig gespeichert: {result}")
        finally:
            repo.close()
    return {
        "rows": rows,
        "runs": runs,
        "file_bytes": source.stat().st_size,
        "parse_ms_median": round(statistics.median(parse_samples), 3),
        "parse_rows_per_second": round(rows / (statistics.median(parse_samples) / 1000), 1),
        "commit_ms_median": round(statistics.median(commit_samples), 3),
        "commit_rows_per_second": round(rows / (statistics.median(commit_samples) / 1000), 1),
        "parse_ms_samples": [round(value, 3) for value in parse_samples],
        "commit_ms_samples": [round(value, 3) for value in commit_samples],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", nargs="+", type=int, default=(1000, 10000, 50000))
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    if args.runs < 1 or any(value < 1 for value in args.rows):
        parser.error("rows and runs must be positive")
    with tempfile.TemporaryDirectory(prefix="portman-import-benchmark-") as temporary:
        results = [measure(rows, args.runs, Path(temporary)) for rows in args.rows]
    print(json.dumps({"benchmark": "synthetic_profile_csv", "results": results}, indent=2))


if __name__ == "__main__":
    main()
