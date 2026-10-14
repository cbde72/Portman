"""Keep direct editor launches on the same environment and working directory."""
from pathlib import Path
from logging.handlers import RotatingFileHandler
import logging
import os
import subprocess
import sys


def setup_logging(log_folder=None):
    root = logging.getLogger()
    if any(hasattr(handler, 'baseFilename') for handler in root.handlers):
        return
    root.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s %(levelname)s [%(name)s] %(message)s', '%Y-%m-%d %H:%M:%S')
    if sys.stderr is not None:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)
    folder = Path(log_folder) if log_folder else (Path(__file__).resolve().parents[2] / 'logs')
    folder.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(folder / 'portman.log', maxBytes=1_000_000, backupCount=3, encoding='utf-8')
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def use_project_python(entrypoint, arguments=None):
    entrypoint = Path(entrypoint).resolve()
    root = entrypoint.parents[2]
    python = root / '.venv' / 'Scripts' / 'python.exe'
    if Path(sys.executable).resolve() == python.resolve():
        os.chdir(entrypoint.parent)
        return
    print('Portman verwendet die Python-Umgebung des Projekts.', flush=True)
    subprocess.run([sys.executable, str(root / 'tools' / 'prepare_environment.py')], check=True)
    result = subprocess.run([str(python), str(entrypoint), *(sys.argv[1:] if arguments is None else arguments)],
                            cwd=entrypoint.parent)
    raise SystemExit(result.returncode)
