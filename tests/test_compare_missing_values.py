from decimal import Decimal
from types import SimpleNamespace

import pytest

from portfolio_v5.storage import Store


@pytest.mark.parametrize('before,after,expected', [
    (None, '120', (None, Decimal('120'), None)),
    ('100', None, (Decimal('100'), None, None)),
    (None, None, (None, None, None)),
    ('0', '120', (Decimal('0'), Decimal('120'), Decimal('120'))),
    ('100', '120', (Decimal('100'), Decimal('120'), Decimal('20'))),
])
def test_compare_unknown_values(before, after, expected):
    def holdings(day, account):
        return [dict(depot='Depot', account='Depot', key='A', name='Aktie',
                     quantity='1' if day == 'start' else '2', value=before if day == 'start' else after,
                     as_of='2026-01-01', period='2026-01')]
    row = Store.compare(SimpleNamespace(holdings=holdings), 'start', 'end')[0]
    assert (row['before'], row['after'], row['change']) == expected
    assert row['quantity_change'] == 1


@pytest.mark.parametrize('added', [True, False])
def test_compare_absent_position_is_zero(added):
    position = dict(depot='Depot', account='Depot', key='A', name='Aktie',
                    quantity='2', value='120', as_of='2026-01-01', period='2026-01')
    def holdings(day, account):
        return [position] if (day == 'end') == added else []
    row = Store.compare(SimpleNamespace(holdings=holdings), 'start', 'end')[0]
    assert row['change'] == (120 if added else -120)
    assert row['quantity_change'] == (2 if added else -2)
