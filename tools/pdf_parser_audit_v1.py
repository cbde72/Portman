"""Read-only, repeatable Portman PDF parser audit. Run from repository root.

This script never writes to scanned source folders and never opens a portfolio DB.
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
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def as_text(x):
    if x is None:
        return ""
    return str(x)


def pdf_paths(root: Path):
    paths = []
    errors = []
    for dirname, _, filenames in os.walk(root, followlinks=False, onerror=lambda e: errors.append(str(e))):
        for name in filenames:
            if name.lower().endswith('.pdf'):
                paths.append(Path(dirname) / name)
    return sorted(paths, key=lambda p: str(p).casefold()), errors


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def scrub(message):
    # Avoid exposing account/IBAN data in issue-sharing by default.
    t = as_text(message)
    t = re.sub(r'\bDE(?:[\s-]*\d){20}\b', '[IBAN]', t, flags=re.I)
    return t[:2000]


def parse_one(path, root, allow_ocr, plugins, plugin_errors):
    from portfolio_v5.pdf_importer import parse_pdf
    start = time.perf_counter()
    row = {'path': path.relative_to(root).as_posix(), 'sha256': '', 'bytes': None,
           'status': 'error', 'plugin': '', 'handler': '', 'document_type': '',
           'confidence': None, 'duration_s': None, 'transactions': 0, 'snapshots': 0,
           'documents': 0, 'tax_events': 0, 'warnings': [], 'errors': [],
           'ocr_indications': 0, 'duplicate_of': None}
    try:
        row['bytes'] = path.stat().st_size
        row['sha256'] = digest(path)
        # Production parsing entry point, no DB commits. Plugin catalog fixed per run.
        batch = parse_pdf(path, allow_ocr=allow_ocr, plugin_catalog=(plugins, list(plugin_errors)))
        row.update(plugin=as_text(getattr(batch, 'plugin_id', '')),
                   handler=as_text(getattr(batch, 'plugin_handler', '')),
                   document_type=as_text(getattr(batch, 'document_type', '')),
                   confidence=getattr(batch, 'detection_confidence', None),
                   transactions=len(getattr(batch, 'transactions', ()) or ()),
                   snapshots=len(getattr(batch, 'snapshots', ()) or ()),
                   documents=len(getattr(batch, 'documents', ()) or ()),
                   tax_events=len(getattr(batch, 'tax_events', ()) or ()))
        row['warnings'] = [scrub(x) for x in getattr(batch, 'warnings', ()) or ()]
        row['errors'] = [scrub(x) for x in getattr(batch, 'errors', ()) or ()]
        row['ocr_indications'] = sum('ocr' in w.casefold() for w in row['warnings'])
        if row['errors']:
            row['status'] = 'error'
        elif row['plugin'] in ('generic.kontoauszug', ''):
            row['status'] = 'generic_fallback'
        elif row['warnings']:
            row['status'] = 'parsed_with_warnings'
        else:
            row['status'] = 'parsed'
    except Exception as e:
        row['errors'] = [scrub(f'{type(e).__name__}: {e}')]
        row['exception_type'] = type(e).__name__
        row['traceback'] = scrub(traceback.format_exc(limit=6))
    finally:
        row['duration_s'] = round(time.perf_counter() - start, 3)
    return row


def load_previous(path):
    if not path:
        return None
    previous = json.loads(Path(path).read_text(encoding='utf-8'))
    return {item['path']: item for item in previous['files']}


def diff_against(rows, previous):
    if previous is None:
        return {'baseline_used': False, 'new_files': [], 'removed_files': [], 'changed': []}
    now = {r['path']: r for r in rows}
    changes = []
    for key in sorted(now.keys() & previous.keys()):
        a, b = previous[key], now[key]
        fields = ('sha256', 'status', 'plugin', 'handler', 'document_type',
                  'transactions', 'snapshots', 'tax_events', 'documents')
        delta = {field: {'before': a.get(field), 'after': b.get(field)}
                 for field in fields if a.get(field) != b.get(field)}
        if delta:
            changes.append({'path': key, 'fields': delta})
    return {'baseline_used': True, 'new_files': sorted(now.keys() - previous.keys()),
            'removed_files': sorted(previous.keys() - now.keys()), 'changed': changes}


def markdown(report):
    s = report['summary']
    lines = ['# Portman – PDF-Parser-Audit', '',
             f"- Zeitpunkt (UTC): `{report['generated_at_utc']}`",
             f"- Scan-Wurzel: `{report['scan_root']}`",
             f"- OCR erlaubt: `{report['ocr_enabled']}`",
             f"- Python: `{report['runtime']['python']}`",
             f"- Gefundene Plugins: **{len(report['plugins'])}**; Ladefehler: **{len(report['plugin_load_errors'])}**",
             f"- PDF-Dateien: **{s['total']}**; eindeutige Inhalte: **{s['unique_hashes']}**",
             f"- Fehler: **{s['errors']}**; generischer Fallback: **{s['generic_fallback']}**; Warnungen: **{s['parsed_with_warnings']}**",
             f"- Erfolgreich ohne Warnung: **{s['parsed']}**; Gesamtdauer: **{s['seconds']} s**", '',
             '## Statusverteilung', '', '| Status | Anzahl |', '|---|---:|']
    lines += [f'| {k} | {v} |' for k, v in sorted(s['by_status'].items())]
    lines += ['', '## Parserabdeckung', '', '| Plugin | PDFs | Fehler | Warnungen |', '|---|---:|---:|---:|']
    for plugin, cnt in sorted(s['by_plugin'].items()):
        lines.append(f"| `{plugin}` | {cnt} | {sum(r['plugin'] == plugin and r['status'] == 'error' for r in report['files'])} | {sum(r['plugin'] == plugin and r['status'] == 'parsed_with_warnings' for r in report['files'])} |")
    lines += ['', '## Plugin-Inventar', '', '| Plugin-ID | Bank | Version | Quelldatei |', '|---|---|---|---|']
    for p in report['plugins']:
        lines.append(f"| `{p['id']}` | {p['bank']} | {p['version']} | `{p['source']}` |")
    if report['plugin_load_errors']:
        lines += ['', '## Plugin-Ladefehler', ''] + ['- ' + x for x in report['plugin_load_errors']]
    if report['scan_errors']:
        lines += ['', '## Dateisystem-Scanfehler', ''] + ['- ' + x for x in report['scan_errors']]
    lines += ['', '## Problemfälle (vollständig)', '', '| Datei | SHA256 (12) | Parser / Handler | Status | Befund |', '|---|---|---|---|---|']
    problems = [r for r in report['files'] if r['status'] != 'parsed']
    for r in problems:
        detail = '; '.join((r['errors'] + r['warnings'])[:3]) or 'Fallback ohne Fehlermeldung'
        detail = detail.replace('|', '\\|').replace('\n', ' ')
        path = r['path'].replace('|', '\\|')
        lines.append(f"| `{path}` | `{r['sha256'][:12]}` | `{r['plugin']}/{r['handler']}` | {r['status']} | {detail[:280]} |")
    if not problems:
        lines.append('Keine Problemfälle.')
    d = report['comparison']
    lines += ['', '## Vergleich mit vorherigem Lauf', '']
    if not d['baseline_used']:
        lines.append('Kein vorheriger Bericht übergeben. Für Delta-Auswertung `--compare` verwenden.')
    else:
        lines.append(f"Neue Dateien: **{len(d['new_files'])}**, entfernte: **{len(d['removed_files'])}**, geänderte Befunde: **{len(d['changed'])}**.")
        for c in d['changed']:
            lines.append(f"- `{c['path']}`: " + ', '.join(f"{k}: {v['before']} → {v['after']}" for k,v in c['fields'].items()))
    lines += ['', '## Methodik und Grenzen', '',
              '- Read-only: PDFs werden nur gelesen; keine Portfolio-Datenbank geöffnet, keine Import-Batches committed.',
              '- Alle Dateien laufen durch den produktiven `parse_pdf()`-Einstieg. Plugin-Erkennung und Handler laufen gemäß Produktivlogik.',
              '- Ein erfolgreicher Parserlauf ist **kein** Nachweis über korrekte Beträge gegenüber dem PDF-Original; fachlicher Goldstandard erfordert Ground-Truth-Fixtures.',
              '- Nicht erkannte PDFs und generische Fallbacks werden separat ausgewiesen; sie gelten nicht als bankspezifisch erfolgreich.',
              '- Native Extraktion ohne OCR kann Scan-PDFs nicht vollständig abdecken. OCR ist optional zuschaltbar.',
              '- Berichte können Dateinamen, Transaktionsreferenzen und weitere sensible Angaben enthalten; nicht öffentlich teilen.',
              '- Eine Parserabdeckung ist nur gegeben, wenn ein PDF den Parser tatsächlich auswählt; ungenutzte Plugins bleiben im Inventar sichtbar.', '']
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(r'C:\Users\chris\Desktop\history'))
    parser.add_argument('--output', type=Path, default=Path('test_reports/pdf_parser_audit'))
    parser.add_argument('--compare', type=Path, help='Previous audit.json to compare')
    parser.add_argument('--allow-ocr', action='store_true', help='Enables local OCR; default native PDF text only')
    parser.add_argument('--limit', type=int, default=None, help='Optional development sample size')
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        parser.error(f'PDF root is not a directory: {args.root}')
    root = args.root.resolve()
    out = args.output.resolve()
    if out == root or root in out.parents:
        parser.error('Output must be OUTSIDE PDF input directory')
    from portfolio_v5.pdf_plugins.registry import discover_plugins
    plugins, load_errors = discover_plugins()
    inventory = [{'id': as_text(p.plugin_id), 'bank': as_text(p.bank_name),
                  'version': as_text(p.version), 'source': as_text(getattr(p, 'source_path', 'entry-point'))}
                 for p in plugins]
    paths, scan_errors = pdf_paths(root)
    if args.limit is not None:
        paths = paths[:args.limit]
    start = time.perf_counter()
    rows, hashes = [], {}
    for i, path in enumerate(paths, 1):
        r = parse_one(path, root, args.allow_ocr, plugins, load_errors)
        if r['sha256']:
            if r['sha256'] in hashes:
                r['duplicate_of'] = hashes[r['sha256']]
            else:
                hashes[r['sha256']] = r['path']
        rows.append(r)
        if i % 25 == 0 or i == len(paths):
            print(f'{i}/{len(paths)} PDFs geprüft; aktuelle Fehler: {sum(x["status"] == "error" for x in rows)}', flush=True)
    statuses = Counter(r['status'] for r in rows)
    summary = {'total': len(rows), 'unique_hashes': len(hashes), 'by_status': dict(statuses),
               'by_plugin': dict(Counter(r['plugin'] or '(kein Plugin)' for r in rows)),
               'errors': statuses['error'], 'generic_fallback': statuses['generic_fallback'],
               'parsed_with_warnings': statuses['parsed_with_warnings'], 'parsed': statuses['parsed'],
               'seconds': round(time.perf_counter()-start, 2)}
    result = {'schema_version': 1, 'generated_at_utc': datetime.now(timezone.utc).isoformat(),
              'scan_root': str(root), 'ocr_enabled': args.allow_ocr,
              'runtime': {'python': sys.version.split()[0], 'platform': platform.platform()},
              'plugins': inventory, 'plugin_load_errors': load_errors, 'scan_errors': scan_errors,
              'summary': summary, 'comparison': diff_against(rows, load_previous(args.compare)), 'files': rows}
    out.mkdir(parents=True, exist_ok=True)
    (out/'audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    (out/'report.md').write_text(markdown(result), encoding='utf-8')
    with (out/'files.csv').open('w', newline='', encoding='utf-8-sig') as f:
        fieldnames = ['path', 'sha256', 'bytes', 'duplicate_of', 'status', 'plugin', 'handler',
                      'document_type', 'confidence', 'transactions', 'snapshots', 'documents',
                      'tax_events', 'duration_s', 'ocr_indications', 'errors', 'warnings']
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore', delimiter=';')
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, 'warnings': ' || '.join(row['warnings']),
                             'errors': ' || '.join(row['errors'])})
    print(f"Fertig: {out / 'report.md'} | Fehler={summary['errors']}, Fallbacks={summary['generic_fallback']}")
    return 0 if not summary['errors'] and not load_errors and not scan_errors else 1


if __name__ == '__main__':
    raise SystemExit(main())
