# Portman PDF Lab – Phase-5-Architektur

```text
PDF → portman-parsers (extract/detect/parse/validate)
    → immutable result
    → portman-pdf-lab SQLite repository
    → PDF/result UI, review, references, comparisons and export
```

`portman-parsers 0.6.0` has no dependency on PDF Lab, Qt, Portman V09/V10,
stores or databases. PDF Lab depends only on the public parser API, PySide6 and
the Python standard-library SQLite driver.

FNZ turnover produces economic events and an optional partial snapshot. A
documented settlement without an identified account is `EXPECTED`; it is not
an actual account booking. A dividend and its reinvestment are separate linked
economic effects whose expected cash effects cancel. A depot statement creates
only a `DepotSnapshot`.

SQLite schema version 1 separates documents, immutable parser runs, confirmed
reference values, reference history and review history. Transactions use
`BEGIN IMMEDIATE`, foreign keys and WAL. Parser runs cannot overwrite reference
values. PDFs stay outside the database and repository; only controlled file
references and SHA-256 identities are stored.

The PySide6 main window has resizable document, PDF and analysis panes. Parsing
runs outside the GUI thread. Evidence selects the real PDF page and displays
the excerpt; no coordinates are synthesized.
