"""Read-only, resumable PDF Lab audit V3 on top of ``analyse_pdf`` and portman-parsers.

Every PDF is analysed in its own child process.  The audit never opens
ReferenceRepository, never calls ``analyse_and_store`` and writes only below
``--output``.  Training data is read through the read-only TrainingExportReader.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


def configure_worker() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="strict")
            except (OSError, ValueError):
                pass

TOOL_PATH = Path(__file__).resolve()
PDF_LAB_ROOT = TOOL_PATH.parents[1]
REPO_ROOT = PDF_LAB_ROOT.parent
PARSERS_ROOT = REPO_ROOT / "portman-parsers"
for import_root in (PDF_LAB_ROOT / "src", PARSERS_ROOT / "src"):
    if import_root.is_dir() and str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

SCHEMA_VERSION = 1
AUDIT_TOOL = "portman-pdf-lab/tools/pdf_audit_v3.py"
DEFAULT_CATALOG = REPO_ROOT / "data" / "Portman_PDF_Lab_Feldkatalog_v1.0.0.yaml"
RULE_MODES = ("STANDARD", "EXTENDED")
REUSABLE_STATUSES = frozenset({"PARSED", "UNSUPPORTED", "OCR_REQUIRED"})
FAILURE_STATUSES = frozenset({"ERROR", "TIMEOUT", "WORKER_CRASH", "AMBIGUOUS"})
SEVERITY_RANK = {"PASS": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "TIMEOUT": 4}
ISSUE_LEVEL = {"INFO": "INFO", "WARNING": "WARNING", "ERROR": "ERROR", "CRITICAL": "ERROR"}
MISSING_MARKERS = frozenset({"", "UNKNOWN", "NOT_FOUND", "MISSING"})
MAX_WORKERS = 4
PROGRESS_EVERY = 10
LOG_TAIL_BYTES = 2000
LOG_LIMIT_BYTES = 64 * 1024
IBAN_PATTERN = re.compile(r"\bDE(?:[\s-]*\d){20}\b", re.I)

EVENT_SCALARS = ("event_id", "kind", "event_date", "reversal_of_event_id", "security_name",
                 "security_isin", "security_wkn", "bank_reference", "bank_reference_status")
EVENT_CHILDREN = {
    "cash_movements": ("movement_id", "movement_type", "amount", "currency", "status", "account_ref"),
    "security_movements": ("movement_id", "security_id", "quantity"),
    "trades": ("trade_id", "side", "security_name", "isin", "wkn", "quantity", "trade_date", "execution_date",
               "value_date", "price", "price_currency", "market_value", "gross_amount", "settlement_amount",
               "settlement_currency"),
    "fee_events": ("fee_id", "category", "subcategory", "amount", "currency", "effect", "fee_date"),
    "tax_events": ("tax_event_id", "kind", "tax_year", "taxable_basis", "assessment_basis", "taxable_amount",
                   "stated_tax_liability", "actually_withheld_tax", "booking_date", "value_date", "currency", "isin"),
    "cost_events": ("cost_event_id", "kind", "amount", "currency", "information_type", "informational"),
}
TRANSACTION_JSON = ("cash_movements", "security_movements", "trades", "fee_events", "tax_events", "cost_events")


def _plugin_groups() -> dict[str, str]:
    from portman_parsers.registry.allowlist import APPROVED_PLUGINS
    return {item.plugin_id: item.group for item in APPROVED_PLUGINS}


PLUGIN_GROUPS = _plugin_groups()


class BaselineError(ValueError):
    pass


class Config:
    __slots__ = ("root", "output", "timeout", "rule_mode", "plugin_id", "profile_dir", "allow_ocr",
                 "training_database", "catalog", "description_store", "baseline", "fingerprint")

    def __init__(self, root: Path, output: Path, timeout: float, rule_mode: str, plugin_id: str | None,
                 profile_dir: Path, allow_ocr: bool, training_database: Path | None, catalog: Path,
                 description_store: Path | None, baseline: dict | None, fingerprint: str):
        self.root = root
        self.output = output
        self.timeout = timeout
        self.rule_mode = rule_mode
        self.plugin_id = plugin_id
        self.profile_dir = profile_dir
        self.allow_ocr = allow_ocr
        self.training_database = training_database
        self.catalog = catalog
        self.description_store = description_store
        self.baseline = baseline
        self.fingerprint = fingerprint


def scrub(value) -> str:
    return IBAN_PATTERN.sub("[IBAN]", str(value))[:4000]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def discover_pdfs(root: Path) -> tuple[list[tuple[str, Path]], list[str]]:
    errors: list[str] = []
    found = []
    for folder, _, names in os.walk(root, followlinks=False, onerror=lambda error: errors.append(scrub(error))):
        for name in names:
            if name.lower().endswith(".pdf"):
                path = Path(folder) / name
                found.append((path.relative_to(root).as_posix(), path))
    return sorted(found, key=lambda item: (item[0].casefold(), item[0])), errors


def elapsed(started: float) -> float:
    return round(time.perf_counter() - started, 3)


def exit_code_text(code: int) -> str:
    if code < 0:
        return f"Signal {-code}"
    return f"0x{code & 0xFFFFFFFF:08X}" if code > 0xFFFF else str(code)


class NoProfiles:
    """Read-only stand-in: without an existing profile directory nothing is active."""

    def active(self, *_args, **_kwargs):
        return None


def profile_store(directory: Path):
    from portman_parsers.rules import ProfileStore
    return ProfileStore(directory) if directory.is_dir() else NoProfiles()


def compact_report(report: dict) -> dict:
    """Keep evidence ids and values, drop text excerpts and page bodies (privacy and size)."""
    preparation = dict(report.get("text_preparation") or {})
    preparation["pages"] = len(preparation.get("pages") or [])
    report["text_preparation"] = preparation
    result = report.get("result")
    if isinstance(result, dict):
        report["result"] = {**result, "evidence": [{key: value for key, value in item.items() if key != "excerpt"}
                                                  for item in result.get("evidence") or []]}
    return report


def worker_main(args, profile_dir: Path) -> int:
    """Child process: one PDF, one JSON result file, no stdout protocol."""
    from portman_pdf_lab.application.pdf_analysis import analyse_pdf
    try:
        report = analyse_pdf(args.worker, rule_mode=args.rule_mode,
                             profile_store=profile_store(profile_dir), plugin_id=args.plugin_id)
    except Exception as error:
        report = {"error": type(error).__name__, "message": scrub(error), "exception": True,
                  "traceback": scrub(traceback.format_exc(limit=6))}
    report = compact_report(report)
    report["source"] = args.relative
    args.result_file.write_text(json.dumps(report, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


def _bounded_drain(stream, sink: list[bytes]) -> None:
    """Read child output but keep at most LOG_LIMIT_BYTES in memory."""
    total = 0
    try:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                break
            if total < LOG_LIMIT_BYTES:
                sink.append(chunk[:LOG_LIMIT_BYTES - total])
            total += len(chunk)
    except (OSError, ValueError):
        pass


def _log_text(chunks: list[bytes]) -> str:
    if not chunks:
        return ""
    data = b"".join(chunks)[-LOG_TAIL_BYTES:]
    return scrub(data.decode("utf-8", "replace"))


def run_child(rel: str, path: Path, config: Config, work_dir: Path) -> dict:
    slug = hashlib.sha256(rel.encode("utf-8")).hexdigest()[:24]
    result_file = work_dir / f"{slug}.json"
    command = [sys.executable, "-X", "utf8", str(TOOL_PATH), "--worker", str(path), "--relative", rel,
               "--result-file", str(result_file), "--rule-mode", config.rule_mode,
               "--profile-dir", str(config.profile_dir)]
    if config.plugin_id:
        command += ["--plugin-id", config.plugin_id]
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    started = time.perf_counter()
    chunks: list[bytes] = []
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               env=env, cwd=str(PDF_LAB_ROOT))
    reader = threading.Thread(target=_bounded_drain, args=(process.stdout, chunks), daemon=True)
    reader.start()
    timed_out = False
    try:
        returncode = process.wait(timeout=config.timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        try:
            returncode = process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            returncode = -9
    finally:
        reader.join(timeout=5)
        try:
            process.stdout.close()
        except OSError:
            pass
    duration = elapsed(started)
    tail = _log_text(chunks)
    if timed_out:
        message = f"Zeitlimit von {config.timeout:g} Sekunden überschritten: {rel}"
        if tail:
            message = f"{message}\n{tail}"
        return {"outcome": "TIMEOUT", "message": message, "duration_s": duration}
    if returncode != 0 or not result_file.is_file():
        message = f"Kindprozess ohne Ergebnis (Exit-Code {exit_code_text(returncode)}): {rel}"
        if tail:
            message = f"{message}\n{tail}"
        return {"outcome": "WORKER_CRASH", "message": message, "exit_code": exit_code_text(returncode),
                "log_tail": tail, "duration_s": duration}
    try:
        report = json.loads(result_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return {"outcome": "WORKER_CRASH",
                "message": scrub(f"Ungültige Worker-Ausgabe ({type(error).__name__}): {rel}\n{tail}"),
                "exit_code": "0", "duration_s": duration}
    finally:
        try:
            result_file.unlink(missing_ok=True)
        except OSError:
            pass
    return {"outcome": "COMPLETED", "report": report, "exit_code": "0", "duration_s": duration}


def safe_run_child(rel: str, path: Path, config: Config, work_dir: Path) -> dict:
    try:
        return run_child(rel, path, config, work_dir)
    except Exception as error:
        return {"outcome": "WORKER_CRASH", "message": scrub(f"{type(error).__name__}: {error} ({rel})"), "duration_s": 0.0}


def plain(node):
    """Unwrap FieldValue transport wrappers and drop missing placeholders."""
    if isinstance(node, dict) and "value" in node:
        node = node["value"]
    if node is None or (isinstance(node, str) and node.strip().upper() in MISSING_MARKERS):
        return None
    return node


def picked(item: dict, keys) -> dict:
    values = {key: plain(item.get(key)) for key in keys}
    return {key: value for key, value in values.items() if value is not None}


def compact_event(event: dict) -> dict:
    compact = picked(event, EVENT_SCALARS)
    for name, keys in EVENT_CHILDREN.items():
        items = []
        for child in event.get(name) or []:
            item = picked(child, keys)
            if name == "tax_events" and child.get("components"):
                item["components"] = [picked(component, ("kind", "amount", "currency"))
                                      for component in child["components"]]
            items.append(item)
        if items:
            compact[name] = items
    return compact


def finding(code: str, level: str, message: str, **extra) -> dict:
    return {"code": code, "level": level, "message": scrub(message), **extra}


def classify(rel: str, sha: str, size, run: dict) -> dict:
    """Map one child run to a single audit row; shared by fresh, resumed and duplicate rows."""
    from portman_pdf_lab.application.batch_csv import flatten_evidence_values
    outcome = run["outcome"]
    report = dict(run.get("report") or {})
    result = report.get("result") if isinstance(report.get("result"), dict) else {}
    detection = report.get("detection") if isinstance(report.get("detection"), dict) else {}
    issues = list(report.get("issues") or [])
    findings = [finding(item["code"], ISSUE_LEVEL.get(item["severity"], "WARNING"), item["message"],
                        nature=item.get("nature") or "", event_id=item.get("event_id") or "",
                        evidence_id=item.get("evidence_id") or "") for item in issues]
    error_text = ""
    if outcome == "DUPLICATE":
        status = "DUPLICATE"
        findings.append(finding("DUPLICATE_SHA256", "INFO",
                                f"Identischer Inhalt wie {run['duplicate_of']}; nicht erneut analysiert"))
    elif outcome in {"TIMEOUT", "WORKER_CRASH", "FILE_ERROR"}:
        status = "ERROR" if outcome == "FILE_ERROR" else outcome
        error_text = scrub(run["message"])
        findings.append(finding(outcome, "TIMEOUT" if outcome == "TIMEOUT" else "ERROR", error_text))
    elif report.get("error"):
        name = str(report["error"])
        status = "AMBIGUOUS" if name == "AmbiguousDetectionError" else "ERROR"
        code = ("AMBIGUOUS_PARSER" if status == "AMBIGUOUS"
                else "PARSER_EXCEPTION" if report.get("exception") else "ANALYSIS_ERROR")
        error_text = scrub(f"{name}: {report.get('message', '')}")
        findings.append(finding(code, "ERROR", error_text))
    else:
        codes = {item["code"] for item in issues}
        status = ("UNSUPPORTED" if "UNSUPPORTED_DOCUMENT" in codes
                  else "OCR_REQUIRED" if "OCR_REQUIRED" in codes else "PARSED")
    values = flatten_evidence_values(result) if result else {}
    if status == "PARSED" and not values:
        findings.append(finding("NO_BUSINESS_VALUES", "WARNING",
                                "Parser lief, aber keine durch PDF-Fundstellen belegten fachlichen Werte erkannt"))
    severity = max((item["level"] for item in findings), key=SEVERITY_RANK.get, default="PASS")
    events = [compact_event(item) for item in result.get("events") or []]
    plugin = str(detection.get("plugin_id") or "")
    duration = run.get("duration_s")
    if outcome == "DUPLICATE":
        analysis = {"source": rel, "source_hash": sha, "duplicate_of": run["duplicate_of"]}
    elif error_text and not report:
        analysis = {"source": rel, "source_hash": sha, "error": status, "message": error_text,
                    "timings": {"total_ns": int((duration or 0) * 1e9)}}
    else:
        analysis = {**report, "source": rel, "source_hash": sha}
    return {
        "path": rel, "sha256": sha, "bytes": size, "duplicate_of": run.get("duplicate_of", ""),
        "status": status, "severity": severity, "plugin": plugin,
        "handler": str(detection.get("handler_id") or ""), "document_type": str(detection.get("document_type") or ""),
        "bank": PLUGIN_GROUPS.get(plugin, "") if plugin else "", "confidence": detection.get("confidence", ""),
        "transactions": events, "tax_events": sum(len(item.get("tax_events") or []) for item in events),
        # V09 ``snapshots`` are depot statements; PDF Lab models them as
        # ``depot_snapshots``.  The legacy ``snapshots`` DTO is still counted.
        "snapshots": len(result.get("depot_snapshots") or []) + len(result.get("snapshots") or []),
        "depot_snapshots": len(result.get("depot_snapshots") or []),
        "field_values": values, "issue_codes": sorted({item["code"] for item in findings
                                                       if item["level"] in {"WARNING", "ERROR", "TIMEOUT"}}),
        "findings": findings, "ocr_indications": sum(item["code"] == "OCR_REQUIRED" for item in findings),
        "duration_s": duration, "exit_code": run.get("exit_code", ""), "error": error_text,
        "analysis": analysis,
    }


def transaction_row(rel: str, sha: str, event: dict) -> dict:
    cash = event.get("cash_movements") or []
    amounts = [item for item in cash if item.get("amount") is not None]
    single = amounts[0] if len(amounts) == 1 else {}
    trades = event.get("trades") or []
    securities = event.get("security_movements") or []
    trade = trades[0] if trades else {}
    security = securities[0] if securities else {}
    return {
        "path": rel, "sha256": sha, "event_id": event.get("event_id", ""), "kind": event.get("kind", ""),
        "event_date": event.get("event_date", ""), "reversal_of_event_id": event.get("reversal_of_event_id", ""),
        "amount": single.get("amount", ""), "currency": single.get("currency", ""),
        "cash_status": single.get("status", ""), "side": trade.get("side", ""),
        "security": event.get("security_name") or trade.get("security_name", ""),
        "isin": event.get("security_isin") or trade.get("isin", ""),
        "wkn": event.get("security_wkn") or trade.get("wkn", ""),
        "quantity": trade.get("quantity", security.get("quantity", "")),
        "gross_amount": trade.get("gross_amount", ""),
        "fee_count": len(event.get("fee_events") or []), "tax_count": len(event.get("tax_events") or []),
        "cost_count": len(event.get("cost_events") or []),
        **{name: event.get(name) or [] for name in TRANSACTION_JSON},
    }


def ratio(part: int, whole: int):
    return round(part / whole, 4) if whole else None


def quality(rows: list[dict]) -> dict:
    unique = [row for row in rows if row["status"] != "DUPLICATE"]
    parsed = [row for row in unique if row["status"] == "PARSED"]
    detected = [row for row in unique if row["plugin"]]
    events = [(row, event) for row in parsed for event in row["transactions"]]
    trades = [trade for _, event in events for trade in event.get("trades", [])]
    security_events = [event for _, event in events
                       if event.get("trades") or event.get("security_movements")
                       or event.get("security_name") or event.get("security_isin")]
    durations = [row["duration_s"] for row in unique if isinstance(row.get("duration_s"), (int, float))]
    counts = Counter(row["status"] for row in rows)
    field_total = sum(len(row["field_values"]) for row in parsed)
    return {
        "physical": len(rows), "unique": len(unique), "duplicates": len(rows) - len(unique),
        "detected": len(detected), "detection_rate": ratio(len(detected), len(unique)),
        "parsed": len(parsed), "technical_success_rate": ratio(len(parsed), len(unique)),
        "status": dict(sorted(counts.items())),
        "unsupported": counts["UNSUPPORTED"], "ocr_required": counts["OCR_REQUIRED"],
        "ambiguous": counts["AMBIGUOUS"], "errors": counts["ERROR"],
        "timeouts": counts["TIMEOUT"], "crashes": counts["WORKER_CRASH"],
        "parsed_without_fields": sum(1 for row in parsed if not row["field_values"]),
        "field_values": field_total, "field_values_per_parsed": ratio(field_total, len(parsed)),
        "events": len(events), "trades": len(trades),
        "security_events_without_isin_wkn": sum(
            1 for event in security_events if not event.get("security_isin") and not event.get("security_wkn")
            and not any(item.get("isin") or item.get("wkn") for item in event.get("trades", []))),
        "trades_without_isin_wkn": sum(1 for trade in trades if not trade.get("isin") and not trade.get("wkn")),
        "trades_without_quantity": sum(1 for trade in trades
                                       if trade.get("side") in {"BUY", "SELL"} and trade.get("quantity") is None),
        "events_without_cash_amount": sum(1 for _, event in events
                                          if not any(item.get("amount") is not None
                                                     for item in event.get("cash_movements", []))),
        "events_without_date": sum(1 for _, event in events if not event.get("event_date")),
        "trades_without_trade_date": sum(1 for trade in trades if not trade.get("trade_date")),
        "tax_events": sum(row["tax_events"] for row in parsed),
        "documents_with_tax_events": sum(1 for row in parsed if row["tax_events"]),
        "fee_events": sum(len(event.get("fee_events", [])) for _, event in events),
        "documents_with_fee_events": sum(1 for row in parsed
                                         if any(event.get("fee_events") for event in row["transactions"])),
        "runtime": {"avg_s": round(sum(durations) / len(durations), 3) if durations else None,
                    "max_s": max(durations) if durations else None,
                    "sum_s": round(sum(durations), 3)},
    }


def group_stats(rows: list[dict], key) -> dict:
    groups = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    stats = {}
    for name in sorted(groups):
        items = groups[name]
        unique = [row for row in items if row["status"] != "DUPLICATE"]
        parsed = [row for row in unique if row["status"] == "PARSED"]
        durations = [row["duration_s"] for row in unique if isinstance(row.get("duration_s"), (int, float))]
        stats[name] = {
            "physical": len(items), "unique": len(unique), "parsed": len(parsed),
            "unsupported": sum(row["status"] == "UNSUPPORTED" for row in items),
            "ambiguous": sum(row["status"] == "AMBIGUOUS" for row in items),
            "errors": sum(row["status"] == "ERROR" for row in items),
            "timeouts": sum(row["status"] == "TIMEOUT" for row in items),
            "crashes": sum(row["status"] == "WORKER_CRASH" for row in items),
            "without_fields": sum(1 for row in parsed if not row["field_values"]),
            "field_values": sum(len(row["field_values"]) for row in parsed),
            "events": sum(len(row["transactions"]) for row in parsed),
            "tax_events": sum(row["tax_events"] for row in parsed),
            "avg_s": round(sum(durations) / len(durations), 3) if durations else None,
        }
    return stats


def economic_signature(row: dict) -> str:
    payload = json.dumps(row.get("transactions") or [], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compare(rows: list[dict], baseline: dict | None, config: Config) -> dict:
    if baseline is None:
        return {"baseline_used": False, "compared": 0, "changed": [], "regressions": [], "improved": [],
                "new_paths": [], "removed_paths": []}
    old_rows = baseline.get("files") or []
    by_path = {row["path"]: row for row in old_rows}
    by_sha: dict[str, dict] = {}
    for row in old_rows:
        by_sha.setdefault(row.get("sha256"), row)
    configuration = {"rule_mode": baseline.get("rule_mode") == config.rule_mode,
                     "plugin_id": (baseline.get("plugin_id") or "") == (config.plugin_id or ""),
                     "parser_fingerprint": baseline.get("parser_fingerprint") == config.fingerprint}
    changed, regressions, improved = [], [], []
    compared = 0
    for row in rows:
        if row["path"] in by_path:
            old, matched = by_path[row["path"]], "path"
        else:
            old, matched = by_sha.get(row["sha256"]), "sha256"
        if old is None:
            continue
        compared += 1
        before = {"status": old.get("status"), "severity": old.get("severity"), "plugin": old.get("plugin"),
                  "handler": old.get("handler"), "document_type": old.get("document_type"),
                  "events": len(old.get("transactions") or []), "tax_events": old.get("tax_events", 0),
                  "transactions_signature": economic_signature(old)}
        after = {"status": row["status"], "severity": row["severity"], "plugin": row["plugin"],
                 "handler": row["handler"], "document_type": row["document_type"],
                 "events": len(row["transactions"]), "tax_events": row["tax_events"],
                 "transactions_signature": economic_signature(row)}
        fields = {key: {"before": before[key], "after": after[key]} for key in before if before[key] != after[key]}
        old_values, new_values = old.get("field_values") or {}, row["field_values"]
        values = {"added": sorted(set(new_values) - set(old_values)),
                  "removed": sorted(set(old_values) - set(new_values)),
                  "changed": {key: {"before": old_values[key], "after": new_values[key]}
                              for key in sorted(set(old_values) & set(new_values))
                              if old_values[key] != new_values[key]}}
        old_codes, new_codes = set(old.get("issue_codes") or []), set(row["issue_codes"])
        entry = {"path": row["path"], "sha256": row["sha256"], "matched_by": matched, "fields": fields,
                 "field_values": values, "new_issue_codes": sorted(new_codes - old_codes),
                 "resolved_issue_codes": sorted(old_codes - new_codes)}
        if not (fields or values["added"] or values["removed"] or values["changed"]
                or entry["new_issue_codes"] or entry["resolved_issue_codes"]):
            continue
        changed.append(entry)
        worse = (SEVERITY_RANK.get(row["severity"], 0) > SEVERITY_RANK.get(old.get("severity"), 0)
                 or (old.get("status") == "PARSED" and row["status"] != "PARSED")
                 or bool(values["removed"]) or bool(old.get("plugin") and old.get("plugin") != row["plugin"]))
        if worse:
            regressions.append(entry)
        elif SEVERITY_RANK.get(row["severity"], 0) < SEVERITY_RANK.get(old.get("severity"), 0):
            improved.append(entry)
    current = {row["path"] for row in rows}
    return {"baseline_used": True, "baseline_schema": baseline.get("schema_version"),
            "configuration": configuration, "comparable_configuration": all(configuration.values()),
            "compared": compared, "changed": changed, "regressions": regressions, "improved": improved,
            "new_paths": sorted(current - set(by_path)), "removed_paths": sorted(set(by_path) - current)}


def load_baseline(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("audit_tool") != AUDIT_TOOL or data.get("schema_version") != SCHEMA_VERSION:
        raise BaselineError("Baseline ist kein PDF-Lab-Audit V3 (audit_tool/schema_version passen nicht). "
                            "V09-Audits werden nicht als PDF-Lab-Baseline interpretiert.")
    return data


def parser_fingerprint(rule_mode: str, plugin_id: str | None, profile_dir: Path) -> str:
    digest = hashlib.sha256()
    digest.update(f"schema={SCHEMA_VERSION}|python={sys.version}|rule={rule_mode}|plugin={plugin_id or ''}".encode())
    sources = [*(PARSERS_ROOT / "src").rglob("*.py"), *(PARSERS_ROOT / "src").rglob("*.yaml"),
               *(PARSERS_ROOT / "src").rglob("*.json"),
               *(PDF_LAB_ROOT / "src" / "portman_pdf_lab" / "application").rglob("*.py"),
               *(PDF_LAB_ROOT / "src" / "portman_pdf_lab" / "analysis").rglob("*.py"), TOOL_PATH]
    normalized = []
    for path in sources:
        if isinstance(path, str):
            path = Path(path)
        normalized.append(path)
    for path in sorted(set(normalized), key=lambda item: item.as_posix()):
        try:
            digest.update(path.relative_to(REPO_ROOT).as_posix().encode())
        except ValueError:
            digest.update(path.as_posix().encode())
        try:
            digest.update(sha256_file(path).encode())
        except OSError:
            try:
                digest.update(str(path.stat().st_mtime_ns).encode())
            except OSError:
                pass
    activations = profile_dir / "activations.json"
    digest.update(sha256_file(activations).encode() if activations.is_file() else b"no-activations")
    return digest.hexdigest()


def load_resume(output: Path, config: Config) -> dict[str, dict]:
    path = output / "progress.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if (data.get("audit_tool") != AUDIT_TOOL or data.get("scan_root") != str(config.root)
            or data.get("parser_fingerprint") != config.fingerprint or data.get("rule_mode") != config.rule_mode
            or (data.get("plugin_id") or "") != (config.plugin_id or "") or data.get("allow_ocr") != config.allow_ocr):
        return {}
    return {row["path"]: row for row in data.get("files", []) if row.get("status") in REUSABLE_STATUSES}


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def save_progress(output: Path, config: Config, rows: list[dict]) -> None:
    progress = {"schema_version": SCHEMA_VERSION, "audit_tool": AUDIT_TOOL, "scan_root": str(config.root),
                "parser_fingerprint": config.fingerprint, "rule_mode": config.rule_mode,
                "plugin_id": config.plugin_id or "", "allow_ocr": config.allow_ocr, "files": rows}
    write_atomic(output / "progress.json", json.dumps(progress, ensure_ascii=False, default=str))


def prepare_catalog(config: Config):
    """Build an in-memory description view below --output; the source catalog is only read."""
    from portman_pdf_lab.field_catalog import FieldCatalog
    from portman_pdf_lab.field_catalog_adapter import import_factual_catalog
    store_dir = config.output / "description-store"
    store_dir.mkdir(parents=True, exist_ok=True)
    destination = store_dir / "field-descriptions.v1.json"
    if config.description_store and config.description_store.is_file():
        shutil.copyfile(config.description_store, destination)
    mapping = None
    if config.catalog and config.catalog.is_file():
        mapping = import_factual_catalog(config.catalog, destination, config.output / "field-catalog-mapping.json")
    catalog = FieldCatalog("", "", "", "*", 1, (), store_dir / "catalog.yaml")
    return catalog, mapping


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), text=True,
                                       encoding="utf-8", stderr=subprocess.DEVNULL, timeout=20).strip()
    except (OSError, subprocess.SubprocessError):
        return "unbekannt"


def table(headers: list[str], rows: list[list]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---:" if index else "---" for index in range(len(headers))) + "|"]
    lines += ["| " + " | ".join("" if value is None else str(value) for value in row) + " |" for row in rows]
    return lines


def render_report(result: dict) -> str:
    q, comparison = result["quality"], result["comparison"]
    lines = ["# Portman PDF Lab – PDF-Audit V3", "",
             f"- Zeitpunkt (UTC): `{result['generated_at_utc']}`",
             f"- Root: `{result['scan_root']}`",
             f"- Commit: `{result['git_commit']}`",
             f"- Regelmodus: `{result['rule_mode']}`; Plugin-Erzwingung: `{result['plugin_id'] or 'automatisch'}`",
             f"- Timeout: `{result['timeout_s']} s`; wiederverwendet (Resume): **{result['summary']['resumed']}**",
             f"- OCR-Flag: `{result['allow_ocr']}` – ohne Wirkung, PDF Lab führt kein OCR aus (OCR_REQUIRED wird als Befund gemeldet)",
             f"- Trainingsdaten: {result['training_database']['path'] or 'nicht angegeben'}"
             + (f" – {'; '.join(result['training_database']['warnings'])}" if result['training_database']['warnings'] else ""),
             "", "## Kennzahlen", "",
             *table(["Kennzahl", "Wert"], [
                 ["PDFs physisch", q["physical"]], ["PDFs eindeutig (SHA-256)", q["unique"]],
                 ["Duplikate", q["duplicates"]],
                 ["Parsererkennungsquote", q["detection_rate"]],
                 ["Erfolgreiche Parsing-Läufe (PARSED)", q["parsed"]],
                 ["Technische Erfolgsquote (PARSED / eindeutig)", q["technical_success_rate"]],
                 ["Nicht unterstützt", q["unsupported"]], ["Mehrdeutige Parserzuordnung", q["ambiguous"]],
                 ["OCR erforderlich", q["ocr_required"]], ["Parserfehler", q["errors"]],
                 ["Timeouts", q["timeouts"]], ["Native Abstürze (Kindprozess)", q["crashes"]],
                 ["PDFs ohne erkannte fachliche Werte", q["parsed_without_fields"]],
                 ["Erkannte fachliche Felder gesamt", q["field_values"]],
                 ["Laufzeit Ø / max (s)", f"{q['runtime']['avg_s']} / {q['runtime']['max_s']}"]]),
             "", "## Fachliche Vollständigkeit (Hinweise, keine Feldgenauigkeit)", "",
             "Diese Zahlen sind Vollständigkeitsindikatoren. Ohne bestätigte Referenzwerte wird keine Erkennungsgenauigkeit behauptet.", "",
             *table(["Prüfung", "Anzahl"], [
                 ["Wertpapier-Ereignisse ohne ISIN/WKN", q["security_events_without_isin_wkn"]],
                 ["Wertpapiergeschäfte ohne ISIN/WKN", q["trades_without_isin_wkn"]],
                 ["Kauf/Verkauf ohne Stückzahl", q["trades_without_quantity"]],
                 ["Ereignisse ohne Geldbetrag (Steuer-/Infodokumente bewusst eingeschlossen)", q["events_without_cash_amount"]],
                 ["Ereignisse ohne Buchungsdatum", q["events_without_date"]],
                 ["Wertpapiergeschäfte ohne Handelsdatum", q["trades_without_trade_date"]],
                 ["Dokumente mit Steuerereignissen", q["documents_with_tax_events"]],
                 ["Steuerereignisse gesamt", q["tax_events"]],
                 ["Gebührenpositionen gesamt", q["fee_events"]]]),
             "", "## Banken", "",
             *table(["Bank", "PDFs", "Eindeutig", "Geparst", "Nicht unterst.", "Mehrdeutig", "Fehler", "Timeouts",
                     "Abstürze", "Ohne Felder", "Felder", "Ereignisse", "Steuerereign.", "Ø s"],
                    [[name, s["physical"], s["unique"], s["parsed"], s["unsupported"], s["ambiguous"], s["errors"],
                      s["timeouts"], s["crashes"], s["without_fields"], s["field_values"], s["events"],
                      s["tax_events"], s["avg_s"]] for name, s in result["banks"].items()]),
             "", "## Parser", "",
             *table(["Parser", "PDFs", "Eindeutig", "Geparst", "Nicht unterst.", "Mehrdeutig", "Fehler", "Timeouts",
                     "Abstürze", "Ohne Felder", "Felder", "Ereignisse", "Steuerereign.", "Ø s"],
                    [[name, s["physical"], s["unique"], s["parsed"], s["unsupported"], s["ambiguous"], s["errors"],
                      s["timeouts"], s["crashes"], s["without_fields"], s["field_values"], s["events"],
                      s["tax_events"], s["avg_s"]] for name, s in result["parsers"].items()]),
             "", "## Dokumenttypen", "",
             *table(["Dokumenttyp", "PDFs", "Eindeutig", "Geparst", "Felder"],
                    [[name, s["physical"], s["unique"], s["parsed"], s["field_values"]]
                     for name, s in result["document_types"].items()]),
             "", "## Issue-Codes", "", *table(["Code", "PDFs"], [
                 [f"`{code}`", count] for code, count in sorted(result["issue_codes"].items(), key=lambda x: (-x[1], x[0]))]),
             "", "## Vergleich mit Baseline", ""]
    if comparison["baseline_used"]:
        lines += [f"- Vergleichbare Konfiguration: **{comparison['comparable_configuration']}** ({comparison['configuration']})",
                  f"- Verglichene Dateien: **{comparison['compared']}**; veränderte: **{len(comparison['changed'])}**; "
                  f"Verschlechterungen: **{len(comparison['regressions'])}**; Verbesserungen: **{len(comparison['improved'])}**",
                  f"- Neue Pfade: **{len(comparison['new_paths'])}**; entfallene Pfade: **{len(comparison['removed_paths'])}**"]
    else:
        lines.append("Keine Baseline angegeben.")
    lines += ["", "## Methodik und Grenzen", "",
              "- Rein lesend: Es wird ausschließlich `analyse_pdf()` aufgerufen; keine SQLite-Datenbank wird verändert.",
              "- Jede PDF läuft in einem isolierten Kindprozess mit Zeitlimit; Hänger werden beendet.",
              "- Resume gilt nur bei identischem Root, Regelmodus, Plugin-Erzwingung und Parser-Fingerprint.",
              "- Technische Erfolgsquote und fachliche Vollständigkeit sind getrennt ausgewiesen.",
              "- Vergleichbarkeit zum V09-Audit: siehe `docs/audits/PORTMAN_PDF_LAB_AUDIT_V3_RESULT.md`.", "",
              "## Befehle", "", "```powershell",
              ".\\.venv\\Scripts\\python.exe -X utf8 .\\portman-pdf-lab\\tools\\pdf_audit_v3.py --root \"C:\\Users\\chris\\Desktop\\history\" --output \".\\test_reports\\pdf_lab_audit_v3\" --timeout 120 --no-cache",
              ".\\.venv\\Scripts\\python.exe -X utf8 .\\portman-pdf-lab\\tools\\pdf_audit_v3.py --root \"C:\\Users\\chris\\Desktop\\history\" --output \".\\test_reports\\pdf_lab_audit_v3\" --timeout 120 --resume",
              "```", ""]
    return "\n".join(lines)


def write_csv(path: Path, rows, fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fields, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
                             for key, value in row.items()})


def write_outputs(output: Path, result: dict) -> None:
    files = result["files"]
    (output / "audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (output / "report.md").write_text(render_report(result), encoding="utf-8")
    write_csv(output / "files.csv", [{
        **{key: row[key] for key in ("path", "sha256", "bytes", "duplicate_of", "status", "severity", "plugin",
                                     "handler", "document_type", "exit_code", "error")},
        "bank": row["bank"], "transactions": len(row["transactions"]), "tax_events": row["tax_events"],
        "snapshots": row["snapshots"], "documents": "", "archive_only": "",
        "ocr_indications": row["ocr_indications"], "duration_s": row["duration_s"],
        "fields": len(row["field_values"]), "issue_codes": row["issue_codes"]} for row in files],
        ["path", "sha256", "bytes", "duplicate_of", "status", "severity", "bank", "plugin", "handler",
         "document_type", "transactions", "tax_events", "snapshots", "documents", "archive_only", "ocr_indications",
         "duration_s", "fields", "issue_codes", "exit_code", "error"])
    write_csv(output / "findings.csv", [{"path": row["path"], "sha256": row["sha256"], **item}
                                        for row in files for item in row["findings"]],
              ["path", "sha256", "code", "level", "message", "nature", "event_id", "evidence_id"])
    write_csv(output / "transactions.csv", [transaction_row(row["path"], row["sha256"], event)
                                            for row in files for event in row["transactions"]],
              ["path", "sha256", "event_id", "kind", "event_date", "reversal_of_event_id", "amount", "currency",
               "cash_status", "side", "security", "isin", "wkn", "quantity", "gross_amount", "fee_count", "tax_count",
               "cost_count", *TRANSACTION_JSON])
    comparison = result["comparison"]
    write_csv(output / "delta.csv", [{"kind": kind, **entry} for kind in ("changed", "regressions", "improved")
                                     for entry in comparison[kind]],
              ["kind", "path", "sha256", "matched_by", "fields", "field_values", "new_issue_codes", "resolved_issue_codes"])


def build_result(rows, config: Config, scan_errors, resumed: int, seconds: float, training_warnings,
                 mapping) -> dict:
    unique = [row for row in rows if row["status"] != "DUPLICATE"]
    counts = Counter(row["status"] for row in rows)
    return {
        "schema_version": SCHEMA_VERSION, "audit_tool": AUDIT_TOOL,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(), "scan_root": str(config.root),
        "git_commit": git_commit(), "rule_mode": config.rule_mode, "plugin_id": config.plugin_id or "",
        "allow_ocr": config.allow_ocr, "timeout_s": config.timeout, "parser_fingerprint": config.fingerprint,
        "runtime": {"python": sys.version.split()[0], "platform": platform.platform()},
        "training_database": {"path": str(config.training_database) if config.training_database else "",
                              "warnings": training_warnings},
        "catalog": {"source": str(config.catalog), "mapping_summary": (mapping or {}).get("summary", {}),
                    "description_store": "description-store/field-descriptions.v1.json"},
        "scan_errors": scan_errors,
        "summary": {"physical": len(rows), "unique": len(unique), "resumed": resumed,
                    "seconds": round(seconds, 2), "status": dict(sorted(counts.items()))},
        "quality": quality(rows),
        "banks": group_stats(rows, lambda row: row["bank"] or "(kein Parser)"),
        "parsers": group_stats(rows, lambda row: row["plugin"] or "(kein Parser)"),
        "document_types": group_stats(rows, lambda row: row["document_type"] or "(keine)"),
        "issue_codes": dict(Counter(code for row in rows for code in row["issue_codes"])),
        "comparison": compare(rows, config.baseline, config),
        "files": rows,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only PDF Lab audit V3 (portman-parsers, Kindprozess je PDF).")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--baseline", type=Path, help="früherer PDF-Lab-Audit V3 (audit.json)")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--allow-ocr", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--training-database", "--training-db", dest="training_database", type=Path,
                        help="bestehende Trainingsdatenbank, nur lesend")
    parser.add_argument("--rule-mode", choices=RULE_MODES, default="STANDARD")
    parser.add_argument("--plugin-id", help="Parser erzwingen statt automatischer Auswahl")
    parser.add_argument("--field-catalog", type=Path, default=DEFAULT_CATALOG,
                        help="YAML-Feldkatalog als Beschreibungsquelle (nur lesend)")
    parser.add_argument("--description-store", type=Path,
                        help="bestehender field-descriptions.v1.json (wird nur kopiert)")
    parser.add_argument("--profile-dir", type=Path, help="Regelprofil-Verzeichnis (nur lesend)")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--relative", help=argparse.SUPPRESS)
    parser.add_argument("--result-file", type=Path, help=argparse.SUPPRESS)
    return parser


def main(argv=None) -> int:
    from portman_parsers.rules.profiles import default_profile_directory
    parser = build_parser()
    args = parser.parse_args(argv)
    profile_dir = (args.profile_dir or default_profile_directory()).resolve()
    if args.worker:
        configure_worker()
        return worker_main(args, profile_dir)
    if not args.root or not args.root.is_dir() or not args.output:
        parser.error("--root muss ein bestehendes Verzeichnis sein; --output ist erforderlich")
    if args.resume and args.no_cache:
        parser.error("--resume und --no-cache schließen sich aus")
    root, output = args.root.resolve(), args.output.resolve()
    if output == root or root in output.parents:
        parser.error("--output muss außerhalb von --root liegen")
    if args.plugin_id and args.plugin_id not in PLUGIN_GROUPS:
        parser.error(f"unbekanntes Plugin: {args.plugin_id}")
    try:
        baseline = load_baseline(args.baseline) if args.baseline else None
    except (OSError, ValueError) as error:
        parser.error(f"Baseline nicht verwendbar: {error}")
    fingerprint = parser_fingerprint(args.rule_mode, args.plugin_id, profile_dir)
    config = Config(root=root, output=output, timeout=args.timeout, rule_mode=args.rule_mode,
                    plugin_id=args.plugin_id, profile_dir=profile_dir, allow_ocr=args.allow_ocr,
                    training_database=args.training_database.resolve() if args.training_database else None,
                    catalog=args.field_catalog.resolve(),
                    description_store=args.description_store.resolve() if args.description_store else None,
                    baseline=baseline, fingerprint=fingerprint)
    started = time.perf_counter()
    output.mkdir(parents=True, exist_ok=True)
    work_dir = output / ".work"
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True)
    try:
        files, scan_errors = discover_pdfs(root)
        resumed_rows = load_resume(output, config) if args.resume else {}
        rows, jobs, first_by_hash, resumed = [], [], {}, 0
        for rel, path in files:
            try:
                digest, size = sha256_file(path), path.stat().st_size
            except OSError as error:
                rows.append(classify(rel, "", "", {"outcome": "FILE_ERROR",
                                                   "message": scrub(f"{type(error).__name__}: {error} ({rel})")}))
                continue
            if digest in first_by_hash:
                rows.append(classify(rel, digest, size, {"outcome": "DUPLICATE", "duplicate_of": first_by_hash[digest]}))
                continue
            first_by_hash[digest] = rel
            prior = resumed_rows.get(rel)
            if prior and prior.get("sha256") == digest and prior.get("bytes") == size:
                rows.append(prior)
                resumed += 1
            else:
                jobs.append((rel, path, digest, size))
        catalog, mapping = prepare_catalog(config)
        workers = max(1, min(MAX_WORKERS, os.cpu_count() or 1))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(safe_run_child, rel, path, config, work_dir): (rel, digest, size)
                       for rel, path, digest, size in jobs}
            for index, future in enumerate(as_completed(futures), 1):
                rel, digest, size = futures[future]
                rows.append(classify(rel, digest, size, future.result()))
                if index % PROGRESS_EVERY == 0 or index == len(jobs):
                    save_progress(output, config, rows)
                if index % 25 == 0 or index == len(jobs):
                    print(f"{len(rows)}/{len(files)} | Fehler {sum(r['status'] == 'ERROR' for r in rows)} | "
                          f"Timeouts {sum(r['status'] == 'TIMEOUT' for r in rows)} | Resume {resumed}", flush=True)
        rows.sort(key=lambda row: (row["path"].casefold(), row["path"]))
        save_progress(output, config, rows)
        batch_report = {"files": [row["analysis"] for row in rows]}
        from portman_pdf_lab.application.batch_csv import export_batch_csv
        export_batch_csv(batch_report, output / "parser_fields.csv", config.training_database, catalog)
        result = build_result(rows, config, scan_errors, resumed, time.perf_counter() - started,
                              batch_report.get("warnings", []), mapping)
        write_outputs(output, result)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    print(f"Bericht: {output / 'report.md'}")
    failures = sum(row["status"] in FAILURE_STATUSES for row in result["files"])
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
