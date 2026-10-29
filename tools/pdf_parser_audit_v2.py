"""Portman PDF parser audit V2. No database access or import writes.

Uses the same parse_pdf as the GUI. Cache reuse is explicit and audited.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
import platform
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from pdf_parser_audit_v1 import pdf_paths, digest, parse_one

INFO = (r'PDF-Plugin:', r'Käufe: Nominale und Kurswert', r'OCR verwendet; Buchungen bitte',
        r'Textergänzung nur aus eingebettetem Text')
RULES = [
 ('BUY_POSITIVE','WARNING',r'Kauf mit positivem Betrag|Kauf.+Abfluss muss negativ'),
 ('NET_GROSS_MISMATCH','WARNING',r'Brutto/Netto passt nicht'),
 ('QUANTITY_CONFLICT','WARNING',r'Stückzahl.*(?:widerspr|abweich|passt nicht)|widersprüchliche Stückzahlen'),
 ('OCR_FAILED','WARNING',r'OCR fehlgeschlagen|OCR hat keinen Text erkannt|geringer Sicherheit'),
 ('OCR_LAYOUT','WARNING',r'Gedrehter Text oder Layoutproblem|Tabellenspalten am Original prüfen'),
 ('CANCELLATION','WARNING',r'Stornobeleg|stornier'),
 ('MIFID_COST','WARNING',r'MiFID|Kosteninformation'),
 ('DIVIDEND_TAX','WARNING',r'Ausschüttung|Dividende|Vorabpauschale'),
]
ERROR_RULES = [
 ('CANCELLATION','Stornobeleg'), ('MIFID_COST','MiFID|Kosteninformation'),
 ('QUANTITY_CONFLICT','Stückzahl|Nominale|Menge'), ('DIVIDEND_TAX','Ausschüttung|Dividende|Steuermitteilung'),
 ('UNSUPPORTED_LAYOUT','keine unterstützte|nicht unterstützt|unbekanntes Layout'),
 ('TEXT_EXTRACTION','Textextraktion|Text nicht|nicht lesbar|OCR|extrahier'),
 ('ENCRYPTED','passwortgeschützt|verschlüsselt'),
]

def messages(row):
    findings=[]
    for err in row.get('errors',[]):
        code=next((k for k,p in ERROR_RULES if re.search(p,err,re.I)), 'PARSER_ERROR')
        findings.append({'code':code,'level':'ERROR','message':err})
    for w in row.get('warnings',[]):
        code=None; level='INFO'
        for k,lev,pat in RULES:
            if re.search(pat,w,re.I): code=k; level=lev; break
        if code is None:
            code='PLUGIN_NOTICE' if any(re.search(p,w,re.I) for p in INFO) else 'UNCLASSIFIED_WARNING'
            level='INFO' if code=='PLUGIN_NOTICE' else 'WARNING'
        findings.append({'code':code,'level':level,'message':w})
    if row.get('plugin') in ('generic.kontoauszug','') and not row.get('errors'):
        findings.append({'code':'GENERIC_FALLBACK','level':'WARNING','message':'Kein spezifischer Parser ausgewählt'})
    return findings

def enrich(row):
    row=dict(row)
    f=messages(row)
    rank={'PASS':0,'INFO':1,'WARNING':2,'ERROR':3}
    severity=max((x['level'] for x in f),key=lambda x:rank[x],default='PASS')
    row['severity']=severity
    row['findings']=f
    row['issue_codes']=sorted({x['code'] for x in f if x['level'] in ('WARNING','ERROR')})
    row['issue_fingerprint']=hashlib.sha256(json.dumps([row.get('plugin'),row.get('handler'),row['issue_codes']],sort_keys=True).encode()).hexdigest()[:16]
    return row

def signatures(plugins):
    """Hash shipped plugin code; core fingerprints collected by file to invalidate stale cache."""
    roots=[]
    for m in ('portfolio_v5.pdf_importer','portfolio_v5.pdf_plugins.registry'):
        mod=__import__(m,fromlist=['x']); roots.append(Path(mod.__file__))
    for p in plugins:
        src=getattr(p,'source_path',None)
        if src and Path(src).is_file(): roots.append(Path(src))
    # Hash parser core and all plugin helpers, so cache never masks code changes.
    from portfolio_v5 import pdf_importer
    core=Path(pdf_importer.__file__).resolve().parent
    roots += list(core.rglob('*.py'))
    for folder in [Path.cwd()/'pdf_plugins']:
        if folder.is_dir(): roots += list(folder.rglob('*.py'))+list(folder.rglob('*.toml'))
    h=hashlib.sha256()
    for p in sorted(set(x.resolve() for x in roots if x.is_file())):
        h.update(str(p).encode());h.update(digest(p).encode())
    h.update(sys.version.encode())
    return h.hexdigest()

def normalize(row):
    return enrich(row)

def full_delta(rows, prior, complete):
    if prior is None: return {'baseline_used':False,'compared':0,'resolved':[],'regressions':[],'changed':[],'new':[],'removed':[]}
    before={r['path']:normalize(r) for r in prior.get('files',[])}
    now={r['path']:r for r in rows}
    changed=[];resolved=[];regressions=[]
    levels={'PASS':0,'INFO':1,'WARNING':2,'ERROR':3}
    for path in sorted(set(now)&set(before)):
        a,b=before[path],now[path]
        old=(a['severity'],a['issue_codes'],a.get('plugin'),a.get('handler'),a.get('sha256'))
        new=(b['severity'],b['issue_codes'],b.get('plugin'),b.get('handler'),b.get('sha256'))
        if old==new: continue
        entry={'path':path,'old_severity':a['severity'],'new_severity':b['severity'],
               'old_codes':a['issue_codes'],'new_codes':b['issue_codes'],
               'content_changed':a.get('sha256')!=b.get('sha256')}
        changed.append(entry)
        if entry['content_changed']: continue
        old_codes=set(a['issue_codes']);new_codes=set(b['issue_codes'])
        if levels[b['severity']]<levels[a['severity']] or (old_codes-new_codes):resolved.append(entry)
        if levels[b['severity']]>levels[a['severity']] or (new_codes-old_codes):regressions.append(entry)
    return {'baseline_used':True,'compared':len(set(now)&set(before)),
            'resolved':resolved,'regressions':regressions,'changed':changed,
            'new':sorted(set(now)-set(before)), 'removed':sorted(set(before)-set(now)) if complete else [],
            'scope_is_complete':complete}

def report_md(result):
    s=result['summary']; d=result['comparison']; lines=[
      '# Portman – PDF-Parser-Audit V2','',
      f"- Datum (UTC): `{result['generated_at_utc']}`",f"- Quellverzeichnis: `{result['scan_root']}`",
      f"- Modus: `{result['mode']}`; OCR: `{result['ocr_enabled']}`; Parser-Fingerprint: `{result['parser_fingerprint'][:16]}`",
      f"- PDFs im Scope: **{s['total']}**; eindeutige SHA-256: **{s['unique_hashes']}**; Cache-Treffer: **{s['cached']}**",
      f"- Plugin-Ladefehler: **{len(result['plugin_load_errors'])}**; Scanfehler: **{len(result['scan_errors'])}**",'',
      '## Schweregrade','', '| Grad | PDFs |','|---|---:|',
    ]
    for k in ('ERROR','WARNING','INFO','PASS'):lines.append(f"| {k} | {s['severity'].get(k,0)} |")
    lines.extend(['','## Befunde (pro Dokument, Kategorien können mehrfach vorkommen)','', '| Kategorie | Dokumente |','|---|---:|'])
    for k,v in sorted(s['issue_codes'].items(),key=lambda x:-x[1]): lines.append(f'| `{k}` | {v} |')
    lines.extend(['','## Parser/Handler','', '| Plugin | Handler | Dateien | Fehler | Warnungen |','|---|---|---:|---:|---:|'])
    grouped=defaultdict(list)
    for row in result['files']:grouped[(row.get('plugin') or '(kein Plugin)',row.get('handler') or '-')].append(row)
    for (p,h),rs in sorted(grouped.items()):
        lines.append(f"| `{p}` | `{h}` | {len(rs)} | {sum(x['severity']=='ERROR' for x in rs)} | {sum(x['severity']=='WARNING' for x in rs)} |")
    lines.extend(['','## Vergleich mit Baseline',''])
    if not d['baseline_used']:lines.append('Keine Baseline angegeben.')
    else:
        lines.append(f"Verglichen: **{d['compared']}**, Verbesserungen: **{len(d['resolved'])}**, Regressionen: **{len(d['regressions'])}**, veränderte Befunde: **{len(d['changed'])}**, neu: **{len(d['new'])}**.")
        if not d.get('scope_is_complete'):lines.append('**Teillauf:** Nicht im Scope enthaltene PDFs gelten nicht als entfernt.')
        for label,key in [('Regressionen','regressions'),('Verbesserungen','resolved')]:
            lines.extend(['',f'### {label} (max. 100, vollständige Liste in delta.csv)',''])
            for x in d[key][:100]:lines.append(f"- `{x['path']}`: {x['old_severity']} → {x['new_severity']} ({','.join(x['old_codes'])} → {','.join(x['new_codes'])})")
    lines.extend(['','## Einzelbefunde','',
                 'Vollständig in `findings.csv` (jede Meldung einzeln), `files.csv` und `audit.json`. Der Markdownbericht enthält nur die ersten 150 ERROR/ WARNING-Dateien.',''])
    n=0
    for row in result['files']:
        if row['severity'] not in ('ERROR','WARNING'): continue
        lines.append(f"- **{row['severity']}** `{row['path']}` · `{row.get('plugin','')}/{row.get('handler','')}` · {', '.join(row['issue_codes'])}")
        n+=1
        if n>=150:break
    lines.extend(['','## Grenzen','',
      '- Klassifikationen sind regelbasierte Priorisierung, **kein** Beweis, dass Beträge fachlich korrekt oder fehlerhaft sind.',
      '- `INFO` umfasst z. B. normale Plugin-Erkennungsnachrichten; `WARNING` enthält auffällige Vorzeichen und Brutto-Netto-Werte.',
      '- Die Suite führt `parse_pdf()` aus und schreibt keinerlei Portman-Datenbankeinträge.',
      '- Optionaler Cache nutzt Dateigröße, mtime_ns, SHA-256, OCR-Modus und Parser-Fingerprint; SHA wird auch bei Cache-Treffern neu berechnet.',
      '- Für schnelle gezielte Läufe `--only-errors`, `--plugin` und `--issue-code` verwenden; mit `--compare` zu V1/V2 vergleichen.',
      '- Historische Baselines unter `test_reports` unverändert aufbewahren. Berichte nicht öffentlich teilen (Dateinamen/Belegdetails).',''])
    return '\n'.join(lines)

def write_csv(path, rows, names):
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=names,delimiter=';',extrasaction='ignore');w.writeheader()
        for row in rows:w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path(r'C:\Users\chris\Desktop\history'))
    p.add_argument('--output',type=Path,default=Path('test_reports/pdf_parser_audit/v2'))
    p.add_argument('--compare',type=Path,help='V1 or V2 audit.json baseline')
    p.add_argument('--cache',type=Path,help='Reuse audit rows if file and parser versions unchanged')
    p.add_argument('--allow-ocr',action='store_true')
    p.add_argument('--only-errors',action='store_true',help='Restrict scope to errors in --compare baseline')
    p.add_argument('--plugin',help='Restrict scope to parser named in --compare baseline')
    p.add_argument('--issue-code',help='Restrict scope to issue code in --compare baseline')
    p.add_argument('--limit',type=int)
    args=p.parse_args(argv)
    root=args.root.resolve();out=args.output.resolve()
    if not root.is_dir():p.error(f'Source missing: {root}')
    if out==root or root in out.parents:p.error('Output must be outside scanned root')
    if args.cache and args.cache.resolve()==out/'audit.json':p.error('Cache cannot point to current output')
    if args.compare and args.compare.resolve()==out/'audit.json':p.error('Baseline cannot point to current output')
    from portfolio_v5.pdf_plugins.registry import discover_plugins
    plugins,load_errors=discover_plugins();fingerprint=signatures(plugins)
    inventory=[{'id':str(x.plugin_id),'bank':str(x.bank_name),'version':str(x.version),'source':str(getattr(x,'source_path','entry-point'))} for x in plugins]
    previous=json.loads(args.compare.read_text(encoding='utf-8')) if args.compare else None
    cached=json.loads(args.cache.read_text(encoding='utf-8')) if args.cache else None
    cache_ok=bool(cached and cached.get('parser_fingerprint')==fingerprint and cached.get('ocr_enabled')==args.allow_ocr and cached.get('scan_root')==str(root))
    cachemap={r['path']:r for r in cached['files']} if cache_ok else {}
    reference={r['path']:enrich(r) for r in previous.get('files',[])} if previous else {}
    if (args.only_errors or args.plugin or args.issue_code) and not previous:p.error('Targeted mode requires --compare baseline')
    paths,scan_errors=pdf_paths(root)
    complete=not (args.only_errors or args.plugin or args.issue_code or args.limit is not None)
    if not complete:
        def chosen(path):
            r=reference.get(path.relative_to(root).as_posix())
            return bool(r and (not args.only_errors or r['severity']=='ERROR') and
                (not args.plugin or r.get('plugin')==args.plugin) and
                (not args.issue_code or args.issue_code in r['issue_codes']))
        if args.only_errors or args.plugin or args.issue_code:paths=[x for x in paths if chosen(x)]
    if args.limit is not None:paths=paths[:args.limit]
    hashes={};rows=[];count_cached=0;start=time.perf_counter()
    for i,path in enumerate(paths,1):
        relative=path.relative_to(root).as_posix()
        stat=path.stat();hashval=digest(path)
        cachedrow=cachemap.get(relative)
        if cachedrow and cachedrow.get('sha256')==hashval and cachedrow.get('bytes')==stat.st_size:
            r=dict(cachedrow);count_cached+=1;r['cached']=True
        else:
            r=parse_one(path,root,args.allow_ocr,plugins,load_errors);r['cached']=False
        r['mtime_ns']=stat.st_mtime_ns
        r['duplicate_of']=hashes.get(hashval)
        hashes.setdefault(hashval,relative)
        r=enrich(r);rows.append(r)
        if i%100==0 or i==len(paths):print(f'{i}/{len(paths)} | Fehler {sum(x["severity"]=="ERROR" for x in rows)} | Cache {count_cached}',flush=True)
    severity=Counter(r['severity'] for r in rows)
    codes=Counter(code for r in rows for code in r['issue_codes'])
    summary={'total':len(rows),'unique_hashes':len(hashes),'cached':count_cached,
             'severity':dict(severity),'issue_codes':dict(codes),
             'plugin_counts':dict(Counter(r.get('plugin') or '(kein Plugin)' for r in rows)),
             'seconds':round(time.perf_counter()-start,2)}
    result={'schema_version':2,'generated_at_utc':datetime.now(timezone.utc).isoformat(),
            'scan_root':str(root),'mode':'full' if complete else 'targeted',
            'ocr_enabled':args.allow_ocr,'parser_fingerprint':fingerprint,
            'runtime':{'python':sys.version.split()[0],'platform':platform.platform()},
            'plugins':inventory,'plugin_load_errors':load_errors,'scan_errors':scan_errors,
            'summary':summary,'comparison':full_delta(rows,previous,complete),'files':rows}
    out.mkdir(parents=True,exist_ok=True)
    (out/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'report.md').write_text(report_md(result),encoding='utf-8')
    write_csv(out/'files.csv',rows,['path','sha256','status','severity','plugin','handler','document_type','confidence','transactions','snapshots','documents','tax_events','issue_codes','duration_s','cached','duplicate_of'])
    findings=[{'path':r['path'],'sha256':r['sha256'],'plugin':r.get('plugin'),'handler':r.get('handler'),**x} for r in rows for x in r['findings']]
    write_csv(out/'findings.csv',findings,['path','sha256','plugin','handler','code','level','message'])
    delta=[{'kind':k,'path':x['path'],'old_severity':x['old_severity'],'new_severity':x['new_severity'],
            'old_codes':x['old_codes'],'new_codes':x['new_codes'],'content_changed':x['content_changed']}
           for k in ('regressions','resolved','changed') for x in result['comparison'][k]]
    write_csv(out/'delta.csv',delta,['kind','path','old_severity','new_severity','old_codes','new_codes','content_changed'])
    print(f'Bericht: {out / "report.md"}; Fehler: {severity["ERROR"]}; Warnungen: {severity["WARNING"]}')
    return 1 if severity['ERROR'] or load_errors or scan_errors else 0

if __name__=='__main__':raise SystemExit(main())
