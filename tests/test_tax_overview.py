import os
from decimal import Decimal

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from portfolio_v5.models import ImportBatch, Transaction
from portman.accounts_widget import AccountsWidget
from portman.repository import PortfolioRepository
from portman.tax_overview import TaxOverviewDialog, automatic_tax_values, tax_overview


class Repository:
    def account_records(self):
        return [
            {'account_key': 'depot', 'name': 'Depot', 'parent_key': None, 'active': True,
             'details': '{"institution": "Bank A"}'},
            {'account_key': 'tagesgeld', 'name': 'Tagesgeld', 'parent_key': None, 'active': True,
             'details': '{"institution": "Bank A"}'},
            {'account_key': 'giro', 'name': 'Giro', 'parent_key': None, 'active': True,
             'details': '{"institution": "Bank B"}'},
        ]

    def transactions(self):
        return [
            {'date': '2026-03-01', 'kind': 'DIVIDEND', 'account': 'Tagesgeld',
             'performance_depot_key': 'depot', 'amount': '75', 'gross_income': '100',
             'taxes': '25', 'withholding_tax': '15', 'currency': 'EUR',
             'tax_items': [{'kind': 'kapitalertragsteuer', 'amount': '23.70'},
                           {'kind': 'solidaritaetszuschlag', 'amount': '1.30'}]},
            {'date': '2026-06-30', 'kind': 'INTEREST', 'account': 'Tagesgeld',
             'amount': '20', 'currency': 'EUR'},
            {'date': '2026-09-30', 'kind': 'BANK_BOOKING', 'account': 'Tagesgeld',
             'amount': '5', 'currency': 'EUR', 'booking_text': 'Zinsgutschrift'},
            {'date': '2026-01-01', 'kind': 'TAX', 'account': 'Giro',
             'amount': '-3', 'currency': 'EUR'},
            {'date': '2025-12-31', 'kind': 'INTEREST', 'account': 'Tagesgeld',
             'amount': '999', 'currency': 'EUR'},
        ]

    def fee_links(self):
        return []

    def account_tax_records(self, year):
        return [
            {'account_key': 'depot', 'year': year, 'exemption': '1000',
             'capital_income': '', 'taxes': '', 'note': ''},
            {'account_key': 'tagesgeld', 'year': year, 'exemption': '500',
             'capital_income': '30', 'taxes': '2', 'note': 'Bescheinigung'},
        ]


def test_automatic_tax_values_assign_dividends_to_depot_and_interest_to_account():
    values = automatic_tax_values(Repository(), 2026)

    assert values['depot']['capital_income'] == Decimal('100')
    assert values['depot']['dividends'] == Decimal('75')
    assert values['depot']['taxes'] == Decimal('25')
    assert values['depot']['withholding_tax'] == Decimal('15')
    assert values['depot']['solidarity_surcharge'] == Decimal('1.30')
    assert values['tagesgeld']['capital_income'] == Decimal('25')
    assert values['tagesgeld']['interest'] == Decimal('25')
    assert values['giro']['taxes'] == Decimal('3')


def test_interest_uses_saved_account_key_instead_of_derived_name_key():
    class ImportedKeyRepository:
        def account_records(self):
            return [{'account_key': 'account-7f31', 'name': 'Tagesgeld PLUS', 'active': True,
                     'parent_key': None, 'details': '{"institution": "comdirect"}'}]

        def transactions(self):
            return [{'date': '2026-09-30', 'kind': 'INTEREST', 'account': 'Tagesgeld PLUS',
                     'amount': '12.34', 'gross_income': '12.34', 'gross_currency': 'EUR',
                     'currency': 'EUR'}]

        def fee_links(self):
            return []

    values = automatic_tax_values(ImportedKeyRepository(), 2026)
    assert values['account-7f31']['interest'] == Decimal('12.34')
    assert values['account-7f31']['capital_income'] == Decimal('12.34')


def test_tax_overview_prefers_manual_certificate_values_and_groups_institutions():
    accounts, institutions = tax_overview(Repository(), 2026)
    cash = next(row for row in accounts if row['account_key'] == 'tagesgeld')

    assert cash['capital_income'] == Decimal('25')
    assert cash['taxes'] == Decimal('0')
    assert institutions['Bank A']['exemption'] == Decimal('1500')
    assert institutions['Bank A']['capital_income'] == Decimal('130')
    assert institutions['Bank A']['interest_and_dividends'] == Decimal('100')
    assert institutions['Bank A']['solidarity_surcharge'] == Decimal('1.30')


