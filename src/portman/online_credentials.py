"""Local API keys, encrypted for the current Windows user using DPAPI."""
import ctypes
import os
from ctypes import wintypes


def protect_windows(raw, decrypt=False):
    if os.name != 'nt':
        raise ValueError('Dauerhaftes Speichern ist hier nur unter Windows verfügbar. Sitzungsspeicherung verwenden.')
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError('Windows konnte den API-Schlüssel nicht entschlüsseln / speichern. Schlüssel bitte erneut eingeben.')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


class CredentialStore:
    def __init__(self, db, protector=protect_windows):
        self.db, self.protector = db, protector
        self.session = {}
        db.execute('CREATE TABLE IF NOT EXISTS online_credentials(provider TEXT PRIMARY KEY, encrypted BLOB NOT NULL)')
        db.commit()

    def has(self, provider):
        return bool(self.session.get(provider) or self.db.execute(
            'SELECT 1 FROM online_credentials WHERE provider=?', (provider,)).fetchone())

    def get(self, provider):
        if provider in self.session:
            return self.session[provider]
        row = self.db.execute('SELECT encrypted FROM online_credentials WHERE provider=?', (provider,)).fetchone()
        return self.protector(bytes(row[0]), decrypt=True).decode('utf-8') if row else ''

    def update(self, values, remove=(), persist=True):
        # Prepare all ciphertexts before changing any records.
        cleaned = {p: v.strip() for p, v in values.items() if v.strip()}
        if any(len(v) > 4096 or any(c.isspace() for c in v) for v in cleaned.values()):
            raise ValueError('API-Schlüssel darf keine Leerzeichen enthalten und maximal 4096 Zeichen lang sein.')
        encrypted = {p: self.protector(v.encode('utf-8')) for p, v in cleaned.items()} if persist else {}
        with self.db:
            for provider in set(remove) | set(cleaned):
                self.db.execute('DELETE FROM online_credentials WHERE provider=?', (provider,))
            for provider, cipher in encrypted.items():
                self.db.execute('INSERT INTO online_credentials VALUES(?,?)', (provider, cipher))
        for provider in set(remove) | set(cleaned):
            self.session.pop(provider, None)
        if not persist:
            self.session.update(cleaned)
