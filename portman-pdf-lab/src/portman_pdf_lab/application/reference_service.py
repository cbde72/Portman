"""Application boundary joining analysis with durable local reference storage."""

from pathlib import Path

from portman_pdf_lab.storage import ReferenceRepository

from .pdf_analysis import analyse_pdf


def analyse_and_store(path: str | Path, repository: ReferenceRepository) -> tuple[dict, int | None]:
    report = analyse_pdf(path)
    if "result" not in report:
        return report, None
    detection = report["detection"]; result = report["result"]
    document_id = repository.register_document(
        report["document_id"], report["source_hash"], str(Path(path).resolve()),
        detection["plugin_id"], detection["document_type"])
    run_id = repository.save_run(
        document_id, detection["plugin_id"], detection["handler_id"],
        detection["plugin_version"], result["schema_version"], result,
        report.get("issues", []), report["timings"]["total_ns"])
    report["run_id"] = run_id
    report["reference_comparison"] = list(repository.reference_comparison(run_id))
    return report, run_id
