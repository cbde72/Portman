"""Baader-/finanzen.net-zero-Wertpapierbelege; Krypto ist bewusst ausgeschlossen."""

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
    ParsedDocument,
    SecurityMovement,
    SecurityTrade,
    TaxComponent,
    TaxEvent,
)
from portman_parsers.registry.allowlist import APPROVED_PLUGINS
from portman_parsers.utilities import stable_id, valid_isin

NUM = r"\d[\d.]*(?:,\d+)?"
DAY = r"\d{2}\.\d{2}\.\d{4}"
DEPOT = re.compile(r"Depot-Nr\.:\s*(\d+)")
REF = re.compile(r"Referenz-Nr\.:\s*(\d+)")
SEC = re.compile(r"Nominale\s+ISIN:\s*([A-Z0-9]{12})\s+WKN:\s*(\w{6})[^\n]*\n\s*STK\s+(" + NUM + r")\s+([^\n]+)")
POS = re.compile(r"(?m)^\s*Stück\s+(" + NUM + r")\s+WKN:\s*(\w{6})\s+([A-Z]{3})\s+(" + NUM + r")\s+(" + NUM + r")\s+(?:([A-Z]{3})\s*)?$")
TOTAL = re.compile(r"Depotwert\s+(" + NUM + r")\s+EUR")
REVERSAL = {"26172813": ("524443206", "526758625", "US0378331005", Decimal("4.125"), Decimal("0.78"), Decimal("0.14"))}


def money(value):
    return Decimal(value.replace(".", "").replace(",", "."))


def date(value):
    return datetime.strptime(value, "%d.%m.%Y").date()


def required(pattern, text, label):
    found = pattern.search(text) if hasattr(pattern, "search") else re.search(pattern, text, re.M)
    if not found:
        raise ValueError(f"Baader-Beleg: {label} fehlt oder hat ein unbekanntes Format")
    return found


