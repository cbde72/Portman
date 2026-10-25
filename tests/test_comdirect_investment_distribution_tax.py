import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
from types import SimpleNamespace

from portfolio_v5.accounts import account_key
from portfolio_v5.models import BankTransaction, ImportBatch, Kind, Position, SecurityInfo, Snapshot
from portfolio_v5.pdf_plugins import ParseContext, PdfDocument, PdfPage
from portfolio_v5.settlement import performance_transactions
from portman.repository_v09 import RepositoryV09
from portman.import_v09 import ImportSession, transaction
from portman.tax_overview import automatic_tax_values


ROOT = Path(__file__).resolve().parents[1]


def plugin():
    path = ROOT / 'pdf_plugins' / 'comdirect_ertraege.py'
    spec = importlib.util.spec_from_file_location('comdirect_distribution_tax_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.plugin


def notice(*, origin='Inländische', day='15.09.2026', value_day=None, reference='1IINP4025ZX000SB',
           gross='9,10', partial='2,73', taxable='6,37', kapst='1,59', soli='0,08',
           church='0,00', paid='1,67', net='7,43'):
    value_day = value_day or day
    text = f'''comdirect bank AG
Datum: {day}
Depotnummer: 476492400
Referenz-Nummer: {reference}
Steuerliche Behandlung: {origin} Investment-Ausschüttung vom {day}
Stk. 27,051 IS.DJ AS.PAC.S.D.50 U.ETF, WKN/ISIN: A0H074/DE000A0H0744
Zu Ihren Gunsten vor Steuern: EUR {gross}
Steuerbemessungsgrundlage (1) EUR {taxable}
Kapitalertragsteuer EUR -{kapst}
Solidaritätszuschlag EUR -{soli}
Kirchensteuer EUR {church}
abgeführte Steuern EUR -{paid}
Zu Ihren Gunsten nach Steuern: EUR {net}
Die Gutschrift erfolgt mit Valuta {value_day} auf Konto EUR mit der IBAN DE71200411330476492440
Investment-Ausschüttung EUR {gross}
Teilfreistellung (30%) EUR -{partial}
Steuerbemessungsgrundlage vor Verlustverrechnung EUR {taxable}
'''
    return PdfDocument(Path('distribution-tax.pdf'), b'%PDF-test\n%%EOF', 'distribution-tax',
                       (PdfPage(1, text),))


def parse(source):
    importer = plugin()
    detection = importer.detect(source)[0]
    batch = ImportBatch(str(source.path), source.file_hash, source_sheet='PDF')
    return detection, importer.parse(source, detection, ParseContext(batch))


def dividend_notice():
    text = '''comdirect bank AG Datum: 27.05.2026 Depotnummer:476492400
Referenz-Nummer:1SINHRMXMUV005VO
SteuerlicheBehandlung:InländischeDividendevom27.05.2026
Stk.3,878FRESENIUSSE+CO.KGAAO.N.,WKN/ISIN:578560/DE0005785604
ZuIhrenGunstenvorSteuern:EUR4,07
SteuerbemessungsgrundlagevorVerlustverrechnungEUR4,07
inAnspruchgenommenerFreistellungsauftragEUR4,07
SteuerbemessungsgrundlagenachVerlustverrechnungEUR0,00
KapitalertragsteuerEUR0,00 SolidaritätszuschlagEUR0,00 KirchensteuerEUR0,00
abgeführteSteuernEUR0,00 ZuIhrenGunstennachSteuern:EUR4,07
DieGutschrifterfolgtmitValuta27.05.2026aufKontoEURmitderIBANDE71200411330476492440'''
    return PdfDocument(Path('dividend-tax.pdf'), b'%PDF-test\n%%EOF', 'dividend-tax',
                       (PdfPage(1, text),))


def test_reference_notice_is_structured_without_second_distribution():
    detection, batch = parse(notice())
    event, tax = batch.tax_events[0], batch.transactions[0]
    assert detection.handler_id == 'investment_ausschuettung'
    assert event.type == 'investment_ausschuettung_inland'
    assert (event.security_ref, event.quantity, event.date, event.document_date) == (
        'DE000A0H0744', '27.051', '2026-09-15', '2026-09-15')
    assert (event.partial_exemption_rate, event.partial_exemption_amount,
            event.taxable_income, event.gross_income) == ('30', '2.73', '6.37', '9.10')
    assert (event.capital_gains_tax, event.solidarity_surcharge,
            event.church_tax, event.paid_taxes) == ('1.59', '0.08', '0.00', '1.67')
    assert (tax.kind, tax.amount, tax.taxes, tax.account) == (
        Kind.TAX, '-1.67', '1.67', 'IBAN DE71200411330476492440')
    assert tax.affects_cash is False
    assert not any(tx.kind in (Kind.DIVIDEND, Kind.DISTRIBUTION) for tx in batch.transactions)
    assert batch.securities[0].wkn == 'A0H074'
    assert batch.documents[0].content_b64


def test_pre_2018_notice_without_partial_exemption_keeps_field_missing():
    source = notice(gross='9,10', partial='0,00', taxable='9,10', kapst='0,00',
                    soli='0,00', paid='0,00', net='9,10')
    text = source.pages[0].text.replace('Teilfreistellung (30%) EUR -0,00\n', '')
    text = text.replace('Depotnummer: 476492400\n', '')
    source = PdfDocument(source.path, source.content, 'old-distribution', (PdfPage(1, text),))
    _detection, batch = parse(source)
    event = batch.tax_events[0]
    assert event.account == 'comdirect Depot'
    assert event.partial_exemption_amount is None
    assert event.partial_exemption_rate is None
    assert batch.transactions == []
    assert len(batch.documents) == 1


def test_explicit_pre_loss_tax_base_takes_precedence_over_page_one_base():
    source = notice(gross='14,86', partial='4,46', taxable='10,40', kapst='0,00',
                    soli='0,00', paid='0,00', net='14,86')
    text = source.pages[0].text.replace(
        'Steuerbemessungsgrundlage (1) EUR 10,40',
        'Steuerbemessungsgrundlage (1) EUR 0,00')
    source = PdfDocument(source.path, source.content, 'two-tax-bases', (PdfPage(1, text),))
    _detection, batch = parse(source)
    assert batch.tax_events[0].taxable_income == '10.40'


def test_foreign_notice_and_documented_zero_remain_cash_neutral():
    _, batch = parse(notice(origin='Ausländische', gross='9,10', partial='0,00', taxable='9,10',
                            kapst='0,00', soli='0,00', paid='0,00', net='9,10'))
    event = batch.tax_events[0]
    assert event.type == 'investment_ausschuettung_ausland'
    assert (event.partial_exemption_amount, event.paid_taxes) == ('0.00', '0.00')
    assert batch.transactions == []
    assert event.related_transaction_id == ''


def test_foreign_notice_preserves_distinct_treatment_and_value_dates():
    _, batch = parse(notice(origin='Ausländische', day='27.02.2026', value_day='02.03.2026'))
    event, payment = batch.tax_events[0], batch.transactions[0]
    assert event.date == '2026-02-27'
    assert (payment.date, payment.value_date) == ('2026-02-27', '2026-03-02')


def test_domestic_share_dividend_tax_notice_preserves_documented_zeroes():
    detection, batch = parse(dividend_notice())
    assert detection.handler_id == 'dividende_steuer_inland'
    assert batch.transactions == []
    event = batch.tax_events[0]
    assert (event.type, event.security_ref, event.quantity) == (
        'dividende_inland', 'DE0005785604', '3.878')
    assert (event.taxable_income, event.used_exemption, event.paid_taxes, event.gross_income) == (
        '4.07', '4.07', '0.00', '4.07')
    assert (event.capital_gains_tax, event.solidarity_surcharge,
            event.church_tax) == ('0.00', '0.00', '0.00')
    assert batch.documents[0].content_b64


def test_existing_distribution_is_not_duplicated_and_reimport_is_idempotent(tmp_path):
    repo = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    try:
        repo.save_account('Depot 476492400', {'kind': 'Depot', 'institution': 'comdirect'})
        repo.save_account('IBAN DE71200411330476492440', {'kind': 'Verrechnungskonto'})
        income = BankTransaction(
            'Depot 476492400', 'income-existing', '2026-09-15', Kind.DIVIDEND, '9.10', 'EUR',
            security='DE000A0H0744', quantity='27.051', gross_amount='9.10', income_basis='gross',
            cash_account='IBAN DE71200411330476492440', document_reference='INCOME-REF')
        repo.commit_batches([ImportBatch('income.pdf', 'income', source_sheet='PDF', transactions=[income])])
        _, first = parse(notice())
        first.documents = []
        first_result = repo.commit_batches([first])[0]
        assert first_result.get('transactions') == 1, first_result
        _, duplicate = parse(notice())
        duplicate.documents = []
        result = repo.commit_batches([duplicate])[0]
        assert result['status'] == 'duplicate'
        transactions = repo.transactions()
        assert sum(tx['kind'] == Kind.DIVIDEND for tx in transactions) == 1
        assert sum(tx['kind'] == Kind.TAX for tx in transactions) == 1
        assert len(repo.tax_events()) == 1
    finally:
        repo.close()


def test_multiple_distributions_in_one_tax_year_remain_distinct(tmp_path):
    repo = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    try:
        repo.save_account('Depot 476492400', {'kind': 'Depot', 'institution': 'comdirect'})
        repo.save_account('IBAN DE71200411330476492440', {'kind': 'Verrechnungskonto'})
        _, first = parse(notice(day='15.06.2026', reference='1OINIWDRSH0002OL'))
        _, second = parse(notice(day='15.09.2026', reference='1IINP4025ZX000SB'))
        first.documents = second.documents = []
        assert repo.commit_batches([first])[0]['status'] == 'imported'
        assert repo.commit_batches([second])[0]['status'] == 'imported'
        assert len(repo.tax_events()) == 2
        assert sum(tx['kind'] == Kind.TAX for tx in repo.transactions()) == 2
    finally:
        repo.close()


def _integration_repo(path):
    repo = RepositoryV09(path, backups=False)
    for name in ('IBAN DE71200411330476492440',):
        repo.save_account(name, {'kind': 'Verrechnungskonto', 'institution': 'comdirect'})
    repo.save_account('Depot 4764924', {
        'kind': 'Depot', 'institution': 'comdirect',
        'cash_account_key': account_key('IBAN DE71200411330476492440')})
    return repo


def _tax_batch():
    _, batch = parse(notice())
    batch.account_assignments = {'depot 476492400': 'depot 4764924'}
    return batch


def _finance_batch():
    dividend = BankTransaction(
        'IBAN DE71200411330476492440', 'statement-a0h074', '2026-09-15', Kind.BANK_BOOKING,
        '7.43', 'EUR', bank_reference='0S5C29F709I0G', affects_cash=True,
        booking_text=('ERTRAEGNISGUTSCHRIFT VOM 15.09.26\nDEPOTBESTAND: 27,051\n'
                      'IS.DJ AS.PAC.S.D.50 U.ETF\nA0H074 EUR 0,336248\n'
                      'Abr.Betrag Brutto 9,10 EUR\nSteuerabzug 1,67- EUR'))
    return ImportBatch(
        'finance.pdf', 'finance-a0h074', source_sheet='PDF', transactions=[dividend],
        snapshots=[Snapshot('Depot 4764924', '2026-09', '2026-09-30', 'Finanzreport', [
            Position('WKN:A0H074', 'IS.DJ AS.PAC.S.D.50 U.ETF', wkn='A0H074',
                     isin='DE000A0H0744', quantity='27.051', value='900.00')])],
        securities=[SecurityInfo('WKN:A0H074', identifier_type='wkn', wkn='A0H074',
                                 name='IS.DJ AS.PAC.S.D.50 U.ETF')])


@pytest.mark.parametrize('order', [('tax', 'finance'), ('finance', 'tax')])
def test_sqlite_integration_maps_links_and_is_idempotent_in_both_orders(tmp_path, order):
    repo = _integration_repo(tmp_path / ('-'.join(order) + '.sqlite'))
    try:
        batches = {'tax': _tax_batch, 'finance': _finance_batch}
        first_results = [repo.commit_batches([batches[name]()])[0] for name in order]
        assert all(result['status'] == 'imported' for result in first_results)

        tax = next(tx for tx in repo.transactions() if tx['kind'] == Kind.TAX)
        dividend = next(tx for tx in repo.transactions() if tx['kind'] == Kind.DIVIDEND)
        assert tax['performance_depot_key'] == dividend['performance_depot_key'] == 'depot 4764924'
        assert tax['affects_cash'] is False
        assert len(repo.fee_links()) == 1

        economic = [tx for tx in performance_transactions(repo.store, repo.transactions())
                    if tx['date'] == '2026-09-15']
        assert [(tx['kind'], tx['amount']) for tx in economic] == [(Kind.DIVIDEND, '7.43')]
        values = automatic_tax_values(repo, 2026)['depot 4764924']
        assert (values['capital_income'], values['dividends'], values['taxes'],
                values['partial_exemption']) == (
                    Decimal('6.37'), Decimal('7.43'), Decimal('1.67'), Decimal('2.73'))

        details = [row for row in repo.tax_detail_records()
                   if row['original_values']['Referenznummer'] == '0S5C29F709I0G']
        assert len(details) == 1
        detail = details[0]
        assert detail['linked_tax_event_id']
        assert detail['original_values']['Vorgang'] == 'Investment-Ausschüttung Inland'
        assert (detail['original_values']['Betrag Brutto'],
                detail['original_values']['Steuerbemessungsgrundlage'],
                detail['original_values']['Verlust Sonstige'],
                detail['original_values']['Summe Steuern'],
                detail['original_values']['Gewinn/Verlust nach Steuern']) == (
                    '9,10', '6,37', '-2,73', '-1,67', '7,43')

        counts_before = tuple(repo.db.execute(query).fetchone()[0] for query in (
            'SELECT COUNT(*) FROM imports WHERE active=1',
            'SELECT COUNT(*) FROM transactions',
            'SELECT COUNT(*) FROM bank_documents',
            "SELECT COUNT(*) FROM import_model_records WHERE kind='tax_events'"))
        repeated = [repo.commit_batches([batches[name]()])[0] for name in order]
        assert all(result['status'] == 'duplicate' for result in repeated)
        counts_after = tuple(repo.db.execute(query).fetchone()[0] for query in (
            'SELECT COUNT(*) FROM imports WHERE active=1',
            'SELECT COUNT(*) FROM transactions',
            'SELECT COUNT(*) FROM bank_documents',
            "SELECT COUNT(*) FROM import_model_records WHERE kind='tax_events'"))
        assert counts_after == counts_before
    finally:
        repo.close()


def test_tax_detail_and_overview_match_without_persisted_fee_link(tmp_path):
    repo = _integration_repo(tmp_path / 'without-fee-link.sqlite')
    try:
        repo.commit_batches([_tax_batch(), _finance_batch()])
        repo.db.execute('DELETE FROM fee_links')
        repo.db.commit()

        values = automatic_tax_values(repo, 2026)['depot 4764924']
        assert (values['capital_income'], values['taxes']) == (Decimal('6.37'), Decimal('1.67'))
        relevant = [row for row in repo.tax_detail_records()
                    if row.get('linked_tax_event_id')]
        assert len(relevant) == 1
        assert relevant[0]['linked_transaction_id']
    finally:
        repo.close()


@pytest.mark.parametrize('order', [('tax', 'finance'), ('finance', 'tax')])
def test_guided_gui_apply_maps_tax_notice_in_both_orders(tmp_path, order):
    """Regression for the atomic ImportWizard/ImportSession save boundary."""
    repo = _integration_repo(tmp_path / ('gui-' + '-'.join(order) + '.sqlite'))
    job = SimpleNamespace(
        isInterruptionRequested=lambda: False,
        progress=SimpleNamespace(emit=lambda *_args: None))
    batches = {'tax': _tax_batch, 'finance': _finance_batch}
    selected = [batches[name]() for name in order]
    try:
        with transaction(repo, commit=True):
            results = ImportSession.apply(None, repo, job, (selected, []))
        assert all(result['status'] == 'imported' for result in results)
        event = next(item for item in repo.tax_events()
                     if item['security_ref'] == 'DE000A0H0744')
        dividend = next(tx for tx in repo.transactions() if tx['kind'] == Kind.DIVIDEND)
        assert event['related_transaction_id'] == dividend['external_id']
        assert dividend['performance_depot_key'] == 'depot 4764924'
        assert len(repo.fee_links()) == 1
        assert [(tx['kind'], tx['amount']) for tx in
                performance_transactions(repo.store, repo.transactions())
                if tx['date'] == '2026-09-15'] == [(Kind.DIVIDEND, '7.43')]

        before = tuple(repo.db.execute(query).fetchone()[0] for query in (
            'SELECT COUNT(*) FROM imports WHERE active=1',
            'SELECT COUNT(*) FROM transactions',
            'SELECT COUNT(*) FROM fee_links'))
        with transaction(repo, commit=True):
            repeated = ImportSession.apply(
                None, repo, job, ([batches[name]() for name in order], []))
        assert all(result['status'] == 'duplicate' for result in repeated)
        assert before == tuple(repo.db.execute(query).fetchone()[0] for query in (
            'SELECT COUNT(*) FROM imports WHERE active=1',
            'SELECT COUNT(*) FROM transactions',
            'SELECT COUNT(*) FROM fee_links'))
    finally:
        repo.close()
