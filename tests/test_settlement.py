import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import base64
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from portfolio_v5.models import BankDocument, BankTransaction, ImportBatch, Position, Snapshot, TaxEvent
from portfolio_v5.performance import security_performance
from portfolio_v5.settlement import performance_transactions, portfolio_cash_kind
from portman.repository_v09 import RepositoryV09, reference
from portman.performance_service import PerformanceService

ISIN = 'US0378331005'


class SettlementTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.repo = RepositoryV09(Path(self.folder.name) / 'test.sqlite', backups=False)
        self.store = self.repo.store
        self.store.save_account('Cash', {'kind': 'Verrechnungskonto'})
        self.store.save_account('Depot', {'kind': 'Depot', 'cash_account_key': 'cash'})
        self.sequence = 0
        for day in ('2025-01-01', '2025-12-31'):
            self.put(snapshots=[Snapshot('Depot', day[:7], day, 'Test',
                [Position(ISIN, 'Apple', isin=ISIN, quantity='10', value='10000')])])

    def tearDown(self):
        self.repo.close()
        self.folder.cleanup()

    def put(self, transactions=(), snapshots=()):
        self.sequence += 1
        return self.store.import_batch(ImportBatch(f'test-{self.sequence}', str(self.sequence),
            transactions=list(transactions), snapshots=list(snapshots)))

    def dividend(self, **changes):
        values = dict(account='Cash', external_id='pdf-dividend', date='2025-12-31',
            kind='DIVIDEND', amount='300', currency='EUR', security=ISIN,
            gross_income='400', gross_currency='EUR', taxes='100', purpose='Dividendengutschrift ' + ISIN)
        return BankTransaction(**{**values, **changes})

    def statement(self, **changes):
        values = dict(account='Cash', external_id='pdf-statement', date='2025-12-31',
            kind='BANK_BOOKING', amount='300', currency='EUR',
            purpose='Dividendengutschrift ' + ISIN)
        return BankTransaction(**{**values, **changes})

    def performance(self):
        return PerformanceService(self.repo).analyze('Depot', '2025-01-01', '2025-12-31')

    def test_net_performance_separate_cash_and_gross(self):
        self.put([self.dividend()])
        result = self.performance()
        self.assertNotIn('error', result)
        self.assertEqual(result['profit'], Decimal('300'))
        self.assertEqual(result['dividends'], Decimal('300'))
        self.assertEqual(result['gross_dividends'], Decimal('400'))
        self.assertEqual(result['twr'], Decimal('.03'))
        self.assertEqual(self.repo.transactions()[0]['account'], 'Cash')
        self.assertEqual(sum(Decimal(t['amount']) for t in self.repo.transactions()
                             if t.get('affects_cash', True)), Decimal('300'))
        self.store.confirm_coverage('Depot', '2025-01-01', '2025-12-31')
        strict = security_performance(self.store, 'Depot', '2025-01-01', '2025-12-31')
        self.assertEqual(strict['profit'], Decimal('400'))
        self.assertEqual(strict['dividends'], Decimal('400'))
        self.assertEqual(strict['taxes_excluded'], Decimal('100'))
        after_tax = security_performance(self.store, 'Depot', '2025-01-01', '2025-12-31', after_taxes=True)
        self.assertEqual(after_tax['profit'], Decimal('300'))
        self.assertEqual(after_tax['dividends'], Decimal('300'))

    def test_security_performance_keeps_fees_but_excludes_embedded_and_separate_tax(self):
        self.put([self.dividend(amount='290', gross_income='400', taxes='100', fees='10'),
                  BankTransaction('Depot', 'tax', '2025-06-01', 'TAX', '-20', 'EUR', security=ISIN)])
        self.store.confirm_coverage('Depot', '2025-01-01', '2025-12-31')
        result = security_performance(self.store, 'Depot', '2025-01-01', '2025-12-31')
        self.assertEqual(result['profit'], Decimal('390'))
        self.assertEqual(result['taxes_excluded'], Decimal('120'))
        after_tax = security_performance(self.store, 'Depot', '2025-01-01', '2025-12-31', after_taxes=True)
        self.assertEqual(after_tax['profit'], Decimal('270'))

    def test_legacy_kind_and_non_cash_income(self):
        self.put([self.dividend(kind='dividende', affects_cash=False)])
        self.assertEqual(self.performance()['profit'], Decimal('300'))
        self.assertFalse(self.repo.transactions()[0]['affects_cash'])

    def test_value_security_text_assigns_positive_coupon_to_holding(self):
        self.put([BankTransaction('Cash', 'coupon', '2025-06-01', 'BANK_BOOKING', '25', 'EUR',
                                  purpose='Wertpapier Kupon WKN 865985')])
        # Add the WKN to the existing position without changing its ISIN identity.
        self.put(snapshots=[Snapshot('Depot', '2025-06', '2025-06-01', 'Test',
            [Position(ISIN, 'Apple', isin=ISIN, wkn='865985', quantity='10', value='10000')])])
        tx = next(row for row in self.repo.transactions() if row['external_id'] == 'coupon')
        self.assertEqual((tx['kind'], tx['security']), ('DIVIDEND', ISIN))
        self.assertEqual(tx['performance_depot_key'], 'depot')

    def test_value_security_text_assigns_negative_amount_as_purchase(self):
        self.put([BankTransaction('Cash', 'purchase', '2025-06-01', 'BANK_BOOKING', '-500', 'EUR',
                                  purpose='Wertpapier Kauf ISIN US0378331005')])
        tx = next(row for row in self.repo.transactions() if row['external_id'] == 'purchase')
        self.assertEqual((tx['kind'], tx['security']), ('BUY', ISIN))
        assigned = performance_transactions(self.store, [tx], 'Depot')
        self.assertEqual((len(assigned), assigned[0]['account'], assigned[0]['cash_account']),
                         (1, 'Depot', 'Cash'))

    def test_coupon_credit_extracts_wkn_position_gross_tax_and_holding_quantity(self):
        self.put(snapshots=[Snapshot('Depot', '2025-05', '2025-05-01', 'Test', [
            Position('IE00B3YCGJ38', 'ISH.S.EUR.SMALL 200 U.ETF', isin='IE00B3YCGJ38',
                     wkn='A0D8QZ', quantity='102.038', value='1000')])])
        purpose = ('Kupon ERTRAEGNISGUTSCHRIFT VOM 15.09.26 0S5C29F709FZ '
                   'DEPOTBESTAND: 102,038 JRRF/4 ISH.S.EUR.SMALL 200 U.ETF A0D8QZ '
                   'EUR 0,550022 Abr.Betrag Brutto 56,12 EUR Steuerabzug 10,36- EUR')
        self.put([BankTransaction('Cash', 'coupon-details', '2026-09-15', 'BANK_BOOKING',
                                  '45.76', 'EUR', purpose=purpose)])
        tx = next(row for row in self.repo.transactions() if row['external_id'] == 'coupon-details')
        self.assertEqual((tx['kind'], tx['security'], tx['performance_depot_key']),
                         ('DIVIDEND', 'IE00B3YCGJ38', 'depot'))
        self.assertEqual((tx['quantity'], tx['gross_income'], tx['gross_currency'], tx['taxes']),
                         ('102.038', '56.12', 'EUR', '10.36'))
        self.assertEqual((tx['per_share_amount'], tx['per_share_currency']), ('0.550022', 'EUR'))

    def test_compact_coupon_uses_bare_wkn_and_derives_gross_from_trailing_tax(self):
        self.put(snapshots=[Snapshot('Depot', '2026-05', '2026-05-01', 'Test', [
            Position('WKN:578560', 'FRESENIUS SE+CO.KGAA O.N.', wkn='578560',
                     quantity='3.878', value='170')])])
        purpose = ('Kupon ERTRAEGNISGUTSCHRIFT VOM 27.05.26 0A5C294F08T28 '
                   'DEPOTBESTAND: 3,878 1I6/2 FRESENIUS SE+CO.KGAA O.N. 578560 EUR 1,05')
        self.put([BankTransaction('Cash', 'compact-coupon', '2026-05-27', 'BANK_BOOKING',
                                  '4.07', 'EUR', purpose=purpose)])
        tx = next(row for row in self.repo.transactions() if row['external_id'] == 'compact-coupon')
        self.assertEqual((tx['kind'], tx['security'], tx['performance_depot_key']),
                         ('DIVIDEND', 'WKN:578560', 'depot'))
        self.assertEqual((tx['quantity'], tx['taxes'], tx['gross_income'], tx['gross_currency']),
                         ('3.878', None, '4.07', 'EUR'))
        self.assertEqual((tx['per_share_amount'], tx['per_share_currency']), ('1.05', 'EUR'))

    def test_coupon_merges_historical_wkn_and_later_isin_identity(self):
        self.put(snapshots=[Snapshot('Depot', '2020-11', '2020-11-25', 'Test', [
            Position('WKN:A0LEW8', 'ISHSII-DEV.MKT.PR.Y.DLDIS', wkn='A0LEW8',
                     quantity='66.476', value='1000')])])
        self.put(snapshots=[Snapshot('Depot', '2026-10', '2026-10-12', 'Test', [
            Position('IE00B1FZS350', 'iShsII-Dev.Mkts Prop.Yld U.ETF', isin='IE00B1FZS350',
                     wkn='A0LEW8', quantity='152.09', value='3200')])])
        purpose = ('Kupon ERTRAEGNISGUTSCHRIFT VOM 25.11.20 0IE20330K3543 '
                   'DEPOTBESTAND: 66,476 895/2 ISHSII-DEV.MKT.PR.Y.DLDIS '
                   'A0LEW8 USD 0,1398')
        self.put([BankTransaction('Cash', 'historical-coupon', '2020-11-26',
                                  'BANK_BOOKING', '7.80', 'EUR', purpose=purpose)])
        tx = next(row for row in self.repo.transactions()
                  if row['external_id'] == 'historical-coupon')
        self.assertEqual((tx['kind'], tx['security'], tx['performance_depot_key']),
                         ('DIVIDEND', 'IE00B1FZS350', 'depot'))
        self.assertEqual(tx['quantity'], '66.476')
        self.assertEqual((tx['per_share_amount'], tx['per_share_currency']), ('0.1398', 'USD'))

    def test_custody_fee_assigns_wkn_and_keeps_amount_with_positive_fee(self):
        self.put(snapshots=[Snapshot('Depot', '2025-05', '2025-05-01', 'Test', [
            Position('DE000A0S9GB0', 'Xetra Gold', isin='DE000A0S9GB0',
                     wkn='A0S9GB', quantity='2', value='200')])])
        purpose = ('Entgelte Verwahrentgelt Xetra Gold 9R2C29EV14XG '
                   'WKN A0S9GB, 3MBZ/7918 gem. Abrechnung')
        self.put([BankTransaction('Cash', 'custody-fee', '2026-09-15', 'BANK_BOOKING',
                                  '-7.50', 'EUR', purpose=purpose)])
        tx = next(row for row in self.repo.transactions() if row['external_id'] == 'custody-fee')
        self.assertEqual((tx['kind'], tx['security'], tx['performance_depot_key']),
                         ('FEE', 'DE000A0S9GB0', 'depot'))
        self.assertEqual((tx['amount'], tx['fees']), ('-7.50', '7.50'))

    def test_securities_purchase_uses_isin_and_adds_it_to_wkn_master_data(self):
        self.put(snapshots=[Snapshot('Depot', '2025-05', '2025-05-01', 'Test', [
            Position('WKN:A111X9', 'IS C.MSCI EMIMI U.ETF DLA', wkn='A111X9',
                     quantity='4', value='500')])])
        purpose = ('Wertpapiere IS C.MSCI EMIMI U.ETF DLA 5K5C29F00AF4 '
                   'WPKNR: A111X9 ISIN: IE00BKM4GZ66 2MDJ/2')
        self.put([BankTransaction('Cash', 'securities-buy', '2026-09-15', 'BANK_BOOKING',
                                  '-100', 'EUR', purpose=purpose.replace('Wertpapiere ', ''),
                                  operation='Wertpapiere')])
        tx = next(row for row in self.repo.transactions() if row['external_id'] == 'securities-buy')
        self.assertEqual((tx['kind'], tx['security'], tx['performance_depot_key']),
                         ('BUY', 'IE00BKM4GZ66', 'depot'))
        self.repo.sync_security_master()
        self.repo.remember_transaction_security_identifiers()
        master = self.repo.db.execute('SELECT * FROM security_master WHERE wkn=?', ('A111X9',)).fetchone()
        self.assertEqual(master['isin'], 'IE00BKM4GZ66')
        self.assertEqual(self.repo.assets.identity('IE00BKM4GZ66'),
                         self.repo.assets.identity('WKN:A111X9'))

    def test_operation_security_and_existing_isin_alone_are_enough_for_assignment(self):
        self.put([BankTransaction('Cash', 'isin-only-buy', '2026-09-16', 'BANK_BOOKING',
                                  '-125', 'EUR', purpose='Abrechnung ISIN US0378331005',
                                  operation='Wertpapier')])
        tx = next(row for row in self.repo.transactions() if row['external_id'] == 'isin-only-buy')
        self.assertEqual((tx['kind'], tx['security'], tx['performance_depot_key']),
                         ('BUY', ISIN, 'depot'))

    def test_depot_notice_and_cash_statement_count_once(self):
        self.put([self.dividend(account='Depot', affects_cash=False)])
        self.put([self.statement()])
        rows = self.repo.transactions()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['account'], 'Cash')
        self.assertTrue(rows[0]['affects_cash'])
        self.assertEqual(self.performance()['profit'], Decimal('300'))
        self.assertEqual(self.repo._cash_timelines()['cash']['totals'][-1], Decimal('300'))

    def test_unknown_or_foreign_gross_does_not_become_zero(self):
        self.put([self.dividend(gross_currency='USD')])
        self.assertIsNone(self.performance()['gross_dividends'])
        self.assertEqual(self.performance()['dividends'], Decimal('300'))

    def test_separate_tax_notice_is_not_presented_as_net(self):
        self.put([self.dividend(income_basis='gross')])
        result = self.performance()
        self.assertFalse(result['dividends_net_complete'])
        self.assertTrue(any('Steuern' in issue['title'] for issue in result['issues']))

    def test_linked_separate_fee_counts_once_in_security_performance(self):
        self.put([self.dividend(amount='290', gross_income='400', taxes='100', fees='10'),
                  BankTransaction('Cash', 'fee-notice', '2025-06-01', 'FEE', '-10', 'EUR',
                                  security=ISIN)])
        self.store.confirm_coverage('Depot', '2025-01-01', '2025-12-31')
        dividend = next(row for row in self.repo.transactions() if row['kind'] == 'DIVIDEND')
        fee = next(row for row in self.repo.transactions() if row['kind'] == 'FEE')
        # Without the link the fee is counted twice: embedded in the net
        # dividend credit and again as the separate cash booking.
        double = security_performance(self.store, 'Depot', '2025-01-01', '2025-12-31')
        self.assertEqual(double['profit'], Decimal('380'))
        self.repo.confirm_fee(reference(dividend), 'fees', reference(fee),
                              'Gebühr aus derselben Abrechnung')
        self.store.confirm_coverage('Depot', '2025-01-01', '2025-12-31')
        result = security_performance(self.store, 'Depot', '2025-01-01', '2025-12-31')
        # 400 gross - 100 taxes - 10 fee = 290 credit; the strict view adds
        # the embedded tax back once and keeps the fee exactly once.
        self.assertEqual(result['profit'], Decimal('390'))

    def test_reinvestment_does_not_double_return(self):
        self.put([self.dividend(account='Depot'),
            BankTransaction('Depot', 'reinvestment', '2025-12-31', 'kauf', '-300', 'EUR', security=ISIN, quantity='1')])
        self.assertEqual(self.performance()['profit'], Decimal('0'))

    def test_link_and_explicit_dividend_survive_reopen(self):
        self.put([self.dividend(performance_depot_key='depot')])
        self.repo.close()
        self.repo = RepositoryV09(Path(self.folder.name) / 'test.sqlite', backups=False)
        self.store = self.repo.store
        self.assertEqual(self.performance()['dividends'], Decimal('300'))
        self.assertEqual(self.repo.transactions()[0]['performance_depot_key'], 'depot')

    def test_edited_cash_booking_is_assigned_to_selected_depot_position(self):
        self.put([self.statement()])
        tx = self.repo.transactions()[0]
        self.repo.edit_transaction(reference(tx), dict(date=tx['date'], value_date=tx['date'],
            kind='DIVIDEND', amount=tx['amount'], currency=tx['currency'], counterparty='',
            purpose=tx['purpose'], security=ISIN, quantity=None), 'Dividendengutschrift geprüft')
        effective = performance_transactions(self.store, self.repo.transactions())
        self.assertEqual(effective[0]['account'], 'Depot')
        self.assertEqual(effective[0]['security'], ISIN)
        self.assertEqual(self.performance()['dividends'], Decimal('300'))

    def test_dividend_edit_keeps_net_gross_fees_and_taxes_separate(self):
        self.put([self.statement()])
        tx = self.repo.transactions()[0]
        values = dict(date=tx['date'], value_date=tx['date'], kind='DIVIDEND', amount='373', currency='EUR',
            counterparty='', purpose=tx['purpose'], security=ISIN, quantity='10', gross_income='400',
            gross_currency='EUR', fees='2', taxes='25', withholding_tax='15', income_basis='net')
        self.repo.edit_transaction(reference(tx), values, 'Abrechnung geprüft')
        edited = self.repo.transactions()[0]
        for field, expected in [('amount', '373'), ('gross_income', '400'), ('fees', '2'),
                                ('taxes', '25'), ('withholding_tax', '15')]:
            self.assertEqual(edited[field], expected)
        with self.assertRaisesRegex(ValueError, 'Netto'):
            self.repo.edit_transaction(reference(edited), {**values, 'amount': '374'}, 'Fehlerhafte Abrechnung')
        with self.assertRaisesRegex(ValueError, 'Quellensteuer'):
            self.repo.edit_transaction(reference(edited), {**values, 'withholding_tax': '26'}, 'Fehlerhafte Steuer')

    def test_ambiguous_documents_do_not_silently_double_performance(self):
        self.put([self.dividend()])
        self.put([self.statement(), self.statement(external_id='second-occurrence')])
        self.assertEqual(len(self.repo.transactions()), 3)
        self.assertIn('Mehrere mögliche Belege', self.performance()['error'])

    def test_non_cash_purchase_is_a_performance_flow(self):
        self.put([BankTransaction('Depot', 'pdf-buy', '2025-06-01', 'BUY', '1000', 'EUR',
                                 security=ISIN, quantity='1', affects_cash=False)])
        self.assertEqual(self.performance()['profit'], Decimal('-1000'))

    def test_ing_plugin_records_net_gross_and_partial_tax(self):
        import importlib.util
        from portfolio_v5.pdf_plugins.api import PdfDocument, PdfPage, ParseContext
        spec = importlib.util.spec_from_file_location('ing_dividend_test',
            Path(__file__).resolve().parents[1] / 'pdf_plugins' / 'ing_wertpapiere.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        text = '''ING-DiBa
Dividendengutschrift
ISIN (WKN) US0378331005 (865985)
Wertpapierbezeichnung Apple
Nominale 10 St\u00fcck
Valuta 31.12.2025
Abrechnungs-IBAN DE89370400440532013000
Brutto USD 400,00
QuSt 15 % (EUR 60,00) USD 60,00
Gesamtbetrag zu Ihren Gunsten EUR 300,00
'''
        document = PdfDocument(Path('dividend.pdf'), b'%PDF-1.4\n%%EOF', 'hash', (PdfPage(1, text),))
        detection = module.plugin.detect(document)[0]
        batch = module.plugin.parse(document, detection, ParseContext(ImportBatch('dividend.pdf', 'hash')))
        tx = batch.transactions[0]
        self.assertEqual(tx.kind, 'DIVIDEND')
        self.assertEqual(tx.amount, '300.00')
        self.assertEqual(tx.gross_income, '400.00')
        self.assertEqual(tx.gross_currency, 'USD')
        self.assertEqual(tx.withholding_tax, '60.00')
        self.assertEqual(tx.taxes, '60.00')

    def test_two_documents_both_orders_and_undo(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                first, second = (self.statement(), self.dividend()) if reverse else (self.dividend(), self.statement())
                a, b = self.put([first]), self.put([second])
                rows = self.repo.transactions()
                self.assertEqual(len(rows), 1)
                self.assertEqual(len(rows[0]['booking_sources']), 2)
                self.assertEqual(self.performance()['profit'], Decimal('300'))
                self.store.undo_import(b['id'])
                self.assertEqual(len(self.repo.transactions()), 1)
                self.store.undo_import(a['id'])

    def test_comdirect_gross_notice_and_later_net_statement_count_once(self):
        self.put(snapshots=[Snapshot('Depot', '2025-12', '2025-12-01', 'Test', [
            Position(ISIN, 'Apple', isin=ISIN, wkn='865985', quantity='10', value='10000')])])
        notice = self.dividend(
            external_id='pdf-income-notice', date='2025-12-30', value_date='2025-12-30',
            amount='400', gross_income=None, taxes=None,
            booking_text='comdirect Ertragsgutschrift',
            purpose='comdirect Ertragsgutschrift: Apple (US0378331005, WKN 865985) 10 Stk.')
        statement = self.statement(
            external_id='finance-net', date='2025-12-31', value_date='2025-12-31', amount='300',
            purpose=('Kupon ERTRAEGNISGUTSCHRIFT VOM 30.12.25 DEPOTBESTAND: 10 '
                     'Apple WKN 865985 USD 40,00 Abr.Betrag Brutto 400,00 EUR '
                     'Steuerabzug 100,00- EUR'))

        self.put([notice])
        self.put([statement])

        rows = self.repo.transactions()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['kind'], rows[0]['amount'], rows[0]['gross_income'], rows[0]['taxes']),
                         ('DIVIDEND', '300', '400.00', '100.00'))
        self.assertEqual(len(rows[0]['booking_sources']), 2)
        self.assertEqual(self.performance()['profit'], Decimal('300'))

    def test_gross_notice_without_statement_keeps_documented_tax_in_performance(self):
        reference = 'TAX-AND-SETTLEMENT'
        self.put([self.dividend(
            external_id='gross-only', amount='20.25', gross_income='20.25', taxes=None,
            bank_reference=reference, document_reference=reference,
            performance_depot_key='depot'),
            BankTransaction('Cash', 'tax-helper', '2025-12-31', 'TAX', '-3.74', 'EUR',
                            security=ISIN, taxes='3.74', affects_cash=False,
                            transaction_reference=reference, performance_depot_key='depot')])
        self.store.import_batch(ImportBatch('tax-event', 'tax-event', tax_events=[TaxEvent(
            'tax-event', 'Depot', 'investment_ausschuettung_inland', '2025-12-31',
            security_ref=ISIN, gross_income='20.25', taxable_income='14.18',
            partial_exemption_amount='6.07', paid_taxes='3.74', reference_no=reference,
            related_transaction_id='tax-helper', cash_account='Cash')]))

        flows = performance_transactions(self.store, self.repo.transactions(), 'Depot')
        self.assertEqual([(tx['kind'], tx['amount']) for tx in flows],
                         [('DIVIDEND', '20.25'), ('TAX', '-3.74')])
        self.assertEqual(sum(Decimal(tx['amount']) for tx in flows), Decimal('16.51'))

    def test_generic_or_conflicting_payments_are_not_merged(self):
        self.put([self.dividend(bank_reference='REF-ONE')])
        self.put([self.statement(bank_reference='REF-TWO')])
        self.put([self.statement(external_id='generic', purpose='Gutschrift')])
        self.assertEqual(len(self.repo.transactions()), 3)

    def test_shared_cash_requires_explicit_depot(self):
        self.store.save_account('Depot 2', {'kind': 'Depot', 'cash_account_key': 'cash'})
        self.put(snapshots=[Snapshot('Depot 2', '2025-01', '2025-01-01', 'Test',
            [Position(ISIN, 'Apple', isin=ISIN, quantity='2', value='2000')])])
        self.put([self.dividend()])
        self.assertIn('mehrdeutig', self.performance()['error'])
        self.put([self.dividend(performance_depot_key='depot')])
        self.assertEqual(self.performance()['profit'], Decimal('300'))
        flows = performance_transactions(self.store, self.repo.transactions(), 'Depot 2')
        self.assertEqual(flows, [])

    def test_manual_portfolio_assignment_and_rule_apply_to_later_booking(self):
        first = self.statement(external_id='first', purpose='Apple Dividende Quartal 4')
        self.put([first])
        tx = self.repo.transactions()[0]
        self.repo.assign_portfolio_transaction(reference(tx), 'DIVIDEND', ISIN, 'depot',
            'Abrechnung und Depotbestand geprüft', 'Apple Dividende')
        assigned = self.repo.transactions()[0]
        self.assertEqual(assigned['kind'], 'DIVIDEND')
        self.assertEqual(assigned['security'], ISIN)
        self.assertEqual(assigned['performance_depot_key'], 'depot')
        self.put([self.statement(external_id='second', purpose='Apple Dividende Quartal 1')])
        automatic = next(t for t in self.repo.transactions() if t['external_id'] == 'second')
        self.assertEqual(automatic['kind'], 'DIVIDEND')
        self.assertEqual(automatic['security'], ISIN)
        self.assertEqual(automatic['performance_depot_key'], 'depot')
        self.assertEqual(automatic['assignment_source'], 'Gespeicherte Zuordnungsregel')
        flows = performance_transactions(self.store, self.repo.transactions(), 'Depot')
        self.assertEqual(len(flows), 2)

    def test_tax_and_fee_are_assigned_to_linked_depot_and_position(self):
        self.put([BankTransaction('Cash', 'tax', '2025-06-01', 'TAX', '-20', 'EUR',
                                  security=ISIN, performance_depot_key='depot'),
                  BankTransaction('Cash', 'fee', '2025-06-02', 'FEE', '-5', 'EUR',
                                  security=ISIN, performance_depot_key='depot')])
        flows = performance_transactions(self.store, self.repo.transactions(), 'Depot')
        self.assertEqual([(t['kind'], t['amount'], t['account']) for t in flows],
                         [('TAX', '-20', 'Depot'), ('FEE', '-5', 'Depot')])

    def test_pdf_wording_recognizes_security_cash_kinds_conservatively(self):
        self.assertEqual(portfolio_cash_kind({'kind': 'BANK_BOOKING', 'purpose': 'Kapitalertragsteuer Apple'}), 'TAX')
        self.assertEqual(portfolio_cash_kind({'kind': 'BANK_BOOKING', 'purpose': 'Vorabpauschale Fonds'}), 'TAX')
        self.assertEqual(portfolio_cash_kind({'kind': 'BANK_BOOKING', 'purpose': 'Orderprovision Kauf'}), 'FEE')
        self.assertEqual(portfolio_cash_kind({'kind': 'BANK_BOOKING', 'purpose': 'Ertragsgutschrift Apple'}), 'DIVIDEND')
        self.assertEqual(portfolio_cash_kind({'kind': 'BANK_BOOKING', 'purpose': 'Allgemeine Gutschrift'}), 'BANK_BOOKING')

    def test_cash_link_survives_rename_and_rejects_invalid_target(self):
        self.store.save_account('Neues Cash', {'kind': 'Verrechnungskonto'}, original='Cash')
        self.put([self.dividend()])
        self.assertEqual(self.performance()['profit'], Decimal('300'))
        with self.assertRaises(ValueError):
            self.store.set_account_active('Neues Cash', False)
        with self.assertRaises(ValueError):
            self.store.save_account('Depot', {'kind': 'Depot', 'cash_account_key': 'depot'}, original='Depot')

    def test_pdf_preview_and_account_editor(self):
        from PySide6.QtWidgets import QApplication
        from portman.import_preview import ImportPreviewDialog
        from portman.account_editor import AccountEditor
        app = QApplication.instance() or QApplication([])
        record = next(r for r in self.repo.account_records() if r['name'] == 'Depot')
        editor = AccountEditor(self.repo, record)
        self.assertEqual(editor.cash_account.currentData(), 'cash')
        content = base64.b64encode(b'%PDF-1.4\n%%EOF').decode()
        batch = ImportBatch('dividend.pdf', 'preview', source_sheet='PDF',
            transactions=[self.dividend()], documents=[BankDocument('Cash', 'document', 'Dividend', '2025-12-31', content)])
        preview = ImportPreviewDialog(self.repo, [batch])
        for _, _, combo, _ in preview.mapping_rows:
            combo.setCurrentIndex(combo.findData('cash'))
        chosen = preview.selected_batches()[0]
        self.assertEqual(chosen.transactions[0].performance_depot_key, 'depot')
        preview.close()
        editor.close()
        app.processEvents()

    def test_pdf_preview_accepts_plain_security_transaction_and_persists_edits(self):
        from dataclasses import asdict
        from PySide6.QtWidgets import QApplication
        from portfolio_v5.models import Transaction
        from portman.import_preview import ImportPreviewDialog
        from portman.import_v09 import decode_batch
        app = QApplication.instance() or QApplication([])
        original = Transaction('Depot', 'plain-buy', '2025-12-31', 'BUY', '-100', 'EUR',
                               security=ISIN, quantity='1', fees='2')
        content = base64.b64encode(b'%PDF-1.4\n%%EOF').decode()
        batch = ImportBatch('buy.pdf', 'plain-preview', source_sheet='PDF',
            transactions=[original], documents=[BankDocument('Depot', 'document', 'Buy', '2025-12-31', content)])
        preview = ImportPreviewDialog(self.repo, [batch])
        for _, _, combo, _ in preview.mapping_rows:
            combo.setCurrentIndex(combo.findData('depot'))
        self.assertEqual(preview.pdf_bookings_table.item(0, 4).text(), '')
        self.assertIn(ISIN, preview.pdf_bookings_table.item(0, 6).text())
        preview.pdf_bookings_table.item(0, 4).setText('02.01.2026')
        preview.pdf_bookings_table.item(0, 6).setText('Geprüfter Wertpapierkauf')
        chosen = decode_batch(asdict(preview.selected_batches()[0]))
        tx = chosen.transactions[0]
        self.assertEqual(tx.value_date, '2026-01-02')
        self.assertEqual(tx.purpose, 'Geprüfter Wertpapierkauf')
        self.assertEqual(Decimal(tx.amount), Decimal(original.amount))
        for field in ('kind', 'security', 'quantity', 'fees', 'external_id'):
            self.assertEqual(getattr(tx, field), getattr(original, field))
        self.assertFalse(hasattr(original, 'value_date'))
        preview.close()
        app.processEvents()


if __name__ == '__main__':
    unittest.main()