class BaaderPlugin:
    metadata = next(item for item in APPROVED_PLUGINS if item.plugin_id == "baader.pdf")

    def detect(self, document):
        text = document.text
        if "Baader Bank" not in text or not DEPOT.search(text) or re.search(r"Krypto|Bitcoin|Ethereum", text, re.I):
            return ()
        pairs = (
            ("quartalsaufstellung", "Quartalsaufstellung"),
            ("jahresdepotauszug", "Depotauszug per"),
            ("dividende", "Dividendenabrechnung"),
            ("vorabpauschale", "Vorabpauschale"),
            ("depotuebertrag", "Depoteinlieferung" if "Depoteinlieferung" in text else "Depotauslieferung"),
            ("wertpapierabrechnung", "Wertpapierabrechnung:"),
        )
        handler = next((key for key, marker in pairs if marker in text), None)
        if not handler:
            return ()
        label = next(item.document_type for item in self.metadata.handlers if item.handler_id == handler)
        return (
            Detection(self.metadata.plugin_id, self.metadata.version, handler, label, Decimal("0.99"), "Baader Bank, Depotnummer und Dokumenttitel erkannt"),
        )

    def parse(self, document, detection):
        depot_match = required(DEPOT, document.text, "Depotnummer")
        depot_no = depot_match.group(1)
        depot_id = stable_id("depot", "baader", depot_no)
        evidences = []

        def evidence(field, excerpt, page=None):
            source = next((p for p in document.pages if (page is None or p.number == page) and excerpt in p.text), None)
            if not source:
                raise ValueError(f"Baader-Evidence fehlt auf der Originalseite: {field}")
            identity = stable_id("evidence", document.document_id, source.number, field, excerpt)
            if not any(item.evidence_id == identity for item in evidences):
                evidences.append(
                    Evidence(
                        identity,
                        document.document_id,
                        source.number,
                        field,
                        excerpt,
                        f"page:{source.number}",
                        document.source_hash,
                        self.metadata.plugin_id,
                        detection.handler_id,
                        self.metadata.version,
                    )
                )
            return identity, source.number

        depot_ev, depot_page = evidence("depot_number", depot_match.group(0))
        depot = Depot(
            depot_id,
            bank_name=FieldValue.manual("Baader Bank"),
            depot_name=FieldValue.manual("finanzen.net zero Depot"),
            depot_number=FieldValue.from_pdf(depot_no, depot_page, depot_ev),
            base_currency=FieldValue.manual("EUR"),
            depot_type=FieldValue.manual(DepotType.WERTPAPIER),
        )
        if detection.handler_id in {"quartalsaufstellung", "jahresdepotauszug"}:
            events, snapshots = (), (self._snapshot(document, detection.handler_id, depot_id, evidence),)
        else:
            events, snapshots = (self._event(document, detection.handler_id, depot_id, evidence),), ()
        attributes = {}
        if detection.handler_id in {"dividende", "vorabpauschale"}:
            attributes["quantity"] = str(money(required(SEC, document.text, "Wertpapierkopf").group(3)))
        return ParsedDocument(
            stable_id("result", document.document_id, self.metadata.version),
            document.document_id,
            self.metadata.plugin_id,
            self.metadata.version,
            detection.handler_id,
            events=events,
            evidence=tuple(evidences),
            depots=(depot,),
            depot_snapshots=snapshots,
            attributes=attributes,
        )

    def _snapshot(self, document, handler, depot_id, ev):
        text = document.text
        pattern = r"MIFID II per\s+(" + DAY + r")" if handler == "quartalsaufstellung" else r"Depotauszug\s+per\s+(" + DAY + r")"
        dated = required(pattern, text, "Bestandsstichtag")
        as_of = date(dated.group(1))
        positions = []
        for page in document.pages:
            rows = list(POS.finditer(page.text))
            for index, row in enumerate(rows):
                block = page.text[row.start() : rows[index + 1].start() if index + 1 < len(rows) else len(page.text)]
                isin = required(r"ISIN:\s*([A-Z0-9]{12})", block, "Bestands-ISIN").group(1)
                if not valid_isin(isin):
                    raise ValueError("Ungültige ISIN im Baader-Depotstand")
                name = required(r"ISIN:[^\n]*\n\s*([^\n]+)", block, "Wertpapiername").group(1).strip()
                quantity, price, value = money(row.group(1)), money(row.group(4)), money(row.group(5))
                if quantity <= 0 or value < 0 or (row.group(6) or "EUR") != "EUR":
                    raise ValueError("Unzulässige Baader-Bestandswerte")
                if row.group(3) == "EUR" and abs(quantity * price - value) > Decimal("0.02"):
                    raise ValueError("Baader-Stückzahl, Kurs und Kurswert stimmen nicht überein")
                eid, pno = ev("depot_position", row.group(0).strip(), page.number)
                pdf = lambda value: FieldValue.from_pdf(value, pno, eid)
                positions.append(
                    DepotPosition(
                        stable_id("position", depot_id, isin),
                        pdf(isin),
                        pdf(quantity),
                        security_name=pdf(name),
                        market_value=pdf(value),
                        currency=pdf("EUR"),
                        price=pdf(price),
                        price_date=pdf(as_of),
                    )
                )
        total_match = required(TOTAL, text, "Depotwert")
        total = money(total_match.group(1))
        if not positions or len({p.security_id.value for p in positions}) != len(positions):
            raise ValueError("Keine eindeutigen Baader-Positionen erkannt")
        if sum((p.market_value.value for p in positions), Decimal()) != total:
            raise ValueError("Baader-Positionssumme stimmt nicht mit dem Depotwert überein")
        total_ev, total_page = ev("depot_total", total_match.group(0))
        date_ev, date_page = ev("snapshot_date", dated.group(0))
        return DepotSnapshot(
            stable_id("snapshot", depot_id, as_of, document.document_id),
            depot_id,
            FieldValue.from_pdf(as_of, date_page, date_ev),
            tuple(positions),
            FieldValue.from_pdf(total, total_page, total_ev),
            FieldValue.from_pdf("EUR", total_page, total_ev),
        )

    def _event(self, document, handler, depot_id, ev):
        if handler == "wertpapierabrechnung":
            return self._trade(document, depot_id, ev)
        text = document.text
        sec = required(SEC, text, "Wertpapierkopf")
        isin, wkn, quantity, name = sec.group(1), sec.group(2), money(sec.group(3)), sec.group(4).strip()
        if not valid_isin(isin) or quantity <= 0:
            raise ValueError("Ungültige ISIN oder Stückzahl im Baader-Ereignis")
        sec_ev, _ = ev("security", sec.group(0))
        if handler == "depotuebertrag":
            inbound = "Depoteinlieferung" in text
            valued = required(r"Lagerstelle:\s*\d+\s+Valuta:\s*(" + DAY + r")", text, "Übertragsvaluta")
            referenced = required(r"(?:EINLIEFERUNG|AUSLIEFERUNG)-(\d+[.]\d+)", text, "Übertragsreferenz")
            when, reference = date(valued.group(1)), referenced.group(1)
            val_ev, _ = ev("value_date", valued.group(0))
            ref_ev, _ = ev("reference", referenced.group(0))
            event_id = stable_id("event", "baader-transfer", reference, isin)
            movement = SecurityMovement(stable_id("security", event_id), event_id, isin, quantity if inbound else -quantity, (sec_ev, val_ev), depot_id)
            return FinancialEvent(
                event_id,
                document.document_id,
                "TRANSFER_IN" if inbound else "TRANSFER_OUT",
                when,
                security_movements=(movement,),
                evidence_ids=(sec_ev, val_ev, ref_ev),
                security_name=name,
                security_wkn=wkn,
                security_isin=isin,
                security_identity_evidence_ids=(sec_ev,),
                bank_reference=reference,
                bank_reference_status="RECOGNIZED",
                bank_reference_evidence_ids=(ref_ev,),
            )
        referenced = required(REF, text, "Referenznummer")
        reference = referenced.group(1)
        ref_ev, _ = ev("reference", referenced.group(0))
        direction = "Gunsten" if handler == "dividende" else "Lasten"
        settled = required(r"Zu\s+" + direction + r"\s+Konto\s+(\d+)\s+Valuta:\s*(" + DAY + r")\s+([A-Z]{3})\s+(" + NUM + r")", text, "Abrechnung")
        when, currency, amount = date(settled.group(2)), settled.group(3), money(settled.group(4))
        settle_ev, _ = ev("settlement", settled.group(0))
        components, tax_evs = [], []
        for kind, label in (
            ("CAPITAL_GAINS_TAX", "Kapitalertragsteuer"),
            ("SOLIDARITY_SURCHARGE", "Solidaritätszuschlag"),
            ("CHURCH_TAX", "Kirchensteuer"),
            ("WITHHOLDING_TAX", "Quellensteuer"),
        ):
            match = re.search(r"(?m)^\s*(?:US-)?" + label + r"\s+EUR\s+(" + NUM + r")\s*-?\s*$", text)
            if match and money(match.group(1)):
                components.append(TaxComponent(kind, money(match.group(1)), "EUR"))
                tax_evs.append(ev("tax", match.group(0).strip())[0])
        tax_total = sum((item.amount for item in components), Decimal())
        if handler == "vorabpauschale" and abs(tax_total - amount) > Decimal("0.01"):
            raise ValueError("Baader-Steuerkomponenten passen nicht zur Vorabpauschalen-Belastung")
        reversal = bool(re.search(r"\bStorno\b|\bStornierung\b", text, re.I))
        reversal_of = None
        if reversal:
            process = required(r"Vorgangs-Nr\.:\s*(\d+)", text, "Vorgangsnummer").group(1)
            verified = REVERSAL.get(process)
            if not verified or (reference, isin, quantity, amount, tax_total) != verified[1:]:
                raise ValueError("Baader-Dividendenstorno ist keinem vollständig geprüften Originalbeleg zugeordnet")
            reversal_of = stable_id("event", "baader-income", verified[0], isin)
        event_id = stable_id("event", "baader-income" if handler == "dividende" else "baader-advance", reference, isin)
        signed = amount if handler == "dividende" else -amount
        if reversal:
            signed = -signed
        cash_id = stable_id("cash", event_id)
        cash = CashMovement(
            cash_id,
            event_id,
            signed,
            currency,
            CashStatus.EXPECTED,
            account_ref="Baader Konto " + settled.group(1),
            evidence_ids=(settle_ev,),
            movement_type=CashMovementType.REVERSAL if reversal else CashMovementType.DIVIDEND_CREDIT if handler == "dividende" else CashMovementType.TAX_DEBIT,
        )
        bases = re.findall(r"Bemessungsgrundlage\s+zur\s+Kapitalertragsteuer\s+EUR\s+(" + NUM + r")\s+EUR\s+(" + NUM + r")", text)
        taxes = (
            (
                TaxEvent(
                    stable_id("tax", event_id),
                    event_id,
                    "WITHHOLDING_TAX" if handler == "dividende" else "ADVANCE_TAX",
                    tuple(components),
                    taxable_basis=money(bases[-1][1]) if bases else None,
                    cash_movement_id=cash_id,
                    evidence_ids=tuple(tax_evs or (settle_ev,)),
                    depot_id=depot_id,
                    isin=isin,
                    tax_year=when.year,
                    booking_date=when,
                    value_date=when,
                    bank_id="baader",
                    currency=currency,
                    actually_withheld_tax=tax_total,
                ),
            )
            if components
            else ()
        )
        return FinancialEvent(
            event_id,
            document.document_id,
            "REVERSAL" if reversal else "DIVIDEND" if handler == "dividende" else "ADVANCE_TAX",
            when,
            cash_movements=(cash,),
            tax_events=taxes,
            reversal_of_event_id=reversal_of,
            evidence_ids=(sec_ev, settle_ev, ref_ev, *tax_evs),
            security_name=name,
            security_wkn=wkn,
            security_isin=isin,
            security_identity_evidence_ids=(sec_ev,),
            bank_reference=reference,
            bank_reference_status="RECOGNIZED",
            bank_reference_evidence_ids=(ref_ev,),
        )

    def _trade(self, document, depot_id, ev):
        text = document.text
        if re.search(r"\bStorno\b|\bStornierung\b", text, re.I):
            raise ValueError("Baader-Stornobeleg muss mit der ursprünglichen Abrechnung abgeglichen werden")
        side_match = required(r"Wertpapierabrechnung:\s*(Kauf|Verkauf)\b", text, "Geschäftsart")
        side = "BUY" if side_match.group(1) == "Kauf" else "SELL"
        referenced = required(REF, text, "Referenznummer")
        reference = referenced.group(1)
        isin = required(r"ISIN:\s*([A-Z0-9]{12})", text, "ISIN").group(1)
        if not valid_isin(isin):
            raise ValueError("Ungültige ISIN in der Baader-Abrechnung")
        wkn_match = required(r"WKN:\s*(\w{6})", text, "WKN")
        nominal = required(r"^\s*STK\s+(" + NUM + r")\s+(.+?)\s{2,}([A-Z]{3})\s+(" + NUM + r")\s*$", text, "Nominale")
        quantity, price = money(nominal.group(1)), money(nominal.group(4))
        if quantity <= 0:
            raise ValueError("Ungültige Stückzahl in der Baader-Abrechnung")
        execution = required(r"Details zur Ausführung:([\s\S]*?)Verwahrart:", text, "Ausführung").group(1)
        dates = set(re.findall(DAY, execution))
        if len(dates) != 1:
            raise ValueError("Kein eindeutiger Baader-Handelstag")
        traded = date(next(iter(dates)))
        settled = required(r"(?:Zu (Lasten|Gunsten) Konto\s+(\d+)|Total)\s+Valuta:\s*(" + DAY + r")\s+([A-Z]{3})\s+(" + NUM + r")", text, "Abrechnungsbetrag")
        direction, account, valued, currency, total = settled.group(1), settled.group(2), date(settled.group(3)), settled.group(4), money(settled.group(5))
        if direction is None and total != 0:
            raise ValueError("Baader-Abrechnung ohne Belastungs- oder Gutschriftrichtung")
        if direction and (side == "BUY") != (direction == "Lasten"):
            raise ValueError("Baader-Geschäftsart widerspricht Belastung oder Gutschrift")
        if nominal.group(3) != currency:
            raise ValueError("Baader-Kurs- und Abrechnungswährung weichen ab")
        gross_match = required(r"^\s*Kurswert\s+" + currency + r"\s+(" + NUM + r")\s*$", text, "Kurswert")
        gross = money(gross_match.group(1))
        fee_matches = list(re.finditer(r"(?m)^\s*Mindermengenzuschlag Finanzen\.net\s+" + currency + r"\s+(" + NUM + r")", text))
        fees = sum((money(x.group(1)) for x in fee_matches), Decimal())
        tax_matches = [
            (kind, match)
            for kind, label in (("CAPITAL_GAINS_TAX", "Kapitalertragsteuer"), ("SOLIDARITY_SURCHARGE", "Solidaritätszuschlag"), ("CHURCH_TAX", "Kirchensteuer"))
            for match in [re.search(r"(?m)^\s*" + label + r"\s+" + currency + r"\s+(" + NUM + r")", text)]
            if match
        ]
        tax_total = sum((money(x.group(1)) for _, x in tax_matches), Decimal())
        if abs(gross - quantity * price) > Decimal("0.02"):
            raise ValueError("Baader-Stückzahl und Kurs passen nicht zum Kurswert")
        if gross + (fees + tax_total) * (1 if side == "BUY" else -1) != total:
            raise ValueError("Baader-Kurswert, Gebühren und Steuern passen nicht zum Abrechnungsbetrag")
        row_ev, _ = ev("trade", nominal.group(0).strip())
        gross_ev, _ = ev("gross", gross_match.group(0).strip())
        ref_ev, _ = ev("reference", referenced.group(0))
        settle_ev, _ = ev("settlement", settled.group(0))
        fee_evs = tuple(ev("fee", x.group(0).strip())[0] for x in fee_matches)
        tax_evs = tuple(ev("tax", x.group(0).strip())[0] for _, x in tax_matches)
        event_id = stable_id("event", "baader-trade", DEPOT.search(text).group(1), reference)
        cash_id = stable_id("cash", event_id)
        cash = CashMovement(
            cash_id,
            event_id,
            -total if side == "BUY" else total,
            currency,
            CashStatus.EXPECTED,
            account_ref="Baader Konto " + account if account else "",
            evidence_ids=(settle_ev,),
            movement_type=CashMovementType.SECURITY_BUY if side == "BUY" else CashMovementType.SECURITY_SELL,
        )
        security = SecurityMovement(stable_id("security", event_id), event_id, isin, quantity if side == "BUY" else -quantity, (row_ev,), depot_id)
        trade = SecurityTrade(
            stable_id("trade", event_id),
            event_id,
            side,
            security_name=nominal.group(2).strip(),
            isin=isin,
            quantity=quantity,
            trade_date=traded,
            value_date=valued,
            price=price,
            price_currency=nominal.group(3),
            market_value=gross,
            gross_amount=gross,
            settlement_amount=total,
            settlement_currency=currency,
            depot_id=depot_id,
            evidence_ids=(row_ev, gross_ev, settle_ev),
        )
        fee_events = (
            (
                FeeEvent(
                    stable_id("fee", event_id),
                    "trading",
                    "minimum_quantity_surcharge",
                    fees,
                    currency,
                    traded,
                    FeeEffect.INCLUDED_IN_SETTLEMENT,
                    document.document_id,
                    "baader",
                    depot_id=depot_id,
                    transaction_id=event_id,
                    cash_movement_id=cash_id,
                    evidence_ids=fee_evs,
                ),
            )
            if fees
            else ()
        )
        tax_events = (
            (
                TaxEvent(
                    stable_id("tax", event_id),
                    event_id,
                    "TRADE_TAX",
                    tuple(TaxComponent(kind, money(x.group(1)), currency) for kind, x in tax_matches),
                    cash_movement_id=cash_id,
                    evidence_ids=tax_evs,
                    depot_id=depot_id,
                    isin=isin,
                    tax_year=traded.year,
                    booking_date=traded,
                    value_date=valued,
                    bank_id="baader",
                    currency=currency,
                    actually_withheld_tax=tax_total,
                ),
            )
            if tax_matches
            else ()
        )
        return FinancialEvent(
            event_id,
            document.document_id,
            side,
            traded,
            cash_movements=(cash,),
            security_movements=(security,),
            tax_events=tax_events,
            fee_events=fee_events,
            trades=(trade,),
            evidence_ids=(row_ev, gross_ev, settle_ev, ref_ev, *fee_evs, *tax_evs),
            security_name=nominal.group(2).strip(),
            security_wkn=wkn_match.group(1),
            security_isin=isin,
            security_identity_evidence_ids=(row_ev,),
            bank_reference=reference,
            bank_reference_status="RECOGNIZED",
            bank_reference_evidence_ids=(ref_ev,),
        )
