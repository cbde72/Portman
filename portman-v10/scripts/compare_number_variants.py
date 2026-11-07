"""Reproduzierbarer SQLite-/Rechenvergleich, kein produktives Schema."""
from __future__ import annotations

import os
import sqlite3
import statistics
import tempfile
import time
from pathlib import Path

from portman_v10.domain.rational import RationalAmount
from portman_v10.infrastructure.sqlite_decimal import (
    DECIMAL_COLLATION,
    RATIONAL_COLLATION,
    register_decimal_collation,
    register_rational_collation,
)
from portman_v10.domain.values import canonical_decimal, sum_decimal_text


ROW_COUNT = 100_000
SCALE = 6
SCALE_FACTOR = 10**SCALE


def source_value(index: int) -> str:
    return canonical_decimal(f"{index}.{(index * 123457) % SCALE_FACTOR:06d}")


def scaled_integer(value: str) -> int:
    whole, separator, fraction = value.partition(".")
    if not separator:
        fraction = ""
    if len(fraction) > SCALE:
        raise ValueError(f"Wert überschreitet die feste Skala {SCALE}: {value}")
    result = int(whole) * SCALE_FACTOR + int(fraction.ljust(SCALE, "0"))
    if not -(2**63) <= result < 2**63:
        raise OverflowError(f"Wert überschreitet SQLite-INTEGER bei Skala {SCALE}: {value}")
    return result


def measure_variant(directory: Path, variant: str, values: tuple[str, ...]) -> dict[str, int | float]:
    path = directory / f"{variant}.sqlite"
    started = time.perf_counter()
    connection = sqlite3.connect(path)
    if variant == "decimal_text":
        register_decimal_collation(connection)
        collation = DECIMAL_COLLATION
        connection.execute(f"CREATE TABLE amounts(value TEXT COLLATE {collation})")
        connection.execute(f"CREATE INDEX amounts_value ON amounts(value COLLATE {collation})")
        encode = lambda value: value
        equality_sql = f"SELECT count(*) FROM amounts WHERE value = ? COLLATE {collation}"
        range_sql = f"SELECT count(*) FROM amounts WHERE value >= ? COLLATE {collation}"
        probe = values[54_321]
        lower_bound = values[50_000]
        probe_arg = probe
        range_arg = lower_bound
    elif variant == "scaled_integer":
        connection.execute("CREATE TABLE amounts(value INTEGER)")
        connection.execute("CREATE INDEX amounts_value ON amounts(value)")
        encode = scaled_integer
        equality_sql = "SELECT count(*) FROM amounts WHERE value = ?"
        range_sql = "SELECT count(*) FROM amounts WHERE value >= ?"
        probe_arg = scaled_integer(values[54_321])
        range_arg = scaled_integer(values[50_000])
    else:
        register_rational_collation(connection)
        connection.execute(f"CREATE TABLE amounts(value TEXT COLLATE {RATIONAL_COLLATION})")
        connection.execute(f"CREATE INDEX amounts_value ON amounts(value COLLATE {RATIONAL_COLLATION})")
        encode = lambda value: RationalAmount.from_decimal(value).to_storage_text()
        equality_sql = f"SELECT count(*) FROM amounts WHERE value = ? COLLATE {RATIONAL_COLLATION}"
        range_sql = f"SELECT count(*) FROM amounts WHERE value >= ? COLLATE {RATIONAL_COLLATION}"
        probe_arg = encode(values[54_321])
        range_arg = encode(values[50_000])
    connection.executemany("INSERT INTO amounts VALUES (?)", ((encode(value),) for value in values))
    connection.commit()
    load_ms = (time.perf_counter() - started) * 1000

    def median_query(sql: str, parameter: str | int) -> tuple[float, int]:
        durations = []
        count = 0
        for _ in range(9):
            tick = time.perf_counter()
            count = connection.execute(sql, (parameter,)).fetchone()[0]
            durations.append((time.perf_counter() - tick) * 1000)
        return statistics.median(durations), count

    equality_ms, equality_count = median_query(equality_sql, probe_arg)
    range_ms, range_count = median_query(range_sql, range_arg)
    if equality_count != 1 or range_count != ROW_COUNT - 50_000:
        raise AssertionError(f"{variant}: unerwartete Suchresultate {equality_count}/{range_count}")
    plan = connection.execute(f"EXPLAIN QUERY PLAN {range_sql}", (range_arg,)).fetchone()[3]
    if "USING" not in plan or "amounts_value" not in plan:
        raise AssertionError(f"{variant}: Bereichsabfrage verwendet den Index nicht: {plan}")
    connection.close()
    return {
        "load_ms": round(load_ms, 2),
        "equality_median_ms": round(equality_ms, 4),
        "range_median_ms": round(range_ms, 4),
        "sqlite_bytes": os.path.getsize(path),
    }


def measure_sums(values: tuple[str, ...]) -> dict[str, float]:
    start = time.perf_counter()
    text_total = sum_decimal_text(values)
    text_ms = (time.perf_counter() - start) * 1000

    start = time.perf_counter()
    scaled_total = sum(scaled_integer(value) for value in values)
    scaled_result = RationalAmount(scaled_total, SCALE_FACTOR)
    integer_ms = (time.perf_counter() - start) * 1000

    start = time.perf_counter()
    rational_total = RationalAmount(0)
    for value in values:
        rational_total += RationalAmount.from_decimal(value)
    rational_ms = (time.perf_counter() - start) * 1000

    if RationalAmount.from_decimal(text_total) != scaled_result or rational_total != scaled_result:
        raise AssertionError("Die Varianten liefern unterschiedliche exakte Summen")
    return {
        "decimal_text_ms": round(text_ms, 2),
        "scaled_integer_ms": round(integer_ms, 2),
        "rational_ms": round(rational_ms, 2),
    }


def main() -> None:
    values = tuple(source_value(index) for index in range(ROW_COUNT))
    with tempfile.TemporaryDirectory(prefix="portman-number-variants-") as temporary:
        directory = Path(temporary)
        results = {
            variant: measure_variant(directory, variant, values)
            for variant in ("decimal_text", "scaled_integer", "rational_text")
        }
    print(f"rows={ROW_COUNT}; scale={SCALE}; sqlite={sqlite3.sqlite_version}")
    for variant, result in results.items():
        print(f"{variant}: {result}")
    print(f"sum_ms={measure_sums(values)}")
    try:
        scaled_integer("1000000000000000000000000000000.000000")
    except OverflowError:
        print("edge_large_scaled_integer=overflow")
    try:
        scaled_integer("0.000000000000000001")
    except ValueError:
        print("edge_crypto_scale=precision_loss_rejected")
    print("edge_text_and_rational=large_balance_and_18dp_round_trip_tested_separately")


if __name__ == "__main__":
    main()
