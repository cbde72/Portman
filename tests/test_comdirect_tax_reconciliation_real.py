"""Opt-in regression against the user's unchanged comdirect 2026 export."""
from decimal import Decimal
from pathlib import Path

import pytest

from portfolio_v5.comdirect_tax_detail import parse_comdirect_tax_detail
from portman.repository_v09 import RepositoryV09
from portman.tax_overview import automatic_tax_values


REAL_EXPORT = Path(
    r'C:\Users\chris\Desktop\history\comdirect\steuerlichedetailansichtexport_1024764924_20261023-0845 (1).csv')


@pytest.mark.skipif(not REAL_EXPORT.exists(), reason='private comdirect reference export is not available')
def test_real_2026_tax_export_is_lossless_and_authoritative(tmp_path):
    repo = RepositoryV09(tmp_path / 'reference.sqlite', backups=False)
    try:
        repo.save_account('Depot 4764924', {'kind': 'Depot', 'institution': 'comdirect'})
        batch = parse_comdirect_tax_detail(REAL_EXPORT, account='Depot 4764924')
        assert len(batch.tax_details) == 39
        assert batch.transactions == [] and batch.tax_events == []
        assert repo.commit_batches([batch])[0]['status'] == 'imported'

        rows = repo.tax_detail_records(tax_year=2026)
        assert len(rows) == 39
        values = automatic_tax_values(repo, 2026)['depot 4764924']
        assert values['capital_income'] == Decimal('523.07')
        assert values['used_exemption'] == Decimal('411.00')
        assert values['taxable_after_fsa'] == Decimal('112.07')
        assert values['taxes'] == Decimal('29.53')
        assert values['advance_tax_taxable'] == Decimal('192.24')
        assert values['advance_tax_count'] == 3

        before = (len(repo.transactions()), len(repo.tax_events()), len(rows))
        assert repo.commit_batches([parse_comdirect_tax_detail(
            REAL_EXPORT, account='Depot 4764924')])[0]['status'] == 'duplicate'
        assert before == (len(repo.transactions()), len(repo.tax_events()),
                          len(repo.tax_detail_records(tax_year=2026)))
    finally:
        repo.close()
