"""Optional real-document OCR integration test (read-only).

Run explicitly after downloading the private comdirect documents:
    $env:PORTMAN_REAL_OCR='1'
    $env:PORTMAN_COMDIRECT_PDF_DIR='C:\\Users\\...\\history\\comdirect\\2026'
    .venv\\Scripts\\python.exe -m pytest tests/test_ocr_windows_real_pdfs.py -q
"""
import os
from decimal import Decimal
from pathlib import Path

import pytest

from portfolio_v5.models import valid_isin
from portfolio_v5.pdf_importer import parse_pdf

CASES = {
    'LS9AVX': 'DE000LS9AVX3',
    'A2H57N': 'LU1681041973',
    'LYX05A': 'LU2090063673',
}


def document_dir():
    configured = os.environ.get('PORTMAN_COMDIRECT_PDF_DIR')
    if configured:
        return Path(configured)
    return Path.home() / 'Desktop' / 'history' / 'comdirect' / '2026'


@pytest.mark.skipif(os.environ.get('PORTMAN_REAL_OCR') != '1',
                    reason='Optional real comdirect OCR integration test')
@pytest.mark.parametrize('wkn, isin', CASES.items())
def test_problematic_comdirect_family_parses_with_ocr(wkn, isin):
    base = document_dir()
    candidates = sorted(base.rglob(f'*Wertpapierabrechnung*{wkn}*.pdf'))
    if not candidates:
        pytest.skip(f'Keine realen Belege für {wkn} unter {base}')
    batch = parse_pdf(candidates[0])
    assert not batch.errors, batch.errors
    assert len(batch.transactions) == 1, batch.warnings
    tx = batch.transactions[0]
    assert tx.security == isin
    assert valid_isin(tx.security)
    quantity, price = Decimal(tx.quantity), Decimal(tx.price)
    assert quantity > 0 and price > 0
    assert abs(quantity * price - Decimal(tx.gross_amount)) <= Decimal('0.02')
    assert Decimal(tx.amount) < 0
    assert any('OCR' in warning for warning in batch.warnings)
    assert any(evidence.get('ocr') for evidence in batch.pdf_booking_evidence)
