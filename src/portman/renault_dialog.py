from .baader_dialog import BaaderDialog, BaaderWorker, BaaderTANDialog
from .renault_banking import fetch_renault
from .renault_credentials import RenaultCredentialStore


class RenaultWorker(BaaderWorker):
    bank = 'Renault Bank direkt'

    def fetch_data(self, *args, **kwargs):
        return fetch_renault(*args, **kwargs)


class RenaultTANDialog(BaaderTANDialog):
    title = 'Renault Bank direkt · TAN-Freigabe'
    placeholder = 'TAN aus SecureGo+ eingeben'


class RenaultDialog(BaaderDialog):
    bank = 'Renault Bank direkt'
    user_label = 'Benutzerkennung / Alias'
    pin_label = 'Online-Banking-PIN'
    store_type = RenaultCredentialStore
    worker_type = RenaultWorker
    tan_dialog_type = RenaultTANDialog
    login_site = 'banking.renault-bank-direkt.de'
    user_hint = 'Verwende dieselbe Benutzerkennung oder denselben Alias wie im Renault-Online-Banking.'
    introduction = ('Salden und verfügbare gebuchte Kontoumsätze deiner Renault-Konten abrufen. '
                    'Verwende die Zugangsdaten des deutschen Renault-Online-Bankings. '
                    'Eine angeforderte TAN aus SecureGo+ wird in Portman eingegeben; '
                    'die Direktfreigabe in der App steht für Finanzsoftware laut Renault nicht zur Verfügung.\n\n'
                    'Tages- und Festgeldkonten werden berücksichtigt, soweit die Bank sie über FinTS '
                    'mit den nötigen Berechtigungen meldet. Nach dem Abruf die vorhandenen Konten '
                    'in der Importvorschau zuordnen. Das PDF-Postfach ist nicht Teil dieses Abrufs.')