def test_tax_records_are_saved_per_institution_and_year(tmp_path):
    repository = PortfolioRepository(tmp_path / 'tax.sqlite')
    repository.save_account('Tagesgeld', {'institution': 'Bank A'})

    repository.save_institution_tax_record('Bank A', 2026, '1.000,00', '123.45', '25,50',
                                           partial_exemption='10', used_exemption='90',
                                           solidarity_surcharge='1,40', note='Bescheid')
    record = repository.institution_tax_records(2026)[0]

    assert record['exemption'] == '1000.00'
    assert record['capital_income'] == '123.45'
    assert record['taxes'] == '25.50'
    assert record['partial_exemption'] == '10'
    assert record['used_exemption'] == '90'
    assert record['solidarity_surcharge'] == '1.40'
    assert record['note'] == 'Bescheid'
    repository.close()


def test_institution_tax_record_follows_institution_rename(tmp_path):
    repository = PortfolioRepository(tmp_path / 'rename.sqlite')
    repository.save_account('Tagesgeld', {'institution': 'Alte Bank'})
    repository.save_institution_tax_record('Alte Bank', 2026, exemption='500')

    repository.rename_institution('Alte Bank', 'Neue Bank')

    record = repository.institution_tax_records(2026)[0]
    assert (record['institution'], record['institution_key'], record['exemption']) == (
        'Neue Bank', 'neue bank', '500')
    repository.close()


def test_tax_overview_dialog_saves_edited_account_values(tmp_path):
    app = QApplication.instance() or QApplication([])
    repository = PortfolioRepository(tmp_path / 'dialog.sqlite')
    repository.save_account('Tagesgeld', {'institution': 'Bank A'})
    dialog = TaxOverviewDialog(repository)
    dialog.year.setValue(2026)
    dialog.institutions.item(0, 2).setText('750,00')
    dialog.institutions.item(0, 5).setText('42,50')
    dialog.institutions.item(0, 7).setText('8,25')
    dialog.institutions.item(0, 9).setText('0,45')
    dialog.institutions.item(0, 10).setText('5,00')
    dialog.institutions.item(0, 11).setText('37,50')
    dialog.institutions.item(0, 14).setText('Steuerbescheinigung')

    dialog.save()

    record = repository.institution_tax_records(2026)[0]
    assert (record['exemption'], record['capital_income'], record['taxes']) == ('750.00', '42.50', '8.25')
    assert (record['partial_exemption'], record['used_exemption']) == ('5.00', '37.50')
    assert record['solidarity_surcharge'] == '0.45'
    assert dialog.institutions.item(0, 2).text() == '750,00'
    dialog.close(); repository.close()
    assert app is not None


def test_account_overview_shows_interest_and_tax_values_directly(tmp_path):
    app = QApplication.instance() or QApplication([])
    repository = PortfolioRepository(tmp_path / 'overview.sqlite')
    repository.save_account('Tagesgeld', {'institution': 'Bank A', 'kind': 'Tagesgeld'})
    repository.commit_batches([ImportBatch('interest', 'interest', transactions=[
        Transaction('Tagesgeld', 'z1', '2026-06-30', 'INTEREST', '20', 'EUR')])])
    repository.save_institution_tax_record('Bank A', 2026, exemption='1000',
                                           partial_exemption='5', used_exemption='15')

    widget = AccountsWidget(repository, lambda: '2026-10-13')
    group = widget.tree.topLevelItem(0)
    account = group.child(0)

    assert account.text(8) == '20,00 €'
    assert account.text(9) == '20,00 €'
    assert account.text(11) == '0,00 €'
    assert account.text(12) == '0,00 €'
    assert group.text(12) == '1.000,00 €'
    assert account.text(13) == '0,00 €'
    assert account.text(14) == '0,00 €'
    assert account.text(15) == '0,00 €'
    assert group.text(13) == '5,00 €'
    assert group.text(14) == '15,00 €'
    assert group.text(15) == '985,00 €'
    assert group.text(8) == '20,00 €'
    widget.close(); repository.close()
    assert app is not None
