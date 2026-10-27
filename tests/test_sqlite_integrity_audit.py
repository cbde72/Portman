import hashlib
import sqlite3
from pathlib import Path

import pytest

from tools.sqlite_integrity_audit import audit, validate_target


SCHEMA = """
CREATE TABLE accounts(account_key TEXT PRIMARY KEY);
CREATE TABLE imports(id INTEGER PRIMARY KEY, active INTEGER NOT NULL);
CREATE TABLE transactions(id INTEGER PRIMARY KEY, import_id INTEGER REFERENCES imports(id),
 account TEXT NOT NULL, external_id TEXT NOT NULL, content_hash TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE snapshots(id INTEGER PRIMARY KEY);
CREATE TABLE balances(id INTEGER PRIMARY KEY);
CREATE TABLE import_model_records(import_id INTEGER REFERENCES imports(id), kind TEXT, ordinal INTEGER,
 payload TEXT, PRIMARY KEY(import_id,kind,ordinal));
"""


def database(path: Path) -> Path:
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO imports VALUES(1,1)")
        db.execute("INSERT INTO transactions VALUES(1,1,'Bank','id-1','hash-1',?)",
                   ('{"amount":"1.00","quantity":"2"}',))
    return path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_refuses_production_name_and_symlink(tmp_path):
    production = database(tmp_path / "portfolio.sqlite")
    with pytest.raises(ValueError, match="produktive"):
        validate_target(production)
    link = tmp_path / "copy.sqlite"
    try:
        link.symlink_to(production)
    except OSError:
        pytest.skip("Symlinks sind in dieser Windows-Konfiguration nicht verfügbar")
    with pytest.raises(ValueError, match="Symlink"):
        validate_target(link, tmp_path / "actual-production.sqlite")


def test_refuses_sidecar_and_wrong_expected_hash(tmp_path):
    copy = database(tmp_path / "portfolio_test.sqlite")
    sidecar = Path(str(copy) + "-wal")
    sidecar.write_bytes(b"active")
    with pytest.raises(ValueError, match="Sidecar"):
        audit(copy)
    sidecar.unlink()
    with pytest.raises(ValueError, match="SHA-256"):
        audit(copy, "0" * 64)


def test_audit_is_aggregate_read_only_and_detects_conflicts(tmp_path):
    copy = database(tmp_path / "portfolio_test.sqlite")
    with sqlite3.connect(copy) as db:
        db.execute("INSERT INTO imports VALUES(2,1)")
        db.execute("INSERT INTO transactions VALUES(2,2,'bank','id-1','hash-2',?)",
                   ('{"amount":"2.00","quantity":"2"}',))
        db.execute("INSERT INTO import_model_records VALUES(1,'tax_events',0,?)",
                   ('{"external_id":"tax-1","taxable_income":"10"}',))
        db.execute("INSERT INTO import_model_records VALUES(2,'tax_events',0,?)",
                   ('{"external_id":"tax-1","taxable_income":"20"}',))
    before = digest(copy)
    report = audit(copy, before, tmp_path / "portfolio.sqlite")
    assert digest(copy) == before
    assert report["unchanged_after_audit"] is True
    assert report["checks"]["sqlite_integrity_ok"] is True
    assert report["checks"]["foreign_key_issue_count"] == 0
    assert report["checks"]["active_conflicting_transaction_identity_count"] == 1
    assert report["checks"]["active_conflicting_tax_event_id_count"] == 1
    assert "id-1" not in str(report) and "tax-1" not in str(report)
