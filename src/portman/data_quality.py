import json,re
from datetime import date
from decimal import Decimal

class DataQualityService:
    def __init__(self,repository):self.repo=repository
    def issues(self,as_of='9999-12-31',account=None):
        issues=[];positions=self.repo.current(as_of,account)
        for p in positions:
            key=p['key'];name=p['name']
            if not p.get('isin'):issues.append(('Fehler','Stammdaten',key,name,'ISIN fehlt'))
            elif not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}\d',p['isin']):issues.append(('Fehler','Stammdaten',key,name,'ISIN ungültig'))
            if not p.get('canonical_name'):issues.append(('Hinweis','Stammdaten',key,name,'Kanonischer Anzeigename fehlt'))
            if p.get('region','Unbekannt')=='Unbekannt':issues.append(('Hinweis','Klassifikation',key,name,'Region unbekannt'))
            if p.get('cap_size','Unbekannt')=='Unbekannt' and p.get('asset_type')=='Aktie':issues.append(('Hinweis','Klassifikation',key,name,'Unternehmensgröße unbekannt'))
            if p.get('cost') is None or Decimal(p.get('cost') or 0)<=0:issues.append(('Warnung','Bewertung',key,name,'Einstandswert fehlt oder ist null'))
        latest={}
        for snap in self.repo.snapshots(account):
            if snap['effective_date'] <= as_of:
                depot = snap.get('depot', snap['account'])
                latest[depot] = max(latest.get(depot, ''), snap['effective_date'])
        today=date.today() if as_of == '9999-12-31' else date.fromisoformat(as_of)
        for acct,d in latest.items():
            age=(today-date.fromisoformat(d)).days
            if age>45:issues.append(('Warnung','Aktualität',acct,acct,f'Letzter Depotstand {d} ist {age} Tage alt'))
        for entry in self.repo.imports():
            if not entry['active']:continue
            report=json.loads(entry['report']);warnings=report.get('warnings',[]);errors=report.get('errors',[])
            if errors:issues.append(('Fehler','Import',str(entry['id']),entry['path'],f'{len(errors)} Importfehler'))
            elif warnings:issues.append(('Hinweis','Import',str(entry['id']),entry['path'],f'{len(warnings)} Prüfhinweise im Importprotokoll'))
        for excluded in self.repo.db.execute('''SELECT s.account,e.reason FROM snapshot_exclusions e
            JOIN snapshots s ON s.id=e.snapshot_id'''):
            issues.append(('Hinweis','Importkorrektur',excluded['account'],excluded['account'],excluded['reason']))
        order={'Fehler':0,'Warnung':1,'Hinweis':2}
        return sorted(issues,key=lambda x:(order[x[0]],x[1],x[3]))
