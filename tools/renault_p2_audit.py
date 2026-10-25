"""Uncached, process-isolated Renault PDF audit with per-file timeouts."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path


def _worker(path: Path, root: Path, allow_ocr: bool) -> dict:
    from portfolio_v5.pdf_importer import parse_pdf

    started = time.perf_counter()
    row = {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    try:
        batch = parse_pdf(path, allow_ocr=allow_ocr)
        transactions = [{key: getattr(tx, key, None) for key in
                         ("external_id", "account", "date", "value_date", "kind", "amount", "currency", "purpose")}
                        for tx in batch.transactions]
        statements = [{key: getattr(statement, key, None) for key in
                       ("account", "statement_no", "period_start", "period_end",
                        "opening_balance", "closing_balance", "currency")}
                      for statement in batch.statements]
        documents = [{key: getattr(document, key, None) for key in
                      ("account", "title", "date", "document_type", "document_no")}
                     for document in batch.documents]
        row.update(status="error" if batch.errors else "warning" if batch.warnings else "pass",
                   plugin=batch.plugin_id, handler=batch.plugin_handler,
                   document_type=batch.document_type, transactions=transactions,
                   transaction_count=len(transactions), document_count=len(documents), documents=documents,
                   tax_events=len(batch.tax_events), statements=statements,
                   errors=list(batch.errors), warnings=list(batch.warnings))
    except Exception as exc:  # audit boundary: preserve exact parser failure
        row.update(status="error", plugin="", handler="", document_type="",
                   transactions=[], transaction_count=0, document_count=0, documents=[], tax_events=0,
                   statements=[], errors=[f"{type(exc).__name__}: {exc}"], warnings=[])
    row["duration_s"] = round(time.perf_counter() - started, 3)
    return row


def _write_csv(path: Path, rows: list[dict], fields: tuple[str, ...]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in fields} for row in rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--allow-ocr", action="store_true")
    parser.add_argument("--worker", type=Path)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(_worker(args.worker, args.root, args.allow_ocr), ensure_ascii=False))
        return 0

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    before = [row for row in baseline["files"] if row["path"].startswith("renault/")]
    old = {row["path"]: row for row in before}
    rows = []
    for index, baseline_row in enumerate(before, 1):
        path = args.root / baseline_row["path"]
        command = [sys.executable, str(Path(__file__).resolve()), "--root", str(args.root),
                   "--baseline", str(args.baseline), "--output", str(args.output), "--worker", str(path)]
        if args.allow_ocr:
            command.append("--allow-ocr")
        try:
            completed = subprocess.run(command, capture_output=True, text=True,
                                       timeout=args.timeout, check=True)
            row = json.loads(completed.stdout)
        except subprocess.TimeoutExpired:
            row = {"path": baseline_row["path"], "sha256": baseline_row["sha256"],
                   "status": "timeout", "plugin": "", "handler": "", "document_type": "",
                   "transactions": [], "transaction_count": 0, "documents": 0, "tax_events": 0,
                   "statements": [], "errors": [f"Timeout after {args.timeout}s"], "warnings": [],
                   "duration_s": args.timeout}
        row["baseline_status"] = baseline_row.get("severity", "")
        row["baseline_plugin"] = baseline_row.get("plugin", "")
        row["baseline_handler"] = baseline_row.get("handler", "")
        rows.append(row)
        if index % 25 == 0 or index == len(before):
            print(f"{index}/{len(before)} errors={sum(r['status'] == 'error' for r in rows)} "
                  f"timeouts={sum(r['status'] == 'timeout' for r in rows)}", flush=True)

    args.output.mkdir(parents=True, exist_ok=True)
    hashes = Counter(row["sha256"] for row in rows)
    regressions = [row["path"] for row in rows
                   if old[row["path"]].get("severity") != "ERROR" and row["status"] in ("error", "timeout")]
    summary = {"physical_files": len(rows), "unique_sha256": len(hashes),
               "duplicate_files": sum(count - 1 for count in hashes.values()),
               "errors": sum(row["status"] == "error" for row in rows),
               "timeouts": sum(row["status"] == "timeout" for row in rows),
               "generic_fallbacks": sum(row["plugin"] == "generic.kontoauszug" for row in rows),
               "regressions": len(regressions),
               "transactions": sum(row["transaction_count"] for row in rows),
                   "documents": sum(row["document_count"] for row in rows)}
    result = {"schema_version": 1, "scope": "renault/", "root": str(args.root),
              "baseline": str(args.baseline), "ocr_enabled": args.allow_ocr,
              "timeout_seconds": args.timeout, "summary": summary,
              "handler_counts": dict(Counter(row["handler"] or "(none)" for row in rows)),
              "regressions": regressions, "files": rows}
    (args.output / "audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    file_rows = []
    findings = []
    for row in rows:
        statement = row["statements"][0] if len(row["statements"]) == 1 else {}
        file_rows.append({"path": row["path"], "sha256": row["sha256"], "status": row["status"],
                          "baseline_status": row["baseline_status"], "plugin": row["plugin"],
                          "handler": row["handler"], "document_type": row["document_type"],
                          "transactions": row["transaction_count"], "documents": row["document_count"],
                          "document_date": "; ".join(sorted({doc.get("date", "") for doc in row["documents"]
                                                               if doc.get("date")})),
                          "accounts": "; ".join(sorted({doc.get("account", "") for doc in row["documents"]
                                                         if doc.get("account")})),
                          "period_start": statement.get("period_start", ""),
                          "period_end": statement.get("period_end", ""),
                          "opening_balance": statement.get("opening_balance", ""),
                          "closing_balance": statement.get("closing_balance", ""),
                          "duration_s": row["duration_s"]})
        for level, values in (("ERROR", row["errors"]), ("WARNING", row["warnings"])):
            findings.extend({"path": row["path"], "sha256": row["sha256"],
                             "level": level, "message": message} for message in values)
    _write_csv(args.output / "files.csv", file_rows, tuple(file_rows[0]))
    _write_csv(args.output / "findings.csv", findings,
               ("path", "sha256", "level", "message"))
    transaction_rows = [{"path": row["path"], **transaction}
                        for row in rows for transaction in row["transactions"]]
    _write_csv(args.output / "transactions.csv", transaction_rows,
               ("path", "external_id", "account", "date", "value_date", "kind", "amount", "currency", "purpose"))
    report = ["# Renault PDF audit P2", "", f"- Physical files: **{summary['physical_files']}**",
              f"- Unique SHA-256: **{summary['unique_sha256']}**",
              f"- Errors: **{summary['errors']}**; timeouts: **{summary['timeouts']}**",
              f"- Generic fallbacks: **{summary['generic_fallbacks']}**; regressions: **{summary['regressions']}**",
              f"- Transactions: **{summary['transactions']}**; archived documents: **{summary['documents']}**",
              "", "## Handlers", ""]
    report += [f"- `{handler}`: {count}" for handler, count in sorted(result["handler_counts"].items())]
    (args.output / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return 1 if summary["errors"] or summary["timeouts"] or summary["regressions"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
