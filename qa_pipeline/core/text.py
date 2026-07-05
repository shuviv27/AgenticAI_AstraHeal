from __future__ import annotations

import re


def words(value: str) -> list[str]:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value or "")
    return re.findall(r"[A-Za-z0-9]+", value)


def pascal_case(value: str) -> str:
    parts = words(value)
    return "".join(p[:1].upper() + p[1:] for p in parts) or "Generated"


def camel_case(value: str) -> str:
    p = pascal_case(value)
    return p[:1].lower() + p[1:] if p else "generated"


def kebab_case(value: str) -> str:
    return "-".join(w.lower() for w in words(value)) or "generated"


def safe_id(value: str) -> str:
    return kebab_case(value).replace("-", "_")
