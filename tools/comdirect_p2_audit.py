"""Isolated, non-persistent audit for the twelve comdirect P2 documents."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def _worker(path: Path, root: Path, allow_ocr: bool) -> dict:
    from portfolio_v5.pdf_importer import parse_pdf

    row = {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    try:
        batch = parse_pdf(path, allow_ocr=allow_ocr)
        row.update(status="error" if batch.errors else "parsed_with_warnings" if batch.warnings else "parsed",
                   plugin=batch.plugin_id, handler=batch.plugin_handler,
                   document_type=batch.document_type, transactions=len(batch.transactions),
                   documents=len(batch.documents), tax_events=len(batch.tax_events),
                   errors=list(batch.errors), warnings=list(batch.warnings))
    except Exception as exc:  # audit boundary: preserve the exact parser exception
        row.update(status="error", plugin="", handler="", document_type="", transactions=0,
                   documents=0, tax_events=0, errors=[f"{type(exc).__name__}: {exc}"], warnings=[])
    return row


def _paths(root: Path, quantity_baseline: Path, distribution_baseline: Path,
           other_baseline: Path | None) -> list[Path]:
    quantity = json.loads(quantity_baseline.read_text(encoding="utf-8"))["files"]
    distribution = json.loads(distribution_baseline.read_text(encoding="utf-8"))["files"]
    relative = [row["path"] for row in quantity]
    relative += [row["path"] for row in distribution
                 if row["path"].startswith("comdirect/") and row.get("severity") == "ERROR"]
    if other_baseline:
        other = json.loads(other_baseline.read_text(encoding="utf-8"))["files"]
        relative += [row["path"] for row in other
                     if row["path"].startswith("comdirect/") and row.get("severity") == "ERROR"]
    return [root / value for value in dict.fromkeys(relative)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--quantity-baseline", type=Path)
    parser.add_argument("--distribution-baseline", type=Path)
    parser.add_argument("--other-baseline", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--allow-ocr", action="store_true")
    parser.add_argument("--worker", type=Path)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(_worker(args.worker, args.root, args.allow_ocr), ensure_ascii=False))
        return 0

    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in _paths(args.root, args.quantity_baseline, args.distribution_baseline, args.other_baseline):
        command = [sys.executable, str(Path(__file__).resolve()), "--root", str(args.root),
                   "--worker", str(path)]
        if args.allow_ocr:
            command.append("--allow-ocr")
        try:
            completed = subprocess.run(command, capture_output=True, text=True,
                                       timeout=args.timeout, check=True)
            rows.append(json.loads(completed.stdout))
        except subprocess.TimeoutExpired:
            rows.append({"path": path.relative_to(args.root).as_posix(),
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                         "status": "timeout", "plugin": "", "handler": "", "document_type": "",
                         "transactions": 0, "documents": 0, "tax_events": 0,
                         "errors": [f"Timeout after {args.timeout}s"], "warnings": []})
    result = {"scope": "comdirect P2", "timeout_seconds": args.timeout,
              "ocr_enabled": args.allow_ocr, "total": len(rows),
              "unique_hashes": len({row["sha256"] for row in rows}),
              "errors": sum(row["status"] == "error" for row in rows),
              "timeouts": sum(row["status"] == "timeout" for row in rows), "files": rows}
    (args.output / "audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    with (args.output / "files.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=("path", "sha256", "status", "plugin", "handler",
                                                        "document_type", "transactions", "documents", "tax_events",
                                                        "errors", "warnings"))
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "errors": " | ".join(row["errors"]),
                             "warnings": " | ".join(row["warnings"])})
    return 1 if result["errors"] or result["timeouts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
