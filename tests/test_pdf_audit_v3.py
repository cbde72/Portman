import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('pdf_audit_v3', ROOT / 'tools' / 'pdf_audit_v3.py')
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def row(path='bank/test.pdf', sha='a' * 64, severity='PASS'):
    return AUDIT.classify({
        'path': path, 'sha256': sha, 'bytes': 10, 'status': severity, 'plugin': 'bank.pdf',
        'handler': 'statement', 'document_type': 'Statement', 'confidence': 1.0,
        'transactions': [], 'tax_events': [], 'snapshots': [], 'documents': [],
        'warnings': [], 'errors': [], 'ocr_indications': 0, 'duration_s': .1})


def completed(stdout='', stderr='', returncode=0):
    return subprocess.CompletedProcess(['worker'], returncode, stdout, stderr)


def powershell_executable():
    return shutil.which('pwsh') or shutil.which('powershell')


def test_worker_stdio_is_reconfigured_to_strict_utf8(monkeypatch):
    calls = []

    class Stream:
        def reconfigure(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(AUDIT.sys, 'stdout', Stream())
    monkeypatch.setattr(AUDIT.sys, 'stderr', Stream())
    AUDIT.configure_worker_stdio()
    assert calls == [
        {'encoding': 'utf-8', 'errors': 'strict'},
        {'encoding': 'utf-8', 'errors': 'strict'},
    ]


def test_unicode_worker_output_uses_explicit_utf8_without_pythonioencoding(monkeypatch, tmp_path):
    pdf = tmp_path / 'Überblick → Kosten−10€.pdf'
    pdf.write_bytes(b'%PDF')
    payload = row(pdf.name)
    payload['warnings'] = ['Änderung → −10 €']
    seen = {}

    def fake_run(*args, **kwargs):
        seen.update(kwargs)
        return completed(json.dumps(payload, ensure_ascii=False))

    monkeypatch.delenv('PYTHONIOENCODING', raising=False)
    monkeypatch.setattr(subprocess, 'run', fake_run)
    result = AUDIT.run_child(pdf, tmp_path, False, 1)
    assert result['warnings'] == ['Änderung → −10 €']
    assert seen['encoding'] == 'utf-8' and seen['errors'] == 'strict'
    assert seen['env']['PYTHONIOENCODING'] == 'utf-8'
    assert seen['env']['PYTHONUTF8'] == '1'


def test_cp1252_parent_environment_does_not_change_worker_protocol(monkeypatch, tmp_path):
    pdf = tmp_path / '€-Umlaut-ä.pdf'
    pdf.write_bytes(b'%PDF')
    monkeypatch.setenv('PYTHONIOENCODING', 'cp1252')
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: completed(
        json.dumps(row(pdf.name), ensure_ascii=False)))
    assert AUDIT.run_child(pdf, tmp_path, False, 1)['path'] == pdf.name


def test_worker_json_deserialization(monkeypatch, tmp_path):
    pdf = tmp_path / 'test.pdf'
    pdf.write_bytes(b'%PDF')
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: completed(json.dumps(row())))
    assert AUDIT.run_child(pdf, tmp_path, False, 1)['severity'] == 'PASS'


def test_worker_crash_is_not_reported_as_parser_error(monkeypatch, tmp_path):
    pdf = tmp_path / 'crash.pdf'
    pdf.write_bytes(b'%PDF')
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: completed(
        stderr='Worker starb → unerwartet', returncode=7))
    result = AUDIT.run_child(pdf, tmp_path, False, 1)
    assert result['severity'] == 'ERROR'
    assert result['status'] == 'WORKER_CRASH'
    assert result['issue_codes'] == ['WORKER_CRASH']
    assert 'PARSER_ERROR' not in result['issue_codes']


