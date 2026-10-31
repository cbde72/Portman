"""Independent Python interpretation of public Portfolio Performance comdirect rules.

This module is distributed under EPL-1.0; see ``LICENSES/EPL-1.0.txt``.
Rule provenance: Portfolio Performance ``ComdirectPDFExtractor.java`` at commit
c08d5053f0066f0fad0685a3e35bd7b7037c9b0f (EPL-1.0).  This module is an
independent implementation against Portman DTOs; it contains no Java runtime,
PDFBox, Portfolio Performance model, fixture, or GUI dependency.
"""

from datetime import datetime
from decimal import Decimal
import re

from portman_parsers.api import (
    AdvanceTaxCalculation, AdvanceTaxCarryforward, CashMovement, CashMovementType,
    CashStatus, Detection, Evidence, FeeEffect, FeeEvent, FinancialEvent,
    Issue, IssueNature, IssueSeverity, MissingValue, ParsedDocument,
    SecurityMovement, SecurityTrade, TaxApprovalStatus, TaxComponent, TaxEvent,
)
from portman_parsers.registry.allowlist import APPROVED_PLUGINS
from portman_parsers.utilities import stable_id

AMOUNT = r"\d[\d.]*,\d+"
DATE = r"\d{2}\.\d{2}\.\d{4}"
ISIN = re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b")
WKN = re.compile(r"\bWKN(?:\s*/\s*ISIN)?\s*:?[ \t]*([A-Z0-9]{6})", re.I)
SECURITY_ROW = re.compile(
    r"(?:Stk\.?|STK|[A-Z]{3})[\s-]+(?P<shares>[\d.,]+)\s+(?P<name>.+?),\s*"
    r"WKN\s*/\s*ISIN:\s*(?P<wkn>[A-Z0-9]{6})\s*/\s*(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)", re.I)

TITLES = (
    ("finanzreport", r"Finanzreport"),
    ("vorabpauschale", r"Steuerliche\s+Behandlung:\s*Vorabpauschale"),
    ("investment_ausschuettung", r"Steuerliche\s+Behandlung:.*Investment[- ]Aussch"),
    ("dividende_steuer_inland", r"Steuerliche\s+Behandlung:.*Dividende"),
    ("wertpapierkauf", r"(?:^|\n)(?!Steuerliche Behandlung:).*Wertpapierkauf"),
    ("wertpapierverkauf", r"(?:^|\n)(?!Steuerliche Behandlung:).*(?:Wertpapierverkauf|Verkauf)"),
    ("einloesung", r"(?:Abrechnung\s*)?Einl[öo]sung"),
    ("dividendengutschrift", r"Dividendengutschrift"),
    ("ertragsgutschrift", r"Ertragsgutschrift|Zinsgutschrift"),
)

TAX_PATTERNS = (
    ("CAPITAL_GAINS_TAX", r"Kapitalertragsteuer(?:\s+auf.*?)?\s*:?[ \t]*(?:[A-Z]{3})?[ \t]*(" + AMOUNT + r")[- ]?"),
    ("SOLIDARITY_SURCHARGE", r"Solidarit.tszuschl?(?:ag)?(?:\s+auf.*?)?\s*:?[ \t]*(?:[A-Z]{3})?[ \t]*(" + AMOUNT + r")[- ]?"),
    ("CHURCH_TAX", r"Kirchensteuer\s*:?[ \t]*(?:[A-Z]{3})?[ \t]*(" + AMOUNT + r")[- ]?"),
    ("WITHHOLDING_TAX", r"(?:nicht erstattungsf.hige )?Quellensteuer.*?(?:[A-Z]{3})[ \t]*(" + AMOUNT + r")[- ]?"),
    ("TRANSACTION_TAX", r"Transaktionssteuer\s*:?[ \t]*(?:[A-Z]{3})?[ \t]*(" + AMOUNT + r")[- ]?"),
)
FEE_PATTERNS = (
    ("provision", r"(?:Gesamtprovision|Provision)\s*:?[ \t]*(?:[A-Z]{3})?[ \t]*(" + AMOUNT + r")[- ]?"),
    ("foreign_expenses", r"(?:fremde|Fremde) Spesen\s*:?[ \t]*(?:[A-Z]{3})?[ \t]*(" + AMOUNT + r")[- ]?"),
    ("brokerage", r"Maklercourtage\s*:?[ \t]*(?:[A-Z]{3})?[ \t]*(" + AMOUNT + r")[- ]?"),
    ("exchange_fee", r"(?:B.rsenplatzabh.ng\. Entgelt|Variable B.rsenspesen|Abwickl\.entgelt Clearstream|Umschreibeentgelt)\s*:?[ \t]*(?:[A-Z]{3})?[ \t]*(" + AMOUNT + r")[- ]?"),
)


