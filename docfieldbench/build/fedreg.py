"""Federal Register rules and proposed rules published 2026-11-02 to 2026-11-10 (class T), fetched from the
federalregister.gov API (public domain, no key). Gold comes from the API's metadata and the document's own
"[FR Doc. ... Filed ...]" line; the fields are built exactly like the dev-set rules (prepared.fedreg_fields).
The document is the rule's HTML edition from federalregister.gov: the printed PDF pages also carry the neighbouring
documents, the HTML holds this document alone. Site navigation and the "Document Headings" help text are removed.

  python -m docfieldbench.build.fedreg --cache CACHE_DIR --out data/v1.0.0-new
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import re
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from ..tasks import validate_task
from .common import write_bytes_task
from .edgar import html_text
from .prepared import fedreg_task
from .visibility import TextIndex

API = "https://www.federalregister.gov/api/v1/documents.json"
FIELDS = ["document_number", "comments_close_on", "publication_date", "body_html_url", "page_length", "docket_ids",
          "regulation_id_numbers", "agencies", "type", "title"]
SEED, N, MAX_PER_AGENCY = 20261111, 10, 2
DASH = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-"})


def get(url: str, params=None) -> bytes:
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"User-Agent": "DocFieldBench-build/0.1"})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except OSError:
            time.sleep(2 * (i + 1))
    raise OSError(f"failed: {url}")


def gold(meta: dict, text: str) -> dict:
    t = text.translate(DASH)
    g = {"publication_date": meta["publication_date"], "comments_due_date": meta.get("comments_close_on"),
         "fr_doc_number": meta["document_number"]}
    m = re.findall(r"\[FR Doc\. *[\d-]+ *Filed *(\d{1,2})-(\d{1,2})-(\d{2});", t)
    if len(m) == 1:
        mo, d, y = (int(x) for x in m[0])
        g["filed_date"] = dt.date(2000 + y, mo, d).isoformat()
    for d_id in meta.get("docket_ids") or []:
        d_id = d_id.translate(DASH).strip()
        if re.match(r"(?i)docket (no\.|number)", d_id):
            g.setdefault("docket_number", re.sub(r"(?i)^docket (no\.|number):?\s*", "", d_id))
        elif re.match(r"^[A-Z]{2,6}-[A-Z0-9]+-[A-Z0-9-]*\d{4}-\d+", d_id):
            g.setdefault("docket_number", d_id)
    rins = meta.get("regulation_id_numbers") or []
    if len(rins) == 1:
        g["rin"] = rins[0]
    ag = meta.get("agencies") or []
    if ag:
        g["agency"] = ag[-1].get("raw_name") or ag[-1].get("name")
        if len(ag) > 1 and ag[0].get("raw_name"):
            g["department"] = ag[0]["raw_name"]
    return {k: v for k, v in g.items() if v}


def clean_html(body: str) -> str:
    """The rule's body as a standalone page: the site's heading help text, links and scripts removed."""
    body = re.sub(r'(?is)<div[^>]*class="[^"]*(?:document-headings|unprinted-element|tooltip)[^"]*".*?</div>\s*</div>',
                  "", body)
    help_text = r"(?is)Document Headings\s*</h\d>.*?Document Drafting Handbook[^<]*(?:<[^>]+>\s*)*?for more details\.?"
    body = re.sub(help_text, "", body)
    body = re.sub(r"(?is)<script[^>]*>.*?</script>", "", body)
    body = re.sub(r"(?is)<a\b[^>]*>(.*?)</a>", r"\1", body)
    body = re.sub(r"(?i)Back to Citation", "", body)
    return "<!doctype html><html><head><meta charset='utf-8'></head><body>" + body + "</body></html>"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cache", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    a.cache.mkdir(parents=True, exist_ok=True)
    metas = []
    for page in (1, 2, 3, 4, 5):
        params = [("per_page", 200), ("page", page), ("order", "oldest"), ("conditions[type][]", "RULE"),
                  ("conditions[type][]", "PRORULE"), ("conditions[publication_date][gte]", "2026-11-02"),
                  ("conditions[publication_date][lte]", "2026-11-10")] + [("fields[]", f) for f in FIELDS]
        res = json.loads(get(API, params))
        metas += res.get("results") or []
        if not res.get("next_page_url"):
            break
    rng = random.Random(SEED)
    metas = [m for m in metas if m.get("page_length") and m["page_length"] <= 10]   # the printed length
    rng.shuffle(metas)
    tasks, skipped, per_agency = [], Counter(), Counter()
    for meta in metas:
        if len(tasks) >= N:
            break
        agency = ((meta.get("agencies") or [{}])[-1]).get("slug", "?")
        if per_agency[agency] >= MAX_PER_AGENCY:
            continue
        f = a.cache / f"{meta['document_number']}.html"
        if not f.exists():
            f.write_bytes(get(meta["body_html_url"]))
            time.sleep(0.5)
        page = clean_html(f.read_text())
        idx = TextIndex(html_text(page))
        text = idx.text
        if text.translate(DASH).count("[FR Doc.") != 1:
            skipped["no single FR Doc line"] += 1
            continue
        g = gold(meta, text)
        alt = {}
        m = re.search(r"AGENCY:\s*(.+?)\.\s*ACTION:", re.sub(r"\s+", " ", text))
        if m and "agency" in g:
            alt["agency"] = [m.group(1).strip()]
        task, _ = fedreg_task({"id": f"fedreg_{meta['document_number']}", "file": f.name, "gold": g, "alt": alt},
                              a.cache, idx=idx, media="text/html")
        present = [p for p, r in task["fields"].items() if r["status"] == "present"]
        if len(present) < 5:
            skipped["too few verifiable fields"] += 1
            continue
        task["source_ref"] = {"url": meta["body_html_url"], "document_number": meta["document_number"],
                              "type": meta["type"]}
        task["layout_family"] = "federal-register"
        errs = validate_task(task)
        if errs:
            raise SystemExit(f"{task['task_id']}: {errs[:3]}")
        write_bytes_task(a.out, task, page.encode("utf-8"))
        tasks.append(task)
        per_agency[agency] += 1
    (a.out / "sources").mkdir(parents=True, exist_ok=True)
    (a.out / "sources" / "fedreg_nov.json").write_text(json.dumps(
        {"source": "federal-register", "window": ["2026-11-02", "2026-11-10"], "seed": SEED,
         "documents": [{"task_id": t["task_id"], **t["source_ref"], "published": t["published"]} for t in tasks]},
        indent=1) + "\n")
    st = Counter((p, r["status"]) for t in tasks for p, r in t["fields"].items())
    print(f"fedreg: {len(tasks)} tasks from {len(metas)} candidates; skipped {dict(skipped)}")
    print("agencies:", dict(per_agency))
    for p in sorted({p for p, _ in st}):
        n = {k: st[(p, k)] for k in ("present", "absent", "excluded")}
        print(f"  {p:22} present={n['present']:2d} absent={n['absent']:2d} excluded={n['excluded']:2d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
