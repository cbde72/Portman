"""Kleiner zustandsbehafteter Vertrags-Fake mit ausschließlich synthetischen Daten.

Er prüft DTO-/Anwendungsabläufe, aber keine persistente Transaktion und keine Finanzlogik.
"""
from dataclasses import replace
from datetime import date
from hashlib import sha256

from portman_v10.application.contracts import (
    Account, AccountInput, AccountPage, ApplicationError, BalanceLine, CommitImport,
    CommitReport, ConflictDecision, Document, DocumentContent, ErrorCode, ExecuteRollback,
    ExemptionOrder, ExemptionOrderInput, ImportJob, ImportPreview, ImportStart,
    Instrument, InstrumentInput, InstrumentPage, OpeningBalance, OpeningBalanceInput, Overview, PreviewItem, RollbackPreview,
    RollbackReport, RollbackSelection, Search, TaxConsumption, TaxSummary,
    TransactionDetail, TransactionPage, TransactionSummary,
)
from portman_v10.domain.values import ExactValue, compare_decimal_text


class FakeService:
    """Synthetischer In-Memory-Service zum Entwickeln späterer Oberflächen."""

    def __init__(self):
        self.data_revision = 1
        self.accounts = {
            "demo-giro": Account("demo-giro", "Demo-Giro", "cash", "checking", "Beispielbank", "EUR", None, True, 1),
            "demo-savings": Account("demo-savings", "Demo-Tagesgeld", "cash", "savings", "Beispielbank", "EUR", None, True, 1),
            "demo-depot": Account("demo-depot", "Demo-Depot", "position", "depot", "Beispielbank", None, "demo-giro", True, 1),
            "demo-old-depot": Account("demo-old-depot", "Demo-Altdepot", "position", "depot", "Beispielbank", None, None, False, 1),
        }
        self.instruments = {"demo-fund": Instrument("demo-fund", "Beispiel-Fonds", "fund", "DE000DEMO001", None)}
        self.openings: dict[str, OpeningBalance] = {}
        self.transactions = {
            "synthetic-buy-001": TransactionSummary("synthetic-buy-001", date(2025, 11, 12), "buy", "Beispielkauf", ("demo-giro", "demo-depot"), ("demo-fund",), ExactValue("-201"), "EUR"),
            "synthetic-dividend-001": TransactionSummary("synthetic-dividend-001", date(2025, 3, 25), "dividend", "Beispielausschüttung", ("demo-giro",), ("demo-fund",), ExactValue("8"), "EUR"),
            "synthetic-transfer-001": TransactionSummary("synthetic-transfer-001", date(2025, 4, 2), "own_transfer", "Eigener Transfer", ("demo-giro", "demo-savings"), (), ExactValue("-100"), "EUR"),
            "synthetic-inactive-001": TransactionSummary("synthetic-inactive-001", date(2024, 8, 1), "interest", "Buchung deaktiviertes Konto", ("demo-old-depot",), (), ExactValue("0.01"), "EUR", False),
        }
        self.details = {
            "synthetic-buy-001": TransactionDetail(self.transactions["synthetic-buy-001"], (("demo-depot", "demo-fund", ExactValue("2"), None, date(2025, 11, 10)), ("demo-giro", "EUR", ExactValue("-201"), "EUR", date(2025, 11, 12))), (("trade_value", ExactValue("200"), "EUR"), ("fee", ExactValue("1"), "EUR")), ("demo-buy-note",), 1),
            "synthetic-dividend-001": TransactionDetail(self.transactions["synthetic-dividend-001"], (("demo-giro", "EUR", ExactValue("8"), "EUR", date(2025, 3, 25)),), (("gross", ExactValue("10"), "EUR"), ("tax", ExactValue("2"), "EUR")), ("demo-dividend-note",), 1),
        }
        content = b"synthetic,non-sensitive,reference-document\n"
        self.documents = {"demo-buy-note": DocumentContent(Document("demo-buy-note", "Beispielkauf.txt", "text/plain", len(content), sha256(content).hexdigest()), content)}
        self.documents["demo-dividend-note"] = DocumentContent(Document("demo-dividend-note", "Beispielausschuettung.txt", "text/plain", len(content), sha256(content).hexdigest()), content)
        self.jobs: dict[str, ImportJob] = {}
        self.previews: dict[str, ImportPreview] = {}
        self.committed: dict[str, CommitReport] = {}
        self.rolled_back: dict[str, RollbackReport] = {}
        self.rollback_plans: dict[str, tuple[str, ...]] = {}
        self.request_inputs: dict[str, tuple[str, object]] = {}
        self.orders: dict[tuple[str, int], ExemptionOrder] = {}
        self.tax_summaries: dict[tuple[str, int], TaxSummary] = {
            ("demo-tax-subject", 2025): TaxSummary(
                "demo-tax-subject", 2025, None,
                (TaxConsumption(ExactValue("2"), "cumulative", date(2025, 12, 31), ("demo-tax-note",), "incomplete"),),
                ExactValue("2"), None, date(2025, 12, 31), "incomplete", 1,
            )
        }

    def _page(self, cursor: str | None, limit: int, count: int) -> tuple[int, str | None]:
        if not 1 <= limit <= 500:
            raise ApplicationError(ErrorCode.VALIDATION_ERROR, "limit muss zwischen 1 und 500 liegen")
        offset = 0
        if cursor:
            try:
                revision, raw_offset = cursor.split(":", 1)
                if int(revision) != self.data_revision:
                    raise ApplicationError(ErrorCode.STALE_REVISION, "Daten wurden geändert; Suche neu starten")
                offset = int(raw_offset)
            except (ValueError, TypeError) as error:
                if isinstance(error, ApplicationError):
                    raise
                raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Cursor ungültig") from error
        next_offset = offset + limit
        return offset, f"{self.data_revision}:{next_offset}" if next_offset < count else None

    def list_accounts(self, cursor: str | None = None, limit: int = 100) -> AccountPage:
        ordered = tuple(sorted(self.accounts.values(), key=lambda row: row.account_id))
        offset, next_cursor = self._page(cursor, limit, len(ordered))
        return AccountPage(ordered[offset:offset + limit], next_cursor, self.data_revision)

    def get_account(self, account_id: str) -> Account:
        try:
            return self.accounts[account_id]
        except KeyError as error:
            raise ApplicationError(ErrorCode.NOT_FOUND, "Konto nicht gefunden") from error

    def save_account(self, value: AccountInput, expected_revision: int | None) -> Account:
        if not value.name.strip():
            raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Kontoname ist erforderlich")
        if value.kind == "cash" and not value.currency:
            raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Geldkonto benötigt Währung")
        if value.kind == "position" and value.currency is not None:
            raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Bestandskonto darf keine Kontowährung haben")
        account_id = value.account_id
        current = self.accounts.get(account_id) if account_id else None
        if value.account_id and current is None:
            raise ApplicationError(ErrorCode.NOT_FOUND, "Konto nicht gefunden")
        if current and expected_revision != current.revision:
            raise ApplicationError(ErrorCode.STALE_REVISION, "Konto-Revision ist veraltet")
        if not current and expected_revision is not None:
            raise ApplicationError(ErrorCode.STALE_REVISION, "Neues Konto darf keine erwartete Revision haben")
        if value.reference_account_id:
            reference = self.accounts.get(value.reference_account_id)
            if reference is None:
                raise ApplicationError(ErrorCode.NOT_FOUND, "Referenzkonto nicht gefunden")
            if reference.kind != "cash":
                raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Referenzkonto muss ein Geldkonto sein")
        account_id = account_id or f"demo-account-{len(self.accounts) + 1}"
        saved = Account(account_id, value.name, value.kind, value.subtype, value.institution, value.currency, value.reference_account_id, current.active if current else True, (current.revision + 1) if current else 1, value.identifiers)
        self.accounts[account_id] = saved
        self.data_revision += 1
        return saved

    def deactivate_account(self, account_id: str, expected_revision: int) -> Account:
        account = self.get_account(account_id)
        if account.revision != expected_revision:
            raise ApplicationError(ErrorCode.STALE_REVISION, "Konto-Revision ist veraltet")
        if account.active:
            updated = replace(account, active=False, revision=account.revision + 1)
            self.accounts[account_id] = updated
            self.data_revision += 1
            return updated
        return account

    def get_instrument(self, instrument_id: str) -> Instrument:
        try:
            return self.instruments[instrument_id]
        except KeyError as error:
            raise ApplicationError(ErrorCode.NOT_FOUND, "Instrument nicht gefunden") from error

    def list_instruments(self, cursor: str | None = None, limit: int = 100) -> InstrumentPage:
        ordered = tuple(sorted(self.instruments.values(), key=lambda row: row.instrument_id))
        offset, next_cursor = self._page(cursor, limit, len(ordered))
        return InstrumentPage(ordered[offset:offset + limit], next_cursor, self.data_revision)

    def save_instrument(self, value: InstrumentInput, expected_revision: int | None) -> Instrument:
        if not value.name.strip() or not value.asset_type.strip():
            raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Name und Anlageart sind erforderlich")
        existing = self.instruments.get(value.instrument_id) if value.instrument_id else None
        if value.instrument_id and existing is None:
            raise ApplicationError(ErrorCode.NOT_FOUND, "Instrument nicht gefunden")
        if existing and expected_revision != existing.revision:
            raise ApplicationError(ErrorCode.STALE_REVISION, "Instrument-Revision ist veraltet")
        if not existing and expected_revision is not None:
            raise ApplicationError(ErrorCode.STALE_REVISION, "Neues Instrument darf keine erwartete Revision haben")
        instrument_id = existing.instrument_id if existing else f"demo-instrument-{len(self.instruments) + 1}"
        saved = Instrument(instrument_id, value.name, value.asset_type, value.isin, value.wkn, existing.revision + 1 if existing else 1, value.identifiers)
        self.instruments[instrument_id] = saved
        self.data_revision += 1
        return saved

    def record_opening(self, value: OpeningBalanceInput) -> OpeningBalance:
        account = self.accounts.get(value.account_id)
        if account is None:
            raise ApplicationError(ErrorCode.NOT_FOUND, "Eröffnungskonto nicht gefunden")
        money = value.currency is not None
        if money and (account.kind != "cash" or account.currency != value.currency):
            raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Geld-Eröffnung muss zur Kontowährung passen")
        if not money and account.kind != "position":
            raise ApplicationError(ErrorCode.VALIDATION_ERROR, "Mengen-Eröffnung benötigt ein Bestandskonto")
        if not money and value.instrument_id not in self.instruments:
            raise ApplicationError(ErrorCode.NOT_FOUND, "Eröffnungsinstrument nicht gefunden")
        if value.opening_id in self.openings:
            raise ApplicationError(ErrorCode.POSSIBLE_DUPLICATE, "Eröffnungs-ID existiert bereits")
        basis = "not_applicable" if money else "known" if value.acquisition_cost is not None else "unknown"
        saved = OpeningBalance(
            value.opening_id, f"opening-event-{value.opening_id}", f"opening-position-{value.opening_id}",
            f"opening-lot-{value.opening_id}" if not money else None, value.account_id, value.effective_date,
            value.amount, value.quantity, value.currency, value.instrument_id, basis, value.acquired_on,
            value.acquisition_cost, value.cost_currency, value.note,
        )
        self.openings[value.opening_id] = saved
        self.data_revision += 1
        return saved

    def get_opening(self, opening_id: str) -> OpeningBalance:
        try:
            return self.openings[opening_id]
        except KeyError as error:
            raise ApplicationError(ErrorCode.NOT_FOUND, "Eröffnungsbestand nicht gefunden") from error

    def start_import(self, value: ImportStart) -> ImportJob:
        unknown = [item for item in value.document_ids if item not in self.documents]
        if unknown:
            raise ApplicationError(ErrorCode.NOT_FOUND, f"Unbekanntes synthetisches Dokument: {unknown[0]}")
        import_id = f"demo-import-{len(self.jobs) + 1}"
        job = ImportJob(f"demo-job-{len(self.jobs) + 1}", import_id, "needs_review", 100, 1, document_count=len(value.document_ids), completed_documents=len(value.document_ids))
        self.jobs[job.job_id] = job
        item = PreviewItem(f"{import_id}-candidate-1", "synthetic_confirmation", "unclassified", ("demo-giro",), (), (("cash", ExactValue("8"), "EUR"),), (date(2025, 3, 25),), "Synthetische Bestätigung")
        self.previews[import_id] = ImportPreview(import_id, 1, self.data_revision, (item,))
        return job

    def get_job(self, job_id: str) -> ImportJob:
        try:
            return self.jobs[job_id]
        except KeyError as error:
            raise ApplicationError(ErrorCode.NOT_FOUND, "Importjob nicht gefunden") from error

    def cancel_job(self, job_id: str, expected_revision: int) -> ImportJob:
        job = self.get_job(job_id)
        if job.revision != expected_revision:
            raise ApplicationError(ErrorCode.STALE_REVISION, "Job-Revision ist veraltet")
        updated = replace(job, state="cancelled", revision=job.revision + 1)
        self.jobs[job_id] = updated
        return updated

    def get_import_preview(self, import_id: str) -> ImportPreview:
        try:
            return self.previews[import_id]
        except KeyError as error:
            raise ApplicationError(ErrorCode.NOT_FOUND, "Importvorschau nicht gefunden") from error

    def resolve_import_item(self, import_id: str, decision: ConflictDecision, expected_revision: int) -> ImportPreview:
        preview = self.get_import_preview(import_id)
        if preview.revision != expected_revision:
            raise ApplicationError(ErrorCode.STALE_REVISION, "Vorschau-Revision ist veraltet")
        candidate = next((item for item in preview.items if item.candidate_id == decision.candidate_id), None)
        if candidate is None:
            raise ApplicationError(ErrorCode.NOT_FOUND, "Kandidat nicht gefunden")
        if candidate.revision != decision.candidate_revision:
            raise ApplicationError(ErrorCode.STALE_REVISION, "Kandidatenrevision ist veraltet")
        if decision.decision == "assign_account" and decision.account_id not in self.accounts:
            raise ApplicationError(ErrorCode.UNRESOLVED_ACCOUNT, "Zielkonto unbekannt")
        updated = replace(preview, revision=preview.revision + 1)
        self.previews[import_id] = updated
        return updated

    @staticmethod
    def _fingerprint(command: object) -> str:
        return sha256(repr(command).encode("utf-8")).hexdigest()

    def commit_import(self, command: CommitImport) -> CommitReport:
        fingerprint = self._fingerprint(command)
        previous = self.request_inputs.get(command.request_id)
        if previous:
            if previous[0] != fingerprint:
                raise ApplicationError(ErrorCode.REQUEST_ID_REUSED, "request_id wurde mit anderer Eingabe wiederverwendet")
            return replace(previous[1], replayed=True)
        preview = self.get_import_preview(command.import_id)
        if command.preview_revision != preview.revision:
            raise ApplicationError(ErrorCode.STALE_REVISION, "Vorschau ist veraltet")
        event_ids = tuple(item.candidate_id for item in preview.items)
        report = CommitReport(command.import_id, event_ids, self.data_revision + 1, False)
        self.committed[command.import_id] = report
        self.request_inputs[command.request_id] = (fingerprint, report)
        self.data_revision += 1
        return report

    def preview_rollback(self, selection: RollbackSelection) -> RollbackPreview:
        import_ids = tuple(sorted(self.committed)) if selection.all_imports else selection.import_ids
        missing = [item for item in import_ids if item not in self.committed]
        if missing:
            raise ApplicationError(ErrorCode.NOT_FOUND, f"Import nicht gefunden: {missing[0]}")
        plan = RollbackPreview(f"demo-rollback-{self.data_revision}", self.data_revision, import_ids, tuple(event for item in import_ids for event in self.committed[item].event_ids), ())
        self.rollback_plans[plan.plan_id] = import_ids
        return plan

    def execute_rollback(self, command: ExecuteRollback) -> RollbackReport:
        fingerprint = self._fingerprint(command)
        previous = self.request_inputs.get(command.request_id)
        if previous:
            if previous[0] != fingerprint:
                raise ApplicationError(ErrorCode.REQUEST_ID_REUSED, "request_id wurde mit anderer Eingabe wiederverwendet")
            return replace(previous[1], replayed=True)
        if command.expected_revision != self.data_revision or command.plan_id not in self.rollback_plans:
            raise ApplicationError(ErrorCode.STALE_REVISION, "Rücknahmeplan ist veraltet")
        # Der Fake prüft nur die API-Wirkung; keine echte Beitrags-/Buchungsrücknahme.
        plan_import_ids = self.rollback_plans[command.plan_id]
        if any(item not in self.committed for item in plan_import_ids):
            raise ApplicationError(ErrorCode.STALE_REVISION, "Import wurde bereits zurückgenommen")
        removed_events = {event for item in plan_import_ids for event in self.committed[item].event_ids}
        deltas = {item for item in plan_import_ids}
        retained = tuple(sorted(event for event in removed_events if any(event in report.event_ids for import_id, report in self.committed.items() if import_id not in deltas)))
        report = RollbackReport(plan_import_ids, retained, self.data_revision + 1, False)
        for import_id in plan_import_ids:
            del self.committed[import_id]
        self.rolled_back[command.plan_id] = report
        self.request_inputs[command.request_id] = (fingerprint, report)
        self.data_revision += 1
        return report

    def search_transactions(self, query: Search) -> TransactionPage:
        rows = list(self.transactions.values())
        if query.text:
            needle = query.text.casefold()
            rows = [row for row in rows if needle in (row.description + " " + row.kind + " " + row.event_id).casefold()]
        if query.account_ids:
            rows = [row for row in rows if set(query.account_ids).intersection(row.account_ids)]
        if query.instrument_ids:
            rows = [row for row in rows if set(query.instrument_ids).intersection(row.instrument_ids)]
        if query.kinds:
            rows = [row for row in rows if row.kind in query.kinds]
        if query.date_from:
            rows = [row for row in rows if row.booking_date >= query.date_from]
        if query.date_to:
            rows = [row for row in rows if row.booking_date <= query.date_to]
        if query.currency:
            rows = [row for row in rows if row.currency == query.currency]
        if query.minimum:
            rows = [row for row in rows if row.amount and compare_decimal_text(row.amount.text, query.minimum.text) >= 0]
        if query.maximum:
            rows = [row for row in rows if row.amount and compare_decimal_text(row.amount.text, query.maximum.text) <= 0]
        if not query.include_inactive_accounts:
            rows = [row for row in rows if row.active]
        ordered = sorted(rows, key=lambda row: (row.booking_date, row.event_id), reverse=True)
        offset, next_cursor = self._page(query.cursor, query.limit, len(ordered))
        return TransactionPage(tuple(ordered[offset:offset + query.limit]), next_cursor, self.data_revision)

    def get_transaction(self, event_id: str) -> TransactionDetail:
        if event_id in self.details:
            return self.details[event_id]
        summary = self.transactions.get(event_id)
        if summary is None:
            raise ApplicationError(ErrorCode.NOT_FOUND, "Vorgang nicht gefunden")
        return TransactionDetail(summary, (), (), (), self.data_revision)

    def get_document(self, document_id: str) -> DocumentContent:
        if document_id not in self.documents:
            raise ApplicationError(ErrorCode.NOT_FOUND, "Dokument nicht gefunden")
        return self.documents[document_id]

    def get_overview(self, as_of: date, account_ids: tuple[str, ...] = ()) -> Overview:
        lines = (
            BalanceLine("demo-giro", ExactValue("1000"), "EUR", None, "complete"),
            BalanceLine("demo-savings", ExactValue("250"), "EUR", None, "complete"),
            BalanceLine("demo-depot", ExactValue("7"), None, "demo-fund", "complete"),
            BalanceLine("demo-old-depot", None, None, "demo-fund", "unknown"),
        )
        if account_ids:
            lines = tuple(line for line in lines if line.account_id in account_ids)
        return Overview(as_of, self.data_revision, lines)

    def save_exemption_order(self, value: ExemptionOrderInput) -> ExemptionOrder:
        key = (value.tax_subject_id, value.tax_year)
        current = self.orders.get(key)
        if current and value.expected_revision != current.revision:
            raise ApplicationError(ErrorCode.STALE_REVISION, "Freistellungsauftrag ist veraltet")
        if not current and value.expected_revision is not None:
            raise ApplicationError(ErrorCode.STALE_REVISION, "Neuer Auftrag darf keine erwartete Revision haben")
        saved = ExemptionOrder(value.tax_subject_id, value.tax_year, value.valid_from, value.valid_to, value.amount, current.revision + 1 if current else 1)
        self.orders[key] = saved
        self.data_revision += 1
        return saved

    def get_tax_summary(self, tax_subject_id: str, tax_year: int) -> TaxSummary:
        key = (tax_subject_id, tax_year)
        existing = self.tax_summaries.get(key)
        if existing:
            order = self.orders.get(key, existing.order)
            return replace(existing, order=order, data_revision=self.data_revision)
        return TaxSummary(tax_subject_id, tax_year, self.orders.get(key), (), None, None, None, "unknown", self.data_revision)
