import unittest
from decimal import Decimal
from portman_v10.domain.values import ExactValue
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

if __name__ == '__main__':
    unittest.main()
