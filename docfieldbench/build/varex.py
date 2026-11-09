"""VAREX (huggingface.co/datasets/ibm-research/VAREX, CDLA-Permissive-2.0): US government forms filled
programmatically; the fill is the gold, so every gold value is printed by construction.

Input: prepared cases (one JSON per form: `template_structure` with the absent fields already added and verified by a
string search of the form's text, `extracted_data` as gold, `metadata.injected_absent`) and the dataset's parquet
files for the form images. Absent fields are either injected-and-verified or left empty by the fill (absent by
construction). Printed dates are month-first (US forms) and become ISO.

  python -m docfieldbench.build.varex --cases DIR --parquet DIR --out data/v1.0.0-dev
"""
from __future__ import annotations

import argparse
import ast
import json
from collections import Counter
from pathlib import Path

from ..normalize import is_nullish
from ..tasks import validate_task
from .common import write_bytes_task
from .convert import iso_date, kind_for, leaves, number_or_none, template_to_schema


def _lit(v):
    return ast.literal_eval(v) if isinstance(v, str) else v


def _cell(kind: str, v):
    if kind == "date":
        return iso_date(v, "MDY")
    if kind in ("amount", "number", "integer"):
        return number_or_none(v)
    return None if is_nullish(v) else v


def build_task(case: dict, doc_id: str, image: bytes) -> dict | None:
    tmpl, gold, meta = _lit(case["template_structure"]), _lit(case["extracted_data"]), _lit(case["metadata"])
    injected = {"/" + a["path"].replace(".", "/") for a in meta.get("injected_absent", [])}
    fields = {}
    for ptr, key, ph, g in leaves(tmpl, gold):
        if isinstance(ph, list):
            item = ph[0] if ph else "__str__"
            rows = g if isinstance(g, list) else []
            if isinstance(item, dict):
                sample = {k: next((r.get(k) for r in rows if isinstance(r, dict) and r.get(k) is not None), None)
                          for k in item}
                im = {k: kind_for(k, item[k], sample[k]) for k in item}
                rows = [{k: _cell(im[k], r.get(k)) for k in item} for r in rows if isinstance(r, dict)]
                rec = {"match": "array_objects", "item_match": im}
            else:
                k = kind_for(key, item, rows[0] if rows else None)
                rows = [c for c in (_cell(k, r) for r in rows) if c is not None]
                rec = {"match": "array_scalars", "item_match": k}
            fields[ptr] = ({"status": "present", "value": rows} if rows else {"status": "absent", "value": None}) \
                | rec | {"provenance": "programmatic_fill"}
            continue
        kind = kind_for(key, ph, g)
        if is_nullish(g):
            fields[ptr] = {"status": "absent", "value": None, "match": kind,
                           "provenance": "injected_absent" if ptr in injected else "programmatic_fill"}
            continue
        v = _cell(kind, g)
        if v is None:
            fields[ptr] = {"status": "excluded", "value": None, "match": kind, "provenance": "programmatic_fill",
                           "reason": f"gold {g!r} not readable as {kind}"}
        else:
            fields[ptr] = {"status": "present", "value": v, "match": kind, "provenance": "programmatic_fill"}
    media = "image/png" if image[:4] == b"\x89PNG" else "image/jpeg"
    tid = f"varex-{doc_id}"
    return {
        "task_id": tid, "doc_id": tid, "track": "forms", "family": "us_government_form",
        "source": "varex", "source_ref": {"dataset": "huggingface.co/datasets/ibm-research/VAREX", "doc_id": doc_id},
        "license": "CDLA-Permissive-2.0", "published": None, "language": "en",
        "locale": {"date_order": "MDY", "decimal": "."},
        "document": {"path": f"docs/{tid}.{'png' if media == 'image/png' else 'jpg'}", "media_type": media,
                     "pages": 1, "condition": "born_digital"},
        "variant_of": None, "schema": template_to_schema(tmpl), "fields": fields,
    }


def main(argv=None) -> int:
    import pyarrow.parquet as pq

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cases", type=Path, required=True, help="directory of prepared VAREX case files")
    ap.add_argument("--parquet", type=Path, required=True, help="directory of the dataset's parquet files")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    # case files are named varex_<doc_id>_<split>; doc ids may themselves contain underscores
    cases = {f.stem[len("varex_"):f.stem.rfind("_")]: json.loads(f.read_text())
             for f in sorted(a.cases.glob("varex_*.json"))}
    images = {}
    for f in sorted(a.parquet.glob("*.parquet")):
        t = pq.read_table(f, columns=["doc_id", "image"])
        for doc_id, img in zip(t.column("doc_id").to_pylist(), t.column("image").to_pylist(), strict=True):
            if doc_id in cases:
                images[doc_id] = img["bytes"]
    made, skipped = [], Counter()
    for doc_id in sorted(cases):
        if doc_id not in images:
            skipped["no image"] += 1
            continue
        t = build_task(cases[doc_id], doc_id, images[doc_id])
        errs = validate_task(t)
        if errs:
            skipped[f"invalid: {errs[0][:60]}"] += 1
            continue
        write_bytes_task(a.out, t, images[doc_id])
        made.append(t)
    st = Counter(r["status"] for t in made for r in t["fields"].values())
    print(f"varex: {len(made)} tasks; skipped {dict(skipped)}; fields {dict(st)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
