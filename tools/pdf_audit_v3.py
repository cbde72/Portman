"""Read-only, resumable Portman PDF parser audit V3.

Every PDF is parsed in a child process through the production ``parse_pdf``
entry point.  The runner never imports RepositoryV09 and never opens a database.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for import_root in (PROJECT_ROOT, PROJECT_ROOT / 'src'):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

SCHEMA_VERSION = 3
SEVERITY = {'PASS': 0, 'INFO': 1, 'WARNING': 2, 'ERROR': 3, 'TIMEOUT': 4}
ERROR_RULES = [
    ('CANCELLATION', r'Stornobeleg|stornier'), ('MIFID_COST', r'MiFID|Kosteninformation'),
    ('QUANTITY_CONFLICT', r'Stückzahl|Nominale|Menge'),
    ('DIVIDEND_TAX', r'Ausschüttung|Dividende|Steuermitteilung'),
    ('UNSUPPORTED_LAYOUT', r'keine unterstützte|nicht unterstützt|unbekanntes Layout'),
    ('TEXT_EXTRACTION', r'Textextraktion|Text nicht|nicht lesbar|OCR|extrahier'),
    ('ENCRYPTED', r'passwortgeschützt|verschlüsselt'),
]
WARNING_RULES = [
    ('BUY_POSITIVE', r'Kauf mit positivem Betrag|Kauf.+Abfluss muss negativ'),
    ('NET_GROSS_MISMATCH', r'Brutto/Netto passt nicht'),
    ('QUANTITY_CONFLICT', r'Stückzahl.*(?:widerspr|abweich|passt nicht)|widersprüchliche Stückzahlen'),
    ('OCR_FAILED', r'OCR fehlgeschlagen|OCR hat keinen Text erkannt|geringer Sicherheit'),
    ('OCR_LAYOUT', r'Gedrehter Text oder Layoutproblem|Tabellenspalten am Original prüfen'),
    ('CANCELLATION', r'Stornobeleg|stornier'), ('MIFID_COST', r'MiFID|Kosteninformation'),
    ('DIVIDEND_TAX', r'Ausschüttung|Dividende|Vorabpauschale'),
]


def configure_worker_stdio():
    """Make the worker protocol independent from the Windows ANSI code page."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure:
            reconfigure(encoding='utf-8', errors='strict')


def json_value(value):
    if is_dataclass(value):
        return json_value(asdict(value))
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    if isinstance(value, (Decimal, Path)):
        return str(value)
    return value


