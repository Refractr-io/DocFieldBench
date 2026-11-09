"""ZUGFeRD corpus (github.com/ZUGFeRD/corpus, Apache-2.0): e-invoice PDFs whose embedded CII XML gives the gold.

Selection, without looking at any system's output:
- one PDF per invoice (seller, buyer, number); a real layout before an XML visualisation (a stylesheet rendering of the
  XML), and a seeded choice among visualisations;
- at most MAX_PER_FAMILY invoices per layout family (a producer's template, or one visualisation stylesheet);
- the other renderings of a chosen invoice are recorded as layout pairs (same gold, different layout).
Per field: an XML value printed in the document is present; an XML value not found in the text layer is excluded;
a value missing from the XML is absent only when the absence check proves it (families.py), else excluded.

  python -m docfieldbench.build.zugferd --src CORPUS_CLONE --commit SHA --out data/v1.0.0-dev
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from ..tasks import validate_task
from . import pdf
from .cii import parse_cii
from .common import decimal_mark, language, sha256, slug, write_task
from .families import INVOICE_LABELS, INVOICE_MATCH, INVOICE_SCHEMA, LINE_ITEM_MATCH, ibans, vat_numbers
from .visibility import TextIndex

SEED = 20261109
MAX_PER_FAMILY = 6
MIN_PRESENT = 6
VIZ = [("viz-ferd", r"Beispiel-Rechnungen für ZUGFeRD"),
       ("viz-intarsys", r"Stylesheet zur Lesbarmachung"),
       ("viz-symtrax", r"Stylesheet Lesbarmachung")]
MERGE = {"ZUGFeRDv1/correct/Mustangproject": "mustang", "ZUGFeRDv2/correct/Mustangproject": "mustang",
         "ZUGFeRDv2/correct/PHP_@gpFacturX": "mustang"}
CREDIT_NOTE = {"381", "396", "532"}


def layout_family(rel_dir: str, first_page: str) -> tuple[str, bool]:
    for name, rx in VIZ:
        if re.search(rx, first_page[:400]):
            return name, True
    return MERGE.get(rel_dir, rel_dir), False


def _value(rec: dict, ptr: str):
    cur = rec
    for t in ptr.strip("/").split("/"):
        cur = (cur or {}).get(t)
    return cur


def _compact(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def scalar_record(ptr: str, value, idx: TextIndex, rec: dict, credit_note: bool) -> dict:
    kind = INVOICE_MATCH[ptr]
    labels = INVOICE_LABELS.get(ptr)
    base = {"match": kind, "provenance": "source_markup"}
    if ptr == "/prepaid_amount" and value == 0 and not idx.label_with_value(labels, "amount"):
        value = None                                     # an XML zero with no prepayment printed: nothing to extract
    if value is not None:
        if idx.visible(kind, value):
            out = {"status": "present", "value": value, **base, "evidence": idx.evidence(kind, value)}
            if kind == "amount" and value and (credit_note or idx.printed_negative(value)):
                out["accept"] = [-value]                 # printed as a deduction or on a credit note: either sign
            return out
        return {"status": "excluded", "value": None, **base,
                "reason": "in the embedded XML but not found in the text layer; needs a human check"}
    if ptr.endswith("/vat_id"):
        known = {_compact(v) for v in (rec["seller"].get("vat_id"), rec["buyer"].get("vat_id")) if v}
        if not vat_numbers(idx.text) - known:
            return {"status": "absent", "value": None, **base, "evidence": {"check": "no other VAT number printed"}}
        return {"status": "excluded", "value": None, **base,
                "reason": "a VAT number the XML doesn't assign is printed; needs a human check"}
    if ptr == "/seller/tax_number" and re.search(r"\b(siret|siren)\b", idx.text, re.IGNORECASE):
        return {"status": "excluded", "value": None, **base,
                "reason": "a SIRET/SIREN is printed; whether that counts as a tax number is ambiguous"}
    if ptr == "/iban":
        if not ibans(idx.text):
            return {"status": "absent", "value": None, **base, "evidence": {"check": "no valid IBAN printed"}}
        return {"status": "excluded", "value": None, **base,
                "reason": "an IBAN is printed but the XML has none; needs a human check"}
    if labels:
        if not idx.label_with_value(labels, kind):
            return {"status": "absent", "value": None, **base,
                    "evidence": {"check": "no label followed by a value of this kind"}}
        return {"status": "excluded", "value": None, **base,
                "reason": "a label with a value after it is printed but the XML has no value; needs a human check"}
    return {"status": "excluded", "value": None, **base,
            "reason": "not in the embedded XML, and absence can't be verified"}


def line_items_record(rows: list[dict], idx: TextIndex) -> tuple[dict, list[str]]:
    """(field record, item columns dropped from this document's schema)."""
    base = {"match": "array_objects", "provenance": "source_markup"}
    if not rows:
        if not idx.has_label(INVOICE_LABELS["/line_items"]):
            return {"status": "absent", "value": None, "item_match": dict(LINE_ITEM_MATCH), **base,
                    "evidence": {"check": "no line-item labels printed"}}, []
        return {"status": "excluded", "value": None, "item_match": dict(LINE_ITEM_MATCH), **base,
                "reason": "no rows in the XML but line-item labels are printed"}, []
    drop = [c for c, k in LINE_ITEM_MATCH.items()
            if any(r.get(c) is None or not idx.visible(k, r[c]) for r in rows)]
    keep = [c for c in LINE_ITEM_MATCH if c not in drop]
    if "description" not in keep or len(keep) < 2:
        return {"status": "excluded", "value": None, "item_match": dict(LINE_ITEM_MATCH), **base,
                "reason": "line items not verifiable in the text layer"}, []
    value = [{c: r[c] for c in keep} for r in rows]
    out = {"status": "present", "value": value, "item_match": {c: LINE_ITEM_MATCH[c] for c in keep}, **base}
    signed = [c for c in keep if LINE_ITEM_MATCH[c] in ("amount", "number")
              and any(idx.printed_negative(r[c]) for r in rows)]
    if signed:
        out["item_sign_either"] = signed                 # printed negative somewhere: either sign is accepted
    return out, drop


def build_task(f: Path, rel: str, rec: dict, pages: list[str], family: str, viz: bool, commit: str) -> dict | None:
    idx = TextIndex(pages)
    credit = (rec.get("type_code") or "") in CREDIT_NOTE
    fields = {ptr: scalar_record(ptr, _value(rec, ptr), idx, rec, credit) for ptr in INVOICE_MATCH}
    li, dropped = line_items_record(rec["line_items"], idx)
    fields["/line_items"] = li
    schema = copy.deepcopy(INVOICE_SCHEMA)
    items = schema["properties"]["line_items"]["items"]
    for c in dropped:
        del items["properties"][c]
        items["required"].remove(c)
    present = sum(r["status"] == "present" for r in fields.values())
    if present < MIN_PRESENT or any(fields[p]["status"] != "present" for p in ("/seller/name", "/buyer/name",
                                                                                 "/total_incl_tax")):
        return None
    tid = "zugferd-" + re.sub(r"^zugferd-", "", slug(Path(rel).stem))
    return {
        "task_id": tid, "doc_id": tid, "track": "business", "family": "invoice",
        "source": "zugferd-corpus",
        "source_ref": {"repository": "https://github.com/ZUGFeRD/corpus", "commit": commit, "path": rel},
        "license": "Apache-2.0", "published": None,
        "language": language(idx.text), "locale": {"date_order": "DMY", "decimal": decimal_mark(idx.text)},
        "document": {"path": f"docs/{tid}.pdf", "media_type": "application/pdf", "pages": pdf.page_count(f),
                     "condition": "born_digital"},
        "variant_of": None, "layout_family": family, "xml_visualisation": viz,
        "doc_type": "credit_note" if credit else "invoice",
        "schema": schema, "fields": fields,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", type=Path, required=True, help="a clone of github.com/ZUGFeRD/corpus")
    ap.add_argument("--commit", required=True, help="the clone's commit (recorded per task)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    rng = random.Random(SEED)

    by_invoice = defaultdict(list)
    skipped = Counter()
    for f in sorted(p for p in a.src.rglob("*") if p.suffix.lower() == ".pdf" and "/fail/" not in str(p)):
        rel = str(f.relative_to(a.src))
        xml = next((b for n, b in pdf.attachments(f) if n.lower().endswith(".xml")), None)
        if xml is None:
            skipped["no embedded XML"] += 1
            continue
        try:
            rec = parse_cii(xml)
        except Exception as e:  # UBL and broken XML are other sources' business
            skipped[f"not parsed: {str(e)[:40]}"] += 1
            continue
        if pdf.page_count(f) > 10:
            skipped["over 10 pages"] += 1
            continue
        pages = pdf.page_texts(f)
        family, viz = layout_family(str(Path(rel).parent), pages[0] if pages else "")
        key = (rec["seller"].get("name"), rec["buyer"].get("name"), rec["invoice_number"])
        by_invoice[key].append({"f": f, "rel": rel, "rec": rec, "pages": pages, "family": family, "viz": viz})

    chosen = []
    for key in sorted(by_invoice, key=str):
        cands = sorted(by_invoice[key], key=lambda c: c["rel"])
        real = [c for c in cands if not c["viz"]]
        pick = real[0] if real else rng.choice(cands)
        pick["pairs"] = [c["rel"] for c in cands if c is not pick and c["family"] != pick["family"]]
        chosen.append(pick)
    by_family = defaultdict(list)
    for c in chosen:
        by_family[c["family"]].append(c)

    tasks, manifest = [], []
    for fam in sorted(by_family):
        cands = by_family[fam]
        rng.shuffle(cands)
        kept = 0
        for c in cands:
            if kept >= MAX_PER_FAMILY:
                skipped["family cap"] += 1
                continue
            t = build_task(c["f"], c["rel"], c["rec"], c["pages"], fam, c["viz"], a.commit)
            if t is None:
                skipped["too few verifiable fields"] += 1
                continue
            errs = validate_task(t)
            if errs:
                raise SystemExit(f"{t['task_id']}: {errs[:3]}")
            write_task(a.out, t, c["f"])
            tasks.append(t)
            kept += 1
            manifest.append({"task_id": t["task_id"], "source_path": c["rel"], "sha256": sha256(c["f"]),
                             "layout_family": fam, "xml_visualisation": c["viz"], "layout_pairs": c["pairs"]})
    (a.out / "sources").mkdir(parents=True, exist_ok=True)
    (a.out / "sources" / "zugferd.json").write_text(json.dumps(
        {"source": "zugferd-corpus", "repository": "https://github.com/ZUGFeRD/corpus", "commit": a.commit,
         "license": "Apache-2.0", "documents": manifest}, indent=1) + "\n")

    st = Counter((p, r["status"]) for t in tasks for p, r in t["fields"].items())
    print(f"zugferd: {len(tasks)} tasks from {len(by_invoice)} distinct invoices; skipped {dict(skipped)}")
    print("families:", dict(Counter(t["layout_family"] for t in tasks)))
    print("languages:", dict(Counter(t["language"] for t in tasks)), "| credit notes:",
          sum(t["doc_type"] == "credit_note" for t in tasks))
    for p in [*INVOICE_MATCH, "/line_items"]:
        print(f"  {p:24} present={st[(p, 'present')]:3d} absent={st[(p, 'absent')]:3d} "
              f"excluded={st[(p, 'excluded')]:3d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
