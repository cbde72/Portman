"""Independent FNZ/finvesto turnover and depot-statement parser."""

from datetime import datetime
from decimal import Decimal
import re

from portman_parsers.api import (
    CashMovement, CashMovementType, CashStatus, Depot, DepotPosition, DepotSnapshot,
    DepotType, Detection, Evidence, FeeEffect, FeeEvent, FieldValue, FinancialEvent,
    Issue, IssueNature, IssueSeverity, MissingValue, ParsedDocument, PdfDocument,
    ReviewStatus, SecurityMovement, TaxComponent, TaxEvent,
)
from portman_parsers.registry.allowlist import APPROVED_PLUGINS
from portman_parsers.utilities import stable_id

DATE = r"\d{2}\.\d{2}\.\d{4}"
NUM = r"\d[\d.]*(?:,\d+)?"
MONEY = r"\d[\d.]*,\d{2}"
BANK = re.compile(r"FNZ\s*Bank|European\s*Bank\s*for\s*Financial\s*Services|\bebase\b", re.I)
TURNOVER = re.compile(r"Umsatzabrechnung\s+f.r\s+Ihr\s+finvesto\s+Depot", re.I)
STATEMENT = re.compile(r"Depotauszug\s+f.r\s+Ihr\s+finvesto\s+Depot", re.I)
DEPOT_NO = re.compile(r"Depot-Nr\.\s*(\d+)", re.I)
REFERENCE = re.compile(r"Ref\.\s*Nr\.\s*(?P<ref>\d+/\d+)\s*,?\s*Buchungsdatum\s*(?P<date>" + DATE + r")", re.I)
MARKER = re.compile(
    r"(?P<dividend>Fondsertrag\s*\(Aussch.ttung\).*?Depotposition\s*\d+\.\d+)"
    r"|(?P<reinvest>Wiederanlage\s+Fondsertrag\s*" + MONEY + r"\s*[A-Z]{3}.*?Depotposition\s*\d+\.\d+)"
    r"|(?P<buy>Kauf\s*" + MONEY + r"\s*[A-Z]{3}.*?Depotposition\s*\d+\.\d+)"
    r"|(?P<sell>Verkauf\s*" + MONEY + r"\s*[A-Z]{3}.*?Depotposition\s*\d+\.\d+)", re.I)
TRADE_ROW = re.compile(r"(?m)^\s*(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)\s+(?P<qty>" + NUM + r")\s+"
                       r"(?P<price>" + NUM + r")\s+(?P<price_currency>[A-Z]{3})(?:\s+(?P<fx>" + NUM + r"))?\s+"
                       r"(?P<amount>" + MONEY + r")\s+(?P<currency>[A-Z]{3})\s*$")
FEE = re.compile(r"(?:ETF-)?Transaktionsentgelt\s+(?P<amount>" + MONEY + r")\s*(?P<currency>[A-Z]{3})", re.I)
PAYMENT = re.compile(r"Zahlungsbetrag(?:\s*aus\s+.berweisung)?\s*(?P<amount>" + MONEY + r")\s*(?P<currency>[A-Z]{3})", re.I)
TAX = re.compile(r"abzgl\.\s*Steuern\s*(?P<amount>" + MONEY + r")\s*(?P<currency>[A-Z]{3})", re.I)
POSITION_HEADER = re.compile(r"Bestand\s+(?:der\s+)?Depotpositionen", re.I)
POSITION_ROW = re.compile(r"(?m)^\s*(?P<sub>\d{2})\s+(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)\s+"
                          r"(?P<qty>" + NUM + r")\s+(?P<price>" + NUM + r")\s+(?P<price_currency>[A-Z]{3})\s+"
                          r"(?P<date>" + DATE + r")\s+(?P<fx>" + NUM + r")\s+(?P<value>" + MONEY + r")\s+EUR\s*$")
TOTAL = re.compile(r"Depotgesamtwert\s*(?P<amount>" + MONEY + r")\s*(?P<currency>[A-Z]{3})", re.I)


def _number(value: str) -> Decimal:
    return Decimal(value.replace(".", "").replace(",", "."))


def _date(value: str):
    return datetime.strptime(value, "%d.%m.%Y").date()


class FnzFinvestoParseError(ValueError):
    pass


