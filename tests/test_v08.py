import os
import json
from pathlib import Path
from decimal import Decimal
from types import SimpleNamespace
import pytest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from portfolio_v5.models import ImportBatch,Snapshot,Position,BankTransaction
try:
    from portman.repository_v08 import RepositoryV08,reference
    from portman.import_v08 import ImportSession,parse_profile_csv
    from portman.analysis_v08 import change_analysis,export_report
    from portman.storage_v08 import backup_records,export_package,prepare_restore,restore_prepared,unpack_package
except ImportError:
    pytest.skip('Legacy: V08-Schemamodule wurden entfernt (repository_v08, import_v08, analysis_v08, storage_v08).', allow_module_level=True)


@pytest.fixture
def repo(tmp_path):
    result=RepositoryV08(tmp_path/'portfolio.sqlite',backups=False)
    yield result
    result.close()


def job(repo): return SimpleNamespace(path=str(repo.store.path),progress=SimpleNamespace(emit=lambda *a:None),isInterruptionRequested=lambda:False)


def snapshot(day,value='100',units='1',depot='Depot',currency='EUR'):
    return ImportBatch(day+depot,day+depot+value,snapshots=[Snapshot(depot,day[:7],day,'Test',[Position('TEST','Test',quantity=units,value=value,currency=currency)])])


def booking(path='one',external='tx1',amount='100',account='Bank',day='2026-01-01'):
    return ImportBatch(path,path,transactions=[BankTransaction(account,external,day,'BANK_BOOKING',amount,'EUR',purpose='Test')],account_names=[account])


def test_revision_persists_and_open_is_read_stable(repo):
    repo.commit_batches([snapshot('2026-01-01')]); revision=repo.revision()
    other=RepositoryV08(repo.store.path,backups=False)
    try: assert other.revision()==revision
    finally: other.close()
    repo.create_accounts(['Extra']); assert repo.revision()>revision


def test_single_snapshot_simulations_do_not_accumulate(repo):
    session=ImportSession(repo.store.path,[snapshot('2026-01-01')])
    session.snapshot.stat().st_size
    for _ in range(3):
        result=session.simulate(job(repo),session.batches,{})
        assert result['results'][0]['status']=='imported'
    assert len(list(session.folder.glob('*.sqlite')))==1
    assert repo.holdings()==[]
    session.commit(job(repo),session.batches,{})
    assert len(repo.holdings())==1


def test_stale_import_rejected_without_partial_write(repo):
    session=ImportSession(repo.store.path,[snapshot('2026-01-01')])
    repo.create_accounts(['Changed'])
    with pytest.raises(ValueError,match='seit der Vorschau'): session.commit(job(repo),session.batches,{})
    assert repo.holdings()==[]


def test_changed_source_rejected(repo,tmp_path):
    source=tmp_path/'source.csv'; source.write_text('original')
    b=booking(str(source)); session=ImportSession(repo.store.path,[b]); source.write_text('changed')
    with pytest.raises(ValueError,match='Quelldatei'): session.commit(job(repo),[b],{})
    assert not repo.transactions()


def test_replace_is_audited_and_undo_restores_old(repo):
    repo.commit_batches([booking()]); old=repo.transactions()[0]
    b=booking('two','tx2'); session=ImportSession(repo.store.path,[b]); conflicts=session.conflicts([b]); assert len(conflicts)==1
    decisions={conflicts[0]['key']:dict(action='replace',reason='Geprüfter neuer Beleg')}
    result=session.commit(job(repo),[b],decisions)
    assert len(repo.transactions())==1 and repo.transactions()[0]['external_id'].startswith('tx2')
    assert repo.db.execute("SELECT count(*) FROM change_log WHERE entity='transaction_supersessions'").fetchone()[0]==1
    repo.undo_import(result[0]['id'])
    assert repo.transactions()==[old]


def test_keep_same_external_id_preserves_both(repo):
    repo.commit_batches([booking()]); b=booking('two'); session=ImportSession(repo.store.path,[b])
    decisions={c['key']:dict(action='keep') for c in session.conflicts([b])}
    session.commit(job(repo),[b],decisions)
    assert len(repo.transactions())==2


def test_unresolved_conflict_cannot_commit(repo):
    repo.commit_batches([booking()]); b=booking('two'); session=ImportSession(repo.store.path,[b])
    with pytest.raises(ValueError,match='ausdrücklich'): session.commit(job(repo),[b],{})
    assert len(repo.transactions())==1


def test_save_resume_session(repo):
    b=booking(); session=ImportSession(repo.store.path,[b]); saved=session.save()
    resumed=ImportSession.resume(repo.store.path,saved)
    assert resumed.batches[0].transactions[0].purpose=='Test'
    assert resumed.revision==session.revision
    resumed.commit(job(repo),resumed.batches,{})
    assert len(repo.transactions())==1


