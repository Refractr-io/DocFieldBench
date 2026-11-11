"""Build the rendered business documents: record -> HTML -> PDF -> task.

  python -m docfieldbench.build.rendered.build --out data/v1.0.0-dev

Per field: a drawn value is present once the PDF's text layer shows it (else excluded for a human check); a value the
record leaves out is absent by construction, except where leaving it out still lets a reader state it (an amount due
equal to the total, a subtotal equal to the total, a zero tax that isn't printed): those are excluded with a reason.
"""
from __future__ import annotations

import argparse
import copy
import json
import random
from collections import Counter
from pathlib import Path

from ...tasks import pointer_get, validate_task
from .. import pdf
from ..common import sha256, write_task
from ..visibility import TextIndex
from .records import FAMILIES
from .schemas import SCHEMAS
from .templates import TEMPLATES
from .vocab import LOCALE_WEIGHTS, LOCALES

SEED = 20261111
PLAN = [("invoice", "inv_letter", 5), ("invoice", "inv_band", 5), ("invoice", "inv_grid", 5),
        ("receipt", "rc_thermal", 5), ("receipt", "rc_store", 5), ("receipt", "rc_slip", 5),
        ("bank_statement", "bs_bank", 5), ("account_statement", "as_supplier", 5),
        ("delivery_note", "dn_classic", 5), ("delivery_note", "dn_warehouse", 5),
        ("payslip", "ps_twocol", 5), ("payslip", "ps_list", 5)]
DROP_COLUMNS = {"rc_store": {"/line_items": ["unit_price"]}}          # columns a template doesn't print
SIGN_EITHER = {"ps_list": {"/deductions": ["amount"]}}               # printed with a minus there, positive elsewhere
NOT_DRAWN = {"check": "not drawn: the rendering record has no value for this field"}


def unreadable_absence(fam: str, ptr: str, rec: dict) -> str | None:
    """A reason when a field that isn't drawn can still be stated from the document, so it can't be called absent."""
    if fam == "invoice" and ptr == "/amount_due":
        return "no amount due is printed; with nothing prepaid it equals the total"
    if fam == "invoice" and ptr == "/tax_total":
        return "no tax line is printed; a zero tax is implied, not stated"
    if fam == "receipt" and ptr == "/subtotal":
        return "no subtotal is printed; whether it equals the total is arguable"
    if fam == "receipt" and ptr == "/tax_total":
        return "no tax line is printed; a zero tax is implied, not stated"
    return None


def field_records(fam: str, tn: str, rec: dict, idx: TextIndex, schema: dict) -> dict:
    _, match, arrays = SCHEMAS[fam]
    fields = {}
    nif = fam == "invoice" and rec["seller"].get("nif_only")
    for ptr, kind in match.items():
        base = {"match": kind, "provenance": "rendering_record"}
        value = pointer_get(rec, ptr)
        if nif and ptr == "/seller/vat_id":
            fields[ptr] = {"status": "excluded", "value": None, **base,
                           "reason": "only the Spanish NIF is printed; whether it is the VAT number is ambiguous"}
            continue
        if nif and ptr == "/seller/tax_number":
            value = rec["seller"]["vat_id"][2:]
        if value is None:
            why = unreadable_absence(fam, ptr, rec)
            fields[ptr] = ({"status": "excluded", "value": None, **base, "reason": why} if why else
                           {"status": "absent", "value": None, **base, "evidence": NOT_DRAWN})
        elif idx.visible(kind, value):
            fields[ptr] = {"status": "present", "value": value, **base, "evidence": idx.evidence(kind, value)}
            acc = []
            region = (pointer_get(rec, ptr.rsplit("/", 1)[0]) or {}).get("region") if ptr.count("/") == 2 else None
            if region and ptr.endswith("/city"):
                acc.append(f"{value}, {region}")                 # the address prints "Austin, TX 78701"
            if region and ptr.endswith("/postcode"):
                acc.append(f"{region} {value}")
            if kind == "amount" and value and idx.printed_negative(value):
                acc.append(-value)                               # printed as a deduction: either sign
            if acc:
                fields[ptr]["accept"] = acc
        else:
            fields[ptr] = {"status": "excluded", "value": None, **base,
                           "reason": "drawn but not found in the text layer; needs a human check"}
    for ptr, cols in arrays.items():
        rows = pointer_get(rec, ptr) or []
        drop = list(DROP_COLUMNS.get(tn, {}).get(ptr, []))
        drop += [c for c, k in cols.items() if c not in drop and any(not idx.visible(k, r[c]) for r in rows)]
        keep = {c: k for c, k in cols.items() if c not in drop}
        node = schema["properties"][ptr.strip("/")]["items"]
        for c in drop:
            del node["properties"][c]
            node["required"].remove(c)
        base = {"match": "array_objects", "provenance": "rendering_record", "item_match": keep}
        if not rows:
            fields[ptr] = {"status": "absent", "value": None, **base, "evidence": NOT_DRAWN}
        elif "description" not in keep and "article_number" not in keep:
            fields[ptr] = {"status": "excluded", "value": None, **base, "item_match": dict(cols),
                           "reason": "rows not verifiable in the text layer"}
            for c in drop:                                  # keep the schema whole for an excluded array
                node["properties"][c] = SCHEMAS[fam][0]["properties"][ptr.strip("/")]["items"]["properties"][c]
                node["required"].append(c)
        else:
            fields[ptr] = {"status": "present", "value": [{c: r[c] for c in keep} for r in rows], **base}
            se = [c for c in SIGN_EITHER.get(tn, {}).get(ptr, []) if c in keep]
            if se:
                fields[ptr]["item_sign_either"] = se
    return fields


