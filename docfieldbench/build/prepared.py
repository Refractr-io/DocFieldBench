"""Sources that arrive as prepared cases: a JSONL of {id, form, file, lang, template, gold, alt?, cond?} plus the
documents themselves.

- fedreg        Federal Register rules (public domain). Gold from the federalregister.gov API and the document's own
                "[FR Doc. ... Filed ...]" line. A gold null is absent only when the absence check proves it.
- cap           Court opinions from the Caselaw Access Project (CC0). The document is the opinion text itself.
- invoice2data  The invoice2data test invoices (MIT), gold read by hand from each document. A hand-gold null means
                the document does not state that value (human-verified absent); `cond` values are printed inside
                images (a logo) and count as present.

  python -m docfieldbench.build.prepared fedreg --cases FILE.jsonl --docs DIR --out data/v1.0.0-dev
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter
from pathlib import Path

from ..normalize import is_nullish
from ..tasks import validate_task
from . import pdf
from .common import decimal_mark, slug, write_bytes_task, write_task
from .convert import iso_date, kind_for, number_or_none, template_to_schema
from .families import INVOICE_MATCH
from .visibility import TextIndex

FEDREG_FIELDS = {"department": ("__str__", "short_text"), "agency": ("__str__", "short_text"),
                 "publication_date": ("__date__", "date"), "docket_number": ("__str__", "id"),
                 "comments_due_date": ("__date__", "date"), "rin": ("__str__", "id"),
                 "fr_doc_number": ("__str__", "id"), "filed_date": ("__date__", "date")}
FEDREG_LABELS = {"department": ["department of"],
                 "comments_due_date": ["comments must be received", "submit comments", "comments are due",
                                       "comments on or before", "send comments", "comment period", "comments by"],
                 "rin": ["rin", "regulation identifier number"],
                 "docket_number": ["docket no", "docket number", "docket id"]}
CAP_FIELDS = {"appellant": ("__str__", "name"), "appellee": ("__str__", "name"),
              "opinion_author": ("__str__", "name"), "decision_date": ("__date__", "date"),
              "docket_number": ("__str__", "id")}
# attorneys per side: a list of person names (firms and offices are not attorneys)
CAP_ATTORNEYS = {"appellant_attorneys": "appellant_counsel", "appellee_attorneys": "appellee_counsel"}
_NOT_PERSON = re.compile(r"&|\b(office|law|llp|llc|pc|p\.c|inc|group|firm|associates|attorney|general|defender|"
                         r"department|state|county|city|district|counsel|bureau|division|service|services)\b",
                         re.IGNORECASE)
_ROLE = re.compile(r"\b(deceased|director|administrator|executor|executrix|etc|indiv|individually|behalf|"
                   r"similarly|guardian|trustee|minor|as next friend)\b", re.IGNORECASE)


def _is_person(s: str) -> bool:
    toks = s.split()
    return 2 <= len(toks) <= 5 and not _NOT_PERSON.search(s) and sum(t[:1].isupper() for t in toks) >= 2


def _party_aliases(gold: str) -> list[str]:
    """The name parts of a party designation: 'LARRY G. TRENT, Director, Department of State Police, et al.' ->
    'LARRY G. TRENT'; 'Estate of X, Deceased. MAUREEN STANCIU, as Administrator, etc.' -> both names."""
    parts = [p.strip(" .") for p in re.split(r",\s*|\.\s+(?=[A-Z])", gold) if p.strip(" .")]
    out = [p for p in parts if not _ROLE.search(p) and not re.fullmatch(r"(?i)et\.? a[lt]\.?|d/b/a.*", p)
           and len(p.split()) >= 2]
    return [p for p in dict.fromkeys(out) if p != gold]
I2D_MAP = {"vendor_name": "seller/name", "vendor_vat_number": "seller/vat_id", "vendor_tax_number": "seller/tax_number",
           "vendor_email": "seller/email", "vendor_gstin": "seller/gstin", "vendor_cin": "seller/cin",
           "vendor_coc_number": "seller/coc_number", "customer_name": "buyer/name",
           "customer_vat_number": "buyer/vat_id", "net_amount": "net_total", "tax_amount": "tax_total",
           "total_amount": "total_incl_tax"}


def _lit(v):
    return ast.literal_eval(v) if isinstance(v, str) else (v or {})


def _value(kind, v, order):
    if is_nullish(v):
        return None
    if kind == "date":
        return iso_date(v, order)
    if kind in ("amount", "number", "integer"):
        return number_or_none(v)
    return v


def _nest(flat: dict) -> dict:
    out: dict = {}
    for path, v in flat.items():
        parts = path.split("/")
        cur = out
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = v
    return out


def _record(kind, value, idx, alt, provenance):
    rec = {"match": kind, "provenance": provenance}
    if alt:
        rec["accept"] = list(alt)
    if idx is not None and not idx.visible(kind, value) and not any(idx.visible(kind, a) for a in alt or []):
        return {"status": "excluded", "value": None, **rec,
                "reason": "not found in the document's text; needs a human check"}
    ev = idx.evidence(kind, value) if idx is not None else None
    return {"status": "present", "value": value, **rec, **({"evidence": ev} if ev else {})}


def fedreg_fields(gold: dict, alt: dict, idx: TextIndex) -> dict:
    fields = {}
    for k, (_, kind) in FEDREG_FIELDS.items():
        v = _value(kind, gold.get(k), "MDY")
        if v is not None:
            fields[f"/{k}"] = _record(kind, v, idx, alt.get(k), "official_metadata")
            continue
        labels = FEDREG_LABELS.get(k)
        blocked = labels and (idx.has_label(labels) if kind == "short_text" else idx.label_with_value(labels, kind))
        fields[f"/{k}"] = ({"status": "excluded", "value": None, "match": kind, "provenance": "official_metadata",
                            "reason": "a label for this field is printed but the metadata has no value"} if blocked
                           else {"status": "absent", "value": None, "match": kind, "provenance": "official_metadata",
                                 "evidence": {"check": "no label followed by a value of this kind"}})
    return fields


def fedreg_task(c: dict, docs: Path, idx: TextIndex | None = None, media: str = "application/pdf") -> tuple[dict, Path]:
    """A Federal Register task. `idx` and `media` are given for a document that isn't a PDF (the HTML edition)."""
    f = docs / c["file"]
    idx = idx or TextIndex(pdf.page_texts(f))
    fields = fedreg_fields(c["gold"], c.get("alt") or {}, idx)
    gold = c["gold"]
    tid = f"fedreg-{slug(c['id'].split('_', 1)[1])}"
    ext = "pdf" if media == "application/pdf" else "html"
    task = {"task_id": tid, "doc_id": tid, "track": "records", "family": "federal_register_document",
            "source": "federal-register", "license": "Public-Domain-US-Government",
            "published": gold.get("publication_date"),
            "language": "en", "locale": {"date_order": "MDY", "decimal": "."},
            "document": {"path": f"docs/{tid}.{ext}", "media_type": media,
                         "pages": pdf.page_count(f) if ext == "pdf" else 1, "condition": "born_digital"},
            "variant_of": None, "schema": template_to_schema({k: ph for k, (ph, _) in FEDREG_FIELDS.items()}),
            "fields": fields}
    return task, f


