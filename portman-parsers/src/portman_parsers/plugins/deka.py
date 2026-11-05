"""Independent Deka quartalsbericht / jahresdepotauszug parser.

No portfolio_v5, database, OCR or GUI dependency.
"""
from datetime import datetime
from decimal import Decimal
import re

from portman_parsers.api import (
    CashMovement, CashMovementType, CashStatus, Depot, DepotPosition,
    DepotSnapshot, DepotType, Detection, Evidence, FieldValue, FinancialEvent,
    Issue, IssueNature, IssueSeverity, ParsedDocument, SecurityMovement,
)
from portman_parsers.registry.allowlist import APPROVED_PLUGINS
from portman_parsers.utilities import stable_id

DATE = r"\d{2}\.\d{2}\.\d{4}"
AMOUNT = r"\d{1,3}(?:\.\d{3})*,\d{2}"
TITLE = re.compile(r"(Quartalsbericht|Jahresdepotauszug)\s+per\s+(" + DATE + r")")
OVERVIEW = re.compile(r"(?m)^\s*Depot(?:übersicht|�bersicht)\s*$")
TURNOVER = re.compile(r"(?m)^\s*Umsatz(?:übersicht|�bersicht|[-\xad�]Jahres(?:übersicht|�bersicht))(?:\s+Seite\s+\d+)?\s*$")
DEPOT = re.compile(r"Depot:\s*(\d{6,})")
ROW = re.compile(r"(?m)^\s*([A-Z]{2}[A-Z0-9]{9}\d)\s+(\d{2})\s+(\S.*?)\s+(" + AMOUNT + r")\s+[+-]" + AMOUNT + r"\s*$")
TOTAL = re.compile(r"Gesamt\s+in\s+EUR\s+(" + AMOUNT + r")\s+[+-]" + AMOUNT)
BLOCK = re.compile(r"ISIN:\s*([A-Z]{2}[A-Z0-9]{9}\d)\s+Unterdepot:\s*(\d+)")
STOCK = re.compile(r"Bestand\s+am\s+(" + DATE + r")\s+(" + AMOUNT + r")\s+([0-9.]+,\d+)\s+([0-9.]+,\d+)")
VALUATION = re.compile(r"Bewertung\s+mit\s+dem\s+Rücknahmepreis\s+vom\s+(" + DATE + r")")
DATED = re.compile(r"(?m)^([^\n]*" + DATE + r"\s+" + DATE + r")\s*$")
DISTRIBUTION = re.compile(
    r"(?:Ausschüttung\s*/\s*Kauf\s+aus\s+Ertrag|Abrechnungsbetrag\s+Ausschüttung)"
    r"\s+(" + AMOUNT + r")\s+([0-9.]+,\d+)\s+([+-][0-9.]+,\d+)"
    r"\s+(" + DATE + r")\s+(" + DATE + r")"
)


def number(value):
    return Decimal(value.replace(".", "").replace(",", "."))


def date(value):
    return datetime.strptime(value, "%d.%m.%Y").date()


class DekaParseError(ValueError):
    pass


