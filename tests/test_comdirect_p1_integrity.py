from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest

from portfolio_v5.accounts import account_key
from portfolio_v5.models import (BankTransaction, FeeItem, ImportBatch, Kind,
                                 Position, SecurityInfo, Snapshot, TaxEvent)
from portfolio_v5.settlement import performance_transactions
from portman.comdirect_import import commit_reports
from portman.import_v09 import ImportSession, transaction
from portman.repository_v09 import RepositoryV09
from portman.tax_matching import match_tax_events
from portman.tax_overview import automatic_tax_values


CASH = 'IBAN DE84200411330476492400'
DEPOT = 'Depot 4764924'


def repository(path):
    repo = RepositoryV09(path, backups=False)
    cash_details = {'kind': 'Girokonto', 'institution': 'comdirect'}
    repo.save_account(CASH, cash_details)
    repo.save_account('Giro DE84200411330476492400', cash_details, original=CASH)
    repo.save_account(DEPOT, {
        'kind': 'Depot', 'institution': 'comdirect',
        'cash_account_key': account_key(CASH),
    })
    return repo


TRADES = (
    ('A111X9', 'IE00BKM4GZ66', '2026-09-07', '2026-09-09', '0.630', '48.401', '30.49', '0.46', '30.95'),
    ('A0S9GB', 'DE000A0S9GB0', '2026-09-23', '2026-09-25', '0.147', '121.20', '17.82', '0.27', '18.09'),
    ('716460', 'DE0007164600', '2026-07-23', '2026-07-27', '0.221', '129.52', '28.62', '0.43', '29.05'),
)


def finance_batch():
    transactions = []
    positions = []
    for index, (wkn, isin, day, valuta, qty, _price, _gross, _fee, total) in enumerate(TRADES):
        text = f'Wertpapiere WPKNR: {wkn} ISIN: {isin}'
        transactions.append(BankTransaction(
            CASH, f'statement-{wkn}', day, Kind.BANK_BOOKING, '-' + total, 'EUR',
            value_date=valuta, booking_text=text, purpose=text,
            bank_reference=f'REPORT-{index}'))
        positions.append(Position('WKN:' + wkn, wkn, wkn=wkn, isin=isin,
                                  quantity=qty, value='100.00'))
    return ImportBatch(
        'finance.pdf', 'finance-p1', source_sheet='PDF', transactions=transactions,
        snapshots=[Snapshot(DEPOT, '2026-09', '2026-09-30', 'Finanzreport', positions)],
        securities=[SecurityInfo('WKN:' + wkn, identifier_type='wkn', wkn=wkn, isin=isin, name=wkn)
                    for wkn, isin, *_ in TRADES])


def trade_batches():
    result = []
    for index, (wkn, isin, day, valuta, qty, price, gross, fee, total) in enumerate(TRADES):
        text = f'Wertpapiere WPKNR: {wkn} ISIN: {isin}'
        evidence = BankTransaction(
            'Depot 476492400', f'notice-{wkn}', day, Kind.BUY, '-' + total, 'EUR',
            security=isin, security_ref=isin, quantity=qty, price=price,
            gross_amount=gross, fees=fee, taxes='0.00', value_date=valuta,
            cash_account=CASH, depot_account='Depot 476492400', booking_text=text,
            purpose=text, document_reference=f'NOTICE-{index}',
            fee_items=[FeeItem('provision', fee)], affects_cash=False)
        result.append(ImportBatch(
            f'{wkn}.pdf', f'notice-p1-{wkn}', source_sheet='PDF', transactions=[evidence],
            plugin_id='user.comdirect-ertraege', plugin_handler='wertpapierkauf',
            account_assignments={'depot 476492400': account_key(CASH)},
            securities=[SecurityInfo(isin, identifier_type='isin', isin=isin, wkn=wkn, name=wkn)]))
    return result


