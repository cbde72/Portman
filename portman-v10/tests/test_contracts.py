import unittest
from decimal import Decimal
from portman_v10.domain.values import ExactValue, canonical_decimal, sum_decimal_text
from portman_v10.application.contracts import RollbackSelection

class ContractTests(unittest.TestCase):
    def test_crypto_roundtrip(self):
        value = ExactValue('12345678901234567890.000000000000000001')
        self.assertEqual(str(value.decimal), value.text)

    def test_float_nan_exponent_rejected(self):
        for value in (0.1, 'NaN', 'Infinity', '1e-18', '', '01.0'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ExactValue(value)

    def test_unknown_is_not_zero(self):
        self.assertEqual(ExactValue('0').decimal, Decimal(0))
        with self.assertRaises(ValueError):
            ExactValue(None)

    def test_rollback_requires_explicit_scope(self):
        for ids, all_imports in (((), False), (('a',), True)):
            with self.assertRaises(ValueError):
                RollbackSelection(ids, all_imports)
        self.assertTrue(RollbackSelection(all_imports=True).all_imports)
        self.assertEqual(RollbackSelection(('a',)).import_ids, ('a',))

    def test_decimal_canonicalization_and_sum_ignore_context_precision(self):
        self.assertEqual(canonical_decimal('-0.000'), '0')
        self.assertEqual(canonical_decimal('120.3400'), '120.34')
        self.assertEqual(
            sum_decimal_text(('999999999999999999999999999999.999999999999999999', '0.000000000000000001')),
            '1000000000000000000000000000000',
        )
        self.assertEqual(sum_decimal_text(('-1.2', '0.15', '0.05')), '-1')

    def test_decimal_strings_can_be_range_searched_with_sqlite_index(self):
        import sqlite3

        from portman_v10.infrastructure.sqlite_decimal import DECIMAL_COLLATION, register_decimal_collation

        connection = sqlite3.connect(':memory:')
        register_decimal_collation(connection)
        connection.execute(f'CREATE TABLE amounts (value TEXT COLLATE {DECIMAL_COLLATION})')
        connection.executemany('INSERT INTO amounts VALUES (?)', [(value,) for value in ('100', '2', '10', '-2', '1.000000000000000001')])
        connection.execute(f'CREATE INDEX amounts_value ON amounts(value COLLATE {DECIMAL_COLLATION})')
        found = connection.execute(
            f'SELECT value FROM amounts WHERE value >= ? COLLATE {DECIMAL_COLLATION} ORDER BY value COLLATE {DECIMAL_COLLATION}',
            ('2',),
        ).fetchall()
        self.assertEqual([row[0] for row in found], ['2', '10', '100'])
        plan = connection.execute(
            f'EXPLAIN QUERY PLAN SELECT value FROM amounts WHERE value >= ? COLLATE {DECIMAL_COLLATION}', ('2',)
        ).fetchone()[3]
        self.assertIn('USING COVERING INDEX amounts_value', plan)
        connection.close()

if __name__ == '__main__':
    unittest.main()