def _decimal(value: str) -> Decimal:
    return Decimal(value.replace(".", "").replace(",", "."))


def _date(value: str):
    return datetime.strptime(value, "%d.%m.%Y").date()


class ComdirectPPPlugin:
    metadata = next(x for x in APPROVED_PLUGINS if x.plugin_id == "portfolio-performance.comdirect")
    source_commit = "c08d5053f0066f0fad0685a3e35bd7b7037c9b0f"
    source_license = "EPL-1.0"

    def detect(self, document):
        text = document.text
        if not re.search(r"comdirect|comdirect bank", text, re.I):
            return ()
        for handler, pattern in TITLES:
            if re.search(pattern, text, re.I | re.S):
                meta = next(x for x in self.metadata.handlers if x.handler_id == handler)
                return (Detection(self.metadata.plugin_id, self.metadata.version, handler,
                                  meta.document_type, Decimal("0.90"),
                                  "Independent PP-derived comdirect rule matched"),)
        return ()

    def parse(self, document, detection):
        evidence = []

        def add_evidence(field, match_or_text):
            excerpt = match_or_text.group(0) if hasattr(match_or_text, "group") else str(match_or_text)
            page = next((p.number for p in document.pages if excerpt in p.text), 1)
            eid = stable_id("evidence", document.document_id, detection.handler_id, field, excerpt, len(evidence))
            evidence.append(Evidence(eid, document.document_id, page, field, excerpt, f"page:{page}",
                                     document.source_hash, self.metadata.plugin_id,
                                     detection.handler_id, self.metadata.version))
            return eid

        title_pattern = next(p for h, p in TITLES if h == detection.handler_id)
        title = re.search(title_pattern, document.text, re.I | re.S)
        title_evidence = add_evidence("document_type", title)
        if detection.handler_id == "finanzreport":
            return self._financial_report(document, detection, evidence, add_evidence, title_evidence)
        if detection.handler_id in {"vorabpauschale", "investment_ausschuettung", "dividende_steuer_inland"}:
            return self._tax_notice(document, detection, evidence, add_evidence, title_evidence)
        return self._security_transaction(document, detection, evidence, add_evidence, title_evidence)

    def _security_transaction(self, document, detection, evidence, ev, title_evidence):
        text = document.text
        handler = detection.handler_id
        side = "BUY" if handler == "wertpapierkauf" else "SELL" if handler == "wertpapierverkauf" else "REDEMPTION" if handler == "einloesung" else "DIVIDEND"
        security = SECURITY_ROW.search(text)
        isin_match = ISIN.search(text)
        wkn_match = WKN.search(text)
        shares_match = re.search(r"(?:Stk\.?|STK)\s*[\- ]*(" + AMOUNT + r")", text, re.I)
        shares = _decimal(security.group("shares")) if security else _decimal(shares_match.group(1)) if shares_match else None
        isin = security.group("isin") if security else isin_match.group(0) if isin_match else None
        wkn = security.group("wkn") if security else wkn_match.group(1) if wkn_match else MissingValue.NOT_FOUND
        name = security.group("name").strip() if security else MissingValue.NOT_FOUND

        settlement = re.search(r"(?:Zu\s*Ihren\s*(?P<direction>Lasten|Gunsten)|Abrechnungsbetrag|Gutschrift)"
                               r"[^\n]{0,100}?(?P<currency>[A-Z]{3})[\s-]*(?P<amount>" + AMOUNT + r")", text, re.I)
        valuta = re.search(r"(?:Valuta|Die (?:Gutschrift|Belastung) erfolgt mit Valuta|zahlbar ab)\s*(" + DATE + r")", text, re.I)
        trade_date = re.search(r"(?:Geschäftstag|Schlusstag|Handelstag)\s*:?[ \t]*(" + DATE + r")", text, re.I)
        price = re.search(r"(?:Ausführungskurs|Kurs)\s*:?[ \t]*(?:(?P<c1>[A-Z]{3})\s*)?(?P<amount>" + AMOUNT + r")(?:\s*(?P<c2>[A-Z]{3}))?", text, re.I)
        market = re.search(r"(?:Kurswert|Gegenwert)\s*:?[ \t]*(?P<currency>[A-Z]{3})\s*(?P<amount>" + AMOUNT + r")", text, re.I)
        gross = re.search(r"Bruttobetrag\s*:?[ \t]*(?P<currency>[A-Z]{3})\s*(?P<amount>" + AMOUNT + r")", text, re.I)
        fx = re.search(r"(?:zum Devisenkurs|Umrechnungen zum Devisenkurs)\s*:?[ \t]*(?:[A-Z]{3}/[A-Z]{3}\s*)?(" + AMOUNT + r")", text, re.I)
        event_id = stable_id("pp-event", document.document_id, handler, isin or "", settlement.group("amount") if settlement else "")
        event_evidence = ev("economic_event", settlement or title_pattern_for(handler))

        issues = []
        for code, missing, message in (
            ("PP_SECURITY_MISSING", not isin, "Wertpapieridentität fehlt im PP-Pfad."),
            ("PP_QUANTITY_MISSING", shares is None, "Stückzahl fehlt im PP-Pfad."),
            ("PP_SETTLEMENT_MISSING", settlement is None, "Settlement fehlt im PP-Pfad."),
        ):
            if missing and side in {"BUY", "SELL", "REDEMPTION"}:
                issues.append(Issue(stable_id("issue", event_id, code), code, IssueSeverity.WARNING,
                                    message, event_id=event_id, nature=IssueNature.MISSING_INFORMATION))

        cash = ()
        if settlement:
            direction = (settlement.groupdict().get("direction") or "").lower()
            sign = -1 if side == "BUY" or direction == "lasten" else 1
            movement_type = CashMovementType.SECURITY_BUY if side == "BUY" else CashMovementType.SECURITY_SELL if side in {"SELL", "REDEMPTION"} else CashMovementType.DIVIDEND_CREDIT
            cash = (CashMovement(stable_id("cash", event_id), event_id,
                                 _decimal(settlement.group("amount")) * sign,
                                 settlement.group("currency"), CashStatus.EXPECTED,
                                 evidence_ids=(event_evidence,), movement_type=movement_type),)
        securities = ()
        if isin and shares is not None:
            quantity = shares if side == "BUY" else -shares if side in {"SELL", "REDEMPTION"} else shares
            securities = (SecurityMovement(stable_id("security", event_id), event_id, isin, quantity, (event_evidence,)),)
        fees = tuple(FeeEvent(stable_id("fee", event_id, kind), "trading", kind,
                              _decimal(match.group(1)), "EUR", _date(valuta.group(1)) if valuta else _date("01.01.1970"),
                              FeeEffect.INCLUDED_IN_SETTLEMENT, document.document_id,
                              "comdirect", transaction_id=event_id, evidence_ids=(ev("fee", match),))
                     for kind, pattern in FEE_PATTERNS for match in [re.search(pattern, text, re.I)] if match)
        components = tuple(TaxComponent(kind, _decimal(match.group(1)), "EUR")
                           for kind, pattern in TAX_PATTERNS for match in [re.search(pattern, text, re.I)] if match)
        taxes = (TaxEvent(stable_id("tax", event_id), event_id, "WITHHOLDING", components,
                          evidence_ids=(event_evidence,), isin=isin, bank_id="comdirect"),) if components else ()
        trades = ()
        if side in {"BUY", "SELL", "REDEMPTION"}:
            trades = (SecurityTrade(stable_id("trade", event_id), event_id, side, name, isin or MissingValue.NOT_FOUND,
                                    wkn, shares if shares is not None else MissingValue.NOT_FOUND,
                                    _date(trade_date.group(1)) if trade_date else MissingValue.NOT_FOUND,
                                    MissingValue.NOT_FOUND, _date(valuta.group(1)) if valuta else MissingValue.NOT_FOUND,
                                    _decimal(price.group("amount")) if price else MissingValue.NOT_FOUND,
                                    (price.group("c1") or price.group("c2")) if price and (price.group("c1") or price.group("c2")) else MissingValue.NOT_FOUND,
                                    _decimal(market.group("amount")) if market else MissingValue.NOT_FOUND,
                                    _decimal(gross.group("amount")) if gross else MissingValue.NOT_FOUND,
                                    _decimal(fx.group(1)) if fx else MissingValue.NOT_FOUND,
                                    _decimal(settlement.group("amount")) if settlement else MissingValue.NOT_FOUND,
                                    settlement.group("currency") if settlement else MissingValue.NOT_FOUND,
                                    evidence_ids=(event_evidence,)),)
        event = FinancialEvent(event_id, document.document_id, side,
                               _date(valuta.group(1)) if valuta else _date(trade_date.group(1)) if trade_date else None,
                               cash, securities, tax_events=taxes, fee_events=fees,
                               evidence_ids=(event_evidence,), trades=trades)
        return self._result(document, detection, evidence, (event,), tuple(issues))

    def _tax_notice(self, document, detection, evidence, ev, title_evidence):
        text = document.text
        isin_match = ISIN.search(text)
        components = tuple(TaxComponent(kind, _decimal(match.group(1)), "EUR")
                           for kind, pattern in TAX_PATTERNS for match in [re.search(pattern, text, re.I)] if match)
        date_match = re.search(r"(?:Valuta|Zufluss|Vorabpauschale).*?(" + DATE + r")", text, re.I)
        before = re.search(r"(?:Vorabpauschale|Investment-Aussch.ttung)\s*(?:[A-Z]{3})?\s*-?(" + AMOUNT + r")", text, re.I)
        basis = re.search(r"Steuerbemessungsgrundlage.*?(?:[A-Z]{3})\s*-?(" + AMOUNT + r")", text, re.I)
        event_id = stable_id("pp-event", document.document_id, detection.handler_id, isin_match.group(0) if isin_match else "")
        tax = TaxEvent(stable_id("tax", event_id), event_id, detection.handler_id.upper(), components,
                       evidence_ids=(title_evidence,), isin=isin_match.group(0) if isin_match else None,
                       bank_id="comdirect", tax_year=_date(date_match.group(1)).year if date_match else None,
                       accrual_date=_date(date_match.group(1)) if date_match else None,
                       assessment_basis=_decimal(basis.group(1)) if basis else MissingValue.NOT_FOUND,
                       advance_before_partial_exemption=_decimal(before.group(1)) if before else MissingValue.NOT_FOUND,
                       taxable_amount=_decimal(basis.group(1)) if basis else MissingValue.NOT_FOUND,
                       actually_withheld_tax=sum((x.amount for x in components), Decimal()))
        event = FinancialEvent(event_id, document.document_id,
                               "ADVANCE_TAX" if detection.handler_id == "vorabpauschale" else "TAX_NOTICE",
                               tax_events=(tax,), evidence_ids=(title_evidence,))
        calculations = ()
        if detection.handler_id == "vorabpauschale":
            calculations = (AdvanceTaxCalculation(tax.tax_event_id, MissingValue.UNKNOWN, MissingValue.UNKNOWN,
                                                   tax.assessment_basis, tax.advance_before_partial_exemption,
                                                   tax.taxable_amount, tax.actually_withheld_tax, components,
                                                   approval_status=TaxApprovalStatus.SYNTHETIC_ONLY,
                                                   rule_source_reference=f"PP {self.source_commit}"),)
        return self._result(document, detection, evidence, (event,), (), calculations)

    def _financial_report(self, document, detection, evidence, ev, title_evidence):
        events = []
        issues = []
        seen = set()
        # PP layouts use both signed trailing amounts and amount/currency columns.
        pattern = re.compile(r"(?m)^(?:A)?(?P<date>" + DATE + r")\s+(?P<text>.+?)\s+"
                             r"(?P<sign>[+-])?(?P<amount>" + AMOUNT + r")(?:\s+(?P<currency>[A-Z]{3}))?\s*$")
        for match in pattern.finditer(document.text):
            description = match.group("text").strip()
            if re.search(r"Alter Saldo|Neuer Saldo|Kontostand", description, re.I):
                continue
            currency = match.group("currency") or "EUR"
            amount = _decimal(match.group("amount"))
            sign = -1 if match.group("sign") == "-" or re.search(r"Lastschrift|Belastung|Entgelt|Geb.hr", description, re.I) else 1
            key = (match.group("date"), description, amount * sign, currency)
            eid = stable_id("pp-event", document.document_id, *key)
            row_evidence = ev("booking", match)
            if key in seen:
                issues.append(Issue(stable_id("issue", eid, "duplicate"), "PP_DUPLICATE_BOOKING",
                                    IssueSeverity.WARNING, "Duplicate Finanzreport booking.", row_evidence,
                                    eid, IssueNature.CONFIRMED_DEVIATION))
                continue
            seen.add(key)
            movement_type = CashMovementType.FEE_DEBIT if re.search(r"Entgelt|Geb.hr|Provision", description, re.I) else CashMovementType.TAX_DEBIT if re.search(r"Steuer", description, re.I) else CashMovementType.OTHER
            cash = CashMovement(stable_id("cash", eid), eid, amount * sign, currency,
                                CashStatus.ACTUAL, evidence_ids=(row_evidence,), movement_type=movement_type)
            events.append(FinancialEvent(eid, document.document_id, "CASH_BOOKING", _date(match.group("date")),
                                         (cash,), evidence_ids=(row_evidence,)))
        return self._result(document, detection, evidence, tuple(events), tuple(issues))

    def _result(self, document, detection, evidence, events, issues=(), calculations=()):
        return ParsedDocument(stable_id("result", document.document_id, self.metadata.plugin_id, self.metadata.version),
                              document.document_id, self.metadata.plugin_id, self.metadata.version,
                              detection.handler_id, events=events, evidence=tuple(evidence), issues=issues,
                              attributes={"rule_origin": f"Portfolio Performance {self.source_commit}",
                                          "source_license": self.source_license},
                              tax_calculations=calculations)


def title_pattern_for(handler):
    return next(pattern for name, pattern in TITLES if name == handler)