def test_atomic_multi_batch_failure(repo):
    batches=[booking(),ImportBatch('bad','bad',errors=['Broken'])]; session=ImportSession(repo.store.path,batches)
    with pytest.raises(ValueError,match='Broken'): session.commit(job(repo),batches,{})
    assert not repo.transactions()


def test_unknown_start_not_zero_and_same_coverage(repo):
    repo.create_accounts(['A','B']); repo.add_balance('A','100','2026-01-01'); repo.add_balance('A','120','2026-02-01'); repo.add_balance('B','500','2026-02-01')
    data=change_analysis(repo,'2026-01-01','2026-02-01')
    assert data['comparable_change']==Decimal(20)
    b=next(r for r in data['accounts'] if r['account']=='B'); assert b['before'] is None and b['change'] is None


def test_aggregate_units_can_be_verified(repo):
    repo.commit_batches([snapshot('2026-01-01'),snapshot('2026-02-01')]); repo.confirm_coverage('Depot','2026-01-01','2026-02-01')
    data=change_analysis(repo,'2026-01-01','2026-02-01')
    assert data['positions'][0]['status']=='Abgestimmt'


def test_missing_snapshot_is_unknown(repo):
    repo.commit_batches([snapshot('2026-02-01')])
    r=change_analysis(repo,'2026-01-01','2026-02-01')['positions'][0]
    assert r['before'] is None and r['opening_units'] is None and r['change'] is None


def test_split_replays_units_without_mutating_original(repo):
    repo.commit_batches([snapshot('2026-01-01','100','1'),snapshot('2026-02-01','100','2')])
    repo.add_action('2026-01-15','Depot','TEST','SPLIT','Beleg',ratio='2')
    row=change_analysis(repo,'2026-01-01','2026-02-01')['positions'][0]
    assert row['expected_units']==2 and row['difference']==0 and row['price_effect'] is None
    assert repo.holdings('2026-01-01')[0]['quantity']=='1'


def test_fx_decomposition_requires_evidence(repo):
    repo.commit_batches([snapshot('2026-01-01','100','1',currency='USD'),snapshot('2026-02-01','120','1',currency='USD')])
    assert change_analysis(repo,'2026-01-01','2026-02-01')['positions'][0]['fx_effect'] is None
    repo.save_fx('2026-01-01','USD','.9','Beleg'); repo.save_fx('2026-02-01','USD','.8','Beleg')
    row=change_analysis(repo,'2026-01-01','2026-02-01')['positions'][0]
    assert row['price_effect']==18 and row['fx_effect']==-12


def test_internal_transfer_scoped_cashflow(repo):
    repo.commit_batches([booking('a','a','-100','A','2026-01-10'),booking('b','b','100','B','2026-01-11')])
    a,b=repo.transactions(); repo.confirm_transfer(reference(a),reference(b),'Gegenkonto geprüft')
    assert change_analysis(repo,'2026-01-01','2026-02-01')['unclassified']==0
    assert change_analysis(repo,'2026-01-01','2026-02-01','A')['internal']['EUR']==-100
    with pytest.raises(ValueError): repo.confirm_transfer(reference(a),reference(b),'Nochmal')


def test_view_overwrite_explicit_and_undo(repo):
    repo.save_view('Test',{'a':1})
    with pytest.raises(ValueError): repo.save_view('Test',{'a':2})
    repo.save_view('Test',{'a':2},replace=True); repo.undo_view(); assert repo.saved_views()['Test']=={'a':1}
    repo.delete_view('Test'); repo.undo_view(); assert repo.saved_views()['Test']=={'a':1}


def test_manual_backup_survives_rotation(repo):
    manual=repo.backup(label='Bleibt')
    for _ in range(15): repo.backup('before-change')
    assert manual.exists()
    assert len(backup_records(repo.backup_folder))<16


def test_package_hash_and_restore(repo,tmp_path):
    repo.create_accounts(['A']); repo.add_balance('A','100','2026-01-01')
    path=tmp_path/'backup.zip'; export_package(repo.db,tmp_path,path)
    repo.add_balance('A','200','2026-02-01'); folder=tmp_path/'prepared'; prepare_restore(path,folder)
    restore_prepared(repo.db,folder,tmp_path)
    assert repo.wealth_summary()['value']==100


def test_malicious_package_path_rejected(tmp_path):
    import zipfile
    source=tmp_path/'bad.zip'
    with zipfile.ZipFile(source,'w') as archive: archive.writestr('../outside','bad')
    with pytest.raises(ValueError): unpack_package(source,tmp_path/'target')
    assert not (tmp_path/'outside').exists()


