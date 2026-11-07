"""Serverseitige lokale Weboberfläche für den vorhandenen V10-Importworkflow."""
from datetime import date
from io import BytesIO
import hmac
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
from urllib.parse import urlsplit

from flask import Flask, abort, g, redirect, render_template, request, send_file, session, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from portman_v10.application.contracts import (
    ApplicationError, CommitImport, ConflictDecision, DocumentUpload, ErrorCode, ExecuteRollback, ImportStart, InstrumentInput,
    RollbackSelection, Search,
)
from portman_v10.infrastructure.import_workflow import ImportWorkflow
from portman_v10.infrastructure.parser_adapter import _resolve_instrument
from portman_v10.infrastructure.sqlite_store import SQLiteStore
from portman_v10.web.accounts import (
    CASH_FORM_TYPES, POSITION_FORM_TYPES, SUBTYPE_LABELS, AccountForm, AccountFormError, account_input_from_form, account_rows, form_from_account, form_from_request, reference_options,
)
from portman_v10.web.instruments import (
    INSTRUMENT_TYPE_LABELS, InstrumentForm, InstrumentFormError, form_from_instrument, instrument_input_from_form, safe_return_path,
)
from portman_v10.web.instruments import form_from_request as instrument_form_from_request
from portman_v10.web.openings import OpeningFormError, opening_input_from_form
from portman_v10.web.overview import STEPS, parse_anchor, shift

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 64 * 1024
MAX_BATCH_FILES = 200
PACKAGE_ROOT = Path(__file__).resolve().parents[3]
STATUS_LABELS = {
    "queued": "Wartet",
    "running": "Wird verarbeitet",
    "needs_review": "Prüfung nötig",
    "completed": "Abgeschlossen",
    "failed": "Fehlgeschlagen",
    "cancelled": "Abgebrochen",
    "parsed": "Verarbeitet",
    "information": "Nur Information",
    "unsupported": "Nicht unterstützt",
    "duplicate_file": "Identischer Dateiinhalt",
}
IMPORT_STATUS_LABELS = {
    "started": "Gestartet",
    "preview": "Vorschau, nicht übernommen",
    "committed": "Übernommen",
    "cancelled": "Abgebrochen",
    "failed": "Fehlgeschlagen",
    "rolled_back": "Zurückgenommen",
}
# Diese Kandidaten überspringt SQLiteStore.commit_import; alle übrigen brauchen eine Entscheidung.
NO_DECISION_STATUSES = frozenset({"information", "error", "duplicate_file"})
# Nicht freigegebene Vorgangstypen kann commit_import nicht buchen; sie lassen sich nur ignorieren.
STALE_PREVIEW_TEXT = ("Seit dieser Vorschau wurde der Datenbestand geändert, zum Beispiel durch eine andere Übernahme, "
                      "eine Rücknahme oder gepflegte Konten bzw. Instrumente. Zum Schutz vor Dubletten und falschen "
                      "Zuordnungen bitte die Vorschau mit aktuellem Datenstand neu erstellen")
IGNORE_ONLY_STATUSES = frozenset({"needs_review"})
ASSIGNMENT_LABELS = {
    "exact_identifier": "Exakte Kennung",
    "user_hint": "Vorgabe",
    "unresolved": "Zuordnung offen",
    "conflict": "Widerspruch prüfen",
}


