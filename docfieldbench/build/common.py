"""Helpers shared by the source builders: ids, language and number-format detection, writing tasks and documents."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from .. import CANARY


def slug(s: str, n: int = 48) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:n].strip("-")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_LANG_WORDS = {
    "de": r"\b(rechnung|datum|betrag|steuer|kunde|lieferung|zahlbar|gesamt|menge|summe)\w*",
    "fr": r"\b(facture|montant|tva|client|échéance|total|quantité|désignation)\b",
    "nl": r"\b(factuur|bedrag|btw|klant|datum|totaal|vervaldatum|aantal)\b",
    "en": r"\b(invoice|amount|total|customer|date|due|bill|quantity|price)\b",
    "es": r"\b(factura|importe|cliente|fecha|total|cantidad|precio|iva)\b",
}


def language(text: str) -> str:
    t = text.lower()
    scores = {k: len(re.findall(rx, t)) for k, rx in _LANG_WORDS.items()}
    return max(scores, key=scores.get)


def decimal_mark(text: str) -> str:
    """',' or '.': which decimal mark the document's amounts use (two-decimal amounts counted)."""
    comma = len(re.findall(r"\d,\d{2}(?!\d)", text))
    dot = len(re.findall(r"\d\.\d{2}(?!\d)", text))
    return "," if comma > dot else "."


_NUMERIC_DATE = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})(?!\d)")


def date_order_from_evidence(fields: dict, default: str = "DMY") -> str:
    """'DMY' or 'MDY': which reading of the document's printed numeric dates gives the gold dates. A printed
    11/03/2017 whose gold is 2017-11-03 votes MDY. Ambiguous dates (day = month) and no evidence keep the default."""
    from ..normalize import parse_date
    votes = {"DMY": 0, "MDY": 0}
    for r in fields.values():
        if r.get("match") != "date" or r.get("status") != "present":
            continue
        for m in _NUMERIC_DATE.finditer((r.get("evidence") or {}).get("text") or ""):
            ok = {o for o in votes if (parse_date(m.group(0), o) or [None])[0] == r["value"]}
            if len(ok) == 1:
                votes[ok.pop()] += 1
    if votes["MDY"] > votes["DMY"]:
        return "MDY"
    if votes["DMY"] > votes["MDY"]:
        return "DMY"
    return default


def _write_json(out: Path, task: dict) -> None:
    tdir = out / "tasks"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / f"{task['task_id']}.json").write_text(
        json.dumps({"canary": CANARY, **task}, indent=1, ensure_ascii=False) + "\n")


def write_task(out: Path, task: dict, doc_src: Path) -> None:
    """Write tasks/<task_id>.json and copy the document to the path the task names."""
    dst = out / task["document"]["path"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(doc_src, dst)
    _write_json(out, task)


def write_bytes_task(out: Path, task: dict, data: bytes) -> None:
    """Like write_task, for a document that exists only as bytes (an image from a dataset file, a text body)."""
    dst = out / task["document"]["path"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)
    _write_json(out, task)
