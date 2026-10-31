from datetime import date

from portman_pdf_lab.analysis import fee_cost_view
from portman_pdf_lab.demo import synthetic_purchase


def test_fee_cost_view_prepares_future_tab_sections():
    view = fee_cost_view(synthetic_purchase())
    assert len(view["fees"]) == 1
    assert len(view["booked_fees"]) == 1
    assert view["informational_fees"] == []
    assert view["fees_per_transaction"][0]["amount"] == "2.00"
    assert view["bank_comparison"][0]["dimensions"][0] == ["bank_id", "synthetic-bank"]
    assert view["document_evidence"]["fee-demo"][0]["page_number"] == 1


def test_fee_cost_view_filters_bank_depot_account_and_period():
    result = synthetic_purchase()
    assert fee_cost_view(result, bank_id="other")["fees"] == []
    assert fee_cost_view(result, depot_id="other")["fees"] == []
    assert fee_cost_view(result, account_id="other")["fees"] == []
    assert fee_cost_view(result, date_from=date(2026, 10, 31))["fees"] == []
    assert len(fee_cost_view(result, bank_id="synthetic-bank", depot_id="depot-demo",
                             account_id="account-demo", date_to=date(2026, 10, 30))["fees"]) == 1

