"""Terminalprüfung: echtes PDF in isolierter V10-Testablage nur vorschauen."""
import argparse
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from portman_v10.application.contracts import ApplicationError, DocumentUpload, ImportStart
from portman_v10.infrastructure.import_workflow import ImportWorkflow
from portman_v10.infrastructure.sqlite_store import SQLiteStore


def _run(pdf: Path, data_dir: Path) -> int:
    source = pdf.read_bytes()
    store = SQLiteStore(data_dir / "v10.sqlite")
    workflow = ImportWorkflow(store, data_dir)
    try:
        uploaded = workflow.upload_document(DocumentUpload(pdf.name, source))
        job = workflow.start_import(ImportStart((uploaded.document.document_id,)))
        result = workflow.wait(job.job_id, timeout=120)
        print(f"Job: {result.state} ({result.completed_documents}/{result.document_count} Dokumente, Fortschritt {result.progress}%)")
        for document in workflow.get_import_document_results(job.job_id):
            print(f"Beleg: {document.name} | Typ: {document.document_type or 'unbekannt'} | Paket/API: {document.parser_package_version or '—'}/{document.parser_api_version or '—'} | Plugin: {document.plugin_id or '—'} {document.plugin_version or ''} | Handler: {document.handler_id or '—'} | Schema: {document.parser_schema_version or '—'} | Ergebnis: {document.status}")
            if document.error_code:
                print(f"  Fehler: {document.error_code.value} — {'; '.join(document.warning_messages)}")
        try:
            preview = workflow.get_import_preview(job.import_id)
        except ApplicationError as error:
            preview = None
            print(f"Vorschau nicht verfügbar: {error.code.value} — {error.message}")
        if preview:
            for item in preview.items:
                print(f"Vorschlag: {item.suggested_kind or item.kind} | Review: {item.review_status} | Datum: {', '.join(f'{d.meaning}={d.value.isoformat() if d.value else 'unbekannt'}' for d in item.dates)}")
                for movement in item.movements:
                    value = movement.amount.text if movement.amount else "unbekannt"
                    references = dict(item.references)
                    unit = movement.currency or movement.instrument_id or movement.instrument_name or references.get("security_isin") or "Einheit offen"
                    account = movement.account_id or "Zuordnung offen"
                    print(f"  Wirkung {movement.movement_type}: {value} {unit} | Konto/Depot: {account} ({movement.account_assignment}) | Status: {movement.status or 'nicht angegeben'}")
                for component in item.components:
                    amount = component.amount.text if component.amount else "unbekannt"
                    print(f"  Detail {component.category}/{component.kind}: {amount} {component.currency or ''} ({component.effect}; keine zusätzliche Geld-/Mengenwirkung)")
                for warning in item.warnings:
                    print(f"  Hinweis {warning.severity}/{warning.code}: {warning.message}")
                for key, value in item.references:
                    print(f"  Referenz {key}: {value or 'unbekannt'}")
                for source in item.source_evidence:
                    print(f"  Quelle Seite {source.page_number or 'unbekannt'} / {source.field or 'Feld unbekannt'}: {source.excerpt or 'kein Exzerpt'}")
                for missing in item.missing_fields:
                    print(f"  Offen: {missing}")
        print("Keine Buchung übernommen; es wurden keine produktiven Geld- oder Mengenpositionen angelegt.")
        return 0 if result.state == "needs_review" else 2
    finally:
        workflow.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="V10-Importvorschau (schreibt keine Buchungen)")
    parser.add_argument("--pdf", required=True, type=Path, help="PDF-Datei; Original wird nur gelesen")
    parser.add_argument("--data-dir", type=Path, help="explizites V10-Testdatenverzeichnis; ohne Option wird ein isoliertes temporäres Verzeichnis verwendet")
    args = parser.parse_args()
    if not args.pdf.is_file():
        parser.error("PDF-Datei nicht gefunden")
    if args.data_dir:
        data_dir = args.data_dir.resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        return _run(args.pdf.resolve(), data_dir)
    with TemporaryDirectory(prefix="portman-v10-preview-") as temporary:
        return _run(args.pdf.resolve(), Path(temporary))


if __name__ == "__main__":
    raise SystemExit(main())
