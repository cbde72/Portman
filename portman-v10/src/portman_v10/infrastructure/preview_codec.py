"""Persistiert ausschließlich normalisierte V10-Vorschau-DTOs, nie Parserdumps."""
from dataclasses import asdict
from datetime import date
import json

from portman_v10.application.contracts import (
    Conflict, ConflictDecision, ErrorCode, ImportDocumentResult, ImportPreview,
    PreviewComponent, PreviewDate, PreviewEvidence, PreviewIssue, PreviewItem,
    PreviewMovement, RecordedDecision,
)
from portman_v10.domain.values import ExactValue


def _json_value(value):
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, ExactValue):
        return {"text": value.text}
    if isinstance(value, ErrorCode):
        return value.value
    raise TypeError(type(value).__name__)


def encode_preview(preview: ImportPreview) -> str:
    return json.dumps(asdict(preview), default=_json_value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _exact(value):
    return ExactValue(value["text"]) if value is not None else None


def decode_preview(payload: str, *, revision: int | None = None, data_revision: int | None = None) -> ImportPreview:
    raw = json.loads(payload)
    items = []
    for item in raw["items"]:
        movements = tuple(PreviewMovement(**{**m, "amount": _exact(m["amount"]), "date": date.fromisoformat(m["date"]) if m["date"] else None}) for m in item.get("movements", ()))
        components = tuple(PreviewComponent(**{**c, "amount": _exact(c["amount"])}) for c in item.get("components", ()))
        dates = tuple(PreviewDate(date.fromisoformat(d["value"]) if d["value"] else None, d["meaning"], d.get("unknown_reason")) for d in item.get("dates", ()))
        evidence = tuple(PreviewEvidence(**e) for e in item.get("source_evidence", ()))
        warnings = tuple(PreviewIssue(**w) for w in item.get("warnings", ()))
        conflicts = tuple(Conflict(ErrorCode(c["code"]), c["message"], c["candidate_id"], c.get("related_event_id")) for c in item.get("conflicts", ()))
        amounts = tuple((a[0], _exact(a[1]), a[2]) for a in item.get("amounts", ()))
        items.append(PreviewItem(**{**item, "movements": movements, "components": components, "dates": dates,
                                    "source_evidence": evidence, "warnings": warnings, "conflicts": conflicts,
                                    "amounts": amounts, "account_ids": tuple(item["account_ids"]),
                                    "instrument_ids": tuple(item["instrument_ids"]),
                                    "references": tuple(tuple(pair) for pair in item.get("references", ())),
                                    "missing_fields": tuple(item.get("missing_fields", ())),
                                    "effective_dates": tuple(date.fromisoformat(d) if d else None for d in item["effective_dates"])}))
    documents = tuple(ImportDocumentResult(**{**d, "error_code": ErrorCode(d["error_code"]) if d["error_code"] else None,
                                              "warning_messages": tuple(d["warning_messages"])}) for d in raw.get("documents", ()))
    decisions = tuple(RecordedDecision(d["candidate_id"], d["candidate_revision"], d["preview_revision"], ConflictDecision(**d["decision"])) for d in raw.get("decisions", ()))
    return ImportPreview(raw["import_id"], revision if revision is not None else raw["revision"],
                         data_revision if data_revision is not None else raw["data_revision"], tuple(items), documents, decisions)
