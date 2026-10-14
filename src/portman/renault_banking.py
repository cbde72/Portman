"""Read-only FinTS access to Renault Bank direkt (Germany)."""
from .ing_banking import create_client as create_fints_client, fetch_ing
from .ing_banking import BankingError as BankingError

ENDPOINT = 'https://fints2.atruvia.de/cgi-bin/hbciservlet'
BANK_CODE = '30520037'
BIC = 'RCIDDE3NPAY'
SOURCE = 'Online Renault Bank direkt'


def create_client(user, pin, product_id, cancelled):
    return create_fints_client(user, pin, product_id, cancelled,
        endpoint=ENDPOINT, bank_code=BANK_CODE, bank='Renault Bank direkt')


def fetch_renault(user, pin, product_id, *, source_root, challenge=None,
                  client_factory=create_client, **options):
    # Postbox/document support is not part of this bank adapter.
    options['fetch_documents'] = False
    return fetch_ing(user, pin, product_id, source_root=source_root,
        challenge=challenge, client_factory=client_factory, bank='Renault Bank direkt',
        bank_code=BANK_CODE, bank_bic=BIC, source_prefix='renault', **options)
