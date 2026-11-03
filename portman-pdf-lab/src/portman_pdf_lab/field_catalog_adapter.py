"""Adapter for the curated, global PDF-Lab field description catalog.

The YAML catalog intentionally is not a ``field_catalog.py`` runtime catalog:
it has no bank/parser/document selection and its paths are semantic paths.
This module maps only paths that exist in the public parser DTOs and writes
unknown/deviating paths to an audit document.  It never changes parser rules
or requirement profiles.
"""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

import yaml

from .field_descriptions import DescriptionCatalog, DescriptionEntry
from .field_catalog import normalize_field_path


SCHEMA_NAME = "portman-pdf-lab-field-description-catalog"
SCHEMA_VERSION = "1.0"

# Semantic catalog collection -> complete public DTO collection path.
_ROOTS = {
    "accounts": "accounts[]",
    "depots": "depots[]",
    "depot_account_links": "depot_account_links[]",
    "trades": "events[].trades[]",
    "cash_movements": "events[].cash_movements[]",
    "tax_events": "events[].tax_events[]",
    "fee_events": "events[].fee_events[]",
    "positions": "depot_snapshots[].positions[]",
    "depot_snapshots": "depot_snapshots[]",
    "issues": "issues[]",
    "evidence": "evidence[]",
    "parser": "",  # handled by the ParsedDocument root below
}

_ALIASES = {
    ("accounts", "account_holder"): "holder_name",
    ("accounts", "opening_balance"): None,
    ("accounts", "closing_balance"): None,
    ("accounts", "balance_date"): None,
    ("accounts", "interest_rate"): None,
    ("depots", "owner_name"): "holder_name",
    ("depots", "currency"): "base_currency",
    ("depot_account_links", "relation_type"): "role",
    ("trades", "net_amount"): "settlement_amount",
    ("trades", "amount_currency"): "settlement_currency",
    ("positions", "valuation_date"): "price_date",
    ("tax_events", "taxable_amount"): "taxable_amount",
    ("tax_events", "tax_amount"): None,
    ("tax_events", "withholding_tax"): "actually_withheld_tax",
    ("fee_events", "fee_type"): None,
    ("fee_events", "is_informational"): None,
    ("evidence", "page"): "page_number",
    ("evidence", "text"): "excerpt",
    ("parser", "parser_id"): "plugin_id",
    ("parser", "version"): "plugin_version",
}

# Fields from the public DTOs, kept here as a contract snapshot.  The audit is
# deliberately explicit: a newly added DTO member must be reviewed and added
# rather than silently becoming an accepted catalog path.
_DTO_FIELDS = {
    "accounts": {"account_id", "bank_name", "account_name", "account_type", "account_number", "iban", "bic", "currency", "holder_name", "attributes", "functions"},
    "depots": {"depot_id", "bank_name", "depot_name", "depot_number", "holder_name", "base_currency", "attributes", "depot_type"},
    "depot_account_links": {"link_id", "depot_id", "account_id", "role", "valid_from", "valid_until", "is_default"},
    "trades": {"trade_id", "event_id", "side", "security_name", "isin", "wkn", "quantity", "trade_date", "execution_date", "value_date", "price", "price_currency", "market_value", "gross_amount", "exchange_rate", "settlement_amount", "settlement_currency", "depot_id", "account_id", "evidence_ids"},
    "cash_movements": {"movement_id", "event_id", "amount", "currency", "status", "account_ref", "evidence_ids", "account_id", "linked_security_movement_id", "movement_type", "transfer_id", "counterpart_movement_id"},
    "tax_events": {"tax_event_id", "event_id", "kind", "components", "taxable_basis", "cash_movement_id", "evidence_ids", "depot_id", "isin", "tax_year", "accrual_date", "booking_date", "value_date", "bank_id", "currency", "account_id", "assessment_basis", "advance_before_partial_exemption", "taxable_amount", "stated_tax_liability", "actually_withheld_tax", "distributions", "start_value", "end_value", "partial_exemption_rate", "exemption_order_used", "loss_offset_used", "acquisition_date", "approval_status"},
    "fee_events": {"fee_id", "category", "subcategory", "amount", "currency", "fee_date", "effect", "document_id", "bank_id", "depot_id", "account_id", "security_id", "transaction_id", "cash_movement_id", "external_reference", "reverses_fee_id", "allocations", "evidence_ids"},
    "positions": {"position_id", "security_id", "quantity", "security_name", "market_value", "currency", "price", "price_date"},
    "depot_snapshots": {"snapshot_id", "depot_id", "as_of", "positions", "total_value", "currency"},
    "issues": {"issue_id", "code", "severity", "message", "nature"},
    "evidence": {"evidence_id", "document_id", "page_number", "excerpt", "source_ref"},
    "parser": {"plugin_id", "handler_id", "plugin_version", "document_hash"},
}


