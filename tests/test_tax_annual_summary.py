import csv
from decimal import Decimal

from portfolio_v5.comdirect_tax_detail import COLUMNS, parse_comdirect_tax_detail
from portfolio_v5.models import BankTransaction, ImportBatch, TaxEvent
from portman.repository_v09 import RepositoryV09
from portman.tax_annual_summary import (METRICS, TaxAnnualSummaryDialog,
                                       aggregate_tax_annual_rows, tax_annual_summaries)
from portman.tax_overview import calculate_fsa


def _write(path):
    first = {column: '0,00' for column in COLUMNS}
    first.update({'Steuerjahr': '2026', 'Buchungstag': '15.10.2026',
        'Steuerliches Datum': '15.10.2026', 'Referenznummer': 'latest',
        'Vorgang': 'Investm. Ausschüttung', 'WKN': 'A0D8Q4',
        'BMG nach FSA': '112,07', 'Kapitalertragssteuer': '-28,02',
        'Solidaritätszuschlag': '-1,51', 'Kirchensteuer': '0,00',
        'Summe Steuern': '-29,53', 'Steuerbemessungsgrundlage': '330,83',
        'Gewinn/Verlust Aktien (Saldo)': '0,00',
        'Gewinn/Verlust Sonstige (Saldo)': '523,07',
        'Umsatz anrechenbarer Quellensteuer': '0,00',
        'Veränderung Angerechnete Quellensteuer': '0,00'})
    second = dict(first)
    second.update({'Buchungstag': '02.01.2026', 'Steuerliches Datum': '02.01.2026',
                   'Referenznummer': 'advance', 'Vorgang': 'Vorabpauschale Ausland',
                   'Steuerbemessungsgrundlage': '192,24', 'BMG nach FSA': '0,00',
                   'Kapitalertragssteuer': '0,00', 'Solidaritätszuschlag': '0,00',
                   'Summe Steuern': '0,00', 'Veränderung FSA': '-411,00',
                   'Gewinn/Verlust Sonstige (Saldo)': '192,24'})
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream, delimiter=';')
        writer.writerows([['Export erstellt am:', '23.10.2026 08:45 Uhr'],
                          ['Institut:', 'comdirect'], [], ['Steuerliche Detailansicht'], [],
                          list(COLUMNS), list(first.values()), list(second.values())])


def test_summary_uses_documented_balances_and_distinguishes_unknown(tmp_path):
    source = tmp_path / 'steuerdetails_20261023-0845.csv'; _write(source)
    repo = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    try:
        repo.save_account('Depot 4764924', {'kind': 'Depot', 'institution': 'comdirect'})
        batch = parse_comdirect_tax_detail(source, account='Depot 4764924')
        assert batch.tax_details[0].source_date == '2026-10-23'
        repo.commit_batches([batch])
        row = tax_annual_summaries(repo, 2026)[0]
        assert row['as_of'] == '2026-10-23' and row['reference_rows'] == 2
        assert row['bank']['other_result'] == Decimal('523.07')
        assert row['bank']['used_exemption'] == Decimal('411.00')
        assert row['bank']['remaining_exemption'] == Decimal('0')
        assert row['bank']['capital_gains_tax'] == Decimal('28.02')
        assert row['bank']['solidarity_surcharge'] == Decimal('1.51')
        assert row['bank']['church_tax'] == Decimal('0.00')
        assert row['portman']['other_result'] == Decimal('523.07')
        assert row['portman']['stock_result'] is None
        assert len(METRICS) == 11
        assert repo.transactions() == []
    finally:
        repo.close()


def test_dialog_shows_source_date_unknown_and_proven_zero(qapp, tmp_path):
    source = tmp_path / 'steuerdetails_20261023-0845.csv'; _write(source)
    repo = RepositoryV09(tmp_path / 'dialog.sqlite', backups=False)
    try:
        repo.save_account('Depot 4764924', {'kind': 'Depot', 'institution': 'comdirect'})
        repo.commit_batches([parse_comdirect_tax_detail(source, account='Depot 4764924')])
        dialog = TaxAnnualSummaryDialog(repo)
        dialog.year.setValue(2026)
        assert '23.10.2026' in dialog.heading.text()
        assert dialog.table.rowCount() == 11
        assert dialog.table.item(0, 2).text() == 'n. v.'
        assert dialog.table.item(8, 1).text() == '1,51'
        assert dialog.table.item(9, 1).text() == '0,00'
        dialog.close()
    finally:
        repo.close()


