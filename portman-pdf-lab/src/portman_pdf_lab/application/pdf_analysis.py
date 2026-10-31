"""End-to-end PDF analysis with stage timings and resilient batch execution."""

from pathlib import Path
from time import perf_counter_ns
import csv
import hashlib

from portman_parsers.api import Issue, IssueNature, IssueSeverity, to_json_compatible
from portman_parsers.extraction import PdfExtractionError, extract_pdf
from portman_parsers.registry import default_registry
from portman_parsers.utilities import stable_id
from portman_parsers.validation import validate_parsed_document

from portman_pdf_lab.analysis.fee_views import fee_cost_view
from portman_pdf_lab.analysis.master_data_views import account_view, depot_account_link_view
from portman_pdf_lab.application.comdirect_comparison import compare_comdirect_parsers


def analyse_pdf(path: str | Path) -> dict[str, object]:
    source = Path(path)
    total_start = perf_counter_ns()
    timings = {}
    try:
        started = perf_counter_ns(); document = extract_pdf(source); timings["extraction_ns"] = perf_counter_ns() - started
        if any(page.extraction_method == "ocr_required" for page in document.pages):
            issue = Issue(stable_id("issue", document.document_id, "ocr"), "OCR_REQUIRED",
                          IssueSeverity.WARNING, "PDF has no usable text layer; OCR is required.",
                          nature=IssueNature.MISSING_INFORMATION)
            return {"source": str(source), "document_id": document.document_id,
                    "source_hash": document.source_hash, "issues": to_json_compatible((issue,)),
                    "timings": {**timings, "total_ns": perf_counter_ns() - total_start}}
        registry = default_registry()
        started = perf_counter_ns(); detection = registry.select(document); timings["detection_ns"] = perf_counter_ns() - started
        if detection is None:
            issue = Issue(stable_id("issue", document.document_id, "unsupported"),
                          "UNSUPPORTED_DOCUMENT", IssueSeverity.ERROR,
                          "No approved parser recognized this document.")
            return {"source": str(source), "document_id": document.document_id,
                    "source_hash": document.source_hash, "issues": to_json_compatible((issue,)),
                    "timings": {**timings, "total_ns": perf_counter_ns() - total_start}}
        started = perf_counter_ns(); result = registry.parse(document, detection); timings["parsing_ns"] = perf_counter_ns() - started
        started = perf_counter_ns(); issues = validate_parsed_document(result); timings["validation_ns"] = perf_counter_ns() - started
        started = perf_counter_ns()
        report = {"source": str(source), "document_id": document.document_id,
                  "source_hash": document.source_hash, "detection": to_json_compatible(detection),
                  "result": result.to_dict(), "issues": to_json_compatible(issues),
                  "account_view": account_view(result),
                  "depot_account_link_view": depot_account_link_view(result),
                  "fee_cost_view": fee_cost_view(result)}
        if detection.plugin_id in {"user.comdirect-ertraege", "comdirect.finanzreport", "portfolio-performance.comdirect"}:
            report["parser_comparison"] = to_json_compatible(compare_comdirect_parsers(document))
        timings["reporting_ns"] = perf_counter_ns() - started
        report["timings"] = {**timings, "total_ns": perf_counter_ns() - total_start}
        return report
    except (PdfExtractionError, OSError, ValueError) as exc:
        return {"source": str(source), "error": type(exc).__name__, "message": str(exc),
                "timings": {**timings, "total_ns": perf_counter_ns() - total_start}}


def analyse_directory(path: str | Path, progress=None, cancelled=None) -> dict[str, object]:
    root = Path(path)
    files = sorted(root.rglob("*.pdf"))
    results = []; seen = {}
    for index, item in enumerate(files, 1):
        if cancelled and cancelled():
            break
        digest = hashlib.sha256(item.read_bytes()).hexdigest()
        if digest in seen:
            result = {"source": str(item), "source_hash": digest, "duplicate_of": seen[digest], "skipped": True}
        else:
            seen[digest] = str(item); result = analyse_pdf(item)
        results.append(result)
        if progress:
            progress(index, len(files), item)
    return {"root": str(root), "files": results, "count": len(results),
            "discovered": len(files), "cancelled": len(results) < len(files)}


def export_batch_csv(report: dict[str, object], path: str | Path) -> Path:
    target = Path(path)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("source", "source_hash", "plugin_id", "handler_id", "status", "runtime_ns"))
        writer.writeheader()
        for item in report.get("files", []):
            detection = item.get("detection", {})
            writer.writerow({"source": item.get("source", ""), "source_hash": item.get("source_hash", ""),
                             "plugin_id": detection.get("plugin_id", ""), "handler_id": detection.get("handler_id", ""),
                             "status": "DUPLICATE" if item.get("duplicate_of") else "ERROR" if item.get("error") else "OK",
                             "runtime_ns": item.get("timings", {}).get("total_ns", "")})
    return target

