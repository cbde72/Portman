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

The package intentionally constrains PySide6 to the tested 6.8/6.9 series.
On the current Windows/Python environment PySide6 6.9.2 loads successfully;
6.11.3 fails while loading `QtWidgets` before PDF Lab code is executed.

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