def _git_value(*arguments: str) -> str:
    try:
        return subprocess.run(
            ["git", *arguments], cwd=PACKAGE_ROOT, check=True, capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unbekannt"


def _account_label(workflow: ImportWorkflow, account_id: str | None) -> str:
    if not account_id:
        return "Zuordnung offen"
    try:
        account = workflow.store.get_account(account_id)
    except ApplicationError:
        return "Konto nicht verfügbar"
    return account.name


def _instrument_summaries(workflow: ImportWorkflow, item):
    references = dict(item.references)
    parsed_isin = references.get("security_isin")
    parsed_wkn = references.get("security_wkn")
    summaries = []
    seen = set()
    for movement in item.movements:
        if movement.movement_type != "quantity":
            continue
        master = None
        if movement.instrument_id:
            try:
                master = workflow.store.get_instrument(movement.instrument_id)
            except ApplicationError:
                master = None
        name = movement.instrument_name or (master.name if master else None)
        identifier = parsed_isin or parsed_wkn or (master.isin or master.wkn if master else None)
        identifier_type = "ISIN" if parsed_isin or (master and master.isin and not parsed_wkn) else "WKN"
        if name and identifier:
            label = f"{name} — {identifier_type} {identifier}"
        elif name:
            label = name
        elif identifier:
            label = f"Wertpapiername nicht erkannt — {identifier_type} {identifier}"
        else:
            label = "Wertpapier nicht erkannt"
        key = (label, movement.instrument_id is None)
        if key in seen:
            continue
        seen.add(key)
        issue = next((value for value in item.missing_fields if any(word in value.casefold() for word in ("instrument", "isin", "wkn"))), None)
        summaries.append({
            "label": label,
            "mapping": "Zuordnung offen" if movement.instrument_id is None else "Zugeordnet",
            "issue": f"Prüfen: {issue}" if issue and movement.instrument_id is None else None,
            "create": _create_params(item, name, parsed_isin, parsed_wkn) if movement.instrument_id is None else None,
        })
    if not summaries and (parsed_isin or parsed_wkn or references.get("security_name")):
        movement_id = next((movement.security_id for movement in item.movements if movement.movement_type == "quantity"), None)
        instrument_id, issue = _resolve_instrument(workflow.store, parsed_isin, parsed_wkn, movement_id)
        master = None
        if instrument_id:
            try:
                master = workflow.store.get_instrument(instrument_id)
            except ApplicationError:
                master = None
        name = references.get("security_name") or (master.name if master else None)
        identifier = parsed_isin or parsed_wkn or (master.isin or master.wkn if master else None)
        identifier_type = "ISIN" if parsed_isin or (master and master.isin and not parsed_wkn) else "WKN"
        label = f"{name} — {identifier_type} {identifier}" if name and identifier else name or f"Wertpapiername nicht erkannt — {identifier_type} {identifier}" if identifier else "Wertpapier nicht erkannt"
        summaries.append({
            "label": label,
            "mapping": "Zugeordnet" if instrument_id else "Zuordnung offen",
            "issue": f"Prüfen: {issue}" if issue else None,
            "create": _create_params(item, name, parsed_isin, parsed_wkn) if not instrument_id else None,
        })
    return tuple(summaries)


def _create_params(item, name, isin, wkn):
    """Vorbelegung für „Instrument anlegen“; nicht, wenn die Übernahme das Instrument selbst anlegt."""
    if getattr(item, "instrument_resolution", None) == "will_create" or not (isin or wkn):
        return None
    return {key: value for key, value in (("name", name), ("isin", isin), ("wkn", wkn)) if value}


def _present_preview(workflow: ImportWorkflow, preview):
    presented = []
    decisions = {value.candidate_id: value.decision.decision for value in preview.decisions}
    decision_labels = {"accept": "Kandidat angenommen", "link": "Als Ergänzungsbeleg zugeordnet", "ignore": "Kandidat ignoriert",
                       "accept_unmatched": "Als neue Buchung ohne Bankreferenz vorgemerkt"}
    for item in preview.items:
        movements = []
        for movement in item.movements:
            movement_checks = ()
            if movement.account_id is None:
                kind = "Depot" if movement.movement_type == "quantity" else "Geldkonto"
                movement_checks = (f"Prüfen: {kind} nicht zugeordnet",)
            movements.append({
                "type": "Geldbewegung" if movement.movement_type == "cash" else "Mengenbewegung",
                "date": movement.date.isoformat() if movement.date else "Unbekannt",
                "account": _account_label(workflow, movement.account_id),
                "account_reference": movement.account_reference or "",
                "amount": movement.amount.text if movement.amount else "Unbekannt",
                "unit": movement.currency or ("Stück" if movement.movement_type == "quantity" else ""),
                "assignment": ASSIGNMENT_LABELS[movement.account_assignment],
                "checks": movement_checks,
            })
        dates = tuple({
            "meaning": value.meaning.replace("_", " "),
            "value": value.value.isoformat() if value.value else "Unbekannt",
            "reason": value.unknown_reason or "",
        } for value in item.dates)
        components = tuple({
            "category": value.category,
            "kind": value.kind,
            "amount": value.amount.text if value.amount else "Unbekannt",
            "currency": value.currency or "",
            "effect": value.effect,
        } for value in item.components)
        evidence = tuple({
            "page": value.page_number or "Unbekannt",
            "field": value.field or "Feld unbekannt",
            "excerpt": value.excerpt or "Kein Textauszug vorhanden",
        } for value in item.source_evidence)
        warnings = tuple({
            "severity": value.severity,
            "code": value.code,
            "message": value.message,
        } for value in item.warnings)
        finanzreport = _is_finanzreport_row(item)
        unmatched_blocker = _unmatched_blocker(item) if finanzreport else None
        waived = finanzreport and decisions.get(item.candidate_id) in FINANZREPORT_DECISIONS
        checks = list(f"Prüfen: {value}" for value in item.missing_fields if not (waived and _is_bank_reference_point(value)))
        linked = _link_resolves_conflicts(item, decisions.get(item.candidate_id))
        if not linked:
            # Nach „Als Ergänzungsbeleg zuordnen“ ist der Dublettenhinweis geklärt; die Entscheidung steht darüber.
            checks.extend(f"Prüfen: {value.message}" for value in item.conflicts)
        checks.extend(f"Prüfen: {value['message']}" for value in warnings if value["severity"] in {"WARNING", "ERROR"})
        decision_missing = item.review_status not in NO_DECISION_STATUSES and item.candidate_id not in decisions
        ignored = decisions.get(item.candidate_id) == "ignore"
        if ignored:
            # Ignorierte Kandidaten bucht commit_import nicht; ihre Prüfpunkte blockieren die Übernahme nicht mehr.
            checks = []
        if decision_missing and finanzreport:
            checks.insert(0, "Prüfen: Entscheidung fehlt – referenzlose Reportzeile: als neue Buchung übernehmen, zuordnen oder ignorieren"
                          if unmatched_blocker is None or item.conflicts else
                          "Prüfen: Entscheidung fehlt – Zeile kann so nicht gebucht werden; „Ignorieren“ wählen oder Ursache beheben")
        elif decision_missing and item.review_status in IGNORE_ONLY_STATUSES:
            checks.insert(0, "Prüfen: Entscheidung fehlt – Vorgangstyp nicht freigegeben; „Ignorieren“ wählen, um die übrigen Kandidaten zu übernehmen")
        elif decision_missing:
            checks.insert(0, "Prüfen: Entscheidung fehlt – „Kandidat prüfen / annehmen“ oder „Ignorieren“ wählen")
        presented.append({
            "kind": item.suggested_kind or item.kind,
            "status": item.review_status,
            "decision_missing": decision_missing,
            "decision_status": decision_labels.get(decisions.get(item.candidate_id)),
            "candidate_id": item.candidate_id,
            "candidate_revision": item.revision,
            "decision": decisions.get(item.candidate_id),
            "finanzreport": finanzreport,
            "unmatched_blocker": unmatched_blocker,
            "related_event": next((value.related_event_id for value in item.conflicts if value.related_event_id), None),
            "instruments": _instrument_summaries(workflow, item),
            "movements": tuple(movements),
            "account_references": tuple(
                ("Geldbewegung" if movement.movement_type == "cash" else "Mengenbewegung", movement.account_reference)
                for movement in item.movements if movement.account_reference
            ),
            "dates": dates,
            "components": components,
            "references": tuple((key, value or "Unbekannt") for key, value in item.references),
            "evidence": evidence,
            "warnings": warnings,
            "missing": item.missing_fields,
            "checks": tuple(dict.fromkeys(checks)),
            "original_text": item.original_text or "",
        })
    return tuple(presented)


LINK_RESOLVABLE_CONFLICTS = frozenset({ErrorCode.POSSIBLE_DUPLICATE, ErrorCode.SOURCE_CONFLICT})


def _link_resolves_conflicts(item, decision: str | None) -> bool:
    """Wie commit_import: „Als Ergänzungsbeleg zuordnen“ klärt Dubletten- und Quellenhinweise, keine anderen Konflikte."""
    return decision == "link" and bool(item.conflicts) and all(value.code in LINK_RESOLVABLE_CONFLICTS for value in item.conflicts)


FINANZREPORT_ROW = ("comdirect.finanzreport", "finanzreport", "CASH_BOOKING")
FINANZREPORT_DECISIONS = frozenset({"accept_unmatched", "link"})


def _is_finanzreport_row(item) -> bool:
    return (item.plugin_id, item.handler_id, item.kind) == FINANZREPORT_ROW and item.review_status == "needs_review"


def _is_bank_reference_point(text: str) -> bool:
    return text.startswith("Bankreferenz fehlt")


def _unmatched_blocker(item) -> str | None:
    """Grund, warum „Als neue Buchung übernehmen“ hier nicht angeboten wird; None = anbieten.

    Nur sichtbare Vorbedingungen aus der Vorschau; die verbindliche Prüfung macht commit_import (Schnittstelle.md).
    """
    if item.conflicts:
        return "Eine gleiche oder mehrdeutige Buchung ist bereits vorhanden – nicht neu buchen, sondern zuordnen oder ignorieren."
    if len(item.movements) != 1 or item.movements[0].movement_type != "cash":
        return "Die Zeile enthält nicht genau eine Geldbewegung."
    if not item.movements[0].account_id:
        return ("Geldkonto nicht zugeordnet – Konto mit passender Kennung unter „Konten & Depots“ anlegen bzw. ergänzen "
                "und die Vorschau neu erstellen, oder die Zeile ignorieren.")
    if any(not _is_bank_reference_point(value) for value in item.missing_fields) or item.warnings:
        return "Außer der fehlenden Bankreferenz sind weitere Angaben offen."
    return None


def _resolved(item, decision: str | None) -> bool:
    """Blockiert dieser Kandidat die Übernahme nicht mehr? Spiegelt nur die Entscheidungswirkung; commit_import prüft verbindlich."""
    if decision == "ignore":
        return True
    missing = item.missing_fields
    status_ok = item.review_status == "complete_candidate"
    if _is_finanzreport_row(item) and decision in FINANZREPORT_DECISIONS:
        # Referenzlose Reportzeile: die ausdrückliche Entscheidung ersetzt die fehlende Bankreferenz.
        missing = tuple(value for value in missing if not _is_bank_reference_point(value))
        status_ok = True
    conflicts_ok = not item.conflicts or _link_resolves_conflicts(item, decision)
    return not missing and status_ok and conflicts_ok


def _bulk_unmatched(preview):
    """Referenzlose Finanzreportzeilen, die „Alle als neue Buchung übernehmen“ erfassen darf."""
    decided = {value.candidate_id for value in preview.decisions}
    return tuple(item for item in preview.items if item.candidate_id not in decided
                 and _is_finanzreport_row(item) and _unmatched_blocker(item) is None)


def _bulk_acceptable(preview):
    """Kandidaten, die „Alle annehmen“ erfassen darf: vollständig, konfliktfrei, noch ohne Entscheidung."""
    decided = {value.candidate_id for value in preview.decisions}
    return tuple(item for item in preview.items if item.candidate_id not in decided and item.review_status == "complete_candidate"
                 and not item.missing_fields and not item.conflicts)


def _bulk_summary(preview):
    ready = len(_bulk_acceptable(preview))
    unmatched = len(_bulk_unmatched(preview))
    return {"ready": ready, "unmatched": unmatched, "others": _preview_summary(preview)["undecided"] - ready - unmatched}


def _preview_summary(preview):
    cash = sum(1 for item in preview.items for movement in item.movements if movement.movement_type == "cash")
    quantity = sum(1 for item in preview.items for movement in item.movements if movement.movement_type == "quantity")
    decisions = {value.candidate_id: value.decision.decision for value in preview.decisions}
    decided = set(decisions)
    unresolved = sum(1 for item in preview.items if not _resolved(item, decisions.get(item.candidate_id)))
    undecided = sum(1 for item in preview.items if item.review_status not in NO_DECISION_STATUSES and item.candidate_id not in decided)
    return {"events": len(preview.items), "cash": cash, "quantity": quantity, "unresolved": unresolved, "undecided": undecided}


def create_app(
    workflow: ImportWorkflow,
    *,
    branch: str = "unbekannt",
    commit: str = "unbekannt",
    profile: str = "isoliertes Web-Testprofil",
) -> Flask:
    app = Flask(__name__, template_folder="templates")
    app.config.update(
        MAX_CONTENT_LENGTH=MAX_REQUEST_BYTES,
        MAX_FORM_MEMORY_SIZE=64 * 1024,
        MAX_FORM_PARTS=MAX_BATCH_FILES + 8,
        TRUSTED_HOSTS=["127.0.0.1", "localhost"],
        SECRET_KEY=secrets.token_urlsafe(32),
        SESSION_COOKIE_DOMAIN=None,
    )

    def csp_nonce() -> str:
        # Pro Antwort eine neue Nonce: nur Skripte aus den eigenen Vorlagen laufen, eingeschleuster Text nicht.
        if "csp_nonce" not in g:
            g.csp_nonce = secrets.token_urlsafe(16)
        return g.csp_nonce

    app.jinja_env.globals["csp_nonce"] = csp_nonce

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self'; script-src 'self' 'nonce-{csp_nonce()}'; style-src 'self' 'unsafe-inline'; "
            "object-src 'self'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.before_request
    def same_origin_uploads():
        if request.method != "POST":
            return None

        def parsed_origin(value: str | None, *, is_referer: bool = False):
            if not value:
                return None
            try:
                parsed = urlsplit(value)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                    return False
                # Origin is serialized as scheme + authority only. Referer is
                # a full URL and legitimately includes the page path/query;
                # those parts do not participate in same-origin comparison.
                if not is_referer and (parsed.path or parsed.query or parsed.fragment):
                    return False
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                return parsed.scheme.casefold(), parsed.hostname.rstrip(".").casefold(), port
            except ValueError:
                return False

        expected = (request.scheme.casefold(), (urlsplit(f"//{request.host}").hostname or "").casefold().rstrip("."), urlsplit(f"//{request.host}").port or (443 if request.scheme == "https" else 80))
        origin_header = request.headers.get("Origin")
        referer_header = request.headers.get("Referer")
        origin = parsed_origin(origin_header) if origin_header is not None else None
        referer = parsed_origin(referer_header, is_referer=True) if referer_header is not None else None
        # Host validation is mandatory, including when a browser serializes an
        # opaque origin as "null" or omits both provenance headers.
        host = urlsplit(f"//{request.host}").hostname
        host = host.casefold().rstrip(".") if host else ""
        local_host = host in {"127.0.0.1", "localhost", "::1"}
        valid = expected is not False and local_host
        if origin_header not in (None, "", "null"):
            valid = valid and origin is not False
        if referer_header not in (None, "", "null"):
            valid = valid and referer is not False
        if origin_header not in (None, "", "null"):
            valid = valid and origin == expected
        if referer_header not in (None, "", "null"):
            valid = valid and referer == expected
        # Null or missing provenance is never itself trusted. A per-session
        # synchronizer token is required in those cases and also protects all
        # accepted upload posts.
        supplied_token = request.form.get("_csrf_token", "")
        # Flask's signed session cookie is the server-managed session boundary;
        # the token itself is stored in that session and compared in constant time.
        expected_token = session.get("v10_csrf_token", "")
        if not expected_token:
            valid = False
        else:
            valid = valid and hmac.compare_digest(supplied_token, expected_token)
        if origin_header in (None, "", "null") or referer_header in (None, "", "null"):
            valid = valid and bool(expected_token)
        if not valid:
            action = {
                "review_item": "Prüfentscheidung",
                "commit_import": "Übernahme",
                "accept_all_candidates": "Prüfentscheidung",
                "refresh_preview": "Übernahme",
                "save_account": "Kontenpflege",
                "save_instrument_type": "Instrumentpflege",
                "save_instrument": "Instrumentpflege",
                "deactivate_account": "Kontenpflege",
                "record_opening": "Kontenpflege",
                "preview_rollback_route": "Rücknahme",
                "execute_rollback_route": "Rücknahme",
            }.get(request.endpoint, "Upload")
            app.logger.warning(
                "V10-Schreibaktion abgelehnt (%s): Origin=%r Referer=%r Host=%r Vergleich=%r/%r Token=%s",
                action,
                origin_header,
                referer_header,
                request.headers.get("Host"),
                origin,
                expected,
                bool(expected_token),
            )
            messages = {
                "Prüfentscheidung": "Prüfentscheidung abgelehnt: lokale Herkunft oder sitzungsgebundener CSRF-Token ungültig.",
                "Übernahme": "Übernahme abgelehnt: lokale Herkunft oder sitzungsgebundener CSRF-Token ungültig.",
                "Kontenpflege": "Kontenpflege abgelehnt: lokale Herkunft oder sitzungsgebundener CSRF-Token ungültig.",
                "Instrumentpflege": "Instrumentpflege abgelehnt: lokale Herkunft oder sitzungsgebundener CSRF-Token ungültig.",
                "Rücknahme": "Rücknahme abgelehnt: lokale Herkunft oder sitzungsgebundener CSRF-Token ungültig.",
                "Upload": "Upload nur von der geöffneten lokalen V10-Seite erlaubt.",
            }
            abort(403, description=messages[action])

    @app.errorhandler(RequestEntityTooLarge)
    def upload_too_large(_error):
        return index_error("Upload überschreitet die Grenze von 50 MiB je Anfrage.", 413)

    @app.get("/health")
    def health():
        return "ok", 200, {"Content-Type": "text/plain; charset=utf-8"}

    @app.get("/")
    def index():
        token = session.setdefault("v10_csrf_token", secrets.token_urlsafe(32))
        return render_template("index.html", branch=branch, commit=commit, profile=profile, csrf_token=token)

    def index_error(message: str, status: int):
        return render_template("index.html", error=message, branch=branch, commit=commit, profile=profile,
                               csrf_token=session.setdefault("v10_csrf_token", secrets.token_urlsafe(32))), status

    def read_pdf(uploaded_file, prefix: str = "") -> tuple[bytes | None, str | None, int]:
        """Prüft eine hochgeladene Datei; liefert Inhalt oder eine verständliche Meldung mit HTTP-Status."""
        if Path(uploaded_file.filename.replace("\\", "/")).suffix.casefold() != ".pdf":
            return None, f"{prefix}Bitte eine Datei mit der Endung .pdf auswählen.", 400
        content = uploaded_file.stream.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            return None, f"{prefix}PDF überschreitet die Grenze von 50 MiB.", 413
        if not content:
            return None, f"{prefix}Die ausgewählte Datei ist leer.", 400
        return content, None, 200

    def upload_status(error: ApplicationError) -> int:
        return 400 if error.code in {ErrorCode.VALIDATION_ERROR, ErrorCode.INVALID_DOCUMENT} else 500

    @app.post("/imports")
    def upload_import():
        """Eine oder mehrere PDFs in einer Anfrage (Weg ohne JavaScript); mehrere ergeben einen gemeinsamen Import."""
        uploaded_files = [value for value in request.files.getlist("pdf") if value and value.filename]
        if not uploaded_files:
            return index_error("Bitte eine PDF-Datei auswählen.", 400)
        if len(uploaded_files) > MAX_BATCH_FILES:
            return index_error(f"Höchstens {MAX_BATCH_FILES} PDF-Dateien je Import.", 400)
        contents = []
        for uploaded_file in uploaded_files:
            prefix = f"{uploaded_file.filename}: " if len(uploaded_files) > 1 else ""
            content, message, status = read_pdf(uploaded_file, prefix)
            if message:
                return index_error(message + (" Es wurde nichts importiert." if prefix else ""), status)
            contents.append((uploaded_file.filename, content))
        try:
            document_ids = [workflow.upload_document(DocumentUpload(name, content)).document.document_id for name, content in contents]
            job = workflow.start_import(ImportStart(tuple(document_ids)))
        except ApplicationError as error:
            return index_error(error.message, upload_status(error))
        return redirect(url_for("job_page", job_id=job.job_id), code=303)

    @app.post("/documents")
    def stage_document():
        """Batch-Upload: eine PDF ablegen, noch ohne Import; die Startseite sammelt die Dokument-IDs."""
        uploaded_file = request.files.get("pdf")
        if uploaded_file is None or not uploaded_file.filename:
            return {"error": "Bitte eine PDF-Datei auswählen."}, 400
        content, message, status = read_pdf(uploaded_file)
        if message:
            return {"error": message}, status
        try:
            stored = workflow.upload_document(DocumentUpload(uploaded_file.filename, content))
        except ApplicationError as error:
            return {"error": error.message}, upload_status(error)
        return {"document_id": stored.document.document_id, "name": uploaded_file.filename,
                "already_stored": stored.identical_content_already_stored}, 201

    @app.post("/imports/batch")
    def start_batch_import():
        """Gemeinsamen Import aus zuvor abgelegten PDFs starten: eine Vorschau, eine Übernahme, gemeinsam rücknehmbar."""
        document_ids = tuple(dict.fromkeys(value.strip() for value in request.form.getlist("document_id") if value.strip()))
        if not document_ids:
            return index_error("Keine gespeicherten PDF-Dateien für den Import übergeben.", 400)
        if len(document_ids) > MAX_BATCH_FILES:
            return index_error(f"Höchstens {MAX_BATCH_FILES} PDF-Dateien je Import.", 400)
        try:
            job = workflow.start_import(ImportStart(document_ids))
        except ApplicationError as error:
            status = 404 if error.code == ErrorCode.NOT_FOUND else upload_status(error)
            return index_error(f"Import nicht gestartet: {error.message}", status)
        return redirect(url_for("job_page", job_id=job.job_id), code=303)

    @app.get("/jobs/<job_id>")
    def job_page(job_id: str):
        return render_job(job_id)

    def render_job(job_id: str, *, action_error: str | None = None, status: int = 200):
        try:
            job = workflow.get_job(job_id)
            documents = workflow.get_import_document_results(job_id)
        except ApplicationError as error:
            abort(404, description=error.message)
        try:
            preview = workflow.get_import_preview(job.import_id)
        except ApplicationError as error:
            if error.code != ErrorCode.NOT_FOUND:
                abort(500, description=error.message)
            preview = None
        commit_report = None
        try:
            raw_report = workflow.store.load_import_commit_report(job.import_id)
            commit_report = raw_report
        except (sqlite3.Error, NameError):
            commit_report = None
        stale_preview = bool(preview and not commit_report and job.state == "needs_review"
                             and preview.data_revision != current_data_revision(preview.data_revision))
        return render_template(
            "job.html",
            job=job,
            documents=documents,
            preview=_present_preview(workflow, preview) if preview else (),
            csrf_token=session.setdefault("v10_csrf_token", secrets.token_urlsafe(32)),
            has_preview=preview is not None,
            preview_revision=preview.revision if preview else 0,
            summary=_preview_summary(preview) if preview else {"events": 0, "cash": 0, "quantity": 0, "unresolved": 0, "undecided": 0},
            commit_report=commit_report,
            stale_preview=stale_preview,
            bulk=_bulk_summary(preview) if preview else {"ready": 0, "others": 0},
            bulk_accepted=request.args.get("accepted", type=int),
            action_error=action_error,
            status_labels=STATUS_LABELS,
            branch=branch,
            commit=commit,
            profile=profile,
        ), status

    def current_data_revision(fallback: int) -> int:
        """Aktueller Datenstand über die Anwendungsschnittstelle; ohne Antwort keine Warnung."""
        try:
            return workflow.list_imports(None, 1).data_revision
        except ApplicationError:
            return fallback

    def render_import_error(import_id: str, message: str, status: int):
        """Fehler einer Schreibaktion auf der Importseite selbst anzeigen statt als nackte Fehlerseite."""
        try:
            job_id = workflow.store.find_job_by_import(import_id)
        except Exception:
            job_id = None
        if not job_id:
            abort(404, description="Import nicht gefunden")
        return render_job(job_id, action_error=message, status=status)

    @app.post("/imports/<import_id>/review")
    def review_item(import_id: str):
        try:
            preview = workflow.get_import_preview(import_id)
            candidate_id = request.form.get("candidate_id", "")
            candidate = next((item for item in preview.items if item.candidate_id == candidate_id), None)
            if candidate is None:
                abort(404, description="Vorschaukandidat nicht gefunden")
            action = request.form.get("decision", "")
            if action not in {"accept", "accept_unmatched", "link", "ignore"}:
                abort(400, description="Ungültige Prüfentscheidung")
            if action == "accept_unmatched":
                if not _is_finanzreport_row(candidate):
                    return render_import_error(import_id, "Prüfentscheidung nicht gespeichert: „Als neue Buchung übernehmen“ gibt es nur für referenzlose Finanzreportzeilen.", 400)
                blocker = _unmatched_blocker(candidate)
                if blocker:
                    return render_import_error(import_id, f"Prüfentscheidung nicht gespeichert: {blocker}", 400)
            elif _is_finanzreport_row(candidate) and action == "link" and not candidate.conflicts:
                return render_import_error(import_id, "Prüfentscheidung nicht gespeichert: Für diese Zeile gibt es keinen bestehenden Vorgang zum Zuordnen.", 400)
            elif candidate.review_status in IGNORE_ONLY_STATUSES and action != "ignore" and not (_is_finanzreport_row(candidate) and action == "link"):
                return render_import_error(import_id, "Prüfentscheidung nicht gespeichert: Dieser Vorgangstyp ist nicht zur Übernahme freigegeben und kann nur ignoriert werden.", 400)
            related = next((value.related_event_id for value in candidate.conflicts if value.related_event_id), None)
            workflow.resolve_import_item(import_id, ConflictDecision(candidate_id, "link" if action == "link" else action, target_id=related if action == "link" else None, candidate_revision=candidate.revision), preview.revision)
            # Zurück an die Stelle des entschiedenen Kandidaten statt an den Seitenanfang.
            return redirect(url_for("job_by_import", import_id=import_id, _anchor=f"candidate-{candidate_id}"), code=303)
        except ApplicationError as error:
            if error.code == ErrorCode.NOT_FOUND:
                abort(404, description=error.message)
            return render_import_error(import_id, f"Prüfentscheidung nicht gespeichert: {error.message}", 409 if error.code == ErrorCode.STALE_REVISION else 400)

    @app.post("/imports/<import_id>/accept-all")
    def accept_all_candidates(import_id: str):
        """Alle bereiten Kandidaten der angezeigten Vorschauversion annehmen; jede Entscheidung über die Anwendungsschnittstelle."""
        try:
            preview = workflow.get_import_preview(import_id)
            expected = int(request.form.get("preview_revision", "-1"))
        except ValueError:
            abort(400, description="Ungültige Vorschauversion")
        except ApplicationError as error:
            if error.code == ErrorCode.NOT_FOUND:
                abort(404, description=error.message)
            raise
        if preview.revision != expected:
            return render_import_error(import_id, "Nicht angenommen: Die Vorschau hat sich seit dem Laden der Seite geändert. Bitte die Kandidaten erneut prüfen.", 409)
        unmatched = request.form.get("mode") == "unmatched"
        decision = "accept_unmatched" if unmatched else "accept"
        accepted = 0
        for candidate in (_bulk_unmatched(preview) if unmatched else _bulk_acceptable(preview)):
            try:
                preview = workflow.resolve_import_item(import_id, ConflictDecision(candidate.candidate_id, decision, candidate_revision=candidate.revision), preview.revision)
            except ApplicationError as error:
                return render_import_error(import_id, f"Nach {accepted} angenommenen Kandidaten abgebrochen: {error.message}",
                                           409 if error.code == ErrorCode.STALE_REVISION else 400)
            accepted += 1
        job_id = workflow.store.find_job_by_import(import_id)
        return redirect(url_for("job_page", job_id=job_id, accepted=accepted, _anchor="commit-area"), code=303)

    @app.get("/imports/<import_id>")
    def job_by_import(import_id: str):
        try:
            row = workflow.store.find_job_by_import(import_id)
        except Exception:
            row = None
        if not row:
            abort(404, description="Import nicht gefunden")
        return redirect(url_for("job_page", job_id=row), code=302)

    @app.post("/imports/<import_id>/commit")
    def commit_import(import_id: str):
        try:
            workflow.commit_import(CommitImport(import_id, int(request.form.get("preview_revision", "0")), request.form.get("request_id", "")))
            return redirect(url_for("job_by_import", import_id=import_id), code=303)
        except (ValueError, ApplicationError) as error:
            if isinstance(error, ApplicationError) and error.code == ErrorCode.NOT_FOUND:
                abort(404, description=error.message)
            status = 409 if isinstance(error, ApplicationError) and error.code in {ErrorCode.STALE_REVISION, ErrorCode.POSSIBLE_DUPLICATE, ErrorCode.SOURCE_CONFLICT} else 400
            message = error.message if isinstance(error, ApplicationError) else "Ungültige Übernahmeanfrage"
            if isinstance(error, ApplicationError) and error.code == ErrorCode.STALE_REVISION:
                message = f"{STALE_PREVIEW_TEXT} ({message})"
            return render_import_error(import_id, f"Übernahme nicht ausgeführt: {message}", status)

    @app.post("/imports/<import_id>/refresh")
    def refresh_preview(import_id: str):
        """Dieselben gespeicherten Belege mit aktuellem Datenstand neu einlesen; der alte Import bleibt unverändert."""
        try:
            job_id = workflow.store.find_job_by_import(import_id)
        except Exception:
            job_id = None
        if not job_id:
            abort(404, description="Import nicht gefunden")
        try:
            job = workflow.get_job(job_id)
            if workflow.store.load_import_commit_report(import_id) is not None or job.state != "needs_review":
                return render_job(job_id, action_error="Vorschau nicht neu erstellt: Dieser Import ist nicht mehr offen.", status=409)
            document_ids = tuple(dict.fromkeys(item.document_id for item in workflow.get_import_document_results(job_id) if item.document_id))
            if not document_ids:
                return render_job(job_id, action_error="Vorschau nicht neu erstellt: Keine gespeicherten Belege gefunden.", status=400)
            new_job = workflow.start_import(ImportStart(document_ids))
        except ApplicationError as error:
            return render_job(job_id, action_error=f"Vorschau nicht neu erstellt: {error.message}", status=400)
        return redirect(url_for("job_page", job_id=new_job.job_id), code=303)

    def all_pages(list_page):
        """Stammdaten sind klein: alle Seiten über den stabilen Cursor der Anwendungsschicht laden."""
        items, cursor = [], None
        while True:
            page = list_page(cursor, 500)
            items.extend(page.items)
            cursor = page.next_cursor
            if cursor is None:
                return tuple(items)

    def all_accounts():
        return all_pages(workflow.store.list_accounts)

    @app.get("/overview")
    def overview_page():
        today = date.today()
        try:
            as_of = date.fromisoformat(request.args.get("date", "")) if request.args.get("date") else today
        except ValueError:
            as_of, date_error = today, "Ungültiges Datum; es wird heute angezeigt."
        else:
            date_error = None
        step = request.args.get("step", "month")
        if step not in dict(STEPS):
            step = "month"
        anchor = parse_anchor(request.args.get("anchor"), as_of)
        navigation = {
            "previous": url_for("overview_page", date=shift(as_of, step, -1, anchor).isoformat(), step=step, anchor=anchor),
            "next": url_for("overview_page", date=shift(as_of, step, 1, anchor).isoformat(), step=step, anchor=anchor),
            "today": url_for("overview_page", date=today.isoformat(), step=step),
            "steps": tuple((value, label, url_for("overview_page", date=as_of.isoformat(), step=value, anchor=anchor)) for value, label in STEPS),
        }
        context = {"as_of": as_of.isoformat(), "step": step, "navigation": navigation, "error": date_error, "notice": None,
                   "groups": (), "data_revision": None, "branch": branch, "commit": commit, "profile": profile}
        # Stände ausschließlich über get_overview(as_of) aus dem Anwendungsvertrag (Bestandsindex, V10-19 bis V10-21).
        get_overview = getattr(workflow.store, "get_overview", None)
        if get_overview is None:
            context["notice"] = "Stichtagsübersicht noch nicht verfügbar: Der Bestandsindex (V10-19 bis V10-21) ist im Datenkern noch nicht umgesetzt."
            return render_template("overview.html", **context)
        try:
            overview = get_overview(as_of)
        except ApplicationError as error:
            context["error"] = error.message
            return render_template("overview.html", **context), 400
        accounts = {account.account_id: account for account in all_accounts()}
        instruments = {}
        groups = {}
        for line in overview.lines:
            if line.instrument_id and line.instrument_id not in instruments:
                try:
                    instruments[line.instrument_id] = workflow.store.get_instrument(line.instrument_id).name
                except ApplicationError:
                    instruments[line.instrument_id] = f"Instrument {line.instrument_id[:8]}"
            account = accounts.get(line.account_id)
            group = groups.setdefault(line.account_id, {
                "account_id": line.account_id,
                "name": account.name if account else f"Konto {line.account_id[:8]}",
                "type": SUBTYPE_LABELS.get(account.subtype, account.subtype) if account else "",
                "active": account.active if account else True,
                "lines": [],
            })
            group["lines"].append({
                "unit": instruments[line.instrument_id] if line.instrument_id else (line.currency or ""),
                "is_quantity": line.instrument_id is not None,
                # Fehlend ist unbekannt, nicht null.
                "value": line.value.text if line.value is not None else "Unbekannt",
                "completeness": {"complete": "vollständig", "incomplete": "unvollständig", "unknown": "unbekannt"}.get(line.completeness, line.completeness),
                "flag": line.completeness != "complete",
            })
        context["groups"] = tuple(sorted(groups.values(), key=lambda value: (not value["active"], value["name"].casefold())))
        context["data_revision"] = overview.data_revision
        return render_template("overview.html", **context)

    @app.get("/imports")
    def imports_page():
        cursor = request.args.get("cursor") or None
        context = {"rows": (), "next_cursor": None, "error": None, "is_continuation": cursor is not None,
                   "csrf_token": session.setdefault("v10_csrf_token", secrets.token_urlsafe(32)),
                   "branch": branch, "commit": commit, "profile": profile}
        try:
            page = workflow.store.list_imports(cursor, 100)
        except ApplicationError as error:
            context["error"] = "Importliste hat sich geändert; bitte von vorn laden." if error.code == ErrorCode.STALE_REVISION else error.message
            return render_template("imports.html", **context), 409 if error.code == ErrorCode.STALE_REVISION else 400
        context["rows"] = tuple({
            "import_id": item.import_id,
            "can_roll_back": item.import_status == "committed",
            "job_id": item.job_id,
            "started_at": item.started_at.replace("T", " ")[:19],
            "filenames": item.filenames,
            "import_status": IMPORT_STATUS_LABELS.get(item.import_status, item.import_status),
            "job_status": STATUS_LABELS.get(item.job_status, item.job_status),
            "candidates": item.candidate_count,
            "rolled_back": item.import_status == "rolled_back",
        } for item in page.items)
        context["next_cursor"] = page.next_cursor
        return render_template("imports.html", **context)

    def render_instruments(*, error=None, saved=None, status=200, form=None):
        instruments = sorted(all_pages(workflow.store.list_instruments), key=lambda item: (item.name.casefold(), item.instrument_id))
        rows = tuple({
            "instrument_id": item.instrument_id,
            "name": item.name,
            "asset_type": item.asset_type,
            "asset_type_known": item.asset_type in INSTRUMENT_TYPE_LABELS,
            "isin": item.isin or "–",
            "wkn": item.wkn or "–",
            "identifiers": tuple(f"{value.provider}/{value.identifier_type} {value.value} ({value.context})" for value in item.identifiers),
            "revision": item.revision,
        } for item in instruments)
        return render_template(
            "instruments.html", rows=rows, types=tuple(INSTRUMENT_TYPE_LABELS.items()), error=error, saved=saved,
            form=form or InstrumentForm(),
            csrf_token=session.setdefault("v10_csrf_token", secrets.token_urlsafe(32)), branch=branch, commit=commit, profile=profile,
        ), status

    def import_label(import_id: str) -> str:
        try:
            job_id = workflow.store.find_job_by_import(import_id)
            names = [document.name for document in workflow.get_import_document_results(job_id)] if job_id else []
        except ApplicationError:
            names = []
        return ", ".join(names) or f"Import {import_id[:8]}"

    def present_rollback(plan):
        accounts, instruments = {}, {}

        def account_name(account_id):
            if account_id not in accounts:
                try:
                    accounts[account_id] = workflow.store.get_account(account_id).name
                except ApplicationError:
                    accounts[account_id] = f"Konto {account_id[:8]}"
            return accounts[account_id]

        def instrument_name(instrument_id):
            if instrument_id not in instruments:
                try:
                    instruments[instrument_id] = workflow.store.get_instrument(instrument_id).name
                except ApplicationError:
                    instruments[instrument_id] = None
            return instruments[instrument_id]

        impacts = []
        for value in plan.balance_impacts:
            # Format laut docs/Schnittstelle.md: Konto-ID|Währung/Instrument|signierter Positionsbetrag
            parts = value.split("|")
            if len(parts) != 3:
                impacts.append({"account": value, "unit": "", "amount": ""})
                continue
            account_id, unit, amount = parts
            kind, _, reference = unit.partition(":")
            if kind == "INSTRUMENT":
                unit = f"{instrument_name(reference) or 'Instrument ' + reference[:8]} (Stück)"
            elif kind == "CURRENCY":
                unit = reference
            impacts.append({"account": account_name(account_id), "unit": unit, "amount": amount})
        return {
            "plan_id": plan.plan_id,
            "revision": plan.revision,
            "imports": tuple(import_label(value) for value in plan.import_ids),
            "import_ids": plan.import_ids,
            "events": len(plan.affected_event_ids),
            "contributions": len(plan.affected_contribution_ids) or len(plan.affected_contributions),
            "documents": len(plan.affected_document_links),
            "impacts": tuple(impacts),
            "removable_instruments": tuple(instrument_name(value) or value for value in plan.removable_instrument_ids),
            "dependencies": plan.unresolved_dependencies,
            "request_id": f"web-rollback-{plan.plan_id}-{plan.revision}",
        }

    def render_imports_error(message: str, status: int):
        return render_template("imports.html", rows=(), next_cursor=None, error=message, is_continuation=False,
                               csrf_token=session.setdefault("v10_csrf_token", secrets.token_urlsafe(32)),
                               branch=branch, commit=commit, profile=profile), status

    @app.post("/rollbacks/preview")
    def preview_rollback_route():
        all_imports = request.form.get("all_imports") == "1"
        import_ids = tuple(dict.fromkeys(value for value in request.form.getlist("import_id") if value.strip()))
        if all_imports and request.form.get("confirm_all") != "1":
            return render_imports_error("Für „alle Importe zurücknehmen“ bitte die Bestätigung anhaken.", 400)
        try:
            selection = RollbackSelection(all_imports=True) if all_imports else RollbackSelection(import_ids=import_ids)
        except ValueError:
            return render_imports_error("Bitte mindestens einen übernommenen Import auswählen.", 400)
        try:
            plan = workflow.preview_rollback(selection)
        except ApplicationError as error:
            message = f"Rücknahmevorschau nicht möglich: {error.message}"
            return_to = safe_return_path(request.form.get("return_to", ""))
            if return_to and len(import_ids) == 1:
                return render_import_error(import_ids[0], message, 400)
            return render_imports_error(message, 409 if error.code == ErrorCode.STALE_REVISION else 400)
        return render_template("rollback.html", plan=present_rollback(plan), report=None,
                               csrf_token=session.setdefault("v10_csrf_token", secrets.token_urlsafe(32)),
                               branch=branch, commit=commit, profile=profile)

    @app.post("/rollbacks/execute")
    def execute_rollback_route():
        try:
            command = ExecuteRollback(request.form.get("plan_id", ""), int(request.form.get("expected_revision", "")), request.form.get("request_id", ""))
        except ValueError:
            return render_imports_error("Ungültige Rücknahmeanfrage.", 400)
        try:
            report = workflow.execute_rollback(command)
        except ApplicationError as error:
            hint = " Bitte die Rücknahmevorschau neu erstellen." if error.code in {ErrorCode.STALE_REVISION, ErrorCode.DEPENDENCY_CONFLICT} else ""
            return render_imports_error(f"Rücknahme nicht ausgeführt: {error.message}.{hint}",
                                        409 if error.code in {ErrorCode.STALE_REVISION, ErrorCode.DEPENDENCY_CONFLICT} else 400)
        return render_template("rollback.html", plan=None, report={
            "imports": tuple(import_label(value) for value in report.removed_import_ids),
            "events": len(report.removed_event_ids),
            "positions": len(report.removed_position_ids),
            "instruments": len(report.removed_instrument_ids),
            "retained": len(report.retained_event_ids),
            "data_revision": report.data_revision,
            "replayed": report.replayed,
        }, csrf_token=session.setdefault("v10_csrf_token", secrets.token_urlsafe(32)), branch=branch, commit=commit, profile=profile)

    @app.get("/instruments")
    def instruments_page():
        saved = None
        if request.args.get("saved"):
            try:
                saved = workflow.store.get_instrument(request.args["saved"]).name
            except ApplicationError:
                saved = None
        return render_instruments(saved=saved)

    @app.get("/instruments/new")
    def new_instrument():
        values = request.args
        return render_instruments(form=InstrumentForm(name=values.get("name", ""), isin=values.get("isin", ""), wkn=values.get("wkn", ""),
                                                      return_to=safe_return_path(values.get("return_to", "")) or ""))

    @app.get("/instruments/<instrument_id>/edit")
    def edit_instrument(instrument_id: str):
        try:
            instrument = workflow.store.get_instrument(instrument_id)
        except ApplicationError as error:
            abort(404, description=error.message)
        return render_instruments(form=form_from_instrument(instrument))

    @app.post("/instruments")
    def save_instrument():
        instrument_id = request.form.get("instrument_id", "").strip()
        current = None
        if instrument_id:
            try:
                current = workflow.store.get_instrument(instrument_id)
            except ApplicationError as error:
                abort(404, description=error.message)
        try:
            value, expected_revision = instrument_input_from_form(request.form, current, workflow.store)
            saved = workflow.store.save_instrument(value, expected_revision)
        except (InstrumentFormError, ApplicationError) as error:
            message = error.message if isinstance(error, ApplicationError) else str(error)
            if isinstance(error, ApplicationError) and error.code == ErrorCode.STALE_REVISION:
                message = "Instrument wurde inzwischen geändert; bitte neu öffnen."
            status = 409 if isinstance(error, ApplicationError) and error.code == ErrorCode.STALE_REVISION else 400
            return render_instruments(error=message, status=status, form=instrument_form_from_request(request.form, current))
        return_to = safe_return_path(request.form.get("return_to", ""))
        if return_to:
            return redirect(return_to, code=303)
        return redirect(url_for("instruments_page", saved=saved.instrument_id, _anchor=f"instrument-{saved.instrument_id}"), code=303)

    @app.post("/instruments/<instrument_id>/asset-type")
    def save_instrument_type(instrument_id: str):
        try:
            current = workflow.store.get_instrument(instrument_id)
        except ApplicationError as error:
            abort(404, description=error.message)
        asset_type = request.form.get("asset_type", "")
        if asset_type not in INSTRUMENT_TYPE_LABELS:
            return render_instruments(error="Bitte eine Art aus der Auswahlliste wählen.", status=400)
        try:
            expected_revision = int(request.form.get("expected_revision", ""))
        except ValueError:
            return render_instruments(error="Erwartete Instrument-Revision fehlt oder ist ungültig.", status=400)
        try:
            # Vollständiger Datensatzstand: Name, ISIN/WKN und alle Kennungen unverändert übernehmen.
            saved = workflow.store.save_instrument(InstrumentInput(
                current.name, asset_type, current.isin, current.wkn, current.instrument_id, current.identifiers,
            ), expected_revision)
        except ValueError as error:
            return render_instruments(error=str(error), status=400)
        except ApplicationError as error:
            message = "Instrument wurde inzwischen geändert; Liste neu geladen, bitte erneut wählen." if error.code == ErrorCode.STALE_REVISION else error.message
            return render_instruments(error=message, status=409 if error.code == ErrorCode.STALE_REVISION else 400)
        return redirect(url_for("instruments_page", saved=saved.instrument_id, _anchor=f"instrument-{saved.instrument_id}"), code=303)

    def render_accounts(*, edit_form=None, cash_form=None, depot_form=None, error=None, saved=None, status=200):
        accounts = all_accounts()
        exclude = edit_form.account_id if edit_form else None
        banks = sorted({account.institution for account in accounts if account.institution} | {"comdirect"}, key=str.casefold)
        return render_template(
            "accounts.html",
            rows=account_rows(accounts),
            cash_types=CASH_FORM_TYPES,
            position_types=POSITION_FORM_TYPES,
            references=reference_options(accounts, exclude),
            banks=banks,
            edit_form=edit_form,
            cash_form=cash_form or AccountForm("checking"),
            depot_form=depot_form or AccountForm("depot", currency=""),
            error=error,
            saved=saved,
            csrf_token=session.setdefault("v10_csrf_token", secrets.token_urlsafe(32)),
            branch=branch,
            commit=commit,
            profile=profile,
        ), status

    @app.get("/accounts")
    def accounts_page():
        saved = None
        saved_id = request.args.get("saved")
        if saved_id:
            try:
                saved = workflow.store.get_account(saved_id).name
            except ApplicationError:
                saved = None
        return render_accounts(saved=saved)

    @app.get("/accounts/<account_id>")
    def account_detail(account_id: str):
        return render_account_detail(account_id)

    def render_account_detail(account_id: str, *, action_error=None, opening_values=None, status=200):
        try:
            account = workflow.store.get_account(account_id)
        except ApplicationError as error:
            abort(404, description=error.message)
        cursor = request.args.get("cursor") or None if request.method == "GET" else None
        row = account_rows((account,))[0]
        if account.reference_account_id:
            try:
                row["reference"] = workflow.store.get_account(account.reference_account_id).name
            except ApplicationError:
                row["reference"] = "Konto nicht verfügbar"
        opened = None
        if request.method == "GET" and request.args.get("opened"):
            try:
                opened = workflow.store.get_opening(request.args["opened"])
            except ApplicationError:
                opened = None
        values = dict(opening_values or {})
        values.setdefault("opening_id", secrets.token_hex(16))  # Wiederholungsschutz für genau dieses Formular
        context = {"account": row, "bookings": None, "next_cursor": None, "notice": None, "error": None,
                   "is_continuation": cursor is not None, "branch": branch, "commit": commit, "profile": profile,
                   "action_error": action_error, "kind": account.kind, "account_currency": account.currency,
                   "opening": values, "opened": {
                       "date": opened.effective_date.isoformat(),
                       "value": f"{opened.amount.text} {opened.currency}" if opened.amount else f"{opened.quantity.text} Stück",
                       "cost": {"known": "Anschaffungskosten bekannt", "unknown": "Anschaffungskosten unbekannt"}.get(opened.cost_basis_status, ""),
                   } if opened else None,
                   "deactivated": request.method == "GET" and request.args.get("deactivated") == "1",
                   "instruments": tuple(sorted(((item.instrument_id, f"{item.name} · {item.isin or item.wkn or 'ohne Kennung'}")
                                                for item in all_pages(workflow.store.list_instruments)), key=lambda value: value[1].casefold()))
                   if account.kind == "position" else (),
                   "csrf_token": session.setdefault("v10_csrf_token", secrets.token_urlsafe(32))}
        # Buchungen ausschließlich über den Anwendungsvertrag search_transactions(Search); keine eigene SQL-Abfrage.
        search = getattr(workflow.store, "search_transactions", None)
        if search is None:
            context["notice"] = "Buchungsanzeige noch nicht verfügbar: Die Buchungssuche (V10-27) ist im Datenkern noch nicht umgesetzt."
            return render_template("account.html", **context), status
        try:
            page = search(Search(account_ids=(account_id,), include_inactive_accounts=True, cursor=cursor, limit=100))
        except ApplicationError as error:
            context["error"] = "Buchungen haben sich geändert; bitte von vorn laden." if error.code == ErrorCode.STALE_REVISION else error.message
            return render_template("account.html", **context), 409 if error.code == ErrorCode.STALE_REVISION else 400
        context["bookings"] = tuple({
            "date": item.booking_date.isoformat(),
            "kind": item.kind,
            "description": item.description,
            "amount": item.amount.text if item.amount else "Unbekannt",
            "currency": item.currency or "",
            "active": item.active,
        } for item in page.items)
        context["next_cursor"] = page.next_cursor
        return render_template("account.html", **context), status

    @app.post("/accounts/<account_id>/deactivate")
    def deactivate_account(account_id: str):
        if request.form.get("confirm") != "1":
            return render_account_detail(account_id, action_error="Zum Deaktivieren bitte die Bestätigung anhaken.", status=400)
        try:
            workflow.store.deactivate_account(account_id, int(request.form.get("expected_revision", "")))
        except ValueError:
            return render_account_detail(account_id, action_error="Erwartete Konto-Revision fehlt oder ist ungültig.", status=400)
        except ApplicationError as error:
            if error.code == ErrorCode.NOT_FOUND:
                abort(404, description=error.message)
            message = "Konto wurde inzwischen geändert; bitte erneut prüfen." if error.code == ErrorCode.STALE_REVISION else error.message
            return render_account_detail(account_id, action_error=f"Nicht deaktiviert: {message}", status=409 if error.code == ErrorCode.STALE_REVISION else 400)
        return redirect(url_for("account_detail", account_id=account_id, deactivated="1"), code=303)

    @app.post("/accounts/<account_id>/openings")
    def record_opening(account_id: str):
        try:
            account = workflow.store.get_account(account_id)
        except ApplicationError as error:
            abort(404, description=error.message)
        entered = {key: request.form.get(key, "") for key in ("opening_id", "effective_date", "amount", "instrument_id", "quantity",
                                                               "acquired_on", "acquisition_cost", "cost_currency", "note")}
        opening_id = entered["opening_id"].strip()
        if opening_id:
            # Erneutes Absenden desselben Formulars legt keinen zweiten Startbestand an.
            try:
                existing = workflow.store.get_opening(opening_id)
            except ApplicationError:
                existing = None
            if existing is not None:
                if existing.account_id != account_id:
                    return render_account_detail(account_id, action_error="Formularkennung gehört zu einem anderen Konto; bitte Seite neu laden.", status=409)
                return redirect(url_for("account_detail", account_id=account_id, opened=opening_id), code=303)
        try:
            saved = workflow.store.record_opening(opening_input_from_form(request.form, account))
        except OpeningFormError as error:
            return render_account_detail(account_id, action_error=f"Eröffnung nicht gespeichert: {error}", opening_values=entered, status=400)
        except ApplicationError as error:
            return render_account_detail(account_id, action_error=f"Eröffnung nicht gespeichert: {error.message}", opening_values=entered,
                                         status=404 if error.code == ErrorCode.NOT_FOUND else 400)
        return redirect(url_for("account_detail", account_id=account_id, opened=saved.opening_id), code=303)

    @app.get("/accounts/<account_id>/edit")
    def edit_account(account_id: str):
        try:
            account = workflow.store.get_account(account_id)
        except ApplicationError as error:
            abort(404, description=error.message)
        try:
            return render_accounts(edit_form=form_from_account(account))
        except AccountFormError as error:
            return render_accounts(error=str(error), status=400)

    @app.post("/accounts")
    def save_account():
        account_id = request.form.get("account_id", "").strip()
        current = None
        if account_id:
            try:
                current = workflow.store.get_account(account_id)
            except ApplicationError as error:
                abort(404, description=error.message)
        try:
            value, expected_revision = account_input_from_form(request.form, current)
            saved = workflow.store.save_account(value, expected_revision)
        except (AccountFormError, ApplicationError) as error:
            message = error.message if isinstance(error, ApplicationError) else str(error)
            status = 409 if isinstance(error, ApplicationError) and error.code == ErrorCode.STALE_REVISION else 400
            entered = form_from_request(request.form, current)
            if current is not None:
                return render_accounts(edit_form=entered, error=message, status=status)
            if entered.is_cash:
                return render_accounts(cash_form=entered, error=message, status=status)
            return render_accounts(depot_form=entered, error=message, status=status)
        return redirect(url_for("accounts_page", saved=saved.account_id), code=303)

    @app.get("/documents/<document_id>")
    def open_document(document_id: str):
        try:
            document = workflow.get_document(document_id)
        except ApplicationError as error:
            abort(404, description=error.message)
        return send_file(
            BytesIO(document.content),
            mimetype="application/pdf",
            as_attachment=False,
            download_name=document.metadata.name,
            conditional=False,
        )

    @app.errorhandler(404)
    def not_found(error):
        return render_template("index.html", error=getattr(error, "description", "Seite nicht gefunden."), branch=branch, commit=commit, profile=profile), 404

    @app.errorhandler(403)
    def forbidden(error):
        return render_template("index.html", error=getattr(error, "description", "Anfrage nicht erlaubt."), branch=branch, commit=commit, profile=profile), 403

    return app


def main() -> None:
    data_dir = Path(os.environ.get("PORTMAN_V10_WEB_DATA", PACKAGE_ROOT / "data" / "web-test")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    branch = os.environ.get("PORTMAN_V10_BRANCH", _git_value("branch", "--show-current"))
    commit = os.environ.get("PORTMAN_V10_COMMIT", _git_value("rev-parse", "--short", "HEAD"))
    workflow = ImportWorkflow(SQLiteStore(data_dir / "v10.sqlite"), data_dir)
    app = create_app(workflow, branch=branch, commit=commit, profile=f"isoliertes Web-Testprofil · {data_dir / 'v10.sqlite'}")
    try:
        app.run(host="127.0.0.1", port=int(os.environ.get("PORTMAN_V10_WEB_PORT", "8765")), debug=False, use_reloader=False, threaded=True)
    finally:
        workflow.close()


if __name__ == "__main__":
    main()