def test_invalid_worker_json_is_worker_crash(monkeypatch, tmp_path):
    pdf = tmp_path / 'broken-json.pdf'
    pdf.write_bytes(b'%PDF')
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: completed('keine JSON-Ausgabe →'))
    result = AUDIT.run_child(pdf, tmp_path, False, 1)
    assert result['status'] == 'WORKER_CRASH'
    assert 'Ungültige Worker-JSON-Ausgabe' in result['errors'][0]


def test_timeout_isolated_as_own_result(monkeypatch, tmp_path):
    pdf = tmp_path / 'slow.pdf'
    pdf.write_bytes(b'%PDF')
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: (_ for _ in ()).throw(
        subprocess.TimeoutExpired(args[0], kwargs['timeout'])))
    result = AUDIT.run_child(pdf, tmp_path, False, .01)
    assert result['severity'] == 'TIMEOUT'
    assert result['issue_codes'] == ['TIMEOUT']


def test_resume_requires_root_ocr_fingerprint_and_matching_file(tmp_path):
    root = tmp_path.resolve()
    progress = tmp_path / 'progress.json'
    progress.write_text(json.dumps({'scan_root': str(root), 'parser_fingerprint': 'fp',
                                    'ocr_enabled': True, 'files': [row()]}), encoding='utf-8')
    assert list(AUDIT.load_resume(progress, root, 'fp', True)) == ['bank/test.pdf']
    assert AUDIT.load_resume(progress, root, 'changed', True) == {}
    assert AUDIT.load_resume(progress, root, 'fp', False) == {}


def test_resume_and_no_cache_are_mutually_exclusive(tmp_path):
    with pytest.raises(SystemExit) as error:
        AUDIT.main(['--root', str(tmp_path), '--output', str(tmp_path.parent / 'out'),
                    '--resume', '--no-cache'])
    assert error.value.code == 2


def test_no_cache_does_not_load_progress(monkeypatch, tmp_path):
    output = tmp_path.parent / f'{tmp_path.name}-output'
    pdf = tmp_path / 'fresh.pdf'
    pdf.write_bytes(b'%PDF')
    output.mkdir()
    (output / 'progress.json').write_text('{}', encoding='utf-8')
    monkeypatch.setattr(AUDIT, 'parser_fingerprint', lambda: 'fp')
    monkeypatch.setattr(AUDIT, 'load_resume', lambda *args: pytest.fail('cache was loaded'))
    monkeypatch.setattr(AUDIT, 'run_child', lambda *args: row(pdf.name, AUDIT.sha256(pdf)))
    monkeypatch.setattr(AUDIT, 'build_result', lambda rows, *args: {
        'files': rows, 'summary': {'severity': {}}, 'comparison': {}})
    monkeypatch.setattr(AUDIT, 'write_outputs', lambda *args: None)
    assert AUDIT.main(['--root', str(tmp_path), '--output', str(output), '--no-cache']) == 0


def test_sha_comparison_matches_moved_file_and_detects_handler_change():
    before = row('old/test.pdf')
    after = row('new/test.pdf')
    after['handler'] = 'new-layout'
    delta = AUDIT.comparison([after], {'files': [before]})
    assert delta['sha_compared'] == 1
    assert delta['physical_compared'] == 0
    assert delta['changed'][0]['matched_by'] == 'sha256'
    assert 'handler' in delta['changed'][0]['fields']


def test_parser_fingerprint_changes_with_parser_content(monkeypatch, tmp_path):
    parser = tmp_path / 'pdf_plugins' / 'parser.py'
    parser.parent.mkdir()
    (tmp_path / 'src' / 'portfolio_v5').mkdir(parents=True)
    monkeypatch.setattr(AUDIT, 'PROJECT_ROOT', tmp_path)
    parser.write_text('one', encoding='utf-8')
    first = AUDIT.parser_fingerprint()
    parser.write_text('two', encoding='utf-8')
    assert AUDIT.parser_fingerprint() != first


