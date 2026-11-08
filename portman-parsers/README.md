# portman-parsers

`portman-parsers` is the independent, versioned parser core for Portman. It
contains immutable DTOs, deterministic plugin selection, evidence tracking and
bank-independent financial validation. It has no dependency on Portman V09,
PDF Lab, GUI frameworks or persistence code.

## Version 0.7.1

Version `0.7.1` adds a separate legacy parser path for historical comdirect
Finanzreports whose account tables contain account numbers instead of IBANs.
It supports both split and compacted PDF text layouts while leaving the parser
path for newer IBAN-based reports unchanged. API and serialized result schema
contracts are unchanged from version `0.7.0`.

## Version 0.7.0

Version `0.7.0` packages the parser functionality developed through commit
`bdc8eb82ea2bd68a760f62716546e898a30023a6`. The public DTO/API contract remains
`0.6` and the serialized result schema remains `1.6.0`; this release adds and
hardens parser implementations without changing those contracts.

The fixed allowlist contains 42 handlers. The following 35 handlers are
executable:

- comdirect: nine security/tax document handlers, the Finanzreport handler and
  nine Portfolio Performance-informed handlers;
- Baader: quarterly and annual depot statements, dividends, advance tax,
  depot transfers and security settlements;
- ING: dividends, purchases, sales, advance tax, tax settlement and annual
  depot statements;
- Deka: quarterly reports and annual depot statements through the combined
  `quartalsbericht` handler;
- FNZ/finvesto: turnover statements and depot statements;
- Bank of Scotland: account statements.

Executable means that a concrete parser is registered and covered by package
tests. It is not a blanket guarantee for every historical layout. Parsers keep
unknown values explicit, validate evidence and reconciliation where supported,
and return issues or reject unsafe input rather than inventing values. Renault's
six handlers and the generic account-statement handler remain metadata-only.
`pbb_direkt` and `baader_krypto` remain explicitly blocked.

Notable 0.7.0 changes include executable Baader, ING and Deka plugins, stricter
FNZ evidence and tax handling, and comdirect improvements for security identity,
quantities, fees, damaged-font documents and historical Finanzreports. Baader
layout extraction uses `pypdf` layout mode and may use the optional PDFium
fallback for damaged text. The synthetic fallback test is covered; validation
with authorized real damaged Baader PDFs remains outstanding.

Positive cash amounts are inflows and negative amounts are outflows. Tax and
cost amounts are unsigned components and have no cash effect unless they
explicitly reference a `CashMovement`. Holdings snapshots never create
synthetic security transactions, and unknown settlement accounts remain
unknown. MiFID disclosures remain cash-neutral.

## Dependencies and tests

PDF text extraction uses `pypdf>=6,<7`. Rule profiles use `PyYAML>=6,<7`.
`pypdfium2>=4,<6` is an optional extra for fallback extraction; no OCR engine is
a mandatory runtime dependency.

```powershell
python -m pip install -e ".[test]"
python -m pytest
```

## Optional rule profiles

The optional profile API does not change the normal registry or parser
implementations:

```python
from portman_parsers.rules import ProfileStore, RuleEngine, RuleMode

standard_result = registry.parse(document, detection)
store = ProfileStore()
profile = store.active(detection.plugin_id, detection.handler_id,
                       detection.document_type, "annotated",
                       detection.plugin_version)
extended = RuleEngine().apply(standard_result, document.text, profile,
                              RuleMode.EXTENDED)
```

`STANDARD` returns the original immutable parser result. `EXTENDED` produces
explicit field decisions alongside that result and never silently mutates the
public DTOs. Profiles are validated YAML with a SHA-256 hash, known rule types,
known merge strategies and bounded regular expressions.
