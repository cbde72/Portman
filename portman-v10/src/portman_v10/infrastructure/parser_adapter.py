"""Einzige Grenze, an der portman-parsers-Objekte vorkommen."""
from datetime import date
from dataclasses import replace
from decimal import Decimal
from importlib.util import find_spec
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from portman_parsers.api import API_VERSION, SCHEMA_VERSION, MissingValue
from portman_parsers.extraction import DamagedPdfError, PasswordProtectedPdfError, extract_pdf
from portman_parsers.registry import AmbiguousDetectionError, default_registry
from portman_parsers.validation import validate_parsed_document

from portman_v10.application.contracts import (
    ApplicationError, Conflict, ErrorCode, ImportDocumentResult, PreviewComponent,
    PreviewDate, PreviewEvidence, PreviewIssue, PreviewItem, PreviewMovement,
)
from portman_v10.domain.values import ExactValue, canonical_decimal
from portman_v10.infrastructure.sqlite_store import SQLiteStore

V10_BOOKING_HANDLERS = frozenset({("user.comdirect-ertraege", "wertpapierkauf")})
V10_INFORMATION_HANDLERS = frozenset({("user.comdirect-ertraege", "kosteninformation_mifid_ii")})


def _value(value: Any) -> Any:
    return None if isinstance(value, MissingValue) else value


def _exact(value: Any) -> ExactValue | None:
    if value is None or isinstance(value, MissingValue):
        return None
    if not isinstance(value, Decimal):
        raise TypeError("Parserwert ist kein Decimal")
    return ExactValue(canonical_decimal(format(value, "f")))


