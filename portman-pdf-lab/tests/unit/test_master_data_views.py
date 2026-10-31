from portman_pdf_lab.analysis import account_view, depot_account_link_view, depot_view
from portman_pdf_lab.demo import synthetic_purchase


def test_depot_view_contains_snapshot_and_multiple_accounts():
    view = depot_view(synthetic_purchase())
    assert len(view) == 1
    assert view[0]["depot"]["depot_id"] == "depot-demo"
    assert len(view[0]["snapshots"]) == 1
    assert view[0]["linked_account_ids"] == ["account-demo", "account-tax-demo"]


def test_account_view_contains_balance_and_depot_relationship():
    view = account_view(synthetic_purchase())
    primary = next(item for item in view if item["account"]["account_id"] == "account-demo")
    assert primary["balances"][0]["amount"]["value"] == "1000.00"
    assert primary["linked_depot_ids"] == ["depot-demo"]


def test_link_view_exposes_field_provenance():
    view = depot_account_link_view(synthetic_purchase())
    assert len(view) == 2
    assert view[0]["link"]["role"]["source"] == "PDF"
    assert view[0]["link"]["role"]["page_number"] == 1
    assert view[0]["link"]["role"]["evidence_ids"] == ["ev-link"]

