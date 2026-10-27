"""Read-only, aggregate-only integrity audit for an explicitly supplied SQLite copy."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path


PRODUCTION_NAME = "portfolio.sqlite"
REQUIRED_TABLES = {
    "accounts",
    "imports",
    "transactions",
    "snapshots",
    "balances",
    "import_model_records",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_target(database: Path, production: Path | None = None) -> Path:
    supplied = database.expanduser()
    if supplied.is_symlink():
        raise ValueError("Die Testdatenbank muss eine reguläre Datei und darf kein Symlink sein.")
    target = supplied.resolve(strict=True)
    if not target.is_file():
        raise ValueError("Die Testdatenbank muss eine reguläre Datei und darf kein Symlink sein.")
    production = (production or target.with_name(PRODUCTION_NAME)).expanduser().resolve(strict=False)
    if target == production or target.name.casefold() == PRODUCTION_NAME:
        raise ValueError("Die produktive portfolio.sqlite darf nicht geprüft werden.")
    for suffix in ("-wal", "-shm", "-journal"):
        if Path(str(target) + suffix).exists():
            raise ValueError(f"Aktive SQLite-Sidecar-Datei gefunden: {target.name}{suffix}")
    return target


def scalar(db: sqlite3.Connection, sql: str) -> int:
    return int(db.execute(sql).fetchone()[0])


def audit(database: Path, expected_sha256: str | None = None,
          production: Path | None = None) -> dict:
    target = validate_target(database, production)
    before_size = target.stat().st_size
    before_hash = sha256(target)
    if expected_sha256 and before_hash.casefold() != expected_sha256.casefold():
        raise ValueError("SHA-256 stimmt nicht mit dem ausdrücklich erwarteten Wert überein.")

    uri = target.as_uri() + "?mode=ro&immutable=1"
    with sqlite3.connect(uri, uri=True, timeout=1) as db:
        db.row_factory = sqlite3.Row
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_schema WHERE type='table'")}
        missing = sorted(REQUIRED_TABLES - tables)
        if missing:
            raise ValueError("Erforderliche Portman-Tabellen fehlen: " + ", ".join(missing))

        integrity_rows = [row[0] for row in db.execute("PRAGMA integrity_check")]
        foreign_rows = list(db.execute("PRAGMA foreign_key_check"))
        foreign_tables = Counter(str(row[0]) for row in foreign_rows)

        conflicting_transactions = scalar(db, """
            SELECT count(*) FROM (
              SELECT lower(trim(t.account)), t.external_id
              FROM transactions t JOIN imports i ON i.id=t.import_id
              WHERE i.active=1
              GROUP BY lower(trim(t.account)), t.external_id
              HAVING count(DISTINCT t.content_hash)>1
            )
        """)
        repeated_transactions = scalar(db, """
            SELECT count(*) FROM (
              SELECT lower(trim(t.account)), t.external_id
              FROM transactions t JOIN imports i ON i.id=t.import_id
              WHERE i.active=1
              GROUP BY lower(trim(t.account)), t.external_id
              HAVING count(*)>1
            )
        """)
        conflicting_tax_ids = scalar(db, """
            SELECT count(*) FROM (
              SELECT json_extract(r.payload,'$.external_id') AS external_id
              FROM import_model_records r JOIN imports i ON i.id=r.import_id
              WHERE i.active=1 AND r.kind='tax_events'
                AND json_extract(r.payload,'$.external_id') IS NOT NULL
              GROUP BY external_id HAVING count(DISTINCT r.payload)>1
            )
        """)
        conflicting_tax_detail_ids = scalar(db, """
            SELECT count(*) FROM (
              SELECT json_extract(r.payload,'$.external_id') AS external_id
              FROM import_model_records r JOIN imports i ON i.id=r.import_id
              WHERE i.active=1 AND r.kind='tax_details'
                AND json_extract(r.payload,'$.external_id') IS NOT NULL
              GROUP BY external_id HAVING count(DISTINCT r.payload)>1
            )
        """)
        nonfinite_payload_numbers = scalar(db, """
            SELECT count(*) FROM transactions t JOIN imports i ON i.id=t.import_id
            WHERE i.active=1 AND (
              lower(CAST(json_extract(t.payload,'$.amount') AS TEXT)) IN ('nan','inf','infinity','-inf','-infinity')
              OR lower(CAST(json_extract(t.payload,'$.quantity') AS TEXT)) IN ('nan','inf','infinity','-inf','-infinity')
            )
        """)

    after_size = target.stat().st_size
    after_hash = sha256(target)
    if (before_size, before_hash) != (after_size, after_hash):
        raise RuntimeError("Die Prüfdatenbank hat sich während des Audits verändert.")

    return {
        "database": str(target),
        "bytes": before_size,
        "sha256": before_hash,
        "read_only_uri": True,
        "unchanged_after_audit": True,
        "checks": {
            "sqlite_integrity_ok": integrity_rows == ["ok"],
            "sqlite_integrity_issue_count": 0 if integrity_rows == ["ok"] else len(integrity_rows),
            "foreign_key_issue_count": len(foreign_rows),
            "foreign_key_issue_tables": dict(sorted(foreign_tables.items())),
            "active_repeated_transaction_identity_count": repeated_transactions,
            "active_conflicting_transaction_identity_count": conflicting_transactions,
            "active_conflicting_tax_event_id_count": conflicting_tax_ids,
            "active_conflicting_tax_detail_id_count": conflicting_tax_detail_ids,
            "active_nonfinite_transaction_count": nonfinite_payload_numbers,
        },
        "privacy": "Nur aggregierte Zähler; keine Konto-, Buchungs- oder Payloaddaten ausgegeben.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path,
                        help="Expliziter Pfad zu einer freigegebenen Testkopie")
    parser.add_argument("--expected-sha256",
                        help="Optionaler, vor dem Öffnen zu bestätigender SHA-256")
    parser.add_argument("--production", type=Path,
                        help="Zusätzlicher expliziter Produktionspfad, der gesperrt wird")
    args = parser.parse_args(argv)
    try:
        report = audit(args.database, args.expected_sha256, args.production)
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "REFUSED", "error": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "COMPLETE", **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
