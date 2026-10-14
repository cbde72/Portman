"""Prepare Portman's project environment directly from VS Code, without a batch file."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CHECK = (
    'import PySide6,pandas,numpy,matplotlib,openpyxl,xlrd,odf,pypdf,pymupdf,requests; '
    'from fints.client import FinTS3PinTanClient; '
    'from importlib.metadata import version; '
    'assert version("fints") == "5.0.0", "Portman benötigt fints 5.0.0"'
)


def prepare(root=ROOT):
    python = root / '.venv' / 'Scripts' / 'python.exe'
    if not python.is_file():
        print('Portman: Projektumgebung wird erstellt.', flush=True)
        subprocess.run([sys.executable, '-m', 'venv', '--system-site-packages', str(root / '.venv')], check=True)
    result = subprocess.run([str(python), '-c', CHECK], capture_output=True, text=True)
    if result.returncode:
        print('Portman: Fehlende Abhängigkeiten werden in .venv installiert.', flush=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(root / 'requirements.txt')], check=True)
        subprocess.run([str(python), '-c', CHECK], check=True)
    print(f'Portman: Python-Umgebung bereit ({python}).', flush=True)


if __name__ == '__main__':
    prepare()
