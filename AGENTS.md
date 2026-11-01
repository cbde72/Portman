# AGENTS.md

## Aktives Projekt

Das aktive Projekt ist dieses Repository (`PortmanNL`). Änderungen, Starts und
Tests hier ausführen. Das benachbarte Verzeichnis `portman` ist veraltet und darf
nicht mehr als Arbeitsprojekt verwendet werden. Antworten auf Deutsch.

## Repo-Struktur (drei unabhängige Pakete in einem Repo)

- **Haupt-App** in `src/` — PySide6-Desktopanwendung zur Depot-/Vermögensverwaltung.
  - Einstiegspunkt: `src/Gui/PortMan_V09.py` (kein `python -m`-Modul).
  - Pakete: `portman/` (GUI + Fachlogik), `portfolio_v5/` (Modelle/Speicher),
    `Gui/` (Top-Level-Modul `Gui.PortMan_V09`).
  - Start per `start_v09.bat` → `tools/prepare_environment.py` erstellt `.venv`
    (`--system-site-packages`), installiert `requirements.txt` und prüft
    `fints==5.0.0` (exakt).
- **`portman-parsers/`** — unabhängiger Parser-Kern (DTOs, Plugin-Auswahl,
  Validierung). Keine Abhängigkeit auf V09, GUI, OCR oder Persistenz.
- **`portman-pdf-lab/`** — eigenständige GUI + CLI für `portman-parsers`
  (PySide6). CLI: `python -m portman_pdf_lab gui`, `batch ORDNER --csv …`.
  `batch` exportiert optional lesend Trainingsdaten per `--training-database`.

Alle drei sind editable installiert (`pip install -e`). Editiere **nur `src/`**;
`portman-pdf-lab/build/` ist ein veralteter, nicht versionierter Build-Artefakt.

## Tests (drei getrennte Suiten)

- **Haupt-Suite:** `tests/` im Repo-Root. `pytest.ini` setzt `pythonpath = src`
  und `testpaths = tests` → `python -m pytest tests/…` aus dem Repo-Root.
- **`portman-pdf-lab/tests/`** und **`portman-parsers/tests/`**: eigene
  `pyproject.toml`-Konfiguration (`testpaths = ["tests"]`), jeweils aus dem
  Paketverzeichnis ausführen.

### Windows: pytest-Basetemp ist gesperrt

Der Default-Basetemp `C:\Users\<user>\AppData\Local\Temp\pytest-of-<user>` ist
hier gesperrt und löst `PermissionError: [WinError 5]` aus. Immer mit eigenem
Basetemp laufen lassen:

```powershell
python -m pytest tests/test_foo.py -p no:cacheprovider --basetemp="C:\Users\chris\AppData\Local\Temp\opencode\pt"
```

(alternativ beliebiges schreibbares Verzeichnis; ohne `--basetemp` schlagen
Setup/Teardown vieler Tests fehl).

## Lint

`ruff` über `pyproject.toml`: `target-version = "py313"`, `line-length = 160`,
nur Regel `F` (pyflakes). Ausführen mit `python -m ruff check <Pfade>`.

## Datenschutz (wichtig)

- Laufzeitdaten liegen in `data/`, `logs/`, `history/`, `factsheets/` und sind
  gitignoriert (echte Portfolios, SQLite, Backups, Sessions).
- `*.portman.json`-Exporte enthalten echte Namen/Kontonummern → niemals committen.
- Tests und Tools dürfen keine echten Kontodaten in `test_reports/` schreiben
  (Repo ist öffentlich).

## Konventionen / Fallstricke

- Code, Kommentare und UI-Texte sind Deutsch; auch Meldungen an Nutzer Deutsch.
- Repository-Zugriff über `RepositoryV09` (bzw. `PortfolioRepository` in
  `portfolio_v5`). Import-/Chart-Logik ist stark modular (z. B. `chart_*.py`,
  `import_v09.py`); Änderungen dort über die gezielten Tests absichern.
- `charts`-Konfiguration (`custom_charts.json`) liegt neben der Datenbank und wird
  über `chart_config.py`/`chart_config_dialog.py` verwaltet.
- `.continue/`, `pytest-*.txt`, `tmp/`, `tools/*.pdf|*.zip` sind Scratch — nicht
  als Quellcode behandeln.