def sha256(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            result.update(block)
    return result.hexdigest()


def pdf_paths(root):
    errors = []
    paths = []
    for folder, _, names in os.walk(root, followlinks=False,
                                     onerror=lambda error: errors.append(str(error))):
        paths.extend(Path(folder) / name for name in names if name.lower().endswith('.pdf'))
    return sorted(paths, key=lambda value: str(value).casefold()), errors


def scrub(value):
    text = str(value)
    return re.sub(r'\bDE(?:[\s-]*\d){20}\b', '[IBAN]', text, flags=re.I)[:4000]


def compact_transaction(transaction):
    data = json_value(transaction)
    return {key: data.get(key) for key in (
        'external_id', 'kind', 'account', 'date', 'value_date', 'amount', 'currency',
        'security', 'security_ref', 'quantity', 'gross_amount', 'fees', 'taxes',
        'fee_items', 'tax_items', 'affects_cash', 'is_reversal', 'reverses_external_id',
        'cash_account', 'depot_account') if data.get(key) not in (None, '', [], {})}


def compact_snapshot(snapshot):
    data = json_value(snapshot)
    positions = []
    for position in data.get('positions', []):
        positions.append({key: position.get(key) for key in (
            'key', 'name', 'isin', 'wkn', 'quantity', 'value', 'currency', 'price',
            'price_currency', 'quote_date') if position.get(key) not in (None, '')})
    return {**{key: data.get(key) for key in (
        'account', 'period', 'as_of', 'sheet', 'complete', 'reported_total_value',
        'reported_position_count', 'statement_type') if data.get(key) not in (None, '')},
            'positions': positions, 'warnings': data.get('warnings', [])}


def worker(path, root, allow_ocr):
    from portfolio_v5.pdf_importer import parse_pdf
    started = time.perf_counter()
    path, root = Path(path), Path(root)
    row = {'path': path.relative_to(root).as_posix(), 'sha256': sha256(path),
           'bytes': path.stat().st_size, 'status': 'ERROR', 'plugin': '', 'handler': '',
           'document_type': '', 'confidence': None, 'transactions': [], 'tax_events': [],
           'snapshots': [], 'documents': [], 'warnings': [], 'errors': [],
           'ocr_indications': 0, 'duration_s': None}
    try:
        batch = parse_pdf(path, allow_ocr=allow_ocr)
        row.update(plugin=str(getattr(batch, 'plugin_id', '')),
                   handler=str(getattr(batch, 'plugin_handler', '')),
                   document_type=str(getattr(batch, 'document_type', '')),
                   confidence=getattr(batch, 'detection_confidence', None),
                   transactions=[compact_transaction(x) for x in getattr(batch, 'transactions', ())],
                   tax_events=[json_value(x) for x in getattr(batch, 'tax_events', ())],
                   snapshots=[compact_snapshot(x) for x in getattr(batch, 'snapshots', ())],
                   documents=[{key: json_value(x).get(key) for key in
                              ('account', 'external_id', 'title', 'date', 'media_type')
                              if json_value(x).get(key) not in (None, '')}
                              for x in getattr(batch, 'documents', ())],
                   warnings=[scrub(x) for x in getattr(batch, 'warnings', ())],
                   errors=[scrub(x) for x in getattr(batch, 'errors', ())])
    except Exception as error:
        row['errors'] = [scrub(f'{type(error).__name__}: {error}')]
        row['exception_type'] = type(error).__name__
        row['traceback'] = scrub(traceback.format_exc(limit=8))
    row['ocr_indications'] = sum('ocr' in item.casefold() for item in row['warnings'])
    row['duration_s'] = round(time.perf_counter() - started, 3)
    return classify(row)


def findings(row):
    result = []
    for message in row.get('errors', []):
        code = next((code for code, pattern in ERROR_RULES if re.search(pattern, message, re.I)),
                    'PARSER_ERROR')
        result.append({'code': code, 'level': 'ERROR', 'message': message})
    for message in row.get('warnings', []):
        match = next(((code, 'WARNING') for code, pattern in WARNING_RULES
                      if re.search(pattern, message, re.I)), None)
        if match:
            code, level = match
        elif re.search(r'PDF-Plugin:|Käufe: Nominale|Textergänzung', message, re.I):
            code, level = 'PLUGIN_NOTICE', 'INFO'
        else:
            code, level = 'UNCLASSIFIED_WARNING', 'WARNING'
        result.append({'code': code, 'level': level, 'message': message})
    if row.get('plugin') in ('generic.kontoauszug', '') and not row.get('errors'):
        result.append({'code': 'GENERIC_FALLBACK', 'level': 'WARNING',
                       'message': 'Kein spezifischer Parser ausgewählt'})
    return result


def classify(row):
    row = dict(row)
    if row.get('status') in ('TIMEOUT', 'WORKER_CRASH'):
        code = row['status']
        level = 'TIMEOUT' if code == 'TIMEOUT' else 'ERROR'
        row['severity'], row['findings'], row['issue_codes'] = level, [
            {'code': code, 'level': level, 'message': row['errors'][0]}], [code]
        row['archive_only'] = False
        return row
    row['findings'] = findings(row)
    row['severity'] = max((item['level'] for item in row['findings']),
                          key=SEVERITY.get, default='PASS')
    row['issue_codes'] = sorted({x['code'] for x in row['findings']
                                 if x['level'] in ('WARNING', 'ERROR', 'TIMEOUT')})
    row['status'] = row['severity']
    if (row['severity'] in ('PASS', 'INFO') and row.get('documents')
            and not row.get('transactions') and not row.get('tax_events') and not row.get('snapshots')):
        row['archive_only'] = True
    else:
        row['archive_only'] = False
    return row


def run_child(path, root, allow_ocr, timeout):
    command = [sys.executable, str(Path(__file__).resolve()), '--worker', str(path),
               '--root', str(root)]
    if allow_ocr:
        command.append('--allow-ocr')
    started = time.perf_counter()
    try:
        child_env = os.environ.copy()
        child_env['PYTHONIOENCODING'] = 'utf-8'
        child_env['PYTHONUTF8'] = '1'
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                                encoding='utf-8', errors='strict', env=child_env,
                                cwd=PROJECT_ROOT)
        if result.returncode:
            detail = result.stderr.strip() or result.stdout.strip() or f'Exit-Code {result.returncode}'
            raise ChildProcessError(detail)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise ValueError(f'Ungültige Worker-JSON-Ausgabe: {error}') from error
    except subprocess.TimeoutExpired:
        return classify({'path': path.relative_to(root).as_posix(), 'sha256': sha256(path),
                         'bytes': path.stat().st_size, 'status': 'TIMEOUT', 'plugin': '',
                         'handler': '', 'document_type': '', 'confidence': None,
                         'transactions': [], 'tax_events': [], 'snapshots': [], 'documents': [],
                         'warnings': [], 'errors': [f'Zeitlimit von {timeout} Sekunden überschritten.'],
                         'ocr_indications': 0, 'duration_s': round(time.perf_counter()-started, 3)})
    except Exception as error:
        return classify({'path': path.relative_to(root).as_posix(), 'sha256': sha256(path),
                         'bytes': path.stat().st_size, 'status': 'WORKER_CRASH', 'plugin': '',
                         'handler': '', 'document_type': '', 'confidence': None,
                         'transactions': [], 'tax_events': [], 'snapshots': [], 'documents': [],
                         'warnings': [], 'errors': [scrub(f'{type(error).__name__}: {error}')],
                         'ocr_indications': 0, 'duration_s': round(time.perf_counter()-started, 3)})


