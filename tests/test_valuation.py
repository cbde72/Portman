from datetime import date
from decimal import Decimal
import pytest
from portman.repository import PortfolioRepository
from portman.valuation import current_wealth,eur_value
from portfolio_v5.models import ImportBatch,Snapshot,Position,Balance

TODAY=date(2026,9,19)
@pytest.fixture
def repo(tmp_path):
 r=PortfolioRepository(tmp_path/'test.sqlite')
 yield r
 r.close()

def setup(r, day='2026-09-16', complete=True, positions=True):
 p=[Position('X','Test',quantity='2',cost=None,value='120',currency='EUR')] if positions else []
 r.commit_batches([ImportBatch('test','test',snapshots=[Snapshot('Depot','2026-09',day,'Test',p,complete=complete)],
 balances=[Balance('2026-09','Wertpapiere','Depot','100','ETF',1),Balance('2026-09','Liquidität','Depot','50','ETF',2),
 Balance('2026-09','Schulden','Kredit','20','ETF',3)])])

def quote(r, price=100,currency='EUR',day='2026-09-18'):
 r.market.save_manual('X',{'price':price,'currency':currency},'Testbeleg',day)

def test_replaces_securities_preserves_cash_and_debt(repo):
 setup(repo);quote(repo)
 v=current_wealth(repo,today=TODAY)
 assert v['baseline']==130 and v['value']==230
 assert sum(r['category']=='Wertpapiere' for r in v['rows'])==1
 assert repo.wealth_summary()['value']==130

def test_old_holdings_do_not_become_current_with_new_quotes(repo):
 setup(repo,'2015-12-23');quote(repo)
 v=current_wealth(repo,today=TODAY)
 assert v['value']==130
 assert 'veraltet' in next(r for r in v['rows'] if r['category']=='Wertpapiere')['note']

def test_foreign_quote_conversion_and_pence():
 fx={'date':'2026-09-18','rates':{'USD':'1.25','GBP':'0.8'}}
 assert eur_value(Decimal(100),'USD',fx,TODAY)==80
 assert eur_value(Decimal(800),'GBp',fx,TODAY)==10
 assert eur_value(Decimal(800),'GBX',fx,TODAY)==10
 assert eur_value(Decimal(100),'JPY',fx,TODAY) is None
 assert eur_value(Decimal(100),'USD',{'date':'2026-08-01','rates':{'USD':'1'}},TODAY) is None

def test_missing_fx_keeps_imported_value_not_foreign_amount(repo):
 setup(repo);quote(repo,currency='USD')
 assert current_wealth(repo,today=TODAY)['value']==150
 repo.market.save_fx({'date':'2026-09-18','rates':{'USD':'1.25'},'source':'test'})
 assert current_wealth(repo,today=TODAY)['value']==190

@pytest.mark.parametrize('day',['2026-09-20','2026-08-01','2026-09-15'])
def test_future_old_or_pre_snapshot_quotes_not_used(repo,day):
 setup(repo);quote(repo,day=day)
 assert current_wealth(repo,today=TODAY)['value']==150

def test_incomplete_snapshot_does_not_replace_account(repo):
 setup(repo,complete=False);quote(repo)
 assert current_wealth(repo,today=TODAY)['value']==130

def test_complete_empty_depot_replaces_old_balance_with_zero(repo):
 setup(repo,positions=False)
 assert current_wealth(repo,today=TODAY)['value']==30

def test_account_filter_excludes_other_accounts(repo):
 setup(repo);quote(repo)
 assert current_wealth(repo,'Depot',TODAY)['value']==250
 repo.set_account_active('Depot',False)
 assert current_wealth(repo,today=TODAY)['value']==-20

def test_cost_correction_scoped_to_snapshot_and_preserves_raw(repo):
 setup(repo);p=repo.holdings()[0]
 repo.correct_cost(p['snapshot_id'],'X','75','Abrechnung 16.09.2026')
 assert repo.current()[0]['cost']=='75'
 assert repo.store.holdings()[0]['cost'] is None
 repo.commit_batches([ImportBatch('new','new',snapshots=[Snapshot('Depot','2026-09','2026-09-18','Test',
 [Position('X','Test',quantity='3',value='180')])])])
 assert repo.current()[0]['cost'] is None
 assert repo.current('2026-09-16')[0]['cost']=='75'

@pytest.mark.parametrize('cost,source',[('NaN','Beleg'),('-10','Beleg'),('10','')])
def test_invalid_cost_rejected(repo,cost,source):
 setup(repo);p=repo.holdings()[0]
 with pytest.raises(ValueError):repo.correct_cost(p['snapshot_id'],'X',cost,source)
