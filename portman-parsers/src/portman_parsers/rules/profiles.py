"""Validated YAML profiles stored outside site-packages and training SQLite."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil

import yaml


class RuleProfileError(ValueError):
    pass


def default_profile_directory() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "Portman" / "PDFLab" / "rule-profiles"


def _canonical(payload: dict) -> str:
    clean = {key: value for key, value in payload.items() if key != "profile_hash"}
    return json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class RuleProfile:
    profile_id: str
    bank: str
    parser_id: str
    document_type: str
    handler_id: str
    layout_variant: str
    profile_version: int
    parser_version: str
    rules: tuple[dict, ...]
    status: str = "APPROVED"
    schema_version: int = 1
    created_at: str = ""
    activated_at: str | None = None
    approved_by: str = ""
    approval_reason: str = ""
    profile_hash: str = ""

    def __post_init__(self):
        if self.schema_version != 1: raise RuleProfileError("unsupported profile schema")
        if self.status not in {"DRAFT", "TESTED", "APPROVED", "REJECTED", "SUPERSEDED"}: raise RuleProfileError("invalid profile status")
        if not all((self.profile_id, self.bank, self.parser_id, self.document_type, self.handler_id, self.layout_variant, self.parser_version)):
            raise RuleProfileError("profile selector fields are required")
        if self.profile_version < 1: raise RuleProfileError("profile version must be positive")
        object.__setattr__(self, "rules", tuple(dict(item) for item in self.rules))

    def to_dict(self, include_hash=True):
        value = {"schema_version": self.schema_version, "profile_id": self.profile_id, "bank": self.bank,
                 "parser_id": self.parser_id, "document_type": self.document_type, "handler_id": self.handler_id,
                 "layout_variant": self.layout_variant, "profile_version": self.profile_version,
                 "parser_version": self.parser_version, "status": self.status,
                 "created_at": self.created_at, "activated_at": self.activated_at,
                 "approved_by": self.approved_by, "approval_reason": self.approval_reason,
                 "rules": list(self.rules)}
        if include_hash: value["profile_hash"] = self.profile_hash or self.compute_hash()
        return value

    def compute_hash(self):
        return hashlib.sha256(_canonical(self.to_dict(False)).encode("utf-8")).hexdigest()

    def sealed(self):
        created = self.created_at or datetime.now(timezone.utc).isoformat()
        profile = replace(self, created_at=created, profile_hash="")
        return replace(profile, profile_hash=profile.compute_hash())

    @classmethod
    def from_dict(cls, value):
        allowed = {field.name for field in __import__("dataclasses").fields(cls)}
        unknown = set(value) - allowed
        if unknown: raise RuleProfileError(f"unknown profile fields: {sorted(unknown)}")
        profile = cls(**value)
        if not profile.profile_hash or profile.profile_hash != profile.compute_hash():
            raise RuleProfileError("profile hash mismatch")
        return profile


class ProfileStore:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else default_profile_directory()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.activation_path = self.directory / "activations.json"

    def save(self, profile: RuleProfile) -> Path:
        profile = profile.sealed()
        if profile.status != "APPROVED": raise RuleProfileError("only approved profiles can be persisted for use")
        target = self.directory / f"{profile.profile_id}.v{profile.profile_version}.yaml"
        if target.exists():
            existing = self.load(target)
            if existing.profile_hash != profile.profile_hash: raise RuleProfileError("approved profile version is immutable")
            return target
        temporary = target.with_suffix(".yaml.tmp")
        temporary.write_text(yaml.safe_dump(profile.to_dict(), allow_unicode=True, sort_keys=True), encoding="utf-8")
        os.replace(temporary, target)
        return target

    def load(self, path) -> RuleProfile:
        value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict): raise RuleProfileError("profile YAML must contain an object")
        return RuleProfile.from_dict(value)

    def import_profile(self, source) -> RuleProfile:
        profile = self.load(source); self.save(profile); return profile

    def export_profile(self, profile: RuleProfile, target) -> Path:
        source = self.save(profile); destination = Path(target); destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination); return destination

    @staticmethod
    def _activation_key(parser_id, handler_id, document_type, layout_variant):
        return "|".join((parser_id, handler_id, document_type, layout_variant))

    def _activations(self):
        if not self.activation_path.exists(): return {}
        return json.loads(self.activation_path.read_text(encoding="utf-8"))

    def activate(self, profile: RuleProfile):
        profile = profile.sealed(); self.save(profile)
        values = self._activations(); key = self._activation_key(profile.parser_id, profile.handler_id, profile.document_type, profile.layout_variant)
        values[key] = {"profile_id": profile.profile_id, "profile_version": profile.profile_version,
                       "profile_hash": profile.profile_hash, "activated_at": datetime.now(timezone.utc).isoformat()}
        temporary = self.activation_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(values, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        os.replace(temporary, self.activation_path)

    def deactivate(self, parser_id, handler_id, document_type, layout_variant):
        values = self._activations(); values.pop(self._activation_key(parser_id, handler_id, document_type, layout_variant), None)
        temporary = self.activation_path.with_suffix(".tmp"); temporary.write_text(json.dumps(values, sort_keys=True, indent=2), encoding="utf-8"); os.replace(temporary, self.activation_path)

    def active(self, parser_id, handler_id, document_type, layout_variant, parser_version=None):
        item = self._activations().get(self._activation_key(parser_id, handler_id, document_type, layout_variant))
        if not item: return None
        path = self.directory / f"{item['profile_id']}.v{item['profile_version']}.yaml"
        profile = self.load(path)
        if parser_version and profile.parser_version != parser_version: return None
        return profile