def test_shared_institution_fsa_is_subtracted_once_for_multiple_accounts(tmp_path):
    repo = RepositoryV09(tmp_path / 'shared.sqlite', backups=False)
    try:
        repo.save_account('Depot', {'kind': 'Depot', 'institution': 'Bank A'})
        repo.save_account('Cash', {'kind': 'Tagesgeld', 'institution': 'Bank A'})
        repo.save_institution_tax_record('Bank A', 2026, exemption='411')
        repo.commit_batches([ImportBatch('facts', 'facts', tax_events=[TaxEvent(
            'advance', 'Depot', 'vorabpauschale_ausland', '2026-01-02', tax_year='2026',
            taxable_income='200.80', advance_tax_base='286.86', used_exemption='200.80')],
            transactions=[BankTransaction('Cash', 'interest', '2026-09-30', 'INTEREST', '7.94', 'EUR')])])

        rows = tax_annual_summaries(repo, 2026)
        assert len(rows) == 2
        assert all(row['portman']['remaining_exemption'] is None for row in rows)
        _bank, portman = aggregate_tax_annual_rows(rows)
        assert portman['used_exemption'] == Decimal('208.74')
        assert portman['remaining_exemption'] == Decimal('202.26')
        assert portman['remaining_exemption'] != Decimal('621.20')
    finally:
        repo.close()


def test_complete_csv_consumption_wins_for_shared_fsa_without_duplication(tmp_path):
    source = tmp_path / 'steuerdetails_20261023-0845.csv'; _write(source)
    repo = RepositoryV09(tmp_path / 'csv-shared.sqlite', backups=False)
    try:
        repo.save_account('Depot 4764924', {'kind': 'Depot', 'institution': 'comdirect'})
        repo.save_account('Tagesgeld', {'kind': 'Tagesgeld', 'institution': 'comdirect'})
        repo.save_institution_tax_record('comdirect', 2026, exemption='411')
        repo.commit_batches([ImportBatch('interest', 'interest', transactions=[
            BankTransaction('Tagesgeld', 'interest', '2026-09-30', 'INTEREST', '0.00', 'EUR')])])
        repo.commit_batches([parse_comdirect_tax_detail(source, account='Depot 4764924')])

        bank, portman = aggregate_tax_annual_rows(tax_annual_summaries(repo, 2026))
        assert bank['used_exemption'] == portman['used_exemption'] == Decimal('411.00')
        assert bank['remaining_exemption'] == portman['remaining_exemption'] == Decimal('0')
        assert portman['other_result'] == Decimal('523.07')
        assert portman['capital_gains_tax'] == Decimal('28.02')
    finally:
        repo.close()


def test_fsa_is_separate_by_institution_and_year_and_unknown_stays_unknown(tmp_path):
    repo = RepositoryV09(tmp_path / 'banks.sqlite', backups=False)
    try:
        repo.save_account('A', {'kind': 'Depot', 'institution': 'Bank A'})
        repo.save_account('B', {'kind': 'Depot', 'institution': 'Bank B'})
        repo.save_institution_tax_record('Bank A', 2026, exemption='100')
        repo.save_institution_tax_record('Bank B', 2026, exemption='300')
        repo.save_institution_tax_record('Bank A', 2025, exemption='50')
        repo.store.import_batch(ImportBatch('events', 'events', account_names=['A', 'B'], tax_events=[
            TaxEvent('a26', 'A', 'vorabpauschale', '2026-01-02', tax_year='2026',
                     income_year='2025', security_ref='AAA111', taxable_income='40',
                     advance_tax_base='40', used_exemption='40'),
            TaxEvent('b26', 'B', 'vorabpauschale', '2026-01-02', tax_year='2026',
                     income_year='2025', security_ref='BBB222', taxable_income='0',
                     advance_tax_base='0', used_exemption='0.00'),
            TaxEvent('a25', 'A', 'vorabpauschale', '2025-01-02', tax_year='2025',
                     income_year='2024', security_ref='AAA111', taxable_income='50',
                     advance_tax_base='50', used_exemption='50')]))

        rows26 = {row['institution']: row for row in tax_annual_summaries(repo, 2026)}
        assert rows26['Bank A']['portman']['remaining_exemption'] == Decimal('60')
        assert rows26['Bank B']['portman']['used_exemption'] == Decimal('0.00')
        assert rows26['Bank B']['portman']['remaining_exemption'] == Decimal('300.00')
        rows25 = tax_annual_summaries(repo, 2025)
        assert rows25[0]['portman']['remaining_exemption'] == Decimal('0')

        repo.save_account('C', {'kind': 'Tagesgeld', 'institution': 'Bank C'})
        repo.commit_batches([ImportBatch('unknown', 'unknown', transactions=[
            BankTransaction('C', 'interest', '2026-06-30', 'INTEREST', '1', 'EUR')])])
        unknown = next(row for row in tax_annual_summaries(repo, 2026) if row['institution'] == 'Bank C')
        assert unknown['portman']['used_exemption'] is None
        assert unknown['portman']['remaining_exemption'] is None
    finally:
        repo.close()


