# portman-pdf-lab

Minimal Phase-3 application shell for deterministic analysis of
`portman-parsers` results. This project deliberately contains no bank parser,
PDF engine, OCR engine, GUI framework or Portman V09 dependency.

Install `portman-parsers` first, then this project:

```powershell
python -m pip install -e ../portman-parsers
python -m pip install -e ".[test]"
portman-pdf-lab demo
portman-pdf-lab create-demo-pdf demo.pdf
portman-pdf-lab analyze demo.pdf --output report.json
portman-pdf-lab batch ./statements --output batch.json
```

The `demo` command uses synthetic data only and prints deterministic JSON.
`analyze` processes one local PDF; `batch` processes PDFs recursively and does
not abort when one file is unreadable. Reports include parser selection,
accounts, balances, events, fees, Evidence, Issues and per-stage timings.

# Portman PDF Lab

Version `0.6.0` is an independent PySide6 desktop application for local PDF
analysis. It provides side-by-side PDF/result inspection, FNZ and Bank of
Scotland analysis, background batch processing, SQLite-backed immutable parser
runs, separately reviewed reference values and version comparisons.

Start it with:

```powershell
portman-pdf-lab gui
# or
portman-pdf-lab-gui
```

Private PDFs are referenced by path and hash; they are never copied into the
source repository by the application.

