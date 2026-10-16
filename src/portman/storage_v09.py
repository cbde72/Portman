"""V09 migrations, protected/retained backups and portable recovery packages."""
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from .persistence import atomic_json, read_json


def inspect_database(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Die Datenbank ist beschädigt.')
        if db.execute('PRAGMA user_version').fetchone()[0] > 9:
            raise ValueError('Diese Datenbank benötigt eine neuere PortMan-Version.')
        if db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone() != ('1',):
            raise ValueError('Kein unterstütztes PortMan-Datenbankschema.')
        return {name: db.execute(f'SELECT count(*) FROM {name}').fetchone()[0]
                for name in ('accounts', 'imports', 'snapshots', 'balances', 'transactions', 'bank_documents')}


def migrate(db):
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version > 9: raise ValueError('Nicht unterstützte Datenbankversion.')
    if version == 9:
        _ensure_transaction_review(db)
        return
    from .schema_previous import migrate as migrate_previous
    migrate_previous(db)
    with db:
        db.execute('CREATE TABLE IF NOT EXISTS v09_revision(id INTEGER PRIMARY KEY CHECK(id=1), value INTEGER NOT NULL)')
        db.execute('INSERT OR IGNORE INTO v09_revision VALUES(1,0)')
        db.execute('CREATE TABLE IF NOT EXISTS view_history(id INTEGER PRIMARY KEY, name TEXT NOT NULL, payload TEXT NOT NULL, operation TEXT NOT NULL, changed_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        db.execute('CREATE TABLE IF NOT EXISTS csv_profiles(name TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        db.execute('''CREATE TABLE IF NOT EXISTS transaction_supersessions(
            id INTEGER PRIMARY KEY, old_import INTEGER NOT NULL, old_account TEXT NOT NULL, old_id TEXT NOT NULL,
            new_import INTEGER NOT NULL, new_account TEXT NOT NULL, new_id TEXT NOT NULL, reason TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        db.execute('CREATE INDEX IF NOT EXISTS supersession_new_import ON transaction_supersessions(new_import)')
        db.execute('CREATE TABLE IF NOT EXISTS transfer_pairs(id INTEGER PRIMARY KEY, first_ref TEXT UNIQUE NOT NULL, second_ref TEXT UNIQUE NOT NULL, note TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        db.execute('''CREATE TABLE IF NOT EXISTS corporate_actions(id INTEGER PRIMARY KEY, day TEXT NOT NULL,
            depot TEXT NOT NULL, security TEXT NOT NULL, kind TEXT NOT NULL, target TEXT, target_depot TEXT,
            ratio TEXT, units TEXT, sequence INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)''')
        db.execute('CREATE TABLE IF NOT EXISTS historical_fx(day TEXT NOT NULL, currency TEXT NOT NULL, rate TEXT NOT NULL, source TEXT NOT NULL, PRIMARY KEY(day,currency))')
        db.execute('''CREATE TABLE IF NOT EXISTS transaction_classifications(ref TEXT PRIMARY KEY, kind TEXT NOT NULL,
            security TEXT NOT NULL DEFAULT '', quantity TEXT, reason TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        db.execute('''CREATE TABLE IF NOT EXISTS fee_links(aux_ref TEXT NOT NULL, field TEXT NOT NULL, fee_ref TEXT NOT NULL UNIQUE,
            reason TEXT NOT NULL, PRIMARY KEY(aux_ref,field))''')
        db.execute('''CREATE TABLE IF NOT EXISTS recurring_rules(id INTEGER PRIMARY KEY, account TEXT NOT NULL,
            description TEXT NOT NULL, currency TEXT NOT NULL, amount TEXT NOT NULL, interval_days INTEGER NOT NULL,
            source_refs TEXT NOT NULL, confirmed_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        # A persistent business revision is comparable across SQLite connections.
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        excluded = {'v09_revision', 'schema_migrations', 'change_log', 'view_history', 'saved_views', 'csv_profiles', 'meta'}
        for table in tables:
            if table in excluded: continue
            columns = [r[1] for r in db.execute(f'PRAGMA table_info("{table}")')]
            for operation in ('INSERT', 'UPDATE', 'DELETE'):
                condition = '' if operation != 'UPDATE' else 'WHEN ' + ' OR '.join(
                    f'OLD."{c}" IS NOT NEW."{c}"' for c in columns if c not in ('updated_at',))
                db.execute(f'''CREATE TRIGGER IF NOT EXISTS revision09_{table}_{operation} AFTER {operation} ON "{table}"
                    {condition} BEGIN UPDATE v09_revision SET value=value+1 WHERE id=1; END''')
            if table in {'transfer_pairs', 'corporate_actions', 'historical_fx', 'transaction_supersessions', 'transaction_classifications','fee_links','recurring_rules'}:
                for operation in ('INSERT', 'UPDATE', 'DELETE'):
                    def js(prefix): return 'json_object(' + ','.join(f"'{c}',{prefix}.\"{c}\"" for c in columns) + ')'
                    old = 'NULL' if operation == 'INSERT' else js('OLD')
                    new = 'NULL' if operation == 'DELETE' else js('NEW')
                    db.execute(f'''CREATE TRIGGER IF NOT EXISTS audit08_{table}_{operation} AFTER {operation} ON "{table}"
                        BEGIN INSERT INTO change_log(entity,operation,old_data,new_data) VALUES('{table}','{operation}',{old},{new}); END''')
        db.execute('INSERT INTO schema_migrations VALUES(9,?)', (datetime.now(timezone.utc).isoformat(),))
        db.execute('PRAGMA user_version=9')
    _ensure_transaction_review(db)


def _ensure_transaction_review(db):
    """Add auditable booking corrections to existing V09 databases."""
    if _marker(db, 'v09_transaction_review_ready'):
        return
    with db:
        db.execute('''CREATE TABLE IF NOT EXISTS transaction_edits(
            ref TEXT PRIMARY KEY, payload TEXT NOT NULL, reason TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        db.execute('''CREATE TABLE IF NOT EXISTS transaction_exclusions(
            ref TEXT PRIMARY KEY, reason TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        db.execute('''CREATE TABLE IF NOT EXISTS transaction_duplicate_reviews(
            ref TEXT PRIMARY KEY, reason TEXT NOT NULL,
            reviewed_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        db.execute('''CREATE TABLE IF NOT EXISTS portfolio_assignment_rules(
            id INTEGER PRIMARY KEY, account_key TEXT NOT NULL, kind TEXT NOT NULL,
            text_pattern TEXT NOT NULL, security TEXT NOT NULL, depot_key TEXT NOT NULL,
            reason TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(account_key,kind,text_pattern))''')
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='v09_revision'").fetchone():
            for table in ('transaction_edits', 'transaction_exclusions', 'transaction_duplicate_reviews', 'portfolio_assignment_rules'):
                for operation in ('INSERT', 'UPDATE', 'DELETE'):
                    db.execute(f'''CREATE TRIGGER IF NOT EXISTS revision09_{table}_{operation}
                        AFTER {operation} ON {table} BEGIN
                        UPDATE v09_revision SET value=value+1 WHERE id=1; END''')
            # Only mark as done once the revision triggers could be installed;
            # otherwise a later migration run has to try again.
            db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('v09_transaction_review_ready','1')")


def _marker(db, key):
    """True if ``key`` was recorded in the ``meta`` table (missing table = False)."""
    try:
        return db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone() == ('1',)
    except sqlite3.OperationalError:
        return False


def initialize(root):
    root = Path(root); folder = root / 'data/v09'; folder.mkdir(parents=True, exist_ok=True)
    target = folder / 'portfolio.sqlite'
    source = next((p for p in (root / 'data/v08/portfolio.sqlite', root / 'data/v07/portfolio.sqlite', root / 'data/portfolio_v05.sqlite') if p.exists()), None)
    if not target.exists() and source:
        inspect_database(source)
        with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as src:
            backup_database(src, folder / 'backups', 'before-migration', protected=True, label='Vor Übernahme in V09')
            temporary = folder / 'migration.tmp'
            with closing(sqlite3.connect(temporary)) as dst: src.backup(dst)
        os.replace(temporary, target)
    origins = ([source.parent] if source else []) + [root / 'src/Gui', root, root / 'data']
    for name in ('portfolio_settings.json', 'etf_cache.json'):
        origin = next((p / name for p in origins if (p / name).is_file()), None)
        if origin and not (folder / name).exists(): atomic_json(folder / name, read_json(origin))
    banking = next((p / 'banking' for p in origins if (p / 'banking').is_dir()), None)
    if banking and not (folder / 'banking').exists():
        with tempfile.TemporaryDirectory(dir=folder) as temporary:
            staged = Path(temporary) / 'banking'; shutil.copytree(banking, staged); os.replace(staged, folder / 'banking')
    return folder


def backup_records(folder, verify=False, job=None):
    rows = []
    for path in sorted(Path(folder).glob('v09-*.sqlite'), reverse=True):
        if job and job.isInterruptionRequested(): raise ValueError('Sicherungsprüfung abgebrochen.')
        try:
            meta = read_json(path.with_suffix('.json'))
            if not meta: raise ValueError('Sicherungsbeschreibung fehlt')
            if verify: meta['counts'] = inspect_database(path)
            rows.append({**meta, 'path': str(path), 'status': 'OK' if verify else 'Noch nicht geprüft'})
        except Exception as error:
            rows.append({'path': str(path), 'label': path.name, 'protected': True, 'status': str(error)})
    return rows


def retained_backups(records):
    automatic = sorted((r for r in records if not r.get('protected', True) and r.get('created')), key=lambda r: r['created'], reverse=True)
    keep = {r['path'] for r in records if r.get('protected', True)} | {r['path'] for r in automatic[:6]}
    for mode, count in (('day', 7), ('week', 8), ('month', 12)):
        buckets = set()
        for row in automatic:
            stamp = datetime.fromisoformat(row['created'])
            key = stamp.date().isoformat() if mode == 'day' else stamp.isocalendar()[:2] if mode == 'week' else (stamp.year, stamp.month)
            if key not in buckets and len(buckets) < count:
                buckets.add(key); keep.add(row['path'])
    return keep


def backup_database(db, folder, reason='manual', protected=None, label=''):
    folder = Path(folder).resolve(); folder.mkdir(parents=True, exist_ok=True)
    created = datetime.now(timezone.utc)
    path = folder / ('v09-' + created.strftime('%Y%m%d-%H%M%S-%f') + '.sqlite')
    temporary = path.with_suffix('.tmp')
    try:
        with closing(sqlite3.connect(temporary)) as dst: db.backup(dst)
        counts = inspect_database(temporary)
        os.replace(temporary, path)
        if protected is None: protected = reason in ('manual', 'before-migration', 'before-restore')
        atomic_json(path.with_suffix('.json'), {'created': created.isoformat(), 'reason': reason,
                    'protected': protected, 'label': label or reason, 'counts': counts})
        records = backup_records(folder); keep = retained_backups(records)
        for row in records:
            old = Path(row['path'])
            if str(old) not in keep and old.resolve().parent == folder and not old.is_symlink():
                old.unlink(); old.with_suffix('.json').unlink(missing_ok=True)
        return path
    finally: temporary.unlink(missing_ok=True)


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''): result.update(block)
    return result.hexdigest()


def export_package(db, data_folder, destination, include_sources=False, job=None, include_credentials=False):
    data_folder = Path(data_folder); destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        snapshot = Path(temporary) / 'portfolio.sqlite'
        with closing(sqlite3.connect(snapshot)) as dst: db.backup(dst)
        inspect_database(snapshot)
        manifest = {'format': 1, 'created': datetime.now(timezone.utc).isoformat(), 'files': {}, 'sources': []}
        entries = {'portfolio.sqlite': snapshot}
        for name in ('portfolio_settings.json', 'etf_cache.json'):
            if (data_folder / name).is_file(): entries['settings/' + name] = data_folder / name
        for path in (data_folder / 'banking').rglob('*') if include_credentials and (data_folder / 'banking').exists() else []:
            if path.is_file() and not path.is_symlink(): entries['banking/' + path.relative_to(data_folder / 'banking').as_posix()] = path
        for row in db.execute('SELECT DISTINCT path FROM imports'):
            path = Path(row[0]); item = {'path': str(path), 'included': False}
            try:
                if path.is_file():
                    item.update(sha256=file_hash(path), bytes=path.stat().st_size)
                    if include_sources:
                        entry = f"sources/{item['sha256']}/{path.name}"; entries[entry] = path
                        item.update(included=True, entry=entry)
            except OSError: item['error'] = 'Quelle nicht lesbar'
            manifest['sources'].append(item)
        temp_zip = destination.with_name(destination.name + '.tmp')
        try:
            with zipfile.ZipFile(temp_zip, 'w', zipfile.ZIP_DEFLATED) as archive:
                for entry, path in entries.items():
                    if job and job.isInterruptionRequested(): raise ValueError('Paketerstellung abgebrochen.')
                    # Hash the exact bytes written, even if a source changes during export.
                    digest = hashlib.sha256()
                    with path.open('rb') as source, archive.open(entry, 'w', force_zip64=True) as target:
                        for block in iter(lambda: source.read(1024 * 1024), b''):
                            if job and job.isInterruptionRequested(): raise ValueError('Paketerstellung abgebrochen.')
                            digest.update(block); target.write(block)
                    manifest['files'][entry] = digest.hexdigest()
                    if job: job.progress.emit(len(manifest['files']),len(entries))
                for source in manifest['sources']:
                    if source.get('included'): source['sha256'] = manifest['files'][source['entry']]
                archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
            os.replace(temp_zip, destination)
        finally: temp_zip.unlink(missing_ok=True)
    return manifest


def unpack_package(path, folder):
    folder = Path(folder).resolve()
    with zipfile.ZipFile(path) as archive:
        if sum(i.file_size for i in archive.infolist()) > 5 * 1024**3: raise ValueError('Sicherungspaket ist größer als 5 GB.')
        names = archive.namelist()
        if len(set(names)) != len(names): raise ValueError('Doppelte Dateinamen im Sicherungspaket.')
        for info in archive.infolist():
            part = PurePosixPath(info.filename)
            if part.is_absolute() or '..' in part.parts or ':' in info.filename or '\\' in info.filename or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Unsicherer Dateipfad im Sicherungspaket.')
            if info.is_dir(): continue
            if info.filename not in ('portfolio.sqlite', 'manifest.json') and part.parts[0] not in ('settings', 'banking', 'sources'):
                raise ValueError('Unerwarteter Paketinhalt.')
            target = folder.joinpath(*part.parts); target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, target.open('wb') as dst: shutil.copyfileobj(src, dst)
    manifest = read_json(folder / 'manifest.json')
    if manifest.get('format') != 1 or 'portfolio.sqlite' not in manifest.get('files', {}): raise ValueError('Kein V09-Sicherungspaket.')
    if set(names) - {'manifest.json'} != set(manifest['files']): raise ValueError('Paketverzeichnis stimmt nicht mit dem Inhalt überein.')
    for entry, expected in manifest['files'].items():
        if file_hash(folder / entry) != expected: raise ValueError('Prüfsumme stimmt nicht: ' + entry)
    inspect_database(folder / 'portfolio.sqlite')
    return manifest


def prepare_restore(source, folder):
    """Always migrate a disposable copy, never the original backup."""
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(source): unpack_package(source, folder)
    else:
        inspect_database(source)
        with closing(sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True)) as src:
            with closing(sqlite3.connect(folder / 'portfolio.sqlite')) as dst: src.backup(dst)
    from .repository import PortfolioRepository
    repo = PortfolioRepository(folder / 'portfolio.sqlite')
    try: migrate(repo.db)
    finally: repo.close()
    return folder / 'portfolio.sqlite'


def _restore_prepared_impl(db, prepared_folder, data_folder):
    prepared_folder, data_folder = Path(prepared_folder), Path(data_folder)
    candidate = prepared_folder / 'portfolio.sqlite'; inspect_database(candidate)
    checkpoint = backup_database(db, data_folder / 'backups', 'before-restore', label='Vor Wiederherstellung')
    # File replacements are staged; failure restores the database and previous files.
    changes = {}
    for name in ('portfolio_settings.json', 'etf_cache.json'):
        source = prepared_folder / 'settings' / name
        if source.exists():
            json.loads(source.read_text(encoding='utf-8')); changes[data_folder / name] = source
    for subdir in ('banking', 'sources'):
        if (prepared_folder / subdir).exists():
            for source in (prepared_folder / subdir).rglob('*'):
                if source.is_file(): changes[data_folder / ('restored-sources' if subdir == 'sources' else subdir) / source.relative_to(prepared_folder / subdir)] = source
    if (prepared_folder / 'manifest.json').is_file(): changes[data_folder / 'restored-sources/manifest.json'] = prepared_folder / 'manifest.json'
    rollback = tempfile.TemporaryDirectory(dir=data_folder)
    previous = {}
    for i, path in enumerate(changes):
        if path.exists():
            saved = Path(rollback.name) / str(i); shutil.copy2(path, saved); previous[path] = saved
        else: previous[path] = None
    old_revision = db.execute('SELECT value FROM v09_revision WHERE id=1').fetchone()[0]
    def replace(path, source):
        path.parent.mkdir(parents=True, exist_ok=True)
        # Keep the staging name short. A package source can already be nested
        # below a SHA-256 directory, and an adjacent suffix may exceed the
        # traditional Windows path limit even though the target itself works.
        handle, temporary_name = tempfile.mkstemp(prefix='.restore-', suffix='.restore-tmp', dir=data_folder)
        os.close(handle)
        temp = Path(temporary_name)
        try:
            with source.open('rb') as incoming, temp.open('wb') as stream:
                shutil.copyfileobj(incoming, stream, 1024 * 1024); stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, path)
        finally: temp.unlink(missing_ok=True)
    try:
        with closing(sqlite3.connect(candidate)) as src: src.backup(db)
        for path, content in changes.items(): replace(path, content)
        with db:
            db.execute("INSERT INTO change_log(entity,operation,new_data) VALUES('database','RESTORE',?)", (json.dumps({'checkpoint': str(checkpoint)}),))
            db.execute('UPDATE v09_revision SET value=max(value,?)+1 WHERE id=1', (old_revision,))
        return checkpoint
    except Exception:
        with closing(sqlite3.connect(checkpoint)) as src: src.backup(db)
        for path, content in previous.items():
            if content is None: path.unlink(missing_ok=True)
            else: replace(path, content)
        raise
    finally: rollback.cleanup()


def restore_prepared(db,prepared_folder,data_folder):
    """Persist rollback data before any live write; startup can finish recovery."""
    import uuid
    root=Path(data_folder).resolve(); stage=root/'restore-jobs'/uuid.uuid4().hex; stage.mkdir(parents=True)
    rollback_db=stage/'rollback.sqlite'
    with closing(sqlite3.connect(rollback_db)) as target: db.backup(target)
    changes=[]; prepared=Path(prepared_folder)
    for category,target_category in [('settings',''),('banking','banking'),('sources','restored-sources')]:
        for source in (prepared/category).rglob('*') if (prepared/category).exists() else []:
            if not source.is_file(): continue
            relative=Path(target_category)/source.relative_to(prepared/category)
            if category=='settings' and relative.name not in ('portfolio_settings.json','etf_cache.json'): continue
            changes.append(relative)
    if (prepared/'manifest.json').exists(): changes.append(Path('restored-sources/manifest.json'))
    records=[]
    for i,relative in enumerate(changes):
        target=(root/relative).resolve()
        if not target.is_relative_to(root): raise ValueError('Wiederherstellungspfad außerhalb des Datenordners.')
        existed=target.exists()
        if existed: shutil.copy2(target,stage/str(i))
        records.append(dict(target=relative.as_posix(),previous=str(i) if existed else None))
    journal=dict(status='pending',files=records,created=datetime.now(timezone.utc).isoformat())
    atomic_json(stage/'journal.json',journal)
    try:
        result=_restore_prepared_impl(db,prepared,root)
        journal['status']='complete'; atomic_json(stage/'journal.json',journal)
        return result
    except Exception:
        recover_pending(root,db)
        raise


def recover_pending(data_folder,db=None):
    root=Path(data_folder).resolve(); recovered=[]
    for journal_path in (root/'restore-jobs').glob('*/journal.json'):
        journal=read_json(journal_path)
        if journal.get('status')!='pending': continue
        stage=journal_path.parent.resolve()
        if stage.parent!=(root/'restore-jobs').resolve(): raise ValueError('Ungültiger Wiederherstellungsauftrag.')
        inspect_database(stage/'rollback.sqlite')
        # Validate the complete file plan before changing either database or files.
        files=[]
        for record in journal['files']:
            target=(root/record['target']).resolve()
            if not target.is_relative_to(root) or target==root or target.is_dir(): raise ValueError('Ungültiger Zielpfad im Wiederherstellungsauftrag.')
            prior=None
            if record['previous'] is not None:
                prior=(stage/record['previous']).resolve()
                if prior.parent!=stage or not prior.is_file(): raise ValueError('Ungültiger oder fehlender Rücksetzungspfad.')
            files.append((target,prior))
        target_db=db if db is not None else sqlite3.connect(root/'portfolio.sqlite')
        try:
            with closing(sqlite3.connect(stage/'rollback.sqlite')) as source: source.backup(target_db)
        finally:
            if db is None: target_db.close()
        for target,prior in files:
            if prior is None: target.unlink(missing_ok=True)
            else:
                target.parent.mkdir(parents=True,exist_ok=True); temporary=target.with_name(target.name+'.recover-tmp')
                shutil.copy2(prior,temporary); os.replace(temporary,target)
        journal['status']='rolled-back'; atomic_json(journal_path,journal); recovered.append(stage.name)
    return recovered


def content_diff(current,candidate,settings_folder=None,candidate_folder=None,limit=300):
    result=[]
    with closing(sqlite3.connect(Path(current).resolve().as_uri()+'?mode=ro',uri=True)) as a, closing(sqlite3.connect(Path(candidate).resolve().as_uri()+'?mode=ro',uri=True)) as b:
        for table in ('accounts','depot_accounts','imports','import_account_links','import_account_rules',
                      'snapshots','snapshot_exclusions','balances','transactions','bank_documents','import_model_records','coverage',
                      'manual_balances','security_classifications','cost_corrections','transaction_classifications',
                      'transaction_edits','transaction_exclusions','transaction_duplicate_reviews',
                      'corporate_actions','historical_fx','transfer_pairs','fee_links','transaction_supersessions',
                      'recurring_rules','saved_views','csv_profiles','account_tax_years'):
            if not a.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone() or not b.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone(): continue
            columns=[r[1] for r in a.execute(f'PRAGMA table_info({table})')]
            pks=[r[1] for r in a.execute(f'PRAGMA table_info({table})') if r[5]] or columns
            def display(value):
                if isinstance(value,bytes): return {'bytes':len(value),'sha256':hashlib.sha256(value).hexdigest()}
                return value
            def rows(db):
                return {tuple(row[columns.index(k)] for k in pks):dict(zip(columns,map(display,row))) for row in db.execute(f'SELECT * FROM {table}')}
            old,new=rows(a),rows(b)
            for key in sorted(old.keys()|new.keys(),key=str):
                if old.get(key)!=new.get(key): result.append([table,str(key),'Neu' if key not in old else 'Entfernt' if key not in new else 'Geändert',json.dumps(old.get(key),ensure_ascii=False),json.dumps(new.get(key),ensure_ascii=False)])
    if settings_folder and candidate_folder:
        for name in ('portfolio_settings.json','etf_cache.json'):
            source=Path(candidate_folder)/'settings'/name
            if not source.exists(): continue
            old=read_json(Path(settings_folder)/name); new=read_json(source)
            for key in sorted(old.keys()|new.keys()):
                if old.get(key)!=new.get(key): result.append([name,key,'Geändert',json.dumps(old.get(key),ensure_ascii=False),json.dumps(new.get(key),ensure_ascii=False)])
    return dict(total=len(result),rows=result[:limit],limited=len(result)>limit)


def session_records(data_folder):
    out=[]; root=Path(data_folder)/'sessions'
    for folder in root.iterdir() if root.exists() else []:
        if not folder.is_dir() or folder.is_symlink(): continue
        status='Abgeschlossen' if (folder/'completed.json').exists() else 'Verworfen' if (folder/'discarded.json').exists() else 'Fortsetzbar' if (folder/'session.json').exists() else 'Unvollständig'
        files=[p for p in folder.rglob('*') if p.is_file() and not p.is_symlink()]
        out.append(dict(path=str(folder),name=folder.name,status=status,bytes=sum(p.stat().st_size for p in files),modified=max((p.stat().st_mtime for p in files),default=folder.stat().st_mtime)))
    return sorted(out,key=lambda r:r['modified'],reverse=True)


def remove_session(data_folder,session_folder):
    root=(Path(data_folder)/'sessions').resolve(); folder=Path(session_folder)
    if folder.is_symlink() or folder.resolve().parent!=root or folder.resolve()==root: raise ValueError('Nur eine direkte Importsitzung kann bereinigt werden.')
    if not ((folder/'completed.json').exists() or (folder/'discarded.json').exists()): raise ValueError('Fortsetzbare und unvollständige Sitzungen bleiben erhalten. Zuerst ausdrücklich verwerfen.')
    shutil.rmtree(folder.resolve())


def verification_status(data_folder):
    root=Path(data_folder); records=backup_records(root/'backups'); checked=read_json(root/'backup-verification.json')
    return dict(last_backup=max((r.get('created','') for r in records),default='Keine'),last_verification=checked.get('checked','Noch nicht geprüft'),free_bytes=shutil.disk_usage(root).free,verification=checked.get('result','Unbekannt'))


def test_restore(path):
    with tempfile.TemporaryDirectory() as folder:
        candidate=prepare_restore(path,folder); counts=inspect_database(candidate)
        from .repository_v09 import RepositoryV09
        repo=RepositoryV09(candidate,backups=False)
        try: repo.holdings(); repo.transactions(); repo.wealth_summary()
        finally: repo.close()
        return counts
