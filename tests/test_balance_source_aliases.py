import os
from decimal import Decimal

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from portfolio_v5.models import Balance, ImportBatch
from portfolio_v5.accounts import account_key
from portman.repository_v09 import RepositoryV09


def observation(repo, source, target, day, value, online=False, category='Liquidität'):
    sheet = 'Online comdirect' if online else 'PDF comdirect Finanzreport'
    return repo.store.import_batch(ImportBatch(source+day,source+day+value,
        source_sheet='Online comdirect' if online else 'PDF',
        balances=[Balance(day[:7],category,source,value,sheet+' '+day,1)],
        account_assignments={account_key(source):account_key(target)}))


def test_account_aliases_do_not_add_historical_balances(tmp_path):
    repo=RepositoryV09(tmp_path/'db.sqlite',backups=False)
    try:
        repo.create_accounts(['Girokonto','Tagesgeld'])
        observation(repo,'Online Giro','Girokonto','2026-09-29','1778.24',True)
        observation(repo,'Online Tagesgeld','Tagesgeld','2026-09-29','2000',True)
        observation(repo,'IBAN Giro','Girokonto','2026-10-01','4325.17')
        observation(repo,'IBAN Tagesgeld','Tagesgeld','2026-10-01','2002.52')
        # Old reports imported afterwards must neither add to nor replace the latest observation.
        observation(repo,'Konto 0476492400','Girokonto','2009-12-31','2447.22')
        observation(repo,'Giro Stammkonto','Girokonto','2013-07-01','485.25')
        observation(repo,'Konto 0476492405','Tagesgeld','2009-12-31','1025.45')
        observation(repo,'Tagesgeld Stammkonto','Tagesgeld','2013-07-01','7016.31')
        observation(repo,'Online Giro','Girokonto','2026-10-03','4325.17',True)
        observation(repo,'Online Tagesgeld','Tagesgeld','2026-10-03','2002.52',True)
        for day in ('2026-10-01','9999-12-31'):
            rows={r['name']:r for r in repo.account_overview(day)}
            assert rows['Girokonto']['balance']==Decimal('4325.17')
            assert rows['Tagesgeld']['balance']==Decimal('2002.52')
            assert repo.wealth_summary(day)['value']==Decimal('6327.69')
        assert repo.wealth_summary('2026-09-29')['value']==Decimal('3778.24')
        balances=[r for r in repo.balances() if r['period']=='2026-10']
        assert len(balances)==2
        assert sum(Decimal(r['value']) for r in balances)==Decimal('6327.69')
        assert repo.db.execute('SELECT count(*) FROM balances').fetchone()[0]==10
    finally: repo.close()


def test_same_month_uses_observation_date_not_import_order(tmp_path):
    repo=RepositoryV09(tmp_path/'db.sqlite',backups=False)
    try:
        repo.create_accounts(['Bank'])
        observation(repo,'IBAN','Bank','2026-09-30','100')
        observation(repo,'Online','Bank','2026-09-01','50',True)
        assert repo.wealth_summary('2026-09-15')['value']==50
        assert repo.wealth_summary('2026-09-30')['value']==100
        assert len(repo.balances())==1 and repo.balances()[0]['value']=='100'
        observation(repo,'IBAN','Bank','2026-09-30','120')
        assert repo.wealth_summary('2026-09-30')['value']==120
        assert repo.balances()[0]['value']=='120'
        observation(repo,'Andere Kategorie','Bank','2026-09-30','200',category='Festgeld')
        assert repo.wealth_summary('2026-09-30')['value']==320
    finally: repo.close()