class DekaQuartalsberichtPlugin:
    metadata = next(p for p in APPROVED_PLUGINS if p.plugin_id == "user.deka-quartalsbericht")

    def detect(self, document):
        if not (re.search(r"Deka", document.text, re.I)
                and TITLE.search(document.text) and OVERVIEW.search(document.text)):
            return ()
        return (Detection(self.metadata.plugin_id, self.metadata.version, "quartalsbericht",
                          "Deka Quartalsbericht/Jahresdepotauszug", Decimal("0.95"),
                          "Deka report title and depot overview"),)

    def parse(self, document, detection):
        if detection.handler_id != "quartalsbericht":
            raise DekaParseError("Unsupported Deka handler")
        title, depot_match = TITLE.search(document.text), DEPOT.search(document.text)
        if not title or not depot_match:
            raise DekaParseError("Deka report date or depot number missing")
        as_of, depot_number = date(title.group(2)), depot_match.group(1)
        depot_id = stable_id("depot", "deka", depot_number)
        evidence, issues, events, positions = [], [], [], []

        def ev(field, excerpt):
            page = next((p.number for p in document.pages if excerpt in p.text), None)
            if page is None:
                raise DekaParseError("Evidence not present on any PDF page: " + field)
            identifier = stable_id("evidence", document.document_id, page, field, excerpt)
            if not any(item.evidence_id == identifier for item in evidence):
                evidence.append(Evidence(identifier, document.document_id, page, field,
                                         excerpt, f"page:{page}", document.source_hash,
                                         self.metadata.plugin_id, detection.handler_id,
                                         self.metadata.version))
            return page, identifier

        def pdf(field, excerpt, value):
            page, eid = ev(field, excerpt)
            return FieldValue.from_pdf(value, page, eid)

        depot_evidence = pdf("depot_number", depot_match.group(0), depot_number)
        depot = Depot(depot_id, bank_name=FieldValue.manual("Deka Investments"),
                      depot_number=depot_evidence, base_currency=FieldValue.manual("EUR"),
                      depot_type=FieldValue.manual(DepotType.WERTPAPIER))
        overview = "\n".join(p.text for p in document.pages if OVERVIEW.search(p.text))
        rows = list(ROW.finditer(overview))
        match_total = TOTAL.search(overview)
        if not rows or not match_total:
            raise DekaParseError("Deka positions or documented total missing")
        expected = number(match_total.group(1))
        if sum((number(r.group(4)) for r in rows), Decimal(0)) != expected:
            raise DekaParseError("Deka overview holdings do not reconcile to stated total")

        # Repeated sub-depot headers on following pages belong to the same account.
        turnovers = {}
        turnover_text = "\n".join(page.text for page in document.pages if TURNOVER.search(page.text))
        blocks = list(BLOCK.finditer(turnover_text))
        for index, block in enumerate(blocks):
            end = blocks[index + 1].start() if index + 1 < len(blocks) else len(turnover_text)
            key = (block.group(1), block.group(2))
            turnovers.setdefault(key, []).append(turnover_text[block.start():end])

        for row in rows:
            isin, sub, name, value_text = row.groups()
            key, market_value = (isin, sub), number(value_text)
            parts = turnovers.get(key, [])
            body = "\n".join(parts)
            matching = [m for m in STOCK.finditer(body) if date(m.group(1)) == as_of]
            quantity = FieldValue.unknown()
            price = FieldValue.unknown()
            price_date = FieldValue.unknown()
            if len(matching) == 1:
                stock = matching[0]
                if number(stock.group(2)) != market_value:
                    raise DekaParseError("Deka sub-depot market value mismatch")
                quantity = pdf("quantity", stock.group(0), number(stock.group(4)))
                price = pdf("price", stock.group(0), number(stock.group(3)))
                valuation = VALUATION.search(body, stock.end())
                if valuation:
                    price_date = pdf("price_date", valuation.group(0), date(valuation.group(1)))
            else:
                issues.append(Issue(stable_id("issue", document.document_id, isin, sub, "quantity"),
                                    "DEKA_QUANTITY_UNVERIFIED", IssueSeverity.WARNING,
                                    "Sub-depot quantity at report date is not uniquely evidenced.",
                                    nature=IssueNature.MISSING_INFORMATION))
            positions.append(DepotPosition(
                stable_id("position", depot_id, isin, sub),
                pdf("security_id", row.group(0), isin), quantity,
                security_name=pdf("security_name", row.group(0), name),
                market_value=pdf("market_value", row.group(0), market_value),
                currency=FieldValue.manual("EUR"), price=price, price_date=price_date,
            ))

            # Preserve the old parser's economic semantics: distribution and reinvestment
            # are distinct linked EXPECTED movements, never actual account postings.
            for part in parts:
                for line in DATED.finditer(part):
                    dist = DISTRIBUTION.search(line.group(1))
                    if not dist:
                        issues.append(Issue(stable_id("issue", document.document_id, isin, sub, line.group(1)),
                                            "DEKA_TURNOVER_UNSUPPORTED", IssueSeverity.WARNING,
                                            "Non-distribution turnover line not imported.",
                                            nature=IssueNature.MISSING_INFORMATION))
                        continue
                    amount, shares = number(dist.group(1)), number(dist.group(3).lstrip("+"))
                    if not dist.group(3).startswith("+") or shares <= 0 or amount <= 0:
                        raise DekaParseError("Invalid Deka reinvestment amount or quantity")
                    when = date(dist.group(4))
                    excerpt = line.group(1)
                    _, eid = ev("distribution", excerpt)
                    basis = stable_id("deka-event", depot_id, sub, isin, when, amount, shares)
                    dividend_id = stable_id("event", basis, "dividend")
                    buy_id = stable_id("event", basis, "reinvestment")
                    if any(e.event_id in (dividend_id, buy_id) for e in events):
                        continue
                    events.append(FinancialEvent(
                        dividend_id, document.document_id, "DIVIDEND", when,
                        cash_movements=(CashMovement(stable_id("cash", dividend_id), dividend_id,
                                                    amount, "EUR", CashStatus.EXPECTED,
                                                    evidence_ids=(eid,), movement_type=CashMovementType.DIVIDEND_CREDIT),),
                        evidence_ids=(eid,), security_isin=isin,
                        security_identity_evidence_ids=(eid,)))
                    events.append(FinancialEvent(
                        buy_id, document.document_id, "REINVESTMENT", when,
                        cash_movements=(CashMovement(stable_id("cash", buy_id), buy_id,
                                                    -amount, "EUR", CashStatus.EXPECTED,
                                                    evidence_ids=(eid,), movement_type=CashMovementType.SECURITY_BUY),),
                        security_movements=(SecurityMovement(stable_id("security", buy_id), buy_id,
                                                             isin, shares, (eid,), depot_id=depot_id),),
                        evidence_ids=(eid,), security_isin=isin,
                        security_identity_evidence_ids=(eid,)))

        snapshot = DepotSnapshot(
            stable_id("snapshot", depot_id, as_of, document.document_id), depot_id,
            pdf("report_date", title.group(0), as_of), tuple(positions),
            pdf("total_value", match_total.group(0), expected), FieldValue.manual("EUR"))
        return ParsedDocument(stable_id("result", document.document_id, self.metadata.version),
                              document.document_id, self.metadata.plugin_id, self.metadata.version,
                              detection.handler_id, events=tuple(events), evidence=tuple(evidence),
                              issues=tuple(issues), depots=(depot,), depot_snapshots=(snapshot,))
