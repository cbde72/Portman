"""ING login bundle in Windows Credential Manager, scoped to this Portman folder."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path


class CredentialError(ValueError):
    pass


class Credential(ctypes.Structure):
    _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
        ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
        ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
        ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)), ('Persist', wintypes.DWORD),
        ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
        ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]


class INGCredentialStore:
    bank = 'ING'
    fields = ('user', 'pin', 'product_id')

    def __init__(self, source_root):
        scope = hashlib.sha256(str(Path(source_root).resolve()).casefold().encode('utf-8')).hexdigest()[:24]
        self.target = f'Portman/{self.bank}/' + scope

    @staticmethod
    def api():
        if os.name != 'nt':
            raise CredentialError('Das Speichern der Bankzugangsdaten benötigt den Windows-Anmeldeinformationsspeicher.')
        api = ctypes.WinDLL('advapi32', use_last_error=True)
        api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
        api.CredReadW.restype = wintypes.BOOL
        api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
        api.CredWriteW.restype = wintypes.BOOL
        api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        api.CredDeleteW.restype = wintypes.BOOL
        api.CredFree.argtypes = [ctypes.c_void_p]
        api.CredFree.restype = None
        return api

    def load(self):
        api = self.api()
        pointer = ctypes.POINTER(Credential)()
        if not api.CredReadW(self.target, 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:  # ERROR_NOT_FOUND
                return {}
            raise CredentialError(f'Windows konnte die gespeicherten {self.bank}-Zugangsdaten nicht lesen.')
        try:
            raw = ctypes.string_at(pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize)
            values = json.loads(raw.decode('utf-8'))
            if not isinstance(values, dict) or not all(isinstance(values.get(key), str) for key in self.fields):
                raise ValueError
            return {key: values[key] for key in self.fields}
        except (ValueError, UnicodeError):
            raise CredentialError(f'Die gespeicherten {self.bank}-Zugangsdaten sind ungültig. Bitte neu eingeben und speichern.') from None
        finally:
            api.CredFree(pointer)

    def save(self, user, pin, product_id):
        values = dict(user=user.strip(), pin=pin, product_id=product_id.strip())
        if not all(values.values()):
            raise CredentialError('Bitte Benutzername, PIN/Passwort und FinTS-Produkt-ID vollständig eingeben.')
        self.save_values(values)

    def save_values(self, values):
        if set(values) != set(self.fields) or not all(isinstance(v, str) and v for v in values.values()):
            raise CredentialError('Bitte alle Zugangsdaten vollständig eingeben.')
        raw = json.dumps(values, ensure_ascii=False).encode('utf-8')
        if len(raw) > 2560:
            raise CredentialError('Die Zugangsdaten sind zu lang für den Windows-Anmeldeinformationsspeicher.')
        api = self.api()
        buffer = ctypes.create_string_buffer(raw)
        credential = Credential()
        credential.Type = 1  # CRED_TYPE_GENERIC
        credential.TargetName = self.target
        credential.Comment = f'Portman {self.bank}: Bankzugang'
        credential.UserName = f'Portman {self.bank}'
        credential.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE: same Windows user, survives logoff
        credential.CredentialBlobSize = len(raw)
        credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        try:
            if not api.CredWriteW(ctypes.byref(credential), 0):
                raise CredentialError(f'Windows konnte die {self.bank}-Zugangsdaten nicht speichern. Es wurde kein Bankabruf gestartet.')
        finally:
            ctypes.memset(buffer, 0, len(raw))

    def delete(self):
        api = self.api()
        if not api.CredDeleteW(self.target, 1, 0) and ctypes.get_last_error() != 1168:
            raise CredentialError(f'Windows konnte die gespeicherten {self.bank}-Zugangsdaten nicht löschen.')
