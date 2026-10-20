import json

import pytest

from portfolio_v5.models import ImportBatch, Position, Snapshot
from pdf_plugins._comdirect_depot import append_depot
from portman.repository_v09 import RepositoryV09
from portman.security_names import apply_repairs, clean_security_name, repair_preview


ISIN = "LU1681041973"
WKN = "A2H57N"
GOOD = "AIS-Amundi MSCI EUROPE H.D.FA. Namens-Anteile C Cap.EUR o.N."
BAD = ("Vorgang: Wertpapiere · Verwendungszweck: Kauf ETF "
       "WPKNR: A2H57N ISIN: LU1681041973")


def snapshot(day, name):
    return ImportBatch(day, day, snapshots=[Snapshot(
        "Depot", day[:7], day, "comdirect Finanzreport",
        [Position("WKN:" + WKN, name, isin=ISIN, wkn=WKN,
                  quantity="1", value="100")])])


def master_key(repo):
    return repo.db.execute("SELECT security_key FROM security_master WHERE wkn=?", (WKN,)).fetchone()[0]


def test_repeated_finanzreport_import_keeps_existing_valid_master_name(tmp_path):
    repo = RepositoryV09(tmp_path / "names.sqlite", backups=False)
    try:
        assert repo.commit_batches([snapshot("2026-01-31", GOOD)])[0]["status"] == "imported"
        assert repo.commit_batches([snapshot("2026-02-28", BAD)])[0]["status"] == "imported"
        row = repo.db.execute(
            "SELECT canonical_name,original_names FROM security_master WHERE wkn=?", (WKN,)).fetchone()
        assert row["canonical_name"] == GOOD
        assert BAD in json.loads(row["original_names"])  # immutable source evidence retained
        assert repo.current()[0]["name"] == GOOD
    finally:
        repo.close()


def test_sync_cleans_identifiers_for_a_new_security_name(tmp_path):
    repo = RepositoryV09(tmp_path / "metadata.sqlite", backups=False)
    try:
        decorated = GOOD + " · WKN: " + WKN + " · ISIN: " + ISIN
        repo.commit_batches([snapshot("2026-01-31", decorated)])
        row = repo.db.execute(
            "SELECT canonical_name FROM security_master WHERE wkn=?", (WKN,)).fetchone()
        assert row["canonical_name"] == GOOD
        assert WKN not in row["canonical_name"] and ISIN not in row["canonical_name"]
        assert clean_security_name(GOOD + " WKN: " + WKN + " ISIN: " + ISIN) == GOOD
    finally:
        repo.close()


def test_name_repair_is_preview_only_and_repairs_a2h57n_explicitly(tmp_path):
    repo = RepositoryV09(tmp_path / "repair.sqlite", backups=False)
    try:
        repo.commit_batches([snapshot("2026-01-31", GOOD)])
        key = master_key(repo)
        with repo.db:
            repo.db.execute("UPDATE security_master SET canonical_name=? WHERE security_key=?",
                            (BAD, key))
        preview = repair_preview(repo.db)
        assert preview == [{"security_key": key, "isin": ISIN, "wkn": WKN,
                            "current_name": BAD, "proposed_name": GOOD}]
        assert repo.db.execute("SELECT canonical_name FROM security_master WHERE wkn=?",
                               (WKN,)).fetchone()[0] == BAD
        assert apply_repairs(repo.db, preview) == 1
        assert repo.db.execute("SELECT canonical_name FROM security_master WHERE wkn=?",
                               (WKN,)).fetchone()[0] == GOOD
        assert repo.db.execute("SELECT display_name FROM security_metadata WHERE security_key=?",
                               (key,)).fetchone()[0] == GOOD
    finally:
        repo.close()


def test_repair_aborts_if_preview_became_stale(tmp_path):
    repo = RepositoryV09(tmp_path / "stale.sqlite", backups=False)
    try:
        repo.commit_batches([snapshot("2026-01-31", GOOD)])
        key = master_key(repo)
        with repo.db:
            repo.db.execute("UPDATE security_master SET canonical_name=? WHERE security_key=?",
                            (BAD, key))
        preview = repair_preview(repo.db)
        with repo.db:
            repo.db.execute("UPDATE security_master SET canonical_name='Manuell geändert' WHERE security_key=?",
                            (key,))
        with pytest.raises(ValueError, match="seit der Vorschau"):
            apply_repairs(repo.db, preview)
    finally:
        repo.close()


def test_finanzreport_depot_rejects_booking_text_as_security_name():
    batch = ImportBatch("report.pdf", "hash")
    pages = ["""comdirect
Finanzreport Nr. 1 per 31.01.2026
Kundennummer: 123 4567890
Depot 100,00
Depotbestand
A2H57N 1,0 100,0 EUR 100,00 90,00 +10,00 Vorgang: Wertpapiere Verwendungszweck: Kauf
Gesamtkurswert 100,00 90,00 +10,00
"""]
    with pytest.raises(ValueError, match="Buchungstext als Wertpapiername.*A2H57N"):
        append_depot(batch, pages)
    assert not batch.snapshots


def test_cleaning_identifiers_does_not_damage_balanced_name_punctuation():
    name = "Deutsche Börse Xetra-Gold IHS 2007(09/Und)"
    assert clean_security_name(name) == name
