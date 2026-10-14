"""One snapshot per import session; reviewed revisions commit atomically."""
import csv
import json
import sqlite3
import uuid
from collections import defaultdict
from contextlib import closing, contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from portfolio_v5.models import (ImportBatch, Snapshot, Position, Balance, Transaction, BankTransaction,
    BankDocument, TaxItem, FeeItem, SecurityInfo, AccountInfo, AccountStatement, TaxEvent,
    CostItem, CostReport, CorporateEvent, digest)
from portfolio_v5.accounts import account_key
from .repository_v09 import RepositoryV09, reference
from .persistence import atomic_json
from .storage_v09 import file_hash, backup_database


def report_phase(job, text):
    signal = getattr(job, 'phase', None)
    if signal is not None:
        signal.emit(text)


@contextmanager
def transaction(repo, commit=False):
    original = repo.store.db
    original.execute('BEGIN IMMEDIATE' if commit else 'BEGIN')
    class Nested:
        def __getattr__(self,name): return getattr(original,name)
        def __enter__(self): original.execute('SAVEPOINT import08'); return self
        def __exit__(self,kind,value,trace):
            if kind: original.execute('ROLLBACK TO import08')
            original.execute('RELEASE import08')
    repo.store.db = Nested()
    try:
        yield
        original.commit() if commit else original.rollback()
    except Exception:
        original.rollback(); raise
    finally:
        repo.store.db = original
        repo.store._read_revision = None
        repo._v8_cache_revision = None


def decode_batch(payload):
    # Avoid deepcopy - construct new objects directly from payload data
    d = {k: v for k, v in payload.items() if k not in ('snapshots', 'balances', 'transactions', 'documents', 'securities', 'accounts', 'statements', 'tax_events', 'cost_reports', 'events')}
    d['snapshots'] = [Snapshot(**{**s,'positions':[Position(**p) for p in s['positions']]}) for s in payload['snapshots']]
    d['balances'] = [Balance(**b) for b in payload['balances']]
    bank_fields = {'purpose', 'counterparty', 'bank_reference', 'operation', 'booking_text',
                   'counterparty_iban', 'counterparty_bic', 'raw_text', 'affects_cash'}
    transactions = []
    for tx in payload['transactions']:
        tx_copy = dict(tx)  # shallow copy is sufficient
        tx_copy['tax_items'] = [TaxItem(**item) if isinstance(item, dict) else item for item in tx_copy.get('tax_items', [])]
        tx_copy['fee_items'] = [FeeItem(**item) if isinstance(item, dict) else item for item in tx_copy.get('fee_items', [])]
        transactions.append((BankTransaction if bank_fields & tx_copy.keys() else Transaction)(**tx_copy))
    d['transactions'] = transactions
    d['documents'] = [BankDocument(**b) for b in payload.get('documents',[])]
    d['securities'] = [SecurityInfo(**row) for row in payload.get('securities', [])]
    d['accounts'] = [AccountInfo(**row) for row in payload.get('accounts', [])]
    d['statements'] = [AccountStatement(**row) for row in payload.get('statements', [])]
    d['tax_events'] = [TaxEvent(**row) for row in payload.get('tax_events', [])]
    d['cost_reports'] = [CostReport(**{**row, 'items': [CostItem(**item) for item in row.get('items', [])]})
                         for row in payload.get('cost_reports', [])]
    d['events'] = [CorporateEvent(**row) for row in payload.get('events', [])]
    return ImportBatch(**d)


