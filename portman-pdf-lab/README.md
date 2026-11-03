# portman-pdf-lab

Independent application for deterministic analysis of `portman-parsers`
results. Bank parsers and PDF extraction come from the separately installable
`portman-parsers` package. The desktop interface uses PySide6 and has no
Portman V09/V10 runtime dependency.

## Installation for development and VS Code

Select the intended Python environment in VS Code with **Python: Select
Interpreter**. In a terminal using that same environment, install both local
projects independently in editable mode:

```powershell
python -m pip install -e ".\portman-parsers[test]"
python -m pip install -e ".\portman-pdf-lab[test]"
```

Run these commands from the `PortmanNL` repository root. No V09/V10 source
directory is added to `PYTHONPATH`. Verify the selected interpreter with:

```powershell
python -c "import sys; print(sys.executable)"
python -c "import portman_parsers, portman_pdf_lab; print(portman_parsers.__file__); print(portman_pdf_lab.__file__)"
```

The package constrains PySide6 to the tested range `>=6.9.2,<6.11.2`.
PySide6 6.11.1 supports the current Python 3.14 environment and its Qt PDF
selection API; 6.11.3 remains excluded because it failed to load `QtWidgets`
in the isolated Windows acceptance environment.

## Commands

The package module delegates to `cli.main`. The definitive GUI module command
is therefore:

```powershell
python -m portman_pdf_lab gui
```

The installed console entry points are equivalent:

```powershell
portman-pdf-lab gui
portman-pdf-lab-gui
```

Other available commands are:

```powershell
portman-pdf-lab demo
portman-pdf-lab create-demo-pdf demo.pdf
portman-pdf-lab analyze demo.pdf --output report.json
portman-pdf-lab batch ./statements --output batch.json
```

The `demo` command uses synthetic data only and prints deterministic JSON.
`analyze` processes one local PDF; `batch` processes PDFs recursively and does
not abort when one file is unreadable. Reports include parser selection,
accounts, balances, events, fees, Evidence, Issues and per-stage timings.

## Start with F5 in VS Code

Open the repository root in VS Code, select the environment in which both
editable packages were installed, and press **F5**. The first launch
configuration, `Portman PDF Lab – GUI (F5)`, starts
`python -m portman_pdf_lab gui` with the active VS-Code interpreter. It does
not inject a source-tree `PYTHONPATH` and does not start Portman V09.

Version `0.6.0` provides side-by-side PDF/result inspection, background batch
processing, SQLite-backed immutable parser runs, reviewed reference values,
parser comparisons and ten tabs (the original nine analysis tabs plus local
parser training):

The PDF pane also exposes a synchronized selectable text layer. Its context
menu maps selections to catalog-defined fields, creates review annotations or
explicit references, and can define optional `attributes.user_fields` entries.
Versioned YAML field catalogs drive field types, validation, editors and F1
help. A missing PDF text layer is reported explicitly; OCR is not simulated.

The main toolbar switches between **Schnell** (the persisted default for a new
installation) and **Experte**. Quick mode presents only the catalog-driven
field analysis and guided PDF training actions. Expert mode restores all tabs,
technical paths, Evidence, comparisons, Golden tests, rule/profile lifecycle,
import/export and rollback. Switching modes never starts a parser run and both
modes use the same SQLite repository, YAML catalogs and approved profiles.

Quick training stays beside the PDF and field analysis in a collapsible
splitter panel. Selecting `Feld trainieren` preloads all technical context; the
user only marks PDF text, confirms or corrects the typed value, then explicitly
tests, approves and activates the rule in separate steps. `Erneut prüfen` runs
EXTENDED and compares the original value, effective value and reference without
leaving quick mode. An annotation or reference alone never turns a parser row
green.

Direct selection on the rendered PDF page uses Qt PDF coordinates and stores
real PDF-point quads, page dimensions, rotation, document hash and character
indices. The synchronized text layer remains available as a fallback for
difficult PDFs.

1. Übersicht
2. Konto
3. Depot
4. Buchungen
5. Geldflüsse
6. Gebühren & Kosten
7. Steuern
8. Referenzvergleich
9. Issues
10. Parsertraining

## Local parser training

After analyzing a PDF, open **Parsertraining**. Select a field, mark its
Evidence text (or use the displayed excerpt when PDF coordinates are not
available), enter the confirmed reference value and save the annotation. A
Golden case becomes approved only through the explicit confirmation action.

Rule suggestions are declarative, versioned and local. They are tested against
confirmed annotations before approval. A candidate with a regression or a
critical cashflow difference cannot be approved. Approval creates a
reproducible rule-profile version; rollback creates a new version from the
previous profile instead of changing parser source code. No PDF content is
sent to an external service.

The rule mode selector controls future imports:

- `STANDARD`: only the existing parser; this is the default.
- `EXTENDED`: parser plus the uniquely active compatible YAML profile.
- `COMPARE`: independent STANDARD and EXTENDED results without changing stored
  parser data.

Profile approval and activation are separate actions. Approved profiles are
stored in the PDF-Lab application-data directory rather than `site-packages`.
They can be exported as YAML and loaded through the public
`portman_parsers.rules` API without PDF Lab or its SQLite database.

Private PDFs are referenced by path and hash; they are never copied into the
source repository by the application.