class FnzFinvestoPlugin:
    metadata = next(item for item in APPROVED_PLUGINS if item.plugin_id == "fnz.finvesto")

    def detect(self, document: PdfDocument) -> tuple[Detection, ...]:
        if not BANK.search(document.text) or not DEPOT_NO.search(document.text):
            return ()
        handler = "umsatzabrechnung" if TURNOVER.search(document.text) else "depotauszug" if STATEMENT.search(document.text) else None
        if not handler:
            return ()
        label = next(item.document_type for item in self.metadata.handlers if item.handler_id == handler)
        return (Detection(self.metadata.plugin_id, self.metadata.version, handler, label,
                          Decimal("0.99"), "FNZ/finvesto title and depot number recognized"),)

    def parse(self, document: PdfDocument, detection: Detection) -> ParsedDocument:
        depot_match = DEPOT_NO.search(document.text)
        if not depot_match:
            raise FnzFinvestoParseError("FNZ depot number missing")
        evidence: list[Evidence] = []

        def ev(field: str, excerpt: str) -> str:
            page = next((p.number for p in document.pages if excerpt in p.text), 1)
            identity = stable_id("evidence", document.document_id, page, field, excerpt)
            evidence.append(Evidence(identity, document.document_id, page, field, excerpt,
                                     f"page:{page}", document.source_hash, self.metadata.plugin_id,
                                     detection.handler_id, self.metadata.version))
            return identity

        depot_no = depot_match.group(1)
        depot_ev = ev("depot_number", depot_match.group(0))
        bank_ev = ev("bank", BANK.search(document.text).group(0))
        depot_id = stable_id("depot", "fnz", depot_no)
        field = lambda value, evidence_id: FieldValue.from_pdf(value, 1, evidence_id,
                                                                review_status=ReviewStatus.UNREVIEWED)
        depot = Depot(depot_id, bank_name=field("FNZ Bank", bank_ev),
                      depot_number=field(depot_no, depot_ev), base_currency=field("EUR", depot_ev),
                      depot_type=FieldValue.manual(DepotType.WERTPAPIER))
        snapshot, snapshot_issues = self._snapshot(document, depot_id, detection.handler_id == "depotauszug", ev)
        events = self._transactions(document, depot_id, ev) if detection.handler_id == "umsatzabrechnung" else ()
        return ParsedDocument(stable_id("result", document.document_id, self.metadata.version),
                              document.document_id, self.metadata.plugin_id, self.metadata.version,
                              detection.handler_id, events=events, evidence=tuple(evidence),
                              issues=snapshot_issues, depots=(depot,),
                              depot_snapshots=(snapshot,) if snapshot else ())

    def _transactions(self, document: PdfDocument, depot_id: str, ev) -> tuple[FinancialEvent, ...]:
        text = document.text
        markers = list(MARKER.finditer(text))
        events: list[FinancialEvent] = []
        seen: set[str] = set()
        for index, marker in enumerate(markers):
            body = text[marker.start():markers[index + 1].start() if index + 1 < len(markers) else len(text)]
            reference, row = REFERENCE.search(body), TRADE_ROW.search(body)
            if not reference or not row or reference.group("ref") in seen:
                raise FnzFinvestoParseError("FNZ turnover lacks a unique reference or security row")
            seen.add(reference.group("ref"))
            kind = "DIVIDEND" if marker.group("dividend") else "BUY" if marker.group("buy") else "SELL" if marker.group("sell") else "REINVESTMENT"
            qty, gross = _number(row.group("qty")), _number(row.group("amount"))
            booked = _date(reference.group("date")); currency = row.group("currency")
            price = _number(row.group("price"))
            if qty <= 0 or gross <= 0 or price <= 0:
                raise FnzFinvestoParseError("FNZ turnover contains non-positive quantity, price or amount")
            calculated = qty * price
            if row.group("price_currency") == currency and abs(calculated - gross) > Decimal("0.01"):
                raise FnzFinvestoParseError("FNZ quantity and price do not match gross amount")
            if row.group("price_currency") != currency and not row.group("fx"):
                raise FnzFinvestoParseError("FNZ foreign-currency trade lacks an exchange rate")
            evidence_id = ev("transaction", body[:min(len(body), 500)].strip())
            event_id = stable_id("event", depot_id, reference.group("ref"), kind, row.group("isin"))
            security = SecurityMovement(stable_id("security-movement", event_id), event_id,
                                        row.group("isin"), qty if kind in {"BUY", "REINVESTMENT"} else -qty,
                                        (evidence_id,), depot_id=depot_id)
            payment = PAYMENT.search(body); fee = FEE.search(body); tax = TAX.search(body)
            fee_amount = _number(fee.group("amount")) if fee else Decimal("0")
            tax_amount = _number(tax.group("amount")) if tax else Decimal("0")
            if payment:
                settlement = _number(payment.group("amount"))
                expected = gross + fee_amount + tax_amount if kind in {"BUY", "REINVESTMENT"} else gross - fee_amount - tax_amount
                if payment.group("currency") != currency or abs(settlement - expected) > Decimal("0.01"):
                    raise FnzFinvestoParseError("FNZ settlement does not reconcile with gross, fees and taxes")
            fees: tuple[FeeEvent, ...] = ()
            taxes: tuple[TaxEvent, ...] = ()
            cash: tuple[CashMovement, ...] = ()
            # A documented settlement is expected, never promoted to an actual account booking.
            if payment:
                cash_value = _number(payment.group("amount"))
                sign = 1 if kind in {"DIVIDEND", "SELL"} else -1
                cash_id = stable_id("expected-settlement", event_id)
                cash = (CashMovement(cash_id, event_id, cash_value * sign, payment.group("currency"),
                                     CashStatus.EXPECTED, evidence_ids=(evidence_id,),
                                     movement_type=CashMovementType.DIVIDEND_CREDIT if kind == "DIVIDEND" else
                                     CashMovementType.SECURITY_SELL if kind == "SELL" else CashMovementType.SECURITY_BUY),)
            if fee:
                amount = fee_amount
                fees = (FeeEvent(stable_id("fee", event_id), "trading", "transaction_fee", amount,
                                 fee.group("currency"), booked, FeeEffect.INCLUDED_IN_SETTLEMENT,
                                 document.document_id, "fnz", depot_id=depot_id,
                                 transaction_id=event_id, evidence_ids=(evidence_id,)),)
            if tax:
                amount = tax_amount
                taxes = (TaxEvent(stable_id("tax", event_id), event_id, "WITHHOLDING_TAX",
                                  (TaxComponent("TOTAL_WITHHOLDING", amount, tax.group("currency")),),
                                  evidence_ids=(evidence_id,), depot_id=depot_id,
                                  isin=row.group("isin"), bank_id="fnz", currency=tax.group("currency")),)
            events.append(FinancialEvent(event_id, document.document_id, kind, booked, cash, (security,),
                                         taxes, fee_events=fees, evidence_ids=(evidence_id,)))
        if not events:
            raise FnzFinvestoParseError("No supported FNZ turnover found")
        return tuple(events)

    def _snapshot(self, document: PdfDocument, depot_id: str, complete: bool, ev):
        header = POSITION_HEADER.search(document.text)
        if not header:
            if complete:
                raise FnzFinvestoParseError("FNZ holdings section missing")
            return None, ()
        positions = []
        for row in POSITION_ROW.finditer(document.text, header.end()):
            evidence_id = ev("depot_position", row.group(0).strip())
            page = next((p.number for p in document.pages if row.group(0).strip() in p.text), 1)
            pdf = lambda value: FieldValue.from_pdf(value, page, evidence_id)
            positions.append(DepotPosition(stable_id("position", depot_id, row.group("sub"), row.group("isin")),
                                           pdf(row.group("isin")), pdf(_number(row.group("qty"))),
                                           market_value=pdf(_number(row.group("value"))), currency=pdf("EUR"),
                                           price=pdf(_number(row.group("price"))), price_date=pdf(_date(row.group("date")))))
        if not positions:
            raise FnzFinvestoParseError("No FNZ depot position recognized")
        total = TOTAL.search(document.text)
        total_ev = ev("depot_total", total.group(0)) if total else None
        total_value = FieldValue.from_pdf(_number(total.group("amount")), 1, total_ev) if total else FieldValue.unknown()
        as_of = max(item.price_date.value for item in positions)
        snapshot = DepotSnapshot(stable_id("snapshot", depot_id, as_of, document.document_id), depot_id,
                                 FieldValue.from_pdf(as_of, 1, positions[0].price_date.evidence_ids[0]),
                                 tuple(positions), total_value,
                                 FieldValue.from_pdf(total.group("currency"), 1, total_ev) if total else FieldValue.unknown())
        issues = []
        if total:
            calculated = sum((item.market_value.value for item in positions), Decimal())
            reported = _number(total.group("amount"))
            if calculated != reported:
                issues.append(Issue(stable_id("issue", snapshot.snapshot_id, "total"), "DEPOT_TOTAL_MISMATCH",
                                    IssueSeverity.ERROR, f"Position sum differs by {reported - calculated} EUR",
                                    evidence_id=total_ev, nature=IssueNature.MATHEMATICAL_INCONSISTENCY))
        elif complete:
            issues.append(Issue(stable_id("issue", snapshot.snapshot_id, "total-missing"), "DEPOT_TOTAL_MISSING",
                                IssueSeverity.WARNING, "Depot total is missing.", nature=IssueNature.MISSING_INFORMATION))
        return snapshot, tuple(issues)