def cap_task(c: dict) -> tuple[dict, bytes]:
    text = c["text"]
    idx = TextIndex([text])
    gold, alt = c["gold"], c.get("alt") or {}
    fields, tmpl = {}, {}
    for k, (ph, kind) in CAP_FIELDS.items():
        g = gold.get(k)
        if is_nullish(g):
            continue
        acc = list(alt.get(k) or [])
        if k in ("appellant", "appellee"):
            acc += [a for a in _party_aliases(g) if a not in acc]
        if k == "docket_number" and re.search(r"\s*cons\.?$", g):
            acc.append(re.sub(r"\s*cons\.?$", "", g))
        fields[f"/{k}"] = _record(kind, _value(kind, g, "MDY"), idx, acc, "official_metadata")
        tmpl[k] = ph
    for field, src in CAP_ATTORNEYS.items():
        names = [n for n in dict.fromkeys([gold.get(src), *(alt.get(src) or [])]) if n and _is_person(n)]
        names = [n for n in names if idx.visible("name", n)]
        if names:
            fields[f"/{field}"] = {"status": "present", "value": names, "match": "array_scalars",
                                   "item_match": "name", "provenance": "official_metadata"}
            tmpl[field] = ["__str__"]
    tid = f"cap-{slug(c['id'].split('_', 1)[1])}"
    task = {"task_id": tid, "doc_id": tid, "track": "records", "family": "court_opinion",
            "source": "caselaw-access-project", "license": "CC0-1.0",
            "published": fields.get("/decision_date", {}).get("value"),
            "language": "en", "locale": {"date_order": "MDY", "decimal": "."},
            "document": {"path": f"docs/{tid}.txt", "media_type": "text/plain", "pages": 1,
                         "condition": "born_digital"},
            "variant_of": None, "schema": template_to_schema(tmpl), "fields": fields}
    return task, text.encode()


