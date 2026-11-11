"""Absent fields: a field the document's family can state, asked of a document that provably doesn't state it.

Absence is never assumed. A field is added as absent only when its check proves the document has no such value (no
label for it, or the family's rule says the box stays empty); where the document does state it, the field is added as
present with the value read from the document; anything in between is not added. Each family has a small library;
which fields a document gets is a seeded draw, and an added field lands at a seeded position in the schema, so neither
its name alone nor its place says whether it is empty.

Used by the release build and by `docfieldbench inject-absent` for your own documents.
"""
from __future__ import annotations

import copy
import random
import re

from .build.visibility import TextIndex
from .normalize import parse_date

MONTH = (r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan\.|Feb\.|"
         r"Mar\.|Apr\.|Aug\.|Sept?\.|Oct\.|Nov\.|Dec\.)\s+\d{1,2},\s*\d{4}")


def _one(found: list[str]):
    vals = list(dict.fromkeys(f.strip() for f in found))
    return vals[0] if len(vals) == 1 else ("ambiguous" if vals else None)


def _date(found: list[str]):
    v = _one(found)
    if v in (None, "ambiguous"):
        return v
    d = parse_date(v, "MDY")
    return d[0] if d else "ambiguous"


# A library entry: key -> (schema node, match kind, read(text) -> value | None | "ambiguous", absent(text) -> bool)
COURT = {
    "dissenting_judge": (
        {"type": ["string", "null"]}, "name",
        lambda t: _one(re.findall(r"([A-Z][A-Za-z'’.\- ]{2,40}?),\s*(?:P\.\s*)?J\.,[^\n]{0,80}?dissent", t)
                       + re.findall(r"JUSTICE ([A-Z][A-Za-z'’\-]+)[^\n]{0,40}dissent", t)),
        lambda t: "dissent" not in t.lower()),
    "rehearing_denied_date": (
        {"type": ["string", "null"], "format": "date"}, "date",
        lambda t: _date(re.findall(r"rehearing[^.]{0,80}?denied,?\s*(?:on\s+)?(" + MONTH + ")", t, re.I)),
        lambda t: "rehearing" not in t.lower()),
    "supreme_court_review_denied_date": (
        {"type": ["string", "null"], "format": "date"}, "date",
        lambda t: _date(re.findall(r"petition for review[^.]{0,120}?denied,?\s*(?:on\s+)?(" + MONTH + ")", t, re.I)),
        lambda t: "petition for review" not in t.lower() and "review denied" not in t.lower()),
    "amicus_curiae": (
        {"type": ["string", "null"]}, "name", lambda t: None, lambda t: "amicus" not in t.lower()),
}
FEDREG = {
    "effective_date": (
        {"type": ["string", "null"], "format": "date"}, "date",
        lambda t: _date(re.findall(r"(?:is|are|become|becomes|will be)\s+effective\s+(?:on\s+)?(" + MONTH + ")",
                                   re.sub(r"\s+", " ", t))),
        lambda t: not TextIndex([t]).label_with_value(["effective"], "date", window=60)),
}
FORM4 = {
    "amendment_original_filing_date": (
        {"type": ["string", "null"], "format": "date"}, "date",
        lambda t: None, lambda t: "If Amendment, Date of Original Filed" in t),
}
LIBRARIES = {"court_opinion": (COURT, 1, 0.75), "federal_register_document": (FEDREG, 1, 1.0),
             "form4": (FORM4, 1, 1.0)}           # family -> (library, fields per document, chance of drawing)


def inject(task: dict, text: str, seed: str) -> tuple[dict, list[str]]:
    """The task with library fields added (stated ones as present, provably missing ones as absent)."""
    lib = LIBRARIES.get(task.get("family"))
    if not lib:
        return task, []
    library, k, chance = lib
    rng = random.Random(f"{seed}-{task['task_id']}")
    stated, missing = [], []
    for key, (_node, _kind, read, absent) in library.items():
        if f"/{key}" in task["fields"]:
            continue
        v = read(text)
        if v not in (None, "ambiguous"):
            stated.append((key, v))
        elif v is None and absent(text):
            missing.append(key)
    picks = [(key, v) for key, v in stated]                      # a stated field is always asked
    if not picks and missing and rng.random() < chance:
        picks = [(key, None) for key in rng.sample(missing, min(k, len(missing)))]
    if not picks:
        return task, []
    t = copy.deepcopy(task)
    props = list(t["schema"]["properties"].items())
    added = []
    for key, v in picks:
        node, kind, _read, _absent = library[key]
        pos = rng.randint(0, len(props))
        props.insert(pos, (key, copy.deepcopy(node)))
        base = {"match": kind, "provenance": "absence_library", "tags": []}
        if v is None:
            t["fields"][f"/{key}"] = {"status": "absent", "value": None, **base,
                                      "evidence": {"check": f"{key}: no label or value for it in the document"}}
        else:
            idx = TextIndex([text])
            if not idx.visible(kind, v):
                continue
            t["fields"][f"/{key}"] = {"status": "present", "value": v, **base, "evidence": idx.evidence(kind, v)}
        added.append(key)
    if not added:
        return task, []
    keep = {k for k, _ in props if k in t["schema"]["properties"] or k in added}
    t["schema"]["properties"] = {k: n for k, n in props if k in keep}
    t["schema"]["required"] = list(t["schema"]["properties"])
    return t, added
