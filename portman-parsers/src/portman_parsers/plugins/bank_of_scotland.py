"""Independent Bank of Scotland Tagesgeld/Festgeld statement parser."""

from datetime import datetime
from decimal import Decimal
from itertools import product
import re

from portman_parsers.api import (
    Account, AccountBalance, AccountFunction, AccountType, CashMovement, CashMovementType,
    CashStatus, Detection, Evidence, FeeEffect, FeeEvent, FieldValue, FinancialEvent,
    Issue, IssueNature, IssueSeverity, ParsedDocument, PdfDocument, ReviewStatus,
    TaxComponent, TaxEvent,
)
from portman_parsers.registry.allowlist import APPROVED_PLUGINS
from portman_parsers.utilities import stable_id


DATE = r"\d{2}\.\d{2}\.\d{4}"
AMOUNT = r"(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}"
HEADER = re.compile(r"Buchungstag\s+Wertstellung\s+Beschreibung\s+(?:Soll|Belastungen)\s+(?:Haben|Gutschriften)", re.I)
ROW = re.compile(rf"^\s*(?P<booked>{DATE})\s+(?P<value>{DATE})\s+(?P<body>.*?)\s+(?P<amount>{AMOUNT})\s*$")
OLD = re.compile(rf"Alter\s+Saldo:\s*(?P<value>-?{AMOUNT})", re.I)
NEW = re.compile(rf"Neuer\s+Saldo:\s*(?P<value>-?{AMOUNT})", re.I)
STATEMENT_DATE = re.compile(rf"Datum:\s*(?P<value>{DATE})", re.I)
IBAN = re.compile(r"IBAN:\s*(?P<value>DE(?:\s*\d){20})", re.I)
ACCOUNT_NO = re.compile(r"Kontonummer:\s*(?P<value>\d+)", re.I)
BIC = re.compile(r"BIC:\s*(?P<value>[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)", re.I)
HOLDER = re.compile(r"Kontoinhaber(?:in)?:\s*(?P<value>[^\n]+)", re.I)
STATEMENT_NO = re.compile(r"Auszugsnummer:\s*(?P<value>\S+)", re.I)


class BankOfScotlandParseError(ValueError):
    pass


def _date(value: str):
    return datetime.strptime(value, "%d.%m.%Y").date()


def _money(value: str) -> Decimal:
    return Decimal(value.replace(".", "").replace(",", "."))


def _field(value, page, evidence):
    return FieldValue.from_pdf(value, page, evidence, review_status=ReviewStatus.UNREVIEWED)


