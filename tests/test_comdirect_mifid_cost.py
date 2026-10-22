import importlib.util
from pathlib import Path

import pytest

from portfolio_v5.accounts import account_key
from portfolio_v5.models import ImportBatch
from portfolio_v5.pdf_plugins import ParseContext, PdfDocument, PdfPage
from portman.repository_v09 import RepositoryV09


ROOT = Path(__file__).resolve().parents[1]
REAL_COSTS = Path(r'C:\Users\chris\Desktop\history\comdirect\2026\Kosteninformationen')


def plugin():
    path = ROOT / 'pdf_plugins' / 'comdirect_ertraege.py'
    spec = importlib.util.spec_from_file_location('comdirect_mifid_cost', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.plugin


def cost_text(*, wkn='578560', name='FRESENIUS SE+CO.KGAA O.N.', total='60,81',
              total_pct='0,66', include_foreign=True, include_product=True,
              include_inducement=True, isin='', file_number='6CC595',
              document_date='06.08.2026'):
    """Synthetic comdirect MiFID-II document with the native text layout."""
    foreign = ('' if not include_foreign else
               '- Dienstleistungskosten fremd                                           3,00 EUR\n'
               '                                                                        0,15 % p.a.\n')
    product = ('' if not include_product else
               '- Produktkosten (nach Zahlung von Dritten)                               5,00 EUR\n'
               '                                                                        0,25 % p.a.\n')
    inducement = ('' if not include_inducement else
                  'Davon erhält die Bank von Dritten 1,00 EUR\n')
    isin_line = f'ISIN: {isin}\n' if isin else ''
    return f'''comdirect bank AG
Kosteninformation zum Wertpapiergeschäft  {document_date} - 15:17 Uhr
Kundennummer: 123 456 789
{name}
WKN: {wkn}
{isin_line}Sparplan: 51,63 EUR mtl.
Sparbetrag pro Jahr: 619,56 EUR
Ausführungsplatz: Tradegate
Abrechnung in EUR

Kosten des Wertpapierkaufes, pro Jahr 9,16 EUR
Orderprovision [E] 9,16 EUR

Kosten während der Haltedauer (pro Jahr) 0,00 EUREUR
Depotentgelt [E] 0,00 EUR

Kosten des Wertpapierverkaufes 15,03 EUR
Börsenplatzabhängiges Entgelt [E] 2,50 EUR
Orderprovision [E] 12,53 EUR

angenommene Laufzeit von 5 Jahr(en) und einer Haltedauer von 5 Jahr(en)
Die voraussichtlichen Gesamtkosten auf {total} EUR und reduzieren die Rendite um
durchschnittlich {total_pct} % pro Jahr.

Gesamtkosten im Detail:
- Dienstleistungskosten der Bank                                              52,81 EUR
                                                                              {total_pct} % p.a.
{inducement}{foreign}{product}
Sparbetrag kumuliert       Kosten des Wertpapierkaufes       Kosten während der Haltedauer       Gesamtkosten       Auswirkung auf die Rendite
Im 1. Jahr                       619,56 EUR               9,16 EUR               0,00 EUR               9,16 EUR                -1,50 %
Im 2. Jahr                     1.239,12 EUR               9,16 EUR               0,00 EUR               9,16 EUR                -0,75 %
Im 3. Jahr                     1.858,68 EUR               9,16 EUR               0,00 EUR               9,16 EUR                -0,50 %
Im 4. Jahr                     2.478,24 EUR               9,16 EUR               0,00 EUR               9,16 EUR                -0,37 %
Im 5. Jahr                     3.097,80 EUR               9,16 EUR               0,00 EUR               9,16 EUR                -0,30 %
Wertpapierverkauf              3.097,80 EUR                                                           15,03 EUR                 -0,49 %
'''


def document(text=None, file_hash='mifid-hash-1', path=None):
    return PdfDocument(
        path or Path(f'Kosteninformation_Sparplan_Nr._38_578560_(Test)_vom_06.08.2026_6CC595.pdf'),
        b'%PDF-1.4\n%%EOF\n', file_hash, (PdfPage(1, text or cost_text()),))


def parse(source=None, file_hash=None):
    source = source or document()
    detected = plugin().detect(source)
    assert detected and detected[0].handler_id == 'kosteninformation_mifid_ii'
    return plugin().parse(source, detected[0], ParseContext(
        ImportBatch(str(source.path), file_hash or source.file_hash, source_sheet='PDF')))


def test_mifid_cost_is_detected_and_structured_without_economic_bookings():
    batch = parse()
    report = batch.cost_reports[0]
    assert batch.errors == []
    assert batch.transactions == [] and batch.snapshots == [] and batch.balances == []
    assert batch.tax_events == [] and batch.tax_details == [] and batch.events == []
    assert len(batch.documents) == 1 and len(batch.securities) == 1
    assert batch.documents[0].document_type.endswith('keine ausgeführte Transaktion')
    assert 'keine ausgeführte Transaktion' in batch.documents[0].title
    assert (report.document_date, report.document_time) == ('2026-08-06', '15:17')
    assert (report.wkn, report.isin, report.security_name) == (
        '578560', '', 'FRESENIUS SE+CO.KGAA O.N.')
    assert (report.reference, report.sparplan_number) == ('6CC595', '38')
    assert (report.monthly_savings, report.annual_savings) == ('51.63', '619.56')
    assert (report.purchase_costs, report.holding_costs, report.sale_costs) == (
        '9.16', '0.00', '15.03')
    assert (report.total_costs, report.ongoing_pct) == ('60.81', '0.66')
    assert (report.service_costs, report.service_pct) == ('52.81', '0.66')
    assert (report.overhead_costs, report.foreign_pct) == ('3.00', '0.15')
    assert (report.product_costs, report.product_pct) == ('5.00', '0.25')
    assert report.inducements == '1.00'
    assert (report.assumed_years, report.holding_years) == ('5', '5')
    assert (report.period_start, report.period_end) == ('2026-08-06', '2031-08-05')
    assert batch.securities[0].identifier_type == 'wkn'
    assert batch.securities[0].key == 'WKN:578560'
    assert batch.securities[0].isin == ''


def test_mifid_cost_keeps_original_cost_lines_phases_and_categories():
    report = parse().cost_reports[0]
    assert [(item.label, item.phase, item.category, item.total, item.annual)
            for item in report.items] == [
        ('Orderprovision [E]', 'kauf', 'eigen', '9.16', True),
        ('Depotentgelt [E]', 'haltedauer', 'eigen', '0.00', True),
        ('Börsenplatzabhängiges Entgelt [E]', 'verkauf', 'eigen', '2.50', False),
        ('Orderprovision [E]', 'verkauf', 'eigen', '12.53', False),
    ]
    assert report.items[0].source_text == 'Orderprovision [E] 9,16 EUR'
    assert report.annual_projection[0] == {
        'label': 'Im 1. Jahr', 'savings_cumulative': '619.56',
        'purchase_costs': '9.16', 'holding_costs': '0.00',
        'total_costs': '9.16', 'return_impact_pct': '-1.50'}
    assert report.annual_projection[-1]['label'] == 'Wertpapierverkauf'
    assert report.annual_projection[-1]['total_costs'] == '15.03'


def test_mifid_cost_missing_category_stays_none_and_never_becomes_zero():
    text = cost_text(include_foreign=False, include_product=False, include_inducement=False)
    report = parse(document(text)).cost_reports[0]
    assert report.overhead_costs is None and report.foreign_pct is None
    assert report.product_costs is None and report.product_pct is None
    assert report.inducements is None
    assert report.service_costs == '52.81'
    assert report.total_costs == '60.81'


def test_mifid_cost_uses_isin_when_printed_but_never_guesses_one():
    report = parse(document(cost_text(isin='DE0005785604'))).cost_reports[0]
    assert (report.wkn, report.isin) == ('578560', 'DE0005785604')
    assert report.items[0].security_ref == 'DE0005785604'
    batch = parse(document(cost_text(isin='')))
    assert batch.cost_reports[0].isin == ''
    assert batch.cost_reports[0].items[0].security_ref == 'WKN:578560'
    assert any('keine ISIN geraten' in warning for warning in batch.warnings)


def _assign_to_depot(batch, depot='Depot 4764924'):
    batch.account_assignments = {account_key(batch.cost_reports[0].account): account_key(depot)}


def test_mifid_cost_import_is_cash_neutral_and_duplicate_safe(tmp_path):
    repo = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    try:
        repo.save_account('Depot 4764924', {'kind': 'Depot', 'institution': 'comdirect'})
        batch = parse(file_hash='mifid-hash-storage')
        _assign_to_depot(batch)
        result = repo.commit_batches([batch])
        assert result[0]['status'] == 'imported'
        assert result[0]['transactions'] == 0 and result[0]['documents'] == 1
        assert repo.transactions() == [] and repo.holdings() == []
        with repo.db:
            counts = {table: repo.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                      for table in ('transactions', 'snapshots', 'balances', 'bank_documents')}
        assert counts == {'transactions': 0, 'snapshots': 0, 'balances': 0, 'bank_documents': 1}
        reports = repo.store.model_records(kind='cost_reports')
        assert len(reports) == 1
        payload = reports[0]['payload']
        assert payload['account'] == 'Depot 4764924'
        assert payload['total_costs'] == '60.81'
        assert payload['items'][0]['label'] == 'Orderprovision [E]'

        replay = parse(file_hash='mifid-hash-storage')
        _assign_to_depot(replay)
        duplicate = repo.commit_batches([replay])
        assert duplicate[0]['status'] == 'duplicate'
        assert repo.transactions() == [] and len(repo.holdings()) == 0
        with repo.db:
            assert repo.db.execute('SELECT COUNT(*) FROM bank_documents').fetchone()[0] == 1
        assert len(repo.store.model_records(kind='cost_reports')) == 1
    finally:
        repo.close()


def test_mifid_cost_import_order_does_not_change_economic_state(tmp_path):
    first = parse(document(cost_text(wkn='111111', name='Erste AG'),
                          file_hash='order-a', path=Path('cost-a.pdf')))
    second = parse(document(cost_text(wkn='222222', name='Zweite AG'),
                           file_hash='order-b', path=Path('cost-b.pdf')))
    for batch in (first, second):
        _assign_to_depot(batch)
    states = []
    for name, batches in [('forward.sqlite', [first, second]),
                          ('reverse.sqlite', [second, first])]:
        repo = RepositoryV09(tmp_path / name, backups=False)
        try:
            repo.save_account('Depot 4764924', {'kind': 'Depot'})
            repo.commit_batches(batches)
            reports = sorted((r['payload']['wkn'], r['payload']['total_costs'])
                             for r in repo.store.model_records(kind='cost_reports'))
            states.append((reports, repo.transactions(), repo.holdings()))
        finally:
            repo.close()
    assert states[0] == states[1]
    assert [wkn for wkn, _total in states[0][0]] == ['111111', '222222']
    assert states[0][1] == [] and states[0][2] == []


def test_mifid_cost_preview_tab_shows_components_and_original_document(tmp_path, qapp):
    from portman.import_preview import ImportPreviewDialog
    repo = RepositoryV09(tmp_path / 'preview.sqlite', backups=False)
    try:
        repo.save_account('Depot 4764924', {'kind': 'Depot'})
        batch = parse(file_hash='mifid-preview')
        dialog = ImportPreviewDialog(repo, [batch])
        assert dialog.cost_table.rowCount() == 1
        assert dialog.cost_item_table.rowCount() == 4
        assert dialog.cost_table.item(0, 4).text() == '578560'
        assert dialog.cost_table.item(0, 17).text() == '60,81 EUR'
        assert dialog.cost_table.item(0, 18).text() == '0,66 % p.a.'
        assert 'keine ausgeführte Transaktion' in dialog.cost_table.item(0, 20).text()
        assert dialog.cost_item_table.item(0, 1).text() == 'Orderprovision [E]'
        assert dialog.cost_item_table.item(0, 3).text() == '9,16 EUR'
        assert dialog.mapping_rows[0][1]['required_kind'] == 'Depot'
        dialog.close()
    finally:
        repo.close()


@pytest.mark.skipif(not REAL_COSTS.is_dir(), reason='comdirect real corpus is not available')
def test_all_23_real_mifid_cost_pdfs_are_structured_and_cash_neutral():
    from portfolio_v5.pdf_importer import parse_pdf
    files = sorted(REAL_COSTS.glob('*.pdf'))
    assert len(files) == 23
    for path in files:
        batch = parse_pdf(path, allow_ocr=False)
        assert batch.errors == [], path.name
        assert batch.plugin_handler == 'kosteninformation_mifid_ii', path.name
        assert len(batch.cost_reports) == 1, path.name
        assert len(batch.documents) == 1, path.name
        assert batch.transactions == [] and batch.snapshots == [] and batch.balances == []
        report = batch.cost_reports[0]
        assert report.wkn and report.total_costs and report.ongoing_pct, path.name
        assert report.sparplan_number == '38', path.name
        assert report.items and all(item.label and item.phase and item.category
                                    for item in report.items), path.name
        assert report.isin == '', path.name
        assert 'keine ausgeführte Transaktion' in batch.documents[0].document_type
