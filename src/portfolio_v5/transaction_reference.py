"""Stable references for persisted transactions.

References are deliberately byte-for-byte compatible with the historical
implementations in the repository, settlement and asset-registry layers.
"""
import json


def transaction_reference(transaction):
    """Return the persisted identity used by cross-table transaction links."""
    return json.dumps(
        [transaction['import_id'], transaction.get('depot', transaction['account']),
         transaction['external_id']],
        ensure_ascii=False,
        separators=(',', ':'),
    )
