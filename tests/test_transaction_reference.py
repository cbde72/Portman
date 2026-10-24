import pytest

from portfolio_v5.transaction_reference import transaction_reference
from portman.asset_registry import transaction_ref
from portman.repository_v09 import reference


@pytest.mark.parametrize('factory', [transaction_reference, transaction_ref, reference])
def test_transaction_reference_preserves_historical_serialization(factory):
    transaction = {
        'import_id': 7,
        'account': '  Giro Ä  ',
        'depot': 'Depot ß',
        'external_id': ' Ref / 01 ',
    }
    assert factory(transaction) == '[7,"Depot ß"," Ref / 01 "]'


def test_transaction_reference_only_falls_back_when_depot_key_is_absent():
    assert transaction_reference({'import_id': 1, 'account': 'Cash', 'external_id': 'x'}) == '[1,"Cash","x"]'
    assert transaction_reference({'import_id': 1, 'account': 'Cash', 'depot': '', 'external_id': 'x'}) == '[1,"","x"]'


def test_transaction_reference_keeps_historical_required_keys():
    with pytest.raises(KeyError):
        transaction_reference({'import_id': 1, 'depot': 'Depot', 'external_id': 'x'})
