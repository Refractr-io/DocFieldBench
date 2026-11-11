"""Score one prediction against one task: a list of units, each with one outcome.

Units and outcomes:
- a present scalar field: correct, swapped (the value is another field's gold in the same document), wrong
  (flagged `partial` when it overlaps the gold), or omitted (null);
- an absent field (scalar or whole array): abstained (null or empty) or fabricated;
- a present array of scalars: one unit per gold item (correct or omitted), plus `extra` for predicted items with no
  gold counterpart;
- a present array of objects: gold and predicted rows are aligned (Hungarian, on per-row field agreement; rows that
  agree on less than half their fields stay unmatched). Each gold row field is a unit; the non-null fields of
  unmatched predicted rows are `extra`.
`extra` units are silent errors but never enter the recall or abstention denominators, which are fixed by the gold.
A document whose response failed (transport error, empty, unparseable, not an object) scores every unit `failed`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from .matchers import accepted, partial
from .normalize import is_null_like_string, is_nullish, parse_number
from .schema import base_type, conformance_errors, item_properties, iter_fields
from .tasks import pointer_get

OK_PARSE = ("ok", "fenced")


@dataclass
class Unit:
    pointer: str
    unit: str
    status: str
    outcome: str
    kind: str
    gold: object = None
    pred: object = None
    partial: bool = False
    null_like: bool = False
    tags: list = field(default_factory=list)


def _swap_pool(task: dict) -> list[tuple[str, str, object, list]]:
    """(unit id, kind, gold, accept) for every present non-boolean, non-zero gold value in the document."""
    pool = []
    for ptr, rec in task["fields"].items():
        if rec.get("status") != "present":
            continue
        kind = rec["match"]
        if kind == "array_objects":
            for i, item in enumerate(rec["value"]):
                for f, k in rec["item_match"].items():
                    g = item.get(f)
                    if k != "boolean" and not is_nullish(g) and parse_number(g) != 0:
                        pool.append((f"{ptr}/{i}/{f}", k, g, []))
        elif kind == "array_scalars":
            for i, g in enumerate(rec["value"]):
                pool.append((f"{ptr}/{i}", rec["item_match"], g, []))
        elif kind != "boolean" and parse_number(rec["value"]) != 0:
            pool.append((ptr, kind, rec["value"], rec.get("accept") or []))
    return pool


def _present_outcome(unit_id, kind, gold, accept, pred, pool, locale):
    if is_nullish(pred):
        return "omitted", False
    if accepted(kind, gold, accept, pred, locale):
        return "correct", False
    for uid, k, g, acc in pool:
        if uid != unit_id and accepted(k, g, acc, pred, locale):
            return "swapped", False
    return "wrong", partial(kind, gold, pred)


def _as_list(pred) -> list:
    if isinstance(pred, list):
        return pred
    return [] if is_nullish(pred) else [pred]


def _item_accept(rec: dict, f: str, g) -> list:
    """Alternatives for one row value: the negated amount when the document prints it negative."""
    if f in (rec.get("item_sign_either") or []) and isinstance(g, (int, float)) and not isinstance(g, bool) and g:
        return [-g]
    return []


def _align(gold_rows, pred_rows, item_match, locale, rec):
    """Pairs (gold index, pred index) of rows that agree on at least half of the gold row's present fields."""
    if not gold_rows or not pred_rows:
        return []
    S = np.zeros((len(gold_rows), len(pred_rows)))
    for i, g in enumerate(gold_rows):
        present = [f for f in item_match if not is_nullish(g.get(f))]
        if not present:
            continue
        for j, p in enumerate(pred_rows):
            hits = sum(accepted(item_match[f], g[f], _item_accept(rec, f, g[f]), p.get(f), locale) for f in present)
            S[i, j] = hits / len(present)
    rows, cols = linear_sum_assignment(-S)
    return [(i, j) for i, j in zip(rows, cols, strict=True) if S[i, j] >= 0.5]


