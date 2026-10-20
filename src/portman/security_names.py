"""Validation and conservative repair helpers for security display names."""
import json
import re


_BOOKING_MARKERS = re.compile(
    r"(?:^|\s|[·|])(?:Vorgang|Verwendungszweck)\s*:", re.I)
_IDENTIFIER = re.compile(
    r"(?:\s*[·,;|()/\-]*\s*)(?:WPKNR|WKN|ISIN)\s*:?\s*"
    r"(?:[A-Z0-9]{6}|[A-Z]{2}[A-Z0-9]{9}\d)\b", re.I)


def clean_security_name(value):
    """Return a display-only name without repeated WKN/ISIN decorations."""
    name = " ".join(str(value or "").split()).strip()
    name = _IDENTIFIER.sub(" ", name)
    return re.sub(r"\s+", " ", name).strip(" ·,;|-/")


def is_valid_security_name(value):
    """Reject identifiers, booking prose and names without meaningful letters."""
    raw = " ".join(str(value or "").split()).strip()
    cleaned = clean_security_name(raw)
    if not cleaned or _BOOKING_MARKERS.search(raw):
        return False
    if re.fullmatch(r"(?:WKN:)?[A-Z0-9]{6}|[A-Z]{2}[A-Z0-9]{9}\d", cleaned, re.I):
        return False
    return len(re.findall(r"[A-Za-zÄÖÜäöüß]", cleaned)) >= 3


def preferred_security_name(*values, fallback=""):
    """Prefer the first valid established name and normalize its presentation."""
    for value in values:
        if is_valid_security_name(value):
            return clean_security_name(value)
    return fallback


def best_security_name(values, fallback=""):
    """Choose the most descriptive valid alias from equally trusted sources."""
    candidates = [clean_security_name(value) for value in values if is_valid_security_name(value)]
    return max(candidates, key=lambda value: (len(value.split()), len(value)), default=fallback)


def repair_preview(db):
    """Describe safe name-only repairs without changing the database."""
    rows = db.execute("""SELECT m.security_key,m.isin,m.wkn,m.canonical_name,
        m.original_names,md.display_name FROM security_master m
        LEFT JOIN security_metadata md ON md.security_key=m.security_key
        ORDER BY m.security_key""").fetchall()
    result = []
    for row in rows:
        try:
            originals = json.loads(row["original_names"] or "[]")
        except (TypeError, ValueError):
            originals = []
        fallback = row["isin"] or ("WKN:" + row["wkn"] if row["wkn"] else row["security_key"])
        proposed = preferred_security_name(row["canonical_name"], row["display_name"], fallback="")
        if not proposed:
            proposed = best_security_name(originals, fallback=fallback)
        if proposed != row["canonical_name"]:
            result.append({"security_key": row["security_key"], "isin": row["isin"],
                           "wkn": row["wkn"], "current_name": row["canonical_name"],
                           "proposed_name": proposed})
    return result


def apply_repairs(db, preview):
    """Apply an unchanged preview to name fields only; source records stay intact."""
    changed = 0
    with db:
        for item in preview:
            current = db.execute(
                "SELECT canonical_name FROM security_master WHERE security_key=?",
                (item["security_key"],)).fetchone()
            if not current or current["canonical_name"] != item["current_name"]:
                raise ValueError("Stammdaten wurden seit der Vorschau geändert; Reparatur abgebrochen.")
            db.execute("UPDATE security_master SET canonical_name=?,updated_at=CURRENT_TIMESTAMP "
                       "WHERE security_key=?", (item["proposed_name"], item["security_key"]))
            db.execute("""INSERT INTO security_metadata(security_key,display_name,updated_at)
                VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(security_key) DO UPDATE SET
                display_name=excluded.display_name,updated_at=CURRENT_TIMESTAMP""",
                (item["security_key"], item["proposed_name"]))
            changed += 1
    return changed