class PortmanParserAdapter:
    def __init__(self, store: SQLiteStore):
        self.store = store
        self.registry = default_registry()
        self.package_version = self._installed_version()
        self.api_version = API_VERSION
        self.schema_version = SCHEMA_VERSION

    @staticmethod
    def _installed_version() -> str | None:
        try:
            return version("portman-parsers")
        except PackageNotFoundError:
            return None

    def parse_path(self, document_id: str, path: str, name: str, account_hint: str | None = None):
        try:
            document = extract_pdf(path)
        except PasswordProtectedPdfError as error:
            raise ApplicationError(ErrorCode.ENCRYPTED_DOCUMENT, "PDF ist verschlüsselt; Passwortgeschützte Dokumente werden derzeit nicht verarbeitet") from error
        except DamagedPdfError as error:
            hint = " Die optionale pypdfium2-Textextraktion ist nicht installiert; sie kann bei manchen beschädigten/textarmen PDFs helfen, ist aber keine OCR oder Reparatur." if find_spec("pypdfium2") is None else " Auch der optionale PDFium-Fallback konnte das PDF nicht lesbar aufbereiten."
            raise ApplicationError(ErrorCode.INVALID_DOCUMENT, "PDF ist ungültig, beschädigt oder nicht lesbar." + hint) from error
        except Exception as error:
            raise ApplicationError(ErrorCode.PARSER_ERROR, "PDF-Textextraktion ist fehlgeschlagen") from error

        document = replace(document, document_id=document_id)
        preparation_version = document.metadata.get("text_preparation_version")

        if not document.pages:
            raise ApplicationError(ErrorCode.INVALID_DOCUMENT, "PDF enthält keine lesbaren Seiten")
        if all(not page.text.strip() for page in document.pages):
            hint = " Der optionale PDFium-Textfallback fehlt in dieser Umgebung." if find_spec("pypdfium2") is None else " PDFium hat keine Textebene gewonnen."
            raise ApplicationError(ErrorCode.INCOMPLETE_RESULT, "PDF enthält keine lesbare Textebene; OCR ist kein Bestandteil dieses V10-Schritts." + hint)
        try:
            detection = self.registry.select(document)
        except AmbiguousDetectionError as error:
            raise ApplicationError(ErrorCode.UNSUPPORTED_DOCUMENT, "Mehrere Parserhandler sind gleich plausibel; automatische Auswahl bleibt offen") from error
        if detection is None:
            return ImportDocumentResult(document_id, name, "unsupported", None, None, None, None, None, (), ErrorCode.UNSUPPORTED_DOCUMENT,
                                       self.package_version, self.api_version, preparation_version), (), ()
        handler_key = (detection.plugin_id, detection.handler_id)
        if handler_key not in V10_BOOKING_HANDLERS and handler_key not in V10_INFORMATION_HANDLERS:
            return ImportDocumentResult(document_id, name, "unsupported", detection.document_type, detection.plugin_id,
                                        detection.plugin_version, detection.handler_id, None, (), ErrorCode.UNSUPPORTED_DOCUMENT,
                                        self.package_version, self.api_version, preparation_version), (), ()
        try:
            result = self.registry.parse(document, detection)
        except NotImplementedError:
            return ImportDocumentResult(document_id, name, "unsupported", detection.document_type, detection.plugin_id, detection.plugin_version, detection.handler_id, None, (), ErrorCode.UNSUPPORTED_DOCUMENT,
                                        self.package_version, self.api_version, preparation_version), (), ()
        except Exception as error:
            raise ApplicationError(ErrorCode.PARSER_ERROR, "Ausgewählter Parserhandler ist fehlgeschlagen") from error

        validation_issues = tuple(validate_parsed_document(result))
        issues = tuple((*result.issues, *validation_issues))
        evidence_by_id = {item.evidence_id: item for item in result.evidence}
        warnings = tuple(PreviewIssue(item.code, item.severity.value, item.message, item.evidence_id) for item in issues)
        information_handler = handler_key in V10_INFORMATION_HANDLERS
        if information_handler and any(event.cash_movements or event.security_movements for event in result.events):
            warning = PreviewIssue("INFORMATION_HANDLER_MOVEMENT", "ERROR", "Informationshandler lieferte unerwartet eine Geld-/Mengenbewegung; Ergebnis zurückgehalten")
            return ImportDocumentResult(document_id, name, "needs_review", detection.document_type, result.plugin_id,
                                        result.plugin_version, result.handler_id, result.schema_version,
                                        tuple(issue.message for issue in (*warnings, warning)), ErrorCode.INCOMPLETE_RESULT,
                                        self.package_version, self.api_version, preparation_version), (), (*warnings, warning)
        candidate_items = []
        for event in result.events:
            item = self._event_preview(document_id, name, detection, result, event, evidence_by_id, warnings, account_hint,
                                       "\n".join(page.text for page in document.pages)[:12000], preparation_version)
            if information_handler:
                item = replace(item, kind="information", suggested_kind="information", review_status="information",
                               missing_fields=(), conflicts=(), disposition="unclassified")
            candidate_items.append(item)

        information = information_handler
        status = "information" if information else "needs_review" if issues or not result.events or any(item.review_status == "needs_review" for item in candidate_items) else "parsed"
        document_result = ImportDocumentResult(document_id, name, status, detection.document_type, result.plugin_id,
                                               result.plugin_version, result.handler_id, result.schema_version,
                                               tuple(issue.message for issue in warnings), None, self.package_version,
                                               self.api_version, preparation_version)
        if information and not candidate_items:
            # Snapshots and account/depot reports describe a state, never a purchase or cash booking.
            candidate_items.append(PreviewItem(
                candidate_id=f"{document_id}:information", kind="information_document", disposition="unclassified",
                account_ids=(), instrument_ids=(), amounts=(), effective_dates=(), description=None,
                document_id=document_id, document_name=name, document_type=detection.document_type,
                plugin_id=result.plugin_id, plugin_version=result.plugin_version, handler_id=result.handler_id,
                parser_schema_version=result.schema_version, suggested_kind="information",
                review_status="information", warnings=warnings,
                original_text="\n".join(page.text for page in document.pages)[:12000],
                parser_package_version=self.package_version, parser_api_version=self.api_version,
                extraction_preparation_version=preparation_version,
            ))
        return document_result, tuple(candidate_items), tuple(warnings)

    def _event_preview(self, document_id, name, detection, result, event, evidence_by_id, warnings, account_hint, source_text, preparation_version):
        parsed_accounts = {account.account_id: account for account in result.accounts}
        movements = []
        account_ids = set()
        for movement in event.cash_movements:
            matched = None
            source_account = parsed_accounts.get(movement.account_id or "")
            iban = _value(source_account.iban.value) if source_account else None
            if iban:
                bank_context = _value(source_account.bank_name.value) if source_account else None
                matches = self.store.match_account_identifier("iban", str(bank_context).casefold() if bank_context else None, iban)
                if len(matches) == 1:
                    matched = matches[0]
            if matched:
                account_ids.add(matched)
            assignment = "exact_identifier" if matched else "unresolved"
            if account_hint and self.store.account_kind(account_hint) == "cash":
                if matched and matched != account_hint:
                    assignment = "conflict"
                    warnings = (*warnings, PreviewIssue("ACCOUNT_HINT_CONFLICT", "WARNING", "Kontovorgabe widerspricht der exakt belegten Parserkennung"))
                elif not matched:
                    matched = account_hint
                    assignment = "user_hint"
                    account_ids.add(matched)
            account_reference = iban or (_value(source_account.account_number.value) if source_account else None) or movement.account_ref or None
            movements.append(PreviewMovement("cash", _exact(movement.amount), movement.currency,
                                             account_id=matched, account_reference=account_reference,
                                             date=event.event_date, date_meaning="event_date",
                                             status=movement.status.value, direction=movement.movement_type.value,
                                             account_assignment=assignment))
        instrument_ids = set()
        parsed_depots = {depot.depot_id: depot for depot in result.depots}
        for movement in event.security_movements:
            isin = movement.security_id if len(movement.security_id) == 12 else None
            matches = self.store.match_instrument_identifier("ISIN", "standard", isin) if isin else ()
            instrument = matches[0] if len(matches) == 1 else None
            if instrument:
                instrument_ids.add(instrument)
            matched_account = None
            assignment = "unresolved"
            depot = parsed_depots.get(movement.depot_id or "")
            depot_number = _value(depot.depot_number.value) if depot else None
            if depot_number:
                bank_context = _value(depot.bank_name.value) if depot else None
                depot_accounts = self.store.match_account_identifier("depot_number", str(bank_context).casefold() if bank_context else None, depot_number)
                if len(depot_accounts) == 1:
                    matched_account = depot_accounts[0]
                    assignment = "exact_identifier"
                    account_ids.add(matched_account)
            if account_hint and self.store.account_kind(account_hint) == "position":
                if matched_account and matched_account != account_hint:
                    assignment = "conflict"
                    warnings = (*warnings, PreviewIssue("ACCOUNT_HINT_CONFLICT", "WARNING", "Kontovorgabe widerspricht der exakt belegten Depotkennung"))
                elif not matched_account:
                    matched_account = account_hint
                    assignment = "user_hint"
                    account_ids.add(matched_account)
            movements.append(PreviewMovement("quantity", _exact(movement.quantity), instrument_id=instrument,
                                             instrument_name=_value(event.security_name), account_id=matched_account, account_reference=depot_number,
                                             date=event.event_date, date_meaning="event_date", direction="security_movement",
                                             account_assignment=assignment))

        components = []
        for fee in event.fee_events:
            components.append(PreviewComponent("fee", fee.subcategory, _exact(fee.amount), fee.currency, fee.effect.value, False))
        for tax in event.tax_events:
            for component in tax.components:
                components.append(PreviewComponent("tax", component.kind, _exact(component.amount), component.currency, "explanatory", False))
            for field_name in ("assessment_basis", "advance_before_partial_exemption", "taxable_amount", "stated_tax_liability", "actually_withheld_tax", "distributions", "exemption_order_used", "loss_offset_used"):
                value = _value(getattr(tax, field_name))
                components.append(PreviewComponent("tax_detail", field_name, _exact(value), tax.currency, "explanatory", False))
        for cost in event.cost_events:
            components.append(PreviewComponent("cost", cost.kind, _exact(cost.amount), cost.currency,
                                                "informational" if cost.informational else "explanatory", False))
        for trade in event.trades:
            for field_name in ("price", "market_value", "gross_amount", "exchange_rate", "settlement_amount"):
                value = _value(getattr(trade, field_name))
                currency = _value(getattr(trade, "price_currency" if field_name in {"price", "market_value"} else "settlement_currency"))
                components.append(PreviewComponent("trade_detail", field_name, _exact(value), currency, "printed_detail", False))

        dates = [PreviewDate(event.event_date, "event_date", "not_found" if event.event_date is None else None)]
        for trade in event.trades:
            for key, meaning in (("trade_date", "trade_date"), ("execution_date", "execution_date"), ("value_date", "value_date")):
                raw_value = getattr(trade, key)
                value = _value(raw_value)
                reason = raw_value.value.casefold() if isinstance(raw_value, MissingValue) else "not_found" if value is None else None
                dates.append(PreviewDate(value if isinstance(value, date) else None, meaning, reason))

        evidence_ids = set(event.evidence_ids)
        evidence_ids.update(event.security_identity_evidence_ids)
        evidence_ids.update(event.bank_reference_evidence_ids)
        for movement in (*event.cash_movements, *event.security_movements):
            evidence_ids.update(movement.evidence_ids)
        for fee in event.fee_events:
            evidence_ids.update(fee.evidence_ids)
        for tax in event.tax_events:
            evidence_ids.update(tax.evidence_ids)
        for cost in event.cost_events:
            evidence_ids.update(cost.evidence_ids)
        for trade in event.trades:
            evidence_ids.update(trade.evidence_ids)
        evidence = tuple(PreviewEvidence(item.evidence_id, item.page_number, item.field, item.excerpt, item.source_ref)
                         for key in sorted(evidence_ids) if (item := evidence_by_id.get(key)) is not None)
        missing = []
        if not event.cash_movements and not event.security_movements:
            missing.append("bestandswirksame Geld- oder Mengenposition")
        if not account_ids:
            missing.append("eindeutige V10-Kontozuordnung")
        elif any(movement.account_id is None for movement in movements):
            missing.append("eindeutige V10-Zuordnung für jede Geld-/Mengenposition")
        if not instrument_ids and event.security_movements:
            missing.append("eindeutige V10-Instrumentzuordnung")
        elif event.security_movements and len(instrument_ids) < len({movement.security_id for movement in event.security_movements}):
            missing.append("eindeutige V10-Zuordnung für jedes Instrument")
        if event.bank_reference_status != "RECOGNIZED":
            missing.append("belegte Bankreferenz")
        conflict = ()
        if any(item.code == "ACCOUNT_HINT_CONFLICT" for item in warnings):
            conflict = (Conflict(ErrorCode.SOURCE_CONFLICT, "Kontovorgabe widerspricht Belegkennung", f"{document_id}:{event.event_id}"),)
        status = "needs_review" if missing or warnings or conflict else "complete_candidate"
        original = source_text or None
        return PreviewItem(
            candidate_id=f"{document_id}:{event.event_id}", kind=event.kind, disposition="conflict" if conflict else "unclassified",
            account_ids=tuple(sorted(account_ids)), instrument_ids=tuple(sorted(instrument_ids)), amounts=(),
            effective_dates=tuple(item.value for item in dates), description=event.kind, conflicts=conflict,
            document_id=document_id, document_name=name, document_type=detection.document_type,
            plugin_id=result.plugin_id, plugin_version=result.plugin_version, handler_id=result.handler_id,
            parser_schema_version=result.schema_version, suggested_kind=event.kind, movements=tuple(movements),
            components=tuple(components), dates=tuple(dates),
            references=(("bank_reference", _value(event.bank_reference)), ("bank_reference_status", event.bank_reference_status), ("security_isin", _value(event.security_isin)), ("security_wkn", _value(event.security_wkn))),
            original_text=original, source_evidence=evidence, warnings=tuple(warnings), missing_fields=tuple(missing), review_status=status,
            parser_package_version=self.package_version, parser_api_version=self.api_version,
            extraction_preparation_version=preparation_version,
        )