def i2d_task(c: dict, docs: Path) -> tuple[dict, Path]:
    tmpl, gold, alt, cond = _lit(c["template"]), _lit(c["gold"]), c.get("alt") or {}, c.get("cond") or {}
    f = docs / c["file"]
    is_pdf = c["form"] == "pdf"
    idx = TextIndex(pdf.page_texts(f)) if is_pdf else None
    lang = c.get("lang") or "en"
    order = None if lang == "en" else "DMY"
    flat_tmpl, fields = {}, {}
    for k, ph in tmpl.items():
        path = I2D_MAP.get(k, k)
        ptr = "/" + path
        kind = INVOICE_MATCH.get(ptr) or kind_for(k, ph, gold.get(k))
        flat_tmpl[path] = ph
        g = gold.get(k)
        if is_nullish(g) and not is_nullish(cond.get(k)):
            g, prov = cond[k], "human (printed inside an image)"
        else:
            prov = "human"
        v = _value(kind, g, order)
        if v is None:
            fields[ptr] = {"status": "absent", "value": None, "match": kind, "provenance": "human",
                           "evidence": {"check": "read by hand: the document does not state it"}}
        else:
            rec = _record(kind, v, idx if prov == "human" else None, alt.get(k), prov)
            if rec["status"] == "excluded":           # hand-read values stand even where the text layer misses them
                rec = {"status": "present", "value": v, "match": kind, "provenance": prov,
                       **({"accept": list(alt[k])} if alt.get(k) else {})}
            fields[ptr] = rec
    base = c["id"].split("_", 1)[1]
    scan = base.endswith("_scan")
    name = base[: -len("_scan")] if scan else base
    tid = f"invoice2data-{slug(name)}" + ("-scan" if scan else "")
    ext = f.suffix.lower().lstrip(".")
    media = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}[ext]
    task = {"task_id": tid, "doc_id": tid, "track": "business", "family": "invoice", "source": "invoice2data",
            "license": "MIT", "published": None, "language": lang,
            "locale": {"date_order": order, "decimal": decimal_mark(idx.text) if idx else ","},
            "document": {"path": f"docs/{tid}.{ext}", "media_type": media,
                         "pages": pdf.page_count(f) if is_pdf else 1, "condition": "scan" if scan else "born_digital"},
            "variant_of": f"invoice2data-{slug(name)}" if scan else None,
            "schema": template_to_schema(_nest(flat_tmpl)), "fields": fields}
    return task, f


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("source", choices=["fedreg", "cap", "invoice2data"])
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--docs", type=Path, help="directory the cases' `file` paths are relative to")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    cases = [json.loads(line) for line in a.cases.read_text().splitlines() if line.strip()]
    made, skipped = [], Counter()
    for c in cases:
        if a.source == "fedreg":
            task, src = fedreg_task(c, a.docs)
        elif a.source == "cap":
            task, src = cap_task(c)
        else:
            task, src = i2d_task(c, a.docs)
        if task["document"]["pages"] > 10:
            skipped["over 10 pages"] += 1
            continue
        errs = validate_task(task)
        if errs:
            skipped[f"invalid: {errs[0][:70]}"] += 1
            continue
        (write_bytes_task if isinstance(src, bytes) else write_task)(a.out, task, src)
        made.append(task)
    st = Counter(r["status"] for t in made for r in t["fields"].values())
    print(f"{a.source}: {len(made)} tasks; skipped {dict(skipped)}; fields {dict(st)}")
    for k, n in sorted(Counter((p, r["status"]) for t in made for p, r in t["fields"].items()
                               if r["status"] != "present").items()):
        print(f"  {k[0]:28} {k[1]:9} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
