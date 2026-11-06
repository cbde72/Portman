"""Serverseitige lokale Weboberfläche für den vorhandenen V10-Importworkflow."""
from io import BytesIO
import os
from pathlib import Path
import sqlite3
import subprocess
from urllib.parse import urlsplit

from flask import Flask, abort, redirect, render_template, request, send_file, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from portman_v10.application.contracts import ApplicationError, CommitImport, ConflictDecision, DocumentUpload, ErrorCode, ImportStart
from portman_v10.infrastructure.import_workflow import ImportWorkflow
from portman_v10.infrastructure.sqlite_store import SQLiteStore

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 64 * 1024
PACKAGE_ROOT = Path(__file__).resolve().parents[3]
STATUS_LABELS = {
    "queued": "Wartet",
    "running": "Wird verarbeitet",
    "needs_review": "Prüfung erforderlich",
    "completed": "Abgeschlossen",
    "failed": "Fehlgeschlagen",
    "cancelled": "Abgebrochen",
    "parsed": "Verarbeitet",
    "information": "Nur Information",
    "unsupported": "Nicht unterstützt",
    "duplicate_file": "Identischer Dateiinhalt",
}
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


def _instrument_label(workflow: ImportWorkflow, instrument_id: str | None, instrument_name: str | None) -> str:
    if instrument_id:
        try:
            instrument = workflow.store.get_instrument(instrument_id)
            return " — ".join(value for value in (instrument.name, instrument.isin or instrument.wkn) if value)
        except ApplicationError:
            return instrument_name or "Instrument nicht verfügbar"
    return instrument_name or "Unbekannt"


def _present_preview(workflow: ImportWorkflow, preview):
    presented = []
    for item in preview.items:
        movements = []
        for movement in item.movements:
            movements.append({
                "type": "Geldbewegung" if movement.movement_type == "cash" else "Mengenbewegung",
                "date": movement.date.isoformat() if movement.date else "Unbekannt",
                "account": _account_label(workflow, movement.account_id),
                "account_reference": movement.account_reference or "",
                "instrument": _instrument_label(workflow, movement.instrument_id, movement.instrument_name),
                "amount": movement.amount.text if movement.amount else "Unbekannt",
                "unit": movement.currency or ("Stück" if movement.movement_type == "quantity" else ""),
                "assignment": ASSIGNMENT_LABELS[movement.account_assignment],
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
        presented.append({
            "kind": item.suggested_kind or item.kind,
            "status": item.review_status,
            "related_event": next((value.related_event_id for value in item.conflicts if value.related_event_id), None),
            "movements": tuple(movements),
            "dates": dates,
            "components": components,
            "references": tuple((key, value or "Unbekannt") for key, value in item.references),
            "evidence": evidence,
            "warnings": warnings,
            "missing": item.missing_fields,
            "original_text": item.original_text or "",
        })
    return tuple(presented)


def _preview_summary(preview):
    cash = sum(1 for item in preview.items for movement in item.movements if movement.movement_type == "cash")
    quantity = sum(1 for item in preview.items for movement in item.movements if movement.movement_type == "quantity")
    unresolved = sum(1 for item in preview.items if item.missing_fields or item.conflicts or item.review_status != "complete_candidate")
    return {"events": len(preview.items), "cash": cash, "quantity": quantity, "unresolved": unresolved}


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
                if not is_referer and (parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
                    return False
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                return parsed.scheme.casefold(), parsed.hostname.rstrip(".").casefold(), port
            except ValueError:
                return False

        expected = parsed_origin(request.host_url)
        origin_header = request.headers.get("Origin")
        referer_header = request.headers.get("Referer")
        origin = parsed_origin(origin_header) if origin_header is not None else None
        referer = parsed_origin(referer_header, is_referer=True) if referer_header is not None else None
        # Native browser form POSTs normally send Origin. If it is omitted, a
        # same-origin Referer is an acceptable fallback; with neither header,
        # deny because the local browser context cannot be established.
        valid = expected is not False and origin is not False and referer is not False
        if origin_header is None and referer_header is None:
            valid = False
        if origin_header is not None:
            valid = valid and origin == expected
        if referer_header is not None:
            valid = valid and referer == expected
        if not valid:
            abort(403, description="Upload nur von der geöffneten lokalen V10-Seite erlaubt.")

    @app.errorhandler(RequestEntityTooLarge)
    def upload_too_large(_error):
        return render_template("index.html", error="Upload überschreitet die Grenze von 50 MiB.", branch=branch, commit=commit, profile=profile), 413

    @app.get("/health")
    def health():
        return "ok", 200, {"Content-Type": "text/plain; charset=utf-8"}

    @app.get("/")
    def index():
        return render_template("index.html", branch=branch, commit=commit, profile=profile)

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
            has_preview=preview is not None,
            preview_revision=preview.revision if preview else 0,
            summary=_preview_summary(preview) if preview else {"events": 0, "cash": 0, "quantity": 0, "unresolved": 0},
            commit_report=commit_report,
            status_labels=STATUS_LABELS,
            branch=branch,
            commit=commit,
            profile=profile,
        )

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
            abort(409 if error.code == ErrorCode.STALE_REVISION else 400, description=error.message)

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
            abort(409 if isinstance(error, ApplicationError) and error.code in {ErrorCode.STALE_REVISION, ErrorCode.POSSIBLE_DUPLICATE, ErrorCode.SOURCE_CONFLICT} else 400,
                  description=error.message if isinstance(error, ApplicationError) else "Ungültige Übernahmeanfrage")

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
    app = create_app(workflow, branch=branch, commit=commit, profile="isoliertes Web-Testprofil · data/web-test")
    try:
        app.run(host="127.0.0.1", port=int(os.environ.get("PORTMAN_V10_WEB_PORT", "8765")), debug=False, use_reloader=False, threaded=True)
    finally:
        workflow.close()


if __name__ == "__main__":
    main()