# These labels describe the origin of an unmapped semantic catalog entry.
# Do not turn optional labels into fictitious parser DTO members.
_RUNTIME_COLLECTIONS = {"document", "parser"}
_OPTIONAL_EXTENSION_PATHS = {
    "trade.venue": "attributes.user_fields.trade.venue",
    "trades[].venue": "attributes.user_fields.trade.venue",
}


def classify_unmapped(path: str, status: str) -> tuple[str, str]:
    """Separate missing DTO members from document metadata and optional hints."""
    collection = path.split(".", 1)[0].removesuffix("[]")
    if path in _OPTIONAL_EXTENSION_PATHS:
        return "OPTIONAL_EXTENSION", "Existing optional user field, not a STANDARD DTO member"
    if collection == "document":
        return "DOCUMENT_METADATA", "Document-level metadata or bank-specific document field, not an audited public DTO member"
    if collection == "parser":
        return "RUNTIME_METADATA", "Execution or extraction metadata; not a public ParsedDocument member"
    if collection in {"securities", "income_events"}:
        return "UNSUPPORTED_COLLECTION", "The public DTO has no dedicated collection of this name"
    if status == "no_dto_member":
        return "UNSUPPORTED_DTO_FIELD", "Explicitly absent from this public DTO; do not invent a mapping"
    if status == "unknown_dto_member":
        return "UNSUPPORTED_DTO_FIELD", "Not a declared member of this public DTO"
    return "UNSUPPORTED_COLLECTION", "No verified root mapping for the semantic collection"


def _mapping(path: str) -> tuple[str | None, str]:
    parts = path.split(".")
    collection = parts[0].removesuffix("[]")
    leaf = parts[-1]
    root = _ROOTS.get(collection)
    if root is None:
        return None, "unknown_collection"
    target_leaf = _ALIASES.get((collection, leaf), leaf)
    if target_leaf is None:
        return None, "no_dto_member"
    if target_leaf not in _DTO_FIELDS.get(collection, set()):
        return None, "unknown_dto_member"
    return f"{root}.{target_leaf}" if root else target_leaf, ("aliased" if target_leaf != leaf else "exact")


def import_factual_catalog(source: str | Path, destination: str | Path,
                           audit_path: str | Path | None = None) -> dict[str, Any]:
    """Import descriptions and produce an auditable DTO mapping.

    Existing ``VERIFIED`` descriptions win.  The destination is the central
    description store used by all runtime catalogs, while the audit retains
    the original semantic path and the complete mapped DTO path.
    """
    source = Path(source); destination = Path(destination)
    payload = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if payload.get("schema_name") != SCHEMA_NAME or str(payload.get("schema_version")) != SCHEMA_VERSION:
        raise ValueError("unsupported factual field catalog schema")
    store = DescriptionCatalog.load(destination)
    mapped, unknown, deviations, classified = [], [], [], []
    for semantic_path, item in (payload.get("fields") or {}).items():
        dto_path, status = _mapping(normalize_field_path(semantic_path))
        record = {"catalog_path": semantic_path, "dto_path": dto_path, "status": status}
        if dto_path is None:
            category, reason = classify_unmapped(semantic_path, status)
            record.update({"classification": category, "reason": reason})
            unknown.append(record)
            classified.append(record)
            continue
        if status == "aliased":
            deviations.append(record)
        mapped.append(record)
        store.put(DescriptionEntry(normalize_field_path(dto_path), str(item.get("description") or ""),
                                   "fachlich_kuratierter_katalog", status="VERIFIED"))
    store.save()
    audit = {"catalog": str(source), "catalog_version": str(payload.get("catalog_version")),
             "schema_version": str(payload.get("schema_version")), "mapped": mapped,
             "unknown_paths": unknown, "deviating_paths": deviations,
             "classified_unmapped": classified,
             "summary": {"total": len(payload.get("fields") or {}), "mapped": len(mapped),
                         "unknown": len(unknown), "deviating": len(deviations),
                         "classified_unmapped": len(classified),
                         "classification_counts": {category: sum(item["classification"] == category for item in classified)
                                                   for category in sorted({item["classification"] for item in classified})}}}
    if audit_path is None:
        audit_path = source.with_suffix(source.suffix + ".audit.json")
    audit_path = Path(audit_path); audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return audit
