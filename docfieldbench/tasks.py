"""Tasks: one document, its schema, and a gold record per field.

A task file holds:
  task_id, doc_id, track, source, license, published, language, locale ({"date_order": "DMY"|"MDY",
  "decimal": ","|"."}), document ({path, media_type, pages, condition}), variant_of (the born-digital task a scan or
  photo variant derives from, else null), schema (bench-schema v1), and
  fields: {json_pointer: {status, value, accept?, match, item_match?, item_accept?, provenance, evidence?, tags?}}
Every field of the schema has exactly one record. `status` is present, absent or excluded.
The document is the original file: the benchmark ships no text or OCR; reading the document is the system's job.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from .matchers import KINDS
from .normalize import is_nullish
from .schema import base_type, check_schema, item_properties, iter_fields, unescape

STATUSES = ("present", "absent", "excluded")
MEDIA_TYPES = ("application/pdf", "image/png", "image/jpeg", "text/html", "text/plain")
CONDITIONS = ("born_digital", "scan", "photo")
MAX_PAGES = 10
ARRAY_KINDS = ("array_scalars", "array_objects")
_KINDS_FOR = {
    "string": ("id", "name", "short_text"),
    "date": ("date",),
    "number": ("amount", "number"),
    "integer": ("integer",),
    "boolean": ("boolean",),
}


def pointer_tokens(pointer: str) -> list[str]:
    return [unescape(t) for t in pointer.split("/")[1:]] if pointer else []


def pointer_get(obj, pointer: str):
    """The value at `pointer`, or None when any step is missing."""
    cur = obj
    for tok in pointer_tokens(pointer):
        if isinstance(cur, dict):
            cur = cur.get(tok)
        elif isinstance(cur, list) and tok.isdigit() and int(tok) < len(cur):
            cur = cur[int(tok)]
        else:
            return None
    return cur


def pointer_set(obj: dict, pointer: str, value) -> None:
    toks = pointer_tokens(pointer)
    cur = obj
    for tok in toks[:-1]:
        cur = cur.setdefault(tok, {})
    cur[toks[-1]] = value


def scalar_kind_type(node: dict) -> str:
    base = base_type(node)
    return "date" if base == "string" and node.get("format") == "date" else base


def load_tasks(path: Path) -> list[dict]:
    """All tasks under a directory (`*.json`), sorted by task_id, or a single task file."""
    path = Path(path)
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    tasks = [json.loads(f.read_text()) for f in files]
    return sorted(tasks, key=lambda t: t["task_id"])


def gold_instance(task: dict) -> dict:
    """The gold answer as one JSON object: what a perfect system returns (a copy: editing it never edits the gold)."""
    out: dict = {}
    fields = task["fields"]
    for ptr, node in iter_fields(task["schema"]):
        rec = fields[ptr]
        is_array = base_type(node) == "array"
        if rec["status"] == "present":
            val = copy.deepcopy(rec["value"])
        else:
            val = [] if is_array else None
        pointer_set(out, ptr, val)
    return out


def validate_task(task: dict) -> list[str]:
    """Every way a task departs from the format (empty when it is well formed)."""
    errors = [f"schema {e}" for e in check_schema(task.get("schema") or {})]
    for key in ("task_id", "doc_id", "track", "source", "license", "document", "fields"):
        if key not in task:
            errors.append(f"missing '{key}'")
    if errors:
        return errors
    doc = task["document"]
    if not isinstance(doc, dict) or not doc.get("path"):
        errors.append("document: needs a 'path'")
    else:
        if doc.get("media_type") not in MEDIA_TYPES:
            errors.append(f"document: media_type must be one of {MEDIA_TYPES}")
        if doc.get("condition") not in CONDITIONS:
            errors.append(f"document: condition must be one of {CONDITIONS}")
        if not isinstance(doc.get("pages"), int) or not 1 <= doc["pages"] <= MAX_PAGES:
            errors.append(f"document: pages must be an integer from 1 to {MAX_PAGES}")
    fields = task["fields"]
    schema_ptrs = {p: n for p, n in iter_fields(task["schema"])}
    for p in sorted(set(schema_ptrs) - set(fields)):
        errors.append(f"{p}: schema field without a gold record")
    for p in sorted(set(fields) - set(schema_ptrs)):
        errors.append(f"{p}: gold record for a field the schema doesn't have")
    for p, node in schema_ptrs.items():
        rec = fields.get(p)
        if rec is None:
            continue
        st, val, kind = rec.get("status"), rec.get("value"), rec.get("match")
        if st not in STATUSES:
            errors.append(f"{p}: status must be one of {STATUSES}")
            continue
        if st == "excluded":
            if not rec.get("reason"):
                errors.append(f"{p}: an excluded field needs a 'reason'")
            continue
        if st == "absent" and not is_nullish(val):
            errors.append(f"{p}: absent field with a non-null value")
        if st == "present" and is_nullish(val):
            errors.append(f"{p}: present field without a value")
        if base_type(node) == "array":
            props = item_properties(node)
            want = "array_objects" if props else "array_scalars"
            if kind != want:
                errors.append(f"{p}: arrays of {'objects' if props else 'scalars'} use match '{want}'")
                continue
            im = rec.get("item_match")
            if props:
                if not isinstance(im, dict) or set(im) != set(props):
                    errors.append(f"{p}: item_match must give a kind for every item field {sorted(props)}")
                    continue
                for f, k in im.items():
                    if k not in _KINDS_FOR[scalar_kind_type(props[f])]:
                        errors.append(f"{p}/{f}: match '{k}' doesn't fit type {scalar_kind_type(props[f])}")
                if st == "present" and not (isinstance(val, list) and all(isinstance(x, dict) for x in val)):
                    errors.append(f"{p}: value must be a list of objects")
                elif st == "present":
                    for i, row in enumerate(val):
                        if set(row) != set(props):
                            errors.append(f"{p}/{i}: a gold row must have exactly the keys {sorted(props)}")
            else:
                if im not in _KINDS_FOR[scalar_kind_type(node["items"])]:
                    errors.append(f"{p}: item_match '{im}' doesn't fit item type")
                if st == "present" and not isinstance(val, list):
                    errors.append(f"{p}: value must be a list")
        else:
            if kind not in KINDS:
                errors.append(f"{p}: unknown match kind {kind!r}")
            elif kind not in _KINDS_FOR[scalar_kind_type(node)]:
                errors.append(f"{p}: match '{kind}' doesn't fit type {scalar_kind_type(node)}")
    return errors