def test_automatic_fsa_uses_complete_taxable_basis_without_csv_or_double_partial_exemption(tmp_path):
    repo = RepositoryV09(tmp_path / 'automatic.sqlite', backups=False)
    try:
        repo.save_account('Depot', {'kind': 'Depot', 'institution': 'comdirect'})
        repo.save_account('Cash', {'kind': 'Girokonto', 'institution': 'comdirect'})
        repo.save_institution_tax_record('comdirect', 2026, exemption='411')
        repo.commit_batches([ImportBatch('tax facts', 'tax facts', tax_events=[
            TaxEvent('advance', 'Depot', 'vorabpauschale_ausland', '2026-01-02', tax_year='2026',
                     taxable_income='192.24', partial_exemption_amount='82.41', loss_offset='0.00'),
            TaxEvent('funds', 'Depot', 'investment_ausschuettung_inland', '2026-09-15', tax_year='2026',
                     taxable_income='314.33', partial_exemption_amount='134.71', loss_offset='0.00'),
            TaxEvent('shares', 'Depot', 'dividende_inland', '2026-05-08', tax_year='2026',
                     taxable_income='8.56', loss_offset='0.00')], transactions=[
            BankTransaction('Cash', 'interest', '2026-09-30', 'INTEREST', '7.94', 'EUR')])])

        rows = tax_annual_summaries(repo, 2026)
        _bank, portman = aggregate_tax_annual_rows(rows)
        calculation = rows[0]['fsa_calculation']
        assert calculation['taxable_income'] == Decimal('523.07')
        assert calculation['used_exemption'] == portman['used_exemption'] == Decimal('411.00')
        assert calculation['remaining_exemption'] == portman['remaining_exemption'] == Decimal('0')
        assert calculation['taxable_after_fsa'] == Decimal('112.07')
        assert calculation['status'] == 'aus Portman-Steuerdaten berechnet'
        assert repo._imported_tax_detail_records(tax_year=2026) == []
    finally:
        repo.close()


def test_fsa_calculation_applies_losses_before_fsa_and_preserves_known_zero():
    partial = calculate_fsa('411', '300', loss_offset='50')
    assert partial['eligible_income'] == Decimal('250')
    assert partial['used_exemption'] == Decimal('250')
    assert partial['remaining_exemption'] == Decimal('161')
    assert partial['taxable_after_fsa'] == Decimal('0')

    zero = calculate_fsa('411', '0', loss_offset='0', documented_used='0.00')
    assert zero['used_exemption'] == Decimal('0')
    assert zero['remaining_exemption'] == Decimal('411')
    assert zero['documented_used_exemption'] == Decimal('0.00')
    assert zero['status'] == 'bankseitig nachgewiesen'

    qualified = calculate_fsa('411', '523.07', loss_offset='0', loss_offset_known=False)
    assert qualified['used_exemption'] == Decimal('411')
    assert qualified['taxable_after_fsa'] == Decimal('112.07')
    assert not qualified['complete']
    assert 'nicht vollständig' in qualified['status']
