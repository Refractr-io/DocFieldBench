"""Bring your own documents: turn a folder of documents and one schema into DocFieldBench tasks.

  docfieldbench init DOCS_DIR --schema SCHEMA.json --out MY_TASKS [--track business] [--family invoice]
      One task per document (PDF, PNG, JPEG, HTML, TXT), with the schema and a gold stub per field. Fill each stub's
      `value` (or set `status` to "absent" with an `evidence` note, or "excluded" with a `reason`), then:
  docfieldbench validate MY_TASKS
  docfieldbench inject-absent MY_TASKS --fields FIELDS.json [--per-doc 1] [--seed S]
      Adds fields your documents provably don't state. FIELDS.json maps a field name to its type, match kind and the
      labels that would print it: {"po_number": {"type": "string", "match": "id", "labels": ["PO", "purchase order"]}}.
      A field is added to a document as absent only when none of its labels appears in the document's text (PDF text
      layer, HTML or text); documents without a text layer are skipped. Added at a seeded position in the schema.
"""
from __future__ import annotations

import json
import random
import re
import shutil
from pathlib import Path

from .matchers import KINDS
from .schema import base_type, check_schema, item_properties, iter_fields
from .tasks import MEDIA_TYPES

EXT = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
       ".html": "text/html", ".htm": "text/html", ".txt": "text/plain"}
DEFAULT_KIND = {"number": "amount", "integer": "integer", "boolean": "boolean", "string": "short_text"}


def _kind(node: dict) -> str:
    return "date" if node.get("format") == "date" else DEFAULT_KIND[base_type(node)]


def stub_fields(schema: dict) -> dict:
    fields = {}
    for p, node in iter_fields(schema):
        if base_type(node) == "array":
            props = item_properties(node)
            rec = {"status": "present", "value": None, "match": "array_objects" if props else "array_scalars",
                   "item_match": {k: _kind(v) for k, v in props.items()} if props else _kind(node["items"])}
        else:
            rec = {"status": "present", "value": None, "match": _kind(node)}
        fields[p] = {**rec, "provenance": "human_label", "todo": "fill value, or mark absent/excluded"}
    return fields


def init(docs: Path, schema_path: Path, out: Path, track: str, family: str) -> int:
    schema = json.loads(schema_path.read_text())
    errs = check_schema(schema)
    if errs:
        print("schema problems:", *errs[:10], sep="\n  ")
        return 1
    (out / "tasks").mkdir(parents=True, exist_ok=True)
    (out / "docs").mkdir(exist_ok=True)
    n = 0
    for f in sorted(docs.iterdir()):
        media = EXT.get(f.suffix.lower())
        if media not in MEDIA_TYPES:
            continue
        tid = re.sub(r"[^a-z0-9]+", "-", f.stem.lower()).strip("-")
        shutil.copyfile(f, out / "docs" / f"{tid}{f.suffix.lower()}")
        task = {"task_id": tid, "doc_id": tid, "track": track, "family": family, "source": "byo",
                "license": "own", "language": "en", "locale": {"date_order": "MDY", "decimal": "."},
                "document": {"path": f"docs/{tid}{f.suffix.lower()}", "media_type": media, "pages": 1,
                             "condition": "born_digital"},
                "variant_of": None, "schema": schema, "fields": stub_fields(schema)}
        (out / "tasks" / f"{tid}.json").write_text(json.dumps(task, indent=1, ensure_ascii=False) + "\n")
        n += 1
    print(f"{n} task stub(s) in {out / 'tasks'}; fill the values, set locale and pages, then validate")
    return 0


def _text(path: Path, media: str) -> str | None:
    if media in ("text/plain", "text/html"):
        return re.sub(r"<[^>]+>", " ", path.read_text(errors="replace"))
    if media == "application/pdf":
        from .readers import _pdf_text_layer
        t = "\n".join(_pdf_text_layer(path.read_bytes()))
        return t if t.strip() else None
    return None


def inject_absent(tasks_dir: Path, fields_path: Path, per_doc: int, seed: str) -> int:
    spec = json.loads(fields_path.read_text())
    for k, s in spec.items():
        if s.get("match") not in KINDS or s.get("type") not in ("string", "number", "integer", "boolean", "date"):
            print(f"{k}: needs a type (string|number|integer|boolean|date) and a match kind {KINDS}")
            return 1
    root = tasks_dir.parent
    added = skipped = 0
    for f in sorted(tasks_dir.glob("*.json")):
        t = json.loads(f.read_text())
        text = _text(root / t["document"]["path"], t["document"]["media_type"])
        if text is None:
            skipped += 1
            continue
        low = text.casefold()
        cands = [k for k, s in spec.items() if k not in t["schema"]["properties"]
                 and not any(re.search(rf"(?<!\w){re.escape(lb.casefold())}(?!\w)", low) for lb in s["labels"])]
        rng = random.Random(f"{seed}-{t['task_id']}")
        props = list(t["schema"]["properties"].items())
        for k in rng.sample(cands, min(per_doc, len(cands))):
            s = spec[k]
            node = ({"type": ["string", "null"], "format": "date"} if s["type"] == "date"
                    else {"type": [s["type"], "null"]})
            props.insert(rng.randint(0, len(props)), (k, node))
            t["fields"][f"/{k}"] = {"status": "absent", "value": None, "match": s["match"],
                                    "provenance": "inject_absent",
                                    "evidence": {"check": f"none of the labels {s['labels']} appears in the text"}}
            added += 1
        t["schema"]["properties"] = dict(props)
        t["schema"]["required"] = list(t["schema"]["properties"])
        f.write_text(json.dumps(t, indent=1, ensure_ascii=False) + "\n")
    print(f"added {added} absent field(s); {skipped} document(s) without a text layer skipped")
    return 0