class BankOfScotlandPlugin:
    metadata = next(item for item in APPROVED_PLUGINS
                    if item.plugin_id == "user.bank-of-scotland-kontoauszug")

    def detect(self, document: PdfDocument) -> tuple[Detection, ...]:
        text = document.text
        if re.search(r"Bank of Scotland|Lloyds Bank GmbH", text, re.I) and HEADER.search(text) \
                and re.search(r"RECHNUNGSABSCHLUSS", text, re.I):
            return (Detection(self.metadata.plugin_id, self.metadata.version, "kontoauszug",
                              "Bank of Scotland Kontoauszug", Decimal("0.95"),
                              "Bank, Rechnungsabschluss und Buchungstabelle erkannt"),)
        return ()

    def parse(self, document: PdfDocument, detection: Detection) -> ParsedDocument:
        if detection.handler_id != "kontoauszug":
            raise BankOfScotlandParseError("unsupported handler")
        text = document.text
        iban_match, number_match = IBAN.search(text), ACCOUNT_NO.search(text)
        if not (iban_match or number_match):
            raise BankOfScotlandParseError("Weder IBAN noch Kontonummer erkannt")
        old, new, statement_day = OLD.search(text), NEW.search(text), STATEMENT_DATE.search(text)
        if not (old and new and statement_day):
            raise BankOfScotlandParseError("Anfangssaldo, Endsaldo oder Auszugsdatum fehlt")
        identity = re.sub(r"\s+", "", iban_match.group("value")) if iban_match else number_match.group("value")
        account_id = stable_id("account", "bank-of-scotland", identity)
        evidence = []

        def ev(field, page, excerpt):
            item = Evidence(stable_id("evidence", document.document_id, page, field, excerpt),
                            document.document_id, page, field, excerpt, f"page:{page}",
                            document.source_hash, self.metadata.plugin_id, detection.handler_id,
                            self.metadata.version)
            evidence.append(item)
            return item.evidence_id

        header_page = next(page.number for page in document.pages
                           if (IBAN.search(page.text) or ACCOUNT_NO.search(page.text)))
        bank_ev = ev("bank_name", header_page, "Bank of Scotland")
        id_ev = ev("account_identity", header_page, identity)
        type_value = AccountType.FESTGELD if re.search(r"Festgeld", text, re.I) else AccountType.TAGESGELD
        type_ev = ev("account_type", header_page, type_value.value)
        attributes = {}
        for key, pattern in (("statement_date", STATEMENT_DATE), ("statement_number", STATEMENT_NO)):
            match = pattern.search(text)
            if match:
                attributes[key] = _field(match.group("value"), header_page,
                                         ev(key, header_page, match.group(0)))
        account = Account(
            account_id, bank_name=_field("Bank of Scotland", header_page, bank_ev),
            account_type=_field(type_value, header_page, type_ev),
            account_number=_field(number_match.group("value"), header_page, id_ev) if number_match else FieldValue.unknown(),
            iban=_field(identity, header_page, id_ev) if iban_match else FieldValue.unknown(),
            bic=_field(BIC.search(text).group("value"), header_page,
                       ev("bic", header_page, BIC.search(text).group(0))) if BIC.search(text) else FieldValue.unknown(),
            currency=_field("EUR", header_page, ev("currency", header_page, "EUR")),
            holder_name=_field(HOLDER.search(text).group("value").strip(), header_page,
                               ev("holder", header_page, HOLDER.search(text).group(0))) if HOLDER.search(text) else FieldValue.unknown(),
            attributes=attributes,
            functions=(FieldValue.manual(AccountFunction.SAVINGS),))
        rows = []
        for page in document.pages:
            if not HEADER.search(page.text):
                if any(ROW.match(line) for line in page.text.splitlines()):
                    raise BankOfScotlandParseError(f"Seite {page.number}: Buchungszeile ohne Tabellenkopf")
                continue
            for line_no, line in enumerate(page.text.splitlines(), 1):
                match = ROW.match(line)
                if match:
                    rows.append({**match.groupdict(), "page": page.number, "line": line_no, "raw": line.strip()})
        if not rows:
            raise BankOfScotlandParseError("Keine Buchungen erkannt")
        opening, closing = _money(old.group("value")), _money(new.group("value"))
        amounts = [_money(row["amount"]) for row in rows]
        solutions = [signs for signs in product((-1, 1), repeat=len(rows))
                     if opening + sum((amount * sign for amount, sign in zip(amounts, signs)), Decimal()) == closing]
        if len(solutions) == 1:
            selected_signs = solutions[0]
        else:
            def inferred_sign(row):
                value = row["body"].lower()
                if any(token in value for token in ("gutschrift", "zinsen", "einzahlung", "erstattung")):
                    return 1
                return -1
            selected_signs = tuple(inferred_sign(row) for row in rows)
        events, fees = [], []
        for index, (row, amount, sign) in enumerate(zip(rows, amounts, selected_signs), 1):
            signed = amount * sign
            row_ev = ev("booking", row["page"], row["raw"])
            description = " ".join(row["body"].split())
            lower = description.lower()
            kind, movement_type = "CASH_BOOKING", CashMovementType.DEPOSIT if sign > 0 else CashMovementType.WITHDRAWAL
            if "zins" in lower:
                kind = "INTEREST_CREDIT" if sign > 0 else "INTEREST_DEBIT"
                movement_type = CashMovementType.INTEREST_CREDIT if sign > 0 else CashMovementType.INTEREST_DEBIT
            elif any(token in lower for token in ("steuer", "solidar", "kirchen")):
                kind = "TAX_REFUND" if sign > 0 else "TAX_DEBIT"
                movement_type = CashMovementType.TAX_REFUND if sign > 0 else CashMovementType.TAX_DEBIT
            elif any(token in lower for token in ("gebühr", "entgelt", "provision")):
                kind = "FEE_REFUND" if sign > 0 else "FEE_DEBIT"
                movement_type = CashMovementType.FEE_REFUND if sign > 0 else CashMovementType.FEE_DEBIT
            elif "überweisung" in lower:
                kind, movement_type = "TRANSFER", CashMovementType.TRANSFER
            event_id = stable_id("event", account_id, row["booked"], row["value"], signed, description, index)
            cash_id = stable_id("cash", event_id)
            cash = CashMovement(cash_id, event_id, signed, "EUR", CashStatus.ACTUAL,
                                account_id=account_id, movement_type=movement_type,
                                evidence_ids=(row_ev,))
            tax_events = ()
            fee_events = ()
            if kind.startswith("TAX"):
                tax_kind = "solidarity_surcharge" if "solidar" in lower else \
                    "church_tax" if "kirchen" in lower else "capital_gains_tax"
                tax_events = (TaxEvent(stable_id("tax", event_id), event_id, tax_kind,
                                       (TaxComponent(tax_kind, amount, "EUR"),),
                                       cash_movement_id=cash_id, evidence_ids=(row_ev,)),)
            if kind.startswith("FEE"):
                fee_item = FeeEvent(stable_id("fee", event_id), "banking", "bank_charge", amount,
                                    "EUR", _date(row["booked"]),
                                    FeeEffect.REFUND if sign > 0 else FeeEffect.ACTUAL_BOOKED,
                                    document.document_id, "bank-of-scotland", account_id=account_id,
                                    transaction_id=event_id, cash_movement_id=cash_id,
                                    external_reference=description, evidence_ids=(row_ev,))
                fees.append(fee_item); fee_events = (fee_item,)
            events.append(FinancialEvent(event_id, document.document_id, kind, _date(row["booked"]),
                                         (cash,), tax_events=tax_events, fee_events=fee_events,
                                         evidence_ids=(row_ev,)))
        statement_date = _date(statement_day.group("value"))
        open_ev = ev("opening_balance", header_page, old.group(0))
        close_ev = ev("closing_balance", header_page, new.group(0))
        balances = (
            AccountBalance(stable_id("balance", account_id, "opening", statement_date), account_id,
                           _field(min(event.event_date for event in events), header_page, open_ev),
                           _field(opening, header_page, open_ev), _field("EUR", header_page, open_ev),
                           FieldValue.manual("opening")),
            AccountBalance(stable_id("balance", account_id, "closing", statement_date), account_id,
                           _field(statement_date, header_page, close_ev), _field(closing, header_page, close_ev),
                           _field("EUR", header_page, close_ev), FieldValue.manual("closing")),)
        issues = []
        calculated = opening + sum((movement.amount for event in events for movement in event.cash_movements), Decimal())
        if calculated != closing:
            issues.append(Issue(stable_id("issue", document.document_id, "balance"), "BALANCE_MISMATCH",
                                IssueSeverity.ERROR, f"Saldoabweichung {closing - calculated} EUR",
                                evidence_id=close_ev, nature=IssueNature.MATHEMATICAL_INCONSISTENCY))
        return ParsedDocument(stable_id("result", document.document_id, self.metadata.version),
                              document.document_id, self.metadata.plugin_id, self.metadata.version,
                              detection.handler_id, events=tuple(events), evidence=tuple(evidence),
                              issues=tuple(issues), accounts=(account,), account_balances=balances)