def build_one(fam: str, tn: str, i: int, out: Path, tmp: Path):
    import os

    import weasyprint
    os.environ["SOURCE_DATE_EPOCH"] = "1793404800"        # fontTools stamps embedded fonts; pinned for identical PDFs
    rng = random.Random(f"{SEED}-{tn}-{i}")
    loc = rng.choices(list(LOCALE_WEIGHTS), weights=list(LOCALE_WEIGHTS.values()))[0]
    rec, dec = FAMILIES[fam](rng, loc)
    html = TEMPLATES[fam][tn](rec, dec, loc, rng)
    tid = f"rendered-{fam.replace('_', '-')}-{tn.split('_', 1)[1]}-{i:02d}"
    f = tmp / f"{tid}.pdf"
    weasyprint.HTML(string=html).write_pdf(f)
    idx = TextIndex(pdf.page_texts(f))
    schema = copy.deepcopy(SCHEMAS[fam][0])
    fields = field_records(fam, tn, rec, idx, schema)
    c = LOCALES[loc]
    task = {"task_id": tid, "doc_id": tid, "track": "business", "family": fam, "source": "docfieldbench-rendered",
            "source_ref": {"generator": "docfieldbench.build.rendered", "template": tn, "seed": f"{SEED}-{tn}-{i}"},
            "license": "CC-BY-4.0", "published": None, "language": c["lang"],
            "locale": {"date_order": c["date_order"], "decimal": c["decimal"], "locale": loc},
            "document": {"path": f"docs/{tid}.pdf", "media_type": "application/pdf", "pages": pdf.page_count(f),
                         "condition": "born_digital"},
            "variant_of": None, "layout_family": f"rendered/{tn}", "doc_type": fam, "schema": schema, "fields": fields}
    errs = validate_task(task)
    if errs:
        raise SystemExit(f"{tid}: {errs[:3]}")
    write_task(out, task, f)
    return task, sha256(f)


def main(argv=None) -> int:
    import tempfile
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    tasks, manifest = [], []
    with tempfile.TemporaryDirectory() as tmp:
        for fam, tn, n in PLAN:
            for i in range(n):
                t, h = build_one(fam, tn, i, a.out, Path(tmp))
                tasks.append(t)
                manifest.append({"task_id": t["task_id"], "template": tn, "seed": t["source_ref"]["seed"],
                                 "sha256": h})
    (a.out / "sources").mkdir(parents=True, exist_ok=True)
    (a.out / "sources" / "rendered.json").write_text(json.dumps(
        {"source": "docfieldbench-rendered", "license": "CC-BY-4.0", "seed": SEED, "documents": manifest},
        indent=1) + "\n")
    st = Counter(r["status"] for t in tasks for r in t["fields"].values())
    print(f"rendered: {len(tasks)} tasks; fields {dict(st)}")
    print("locales:", dict(Counter(t["locale"]["locale"] for t in tasks)))
    for t in tasks:
        ex = [p for p, r in t["fields"].items() if r["status"] == "excluded" and "text layer" in r.get("reason", "")]
        if ex:
            print(f"  {t['task_id']}: not visible {ex}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
