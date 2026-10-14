import os
from decimal import Decimal

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from portman.income_costs_widget import (
    IncomeCostsWidget, annual_dividends, annual_interest_rows, depot_years,
)


def test_annual_dividends_stacks_positions_by_year_and_currency():
    rows = [
        {'date': '2025-03-01', 'kind': 'DIVIDEND', 'security': 'A', 'currency': 'EUR',
         'net_dividend': Decimal('10.25')},
        {'date': '2025-08-01', 'kind': 'DIVIDEND', 'security': 'A', 'currency': 'EUR',
         'net_dividend': Decimal('4.75')},
        {'date': '2025-06-01', 'kind': 'DIVIDEND', 'security': 'B', 'currency': 'EUR',
         'net_dividend': Decimal('20')},
        {'date': '2026-01-01', 'kind': 'DIVIDEND', 'security': 'A', 'currency': 'USD',
         'net_dividend': Decimal('5')},
        {'date': '2025-02-01', 'kind': 'FEE', 'security': 'A', 'currency': 'EUR',
         'net_dividend': Decimal('999')},
    ]

    result = annual_dividends(rows)

    assert result['EUR']['2025'] == {'A': Decimal('15.00'), 'B': Decimal('20')}
    assert result['USD']['2026'] == {'A': Decimal('5')}


def test_annual_dividends_keeps_unassigned_position():
    result = annual_dividends([{
        'date': '2026-01-01', 'kind': 'DIVIDEND', 'security': '', 'currency': 'EUR',
        'net_dividend': Decimal('3.50'),
    }])

    assert result['EUR']['2026'][''] == Decimal('3.50')


def test_annual_dividend_chart_renders_stacked_positions():
    class Repository:
        def account_records(self):
            return [{'account_key': 'depot', 'name': 'Mein Depot', 'active': True,
                     'details': '{"kind": "Depot"}'}]

        def holdings(self, *_):
            return [{'isin': 'A', 'name': 'Alpha'}, {'isin': 'B', 'name': 'Beta'}]

        def fee_links(self):
            return []

        def transactions(self):
            base = {'kind': 'DIVIDEND', 'currency': 'EUR', 'account': 'Cash',
                    'depot': 'Mein Depot', 'performance_depot_key': 'depot'}
            return [
                {**base, 'date': '2025-03-01', 'security': 'A', 'amount': '10',
                 'import_id': 'i1', 'external_id': 'e1'},
                {**base, 'date': '2025-06-01', 'security': 'B', 'amount': '20',
                 'import_id': 'i2', 'external_id': 'e2'},
                {'kind': 'INTEREST', 'date': '2025-09-30', 'account': 'Tagesgeld',
                 'currency': 'EUR', 'amount': '8.75'},
            ]

    app = QApplication.instance() or QApplication([])
    widget = IncomeCostsWidget(Repository(), lambda: '2025-12-31')
    widget.period.setCurrentIndex(2)
    widget.annual_canvas.draw()

    axis = widget.annual_figure.axes[0]
    assert len(axis.patches) == 2
    assert {text.get_text() for text in widget.annual_figure.legends[0].texts} == {'Alpha', 'Beta'}
    assert widget.interest.rowCount() == 1
    assert widget.interest.item(0, 1).text() == 'Tagesgeld'
    assert widget.interest.item(0, 4).text() == '8.75'
    widget.period.setCurrentIndex(widget.period.findData(2025))
    assert widget.start.date().toString('yyyy-MM-dd') == '2025-01-01'
    assert widget.end.date().toString('yyyy-MM-dd') == '2025-12-31'
    widget.close()
    assert app is not None


def test_depot_years_begin_at_first_depot_state_and_include_each_year():
    class Store:
        def snapshots(self, account):
            assert account == 'Mein Depot'
            return [{'effective_date': '2022-08-31'}, {'effective_date': '2024-01-31'}]

    class Repository:
        store = Store()

        def account_records(self):
            return [{'account_key': 'depot', 'name': 'Mein Depot'}]

        def transactions(self):
            return []

    assert depot_years(Repository(), 'depot', '2026-10-13') == [2022, 2023, 2024, 2025, 2026]


def test_annual_interest_rows_cover_every_account_and_currency():
    class Repository:
        def account_records(self):
            return [
                {'account_key': 'tagesgeld', 'name': 'Tagesgeld'},
                {'account_key': 'giro', 'name': 'Girokonto'},
            ]

        def transactions(self):
            return [
                {'date': '2025-03-31', 'kind': 'INTEREST', 'account': 'Tagesgeld',
                 'currency': 'EUR', 'amount': '12.50'},
                {'date': '2025-06-30', 'kind': 'INTEREST', 'account': 'Tagesgeld',
                 'currency': 'EUR', 'amount': '7.50'},
                {'date': '2025-09-30', 'kind': 'BANK_BOOKING', 'account': 'Tagesgeld',
                 'currency': 'EUR', 'amount': '2.00', 'purpose': 'Habenzinsen Quartal'},
                {'date': '2025-12-31', 'kind': 'INTEREST', 'account': 'Girokonto',
                 'currency': 'EUR', 'amount': '1.25'},
                {'date': '2024-12-31', 'kind': 'INTEREST', 'account': 'Tagesgeld',
                 'currency': 'EUR', 'amount': '99'},
                {'date': '2025-01-01', 'kind': 'FEE', 'account': 'Girokonto',
                 'currency': 'EUR', 'amount': '-5'},
            ]

    rows = annual_interest_rows(Repository(), '2025-01-01', '2025-12-31')

    assert ('2025', 'Tagesgeld', 'EUR', 3, Decimal('22.00')) in rows
    assert ('2025', 'Girokonto', 'EUR', 1, Decimal('1.25')) in rows
    assert len(rows) == 2