def test_csv_profile_respects_sign_and_decimal(tmp_path):
    source=tmp_path/'input.csv'; source.write_text('Account;Day;Amount\nA;01/31/2026;1,234.56\n',encoding='utf-8')
    profile=dict(columns=dict(account='Account',date='Day',amount='Amount'),date_format='%m/%d/%Y',decimal='.',thousands=',',invert_sign=True)
    result=parse_profile_csv(source,profile)
    assert not result.errors and result.transactions[0].amount=='-1234.56' and result.transactions[0].date=='2026-01-31'


def test_analysis_invalid_range_clears_ui(repo):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QDate
    from portman.widgets_v08 import AnalysisDialog
    QApplication.instance() or QApplication([])
    repo.commit_batches([snapshot('2026-01-01'),snapshot('2026-02-01')])
    dialog=AnalysisDialog(repo,start='2026-01-01',end='2026-02-01')
    assert dialog.tables[2].rowCount()==1
    dialog.start.setDate(QDate(2026,3,1))
    assert dialog.data is None and not dialog.export.isEnabled() and all(t.rowCount()==0 for t in dialog.tables)
    dialog.close()


def test_report_escapes_sources(repo,tmp_path):
    repo.commit_batches([snapshot('2026-01-01'),snapshot('2026-02-01')]); data=change_analysis(repo,'2026-01-01','2026-02-01'); data['scope']='<script>x</script>'
    destination=tmp_path/'report.html'; export_report(data,destination)
    assert '<script>' not in destination.read_text(encoding='utf-8') and 'Datenrevision' in destination.read_text(encoding='utf-8')


def test_fee_auxiliary_field_and_dedicated_row_count_once(repo):
    from portfolio_v5.models import Transaction
    repo.commit_batches([ImportBatch('fees','fees',transactions=[
        Transaction('A','buy','2026-01-10','BUY','-100','EUR',security='TEST',quantity='1',fees='2'),
        Transaction('A','fee','2026-01-10','FEE','-2','EUR',security='TEST',fees='2')])])
    rows=change_analysis(repo,'2026-01-01','2026-02-01')['income']
    assert sum(r['amount'] for r in rows if r['kind']=='FEE')==-2


def test_restoration_invalidates_previously_reviewed_session(repo,tmp_path):
    backup=repo.backup(); session=ImportSession(repo.store.path,[booking()]); folder=tmp_path/'restored'
    prepare_restore(backup,folder); restore_prepared(repo.db,folder,tmp_path)
    with pytest.raises(ValueError,match='seit der Vorschau'): session.commit(job(repo),session.batches,{})


def test_package_contains_recoverable_original_manifest(repo,tmp_path):
    source=tmp_path/'original.csv'; source.write_text('Testbeleg',encoding='utf-8'); b=booking(str(source)); repo.commit_batches([b])
    archive=tmp_path/'full.zip'; export_package(repo.db,tmp_path,archive,True)
    prepared=tmp_path/'prepared'; prepare_restore(archive,prepared); restore_prepared(repo.db,prepared,tmp_path)
    manifest=json.loads((tmp_path/'restored-sources/manifest.json').read_text(encoding='utf-8'))
    item=manifest['sources'][0]
    assert item['included'] and (tmp_path/'restored-sources'/Path(item['entry']).relative_to('sources')).read_text(encoding='utf-8')=='Testbeleg'


def test_bounded_repository_and_storage_caches(repo):
    for year in range(1900,2000): repo.holdings(f'{year}-01-01'); repo.store.holdings(f'{year}-01-01')
    assert len(repo._v8_cache)<=32 and len(repo.store._read_cache)<=64


def test_cancel_before_commit_leaves_database_unchanged(repo):
    session=ImportSession(repo.store.path,[booking()]); cancelled=job(repo); cancelled.isInterruptionRequested=lambda:True
    with pytest.raises(ValueError,match='abgebrochen'): session.commit(cancelled,session.batches,{})
    assert repo.transactions()==[]


def test_restore_file_failure_rolls_back_database(repo,tmp_path,monkeypatch):
    import portman.storage_v08 as storage
    repo.create_accounts(['A']); repo.add_balance('A','100','2026-01-01')
    prepared=tmp_path/'prepared'; prepare_restore(repo.backup(),prepared)
    (prepared/'settings').mkdir(); (prepared/'settings/portfolio_settings.json').write_text('{}')
    repo.add_balance('A','200','2026-02-01')
    original=storage.os.replace
    def fail(source,target):
        if str(source).endswith('.restore-tmp'): raise OSError('disk full')
        return original(source,target)
    monkeypatch.setattr(storage.os,'replace',fail)
    with pytest.raises(OSError,match='disk full'): restore_prepared(repo.db,prepared,tmp_path)
    assert repo.wealth_summary()['value']==200
