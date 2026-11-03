"""Optional overlays for STANDARD/EXTENDED/COMPARE without mutating parser DTOs."""

from dataclasses import dataclass
from enum import StrEnum
import re
from collections.abc import Mapping

from portman_parsers.api import MissingValue, ParsedDocument
from .profiles import RuleProfile, RuleProfileError


class RuleMode(StrEnum):
    STANDARD = "STANDARD"
    EXTENDED = "EXTENDED"
    COMPARE = "COMPARE"


class RuleSafetyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FieldDecision:
    field_path: str
    standard_value: object
    rule_value: object
    effective_value: object
    strategy: str
    rule_id: str
    provenance: str
    conflict: bool


@dataclass(frozen=True, slots=True)
class ExtendedParseResult:
    standard_result: ParsedDocument
    mode: RuleMode
    profile_id: str | None = None
    profile_version: int | None = None
    profile_hash: str | None = None
    decisions: tuple[FieldDecision, ...] = ()


def _get_path(value, path):
    current = value
    for token in re.findall(r"[^.\[\]]+|\d+(?=\])", path):
        if token.isdigit():
            current = current[int(token)]
        elif isinstance(current, Mapping):
            current = current.get(token)
        else:
            current = getattr(current, token, None)
        if current is None: break
    return current


class RuleEngine:
    RULE_TYPES = {"LITERAL_FIELD", "REGEX_FIELD"}
    NORMALIZERS = {"TEXT", "AMOUNT", "DATE", "QUANTITY", "UPPER", "STRIP"}
    STRATEGIES = {"FILL_MISSING", "PROPOSE_REPLACEMENT", "APPROVED_OVERRIDE"}

    @staticmethod
    def _safe_pattern(pattern):
        if not pattern or len(pattern) > 240: raise RuleSafetyError("invalid pattern length")
        if re.search(r"\([^)]*[+*][^)]*\)[+*{]|\.\*[+*{]|\.\+[+*{]", pattern): raise RuleSafetyError("unsafe quantifier")
        if any(item in pattern for item in ("(?=", "(?!", "(?<=", "(?<!")): raise RuleSafetyError("look-around is not allowed")
        try: return re.compile(pattern, re.MULTILINE)
        except re.error as exc: raise RuleSafetyError(str(exc)) from exc

    @classmethod
    def validate_profile(cls, profile: RuleProfile):
        if profile.status != "APPROVED": raise RuleProfileError("extended mode requires approved profile")
        for rule in profile.rules:
            if rule.get("rule_type") not in cls.RULE_TYPES: raise RuleSafetyError("unknown rule type")
            if rule.get("strategy", "FILL_MISSING") not in cls.STRATEGIES: raise RuleSafetyError("unknown merge strategy")
            if rule.get("normalizer", "TEXT") not in cls.NORMALIZERS: raise RuleSafetyError("unknown normalizer")
            if not rule.get("field_path") or not rule.get("rule_id"): raise RuleSafetyError("rule identity and field path required")
            cls._safe_pattern(rule.get("pattern", ""))

    @staticmethod
    def _missing(value):
        return value is None or isinstance(value, MissingValue) or value in {"NOT_FOUND", "UNKNOWN", "NOT_APPLICABLE", ""}

    def apply(self, result: ParsedDocument, document_text: str, profile: RuleProfile | None, mode=RuleMode.STANDARD):
        mode = RuleMode(mode)
        if mode == RuleMode.STANDARD or profile is None:
            return ExtendedParseResult(result, RuleMode.STANDARD)
        self.validate_profile(profile); decisions = []
        for rule in profile.rules:
            match = self._safe_pattern(rule["pattern"]).search(document_text)
            if not match: continue
            rule_value = match.groupdict().get("value") if match.groupdict() else match.group(0)
            standard = _get_path(result, rule["field_path"]); strategy = rule.get("strategy", "FILL_MISSING")
            effective = standard; conflict = not self._missing(standard) and standard != rule_value
            if strategy == "FILL_MISSING" and self._missing(standard): effective = rule_value
            elif strategy == "APPROVED_OVERRIDE": effective = rule_value
            decisions.append(FieldDecision(rule["field_path"], standard, rule_value, effective, strategy,
                                           rule["rule_id"], f"rule-profile:{profile.profile_id}@{profile.profile_version}", conflict))
        return ExtendedParseResult(result, mode, profile.profile_id, profile.profile_version,
                                   profile.profile_hash or profile.compute_hash(), tuple(decisions))
