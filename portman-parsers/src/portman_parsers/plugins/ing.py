"""ING-Wertpapierbelege ohne Abhängigkeit zur Desktopanwendung."""

from datetime import datetime
from decimal import Decimal
import re

from portman_parsers.api import (
    CashMovement,
    CashMovementType,
    CashStatus,
    Depot,
    DepotPosition,
    DepotSnapshot,
    DepotType,
    Detection,
    Evidence,
    FeeEffect,
    FeeEvent,
    FieldValue,
    FinancialEvent,
    Issue,
    IssueNature,
    IssueSeverity,
    MissingValue,
    ParsedDocument,
    SecurityMovement,
    SecurityTrade,
    TaxComponent,
    TaxEvent,
)
from portman_parsers.registry.allowlist import APPROVED_PLUGINS
from portman_parsers.utilities import stable_id, valid_isin

DAY = r"\d{2}\.\d{2}\.\d{4}"
AMOUNT = r"\d[\d.]*(?:,\d+)?"
QTY = AMOUNT
SECURITY = re.compile(r"ISIN\s*\(WKN\)\s+([A-Z]{2}[A-Z0-9]{9}\d)\s*\(([A-Z0-9]{6})\)")
NAME = re.compile(r"Wertpapierbezeichnung\s+(.+?)\s*(?=Nominale)", re.S)
DEPOT = re.compile(r"Direkt-Depot\s*Nr\.:\s*(\d+)")
IBAN = re.compile(r"(?:Abrechnungs-IBAN|Gegenkonto)\s+(DE(?:[ \t]*\d){20})")
VALUTA = re.compile(r"Valuta\s+(" + DAY + r")")
TOTALS = {
    "dividendengutschrift": re.compile(r"Gesamtbetrag\s+zu\s+Ihren\s+Gunsten\s+([A-Z]{3})\s+(" + AMOUNT + r")"),
    "kauf": re.compile(r"Endbetrag\s+zu\s+Ihren\s+Lasten\s+([A-Z]{3})\s+(" + AMOUNT + r")"),
    "verkauf": re.compile(r"Endbetrag\s+zu\s+Ihren\s+Gunsten\s+([A-Z]{3})\s+(" + AMOUNT + r")"),
    "vorabpauschale": re.compile(r"Gesamtbetrag\s+zu\s+Ihren\s+Lasten\s+([A-Z]{3})\s*-?\s*(" + AMOUNT + r")"),
    "steuerverrechnung": re.compile(r"Erstattung/Belastung\s*\(-\)\s+(-)?\s*(" + AMOUNT + r")"),
}
TAXES = {
    "CAPITAL_GAINS_TAX": re.compile(r"Kapitalertragsteuer[^\n]*?EUR\s*-?\s*(" + AMOUNT + r")"),
    "SOLIDARITY_SURCHARGE": re.compile(r"Solidaritätszuschlag[^\n]*?EUR\s*-?\s*(" + AMOUNT + r")"),
    "CHURCH_TAX": re.compile(r"Kirchensteuer[^\n]*?EUR\s*-?\s*(" + AMOUNT + r")"),
}
STATEMENT_ROW = re.compile(r"(?m)^[ \t]*(" + QTY + r")[ \t]+Stück[ \t]+(\S.*?)[ \t]+([0-9.]+,\d+)[ \t]+[A-Z]{3}[ \t]+(" + AMOUNT + r")[ \t]+EUR[ \t]*$")
STATEMENT_ISIN = re.compile(r"ISIN\s*\(WKN\):\s*([A-Z]{2}[A-Z0-9]{9}\d)\s*\(([A-Z0-9]{6})\)")
REFERENCE = re.compile(
    r"(?:End-to-End-(?:Ref(?:erenz)?\.?)|Buchungsreferenz|Kundenreferenz|Mandatsreferenz|Vorgangs(?:nummer|-Nr\.)|Transaktions(?:nummer|-Nr\.)|Referenz(?:-Nr\.)?)(?=\s|:|$)\s*:?[ \t]*([^\r\n]+)",
    re.I,
)


def number(value):
    return Decimal(value.replace(".", "").replace(",", "."))


def day(value):
    return datetime.strptime(value, "%d.%m.%Y").date()


