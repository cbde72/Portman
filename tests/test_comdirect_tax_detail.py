import csv
from decimal import Decimal
from pathlib import Path

from portfolio_v5.comdirect_tax_detail import COLUMNS, GROUPS, parse_comdirect_tax_detail
from portfolio_v5.models import ImportBatch, TaxEvent
from portman.repository_v09 import RepositoryV09
from portman.tax_overview import automatic_tax_values


def write_export(path, rows):
    with path.open('w', encoding='cp1252', newline='') as stream:
        writer = csv.writer(stream, delimiter=';')
        writer.writerows([
            ['Export erstellt am:', '13.10.2026 12:27 Uhr'],
            ['Institut:', 'comdirect - Testinstitut'], [], ['Steuerliche Detailansicht'], [],
            [*COLUMNS, ''], *[[*(row.get(column, '') for column in COLUMNS), ''] for row in rows]])


def advance_tax(**changes):
    row = {column: '0,00' for column in COLUMNS}
    row.update({'Steuerjahr': '2026', 'Buchungstag': '19.01.2026',
        'Steuerliches Datum': '02.01.2026', 'Referenznummer': 'ANON-REF-001',
        'Vorgang': 'Vorabpauschale Ausland', 'Stück/Nominale': '234,36',
        'Bezeichnung': 'ANONYMISIERTER ETF', 'WKN': 'A111X9',
        'BMG nach VV': '96,35', 'Veränderung FSA': '-96,35', 'BMG nach FSA': '0,00',
        'Summe Steuern': '0,00', 'Steuerbemessungsgrundlage': '96,35'})
    row.update(changes)
    return row


def test_parser_preserves_all_32_original_columns(tmp_path):
    source = tmp_path / 'steuerdetails_ANON_20261013.csv'; write_export(source, [advance_tax()])
    batch = parse_comdirect_tax_detail(source, account='Depot Test')
    record = batch.tax_details[0]
    assert len(COLUMNS) == sum(len(columns) for columns in GROUPS.values()) == 32
    assert tuple(record.original_values) == COLUMNS
    assert record.original_values['Stück/Nominale'] == '234,36'
    assert record.original_values['Veränderung FSA'] == '-96,35'
    assert batch.transactions == [] and batch.tax_events == []


def test_repeated_and_overlapping_exports_do_not_duplicate_rows(tmp_path):
    first = tmp_path / 'first.csv'; second = tmp_path / 'second.csv'
    write_export(first, [advance_tax()]); write_export(second, [advance_tax()])
    repo = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    try:
        repo.commit_batches([parse_comdirect_tax_detail(first, account='Depot Test')])
        repo.commit_batches([parse_comdirect_tax_detail(second, account='Depot Test')])
        assert len(repo.tax_detail_records()) == 1
    finally: repo.close()


def test_pdf_event_wins_over_csv_without_quantity_or_cash_mutation(tmp_path):
    source = tmp_path / 'tax.csv'; write_export(source, [advance_tax()])
    repo = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    try:
        repo.commit_batches([ImportBatch('pdf', 'pdf', account_names=['Depot Test'], tax_events=[TaxEvent(
            'pdf-event', 'Depot Test', 'vorabpauschale_ausland', '2026-01-02', tax_year='2026',
            income_year='2025', document_date='2026-01-19', security_ref='A111X9', quantity='234.356',
            advance_tax_base='137.65', partial_exemption_amount='41.30', taxable_income='96.35',
            used_exemption='96.35', paid_taxes='0.00', reference_no='ANON-REF-001')])])
        repo.commit_batches([parse_comdirect_tax_detail(source, account='Depot Test')])
        detail = repo.tax_detail_records()[0]
        assert detail['linked_tax_event_id'] == 'pdf-event'
        assert (detail['booking_date'], detail['tax_date'], detail['document_date'], detail['income_year']) == (
            '2026-01-19', '2026-01-02', '2026-01-19', '2025')
        assert repo.tax_events()[0]['quantity'] == '234.356'
        assert repo.transactions() == [] and repo.holdings() == []
        values = automatic_tax_values(repo, 2026)
        key = next(iter(values))
        assert values[key]['advance_tax_base'] == Decimal('137.65')
        assert values[key]['advance_tax_taxable'] == Decimal('96.35')
        assert values[key]['used_exemption'] == Decimal('96.35')
    finally: repo.close()


def test_csv_only_advance_tax_is_cash_neutral_overview_fallback(tmp_path):
    source = tmp_path / 'tax.csv'; write_export(source, [advance_tax()])
    repo = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    try:
        repo.commit_batches([parse_comdirect_tax_detail(source, account='Depot Test')])
        values = automatic_tax_values(repo, 2026); item = next(iter(values.values()))
        assert item['advance_tax_taxable'] == Decimal('96.35')
        assert item['used_exemption'] == Decimal('96.35')
        assert item['taxes'] == 0
        assert repo.transactions() == []
    finally: repo.close()


def test_refund_and_loss_offset_original_values_remain_distinct(tmp_path):
    source = tmp_path / 'tax.csv'
    write_export(source, [advance_tax(**{'Vorgang': 'Steuererstattung',
        'verrechneter Verlust Sonstige': '-12,34', 'Kapitalertragssteuer': '3,08',
        'Summe Steuern': '3,25', 'Gewinn/Verlust nach Steuern': '15,59'})])
    row = parse_comdirect_tax_detail(source, account='Konto Test').tax_details[0].original_values
    assert row['verrechneter Verlust Sonstige'] == '-12,34'
    assert row['Kapitalertragssteuer'] == '3,08'
    assert row['Summe Steuern'] == '3,25'


def test_detail_view_exposes_all_columns_and_filters(tmp_path, qapp):
    from portman.tax_detail_view import TaxDetailDialog
    source = tmp_path / 'tax.csv'; write_export(source, [advance_tax()])
    repo = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    try:
        repo.commit_batches([parse_comdirect_tax_detail(source, account='Depot Test')])
        dialog = TaxDetailDialog(repo)
        assert dialog.model.columnCount() == 32
        assert dialog.proxy.rowCount() == 1
        dialog.search.setText('nicht vorhanden')
        assert dialog.proxy.rowCount() == 0
        dialog.close()
    finally: repo.close()
