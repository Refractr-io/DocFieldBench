"""Deterministic field matchers. Each answers one question: is this prediction the gold value for a field of this kind?

Value correctness only. Whether the prediction also followed the output contract (ISO dates, JSON numbers, JSON
null) is conformance, scored separately (`schema.py`).
"""
from __future__ import annotations

from .normalize import alnum, bare_name, is_nullish, parse_date, parse_number, text_norm, tokens

KINDS = ("id", "date", "amount", "number", "integer", "boolean", "name", "short_text")
STRING_KINDS = ("id", "name", "short_text")

_TRUE = {"true", "yes", "y", "ja", "j", "si", "sí", "oui", "x", "checked", "1"}
_FALSE = {"false", "no", "n", "nee", "nein", "non", "unchecked", "0"}


def _bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = text_norm(v)
        if s in _TRUE:
            return True
        if s in _FALSE:
            return False
    return None


def same(kind: str, gold, pred, locale: dict | None = None) -> bool:
    """True when `pred` is the value `gold` for a field of this kind."""
    if is_nullish(gold) or is_nullish(pred) or isinstance(pred, (dict, list)):
        return False
    locale = locale or {}
    if kind == "boolean":
        g, p = _bool(gold), _bool(pred)
        return g is not None and g == p
    if kind in ("amount", "number", "integer"):
        g = parse_number(gold, locale.get("decimal"))
        p = parse_number(pred, locale.get("decimal"))
        if g is None or p is None:
            return False
        if kind == "integer":
            return p == int(p) and int(p) == int(g)
        if kind == "amount":
            return abs(g - p) <= 0.005
        return abs(g - p) <= max(1e-9, 1e-9 * abs(g))
    if kind == "date":
        g = parse_date(str(gold))
        p = parse_date(str(pred), locale.get("date_order"))
        return g is not None and p is not None and g[0] == p[0]
    if kind == "id":
        a, b = alnum(gold), alnum(pred)
        return bool(a) and a == b
    if kind in ("name", "short_text"):
        if text_norm(gold) == text_norm(pred):
            return True
        a, b = alnum(gold), alnum(pred)
        if len(a) >= 3 and a == b:
            return True
        if kind == "name":
            a, b = bare_name(gold), bare_name(pred)
            return len(a) >= 3 and a == b
        return False
    raise ValueError(f"unknown match kind: {kind}")


def accepted(kind: str, gold, accept, pred, locale: dict | None = None) -> bool:
    """`pred` matches the gold value or one of its accepted alternatives."""
    return any(same(kind, g, pred, locale) for g in [gold, *(accept or [])])


def partial(kind: str, gold, pred) -> bool:
    """A wrong string answer that overlaps the gold: one contains the other, or half the tokens agree."""
    if kind not in STRING_KINDS or is_nullish(gold) or is_nullish(pred) or isinstance(pred, (dict, list)):
        return False
    g, p = text_norm(gold), text_norm(pred)
    if len(p) >= 3 and len(g) >= 3 and (g in p or p in g):
        return True
    a, b = tokens(gold), tokens(pred)
    return bool(a and b) and len(a & b) / len(a | b) >= 0.5