def required(pattern, text, label):
    match = pattern.search(text) if hasattr(pattern, "search") else re.search(pattern, text, re.M)
    if not match:
        raise ValueError(f"ING-Beleg: {label} fehlt oder ist mehrdeutig")
    return match


class IngPlugin:
    metadata = next(item for item in APPROVED_PLUGINS if item.plugin_id == "user.ing-wertpapiere")

    def detect(self, document):
        text = document.text
        if not re.search(r"ING-DiBa|ing\.de", text):
            return ()
        choices = (
            ("dividendengutschrift", bool(re.search(r"(?m)^\s*Dividendengutschrift\s*$", text))),
            ("kauf", bool(re.search(r"Wertpapierabrechnung\s+Kauf", text))),
            ("verkauf", bool(re.search(r"Wertpapierabrechnung\s+Verkauf", text))),
            ("vorabpauschale", bool(re.search(r"(?m)^\s*Vorabpauschale\s*$", text))),
            ("steuerverrechnung", bool(re.search(r"Verlustverrechnung", text, re.I))),
            ("jahresdepotauszug", bool(re.search(r"(?m)^\s*Jahresdepotauszug\s*$", text))),
        )
        found = [handler for handler, title in choices if title and (handler == "jahresdepotauszug" or TOTALS[handler].search(text))]
        if len(found) != 1:
            return ()
        handler = found[0]
        label = next(item.document_type for item in self.metadata.handlers if item.handler_id == handler)
        return (Detection(self.metadata.plugin_id, self.metadata.version, handler, label, Decimal("0.98"), "ING-DiBa und Belegart erkannt"),)

    def parse(self, document, detection):
        handler = detection.handler_id
        text = document.text
        depot_match = DEPOT.search(text)
        if not depot_match and handler != "dividendengutschrift":
            raise ValueError("ING-Depotnummer nicht erkannt")
        evidence = []

        def ev(field, excerpt, page=None):
            source = next((p for p in document.pages if (page is None or p.number == page) and excerpt in p.text), None)
            if source is None:
                raise ValueError(f"ING-Evidence fehlt auf der Originalseite: {field}")
            identity = stable_id("evidence", document.document_id, source.number, field, excerpt)
            if not any(item.evidence_id == identity for item in evidence):
                evidence.append(
                    Evidence(
                        identity,
                        document.document_id,
                        source.number,
                        field,
                        excerpt,
                        f"page:{source.number}",
                        document.source_hash,
                        self.metadata.plugin_id,
                        handler,
                        self.metadata.version,
                    )
                )
            return identity, source.number

        depot_id = stable_id("depot", "ing", depot_match.group(1)) if depot_match else None
        depots = ()
        if depot_match:
            eid, page = ev("depot_number", depot_match.group(0))
            depots = (
                Depot(
                    depot_id,
                    bank_name=FieldValue.manual("ING"),
                    depot_number=FieldValue.from_pdf(depot_match.group(1), page, eid),
                    base_currency=FieldValue.manual("EUR"),
                    depot_type=FieldValue.manual(DepotType.WERTPAPIER),
                ),
            )
        if handler == "jahresdepotauszug":
            snapshots, events, issues = (self._statement(document, depot_id, ev),), (), ()
        else:
            event, issues = self._event(document, handler, depot_id, ev)
            snapshots, events = (), (event,)
        attributes = self._attributes(document, handler, ev)
        return ParsedDocument(
            stable_id("result", document.document_id, self.metadata.version),
            document.document_id,
            self.metadata.plugin_id,
            self.metadata.version,
            handler,
            events=events,
            evidence=tuple(evidence),
            depots=depots,
            depot_snapshots=snapshots,
            issues=issues,
            attributes=attributes,
        )

    def _attributes(self, document, handler, ev):
        """V09-Zusatzfelder ohne eigene Kern-DTO-Spalte mit Originalbeleg bewahren."""
        if handler == "jahresdepotauszug":
            values = {}
            for page in document.pages:
                isin = None
                for line in page.text.splitlines():
                    found = STATEMENT_ISIN.search(line)
                    if found:
                        isin = found.group(1)
                        continue
                    custody = re.match(r"^[ \t]*(Verwahrart|Lagerland):\s*(\S.*?)\s*$", line)
                    if custody and isin:
                        field = "custody_type" if custody.group(1) == "Verwahrart" else "custody_country"
                        key = f"position.{isin}.{field}"
                        ev(key, custody.group(0).strip(), page.number)
                        values[key] = custody.group(2)
            return values
        text = document.text
        if handler in {"kauf", "verkauf"}:
            patterns = {
                "order_id": (r"Ordernummer\s+([0-9.]+)", 1),
                "venue": (r"Handelsplatz\s+(\S[^\n]*?)\s*(?:\n|$)", 1),
                "execution_time": (r"Ausführungstag(?:\s*/\s*-zeit)?\s+" + DAY + r"\s+um\s+(\d{2}:\d{2}:\d{2})", 1),
            }
            title = re.search(r"Wertpapierabrechnung\s+(?:Kauf|Verkauf)[^\n]*", text)
            values = self._matched_attributes(text, patterns, ev)
            if "venue" in values:
                values["venue"] = " ".join(values["venue"].split())
            if title:
                if "Sparplan" in title.group(0):
                    ev("order_subtype", title.group(0))
                    values["order_subtype"] = "sparplan"
                elif "Wiederanlage" in title.group(0):
                    ev("order_subtype", title.group(0))
                    values["order_subtype"] = "wiederanlage"
            return values
        if handler == "vorabpauschale":
            return self._matched_attributes(
                text,
                {
                    "per_unit": (r"Vorabpauschale\s+pro\s+Stück\s+EUR\s+(" + AMOUNT + r")", 1),
                    "taxable_income": (r"KapSt-pflichtiger\s+Kapitalertrag\s+(" + AMOUNT + r")\s+EUR", 1),
                    "partial_exemption_amount": (r"Teilfreistellung[^\n]*?(" + AMOUNT + r")\s+EUR", 1),
                    "allowance_before": (r"Sparer-Pauschbetrag\s+vor\s+Ertrag\s+(" + AMOUNT + r")\s+EUR", 1),
                    "allowance_after": (r"Sparer-Pauschbetrag\s+nach\s+Ertrag\s+(" + AMOUNT + r")\s+EUR", 1),
                },
                ev,
            )
        if handler != "dividendengutschrift":
            return {}
        patterns = {
            "quantity": (r"Nominale\s+(" + QTY + r")\s+Stück", 1),
            "ex_date": (r"Ex-Tag\s+(" + DAY + r")", 1),
            "pay_date": (r"Zahltag\s+(" + DAY + r")", 1),
            "per_share_amount": (r"Zins-/Dividendensatz\s+([0-9.]+,\d+)\s+[A-Z]{3}", 1),
            "per_share_currency": (r"Zins-/Dividendensatz\s+[0-9.]+,\d+\s+([A-Z]{3})", 1),
            "gross_income": (r"Brutto\s+[A-Z]{3}\s+(" + AMOUNT + r")", 1),
            "gross_currency": (r"Brutto\s+([A-Z]{3})\s+" + AMOUNT, 1),
            "fx_rate": (r"Umg\.\s*z\.\s*Dev\.-Kurs\s*\(([0-9.,]+)\)", 1),
            "withholding_tax": (r"QuSt\s+[\d,]+\s*%\s*\(EUR\s+(" + AMOUNT + r")\)", 1),
            "taxable_income": (r"KapSt-pflichtiger\s+Kapitalertrag\s+(" + AMOUNT + r")\s+EUR", 1),
            "creditable_withholding": (r"Anrechenbare\s+ausländische\s+Quellensteuer\s+(" + AMOUNT + r")\s+EUR", 1),
            "allowance_before": (r"Sparer-Pauschbetrag\s+vor\s+Ertrag\s+(" + AMOUNT + r")\s+EUR", 1),
            "allowance_after": (r"Sparer-Pauschbetrag\s+nach\s+Ertrag\s+(" + AMOUNT + r")\s+EUR", 1),
            "withholding_pot_before": (r"Verrechnungstopf\s+ausländ\.\s+Quellenst\.\s+vor\s+Ertrag\s+(" + AMOUNT + r")\s+EUR", 1),
            "withholding_pot_after": (r"Verrechnungstopf\s+ausländ\.\s+Quellenst\.\s+nach\s+Ertrag\s+(" + AMOUNT + r")\s+EUR", 1),
        }
        values = self._matched_attributes(text, patterns, ev)
        if values.get("gross_currency") and values["gross_currency"] != "EUR" and values.get("fx_rate"):
            values["original_amount"] = values["gross_income"]
            values["original_currency"] = values["gross_currency"]
        return values

    @staticmethod
    def _matched_attributes(text, patterns, ev):
        values = {}
        for field, (pattern, group) in patterns.items():
            match = re.search(pattern, text)
            if match:
                ev(field, match.group(0))
                values[field] = match.group(group)
        return values

    def _event(self, document, handler, depot_id, ev):
        text = document.text
        total_pattern = TOTALS[handler]
        located = [(page, match) for page in document.pages for match in total_pattern.finditer(page.text)]
        if len(located) != 1:
            raise ValueError("Genau ein ING-Abrechnungsbetrag pro PDF erwartet")
        total_page, total = located[0]
        total_ev, _ = ev("settlement", total.group(0), total_page.number)
        if handler == "steuerverrechnung":
            return self._tax_settlement(document, total, total_ev, depot_id, ev), ()
        if total.group(1) != "EUR":
            raise ValueError("ING-Abrechnung nicht in EUR")
        sec = required(SECURITY, text, "ISIN/WKN")
        isin, wkn = sec.group(1, 2)
        if not valid_isin(isin):
            raise ValueError("Ungültige ING-ISIN")
        name = " ".join(required(NAME, text, "Wertpapierbezeichnung").group(1).split())
        iban = required(IBAN, text, "Abrechnungs-IBAN")
        account = "IBAN " + re.sub(r"\s+", "", iban.group(1))
        valued = required(VALUTA, text, "Valuta")
        value_date = day(valued.group(1))
        amount = number(total.group(2))
        sec_ev, _ = ev("security", sec.group(0))
        iban_ev, _ = ev("account", iban.group(0))
        value_ev, _ = ev("value_date", valued.group(0))
        reference = REFERENCE.search(text)
        ref_ev = ev("reference", reference.group(0))[0] if reference else None
        ref = reference.group(1).strip() if reference else None
        quantity_pattern = r"Nominale\s+(?:Stück\s+)?(" + QTY + r")\s*(?:Stück)?"
        quantity_match = required(quantity_pattern, text, "Stückzahl")
        quantity = number(quantity_match.group(1))
        if quantity <= 0:
            raise ValueError("ING-Stückzahl muss positiv sein")
        qty_ev, _ = ev("quantity", quantity_match.group(0))
        order_identity = re.search(r"Ordernummer\s+([0-9.]+)", text)
        identity = order_identity.group(1) if order_identity else (account, isin, value_date, amount, quantity)
        event_id = stable_id("event", "ing", handler, depot_id or account, identity, isin)
        cash_id = stable_id("cash", event_id)
        sign = -1 if handler in {"kauf", "vorabpauschale"} else 1
        cash = CashMovement(
            cash_id,
            event_id,
            sign * amount,
            "EUR",
            CashStatus.EXPECTED,
            account_ref=account,
            evidence_ids=(total_ev, iban_ev),
            movement_type={
                "kauf": CashMovementType.SECURITY_BUY,
                "verkauf": CashMovementType.SECURITY_SELL,
                "dividendengutschrift": CashMovementType.DIVIDEND_CREDIT,
                "vorabpauschale": CashMovementType.TAX_DEBIT,
            }[handler],
        )
        if handler in {"kauf", "verkauf"}:
            return self._trade(
                document, handler, event_id, depot_id, name, isin, wkn, quantity, value_date, amount, cash, sec_ev, qty_ev, total_ev, value_ev, ref, ref_ev, ev
            )
        if handler == "dividendengutschrift":
            return self._dividend(
                document, event_id, depot_id, name, isin, wkn, quantity, value_date, amount, cash, sec_ev, qty_ev, total_ev, value_ev, ref, ref_ev, ev
            )
        return self._advance(
            document, event_id, depot_id, name, isin, wkn, quantity, value_date, amount, cash, sec_ev, qty_ev, total_ev, value_ev, ref, ref_ev, ev
        )

    def _trade(
        self, document, handler, event_id, depot_id, name, isin, wkn, quantity, valued, amount, cash, sec_ev, qty_ev, total_ev, value_ev, ref, ref_ev, ev
    ):
        text = document.text
        order = required(r"Ordernummer\s+([0-9.]+)", text, "Ordernummer")
        execution = required(r"Ausführungstag(?:\s*/\s*-zeit)?\s+(" + DAY + r")", text, "Ausführungstag")
        traded = day(execution.group(1))
        order_ev, _ = ev("order", order.group(0))
        execution_ev, _ = ev("trade_date", execution.group(0))
        gross_match = re.search(r"Kurswert\s+EUR\s+(" + AMOUNT + r")", text)
        price_match = re.search(r"\bKurs(?:[ \t]*\([^)\n]*\))?\s+EUR\s+(" + AMOUNT + r")", text)
        gross = number(gross_match.group(1)) if gross_match else None
        price = number(price_match.group(1)) if price_match else None
        gross_ev = ev("market_value", gross_match.group(0))[0] if gross_match else None
        price_ev = ev("price", price_match.group(0))[0] if price_match else None
        issues = []
        if gross is not None and price is not None and abs(price * quantity - gross) > Decimal("0.02"):
            issues.append(self._issue(document, event_id, "ING_KURS_ABWEICHUNG", "Kurs mal Stückzahl passt nicht zum Kurswert; Original prüfen", gross_ev))
        components, tax_evs = self._taxes(text, ev)
        tax_total = sum((item.amount for item in components), Decimal())
        fees = None
        fee_events = ()
        if gross is not None:
            diff = amount - gross if handler == "kauf" else gross - amount
            fees = diff - tax_total
            if diff < 0 or fees < 0:
                raise ValueError("ING-Endbetrag, Kurswert und Steuerkomponenten widersprechen sich")
            if fees:
                fee_match = re.search(r"Provision\s+EUR\s+(" + AMOUNT + r")", text)
                fee_ev = ev("fee", fee_match.group(0))[0] if fee_match else gross_ev
                fee_events = (
                    FeeEvent(
                        stable_id("fee", event_id),
                        "trading",
                        "provision" if fee_match else "entgelt",
                        fees,
                        "EUR",
                        traded,
                        FeeEffect.INCLUDED_IN_SETTLEMENT,
                        document.document_id,
                        "ing",
                        depot_id=depot_id,
                        transaction_id=event_id,
                        cash_movement_id=cash.movement_id,
                        evidence_ids=(fee_ev,),
                    ),
                )
                issues.append(
                    self._issue(
                        document, event_id, "ING_ENTGELT_UEBERNOMMEN", "Endbetrag weicht vom Kurswert ab; nach Steuerabzug als Entgelt übernommen", fee_ev
                    )
                )
            elif tax_total:
                issues.append(
                    self._issue(document, event_id, "ING_STEUER_UEBERNOMMEN", "Endbetragsabweichung ist vollständig durch Steuern belegt", tax_evs[0])
                )
        tax_events = self._tax_event(event_id, depot_id, isin, traded, valued, cash.movement_id, components, tax_evs, "TRADE_TAX")
        trade = SecurityTrade(
            stable_id("trade", event_id),
            event_id,
            "BUY" if handler == "kauf" else "SELL",
            security_name=name,
            isin=isin,
            wkn=wkn,
            quantity=quantity,
            trade_date=traded,
            value_date=valued,
            price=price if price is not None else MissingValue.UNKNOWN,
            price_currency="EUR" if price is not None else MissingValue.UNKNOWN,
            market_value=gross if gross is not None else MissingValue.UNKNOWN,
            gross_amount=gross if gross is not None else MissingValue.UNKNOWN,
            settlement_amount=amount,
            settlement_currency="EUR",
            depot_id=depot_id,
            evidence_ids=tuple(x for x in (qty_ev, gross_ev, price_ev, total_ev, execution_ev) if x),
        )
        movement = SecurityMovement(stable_id("security", event_id), event_id, isin, quantity if handler == "kauf" else -quantity, (qty_ev,), depot_id)
        event = FinancialEvent(
            event_id,
            document.document_id,
            "BUY" if handler == "kauf" else "SELL",
            traded,
            cash_movements=(cash,),
            security_movements=(movement,),
            trades=(trade,),
            fee_events=fee_events,
            tax_events=tax_events,
            evidence_ids=tuple(x for x in (sec_ev, qty_ev, total_ev, value_ev, order_ev, execution_ev, gross_ev, price_ev, ref_ev, *tax_evs) if x),
            security_name=name,
            security_wkn=wkn,
            security_isin=isin,
            security_identity_evidence_ids=(sec_ev,),
            bank_reference=ref or MissingValue.UNKNOWN,
            bank_reference_status="RECOGNIZED" if ref else "MISSING",
            bank_reference_evidence_ids=(ref_ev,) if ref_ev else (),
        )
        if gross is None:
            issues.append(self._issue(document, event_id, "ING_KURSWERT_FEHLT", "Kurswert fehlt; Entgelt nicht prüfbar", total_ev))
        return event, tuple(issues)

    def _taxes(self, text, ev):
        components, ids = [], []
        for kind, pattern in TAXES.items():
            match = pattern.search(text)
            if match and number(match.group(1)):
                components.append(TaxComponent(kind, number(match.group(1)), "EUR"))
                ids.append(ev("tax", match.group(0))[0])
        return tuple(components), tuple(ids)

    def _tax_event(self, event_id, depot_id, isin, booked, valued, cash_id, components, tax_evs, kind, taxable=None):
        if not components:
            return ()
        return (
            TaxEvent(
                stable_id("tax", event_id),
                event_id,
                kind,
                components,
                taxable_basis=taxable,
                cash_movement_id=cash_id,
                evidence_ids=tax_evs,
                depot_id=depot_id,
                isin=isin,
                tax_year=booked.year,
                booking_date=booked,
                value_date=valued,
                bank_id="ing",
                actually_withheld_tax=sum((item.amount for item in components), Decimal()),
            ),
        )

    def _issue(self, document, event_id, code, message, evidence_id):
        return Issue(
            stable_id("issue", document.document_id, code), code, IssueSeverity.WARNING, message, evidence_id, event_id, IssueNature.MISSING_INFORMATION
        )

    def _dividend(self, document, event_id, depot_id, name, isin, wkn, quantity, valued, amount, cash, sec_ev, qty_ev, total_ev, value_ev, ref, ref_ev, ev):
        text = document.text
        withholding = re.search(r"QuSt\s+([\d,]+)\s*%\s*\(EUR\s+(" + AMOUNT + r")\)\s+([A-Z]{3})\s+(" + AMOUNT + r")", text)
        components = (TaxComponent("WITHHOLDING_TAX", number(withholding.group(2)), "EUR"),) if withholding else ()
        tax_ev = ev("withholding_tax", withholding.group(0))[0] if withholding else None
        taxable = re.search(r"KapSt-pflichtiger\s+Kapitalertrag\s+(" + AMOUNT + r")\s+EUR", text)
        taxable_ev = ev("taxable_income", taxable.group(0))[0] if taxable else None
        taxes = self._tax_event(
            event_id,
            depot_id,
            isin,
            valued,
            valued,
            cash.movement_id,
            components,
            tuple(x for x in (tax_ev, taxable_ev) if x),
            "WITHHOLDING_TAX" if withholding else "INCOME_TAX_STATUS",
            number(taxable.group(1)) if taxable else None,
        )
        if taxable and not taxes:
            taxes = (
                TaxEvent(
                    stable_id("tax", event_id),
                    event_id,
                    "INCOME_TAX_STATUS",
                    taxable_basis=number(taxable.group(1)),
                    evidence_ids=(taxable_ev,),
                    depot_id=depot_id,
                    isin=isin,
                    tax_year=valued.year,
                    booking_date=valued,
                    value_date=valued,
                    bank_id="ing",
                ),
            )
        gross = re.search(r"Brutto\s+([A-Z]{3})\s+(" + AMOUNT + r")", text)
        fx = re.search(r"Umg\.\s*z\.\s*Dev\.-Kurs\s*\(([0-9.,]+)\)", text)
        issues = []
        subtotal = re.search(r"Zwischensumme\s+([A-Z]{3})\s+(" + AMOUNT + r")", text)
        if subtotal and fx and abs(number(subtotal.group(2)) / number(fx.group(1)) - amount) > Decimal("0.015"):
            subtotal_ev = ev("subtotal", subtotal.group(0))[0]
            issues.append(
                self._issue(
                    document, event_id, "ING_FX_ZWISCHENSUMME", "Gesamtbetrag passt nicht zu Zwischensumme und Devisenkurs; Original prüfen", subtotal_ev
                )
            )
        if gross and gross.group(1) != "EUR" and fx:
            expected = number(gross.group(2)) / number(fx.group(1))
            if abs(expected - amount - sum((x.amount for x in components), Decimal())) > Decimal("0.02"):
                issues.append(
                    self._issue(document, event_id, "ING_FX_ABWEICHUNG", "Brutto, Devisenkurs und Quellensteuer weichen vom Gesamtbetrag ab", total_ev)
                )
        if re.search(r"automatisch\s+wieder\s+an", text):
            issues.append(self._issue(document, event_id, "ING_WIEDERANLAGE", "Wiederanlage separat belegt; keinen zweiten Cashflow erzeugen", total_ev))
        event = FinancialEvent(
            event_id,
            document.document_id,
            "DIVIDEND",
            valued,
            cash_movements=(cash,),
            tax_events=taxes,
            evidence_ids=tuple(x for x in (sec_ev, qty_ev, total_ev, value_ev, tax_ev, taxable_ev, ref_ev) if x),
            security_name=name,
            security_wkn=wkn,
            security_isin=isin,
            security_identity_evidence_ids=(sec_ev,),
            bank_reference=ref or MissingValue.UNKNOWN,
            bank_reference_status="RECOGNIZED" if ref else "MISSING",
            bank_reference_evidence_ids=(ref_ev,) if ref_ev else (),
        )
        return event, tuple(issues)

    def _advance(self, document, event_id, depot_id, name, isin, wkn, quantity, valued, amount, cash, sec_ev, qty_ev, total_ev, value_ev, ref, ref_ev, ev):
        text = document.text
        per_unit = required(r"Vorabpauschale\s+pro\s+Stück\s+EUR\s+(" + AMOUNT + r")", text, "Vorabpauschale je Stück")
        taxable = required(r"KapSt-pflichtiger\s+Kapitalertrag\s+(" + AMOUNT + r")\s+EUR", text, "steuerpflichtiger Ertrag")
        components, tax_evs = self._taxes(text, ev)
        if abs(sum((x.amount for x in components), Decimal()) - amount) > Decimal("0.01"):
            raise ValueError("ING-Steuerkomponenten passen nicht zur Vorabpauschalen-Belastung")
        unit_ev = ev("advance_per_unit", per_unit.group(0))[0]
        basis_ev = ev("taxable_basis", taxable.group(0))[0]
        taxes = self._tax_event(
            event_id, depot_id, isin, valued, valued, cash.movement_id, components, (*tax_evs, unit_ev, basis_ev), "ADVANCE_TAX", number(taxable.group(1))
        )
        event = FinancialEvent(
            event_id,
            document.document_id,
            "ADVANCE_TAX",
            valued,
            cash_movements=(cash,),
            tax_events=taxes,
            evidence_ids=tuple(x for x in (sec_ev, qty_ev, total_ev, value_ev, ref_ev, unit_ev, basis_ev, *tax_evs) if x),
            security_name=name,
            security_wkn=wkn,
            security_isin=isin,
            security_identity_evidence_ids=(sec_ev,),
            bank_reference=ref or MissingValue.UNKNOWN,
            bank_reference_status="RECOGNIZED" if ref else "MISSING",
            bank_reference_evidence_ids=(ref_ev,) if ref_ev else (),
        )
        return event, ()

    def _tax_settlement(self, document, total, total_ev, depot_id, ev):
        text = document.text
        iban = required(IBAN, text, "Gegenkonto")
        valued = required(VALUTA, text, "Valuta")
        amount = number(total.group(2))
        components, tax_evs = self._taxes(text, ev)
        if not components or abs(sum((x.amount for x in components), Decimal()) - amount) > Decimal("0.01"):
            raise ValueError("ING-Steuerkomponenten passen nicht zum Erstattungs-/Belastungsbetrag")
        account = "IBAN " + re.sub(r"\s+", "", iban.group(1))
        booked = day(valued.group(1))
        iban_ev = ev("account", iban.group(0))[0]
        value_ev = ev("value_date", valued.group(0))[0]
        reference = REFERENCE.search(text)
        ref = reference.group(1).strip() if reference else None
        ref_ev = ev("reference", reference.group(0))[0] if reference else None
        charge = bool(total.group(1))
        event_id = stable_id("event", "ing-tax-settlement", depot_id, account, booked, charge, amount, ref)
        cash_id = stable_id("cash", event_id)
        cash = CashMovement(
            cash_id,
            event_id,
            -amount if charge else amount,
            "EUR",
            CashStatus.EXPECTED,
            account_ref=account,
            evidence_ids=(total_ev, iban_ev),
            movement_type=CashMovementType.TAX_DEBIT if charge else CashMovementType.TAX_REFUND,
        )
        taxes = self._tax_event(event_id, depot_id, None, booked, booked, cash_id, components, tax_evs, "TAX_CHARGE" if charge else "TAX_REFUND")
        return FinancialEvent(
            event_id,
            document.document_id,
            "TAX" if charge else "TAX_REFUND",
            booked,
            cash_movements=(cash,),
            tax_events=taxes,
            evidence_ids=tuple(x for x in (total_ev, iban_ev, value_ev, ref_ev, *tax_evs) if x),
            bank_reference=ref or MissingValue.UNKNOWN,
            bank_reference_status="RECOGNIZED" if ref else "MISSING",
            bank_reference_evidence_ids=(ref_ev,) if ref_ev else (),
        )

    def _statement(self, document, depot_id, ev):
        if any(page.extraction_method == "ocr_required" for page in document.pages):
            raise ValueError("ING-Depotauszug benötigt eingebetteten Text")
        text = document.text
        dated = required(r"zum\s+(" + DAY + r")\s+abgeschlossene\s+Aufstellung", text, "Bestandsstichtag")
        as_of = day(dated.group(1))
        positions, running = [], Decimal()
        for page in document.pages:
            current = None
            for line in page.text.splitlines():
                row = STATEMENT_ROW.match(line)
                if row:
                    if current is not None:
                        raise ValueError("ING-Position ohne ISIN")
                    current = row
                    continue
                isin_match = STATEMENT_ISIN.search(line)
                if isin_match and current is not None:
                    isin, wkn = isin_match.group(1, 2)
                    if not valid_isin(isin):
                        raise ValueError("Ungültige ING-Bestands-ISIN")
                    qty, price, value = number(current.group(1)), number(current.group(3)), number(current.group(4))
                    row_ev = ev("depot_position", current.group(0).strip(), page.number)[0]
                    isin_ev = ev("position_isin", isin_match.group(0), page.number)[0]
                    pdf = lambda value: FieldValue.from_pdf(value, page.number, row_ev)
                    positions.append(
                        DepotPosition(
                            stable_id("position", depot_id, isin),
                            FieldValue.from_pdf(isin, page.number, isin_ev),
                            pdf(qty),
                            security_name=pdf(" ".join(current.group(2).split())),
                            market_value=pdf(value),
                            currency=pdf("EUR"),
                            price=pdf(price),
                            price_date=pdf(as_of),
                        )
                    )
                    running += value
                    current = None
            if current is not None:
                raise ValueError("ING-Position am Seitenende ohne ISIN")
            carry = re.search(r"Übertrag\s+Kurswert\s+(" + AMOUNT + r")\s+EUR", page.text)
            if carry and abs(running - number(carry.group(1))) > Decimal("0.005"):
                raise ValueError("ING-Seitenübertrag stimmt nicht mit Positionen überein")
        total = required(r"Gesamtkurswert\s+(" + AMOUNT + r")\s+EUR", text, "Gesamtkurswert")
        count = re.search(r"Anzahl\s+Posten:\s*(\d+)", text)
        if not positions or len({p.security_id.value for p in positions}) != len(positions):
            raise ValueError("Keine eindeutigen ING-Positionen")
        if abs(running - number(total.group(1))) > Decimal("0.005") or (count and int(count.group(1)) != len(positions)):
            raise ValueError("ING-Positionssumme oder Anzahl stimmt nicht mit dem Auszug überein")
        total_ev, total_page = ev("depot_total", total.group(0))
        date_ev, date_page = ev("snapshot_date", dated.group(0))
        return DepotSnapshot(
            stable_id("snapshot", depot_id, as_of, document.document_id),
            depot_id,
            FieldValue.from_pdf(as_of, date_page, date_ev),
            tuple(positions),
            FieldValue.from_pdf(number(total.group(1)), total_page, total_ev),
            FieldValue.from_pdf("EUR", total_page, total_ev),
        )
