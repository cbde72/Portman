"""Streaming authenticated encryption for optional portable backup packages."""
import os
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.exceptions import InvalidTag
MAGIC=b'PORTMAN09\x00'
def key(password,salt):
    if len(password)<10: raise ValueError('Mindestens zehn Zeichen für das Paketpasswort verwenden.')
    return Scrypt(salt=salt,length=32,n=2**15,r=8,p=1).derive(password.encode('utf-8'))
def encrypt(source,destination,password):
    salt=os.urandom(16); iv=os.urandom(12); header=MAGIC+salt+iv
    cipher=Cipher(algorithms.AES(key(password,salt)),modes.GCM(iv)).encryptor(); cipher.authenticate_additional_data(header)
    destination=Path(destination); temporary=destination.with_name(destination.name+'.tmp')
    try:
        with Path(source).open('rb') as src,temporary.open('wb') as out:
            out.write(header)
            for block in iter(lambda:src.read(1024*1024),b''): out.write(cipher.update(block))
            out.write(cipher.finalize()); out.write(cipher.tag); out.flush(); os.fsync(out.fileno())
        os.replace(temporary,destination)
    finally: temporary.unlink(missing_ok=True)
def decrypt(source,destination,password):
    destination=Path(destination); temporary=destination.with_name(destination.name+'.tmp')
    try:
        with Path(source).open('rb') as src:
            header=src.read(len(MAGIC)+28)
            if len(header)!=len(MAGIC)+28 or not header.startswith(MAGIC): raise ValueError('Kein verschlüsseltes PortMan-09-Paket.')
            salt=header[len(MAGIC):len(MAGIC)+16]; iv=header[-12:]
            src.seek(-16,2); end=src.tell(); tag=src.read(16); src.seek(len(header))
            if end<len(header): raise ValueError('Paket unvollständig.')
            cipher=Cipher(algorithms.AES(key(password,salt)),modes.GCM(iv,tag)).decryptor(); cipher.authenticate_additional_data(header)
            with temporary.open('wb') as out:
                while src.tell()<end: out.write(cipher.update(src.read(min(1024*1024,end-src.tell()))))
                out.write(cipher.finalize()); out.flush(); os.fsync(out.fileno())
        os.replace(temporary,destination)
    except InvalidTag: raise ValueError('Passwort falsch oder Paket beschädigt.') from None
    finally: temporary.unlink(missing_ok=True)
