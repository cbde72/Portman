"""Feste transportneutrale Ein-/Ausgabeverträge der Anwendungsschicht."""
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol, Literal
from datetime import date as DateType

from portman_v10.domain.values import ExactValue, canonical_decimal, compare_decimal_text


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    STALE_REVISION = "STALE_REVISION"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    DEPENDENCY_CONFLICT = "DEPENDENCY_CONFLICT"
    UNRESOLVED_ACCOUNT = "UNRESOLVED_ACCOUNT"
    NOT_FOUND = "NOT_FOUND"
    CANCELLED = "CANCELLED"
    REQUEST_ID_REUSED = "REQUEST_ID_REUSED"
    INVALID_DOCUMENT = "INVALID_DOCUMENT"
    ENCRYPTED_DOCUMENT = "ENCRYPTED_DOCUMENT"
    UNSUPPORTED_DOCUMENT = "UNSUPPORTED_DOCUMENT"
    PARSER_ERROR = "PARSER_ERROR"
    INCOMPLETE_RESULT = "INCOMPLETE_RESULT"
    STORAGE_ERROR = "STORAGE_ERROR"
    JOB_INTERRUPTED = "JOB_INTERRUPTED"


class ApplicationError(Exception):
    def __init__(self, code: ErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _required(value: str, name: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} darf nicht leer sein")


def _decimal(value: ExactValue | None, name: str, *, required: bool = False) -> None:
    if required and value is None:
        raise ValueError(f"{name} ist erforderlich")
    if value is not None:
        if canonical_decimal(value.text) != value.text:
            raise ValueError(f"{name} muss kanonisch serialisiert sein")


@dataclass(frozen=True, slots=True)
class AccountIdentifier:
    identifier_type: str
    context: str
    value: str

    def __post_init__(self):
        if not self.identifier_type.strip() or not self.context.strip() or not self.value.strip():
            raise ValueError("Kontokennung benötigt Typ, Kontext und Wert")


@dataclass(frozen=True, slots=True)
class Account:
    account_id: str
    name: str
    kind: Literal["cash", "position"]
    subtype: Literal["checking", "savings", "fixed_term", "settlement", "depot", "crypto"]
    institution: str | None
    currency: str | None
    reference_account_id: str | None
    active: bool
    revision: int
    identifiers: tuple[AccountIdentifier, ...] = ()

    def __post_init__(self):
        _required(self.account_id, "account_id")
        _required(self.name, "name")
        if self.revision < 1:
            raise ValueError("revision muss positiv sein")
        if self.kind == "cash" and not self.currency:
            raise ValueError("Geldkonten benötigen eine Währung")
        if self.kind == "position" and self.currency is not None:
            raise ValueError("Bestandskonten führen keine Kontowährung")


@dataclass(frozen=True, slots=True)
class AccountInput:
    name: str
    kind: Literal["cash", "position"]
    subtype: Literal["checking", "savings", "fixed_term", "settlement", "depot", "crypto"]
    institution: str | None = None
    currency: str | None = None
    reference_account_id: str | None = None
    account_id: str | None = None
    identifiers: tuple[AccountIdentifier, ...] = ()

    def __post_init__(self):
        _required(self.name, "name")
        if self.kind == "cash":
            if self.subtype not in ("checking", "savings", "fixed_term", "settlement") or not self.currency:
                raise ValueError("Geldkonto benötigt passende Unterart und Währung")
        elif self.kind == "position":
            if self.subtype not in ("depot", "crypto") or self.currency is not None:
                raise ValueError("Bestandskonto benötigt Depot-/Krypto-Unterart ohne Kontowährung")
        else:
            raise ValueError("Unbekannter Kontotyp")
        if self.reference_account_id == self.account_id and self.account_id is not None:
            raise ValueError("Ein Konto darf nicht sich selbst als Referenzkonto haben")
        if any(not item.identifier_type.strip() or not item.context.strip() or not item.value.strip() for item in self.identifiers):
            raise ValueError("Kontokennungen benötigen Typ, Kontext und Wert")


@dataclass(frozen=True, slots=True)
class InstrumentIdentifier:
    provider: str
    identifier_type: str
    context: str
    value: str

    def __post_init__(self):
        if not self.provider.strip() or not self.identifier_type.strip() or not self.context.strip() or not self.value.strip():
            raise ValueError("Instrumentkennung benötigt Anbieter, Typ, Kontext und Wert")


@dataclass(frozen=True, slots=True)
class Instrument:
    instrument_id: str
    name: str
    asset_type: str
    isin: str | None = None
    wkn: str | None = None
    revision: int = 1
    identifiers: tuple[InstrumentIdentifier, ...] = ()


@dataclass(frozen=True, slots=True)
class InstrumentInput:
    name: str
    asset_type: str
    isin: str | None = None
    wkn: str | None = None
    instrument_id: str | None = None
    identifiers: tuple[InstrumentIdentifier, ...] = ()

    def __post_init__(self):
        _required(self.name, "name")
        _required(self.asset_type, "asset_type")
        if any(not item.provider.strip() or not item.identifier_type.strip() or not item.context.strip() or not item.value.strip() for item in self.identifiers):
            raise ValueError("Instrumentkennungen benötigen Anbieter, Typ, Kontext und Wert")
        supplied = [(item.provider, item.identifier_type, item.context, item.value) for item in self.identifiers]
        if len(supplied) != len(set(supplied)):
            raise ValueError("Instrumentkennungen dürfen nicht doppelt angegeben werden")
        if any(item.provider == "instrument" and item.identifier_type in {"ISIN", "WKN"} for item in self.identifiers):
            raise ValueError("ISIN/WKN werden über die dedizierten Felder angegeben")


@dataclass(frozen=True, slots=True)
class OpeningBalanceInput:
    opening_id: str
    account_id: str
    effective_date: date
    currency: str | None = None
    amount: ExactValue | None = None
    instrument_id: str | None = None
    quantity: ExactValue | None = None
    acquired_on: date | None = None
    acquisition_cost: ExactValue | None = None
    cost_currency: str | None = None
    note: str | None = None

    def __post_init__(self):
        _required(self.opening_id, "opening_id")
        _required(self.account_id, "account_id")
        money = self.currency is not None or self.amount is not None
        quantity = self.instrument_id is not None or self.quantity is not None or self.acquisition_cost is not None or self.cost_currency is not None or self.acquired_on is not None
        if money == quantity:
            raise ValueError("Eröffnung muss genau eine Geld- oder Mengenposition enthalten")
        if money:
            _required(self.currency or "", "currency")
            _decimal(self.amount, "amount", required=True)
        else:
            _required(self.instrument_id or "", "instrument_id")
            _decimal(self.quantity, "quantity", required=True)
            if compare_decimal_text(self.quantity.text, "0") <= 0:
                raise ValueError("Eröffnungsmenge muss positiv sein")
            _decimal(self.acquisition_cost, "acquisition_cost")
            if self.acquisition_cost is not None and (self.acquisition_cost.text.startswith("-") or not self.cost_currency):
                raise ValueError("Bekannte Anschaffungskosten benötigen Währung und dürfen nicht negativ sein")
            if self.acquisition_cost is None and self.cost_currency is not None:
                raise ValueError("Kostenwährung ohne belegten Kostenbetrag bleibt unbekannt")


@dataclass(frozen=True, slots=True)
class OpeningBalance:
    opening_id: str
    event_id: str
    position_id: str
    lot_id: str | None
    account_id: str
    effective_date: date
    amount: ExactValue | None
    quantity: ExactValue | None
    currency: str | None
    instrument_id: str | None
    cost_basis_status: Literal["not_applicable", "known", "unknown"]
    acquired_on: date | None = None
    acquisition_cost: ExactValue | None = None
    cost_currency: str | None = None
    note: str | None = None
    source_kind: Literal["manual"] = "manual"
    history_scope: Literal["starting_balance"] = "starting_balance"


@dataclass(frozen=True, slots=True)
class AccountPage:
    items: tuple[Account, ...]
    next_cursor: str | None
    data_revision: int


@dataclass(frozen=True, slots=True)
class InstrumentPage:
    items: tuple[Instrument, ...]
    next_cursor: str | None
    data_revision: int


@dataclass(frozen=True, slots=True)
class ImportSummary:
    import_id: str
    job_id: str
    started_at: str
    import_status: Literal["started", "preview", "committed", "cancelled", "failed", "rolled_back"]
    job_status: Literal["queued", "running", "needs_review", "completed", "failed", "cancelled"]
    filenames: tuple[str, ...]
    candidate_count: int
    committed: bool


@dataclass(frozen=True, slots=True)
class ImportPage:
    items: tuple[ImportSummary, ...]
    next_cursor: str | None
    data_revision: int


@dataclass(frozen=True, slots=True)
class ImportStart:
    document_ids: tuple[str, ...]
    account_hint: str | None = None

    def __post_init__(self):
        if not self.document_ids or any(not value.strip() for value in self.document_ids):
            raise ValueError("Mindestens eine Dokument-ID ist erforderlich")


@dataclass(frozen=True, slots=True)
class DocumentUpload:
    """Bytes aus einem Upload; enthält ausdrücklich keinen Serverpfad."""
    original_name: str
    content: bytes
    account_hint: str | None = None

    def __post_init__(self):
        _required(self.original_name, "original_name")
        if not isinstance(self.content, bytes) or not self.content:
            raise ValueError("PDF-Inhalt muss als nichtleerer Bytewert vorliegen")


@dataclass(frozen=True, slots=True)
class ImportJob:
    job_id: str
    import_id: str
    state: Literal["queued", "running", "needs_review", "completed", "cancelled", "failed"]
    progress: int
    revision: int
    error_code: ErrorCode | None = None
    document_count: int = 0
    completed_documents: int = 0
    cancel_requested: bool = False


@dataclass(frozen=True, slots=True)
class ImportDocumentResult:
    document_id: str
    name: str
    status: Literal["queued", "parsed", "needs_review", "information", "unsupported", "failed", "cancelled", "duplicate_file"]
    document_type: str | None
    plugin_id: str | None
    plugin_version: str | None
    handler_id: str | None
    parser_schema_version: str | None
    warning_messages: tuple[str, ...] = ()
    error_code: ErrorCode | None = None
    parser_package_version: str | None = None
    parser_api_version: str | None = None
    extraction_preparation_version: str | None = None


@dataclass(frozen=True, slots=True)
class Conflict:
    code: ErrorCode
    message: str
    candidate_id: str
    related_event_id: str | None = None


@dataclass(frozen=True, slots=True)
class PreviewItem:
    candidate_id: str
    kind: str
    disposition: Literal["unclassified", "existing", "complement", "conflict"]
    account_ids: tuple[str, ...]
    instrument_ids: tuple[str, ...]
    amounts: tuple[tuple[str, ExactValue | None, str | None], ...]
    effective_dates: tuple[date | None, ...]
    description: str | None
    conflicts: tuple[Conflict, ...] = ()
    document_id: str = ""
    document_name: str = ""
    document_type: str | None = None
    plugin_id: str | None = None
    plugin_version: str | None = None
    handler_id: str | None = None
    parser_schema_version: str | None = None
    suggested_kind: str | None = None
    movements: tuple["PreviewMovement", ...] = ()
    components: tuple["PreviewComponent", ...] = ()
    dates: tuple["PreviewDate", ...] = ()
    references: tuple[tuple[str, str | None], ...] = ()
    original_text: str | None = None
    source_evidence: tuple["PreviewEvidence", ...] = ()
    warnings: tuple["PreviewIssue", ...] = ()
    missing_fields: tuple[str, ...] = ()
    review_status: Literal["complete_candidate", "needs_review", "error", "information", "duplicate_file"] = "needs_review"
    revision: int = 1
    parser_package_version: str | None = None
    parser_api_version: str | None = None
    extraction_preparation_version: str | None = None
    instrument_resolution: Literal["not_applicable", "existing", "will_create", "unresolved"] = "not_applicable"
    instrument_message: str | None = None

    def __post_init__(self):
        _required(self.candidate_id, "candidate_id")
        if self.revision < 1:
            raise ValueError("candidate revision muss positiv sein")


@dataclass(frozen=True, slots=True)
class PreviewMovement:
    movement_type: Literal["cash", "quantity"]
    amount: ExactValue | None
    currency: str | None = None
    instrument_id: str | None = None
    instrument_name: str | None = None
    account_id: str | None = None
    account_reference: str | None = None
    #date: date | None = None
    date: DateType | None = None
    date_meaning: str | None = None
    status: str | None = None
    direction: str | None = None
    account_assignment: Literal["exact_identifier", "user_hint", "unresolved", "conflict"] = "unresolved"


@dataclass(frozen=True, slots=True)
class PreviewComponent:
    category: str
    kind: str
    amount: ExactValue | None
    currency: str | None
    effect: str
    counts_as_movement: bool = False


@dataclass(frozen=True, slots=True)
class PreviewDate:
    value: date | None
    meaning: str
    unknown_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PreviewEvidence:
    evidence_id: str
    page_number: int | None
    field: str | None
    excerpt: str | None
    source_ref: str | None


@dataclass(frozen=True, slots=True)
class PreviewIssue:
    code: str
    severity: str
    message: str
    evidence_id: str | None = None


@dataclass(frozen=True, slots=True)
class ImportPreview:
    import_id: str
    revision: int
    data_revision: int
    items: tuple[PreviewItem, ...]
    documents: tuple[ImportDocumentResult, ...] = ()
    decisions: tuple["RecordedDecision", ...] = ()


@dataclass(frozen=True, slots=True)
class RecordedDecision:
    candidate_id: str
    candidate_revision: int
    preview_revision: int
    decision: "ConflictDecision"


@dataclass(frozen=True, slots=True)
class ConflictDecision:
    candidate_id: str
    decision: Literal["accept", "accept_unmatched", "link", "ignore", "assign_account"]
    target_id: str | None = None
    account_id: str | None = None
    candidate_revision: int = 1

    def __post_init__(self):
        _required(self.candidate_id, "candidate_id")
        if self.candidate_revision < 1:
            raise ValueError("candidate_revision muss positiv sein")


@dataclass(frozen=True, slots=True)
class CommitImport:
    import_id: str
    preview_revision: int
    request_id: str

    def __post_init__(self):
        _required(self.import_id, "import_id")
        _required(self.request_id, "request_id")
        if self.preview_revision < 1:
            raise ValueError("preview_revision muss positiv sein")


@dataclass(frozen=True, slots=True)
class CommitReport:
    import_id: str
    event_ids: tuple[str, ...]
    data_revision: int
    replayed: bool
    created_event_ids: tuple[str, ...] = ()
    linked_event_ids: tuple[str, ...] = ()
    created_instrument_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RollbackSelection:
    import_ids: tuple[str, ...] = ()
    all_imports: bool = False

    def __post_init__(self):
        if bool(self.import_ids) == self.all_imports or any(not value.strip() for value in self.import_ids):
            raise ValueError("Entweder Import-IDs oder ausdrücklich alle Importe auswählen")


@dataclass(frozen=True, slots=True)
class RollbackContribution:
    contribution_id: str
    import_id: str
    event_id: str | None
    document_id: str | None
    target_type: str
    field_name: str
    action: str
    value_text: str | None


@dataclass(frozen=True, slots=True)
class RollbackPreview:
    plan_id: str
    revision: int
    import_ids: tuple[str, ...]
    affected_event_ids: tuple[str, ...]
    unresolved_dependencies: tuple[str, ...]
    affected_contribution_ids: tuple[str, ...] = ()
    affected_document_links: tuple[str, ...] = ()
    affected_instrument_ids: tuple[str, ...] = ()
    balance_impacts: tuple[str, ...] = ()
    removable_instrument_ids: tuple[str, ...] = ()
    affected_contributions: tuple[RollbackContribution, ...] = ()


@dataclass(frozen=True, slots=True)
class ExecuteRollback:
    plan_id: str
    expected_revision: int
    request_id: str

    def __post_init__(self):
        _required(self.plan_id, "plan_id")
        _required(self.request_id, "request_id")


@dataclass(frozen=True, slots=True)
class RollbackReport:
    removed_import_ids: tuple[str, ...]
    retained_event_ids: tuple[str, ...]
    data_revision: int
    replayed: bool
    removed_event_ids: tuple[str, ...] = ()
    removed_instrument_ids: tuple[str, ...] = ()
    removed_position_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Search:
    text: str = ""
    account_ids: tuple[str, ...] = ()
    instrument_ids: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()
    date_from: date | None = None
    date_to: date | None = None
    currency: str | None = None
    minimum: ExactValue | None = None
    maximum: ExactValue | None = None
    include_inactive_accounts: bool = True
    cursor: str | None = None
    limit: int = 100

    def __post_init__(self):
        _decimal(self.minimum, "minimum")
        _decimal(self.maximum, "maximum")
        if self.minimum and self.maximum and self.minimum.text and self.maximum.text:
            from portman_v10.domain.values import compare_decimal_text
            if compare_decimal_text(self.minimum.text, self.maximum.text) > 0:
                raise ValueError("minimum darf maximum nicht überschreiten")
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from darf date_to nicht überschreiten")
        if not 1 <= self.limit <= 500:
            raise ValueError("limit muss zwischen 1 und 500 liegen")


@dataclass(frozen=True, slots=True)
class TransactionSummary:
    event_id: str
    booking_date: date
    kind: str
    description: str
    account_ids: tuple[str, ...] = ()
    instrument_ids: tuple[str, ...] = ()
    amount: ExactValue | None = None
    currency: str | None = None
    active: bool = True


@dataclass(frozen=True, slots=True)
class TransactionDetail:
    summary: TransactionSummary
    positions: tuple[tuple[str, str, ExactValue, str | None, date], ...]
    components: tuple[tuple[str, ExactValue | None, str | None], ...]
    source_document_ids: tuple[str, ...]
    revision: int


@dataclass(frozen=True, slots=True)
class TransactionPage:
    items: tuple[TransactionSummary, ...]
    next_cursor: str | None
    data_revision: int


@dataclass(frozen=True, slots=True)
class Document:
    document_id: str
    name: str
    media_type: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class DocumentContent:
    metadata: Document
    content: bytes


@dataclass(frozen=True, slots=True)
class DocumentUploadResult:
    document: Document
    identical_content_already_stored: bool


@dataclass(frozen=True, slots=True)
class BalanceLine:
    account_id: str
    value: ExactValue | None
    currency: str | None
    instrument_id: str | None
    completeness: Literal["complete", "incomplete", "unknown"]


@dataclass(frozen=True, slots=True)
class Overview:
    as_of: date
    data_revision: int
    lines: tuple[BalanceLine, ...]


@dataclass(frozen=True, slots=True)
class ExemptionOrder:
    tax_subject_id: str
    tax_year: int
    valid_from: date
    valid_to: date | None
    amount: ExactValue
    revision: int


@dataclass(frozen=True, slots=True)
class ExemptionOrderInput:
    tax_subject_id: str
    tax_year: int
    valid_from: date
    valid_to: date | None
    amount: ExactValue
    expected_revision: int | None

    def __post_init__(self):
        _required(self.tax_subject_id, "tax_subject_id")
        _decimal(self.amount, "amount", required=True)
        if self.tax_year < 1900 or (self.valid_to and self.valid_to < self.valid_from):
            raise ValueError("Steuerjahr oder Gültigkeitszeitraum ungültig")
        if self.amount.text.startswith("-"):
            raise ValueError("Freistellungsbetrag darf nicht negativ sein")


@dataclass(frozen=True, slots=True)
class TaxConsumption:
    amount: ExactValue | None
    meaning: Literal["individual", "cumulative"]
    as_of: date | None
    source_document_ids: tuple[str, ...]
    completeness: Literal["complete", "incomplete", "unknown"]


@dataclass(frozen=True, slots=True)
class TaxSummary:
    tax_subject_id: str
    tax_year: int
    order: ExemptionOrder | None
    consumptions: tuple[TaxConsumption, ...]
    used: ExactValue | None
    available: ExactValue | None
    source_as_of: date | None
    completeness: Literal["complete", "incomplete", "unknown"]
    data_revision: int


class ApplicationService(Protocol):
    def list_accounts(self, cursor: str | None = None, limit: int = 100) -> AccountPage: ...
    def list_imports(self, cursor: str | None = None, limit: int = 100) -> ImportPage: ...
    def save_account(self, value: AccountInput, expected_revision: int | None) -> Account: ...
    def get_account(self, account_id: str) -> Account: ...
    def deactivate_account(self, account_id: str, expected_revision: int) -> Account: ...
    def save_instrument(self, value: InstrumentInput, expected_revision: int | None) -> Instrument: ...
    def get_instrument(self, instrument_id: str) -> Instrument: ...
    def list_instruments(self, cursor: str | None = None, limit: int = 100) -> InstrumentPage: ...
    def record_opening(self, value: OpeningBalanceInput) -> OpeningBalance: ...
    def get_opening(self, opening_id: str) -> OpeningBalance: ...
    def upload_document(self, upload: DocumentUpload) -> DocumentUploadResult: ...
    def start_import(self, value: ImportStart) -> ImportJob: ...
    def get_job(self, job_id: str) -> ImportJob: ...
    def get_import_document_results(self, job_id: str) -> tuple[ImportDocumentResult, ...]: ...
    def cancel_job(self, job_id: str, expected_revision: int) -> ImportJob: ...
    def get_import_preview(self, import_id: str) -> ImportPreview: ...
    def discard_import(self, import_id: str, expected_revision: int) -> ImportJob: ...
    def resolve_import_item(self, import_id: str, decision: ConflictDecision, expected_revision: int) -> ImportPreview: ...
    def commit_import(self, command: CommitImport) -> CommitReport: ...
    def preview_rollback(self, selection: RollbackSelection) -> RollbackPreview: ...
    def execute_rollback(self, command: ExecuteRollback) -> RollbackReport: ...
    def search_transactions(self, query: Search) -> TransactionPage: ...
    def get_transaction(self, event_id: str) -> TransactionDetail: ...
    def get_document(self, document_id: str) -> DocumentContent: ...
    def get_overview(self, as_of: date, account_ids: tuple[str, ...] = ()) -> Overview: ...
    def save_exemption_order(self, value: ExemptionOrderInput) -> ExemptionOrder: ...
    def get_tax_summary(self, tax_subject_id: str, tax_year: int) -> TaxSummary: ...
