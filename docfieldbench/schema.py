"""bench-schema v1: the JSON Schema subset every task uses, conformance checking, and provider conversions.

The subset (every major structured-output API and local grammar engine accepts it):
- the root is an object; every object lists all its properties in `required` and sets `additionalProperties: false`;
- scalars are nullable: `{"type": [T, "null"]}` with T in string, integer, number, boolean; `"format": "date"` is
  allowed on strings and means an ISO 8601 calendar date at year, month or day precision;
- arrays are fields: `{"type": ["array", "null"], "items": ...}`, items are non-null scalars or flat objects of
  nullable scalars;
- nested objects (non-null) group fields; at most three container levels below the root;
- no descriptions, enums, compositions or references: field names carry the meaning.
"""
from __future__ import annotations

import copy
import re
from collections.abc import Iterator

from jsonschema import Draft202012Validator, FormatChecker

from .normalize import is_null_like_string

SCALARS = ("string", "integer", "number", "boolean")
_OBJECT_KEYS = {"type", "properties", "required", "additionalProperties"}
_SCALAR_KEYS = {"type", "format"}
_ARRAY_KEYS = {"type", "items"}
MAX_DEPTH = 3


def escape(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _nullable(t, base) -> bool:
    return isinstance(t, list) and len(t) == 2 and base in t and "null" in t


def _check_object(node, path, depth, errors, *, item=False):
    where = path or "/"
    if not isinstance(node, dict) or node.get("type") != "object":
        errors.append(f"{where}: must be an object node with type 'object'")
        return
    extra = set(node) - _OBJECT_KEYS
    if extra:
        errors.append(f"{where}: keys not allowed: {sorted(extra)}")
    props = node.get("properties")
    if not isinstance(props, dict) or not props:
        errors.append(f"{where}: needs a non-empty 'properties'")
        return
    if sorted(node.get("required") or []) != sorted(props):
        errors.append(f"{where}: 'required' must list every property")
    if node.get("additionalProperties") is not False:
        errors.append(f"{where}: 'additionalProperties' must be false")
    if depth > MAX_DEPTH:
        errors.append(f"{where}: deeper than {MAX_DEPTH} container levels")
    for k, v in props.items():
        p = f"{path}/{escape(k)}"
        if not isinstance(v, dict):
            errors.append(f"{p}: must be a schema object")
            continue
        t = v.get("type")
        if t == "object":
            if item:
                errors.append(f"{p}: array items must be flat (no nested objects)")
            else:
                _check_object(v, p, depth + 1, errors)
        elif _nullable(t, "array"):
            if item:
                errors.append(f"{p}: array items must be flat (no nested arrays)")
            else:
                _check_array(v, p, depth + 1, errors)
        elif isinstance(t, list) and any(_nullable(t, s) for s in SCALARS):
            _check_scalar(v, p, errors)
        else:
            errors.append(f"{p}: type must be 'object', ['array','null'] or [scalar,'null'], got {t!r}")


def _check_scalar(node, path, errors, *, nullable=True):
    extra = set(node) - _SCALAR_KEYS
    if extra:
        errors.append(f"{path}: keys not allowed: {sorted(extra)}")
    t = node.get("type")
    base = t if isinstance(t, str) else next((x for x in t if x != "null"), None)
    if "format" in node and (base != "string" or node["format"] != "date"):
        errors.append(f"{path}: only strings may carry a format, and only 'date'")
    if not nullable and not (isinstance(t, str) and t in SCALARS):
        errors.append(f"{path}: array items must be a single non-null scalar type")


def _check_array(node, path, depth, errors):
    extra = set(node) - _ARRAY_KEYS
    if extra:
        errors.append(f"{path}: keys not allowed: {sorted(extra)}")
    items = node.get("items")
    if not isinstance(items, dict):
        errors.append(f"{path}: needs 'items'")
        return
    if items.get("type") == "object":
        _check_object(items, f"{path}/items", depth, errors, item=True)
    else:
        _check_scalar(items, f"{path}/items", errors, nullable=False)


def check_schema(schema: dict) -> list[str]:
    """Every way `schema` departs from bench-schema v1 (empty when it conforms)."""
    errors: list[str] = []
    _check_object(schema, "", 0, errors)
    return errors


def base_type(node: dict) -> str:
    t = node.get("type")
    return t if isinstance(t, str) else next(x for x in t if x != "null")


def iter_fields(schema: dict, path: str = "") -> Iterator[tuple[str, dict]]:
    """(JSON pointer, schema node) for every field: each scalar and each array; nested objects are walked into."""
    for k, v in schema["properties"].items():
        p = f"{path}/{escape(k)}"
        if v.get("type") == "object":
            yield from iter_fields(v, p)
        else:
            yield p, v


def item_properties(array_node: dict) -> dict | None:
    """The item fields of an array of objects, or None for an array of scalars."""
    items = array_node["items"]
    return items["properties"] if items.get("type") == "object" else None


# ---------------------------------------------------------------------------------------------------------------
# conformance

_ISO_DATE = re.compile(r"^\d{4}(-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?)?$")
FORMATS = FormatChecker(formats=())


@FORMATS.checks("date")
def _is_iso_date(value) -> bool:
    return not isinstance(value, str) or bool(_ISO_DATE.match(value))


def _null_like_paths(value, path="") -> Iterator[str]:
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _null_like_paths(v, f"{path}/{escape(str(k))}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _null_like_paths(v, f"{path}/{i}")
    elif is_null_like_string(value):
        yield path or "/"


def conformance_errors(schema: dict, instance, limit: int = 20) -> list[str]:
    """Contract violations: schema errors (types, missing or extra keys, non-ISO dates) and null-like strings."""
    v = Draft202012Validator(schema, format_checker=FORMATS)
    errs = [f"/{'/'.join(escape(str(p)) for p in e.absolute_path)}: {e.message}" for e in v.iter_errors(instance)]
    errs += [f"{p}: null-like string instead of null" for p in _null_like_paths(instance)]
    return errs[:limit]


# ---------------------------------------------------------------------------------------------------------------
# provider conversions

def _strip_format(node):
    if isinstance(node, dict):
        return {k: _strip_format(v) for k, v in node.items() if k != "format"}
    return node


def to_json_schema(schema: dict, keep_format: bool = False) -> dict:
    """Plain JSON Schema for OpenAI strict mode, Anthropic tools, vLLM and llama.cpp. `format` is dropped by default:
    strict engines would force full dates where the document gives only a month; the prompt states the date rule."""
    return copy.deepcopy(schema) if keep_format else _strip_format(schema)


def to_openai_response_format(schema: dict, keep_format: bool = False) -> dict:
    return {"type": "json_schema",
            "json_schema": {"name": "extraction", "strict": True, "schema": to_json_schema(schema, keep_format)}}


def to_anthropic_tool(schema: dict) -> dict:
    return {"name": "record_extraction", "description": "Record the values extracted from the document.",
            "input_schema": to_json_schema(schema)}


def to_gemini(node: dict) -> dict:
    """Gemini `responseSchema` (OpenAPI subset): upper-case types, `nullable` instead of type unions."""
    t = node.get("type")
    base = base_type(node)
    out: dict = {"type": base.upper()}
    if isinstance(t, list) and "null" in t:
        out["nullable"] = True
    if base == "object":
        props = node["properties"]
        out["properties"] = {k: to_gemini(v) for k, v in props.items()}
        out["required"] = list(props)
        out["propertyOrdering"] = list(props)
    elif base == "array":
        out["items"] = to_gemini(node["items"])
    return out
