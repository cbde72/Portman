from decimal import Decimal

import pytest

from pdf_plugins._baader_core import parse_baader_portfolio
from portfolio_v5.models import ImportBatch, transaction_validation
from portman.repository_v09 import RepositoryV09


TEMPLATE = '''Baader Bank AG
Depot-Nr.: 3128164001
Vorgangs-Nr.: 26172813
Referenz-Nr.: {reference}
Dividendenabrechnung {storno}
Ex-Tag: 09.02.2024
Nominale ISIN: US0378331005 WKN: 865985 Ausschüttung
STK 4,125 Apple Inc.  USD 0,24 p.STK
Zahltag: 15.02.2024
Umrechnungskurs: EUR/USD 1,07733
Bruttobetrag EUR 0,92
US-Quellensteuer EUR 0,14 -
Zu Gunsten Konto 3128164005 Valuta: 15.02.2024 EUR 0,78
'''


def parse(reference, storno=''):
    batch = ImportBatch(reference + '.pdf', reference, source_sheet='PDF')
    return parse_baader_portfolio(
        batch, [TEMPLATE.format(reference=reference, storno=storno)], b'%PDF-test')


def test_verified_dividend_reversal_cancels_original_exactly(tmp_path):
    original = parse('524443206')
    reversal = parse('526758625', 'STORNO')
    first, second = original.transactions[0], reversal.transactions[0]

    assert (first.amount, first.gross_amount, first.taxes) == ('0.78', '0.92', '0.14')
    assert (second.amount, second.gross_amount, second.taxes) == ('-0.78', '-0.92', '-0.14')
    assert second.is_reversal is True
    assert second.reverses_external_id == first.external_id
    assert transaction_validation(first) == ([], [])
    assert transaction_validation(second) == ([], [])
    assert sum(Decimal(tx.amount) for tx in (first, second)) == 0
    assert sum(Decimal(tx.taxes) for tx in (first, second)) == 0

    original.documents = []
    reversal.documents = []
    repo = RepositoryV09(tmp_path / 'baader-reversal.sqlite', backups=False)
    try:
        assert [result['status'] for result in repo.commit_batches([original, reversal])] == [
            'imported', 'imported']
        assert repo.commit_batches([original, reversal])[0]['status'] == 'duplicate'
        rows = repo.transactions(account='Baader Depot 3128164001')
        assert sum(Decimal(row['amount']) for row in rows) == 0
    finally:
        repo.close()


def test_unverified_or_changed_dividend_reversal_stays_rejected():
    changed = TEMPLATE.format(reference='526758625', storno='STORNO').replace('STK 4,125', 'STK 4,126')
    with pytest.raises(ValueError, match='keinem vollständig geprüften Originalbeleg'):
        parse_baader_portfolio(ImportBatch('changed.pdf', 'changed'), [changed], b'%PDF-test')