def score_task(task: dict, prediction: dict | None) -> dict:
    """{'task_id', 'doc': document-level flags, 'units': [Unit as dict]} for one prediction."""
    prediction = prediction or {"parse_status": "transport", "parsed": None}
    status = prediction.get("parse_status", "ok")
    parsed = prediction.get("parsed")
    failed = status not in OK_PARSE or not isinstance(parsed, dict)
    locale = task.get("locale") or {}
    errs = [] if failed else conformance_errors(task["schema"], parsed)
    doc = {"parse_status": status, "failed": failed, "fenced": status == "fenced",
           "conformant": not failed and not errs, "conformance_errors": errs, "item_counts": []}
    pool = _swap_pool(task)
    units: list[Unit] = []
    for ptr, node in iter_fields(task["schema"]):
        rec = task["fields"][ptr]
        st = rec["status"]
        if st == "excluded":
            continue
        tags = list(rec.get("tags") or [])
        kind = rec["match"]
        pred = None if failed else pointer_get(parsed, ptr)
        is_array = base_type(node) == "array"

        if st == "absent":
            empty = all(is_nullish(x) for x in _as_list(pred)) if is_array else is_nullish(pred)
            out = "failed" if failed else ("abstained" if empty else "fabricated")
            units.append(Unit(ptr, ptr, "absent", out, kind, None, pred,
                              null_like=is_null_like_string(pred), tags=tags))
            continue

        if not is_array:
            if failed:
                units.append(Unit(ptr, ptr, "present", "failed", kind, rec["value"], None, tags=tags))
                continue
            out, part = _present_outcome(ptr, kind, rec["value"], rec.get("accept"), pred, pool, locale)
            units.append(Unit(ptr, ptr, "present", out, kind, rec["value"], pred, part,
                              is_null_like_string(pred), tags))
            continue

        gold_rows = rec["value"]
        pred_rows = _as_list(pred)
        doc["item_counts"].append({"pointer": ptr, "gold": len(gold_rows), "pred": len(pred_rows)})
        row_tags = tags + ["line_item"]

        if kind == "array_scalars":
            ik = rec["item_match"]
            accepts = rec.get("item_accept") or [[] for _ in gold_rows]
            used: set[int] = set()
            for i, g in enumerate(gold_rows):
                uid = f"{ptr}/{i}"
                if failed:
                    units.append(Unit(ptr, uid, "present", "failed", ik, g, None, tags=row_tags))
                    continue
                j = next((j for j, p in enumerate(pred_rows)
                          if j not in used and accepted(ik, g, accepts[i], p, locale)), None)
                if j is None:
                    units.append(Unit(ptr, uid, "present", "omitted", ik, g, None, tags=row_tags))
                else:
                    used.add(j)
                    units.append(Unit(ptr, uid, "present", "correct", ik, g, pred_rows[j], tags=row_tags))
            for j, p in enumerate(pred_rows):
                if j not in used and not failed and not is_nullish(p):
                    units.append(Unit(ptr, f"{ptr}/+{j}", "extra", "extra", ik, None, p, tags=row_tags))
            continue

        # array of objects
        im = rec["item_match"]
        props = item_properties(node) or {}
        prows = [p if isinstance(p, dict) else {} for p in pred_rows]
        pairs = {} if failed else dict(_align(gold_rows, prows, im, locale, rec))
        matched_pred = set(pairs.values())
        for i, g in enumerate(gold_rows):
            j = pairs.get(i)
            p = prows[j] if j is not None else {}
            for f in props:
                uid, k, gv = f"{ptr}/{i}/{f}", im[f], g.get(f)
                pv = p.get(f)
                if failed:
                    out, part = "failed", False
                elif is_nullish(gv):
                    out, part = ("abstained" if is_nullish(pv) else "fabricated"), False
                elif j is None:
                    out, part = "omitted", False
                else:
                    out, part = _present_outcome(uid, k, gv, _item_accept(rec, f, gv), pv, pool, locale)
                units.append(Unit(ptr, uid, "absent" if is_nullish(gv) else "present", out, k, gv,
                                  None if failed else pv, part, is_null_like_string(pv), row_tags))
        for j, p in enumerate(prows):
            if j in matched_pred or failed:
                continue
            for f, pv in p.items():
                if f in im and not is_nullish(pv):
                    units.append(Unit(ptr, f"{ptr}/+{j}/{f}", "extra", "extra", im[f], None, pv, tags=row_tags))

    return {"task_id": task["task_id"], "track": task.get("track"), "variant_of": task.get("variant_of"),
            "condition": (task.get("document") or {}).get("condition"), "doc": doc,
            "units": [asdict(u) for u in units]}
