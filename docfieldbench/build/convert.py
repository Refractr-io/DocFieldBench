"""Shared conversions for sources that arrive as prepared cases: a typed template (leaves are type placeholders
such as "__str__", "__date__", "__float__", "__int__", "__bool__"; lists hold one item template) and a gold object of
the same shape. Turns them into a bench-schema v1 schema and per-field gold records.
"""
from __future__ import annotations

import re

from ..normalize import is_nullish, parse_date, parse_number
from ..schema import escape

_MONEY = re.compile(r"amount|total|tax|price|cost|fee|wage|salary|income|paid|payment|due|balance|premium|charge|"
                    r"rent|value|subtotal|refund|deduct|credit|debit|interest", re.IGNORECASE)
_NAME = re.compile(r"(^|_)(name|names|signature|signed_by|signatory|printed|author|judge|counsel|attorney|"
                   r"preparer|employer|employee|applicant|owner|agency|department)(_|$)", re.IGNORECASE)


def _scalar_schema(ph: str) -> dict:
    if ph == "__date__":
        return {"type": ["string", "null"], "format": "date"}
    return {"type": [{"__int__": "integer", "__float__": "number", "__bool__": "boolean"}.get(ph, "string"), "null"]}


def template_to_schema(tmpl) -> dict:
    """Typed template -> bench-schema v1 (every scalar nullable, every array nullable, objects closed)."""
    if isinstance(tmpl, dict):
        props = {k: template_to_schema(v) for k, v in tmpl.items()}
        return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}
    if isinstance(tmpl, list):
        item = tmpl[0] if tmpl else "__str__"
        inner = template_to_schema(item)
        if isinstance(item, str):
            inner = {"type": inner["type"][0], **({"format": "date"} if item == "__date__" else {})}
        return {"type": ["array", "null"], "items": inner}
    return _scalar_schema(tmpl if isinstance(tmpl, str) else "__str__")


def looks_like_id(v) -> bool:
    s = str(v).strip()
    return bool(s) and len(s) <= 40 and bool(re.search(r"\d", s)) and not re.search(r"[a-z]{4,}", s)


def kind_for(key: str, ph: str, value) -> str:
    """Match kind for one leaf, from its placeholder, its key and (for strings) the gold value's shape."""
    if ph == "__date__":
        return "date"
    if ph == "__bool__":
        return "boolean"
    if ph == "__int__":
        return "integer"
    if ph == "__float__":
        return "amount" if _MONEY.search(key) else "number"
    if _NAME.search(key):
        return "name"
    if value is not None and looks_like_id(value):
        return "id"
    return "short_text"


def iso_date(value, order: str | None):
    """Gold dates in ISO; a printed form ('08/01/2023') is resolved with the document's date order."""
    if is_nullish(value):
        return None
    d = parse_date(str(value), order)
    return d[0] if d else None


def leaves(tmpl, gold, path: str = ""):
    """(pointer, key, placeholder or item template, gold value) for every field: scalars and arrays."""
    for k, v in tmpl.items():
        p = f"{path}/{escape(k)}"
        g = gold.get(k) if isinstance(gold, dict) else None
        if isinstance(v, dict):
            yield from leaves(v, g, p)
        else:
            yield p, k, v, g


def number_or_none(v):
    return None if is_nullish(v) else parse_number(v)
