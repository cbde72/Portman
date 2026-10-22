#!/usr/bin/env python
"""Check PortMan's local Windows OCR stack without installing or changing anything.

Examples:
    .venv\\Scripts\\python.exe tools\\check_ocr_windows.py
    .venv\\Scripts\\python.exe tools\\check_ocr_windows.py --pdf beleg1.pdf --pdf beleg2.pdf
    .venv\\Scripts\\python.exe tools\\check_ocr_windows.py --pdf-dir C:\\belege --json

Exit codes: 0 = PASS or WARN, 1 = FAIL (or WARN with --strict), 2 = usage error.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding='utf-8')
    except (AttributeError, OSError):
        pass

from portfolio_v5.ocr_diagnostics import format_report, report_json, run_diagnostics  # noqa: E402


def collect_pdfs(directories):
    paths = []
    for directory in directories:
        base = Path(directory)
        if base.is_file() and base.suffix.lower() == '.pdf':
            paths.append(base)
        elif base.is_dir():
            paths.extend(sorted(base.rglob('*.pdf')))
    return paths


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only OCR diagnostics for PortMan on Windows.')
    parser.add_argument('--pdf', action='append', default=[], metavar='PATH',
                        help='Realer Beleg für Rendering/OCR/Parserprüfung (mehrfach möglich).')
    parser.add_argument('--pdf-dir', action='append', default=[], metavar='DIR',
                        help='Verzeichnis mit realen Belegen (rekursiv, mehrfach möglich).')
    parser.add_argument('--json', action='store_true', help='Maschinenlesbare Ausgabe.')
    parser.add_argument('--skip-recognition', action='store_true',
                        help='Synthetischen OCR-Erkennungstest überspringen.')
    parser.add_argument('--strict', action='store_true', help='WARN als Fehler behandeln.')
    args = parser.parse_args(argv)

    pdfs = [Path(item) for item in args.pdf] + collect_pdfs(args.pdf_dir)
    # Keep the order but remove accidental duplicates.
    pdfs = list(dict.fromkeys(p.resolve() for p in pdfs))
    report = run_diagnostics(pdfs, run_recognition=not args.skip_recognition)
    print(report_json(report) if args.json else format_report(report))
    if report.status == 'FAIL' or (args.strict and report.status == 'WARN'):
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
