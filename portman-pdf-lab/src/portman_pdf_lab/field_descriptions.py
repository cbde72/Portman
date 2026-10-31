"""Versioned, reusable German descriptions for public parser DTO fields."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Any

from .field_catalog import FieldCatalog, FieldDefinition, normalize_field_path


DESCRIPTION_SCHEMA_VERSION = 1
_TECHNICAL_SUFFIXES = ("status", "evidence", "confidence", "source")


@dataclass(frozen=True)
class DescriptionEntry:
    normalized_path: str
    description: str
    source: str
    schema_version: int = DESCRIPTION_SCHEMA_VERSION
    status: str = "AUTO_DERIVED"


_KNOWN: dict[str, str] = {
    "bank_name": "Name der kontoführenden Bank",
    "account_name": "Bezeichnung des Bankkontos",
    "account_id": "Eindeutige Kennung des Bankkontos",
    "account_number": "Kontonummer des Bankkontos",
    "iban": "Internationale Bankkontonummer",
    "bic": "Internationale Kennung des kontoführenden Instituts",
    "currency": "Währung des zugehörigen Kontos oder Betrags",
    "isin": "Internationale Wertpapierkennnummer",
    "wkn": "Wertpapierkennnummer",
    "security_name": "Bezeichnung des Wertpapiers",
    "quantity": "Anzahl der Wertpapierstücke oder Anteile",
    "gross_amount": "Bruttobetrag vor den ausgewiesenen Abzügen",
    "settlement_amount": "Settlementbetrag nach den ausgewiesenen Zu- und Abzügen",
    "net_amount": "Nettobetrag nach den ausgewiesenen Abzügen",
    "value_date": "Datum der Wertstellung",
    "trade_date": "Datum des Wertpapiergeschäfts",
    "execution_date": "Datum der Ausführung des Wertpapiergeschäfts",
    "price": "Ausgewiesener Kurs des Wertpapiers",
    "market_value": "Ausgewiesener Markt- oder Kurswert",
    "amount": "Ausgewiesener Geldbetrag",
    "tax_amount": "Ausgewiesener Steuerbetrag",
    "fee_amount": "Ausgewiesener Gebührenbetrag",
    "fee_date": "Datum der Gebührenposition",
    "venue": "Handelsplatz beziehungsweise Börsenplatz",
    "security_id": "Kennung des Wertpapiers",
    "depot_id": "Eindeutige Kennung des Depots",
    "depot_number": "Depotnummer",
    "account_ref": "Referenz auf das zugehörige Konto",
    "custom_reference": "Zusätzlicher Referenzwert des zugehörigen Objekts",
}


def description_lookup_path(path: str) -> str:
    """Remove indices and only technical wrappers used by FieldValue DTOs."""
    normalized = normalize_field_path(path)
    parts = normalized.split(".") if normalized else []
    while parts and parts[-1] in _TECHNICAL_SUFFIXES:
        parts.pop()
    return ".".join(parts)


def _context_description(path: str, leaf: str) -> str | None:
    if leaf == "quantity":
        if ".positions[]" in path or "depot_snapshots[]" in path:
            return "Anzahl der im Depot gehaltenen Wertpapierstücke oder Anteile"
        if ".trades[]" in path or ".security_movements[]" in path:
            return "Anzahl der gehandelten Wertpapierstücke oder Anteile"
    if leaf == "currency":
        if ".cash_movements[]" in path:
            return "Währung des Geldbetrags"
        if ".trades[]" in path:
            return "Währung des Wertpapierbetrags"
    if leaf == "amount":
        if ".fee_events[]" in path:
            return "Ausgewiesener Gebührenbetrag"
        if ".tax_events[]" in path or ".components[]" in path:
            return "Ausgewiesener Steuerbetrag"
        if ".cash_movements[]" in path:
            return "Ausgewiesener Betrag der Kontobewegung"
    if leaf == "custom_reference" and path.startswith("accounts[]"):
        return "Zusätzlicher Referenzwert des Bankkontos"
    return None


def _neutral_description(path: str) -> str:
    parts = [part for part in description_lookup_path(path).split(".") if part]
    leaf = parts[-1] if parts else "Feld"
    if leaf == "value":
        return "Zusätzlicher Wert des zugehörigen Objekts"
    contextual = _context_description(".".join(parts), leaf)
    if contextual:
        return contextual
    if leaf in _KNOWN:
        return _KNOWN[leaf]
    words = re.sub(r"[_-]+", " ", leaf).strip()
    context = " des zugehörigen Objekts"
    if parts and parts[0] == "accounts":
        context = " des Bankkontos"
    elif parts and parts[0] in {"trades", "events"}:
        context = " des Vorgangs"
    elif parts and parts[0] in {"depots", "depot_snapshots"}:
        context = " des Depots"
    return f"Zusätzlicher Wert {words}{context}" if words else "Zusätzlicher Wert des zugehörigen Objekts"


class DescriptionCatalog:
    def __init__(self, entries: tuple[DescriptionEntry, ...] = (), path: Path | None = None):
        self.path = path
        self._entries = {entry.normalized_path: entry for entry in entries}

    @classmethod
    def load(cls, path: str | Path):
        source = Path(path)
        if not source.exists():
            return cls(path=source)
        payload = json.loads(source.read_text(encoding="utf-8"))
        if int(payload.get("schema_version", 0)) != DESCRIPTION_SCHEMA_VERSION:
            raise ValueError("unsupported description catalog schema")
        entries = tuple(DescriptionEntry(**item) for item in payload.get("entries", ()))
        return cls(entries, source)

    def save(self) -> Path:
        if self.path is None:
            raise ValueError("description catalog has no path")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"schema_version": DESCRIPTION_SCHEMA_VERSION,
                                         "entries": [asdict(item) for item in sorted(self._entries.values(), key=lambda x: x.normalized_path)]},
                                        ensure_ascii=False, indent=2), encoding="utf-8")
        return self.path

    def get(self, path: str) -> DescriptionEntry | None:
        return self._entries.get(description_lookup_path(path))

    def put(self, entry: DescriptionEntry) -> DescriptionEntry:
        existing = self._entries.get(entry.normalized_path)
        if existing and existing.status == "VERIFIED":
            return existing
        self._entries[entry.normalized_path] = entry
        return entry

    def resolve(self, path: str, definition: FieldDefinition | None = None) -> DescriptionEntry:
        normalized = description_lookup_path(path)
        existing = self.get(path)
        if existing:
            return existing
        if definition and definition.description.strip():
            entry = DescriptionEntry(normalized, definition.description.strip(), "field_catalog", status="VERIFIED")
        else:
            entry = DescriptionEntry(normalized, _neutral_description(path), "dto_context_derived")
        return self.put(entry)


def catalog_for_field_catalog(catalog: FieldCatalog | None) -> DescriptionCatalog:
    path = catalog.path.parent / "field-descriptions.v1.json" if catalog and catalog.path else None
    return DescriptionCatalog.load(path) if path else DescriptionCatalog()


def resolve_description(path: str, catalog: FieldCatalog | None = None,
                        description_catalog: DescriptionCatalog | None = None) -> DescriptionEntry:
    definition = None
    if catalog:
        definition = catalog.field_for_description(path)
    store = description_catalog or catalog_for_field_catalog(catalog)
    entry = store.resolve(path, definition)
    if store.path:
        store.save()
    return entry