def parser_fingerprint():
    roots = list((PROJECT_ROOT / 'pdf_plugins').rglob('*.py'))
    roots += list((PROJECT_ROOT / 'src' / 'portfolio_v5').rglob('*.py'))
    digest = hashlib.sha256()
    digest.update(f'audit-schema-{SCHEMA_VERSION}'.encode())
    for path in sorted(set(roots)):
        digest.update(path.relative_to(PROJECT_ROOT).as_posix().encode())
        digest.update(sha256(path).encode())
    digest.update(sys.version.encode())
    return digest.hexdigest()


def audit_worker_count(allow_ocr, cpu_count=None):
    """Bound OCR process contention; two RapidOCR workers stay below file timeouts."""
    available = cpu_count if cpu_count is not None else (os.cpu_count() or 1)
    limit = 2 if allow_ocr else 4
    return max(1, min(limit, available))


def economic_signature(row):
    fields = ('external_id', 'kind', 'account', 'date', 'amount', 'currency', 'security',
              'quantity', 'gross_amount', 'fees', 'taxes', 'is_reversal', 'reverses_external_id')
    values = [{key: tx.get(key) for key in fields if tx.get(key) not in (None, '')}
              for tx in row.get('transactions', [])]
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def comparison(rows, baseline):
    if not baseline:
        return {'baseline_used': False, 'physical_compared': 0, 'sha_compared': 0,
                'changed': [], 'regressions': [], 'new_paths': [], 'removed_paths': []}
    old_rows = baseline.get('files', [])
    old_path = {row['path']: row for row in old_rows}
    old_sha = defaultdict(list)
    for row in old_rows:
        old_sha[row.get('sha256')].append(row)
    now_path = {row['path']: row for row in rows}
    changed, regressions = [], []
    for row in rows:
        old = old_path.get(row['path'])
        match = 'path'
        if not old and old_sha.get(row['sha256']):
            old, match = old_sha[row['sha256']][0], 'sha256'
        if not old:
            continue
        old = classify(old)
        fields = {}
        for key, before, after in (
            ('severity', old['severity'], row['severity']), ('plugin', old.get('plugin'), row.get('plugin')),
            ('handler', old.get('handler'), row.get('handler')),
            ('transactions', old.get('transactions', 0) if isinstance(old.get('transactions'), int) else len(old.get('transactions', [])), len(row['transactions'])),
            ('tax_events', old.get('tax_events', 0) if isinstance(old.get('tax_events'), int) else len(old.get('tax_events', [])), len(row['tax_events'])),
            ('snapshots', old.get('snapshots', 0) if isinstance(old.get('snapshots'), int) else len(old.get('snapshots', [])), len(row['snapshots'])),
        ):
            if before != after:
                fields[key] = {'before': before, 'after': after}
        if fields:
            entry = {'path': row['path'], 'sha256': row['sha256'], 'matched_by': match,
                     'fields': fields, 'economic_signature': economic_signature(row)}
            changed.append(entry)
            if (SEVERITY[row['severity']] > SEVERITY[old['severity']]
                    or (old.get('plugin') and row.get('plugin') != old.get('plugin'))):
                regressions.append(entry)
    return {'baseline_used': True,
            'physical_compared': len(set(now_path) & set(old_path)),
            'sha_compared': len(set(x['sha256'] for x in rows) & set(old_sha)),
            'changed': changed, 'regressions': regressions,
            'new_paths': sorted(set(now_path) - set(old_path)),
            'removed_paths': sorted(set(old_path) - set(now_path))}