class ImportSession:
    def __init__(self, path, batches, folder=None):
        self.live_path = str(path)
        self.folder = Path(folder) if folder else Path(path).parent / 'sessions' / uuid.uuid4().hex
        self.folder.mkdir(parents=True,exist_ok=True)
        self.snapshot = self.folder / 'snapshot.sqlite'
        if not self.snapshot.exists():
            with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as src:
                with closing(sqlite3.connect(self.snapshot)) as dst: src.backup(dst)
        with closing(sqlite3.connect(self.snapshot)) as db:
            self.revision = db.execute('SELECT value FROM v09_revision WHERE id=1').fetchone()[0]
        self.batches = batches
        self.decisions = {}
        self.sources = {b.path:file_hash(b.path) for b in batches if Path(b.path).is_file()}

    def save(self, batches=None, decisions=None):
        if batches is not None: self.batches = batches
        if decisions is not None: self.decisions = decisions
        atomic_json(self.folder/'session.json',dict(format=1,revision=self.revision,sources=self.sources,
            batches=[asdict(b) for b in self.batches],decisions=self.decisions))
        return self.folder/'session.json'

    @classmethod
    def resume(cls,path,session_file):
        payload = json.loads(Path(session_file).read_text(encoding='utf-8'))
        if payload.get('format') != 1: raise ValueError('Unbekanntes Sitzungsformat.')
        folder = Path(session_file).parent
        if not (folder/'snapshot.sqlite').exists(): raise ValueError('Datenkopie der Sitzung fehlt.')
        result = cls(path,[decode_batch(b) for b in payload['batches']],folder)
        if result.revision != payload['revision']: raise ValueError('Sitzung und Datenkopie passen nicht zusammen.')
        result.decisions = payload['decisions']; result.sources = payload['sources']
        return result

    def summaries(self,job):
        repo = RepositoryV09(self.snapshot,backups=False)
        try:
            result=[]
            for i,b in enumerate(self.batches):
                if job.isInterruptionRequested(): raise ValueError('Abgebrochen.')
                result.append(repo.preview_summary(b)); job.progress.emit(i+1,len(self.batches))
            return result
        finally: repo.close()

    def conflicts(self,batches):
        token=digest([asdict(b) for b in batches])
        if getattr(self,'_conflict_token',None)==token: return deepcopy(self._conflict_cache)
        repo = RepositoryV09(self.snapshot,backups=False)
        try:
            index=defaultdict(list); ids=defaultdict(list); signatures={}; security_last={}
            def add(t):
                amount_key=(account_key(t['account']),t['date'],t['currency'],Decimal(t['amount']))
                id_key=(account_key(t['depot']),t['external_id'])
                index[amount_key].append(t); ids[id_key].append(t)
                security_last[(amount_key,t.get('security') or '')]=t
                for key in (('amount',amount_key),('id',id_key)):
                    signatures[key]=digest([signatures.get(key,''),reference(t),t])
            for t in repo.transactions():
                add(t)
            names = {r['account_key']:r['name'] for r in repo.account_records()}
            result=[]; self._candidate_buckets={}
            for i,b in enumerate(batches):
                if len({(account_key(t.account),t.external_id) for t in b.transactions})!=len(b.transactions):
                    raise ValueError('Mehrfach verwendete Buchungskennung innerhalb einer Datei: '+b.path+'. Bitte Quelldaten korrigieren.')
                for j,t in enumerate(b.transactions):
                    target=b.account_assignments.get(account_key(t.account),account_key(t.account)); effective=names.get(target,t.account)
                    amount_key=(account_key(effective),t.date,t.currency,Decimal(t.amount)); id_key=(account_key(t.account),t.external_id)
                    by_amount,by_id=index[amount_key],ids[id_key]
                    old=by_id[-1] if by_id else (security_last.get((amount_key,t.security)) or security_last.get((amount_key,''))) if t.security else by_amount[-1] if by_amount else None
                    if old:
                        ref=reference(old); key=digest([b.path,t.account,t.external_id,i,j])
                        result.append(dict(key=key,batch=i,new=asdict(t),old=old,old_ref=ref,source=b.path,id_match=bool(by_id),
                            candidate_count=len(by_amount)+len(by_id),candidate_signature=digest([signatures.get(('amount',amount_key)),signatures.get(('id',id_key))])))
                        # Bucket lists are shared, bounded by the reviewed prefix. No quadratic pair list.
                        self._candidate_buckets[key]=(by_amount,len(by_amount),by_id,len(by_id),asdict(t))
                    # Also detect overlaps between incoming files (keep/skip only).
                    staged={**asdict(t),'account':effective,'depot':t.account,'source':b.path,'import_id':-i-1}
                    add(staged)
            self._conflict_token,self._conflict_cache=token,result
            return deepcopy(result)
        finally: repo.close()

    def candidates(self,key):
        a,na,b,nb,new=self._candidate_buckets[key]; seen=set(); rows=[]
        from itertools import chain,islice
        for old in chain(islice(a,na),islice(b,nb)):
            ref=reference(old)
            if ref in seen: continue
            seen.add(ref)
            if old.get('security') and new.get('security') and old['security']!=new['security'] and old['external_id']!=new['external_id']: continue
            rows.append(old)
        return rows

    def resolve(self,batches,decisions):
        selected=deepcopy(batches); replacements=[]; skip=set(); rename=set()
        conflicts=self.conflicts(batches)
        groups=defaultdict(list)
        for c in conflicts: groups[(c['batch'],c['new']['account'],c['new']['external_id'])].append(c)
        replaced=set()
        for group in groups.values():
            choices=[decisions.get(c['key'],{}).get('action') for c in group]
            if 'skip' in choices and any(x!='skip' for x in choices): raise ValueError('Widersprüchliche Entscheidung: eine neue Buchung kann nicht zugleich übersprungen und übernommen werden.')
            if choices.count('replace')>1: raise ValueError('Eine neue Buchung darf höchstens eine alte Buchung ersetzen.')
        for conflict in conflicts:
            decision=decisions.get(conflict['key'],{})
            action=decision.get('action')
            if action not in ('keep','skip','replace'): raise ValueError('Alle Buchungsüberschneidungen ausdrücklich entscheiden.')
            key=(conflict['batch'],conflict['new']['account'],conflict['new']['external_id'])
            if action=='skip': skip.add(key)
            elif action=='replace':
                chosen=decision.get('old_ref')
                if conflict['candidate_count']>1 and not chosen and len(self.candidates(conflict['key']))>1: raise ValueError('Bei mehreren Treffern den zu ersetzenden Beleg ausdrücklich auswählen.')
                if chosen:
                    matches=[t for t in self.candidates(conflict['key']) if reference(t)==chosen]
                    if not matches: raise ValueError('Gewählter Ersatzbeleg passt nicht mehr zur Buchung.')
                    conflict={**conflict,'old':matches[0],'old_ref':chosen}
                if conflict['old']['import_id'] < 0: raise ValueError('Zwischen neuen Dateien nur Behalten oder Überspringen wählen.')
                if not decision.get('reason','').strip(): raise ValueError('Ersetzung benötigt eine Begründung.')
                if conflict['old_ref'] in replaced: raise ValueError('Eine alte Buchung kann nicht mehrfach ersetzt werden.')
                replaced.add(conflict['old_ref'])
                replacements.append((key,conflict['old'],decision['reason']))
                rename.add(key)
            elif action == 'keep':
                # A kept conflict must still remain distinguishable from the current record.
                # Otherwise same-account/date/amount duplicates can later be merged or hidden.
                same_signature = (
                    conflict.get('id_match')
                    or conflict['old']['external_id'] == conflict['new']['external_id']
                    or (
                        conflict['old'].get('account') == conflict['new'].get('account')
                        and conflict['old'].get('date') == conflict['new'].get('date')
                        and conflict['old'].get('amount') == conflict['new'].get('amount')
                        and conflict['old'].get('currency') == conflict['new'].get('currency')
                    )
                )
                if same_signature:
                    rename.add(key)
        renamed={}
        for i,b in enumerate(selected):
            txs=[]
            for t in b.transactions:
                key=(i,t.account,t.external_id)
                if key in skip: continue
                if key in rename:
                    t.external_id += ':v09:'+digest([self.folder.name,i,t.external_id])[:16]
                renamed[key]=t.external_id; txs.append(t)
            b.transactions=txs
        return selected,[(key,old,reason,renamed[key]) for key,old,reason in replacements if key not in skip]

    def rebase(self):
        # Retain a decision only when both the incoming payload and the old record match.
        for path,expected in self.sources.items():
            if not Path(path).is_file() or file_hash(path)!=expected: raise ValueError('Quelldatei verändert. Datei neu einlesen statt Entscheidungen zu übernehmen.')
        old={c['key']:c for c in self.conflicts(self.batches)}
        fresh=ImportSession(self.live_path,self.batches)
        decisions={}
        for c in fresh.conflicts(fresh.batches):
            prior=old.get(c['key'])
            if prior and prior['new']==c['new'] and prior.get('candidate_signature')==c.get('candidate_signature') and c['key'] in self.decisions:
                decisions[c['key']]=self.decisions[c['key']]
        fresh.decisions=decisions; fresh.save()
        return fresh

    def summary(self,batches,decisions,results):
        selected,replacements=self.resolve(batches,decisions)
        skipped=sum(len(b.transactions) for b in batches)-sum(len(b.transactions) for b in selected)
        return dict(files=len(results),imported=sum(r['status']=='imported' for r in results),unchanged=sum(r['status']=='duplicate' for r in results),
                    skipped_bookings=skipped,replaced_bookings=len(replacements),selected_bookings=sum(len(b.transactions) for b in selected),errors=sum(r['status']=='error' for r in results))

    def apply(self,repo,job,resolved):
        report_phase(job, 'Buchungen und Belege übernehmen …')
        selected,replacements=resolved; results=[]
        # Only load transaction references if replacements are planned
        if replacements:
            active = {reference(t) for t in repo.transactions()}
        else:
            active = set()
        for i,b in enumerate(selected):
            if job.isInterruptionRequested(): raise ValueError('Import abgebrochen; keine Änderungen gespeichert.')
            if b.errors: raise ValueError('; '.join(b.errors))
            result=repo.store.import_batch(b); result['path']=b.path; results.append(result)
            if result['status']=='error': raise ValueError('; '.join(result.get('errors',[])))
            for key,old,reason,new_id in replacements:
                if key[0]!=i: continue
                if reference(old) not in active: raise ValueError('Zu ersetzende Buchung ist nicht mehr aktiv.')
                if result['status']!='imported': raise ValueError('Eine doppelte Datei kann keine Buchung ersetzen. Auswahl prüfen.')
                if not repo.db.execute('SELECT 1 FROM transactions WHERE import_id=? AND external_id=? AND account=?',(result['id'],new_id,key[1])).fetchone(): raise ValueError('Ersatzbuchung wurde nicht gespeichert.')
                repo.db.execute('INSERT INTO transaction_supersessions(old_import,old_account,old_id,new_import,new_account,new_id,reason) VALUES(?,?,?,?,?,?,?)',
                    (old['import_id'],old['depot'],old['external_id'],result['id'],key[1],new_id,reason))
            job.progress.emit(i+1,len(selected))
        report_phase(job, 'Wertpapier-Stammdaten abgleichen …')
        repo.sync_security_master()
        repo.remember_transaction_security_identifiers()
        return results

    def simulate(self,job,batches,decisions):
        resolved=self.resolve(batches,decisions)
        repo=RepositoryV09(self.snapshot,backups=False)
        try:
            before={(p['depot'],p['key']):p for p in repo.holdings()}
            old_balances={r['name']:r.get('balance') for r in repo.account_overview()}
            dates=sorted({s.effective_date for b in resolved[0] for s in b.snapshots})
            # Cache holdings() results per date to avoid redundant queries
            _holdings_cache = {}
            def holdings_for(day):
                if day not in _holdings_cache:
                    _holdings_cache[day] = {(p['depot'],p['key']):p for p in repo.holdings(day)}
                return _holdings_cache[day]
            historical = {day: holdings_for(day) for day in dates}
            with transaction(repo):
                results=self.apply(repo,job,resolved)
                after={(p['depot'],p['key']):p for p in repo.holdings()}
                changes=[]
                for key in sorted(before.keys() | after.keys()):
                    a,b=before.get(key,{}),after.get(key,{})
                    if (a.get('quantity'),a.get('value'))!=(b.get('quantity'),b.get('value')):
                        changes.append([key[0],(b or a)['name'],a.get('quantity'),b.get('quantity'),a.get('value'),b.get('value')])
                dated=[]
                for day in dates:
                    current=holdings_for(day)
                    for key in sorted(historical[day].keys()|current.keys()):
                        a,b=historical[day].get(key,{}),current.get(key,{})
                        if (a.get('quantity'),a.get('value'))!=(b.get('quantity'),b.get('value')):
                            dated.append([day,key[0],(b or a)['name'],a.get('quantity'),b.get('quantity'),a.get('value'),b.get('value')])
                balances=[[r['name'],old_balances.get(r['name']),r.get('balance')] for r in repo.account_overview() if old_balances.get(r['name'])!=r.get('balance')]
                txs=[[b.path,t.date,t.account,t.kind,t.security,t.quantity,t.amount,t.currency] for b in resolved[0] for t in b.transactions]
                return dict(results=results,changes=changes,transactions=len(txs),transaction_rows=txs,balances=balances,dated=dated)
        finally: repo.close()

    def commit(self,job,batches,decisions):
        report_phase(job, 'Importentscheidungen prüfen …')
        resolved=self.resolve(batches,decisions)
        report_phase(job, 'Datenbank vorbereiten …')
        repo=RepositoryV09(self.live_path,backups=False)
        try:
            report_phase(job, 'Sicherung erstellen und prüfen …')
            backup_database(repo.db,Path(self.live_path).parent/'backups','before-import')
            with transaction(repo,commit=True):
                report_phase(job, 'Quelldateien auf Änderungen prüfen …')
                if repo.revision()!=self.revision: raise ValueError('Daten wurden seit der Vorschau geändert. Neue Importsitzung starten.')
                for source,expected in self.sources.items():
                    if not Path(source).is_file() or file_hash(source)!=expected: raise ValueError('Quelldatei seit der Vorschau geändert oder entfernt: '+source)
                results=self.apply(repo,job,resolved)
                if job.isInterruptionRequested(): raise ValueError('Import abgebrochen; keine Änderungen gespeichert.')
                report_phase(job, 'Änderungen gemeinsam speichern …')
            try: atomic_json(self.folder/'completed.json',dict(results=results))
            except OSError:
                for result in results: result.setdefault('warnings',[]).append('Import gespeichert; Sitzungsabschlussdatei konnte nicht geschrieben werden.')
            return results
        finally: repo.close()


