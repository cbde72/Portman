"""Unabhängiger Parser für FNZ-/finvesto-Umsatzabrechnungen und Depotauszüge."""

from datetime import datetime
from decimal import Decimal
import re

from portman_parsers.api import (
    CashMovement, CashMovementType, CashStatus, Depot, DepotPosition, DepotSnapshot,
    DepotType, Detection, Evidence, FeeEffect, FeeEvent, FieldValue, FinancialEvent,
    Issue, IssueNature, IssueSeverity, MissingValue, ParsedDocument, PdfDocument,
    ReviewStatus, SecurityMovement, SecurityTrade, TaxComponent, TaxEvent,
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
COURSE_DATE = re.compile(r"Kursdatum\s*(?P<date>" + DATE + r")", re.I)
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
TAX_COMPONENTS = re.compile(
    r"Kapitalertragsteuer\s+Solidarit.tszuschlag\s+Kirchensteuer\s+Devisenkurs\s+abzgl\.\s*Steuern\s+"
    r"(?P<capital>" + MONEY + r")\s*EUR\s+(?P<solidarity>" + MONEY + r")\s*EUR\s+"
    r"(?P<church>" + MONEY + r")\s*EUR\s+(?P<fx>" + NUM + r")\s+"
    r"(?P<total>" + MONEY + r")\s*(?P<currency>[A-Z]{3})", re.I)
POSITION_HEADER = re.compile(r"Bestand\s+(?:der\s+)?Depotpositionen", re.I)
POSITION_ROW = re.compile(r"(?m)^\s*(?P<sub>\d{2})\s+(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)\s+"
                          r"(?P<qty>" + NUM + r")\s+(?P<price>" + NUM + r")\s+(?P<price_currency>[A-Z]{3})\s+"
                          r"(?P<date>" + DATE + r")\s+(?P<fx>" + NUM + r")\s+(?P<value>" + MONEY + r")\s+EUR\s*$")
POSITION_ROW_VERTICAL = re.compile(
    r"(?m)^\s*(?P<sub>\d{2})\s*\n\s*(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)\s*\n\s*"
    r"(?P<qty_int>\d[\d.]*)\s*\n\s*,(?P<qty_dec>\d+)\s*\n\s*"
    r"(?P<price_int>\d[\d.]*)\s*\n\s*,(?P<price_dec>\d+)\s+(?P<price_currency>[A-Z]{3})\s*\n\s*"
    r"(?P<date>" + DATE + r")\s*\n\s*(?P<fx_int>\d[\d.]*)\s*\n\s*,(?P<fx_dec>\d+)\s*\n\s*"
    r"(?P<value_int>\d[\d.]*)\s*\n\s*,(?P<value_dec>\d+)\s+EUR\s*$")
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
                          Decimal("0.99"), "FNZ-/finvesto-Titel und Depotnummer erkannt"),)

    def parse(self, document: PdfDocument, detection: Detection) -> ParsedDocument:
        depot_match = DEPOT_NO.search(document.text)
        if not depot_match:
            raise FnzFinvestoParseError("FNZ-Depotnummer fehlt")
        evidence: list[Evidence] = []
        evidence_pages: dict[str, int] = {}

        page_offsets = []
        offset = 0
        for page_item in document.pages:
            page_offsets.append((offset, offset + len(page_item.text), page_item))
            offset += len(page_item.text) + 1

        def ev(field: str, excerpt: str, source_offset: int | None = None) -> str:
            source = next((page_item for start, end, page_item in page_offsets
                           if source_offset is not None and start <= source_offset <= end), None)
            page = source.number if source else next((p.number for p in document.pages if excerpt in p.text), None)
            if page is None:
                raise FnzFinvestoParseError("FNZ-Evidence ist auf keiner PDF-Seite vorhanden: " + field)
            if excerpt not in next(p.text for p in document.pages if p.number == page):
                raise FnzFinvestoParseError("FNZ-Evidence ist nicht auf der angegebenen PDF-Seite vorhanden: " + field)
            identity = stable_id("evidence", document.document_id, page, field, excerpt)
            if identity not in evidence_pages:
                evidence.append(Evidence(identity, document.document_id, page, field, excerpt,
                                         f"page:{page}", document.source_hash, self.metadata.plugin_id,
                                         detection.handler_id, self.metadata.version))
                evidence_pages[identity] = page
            return identity

        depot_no = depot_match.group(1)
        depot_ev = ev("depot_number", depot_match.group(0))
        bank_ev = ev("bank", BANK.search(document.text).group(0))
        depot_id = stable_id("depot", "fnz", depot_no)
        field = lambda value, evidence_id: FieldValue.from_pdf(value, evidence_pages[evidence_id], evidence_id,
                                                                review_status=ReviewStatus.UNREVIEWED)
        depot = Depot(depot_id, bank_name=field("FNZ Bank", bank_ev),
                      depot_number=field(depot_no, depot_ev), base_currency=field("EUR", depot_ev),
                      depot_type=FieldValue.manual(DepotType.WERTPAPIER))
        snapshot, snapshot_issues = self._snapshot(document, depot_id, detection.handler_id == "depotauszug", ev, field)
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
                raise FnzFinvestoParseError("FNZ-Umsatz besitzt keine eindeutige Referenz oder Wertpapierzeile")
            seen.add(reference.group("ref"))
            kind = "DIVIDEND" if marker.group("dividend") else "BUY" if marker.group("buy") else "SELL" if marker.group("sell") else "REINVESTMENT"
            qty, gross = _number(row.group("qty")), _number(row.group("amount"))
            booked = _date(reference.group("date")); currency = row.group("currency")
            price = _number(row.group("price"))
            if qty <= 0 or gross <= 0 or price <= 0:
                raise FnzFinvestoParseError("FNZ-Umsatz enthält eine nicht positive Stückzahl, einen nicht positiven Kurs oder Betrag")
            calculated = qty * price
            if row.group("price_currency") == currency and abs(calculated - gross) > Decimal("0.01"):
                raise FnzFinvestoParseError("FNZ-Stückzahl und Kurs stimmen nicht mit dem Bruttobetrag überein")
            if row.group("price_currency") != currency and not row.group("fx"):
                raise FnzFinvestoParseError("FNZ-Fremdwährungsgeschäft besitzt keinen Wechselkurs")
            payment = PAYMENT.search(body); fee = FEE.search(body); tax_components = TAX_COMPONENTS.search(body)
            tax = None if tax_components else TAX.search(body)
            evidence_matches = ((marker, marker.start()),
                                (reference, marker.start() + reference.start()),
                                (row, marker.start() + row.start()),
                                (payment, marker.start() + payment.start() if payment else None),
                                (fee, marker.start() + fee.start() if fee else None),
                                (tax_components or tax, marker.start() + (tax_components or tax).start() if (tax_components or tax) else None))
            evidence_ids = tuple(ev("transaction", match.group(0).strip(), source_offset)
                                 for match, source_offset in evidence_matches if match)
            row_evidence = evidence_ids[2]
            event_id = stable_id("event", depot_id, reference.group("ref"), kind, row.group("isin"))
            security = () if kind == "DIVIDEND" else (
                SecurityMovement(stable_id("security-movement", event_id), event_id,
                                 row.group("isin"), qty if kind in {"BUY", "REINVESTMENT"} else -qty,
                                 evidence_ids, depot_id=depot_id),)
            fee_amount = _number(fee.group("amount")) if fee else Decimal("0")
            tax_amount = _number((tax_components or tax).group("total" if tax_components else "amount")) if (tax_components or tax) else Decimal("0")
            if payment:
                settlement = _number(payment.group("amount"))
                expected = gross + fee_amount + tax_amount if kind in {"BUY", "REINVESTMENT"} else gross - fee_amount - tax_amount
                if payment.group("currency") != currency or abs(settlement - expected) > Decimal("0.01"):
                    raise FnzFinvestoParseError("FNZ-Abrechnungsbetrag stimmt nicht mit Brutto, Gebühren und Steuern überein")
            fees: tuple[FeeEvent, ...] = ()
            taxes: tuple[TaxEvent, ...] = ()
            cash: tuple[CashMovement, ...] = ()
            trades: tuple[SecurityTrade, ...] = ()
            # Ein ausgewiesener Abrechnungsbetrag bleibt erwartet und wird nie zur tatsächlichen Kontobuchung.
            if payment:
                cash_value = _number(payment.group("amount"))
                sign = 1 if kind in {"DIVIDEND", "SELL"} else -1
                cash_id = stable_id("expected-settlement", event_id)
                cash = (CashMovement(cash_id, event_id, cash_value * sign, payment.group("currency"),
                                     CashStatus.EXPECTED, evidence_ids=evidence_ids,
                                     movement_type=CashMovementType.DIVIDEND_CREDIT if kind == "DIVIDEND" else
                                     CashMovementType.SECURITY_SELL if kind == "SELL" else CashMovementType.SECURITY_BUY),)
            if fee:
                amount = fee_amount
                fees = (FeeEvent(stable_id("fee", event_id), "trading", "transaction_fee", amount,
                                 fee.group("currency"), booked, FeeEffect.INCLUDED_IN_SETTLEMENT,
                                 document.document_id, "fnz", depot_id=depot_id,
                                 transaction_id=event_id, evidence_ids=evidence_ids),)
            if tax_components or tax:
                if tax_components:
                    exchange_rate = _number(tax_components.group("fx"))
                    components = tuple(
                        TaxComponent(label, (_number(tax_components.group(group)) * exchange_rate).quantize(Decimal("0.01")),
                                     tax_components.group("currency"))
                        for label, group in (("CAPITAL_GAINS_TAX", "capital"),
                                             ("SOLIDARITY_SURCHARGE", "solidarity"),
                                             ("CHURCH_TAX", "church")))
                    if abs(sum((item.amount for item in components), Decimal()) - tax_amount) > Decimal("0.01"):
                        raise FnzFinvestoParseError("FNZ-Steuerkomponenten stimmen nicht mit dem ausgewiesenen Gesamtbetrag überein")
                else:
                    components = (TaxComponent("TOTAL_WITHHOLDING", tax_amount, tax.group("currency")),)
                taxes = (TaxEvent(stable_id("tax", event_id), event_id, "WITHHOLDING_TAX",
                                  components, evidence_ids=evidence_ids, depot_id=depot_id,
                                  isin=row.group("isin"), bank_id="fnz", currency=(tax_components or tax).group("currency"),
                                  actually_withheld_tax=tax_amount),)
            if kind in {"BUY", "SELL", "REINVESTMENT"}:
                course_date = COURSE_DATE.search(marker.group(0))
                trades = (SecurityTrade(stable_id("trade", event_id), event_id,
                                        "SELL" if kind == "SELL" else "BUY", isin=row.group("isin"),
                                        quantity=qty, trade_date=_date(course_date.group("date")) if course_date else MissingValue.UNKNOWN,
                                        price_currency=row.group("price_currency"), market_value=gross,
                                        gross_amount=gross,
                                        exchange_rate=_number(row.group("fx")) if row.group("fx") else MissingValue.UNKNOWN,
                                        settlement_amount=_number(payment.group("amount")) if payment else MissingValue.UNKNOWN,
                                        settlement_currency=payment.group("currency") if payment else MissingValue.UNKNOWN,
                                        depot_id=depot_id, evidence_ids=evidence_ids),)
            events.append(FinancialEvent(event_id, document.document_id, kind, booked, cash, security,
                                         taxes, fee_events=fees, trades=trades, evidence_ids=evidence_ids,
                                         security_isin=row.group("isin"), security_identity_evidence_ids=(row_evidence,)))
        if not events:
            raise FnzFinvestoParseError("Kein unterstützter FNZ-Umsatz gefunden")
        return tuple(events)

    def _snapshot(self, document: PdfDocument, depot_id: str, complete: bool, ev, field):
        header = POSITION_HEADER.search(document.text)
        if not header:
            if complete:
                raise FnzFinvestoParseError("FNZ-Bestandsabschnitt fehlt")
            return None, ()
        positions = []
        rows = list(POSITION_ROW.finditer(document.text, header.end()))
        vertical = not rows
        if vertical:
            rows = list(POSITION_ROW_VERTICAL.finditer(document.text, header.end()))
        for row in rows:
            evidence_id = ev("depot_position", row.group(0).strip())
            pdf = lambda value: field(value, evidence_id)
            values = row.groupdict()
            if vertical:
                values.update(qty=values["qty_int"] + "," + values["qty_dec"],
                              price=values["price_int"] + "," + values["price_dec"],
                              fx=values["fx_int"] + "," + values["fx_dec"],
                              value=values["value_int"] + "," + values["value_dec"])
            positions.append(DepotPosition(stable_id("position", depot_id, row.group("sub"), row.group("isin")),
                                           pdf(values["isin"]), pdf(_number(values["qty"])),
                                           market_value=pdf(_number(values["value"])), currency=pdf("EUR"),
                                           price=pdf(_number(values["price"])), price_date=pdf(_date(values["date"]))))
        if not positions:
            raise FnzFinvestoParseError("Keine FNZ-Depotposition erkannt")
        total = TOTAL.search(document.text)
        total_ev = ev("depot_total", total.group(0)) if total else None
        total_value = field(_number(total.group("amount")), total_ev) if total else FieldValue.unknown()
        as_of = max(item.price_date.value for item in positions)
        snapshot = DepotSnapshot(stable_id("snapshot", depot_id, as_of, document.document_id), depot_id,
                                 field(as_of, positions[0].price_date.evidence_ids[0]),
                                 tuple(positions), total_value,
                                 field(total.group("currency"), total_ev) if total else FieldValue.unknown())
        issues = []
        if total:
            calculated = sum((item.market_value.value for item in positions), Decimal())
            reported = _number(total.group("amount"))
            if calculated != reported:
                issues.append(Issue(stable_id("issue", snapshot.snapshot_id, "total"), "DEPOT_TOTAL_MISMATCH",
                                    IssueSeverity.ERROR, f"Positionssumme weicht um {reported - calculated} EUR ab",
                                    evidence_id=total_ev, nature=IssueNature.MATHEMATICAL_INCONSISTENCY))
        elif complete:
            issues.append(Issue(stable_id("issue", snapshot.snapshot_id, "total-missing"), "DEPOT_TOTAL_MISSING",
                                IssueSeverity.WARNING, "Depotgesamtwert fehlt.", nature=IssueNature.MISSING_INFORMATION))
        return snapshot, tuple(issues)
