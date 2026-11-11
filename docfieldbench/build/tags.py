"""Capability tags per field, computed at build time from the gold and the document text. Results are reported per
tag, so a reader can see where a system's errors sit.

  lookalike   another field of the same task has the same kind and a different present value (invoice date vs
              due date, seller vs buyer): choosing the right one is the test
  normalize   the printed form differs from the gold form (a date not printed as ISO, an amount with separators or a
              currency sign): the value must be normalised
  late        the value first appears in the second half of the document
  lang:xx     the document's language
"""
from __future__ import annotations

import re

NUMERIC = ("amount", "number", "integer")


def _first_pos(text: str, rec: dict) -> float | None:
    ev = (rec.get("evidence") or {}).get("text")
    if not ev or not text:
        return None
    i = text.find(ev[:60])
    return i / max(1, len(text)) if i >= 0 else None


def _printed_differs(rec: dict) -> bool:
    ev = (rec.get("evidence") or {}).get("text") or ""
    v = rec.get("value")
    if rec["match"] == "date":
        return isinstance(v, str) and v not in ev
    if rec["match"] in NUMERIC and isinstance(v, (int, float)):
        plain = {str(v), f"{v:.2f}", str(int(v)) if float(v).is_integer() else str(v)}
        return not any(re.search(rf"(?<![\d.,]){re.escape(p)}(?![\d])", ev) for p in plain)
    return False


def tag_task(task: dict, text: str) -> dict:
    present = {p: r for p, r in task["fields"].items() if r["status"] == "present" and r["match"] not in
               ("array_objects", "array_scalars")}
    for p, r in task["fields"].items():
        tags = [t for t in (r.get("tags") or []) if not t.startswith(("lookalike", "normalize", "late", "lang:"))]
        if r["status"] == "present":
            same_kind = [q for q, o in present.items()
                         if q != p and o["match"] == r["match"] and o["value"] != r["value"]]
            if r["match"] in ("date", "amount", "name", "id") and same_kind:
                tags.append("lookalike")
            if _printed_differs(r):
                tags.append("normalize")
            pos = _first_pos(text, r)
            if pos is not None and pos > 0.5:
                tags.append("late")
        tags.append(f"lang:{task.get('language') or '?'}")
        r["tags"] = tags
    return task