@pytest.mark.parametrize('order', ('finance-first', 'notices-first'))
def test_comdirect_trade_fees_persist_without_second_cashflow(tmp_path, order):
    repo = repository(tmp_path / (order + '.sqlite'))
    try:
        finance = finance_batch()
        notices = trade_batches()
        batches = [finance, *notices] if order == 'finance-first' else [*notices, finance]
        assert all(repo.commit_batches([deepcopy(batch)])[0]['status'] == 'imported' for batch in batches)

        assert repo.db.execute('SELECT COUNT(*) FROM transactions').fetchone()[0] == 3
        assert repo.db.execute('SELECT COUNT(*) FROM booking_details').fetchone()[0] == 3
        assert repo.db.execute(
            "SELECT COUNT(*) FROM import_model_records WHERE kind='booking_evidence'").fetchone()[0] == 3
        actual = {tx['security']: tx for tx in repo.transactions()}
        for wkn, isin, _day, _valuta, qty, _price, gross, fee, total in TRADES:
            tx = actual[isin]
            assert (tx['kind'], tx['quantity'], tx['gross_amount'], tx['fees'], tx['amount']) == (
                Kind.BUY, qty, gross, fee, '-' + total)
            assert tx['fee_items'] == [{'kind': 'provision', 'amount': fee}]
        performance = performance_transactions(repo.store, repo.transactions())
        assert [(tx['security'], tx['amount'], tx['fees']) for tx in performance] == [
            (isin, '-' + total, fee) for _wkn, isin, _day, _valuta, _qty,
            _price, _gross, fee, total in sorted(TRADES, key=lambda row: row[2])]

        counts = tuple(repo.db.execute(query).fetchone()[0] for query in (
            'SELECT COUNT(*) FROM imports WHERE active=1',
            'SELECT COUNT(*) FROM transactions',
            'SELECT COUNT(*) FROM booking_details',
            "SELECT COUNT(*) FROM import_model_records WHERE kind='booking_evidence'"))
        assert all(repo.commit_batches([deepcopy(batch)])[0]['status'] == 'duplicate' for batch in batches)
        assert counts == tuple(repo.db.execute(query).fetchone()[0] for query in (
            'SELECT COUNT(*) FROM imports WHERE active=1',
            'SELECT COUNT(*) FROM transactions',
            'SELECT COUNT(*) FROM booking_details',
            "SELECT COUNT(*) FROM import_model_records WHERE kind='booking_evidence'"))
    finally:
        repo.close()


def test_zero_tax_regular_dividend_links_to_statement_without_fee_link(tmp_path):
    repo = repository(tmp_path / 'ordinary-dividend.sqlite')
    try:
        finance = ImportBatch(
            'finance-dividend.pdf', 'finance-dividend', source_sheet='PDF',
            transactions=[BankTransaction(
                CASH, 'statement-sap-dividend', '2026-05-08', Kind.BANK_BOOKING,
                '4.49', 'EUR', booking_text=(
                    'Kupon ERTRAEGNISGUTSCHRIFT VOM 08.05.26 DEPOTBESTAND: 1,794 '
                    'SAP SE O.N. 716460 EUR 2,50'), bank_reference='SAP-REPORT')],
            snapshots=[Snapshot(DEPOT, '2026-05', '2026-05-31', 'Finanzreport', [
                Position('WKN:716460', 'SAP SE O.N.', wkn='716460', isin='DE0007164600',
                         quantity='1.794', value='300.00')])],
            securities=[SecurityInfo('WKN:716460', identifier_type='wkn', wkn='716460',
                                     isin='DE0007164600', name='SAP SE')])
        event = TaxEvent(
            'sap-tax-event', 'Depot 476492400', 'dividende_inland', '2026-05-08',
            security_ref='DE0007164600', quantity='1.794', currency='EUR',
            taxable_income='4.49', paid_taxes='0.00', capital_gains_tax='0.00',
            solidarity_surcharge='0.00', church_tax='0.00', reference_no='SAP-TAX',
            cash_account=CASH)
        notice = ImportBatch(
            'sap-tax.pdf', 'sap-tax', source_sheet='PDF', tax_events=[event],
            account_assignments={'depot 476492400': account_key(DEPOT)})
        repo.commit_batches([notice])
        repo.commit_batches([finance])
        linked = next(item for item in repo.tax_events() if item['external_id'] == 'sap-tax-event')
        assert linked['related_transaction_id'] == 'statement-sap-dividend'
        assert repo.fee_links() == []
        assert len([row for row in repo.tax_detail_records()
                    if row.get('linked_tax_event_id') == 'sap-tax-event']) == 1
    finally:
        repo.close()


