import os
from decimal import Decimal
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication

from portfolio_v5.accounts import account_key
from portfolio_v5.models import ImportBatch, TaxEvent, Transaction
from portfolio_v5.pdf_importer import parse_pdf
from portman.accounts_widget import AccountsWidget
from portman.repository import PortfolioRepository
from portman.repository_v09 import RepositoryV09
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


def test_foreign_gross_currency_keeps_the_eur_booking_in_the_overview():
    class ForeignRepository(Repository):
        def transactions(self):
            return [{'date': '2026-05-31', 'kind': 'DIVIDEND', 'account': 'Tagesgeld',
                     'performance_depot_key': 'depot', 'amount': '75', 'gross_income': '100',
                     'gross_currency': 'USD', 'taxes': '10', 'currency': 'EUR'}]

    values = automatic_tax_values(ForeignRepository(), 2026)

    # The USD document no longer drops the EUR booking; capital income is the
    # EUR reconstruction (75 + 10) instead of an USD amount in an EUR sum.
    assert values['depot']['dividends'] == Decimal('75')
    assert values['depot']['capital_income'] == Decimal('85')
    assert values['depot']['taxes'] == Decimal('10')


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


def test_imported_vorabpauschale_consumes_only_taxable_exemption_amount(tmp_path):
    repository = PortfolioRepository(tmp_path / 'advance-tax.sqlite')
    repository.save_account('comdirect Depot', {'institution': 'comdirect', 'kind': 'Depot', 'exemption': '300'})
    repository.store.import_batch(ImportBatch('tax.pdf', 'tax-hash', account_names=['comdirect Depot'], tax_events=[
        TaxEvent('advance-1', 'comdirect Depot', 'vorabpauschale_ausland', '2020-01-02',
                 tax_year='2020', security_ref='IE00BKM4GZ66', currency='EUR', taxable_income='8.77',
                 advance_tax_base='12.54', partial_exemption_amount='3.77', used_exemption='8.77',
                 after_partial_exemption='8.77',
                 partial_exemption_rate='30')]))

    values = automatic_tax_values(repository, 2020)['comdirect depot']
    assert values['capital_income'] == Decimal('8.77')
    assert values['advance_tax_base'] == Decimal('12.54')
    assert values['advance_tax_taxable'] == Decimal('8.77')
    assert values['advance_tax_count'] == 1
    assert values['partial_exemption'] == Decimal('3.77')
    assert values['used_exemption'] == Decimal('8.77')
    _, institutions = tax_overview(repository, 2020)
    assert institutions['comdirect']['used_exemption'] == Decimal('8.77')
    assert institutions['comdirect']['remaining_exemption'] == Decimal('291.23')
    assert institutions['comdirect']['advance_tax_base'] == Decimal('12.54')
    repository.close()


def test_advance_taxable_basis_is_derived_only_from_complete_evidence(tmp_path):
    repository = PortfolioRepository(tmp_path / 'advance-tax-fallback.sqlite')
    repository.save_account('Depot', {'institution': 'comdirect', 'kind': 'Depot', 'exemption': '100'})
    repository.store.import_batch(ImportBatch('tax.pdf', 'tax-fallback', tax_events=[
        TaxEvent('complete', 'Depot', 'vorabpauschale_ausland', '2026-01-02', tax_year='2026',
                 income_year='2025', security_ref='COMPLETE',
                 advance_tax_base='12.54', partial_exemption_amount='3.77'),
        TaxEvent('incomplete', 'Depot', 'vorabpauschale_ausland', '2026-01-03', tax_year='2026',
                 income_year='2025', security_ref='INCOMPLETE', advance_tax_base='25.00')]))

    values = automatic_tax_values(repository, 2026)['depot']
    assert values['advance_tax_base'] == Decimal('37.54')
    assert values['advance_tax_taxable'] == Decimal('8.77')
    assert values['capital_income'] == Decimal('8.77')
    repository.save_institution_tax_record(
        'comdirect', 2026, exemption='100', capital_income='', taxes='',
        partial_exemption='', used_exemption='')
    _, institutions = tax_overview(repository, 2026)
    # The evidenced 3.77 EUR exemption is already reflected in 8.77 EUR and
    # must not be subtracted for a second time.
    assert institutions['comdirect']['used_exemption'] == Decimal('8.77')
    repository.close()


REAL_ADVANCE_TAX = Path(r'C:\Users\chris\Desktop\history\comdirect\2026\Steuerinformationen')


@pytest.mark.skipif(not REAL_ADVANCE_TAX.is_dir(), reason='comdirect real corpus is not available')
def test_three_real_comdirect_advance_taxes_use_post_exemption_basis(tmp_path):
    paths = [next(REAL_ADVANCE_TAX.glob(f'Steuermitteilung_{wkn}_*.pdf'))
             for wkn in ('A1JJTF', 'A111X9', 'A2H57N')]
    batches = [parse_pdf(path) for path in paths]
    expected = {
        'IE00B48X4842': ('37.75', '11.33', '26.42'),
        'IE00BKM4GZ66': ('137.65', '41.30', '96.35'),
        'LU1681041973': ('99.25', '29.78', '69.47'),
    }
    repository = RepositoryV09(tmp_path / 'real-advance-tax.sqlite', backups=False)
    try:
        repository.save_account('Depot 4764924', {'institution': 'comdirect', 'kind': 'Depot'})
        for batch in batches:
            event = batch.tax_events[0]
            assert (event.advance_tax_base, event.partial_exemption_amount,
                    event.taxable_income) == expected[event.security_ref]
            assert (event.date, event.tax_year, event.income_year) == (
                '2026-01-02', '2026', '2025')
            batch.account_assignments = {
                account_key(event.account): account_key('Depot 4764924')}
            repository.commit_batches([batch])

        values = automatic_tax_values(repository, 2026)['depot 4764924']
        assert values['advance_tax_base'] == Decimal('274.65')
        assert values['partial_exemption'] == Decimal('82.41')
        assert values['advance_tax_taxable'] == Decimal('192.24')
        assert values['capital_income'] == Decimal('192.24')
        assert values['advance_tax_count'] == 3
        assert repository.transactions() == []
        assert repository.holdings() == []
    finally:
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
    dialog.institutions.item(0, 7).setText('42,50')
    dialog.institutions.item(0, 9).setText('8,25')
    dialog.institutions.item(0, 11).setText('0,45')
    dialog.institutions.item(0, 12).setText('5,00')
    dialog.institutions.item(0, 13).setText('37,50')
    dialog.institutions.item(0, 16).setText('Steuerbescheinigung')

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
