"""Exaktheit und Anzeige der V10-05-Zahlenvarianten, ohne produktive Migration."""
import unittest
from fractions import Fraction
import sqlite3

from portman_v10.domain.rational import RationalAmount
from portman_v10.infrastructure.sqlite_decimal import (
    DECIMAL_COLLATION,
    RATIONAL_COLLATION,
    register_decimal_collation,
    register_rational_collation,
)
from portman_v10.domain.values import canonical_decimal, compare_decimal_text
from reference_cases import PARTIAL_LOT_SPLITS, REPEATING_COST_SPLIT


class NumberRepresentationTests(unittest.TestCase):
    def test_original_decimal_inputs_round_trip_for_crypto_and_large_balances(self):
        values = {
            "0.000000000000000001": "0.000000000000000001",
            "1000000000000000000000000000000": "1000000000000000000000000000000",
            "103.00": "103",
        }
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE original_amounts(value TEXT)")
        connection.executemany("INSERT INTO original_amounts VALUES (?)", [(canonical,) for canonical in values.values()])
        self.assertEqual([row[0] for row in connection.execute("SELECT value FROM original_amounts")], list(values.values()))
        connection.close()
        for value, canonical in values.items():
            with self.subTest(value=value):
                parsed = RationalAmount.from_decimal(value)
                stored = parsed.to_storage_text()
                self.assertEqual(RationalAmount.from_storage_text(stored), parsed)
                self.assertEqual(canonical_decimal(value), canonical)
                self.assertEqual(RationalAmount.from_decimal(canonical), parsed)

    def test_rational_calculation_matches_independent_fraction_golden(self):
        golden = REPEATING_COST_SPLIT.allocated_cost
        calculated = RationalAmount.from_decimal("100") * RationalAmount.from_decimal("1") / RationalAmount.from_decimal("3")
        self.assertEqual(Fraction(calculated.numerator, calculated.denominator), golden)
        self.assertEqual(calculated.to_storage_text(), "100/3")

    def test_repeated_splits_and_full_delivery_conserve_original_cost(self):
        source_lot = PARTIAL_LOT_SPLITS[0]
        original_cost = RationalAmount.from_decimal(source_lot.original_cost)
        remaining_cost = original_cost
        remaining_quantity = RationalAmount.from_decimal(source_lot.original_quantity)
        allocated = []
        for quantity_text in ("3", "2", "5"):
            quantity = RationalAmount.from_decimal(quantity_text)
            part = remaining_cost * quantity / remaining_quantity
            allocated.append(part)
            remaining_cost = remaining_cost - part
            remaining_quantity = remaining_quantity - quantity
        self.assertEqual(remaining_quantity, RationalAmount(0))
        self.assertEqual(remaining_cost, RationalAmount(0))
        self.assertEqual(sum(allocated, RationalAmount(0)), original_cost)
        # Removing all transfer contributions restores the original lot exactly.
        restored_source_cost = sum(allocated, remaining_cost)
        self.assertEqual(restored_source_cost, original_cost)

    def test_display_rounding_is_half_up_and_does_not_change_exact_value(self):
        thirds = RationalAmount(1, 3)
        self.assertEqual(thirds.display(2), "0.33")
        self.assertFalse(thirds.is_exact_at_scale(2))
        self.assertTrue(RationalAmount(1, 4).is_exact_at_scale(2))
        self.assertEqual(RationalAmount(-1, 200).display(2), "-0.01")
        self.assertEqual(RationalAmount(1, 200).display(2), "0.01")
        displayed_shares = sum((RationalAmount.from_decimal(thirds.display(2)) for _ in range(3)), RationalAmount(0))
        self.assertEqual(displayed_shares.display(2), "0.99")
        self.assertEqual((thirds + thirds + thirds).display(2), "1.00")
        self.assertEqual(thirds.to_storage_text(), "1/3")

    def test_float_inputs_are_not_accepted_as_rational_values(self):
        with self.assertRaises(ValueError):
            RationalAmount.from_decimal(0.1)
        with self.assertRaises(TypeError):
            RationalAmount(0.1)

    def test_decimal_comparator_orders_negative_large_and_tiny_values_exactly(self):
        values = ("-100000000000000000000", "-2", "-1.000000000000000001", "-1", "0", "0.000000000000000001", "1", "1.000000000000000001", "100000000000000000000")
        for lower, upper in zip(values, values[1:]):
            with self.subTest(lower=lower, upper=upper):
                self.assertEqual(compare_decimal_text(lower, upper), -1)
        self.assertEqual(compare_decimal_text("1.0", "1"), 0)
        connection = sqlite3.connect(":memory:")
        register_decimal_collation(connection)
        connection.execute(f"CREATE TABLE original(value TEXT COLLATE {DECIMAL_COLLATION})")
        connection.executemany("INSERT INTO original VALUES (?)", [(value,) for value in values])
        connection.execute(f"CREATE INDEX original_value ON original(value COLLATE {DECIMAL_COLLATION})")
        found = connection.execute(
            f"SELECT value FROM original WHERE value >= ? COLLATE {DECIMAL_COLLATION} ORDER BY value COLLATE {DECIMAL_COLLATION}",
            ("100000000000000000000",),
        ).fetchall()
        self.assertEqual([row[0] for row in found], ["100000000000000000000"])
        self.assertEqual(
            connection.execute(
                f"SELECT count(*) FROM original WHERE value = ? COLLATE {DECIMAL_COLLATION}",
                ("0.000000000000000001",),
            ).fetchone()[0],
            1,
        )
        connection.close()

    def test_rational_storage_supports_exact_indexed_range_search(self):
        connection = sqlite3.connect(":memory:")
        register_rational_collation(connection)
        connection.execute(f"CREATE TABLE costs(value TEXT COLLATE {RATIONAL_COLLATION})")
        connection.executemany("INSERT INTO costs VALUES (?)", [(value,) for value in ("-100/3", "1/3", "2/3", "1/1", "100000000000000000000/1")])
        connection.execute(f"CREATE INDEX costs_value ON costs(value COLLATE {RATIONAL_COLLATION})")
        rows = connection.execute(
            f"SELECT value FROM costs WHERE value >= ? COLLATE {RATIONAL_COLLATION} ORDER BY value COLLATE {RATIONAL_COLLATION}",
            ("1/3",),
        ).fetchall()
        self.assertEqual([row[0] for row in rows], ["1/3", "2/3", "1/1", "100000000000000000000/1"])
        plan = connection.execute(
            f"EXPLAIN QUERY PLAN SELECT value FROM costs WHERE value >= ? COLLATE {RATIONAL_COLLATION}", ("1/3",)
        ).fetchone()[3]
        self.assertIn("USING COVERING INDEX costs_value", plan)
        connection.close()


if __name__ == "__main__":
    unittest.main()
