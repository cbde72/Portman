import os
from decimal import Decimal

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from portman.income_basis import dividend_amounts
from portman.income_costs_widget import income_cost_rows


class Repository:
    def __init__(self, transactions):
        self._transactions = transactions

    def account_records(self):
        return [{'account_key': 'depot', 'name': 'Depot', 'parent_key': None, 'active': True,
                 'details': '{"kind": "Depot"}'}]

    def fee_links(self):
        return []

    def transactions(self):
        return self._transactions


def dividend(**changes):
    values = dict(date='2026-05-31', kind='DIVIDEND', performance_depot_key='depot',
                  account='Cash', amount='300', currency='EUR', security='US0378331005',
                  import_id='test', external_id='div')
    values.update(changes)
    return values


def test_foreign_documented_gross_never_enters_the_booking_currency_sum():
    net, gross = dividend_amounts(dividend(gross_income='400', gross_currency='USD', taxes='60'))

    assert net == Decimal('300')
    # EUR reconstruction from booked components instead of the USD 400 document.
    assert gross == Decimal('360')


def test_euro_documented_gross_wins_over_reconstruction():
    net, gross = dividend_amounts(dividend(gross_income='400', gross_currency='EUR', taxes='100'))

    assert (net, gross) == (Decimal('300'), Decimal('400'))


def test_gross_basis_booking_is_gross_and_not_gross_plus_components():
    net, gross = dividend_amounts(dividend(amount='100', taxes='25', income_basis='gross'))

    # income_basis='gross' means the booked amount already is the gross credit
    # (docs/pdf-import.md); the components are deductions from it.
    assert (net, gross) == (Decimal('75'), Decimal('100'))


def test_missing_gross_falls_back_to_amount_plus_components():
    net, gross = dividend_amounts(dividend(taxes='100'))

    assert (net, gross) == (Decimal('300'), Decimal('400'))


def test_income_cost_rows_apply_the_shared_net_gross_rule():
    rows = income_cost_rows(Repository([
        dividend(gross_income='400', gross_currency='USD', taxes='60'),
        dividend(date='2026-06-30', external_id='div2', amount='100', taxes='25',
                 income_basis='gross'),
        dict(date='2026-07-31', kind='FEE', performance_depot_key='depot', account='Cash',
             amount='-2', currency='EUR', import_id='test', external_id='fee'),
    ]), 'depot')
    by_date = {row['date']: row for row in rows}

    assert (by_date['2026-05-31']['net_dividend'], by_date['2026-05-31']['gross_dividend']) == (
        Decimal('300'), Decimal('360'))
    assert (by_date['2026-06-30']['net_dividend'], by_date['2026-06-30']['gross_dividend']) == (
        Decimal('75'), Decimal('100'))
    assert by_date['2026-07-31']['fees'] == Decimal('2')
