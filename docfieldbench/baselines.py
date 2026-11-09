"""Shortcut baselines: systems that never understand the document. A track where they come close to real systems
is too easy, and the report says so.

- null_all: every field null. Abstention 100%, recall 0: it calibrates the absence metric.
- first_candidate: each typed field gets the first value of its type in the text (first date, first amount, first
  integer, first identifier-shaped token); names, free text and booleans stay null. It measures how much a track
  tests choosing the right value among look-alikes. A build-time check: the caller supplies the text (the PDF's text
  layer); the benchmark itself never converts documents.
"""
from __future__ import annotations

import re

from .normalize import parse_date, parse_number
from .schema import base_type, iter_fields
from .tasks import pointer_set

_DATE_PATTERNS = [
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b",
    r"\b\d{1,2}\.? [A-Za-zÀ-ÿ]{3,10}\.? \d{4}\b",
    r"\b[A-Za-zÀ-ÿ]{3,10}\.? \d{1,2},? \d{4}\b",
]
_AMOUNT = re.compile(r"(?<![\w.,])-?\d{1,3}(?:[.,\s]\d{3})*[.,]\d{2}(?!\d|[.,]\d)")
_INTEGER = re.compile(r"(?<![\w.,])\d+(?![\w.,]\d)")
_ID = re.compile(r"\b(?=[A-Za-z0-9/-]*\d)[A-Za-z0-9][A-Za-z0-9/-]{3,}\b")


def null_all(task: dict) -> dict:
    out: dict = {}
    for ptr, node in iter_fields(task["schema"]):
        pointer_set(out, ptr, [] if base_type(node) == "array" else None)
    return {"task_id": task["task_id"], "parse_status": "ok", "parsed": out}


def _first_date(text: str, order: str | None):
    hits = []
    for rx in _DATE_PATTERNS:
        for m in re.finditer(rx, text):
            d = parse_date(m.group(0), order)
            if d:
                hits.append((m.start(), d[0]))
    return min(hits)[1] if hits else None


def first_candidate(task: dict, text: str) -> dict:
    locale = task.get("locale") or {}
    out: dict = {}
    first_date = _first_date(text, locale.get("date_order"))
    am = _AMOUNT.search(text)
    first_amount = parse_number(am.group(0), locale.get("decimal")) if am else None
    im = _INTEGER.search(text)
    first_int = int(im.group(0)) if im else None
    idm = _ID.search(text)
    first_id = idm.group(0) if idm else None
    for ptr, node in iter_fields(task["schema"]):
        rec = task["fields"][ptr]
        kind = rec.get("match")
        if base_type(node) == "array":
            val = []
        elif kind == "date":
            val = first_date
        elif kind in ("amount", "number"):
            val = first_amount
        elif kind == "integer":
            val = first_int
        elif kind == "id":
            val = first_id
        else:
            val = None
        pointer_set(out, ptr, val)
    return {"task_id": task["task_id"], "parse_status": "ok", "parsed": out}
