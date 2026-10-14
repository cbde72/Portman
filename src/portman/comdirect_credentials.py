"""Bank-specific namespace in the existing Windows Credential Manager store."""
from .ing_credentials import INGCredentialStore, CredentialError  # noqa: F401 - CredentialError re-exported for callers


class ComdirectCredentialStore(INGCredentialStore):
    bank = 'comdirect'
    fields = ('user', 'pin', 'client_id', 'client_secret')

    def save(self, user, pin, client_id, client_secret):
        self.save_values(dict(user=user.strip(), pin=pin, client_id=client_id.strip(),
                              client_secret=client_secret.strip()))
