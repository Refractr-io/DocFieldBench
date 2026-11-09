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


def write_task(out: Path, task: dict, doc_src: Path) -> None:
    """Write tasks/<task_id>.json and copy the document to the path the task names."""
    task = {"canary": CANARY, **task}
    dst = out / task["document"]["path"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(doc_src, dst)
    tdir = out / "tasks"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / f"{task['task_id']}.json").write_text(json.dumps(task, indent=1, ensure_ascii=False) + "\n")