def test_tax_matching_uses_imported_wkn_isin_bridge_on_clean_database(tmp_path):
    repo = repository(tmp_path / 'clean-tax-match.sqlite')
    try:
        dividend = BankTransaction(
            CASH, 'statement-distribution', '2026-09-15', Kind.DIVIDEND,
            '7.43', 'EUR', security='WKN:A0H074', gross_income='9.10',
            taxes='1.67', performance_depot_key=account_key(DEPOT),
            bank_reference='REPORT-DISTRIBUTION')
        finance = ImportBatch(
            'finance-distribution.pdf', 'finance-distribution', transactions=[dividend],
            snapshots=[Snapshot(DEPOT, '2026-09', '2026-09-30', 'Finanzreport', [
                Position('WKN:A0H074', 'ETF', wkn='A0H074', quantity='1', value='9.10')])])
        notice = ImportBatch(
            'tax-distribution.pdf', 'tax-distribution',
            securities=[SecurityInfo('DE000A0H0744', identifier_type='isin',
                                     isin='DE000A0H0744', wkn='A0H074', name='ETF')],
            tax_events=[TaxEvent(
                'tax-distribution', DEPOT, 'investment_ausschuettung_inland',
                '2026-09-15', security_ref='DE000A0H0744', gross_income='9.10',
                partial_exemption_amount='2.73', taxable_income='6.37',
                paid_taxes='1.67', cash_account=CASH)])
        repo.commit_batches([finance])
        repo.commit_batches([notice])

        master = repo.db.execute(
            "SELECT isin FROM security_master WHERE security_key='WKN:A0H074'").fetchone()
        assert master['isin'] == ''
        assert list(match_tax_events(repo).values())[0]['external_id'] == 'statement-distribution'
        values = automatic_tax_values(repo, 2026)[account_key(DEPOT)]
        assert (values['capital_income'], values['taxes']) == (
            Decimal('6.37'), Decimal('1.67'))
    finally:
        repo.close()


@pytest.mark.parametrize('order', ('finance-first', 'notices-first'))
def test_guided_gui_apply_persists_trade_details_in_both_orders(tmp_path, order):
    """Exercise both storage paths used by the two V09 import previews."""
    path = tmp_path / ('gui-' + order + '.sqlite')
    repo = repository(path)
    repo.close()
    job = SimpleNamespace(
        path=str(path),
        isInterruptionRequested=lambda: False,
        progress=SimpleNamespace(emit=lambda *_args: None))
    finance = finance_batch()
    notices = trade_batches()
    for notice in notices:
        notice.account_assignments = {'depot 476492400': account_key(DEPOT)}

    def apply_notices(batches):
        current = RepositoryV09(str(path), backups=False)
        try:
            with transaction(current, commit=True):
                return ImportSession.apply(None, current, job, (deepcopy(batches), []))
        finally:
            current.close()

    if order == 'finance-first':
        results = commit_reports(job, [deepcopy(finance)], RepositoryV09)
        results.extend(apply_notices(notices))
    else:
        results = apply_notices(notices)
        results.extend(commit_reports(job, [deepcopy(finance)], RepositoryV09))

    repo = RepositoryV09(str(path), backups=False)
    try:
        assert all(result['status'] == 'imported' for result in results)
        assert repo.db.execute('SELECT COUNT(*) FROM transactions').fetchone()[0] == 3
        assert repo.db.execute('SELECT COUNT(*) FROM booking_details').fetchone()[0] == 3
        assert {tx['security']: tx['fees'] for tx in repo.transactions()} == {
            isin: fee for _wkn, isin, _day, _valuta, _qty, _price, _gross, fee, _total in TRADES}
        assert {tx['performance_depot_key'] for tx in repo.transactions()} == {
            account_key(DEPOT)}

        counts = tuple(repo.db.execute(query).fetchone()[0] for query in (
            'SELECT COUNT(*) FROM imports WHERE active=1',
            'SELECT COUNT(*) FROM transactions',
            'SELECT COUNT(*) FROM booking_details'))
        repo.close()
        repeated = commit_reports(job, [deepcopy(finance)], RepositoryV09)
        repeated.extend(apply_notices(notices))
        repo = RepositoryV09(str(path), backups=False)
        assert all(result['status'] == 'duplicate' for result in repeated)
        assert counts == tuple(repo.db.execute(query).fetchone()[0] for query in (
            'SELECT COUNT(*) FROM imports WHERE active=1',
            'SELECT COUNT(*) FROM transactions',
            'SELECT COUNT(*) FROM booking_details'))
    finally:
        repo.close()
