import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from portfolio_v5 import ocr_diagnostics as diagnostics


def test_version_satisfies_handles_requirement_ranges():
    assert diagnostics.version_satisfies('3.10.0', '>=3.9.2,<4')
    assert not diagnostics.version_satisfies('4.0.0', '>=3.9.2,<4')
    assert diagnostics.version_satisfies('5.14.0', '>=4,<6')
    assert not diagnostics.version_satisfies('3.13.0', '>=4,<6')


def test_parse_requirements_ignores_comments_and_options(tmp_path):
    path = tmp_path / 'requirements.txt'
    path.write_text('# comment\nrapidocr>=3.9.2,<4\npypdfium2>=4,<6\n-r other.txt\n', encoding='utf-8')
    assert diagnostics.parse_requirements(path) == {
        'rapidocr': '>=3.9.2,<4', 'pypdfium2': '>=4,<6'}


def test_missing_package_is_reported_as_fail():
    status, detail = diagnostics.package_check('portman-package-that-does-not-exist')
    assert status == diagnostics.FAIL
    assert 'nicht installiert' in detail


def test_report_uses_worst_status_and_json_roundtrip():
    report = diagnostics.Report(metadata={'python': '3.13'})
    report.add('A', diagnostics.PASS, 'ok')
    report.add('B', diagnostics.WARN, 'careful')
    assert report.status == diagnostics.WARN
    report.add('C', diagnostics.FAIL, 'broken')
    assert report.status == diagnostics.FAIL
    assert report.counts == {diagnostics.PASS: 1, diagnostics.WARN: 1, diagnostics.FAIL: 1}
    loaded = json.loads(diagnostics.report_json(report))
    assert loaded['status'] == diagnostics.FAIL
    assert loaded['counts'][diagnostics.FAIL] == 1
    assert 'C: broken' in diagnostics.format_report(report)


def test_check_pdf_reports_missing_file_as_fail():
    report = diagnostics.Report()
    diagnostics.check_real_pdf(report, Path('does-not-exist.pdf'))
    assert report.status == diagnostics.FAIL
    assert 'nicht gefunden' in report.checks[-1].detail


def test_wkn_detection_from_problem_file_names():
    assert diagnostics._wkn_from_name(
        'Wertpapierabrechnung_Kauf_0,006_St._LS9AVX_(LANG+SCHWARZ)_vom_07.01.2026.pdf') == 'LS9AVX'
    assert diagnostics._wkn_from_name(
        'Steuermitteilung_A2H57N_(AIS)_vom_02.01.2026.pdf') == 'A2H57N'
    assert diagnostics._wkn_from_name(
        'Kosteninformation_Sparplan_Nr._38_LYX05A_(MUL)_vom_02.09.2026.pdf') == 'LYX05A'


def test_transaction_problems_accepts_negative_buy_amount():
    tx = SimpleNamespace(security='DE000LS9AVX3', quantity='0.006', price='4152.91',
                         gross_amount='24.92', amount='-24.92', kind='BUY')
    assert diagnostics._transaction_problems(tx, 'DE000LS9AVX3', lambda isin: True) == []


def test_transaction_problems_reports_wrong_isin_and_amount():
    tx = SimpleNamespace(security='DE0000000000', quantity='0.006', price='4152.91',
                         gross_amount='24.92', amount='24.92', kind='BUY')
    problems = diagnostics._transaction_problems(tx, 'DE000LS9AVX3', lambda isin: False)
    assert any('DE000LS9AVX3' in problem for problem in problems)
    assert any('ungültige ISIN' in problem for problem in problems)
    assert any('nicht negativ' in problem for problem in problems)
    assert abs(Decimal(tx.quantity) * Decimal(tx.price) - Decimal(tx.gross_amount)) < Decimal('0.01')
