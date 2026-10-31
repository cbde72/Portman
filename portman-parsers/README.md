# portman-parsers

`portman-parsers` is the independent, versioned parser core for Portman PDF Lab.
It contains DTOs, deterministic plugin selection and bank-independent financial
validation. It intentionally has no dependency on Portman V09, PDF engines,
OCR packages, GUI frameworks or persistence code.

Version `0.6.0` provides the Phase-5 public contract and executable Bank of Scotland
and FNZ/finvesto parsers. The FNZ handlers cover turnover statements and depot
statements; snapshots never create synthetic security transactions and unknown
settlement accounts remain unknown.

The earlier `0.5.0` contract introduced the consolidated Phase-4 public contract, the first executable bank
parser and metadata placeholders
for all 33 approved handlers. Bank-specific parsing is deliberately not yet
implemented. Positive cash amounts are inflows and negative amounts are
outflows. Tax and cost amounts are unsigned components and have no cash effect
unless they explicitly reference a `CashMovement`.

The advance-tax contract separates immutable extracted values from sourced
calculations, tax carryforwards and evidenced account debits. It validates
partial exemptions, distributions, appreciation caps, intra-year purchases,
allowances and loss offsets without guessing missing data. An advance-tax event
never creates cash or security movements by itself.

Depot and account master data are modeled independently from balances,
holdings snapshots, transactions and economic events. Every extracted field is
represented by a `FieldValue` containing origin, PDF page, Evidence references
and review status; missing properties remain explicitly unknown.

The cross-bank fee model distinguishes booked, settlement-included,
informational, estimated, refunded and reversed costs. It deduplicates economic
fee positions, keeps MiFID disclosures cash-neutral and aggregates currencies
separately unless a documented conversion is supplied by a future adapter.

PDF text extraction uses `pypdf>=6,<7`. It is pure Python, preserves page order,
supports encrypted-file detection and can flag pages without a text layer for
optional OCR. Bank of Scotland is the first executable parser; all remaining
approved handlers stay explicit metadata-only placeholders.

```powershell
python -m pip install -e ".[test]"
python -m pytest
```

