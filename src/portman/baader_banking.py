"""Read-only Baader FinTS access for ZERO and other Baader-held depots."""
from .ing_banking import BankingError, Cancelled, create_client as create_fints_client, fetch_ing  # noqa: F401 - BankingError/Cancelled re-exported for callers

ENDPOINT = 'https://fints.baaderbank.de/'
BANK_CODE = '70033100'
BIC = 'BDWBDEMMXXX'
SOURCE = 'Online Baader'


def create_client(user, pin, product_id, cancelled):
    return create_fints_client(user, pin, product_id, cancelled,
        endpoint=ENDPOINT, bank_code=BANK_CODE, bank='Baader')


def fetch_baader(user, pin, product_id, *, source_root, challenge=None,
                 client_factory=create_client, **options):
    return fetch_ing(user, pin, product_id, source_root=source_root, challenge=challenge,
        client_factory=client_factory, bank='Baader', bank_code=BANK_CODE,
        source_prefix='baader', prefer_upd_accounts=True, bank_bic=BIC, **options)
