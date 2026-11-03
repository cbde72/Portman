import hashlib
import re


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(payload).hexdigest()[:24]}"


def valid_isin(value: str) -> bool:
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", value):
        return False
    expanded = "".join(str(ord(char) - 55) if char.isalpha() else char for char in value)
    total = sum((int(digit) * (2 if (len(expanded) - index) % 2 == 0 else 1)) // 10
                + (int(digit) * (2 if (len(expanded) - index) % 2 == 0 else 1)) % 10
                for index, digit in enumerate(expanded))
    return total % 10 == 0