def test_complete_result_files_are_written_with_unicode(tmp_path):
    unicode_row = row('Bänk/Überblick → −10€.pdf')
    unicode_row['warnings'] = ['Gebühr −10 € → geprüft']
    result = {
        'summary': {'resumed': 0, 'physical': 1, 'unique_sha': 1,
                    'severity': {'PASS': 1}, 'generic_fallbacks': 0,
                    'issue_codes': {}, 'newly_supported': 0,
                    'changed_transaction_counts': 0, 'changed_tax_event_counts': 0},
        'comparison': {'physical_compared': 0, 'sha_compared': 0, 'changed': [],
                       'regressions': []},
        'generated_at_utc': '2026-10-26T00:00:00+00:00', 'scan_root': 'input',
        'git_commit': 'abc', 'ocr_enabled': False, 'timeout_s': 1,
        'banks': {'Bänk': {'physical': 1, 'unique_sha': 1, 'errors': 0, 'timeouts': 0,
                           'warnings': 0, 'fallbacks': 0, 'transactions': 0,
                           'tax_events': 0, 'archive_only': 0}},
        'potential_duplicates': [], 'files': [unicode_row],
    }
    AUDIT.write_outputs(tmp_path, result)
    expected = {'audit.json', 'files.csv', 'findings.csv', 'transactions.csv', 'delta.csv', 'report.md'}
    assert expected == {path.name for path in tmp_path.iterdir()}
    decoded = json.loads((tmp_path / 'audit.json').read_text(encoding='utf-8'))
    assert decoded['files'][0]['path'] == 'Bänk/Überblick → −10€.pdf'
    assert 'Bänk' in (tmp_path / 'report.md').read_text(encoding='utf-8')


@pytest.mark.skipif(not powershell_executable(), reason='PowerShell is not installed')
def test_powershell_launcher_sets_import_path_before_environment_check(tmp_path):
    pdf_root = tmp_path / 'pdfs'
    output = tmp_path / 'fresh-output'
    baseline = tmp_path / 'baseline.json'
    pdf_root.mkdir()
    baseline.write_text('{"files": []}', encoding='utf-8')
    environment = os.environ.copy()
    environment['PYTHONPATH'] = ''
    environment['PYTHONIOENCODING'] = 'cp1252'
    result = subprocess.run([
        powershell_executable(), '-NoProfile', '-File', str(ROOT / 'tools' / 'powershell_audit_v3.ps1'),
        '-PdfRoot', str(pdf_root), '-Baseline', str(baseline), '-Output', str(output),
    ], cwd=tmp_path, env=environment, capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert result.returncode == 0, result.stderr
    assert (output / 'audit.json').is_file()


@pytest.mark.skipif(not powershell_executable(), reason='PowerShell is not installed')
def test_powershell_launcher_refuses_to_overwrite_existing_output(tmp_path):
    pdf_root = tmp_path / 'pdfs'
    output = tmp_path / 'existing-output'
    baseline = tmp_path / 'baseline.json'
    pdf_root.mkdir()
    output.mkdir()
    sentinel = output / 'keep.txt'
    sentinel.write_text('do not overwrite', encoding='utf-8')
    baseline.write_text('{"files": []}', encoding='utf-8')
    result = subprocess.run([
        powershell_executable(), '-NoProfile', '-File', str(ROOT / 'tools' / 'powershell_audit_v3.ps1'),
        '-PdfRoot', str(pdf_root), '-Baseline', str(baseline), '-Output', str(output),
    ], cwd=tmp_path, capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert result.returncode != 0
    assert 'Output directory already exists' in result.stderr
    assert sentinel.read_text(encoding='utf-8') == 'do not overwrite'


def test_ocr_audit_limits_process_contention_without_serializing_plain_text():
    assert AUDIT.audit_worker_count(True, 16) == 2
    assert AUDIT.audit_worker_count(False, 16) == 4
    assert AUDIT.audit_worker_count(True, 1) == 1
