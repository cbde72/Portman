import tempfile
import unittest
import pytest
from pathlib import Path
from decimal import Decimal

from portfolio_v5.importers import parse_file
from portfolio_v5.models import ImportBatch, Position, Snapshot, Transaction
from portfolio_v5.performance import xirr
from portfolio_v5.storage import Store
from portman.repository import PortfolioRepository
from portman.performance_service import PerformanceService
from portman.rebalancing import plan_rebalancing
from portman.etf_factsheets import parse_holdings_text

ROOT=Path(__file__).resolve().parents[1]
class V05Tests(unittest.TestCase):
    @pytest.mark.skip(reason='Benutzerdaten-Datei history/finanzen2026-09.xlsx ist nicht im Arbeitsverzeichnis vorhanden.')
    def test_archive_xlsx(self):
        b=parse_file(ROOT/'history'/'finanzen2026-09.xlsx')
        self.assertFalse(b.errors); self.assertGreaterEqual(len(b.snapshots),3)
        self.assertGreater(sum(len(s.positions) for s in b.snapshots),50)
        self.assertTrue(any(s.account=='ING' and s.as_of=='2026-09-02' for s in b.snapshots))
    def test_csv_profiles(self):
        for f in (ROOT/'depots').glob('*.csv'):
            b=parse_file(f); self.assertFalse(b.errors, (f,b.errors)); self.assertTrue(b.snapshots)
    def test_duplicate_and_snapshot_materialization(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(Path(d)/'x.sqlite')
            b=ImportBatch('x','source',snapshots=[Snapshot('A','2026-01','2026-01-31','x',[Position('X','X',quantity='1',value='10')])])
            self.assertEqual(s.import_batch(b)['status'],'imported')
            self.assertEqual(s.import_batch(b)['status'],'duplicate')
            self.assertEqual(Decimal(s.holdings()[0]['value']),Decimal('10')); s.close()
    def test_xirr(self):
        r,e=xirr([('2025-01-01',Decimal('-100')),('2026-01-01',Decimal('110'))])
        self.assertIsNone(e); self.assertAlmostEqual(r,.1,places=6)
    def test_v06_repository_aggregates_accounts(self):
        with tempfile.TemporaryDirectory() as d:
            repo=PortfolioRepository(Path(d)/'x.sqlite')
            for account,value in [('A','10'),('B','20')]:
                b=ImportBatch(account,account,snapshots=[Snapshot(account,'2026-01','2026-01-31','x',[Position('X','Titel',isin='DE0000000001',quantity='1',cost='5',value=value)])])
                repo.store.import_batch(b)
            rows=repo.current();self.assertEqual(len(rows),1);self.assertEqual(Decimal(rows[0]['value']),Decimal('30'));self.assertEqual(Decimal(rows[0]['quantity']),Decimal('2'));repo.close()
    def test_master_data_preserves_original_name(self):
        with tempfile.TemporaryDirectory() as d:
            repo=PortfolioRepository(Path(d)/'x.sqlite');b=ImportBatch('x','x',snapshots=[Snapshot('A','2026-01','2026-01-31','x',[Position('DE0000000001','BANKNAME O.N.',isin='DE0000000001',quantity='1',value='10')])]);repo.store.import_batch(b);repo.sync_security_master();m=repo.metadata()['DE0000000001'];self.assertIn('BANKNAME O.N.',m['original_names']);repo.close()
    def test_canonical_name_persists(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'x.sqlite';repo=PortfolioRepository(path);b=ImportBatch('x','x',snapshots=[Snapshot('A','2026-01','2026-01-31','x',[Position('IE000S9YS762','LINDE PLC EO -,001',isin='IE000S9YS762',quantity='1',value='10')])]);repo.store.import_batch(b);repo.sync_security_master()
            class H:isin='IE000S9YS762';wkn='';name='Linde plc';asset_type='Aktie';region='Europa';cap_size='Large';beta=1.;volatility=15.;dividend_yield=1.
            repo.save_metadata([H()]);repo.close();repo=PortfolioRepository(path);self.assertEqual(repo.current()[0]['name'],'Linde plc');repo.close()
    def test_valuation_series_is_incremental(self):
        with tempfile.TemporaryDirectory() as d:
            repo=PortfolioRepository(Path(d)/'x.sqlite')
            for month,value in [('01','10'),('02','12')]:repo.store.import_batch(ImportBatch(month,month,snapshots=[Snapshot('A',f'2026-{month}',f'2026-{month}-28','x',[Position('X','X',quantity='1',value=value)])]))
            series=PerformanceService(repo).valuation_series('A');self.assertEqual([x['value'] for x in series],[Decimal('10'),Decimal('12')]);repo.close()
    def test_twr_neutralizes_purchase(self):
        with tempfile.TemporaryDirectory() as d:
            repo=PortfolioRepository(Path(d)/'x.sqlite')
            snapshots=[
                Snapshot('A','2026-01','2026-01-01','x',[Position('X','X',quantity='1',value='100')]),
                Snapshot('A','2026-01','2026-01-02','x',[Position('X','X',quantity='2',value='200')]),
                Snapshot('A','2026-01','2026-01-31','x',[Position('X','X',quantity='2',value='220')]),
            ]
            tx=Transaction('A','buy-1','2026-01-02','BUY','-100','EUR',security='X',quantity='1')
            repo.store.import_batch(ImportBatch('performance','performance',snapshots=snapshots,transactions=[tx]))
            result=PerformanceService(repo).analyze('A','2026-01-01','2026-01-31')
            self.assertAlmostEqual(float(result['value_change']),1.2,places=6)
            self.assertAlmostEqual(float(result['twr']),.1,places=6)
            self.assertEqual(result['net_contributions'],Decimal('100'))
            repo.close()
    def test_factsheet_holdings_formats(self):
        text='''Top-10-Positionen\nAPPLE 18,77%\nNVIDIA 18,54%\nPortfolio insgesamt 37,31%'''
        rows=parse_holdings_text(text)
        self.assertEqual([(r['name'],r['weight_pct']) for r in rows],[('APPLE',18.77),('NVIDIA',18.54)])
        xtrackers='''Die 10 größten ETF-Bestandteile\nWertpapier ISIN Gewichtung\nMICROSOFT US5949181045 5,85%\nNVIDIA US67066G1040 4,93%\nQuelle: DWS'''
        rows=parse_holdings_text(xtrackers)
        self.assertEqual(rows[0]['isin'],'US5949181045');self.assertEqual(rows[0]['name'],'MICROSOFT')
    def test_rebalancing_respects_buy_budget_and_fee(self):
        result=plan_rebalancing({'Aktie':6000,'ETF':4000},{'Aktie':50,'ETF':50},cash=1000,tolerance_pct=0,minimum_order=10,fee=5,buys_only=True)
        self.assertLessEqual(result['cash_used'],Decimal('1000'));self.assertEqual(sum(r['action']>0 for r in result['rows']),1)
    def test_rebalancing_tolerance_suppresses_small_order(self):
        result=plan_rebalancing({'Aktie':5050,'ETF':4950},{'Aktie':50,'ETF':50},cash=0,tolerance_pct=1,minimum_order=0,fee=0,buys_only=False)
        self.assertTrue(all(r['action']==0 for r in result['rows']))

if __name__=='__main__': unittest.main()
