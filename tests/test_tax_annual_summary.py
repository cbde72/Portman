import csv
from decimal import Decimal

from portfolio_v5.comdirect_tax_detail import COLUMNS, parse_comdirect_tax_detail
from portman.repository_v09 import RepositoryV09
from portman.tax_annual_summary import METRICS, TaxAnnualSummaryDialog, tax_annual_summaries


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