def parse_profile_csv(path,profile):
    """Explicit column and number conventions; never guess a transaction kind."""
    path=Path(path); mapping=profile.get('columns',{})
    delimiter=profile.get('delimiter',';'); decimal=profile.get('decimal',','); thousands=profile.get('thousands','.')
    if decimal==thousands or len(delimiter)!=1: raise ValueError('Trennzeichen prüfen.')
    def num(raw):
        if not raw.strip(): return None
        raw=raw.strip().replace(thousands,'') if thousands else raw.strip()
        value=Decimal(raw.replace(decimal,'.'))
        if not value.is_finite(): raise ValueError('Nicht endliche Zahl.')
        return str(value)
    batch=ImportBatch(str(path),file_hash(path))
    with path.open(encoding=profile.get('encoding','utf-8-sig'),newline='') as source:
        rows=csv.DictReader(source,delimiter=delimiter)
        required=('account','date','amount')
        if any(not mapping.get(k) or mapping[k] not in (rows.fieldnames or []) for k in required): raise ValueError('Kontospalte, Datum und Betrag zuordnen.')
        for n,row in enumerate(rows,2):
            def get(k,default=''): return (row.get(mapping.get(k,'')) or default).strip()
            try:
                day=datetime.strptime(get('date'),profile.get('date_format','%d.%m.%Y')).date().isoformat()
                amount=num(get('amount'))
                if amount is None: raise ValueError('Betrag fehlt')
                if profile.get('invert_sign'): amount=str(-Decimal(amount))
                kind=get('kind','BANK_BOOKING').upper()
                if kind not in ('BUY','SELL','TRANSFER_IN','TRANSFER_OUT','DEPOSIT','WITHDRAWAL','DIVIDEND','INTEREST','FEE','TAX','BANK_BOOKING'): raise ValueError('Unbekannte Buchungsart '+kind)
                value_date=datetime.strptime(get('value_date'),profile.get('date_format','%d.%m.%Y')).date().isoformat() if get('value_date') else ''
                tx=BankTransaction(get('account'),get('external_id') or digest([row,n]),day,kind,amount,get('currency',profile.get('currency','EUR')).upper(),
                    security=get('security'),quantity=num(get('quantity')),fees=num(get('fees')),taxes=num(get('taxes')),row=n,
                    value_date=value_date,purpose=get('purpose'),counterparty=get('counterparty'),
                    bank_reference=get('bank_reference') or get('reference') or get('transaction_reference'),
                    document_reference=get('document_reference') or get('bank_reference') or get('reference') or get('transaction_reference'),
                    transaction_reference=get('transaction_reference') or get('bank_reference') or get('reference'),
                    withholding_tax=num(get('withholding_tax')),
                    withholding_country=get('withholding_country').upper(),
                    withholding_tax_rate=num(get('withholding_tax_rate')),
                    tax_rate=num(get('tax_rate')),
                    per_share_amount=num(get('per_share_amount')),
                    per_share_currency=get('per_share_currency').upper())
                batch.transactions.append(tx)
            except Exception as error: batch.errors.append(f'Zeile {n}: {error}')
    batch.account_names=sorted({t.account for t in batch.transactions})
    return batch
