from portfolio_v5.models import ImportBatch, Snapshot, Position
from portfolio_v5.importers import parse_file
from portman.repository import PortfolioRepository


def test_legacy_crypto_migration_preserves_securities_and_target(tmp_path):
    path=tmp_path/'db.sqlite'
    repo=PortfolioRepository(path)
    repo.create_accounts(['Depot','Wallet'])
    securities=ImportBatch('finanzen2026-09.xlsx','stocks',snapshots=[Snapshot('ZERO','2026-09','2026-09-02','Zero',[Position('stock','Aktie',quantity='6.847',value='100')])],account_assignments={'finanzen zero':'depot'})
    crypto=ImportBatch('ZERO-pos-krypto-20.09.2026.csv','crypto',snapshots=[Snapshot('ZERO','2026-09','2026-09-20','CSV',[Position('btc','BTC',asset_type='Krypto',quantity='0.01423079',value='997.50')])],account_assignments={'finanzen zero':'wallet'})
    repo.commit_batches([securities,crypto]);repo.close()
    repo=PortfolioRepository(path)
    assert repo.holdings(account='Depot')[0]['quantity']=='6.847'
    assert repo.holdings(account='Wallet')[0]['quantity']=='0.01423079'
    assert {p['depot'] for p in repo.holdings()}=={'ZERO','ZERO/Krypto'}
    overview={r['name']:r for r in repo.account_overview()}
    assert overview['Depot']['depots'][0]['positions']==1
    assert overview['Wallet']['depots'][0]['positions']==1
    assert len(repo.holdings('2026-09-10'))==1
    assert not repo.db.execute('PRAGMA foreign_key_check').fetchall()
    repo.close()
    repo=PortfolioRepository(path)
    assert len(repo.holdings())==2
    assert len(repo.imports())==2
    repo.close()


def test_new_zero_crypto_export_has_distinct_source(tmp_path):
    path=tmp_path/'ZERO-pos-krypto-20.09.2026.csv'
    path.write_text('Name;ISIN;Art;Anzahl;Kursdatum;Wert\nBTC;XC000A2YY6Q6;KRYPTO;0,01423079;20.09.2026;997,50\n',encoding='utf-8')
    batch=parse_file(path)
    assert not batch.errors
    assert batch.snapshots[0].account=='ZERO/Krypto'
    assert batch.snapshots[0].positions[0].quantity=='0.01423079'