def write_csv(path, rows, fields):
    with path.open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fields, delimiter=';', extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict))
                             else value for key, value in row.items()})


def bank_name(row, plugin_banks):
    return plugin_banks.get(row.get('plugin')) or row['path'].split('/', 1)[0]


def report(result):
    summary, delta = result['summary'], result['comparison']
    lines = ['# Portman V09 – Vollständiger PDF-Parser-Audit V3', '',
             f"- Zeitpunkt (UTC): `{result['generated_at_utc']}`",
             f"- Root: `{result['scan_root']}`", f"- Ausgangscommit: `{result['git_commit']}`",
             f"- OCR: `{result['ocr_enabled']}`; Timeout: `{result['timeout_s']} s`; Cachetreffer: **{summary['resumed']}**",
             f"- PDFs: **{summary['physical']}** physisch / **{summary['unique_sha']}** eindeutig",
             f"- Fehler: **{summary['severity'].get('ERROR', 0)}**; Timeouts: **{summary['severity'].get('TIMEOUT', 0)}**; generische Fallbacks: **{summary['generic_fallbacks']}**", '',
             '## Bankenübersicht', '',
             '| Bank | Physisch | Eindeutig | Fehler | Timeouts | Warnungen | Fallbacks | Transaktionen | Steuerereignisse | Archiv-only |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for bank, data in sorted(result['banks'].items()):
        lines.append(f"| {bank} | {data['physical']} | {data['unique_sha']} | {data['errors']} | {data['timeouts']} | {data['warnings']} | {data['fallbacks']} | {data['transactions']} | {data['tax_events']} | {data['archive_only']} |")
    lines += ['', '## Warnungen und Fehlercodes', '', '| Code | PDFs |', '|---|---:|']
    lines += [f'| `{code}` | {count} |' for code, count in sorted(summary['issue_codes'].items(), key=lambda x: (-x[1], x[0]))]
    lines += ['', '## Vergleich mit V2', '',
              f"Physisch verglichen: **{delta['physical_compared']}**; per SHA verglichen: **{delta['sha_compared']}**; veränderte Datensätze: **{len(delta['changed'])}**; unbeabsichtigte Regressionen: **{len(delta['regressions'])}**.",
              f"Neu unterstützte Dokumente: **{summary['newly_supported']}**; veränderte Buchungsanzahl: **{summary['changed_transaction_counts']}**; neue/weggefallene Steuerereigniszahlen: **{summary['changed_tax_event_counts']}**.",
              '', 'Die V2-Baseline enthält nur Zählwerte, keine normalisierten Einzelbuchungen. Exakte Betragsänderungen sind daher nur für V3-Folgeläufe automatisiert vergleichbar; V2→V3 wird konservativ über Anzahl, Handler, Status und Original-SHA ausgewiesen.',
              '', '## Potenzielle Dubletten', '',
              f"Identische wirtschaftliche IDs über unterschiedliche SHA-Inhalte: **{len(result['potential_duplicates'])}**. Vollständige Details stehen in `audit.json`.",
              '', '## Methodik und Grenzen', '',
              '- Rein lesend: Es wird ausschließlich `parse_pdf()` aufgerufen; keine produktive Datenbank wird geöffnet.',
              '- Jede PDF wird in einem isolierten Kindprozess verarbeitet und bei Überschreitung des Limits beendet.',
              '- Resume-Daten gelten nur bei identischem Root, OCR-Modus und Parser-Fingerprint.',
              '- Parserwarnungen bleiben erhalten. Archiv-only, generischer Fallback, Fehler und Timeout sind getrennt.',
              '- `delta.csv` enthält jede Status-, Handler-, Transaktions-, Snapshot- oder Steuerereignisänderung.',
              '', '## PowerShell-Befehle', '', '```powershell',
              'python tools/pdf_audit_v3.py --root C:\\Users\\chris\\Desktop\\history --baseline C:\\Users\\chris\\Desktop\\programming\\PortmanNL\\test_reports\\pdf_parser_audit\\run_001\\audit.json --output test_reports\\pdf_parser_audit\\v3_full --allow-ocr --timeout 120 --no-cache',
              'python tools/pdf_audit_v3.py --root C:\\Users\\chris\\Desktop\\history --baseline C:\\Users\\chris\\Desktop\\programming\\PortmanNL\\test_reports\\pdf_parser_audit\\run_001\\audit.json --output test_reports\\pdf_parser_audit\\v3_full --allow-ocr --timeout 120 --resume',
              'Import-Csv test_reports\\pdf_parser_audit\\v3_full\\files.csv -Delimiter ";" | Group-Object severity', '```', '']
    return '\n'.join(lines)


def build_result(rows, root, baseline, fingerprint, allow_ocr, timeout, resumed, scan_errors):
    hashes = {}
    for row in sorted(rows, key=lambda x: x['path'].casefold()):
        row['duplicate_of'] = hashes.get(row['sha256'])
        hashes.setdefault(row['sha256'], row['path'])
    plugin_banks = {}
    from portfolio_v5.pdf_plugins.registry import discover_plugins
    plugins, plugin_errors = discover_plugins()
    for plugin in plugins:
        plugin_banks[str(plugin.plugin_id)] = str(plugin.bank_name)
    grouped = defaultdict(list)
    for row in rows:
        grouped[bank_name(row, plugin_banks)].append(row)
    banks = {}
    for bank, items in grouped.items():
        banks[bank] = {'physical': len(items), 'unique_sha': len({x['sha256'] for x in items}),
                       'errors': sum(x['severity'] == 'ERROR' for x in items),
                       'timeouts': sum(x['severity'] == 'TIMEOUT' for x in items),
                       'warnings': sum(x['severity'] == 'WARNING' for x in items),
                       'fallbacks': sum('GENERIC_FALLBACK' in x['issue_codes'] for x in items),
                       'transactions': sum(len(x['transactions']) for x in items),
                       'tax_events': sum(len(x['tax_events']) for x in items),
                       'archive_only': sum(x['archive_only'] for x in items)}
    delta = comparison(rows, baseline)
    identities = defaultdict(list)
    for row in rows:
        for tx in row['transactions']:
            if tx.get('external_id'):
                identities[(tx.get('account'), tx['external_id'])].append((row['sha256'], row['path']))
    duplicates = [{'account': key[0], 'external_id': key[1], 'sources': sources}
                  for key, sources in identities.items() if len({x[0] for x in sources}) > 1]
    severity = Counter(row['severity'] for row in rows)
    codes = Counter(code for row in rows for code in row['issue_codes'])
    newly = sum(any(change.get('before') == 'ERROR' and change.get('after') not in ('ERROR', 'TIMEOUT')
                    for change in entry['fields'].values()) for entry in delta['changed'])
    result = {'schema_version': SCHEMA_VERSION, 'generated_at_utc': datetime.now(timezone.utc).isoformat(),
              'scan_root': str(root), 'git_commit': subprocess.check_output(
                  ['git', 'rev-parse', 'HEAD'], text=True, encoding='utf-8').strip(),
              'ocr_enabled': allow_ocr,
              'timeout_s': timeout, 'parser_fingerprint': fingerprint,
              'runtime': {'python': sys.version.split()[0], 'platform': platform.platform()},
              'plugin_load_errors': plugin_errors, 'scan_errors': scan_errors, 'banks': banks,
              'comparison': delta, 'potential_duplicates': duplicates, 'files': rows}
    result['summary'] = {'physical': len(rows), 'unique_sha': len(hashes), 'resumed': resumed,
                         'severity': dict(severity), 'issue_codes': dict(codes),
                         'generic_fallbacks': codes['GENERIC_FALLBACK'], 'newly_supported': newly,
                         'changed_transaction_counts': sum('transactions' in x['fields'] for x in delta['changed']),
                         'changed_tax_event_counts': sum('tax_events' in x['fields'] for x in delta['changed'])}
    return result


def write_outputs(output, result):
    output.mkdir(parents=True, exist_ok=True)
    (output / 'audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'report.md').write_text(report(result), encoding='utf-8')
    file_rows = [{**row, 'transactions': len(row['transactions']), 'tax_events': len(row['tax_events']),
                  'snapshots': len(row['snapshots']), 'documents': len(row['documents'])}
                 for row in result['files']]
    write_csv(output / 'files.csv', file_rows, ['path', 'sha256', 'bytes', 'duplicate_of', 'status',
              'severity', 'plugin', 'handler', 'document_type', 'transactions', 'tax_events',
              'snapshots', 'documents', 'archive_only', 'ocr_indications', 'duration_s', 'issue_codes'])
    write_csv(output / 'findings.csv', [{'path': row['path'], 'sha256': row['sha256'], **item}
              for row in result['files'] for item in row['findings']],
              ['path', 'sha256', 'code', 'level', 'message'])
    write_csv(output / 'transactions.csv', [{'path': row['path'], 'sha256': row['sha256'], **tx}
              for row in result['files'] for tx in row['transactions']],
              ['path', 'sha256', 'external_id', 'kind', 'account', 'date', 'value_date', 'amount',
               'currency', 'security', 'quantity', 'gross_amount', 'fees', 'taxes', 'is_reversal',
               'reverses_external_id', 'affects_cash', 'fee_items', 'tax_items'])
    delta_rows = [{'kind': kind, **entry} for kind in ('changed', 'regressions')
                  for entry in result['comparison'][kind]]
    write_csv(output / 'delta.csv', delta_rows,
              ['kind', 'path', 'sha256', 'matched_by', 'fields', 'economic_signature'])


def load_resume(path, root, fingerprint, allow_ocr):
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    if (data.get('scan_root') != str(root) or data.get('parser_fingerprint') != fingerprint
            or data.get('ocr_enabled') != allow_ocr):
        return {}
    return {row['path']: row for row in data.get('files', [])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--allow-ocr', action='store_true')
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--no-cache', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.worker:
        configure_worker_stdio()
        sys.stdout.write(json.dumps(worker(args.worker.resolve(), root, args.allow_ocr),
                                    ensure_ascii=False) + '\n')
        sys.stdout.flush()
        return 0
    if not root.is_dir() or not args.output:
        parser.error('--root must exist and --output is required')
    output = args.output.resolve()
    if args.resume and args.no_cache:
        parser.error('--resume and --no-cache are mutually exclusive')
    if output == root or root in output.parents:
        parser.error('--output must be outside --root')
    fingerprint = parser_fingerprint()
    baseline = json.loads(args.baseline.read_text(encoding='utf-8')) if args.baseline else None
    paths, scan_errors = pdf_paths(root)
    resumed_rows = load_resume(output / 'progress.json', root, fingerprint, args.allow_ocr) if args.resume else {}
    rows, resumed = [], 0
    pending = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        prior = resumed_rows.get(relative)
        if (prior and prior.get('severity') != 'TIMEOUT'
                and prior.get('sha256') == sha256(path) and prior.get('bytes') == path.stat().st_size):
            rows.append(prior); resumed += 1
        else:
            pending.append(path)
    started = time.perf_counter()
    workers = audit_worker_count(args.allow_ocr)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(run_child, path, root, args.allow_ocr, args.timeout): path
                   for path in pending}
        for index, future in enumerate(as_completed(futures), 1):
            rows.append(future.result())
            progress = {'scan_root': str(root), 'parser_fingerprint': fingerprint,
                        'ocr_enabled': args.allow_ocr, 'files': rows}
            (output).mkdir(parents=True, exist_ok=True)
            (output / 'progress.json').write_text(json.dumps(progress, ensure_ascii=False), encoding='utf-8')
            if index % 25 == 0 or index == len(pending):
                print(f'{len(rows)}/{len(paths)} | Fehler {sum(x["severity"] == "ERROR" for x in rows)} | Timeouts {sum(x["severity"] == "TIMEOUT" for x in rows)} | Resume {resumed}', flush=True)
    result = build_result(rows, root, baseline, fingerprint, args.allow_ocr, args.timeout, resumed, scan_errors)
    result['summary']['seconds'] = round(time.perf_counter() - started, 2)
    write_outputs(output, result)
    print(f'Bericht: {output / "report.md"}')
    return 1 if result['summary']['severity'].get('ERROR', 0) or result['summary']['severity'].get('TIMEOUT', 0) else 0


if __name__ == '__main__':
    raise SystemExit(main())
