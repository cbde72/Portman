"""Safe declarative rule suggestions; never executes generated Python code."""

from decimal import Decimal, InvalidOperation
import re


class UnsafeRuleError(ValueError):
    pass


def _decimal(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        candidate = value.strip().replace(".", "").replace(",", ".")
        try:
            return Decimal(candidate)
        except InvalidOperation:
            return None
    return None


def compare_values(left, right) -> bool:
    """Compare financial numbers numerically, other values structurally."""
    a, b = _decimal(left), _decimal(right)
    return a == b if a is not None and b is not None else left == right


class SafeRuleEngine:
    MAX_PATTERN_LENGTH = 240

    @classmethod
    def validate_pattern(cls, pattern: str) -> None:
        if not pattern or len(pattern) > cls.MAX_PATTERN_LENGTH:
            raise UnsafeRuleError("pattern is empty or too long")
        if re.search(r"\([^)]*[+*][^)]*\)[+*{]", pattern) or re.search(r"\.\*[+*{]|\.\+[+*{]", pattern):
            raise UnsafeRuleError("nested or repeated wildcard quantifier")
        if "(?=" in pattern or "(?<=" in pattern or "(?!" in pattern or "(?<!" in pattern:
            raise UnsafeRuleError("look-around is not allowed in training rules")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise UnsafeRuleError(str(exc)) from exc

    def suggest(self, annotation: dict) -> dict | None:
        """Prefer a bounded label/value rule; transparently fall back to a literal."""
        text = annotation.get("original_text") or ""
        reference = annotation.get("reference_value")
        field_path = annotation.get("field_path") or ""
        if not text or reference in (None, "") or not field_path:
            return None
        literal = str(reference)
        if literal not in text:
            normalized = literal.replace(".", ",")
            literal = normalized if normalized in text else ""
        if not literal:
            return None
        position = text.find(literal)
        label_part = text[:position].strip() if position >= 0 else ""
        label = re.sub(r"\s*[:=\-–]\s*$", "", label_part).strip()
        if label and len(label) <= 80 and "\n" not in label:
            separator = r"\s*(?:[:=\-–]\s*)?"
            pattern = re.escape(label) + separator + r"(?P<value>[^\r\n;]+)"
            rule_type = "REGEX_FIELD"
            explanation = f"Erkennt den Wert rechts neben dem Label „{label}“; nicht auf „{literal}“ festgelegt."
            risk = "Vorläufig bis ein zweiter Wert desselben Layouts oder ein Golden-Test bestätigt ist."
        else:
            pattern = re.escape(literal); rule_type = "LITERAL_FIELD"
            explanation = "Extract the confirmed literal from its annotated PDF excerpt."
            risk = "Layout-specific literal; requires Golden regression before approval."
        self.validate_pattern(pattern)
        return {"rule_id": f"annotation-{annotation.get('annotation_id', 'new')}",
                "rule_type": rule_type, "field_path": field_path,
                "pattern": pattern, "normalizer": annotation.get("annotation_kind", "TEXT"),
                "strategy": "FILL_MISSING",
                "explanation": explanation, "risk": risk}

    def execute(self, rule: dict, text: str):
        if rule.get("rule_type") not in {"LITERAL_FIELD", "REGEX_FIELD"}:
            raise UnsafeRuleError("unsupported declarative rule type")
        pattern = rule.get("pattern", "")
        self.validate_pattern(pattern)
        match = re.search(pattern, text)
        return (match.groupdict().get("value", match.group(0)).strip() if match else None)
