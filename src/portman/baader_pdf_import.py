"""Discover Baader archive PDFs for the shared account-assignment import flow."""
import os
from pathlib import Path


def baader_pdf_files(folder):
    root = Path(folder)
    if not root.is_dir():
        raise ValueError('Der Baader-Ordner wurde nicht gefunden.')

    def unreadable(error):
        raise ValueError(f'Unterordner konnte nicht gelesen werden: {error.filename}') from error

    paths = []
    for current, directories, files in os.walk(root, followlinks=False, onerror=unreadable):
        directories.sort(key=str.casefold)
        for name in files:
            path = Path(current) / name
            if path.suffix.casefold() == '.pdf' and path.is_file() and not path.is_symlink():
                paths.append(path)
    return sorted(paths, key=lambda path: str(path.relative_to(root)).casefold())
