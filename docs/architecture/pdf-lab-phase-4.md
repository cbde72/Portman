# Portman PDF Lab – Phase-4-Architektur

Phase 4 retains the Phase-3 dependency direction: PDF Lab consumes only the
public `portman-parsers` API. `portman-parsers 0.5.0` has no Portman V09/V10,
GUI, Store, repository or database dependency.

## End-to-End flow

```text
local PDF → pypdf extraction → PdfDocument/PdfPage → deterministic registry
          → Bank of Scotland parser → ParsedDocument → shared validation
          → account/fee/link projections → JSON report
```

PDF bytes are never embedded in a parser result. OCR is not a required runtime
dependency; an empty text layer is reported as `OCR_REQUIRED`.

## Accounts, depots and cash

`AccountType` contains `GIRO`, `TAGESGELD`, `FESTGELD` and `OTHER`.
`AccountFunction` independently describes payment, savings, settlement,
dividend, fee and tax functions. A giro account may therefore be a settlement
account without creating an artificial account. `DepotType.WERTPAPIER` is
separate from account type.

`DepotAccountLink` contains role, validity interval and default status as
provenanced `FieldValue`s. Explicit transaction evidence has priority;
ambiguous, missing or conflicting assignments generate Issues.

Internal transfers use one transfer ID across evidenced movements. One known
side remains one movement with a review Issue; no counter-booking is invented.
For trade settlement, an ACTUAL movement supersedes an EXPECTED movement with
the same settlement identity.

## Bank of Scotland

The package-local parser supports the verified statement table shape for
Tagesgeld and, provisionally where explicitly labelled, Festgeld. It extracts
account identity, holder, IBAN/BIC, statement metadata, bookings, interest,
taxes, bank fees, refunds and opening/closing balances. Every extracted field
has document hash, page, excerpt, parser/handler/version and review state.

No real customer PDF was committed. Production layout approval remains pending
until anonymized, explicitly released reference documents are available.

## Advance tax and tax evidence

An extracted `TaxEvent` remains immutable source data. A separate
`AdvanceTaxCalculation` applies a sourced year/bank rule set and records its
results and differences without replacing source amounts. It models base
yield, appreciation cap, distributions, acquisition-month reduction, partial
exemption and separate allowance/loss offsets. Unknown inputs stay unknown.

The event itself is cash-neutral. An actual withholding is valid only when it
references a pre-existing, evidenced tax debit on the real account. The model
does not assume a settlement account and never creates one. Carryforwards for a
later fund sale are tax history only, not acquisitions or security movements.
Calculations lacking confirmed reference evidence are not professionally
approved. The comdirect, Baader and ING advance-tax handlers remain inactive.

