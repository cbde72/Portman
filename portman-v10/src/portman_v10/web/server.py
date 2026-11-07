"""Serverseitige lokale Weboberfläche für den vorhandenen V10-Importworkflow."""
from io import BytesIO
import hmac
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
from urllib.parse import urlsplit

from flask import Flask, abort, redirect, render_template, request, send_file, session, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from portman_v10.application.contracts import ApplicationError, CommitImport, ConflictDecision, DocumentUpload, ErrorCode, ImportStart
from portman_v10.infrastructure.import_workflow import ImportWorkflow
from portman_v10.infrastructure.parser_adapter import _resolve_instrument
from portman_v10.infrastructure.sqlite_store import SQLiteStore
from portman_v10.web.accounts import (
    AccountForm, AccountFormError, account_input_from_form, account_rows, form_from_account, form_from_request, reference_options,
)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 64 * 1024
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
# Diese Kandidaten überspringt SQLiteStore.commit_import; alle übrigen brauchen eine Entscheidung.
# needs_review hat in job.html keine Entscheidungsknöpfe und blockiert die Übernahme bereits als offener Punkt.
NO_DECISION_STATUSES = frozenset({"information", "error", "duplicate_file", "needs_review"})
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
        })
    return tuple(summaries)


def _present_preview(workflow: ImportWorkflow, preview):
    presented = []
    decisions = {value.candidate_id: value.decision.decision for value in preview.decisions}
    decision_labels = {"accept": "Kandidat angenommen", "link": "Als Ergänzungsbeleg zugeordnet", "ignore": "Kandidat ignoriert"}
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
        checks = list(f"Prüfen: {value}" for value in item.missing_fields)
        checks.extend(f"Prüfen: {value.message}" for value in item.conflicts)
        checks.extend(f"Prüfen: {value['message']}" for value in warnings if value["severity"] in {"WARNING", "ERROR"})
        decision_missing = item.review_status not in NO_DECISION_STATUSES and item.candidate_id not in decisions
        if decision_missing:
            checks.insert(0, "Prüfen: Entscheidung fehlt – „Kandidat prüfen / annehmen“ oder „Ignorieren“ wählen")
        presented.append({
            "kind": item.suggested_kind or item.kind,
            "status": item.review_status,
            "decision_missing": decision_missing,
            "decision_status": decision_labels.get(decisions.get(item.candidate_id)),
            "candidate_id": item.candidate_id,
            "candidate_revision": item.revision,
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


def _preview_summary(preview):
    cash = sum(1 for item in preview.items for movement in item.movements if movement.movement_type == "cash")
    quantity = sum(1 for item in preview.items for movement in item.movements if movement.movement_type == "quantity")
    unresolved = sum(1 for item in preview.items if item.missing_fields or item.conflicts or item.review_status != "complete_candidate")
    decided = {value.candidate_id for value in preview.decisions}
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
        MAX_FORM_PARTS=8,
        TRUSTED_HOSTS=["127.0.0.1", "localhost"],
        SECRET_KEY=secrets.token_urlsafe(32),
        SESSION_COOKIE_DOMAIN=None,
    )

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'self'; base-uri 'none'; form-action 'self'"
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
                "save_account": "Kontenpflege",
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
                "Upload": "Upload nur von der geöffneten lokalen V10-Seite erlaubt.",
            }
            abort(403, description=messages[action])

    @app.errorhandler(RequestEntityTooLarge)
    def upload_too_large(_error):
        return render_template("index.html", error="Upload überschreitet die Grenze von 50 MiB.", branch=branch, commit=commit, profile=profile), 413

    @app.get("/health")
    def health():
        return "ok", 200, {"Content-Type": "text/plain; charset=utf-8"}

    @app.get("/")
    def index():
        token = session.setdefault("v10_csrf_token", secrets.token_urlsafe(32))
        return render_template("index.html", branch=branch, commit=commit, profile=profile, csrf_token=token)

    @app.post("/imports")
    def upload_import():
        uploaded_file = request.files.get("pdf")
        if uploaded_file is None or not uploaded_file.filename:
            return render_template("index.html", error="Bitte eine PDF-Datei auswählen.", branch=branch, commit=commit, profile=profile), 400
        if Path(uploaded_file.filename.replace("\\", "/")).suffix.casefold() != ".pdf":
            return render_template("index.html", error="Bitte eine Datei mit der Endung .pdf auswählen.", branch=branch, commit=commit, profile=profile), 400
        content = uploaded_file.stream.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            return render_template("index.html", error="PDF überschreitet die Grenze von 50 MiB.", branch=branch, commit=commit, profile=profile), 413
        if not content:
            return render_template("index.html", error="Die ausgewählte Datei ist leer.", branch=branch, commit=commit, profile=profile), 400

        try:
            stored = workflow.upload_document(DocumentUpload(uploaded_file.filename, content))
            job = workflow.start_import(ImportStart((stored.document.document_id,)))
        except ApplicationError as error:
            return render_template("index.html", error=error.message, branch=branch, commit=commit, profile=profile), 400 if error.code in {ErrorCode.VALIDATION_ERROR, ErrorCode.INVALID_DOCUMENT} else 500
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
            action_error=action_error,
            status_labels=STATUS_LABELS,
            branch=branch,
            commit=commit,
            profile=profile,
        ), status

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
            if action not in {"accept", "link", "ignore"}:
                abort(400, description="Ungültige Prüfentscheidung")
            related = next((value.related_event_id for value in candidate.conflicts if value.related_event_id), None)
            workflow.resolve_import_item(import_id, ConflictDecision(candidate_id, "link" if action == "link" else action, target_id=related if action == "link" else None, candidate_revision=candidate.revision), preview.revision)
            return redirect(url_for("job_by_import", import_id=import_id), code=303)
        except ApplicationError as error:
            if error.code == ErrorCode.NOT_FOUND:
                abort(404, description=error.message)
            return render_import_error(import_id, f"Prüfentscheidung nicht gespeichert: {error.message}", 409 if error.code == ErrorCode.STALE_REVISION else 400)

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
            return render_import_error(import_id, f"Übernahme nicht ausgeführt: {message}", status)

    def all_accounts():
        items, cursor = [], None
        while True:
            page = workflow.store.list_accounts(cursor, 500)
            items.extend(page.items)
            cursor = page.next_cursor
            if cursor is None:
                return tuple(items)

    def render_accounts(*, edit_form=None, cash_form=None, depot_form=None, error=None, saved=None, status=200):
        accounts = all_accounts()
        exclude = edit_form.account_id if edit_form else None
        banks = sorted({account.institution for account in accounts if account.institution} | {"comdirect"}, key=str.casefold)
        return render_template(
            "accounts.html",
            rows=account_rows(accounts),
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
