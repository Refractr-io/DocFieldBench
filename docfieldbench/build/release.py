"""Assemble a release from built source directories: absence library, tags, gates, manifest, diversity card.

  python -m docfieldbench.build.release --src data/v1.0.0-dev data/v1.0.0-new --out data/v1.0.0-rc1

Gates (any failure stops the build): every task validates; every document is within the page cap; every task carries
the canary; no layout family holds more than MAX_PER_FAMILY documents; the PII scan finds no card numbers and no email
addresses in synthetic documents outside example.com; Rule 0 passes per track. Writes manifest.json (sha256 per file)
and DIVERSITY.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from .. import CANARY
from ..absence import inject
from ..adjudicate import _set_field
from ..tasks import MAX_PAGES, validate_task
from . import pdf, rule0
from .edgar import html_text
from .tags import tag_task
from .variants import make_variant

SEED = "20261111"
MAX_PER_FAMILY = 6
SYNTHETIC = {"docfieldbench-rendered", "irs-form-fill"}
CARD = re.compile(r"(?<![\w -])(?:4\d{3}|5[1-5]\d{2}|3[47]\d{2})[ -]?\d{4}[ -]?\d{4}[ -]?\d{3,4}(?![\w])")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")


def doc_text(path: Path, media: str) -> str:
    if media == "application/pdf":
        return "\n".join(pdf.page_texts(path))
    if media == "text/html":
        return "\n".join(html_text(path.read_text(errors="replace")))
    if media == "text/plain":
        return path.read_text(errors="replace")
    return ""                                    # images: no text layer; the PII scan relies on the source being public


def luhn(num: str) -> bool:
    d = [int(c) for c in num if c.isdigit()]
    s = sum(d[-1::-2]) + sum(sum(divmod(2 * x, 10)) for x in d[-2::-2])
    return len(d) >= 13 and s % 10 == 0


def pii_problems(task: dict, text: str) -> list[str]:
    scan = IBAN.sub(" ", text)
    out = [f"card-like number {m.group(0)}" for m in CARD.finditer(scan)
           if luhn(m.group(0)) and len(re.sub(r"\D", "", m.group(0))) in (15, 16)]
    if task["source"] in SYNTHETIC:
        out += [f"email outside example.com: {m.group(0)}" for m in EMAIL.finditer(text)
                if m.group(1).lower() not in ("example.com", "example.org")]
    return out


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def diversity(tasks: list[dict], sizes: dict[str, int]) -> str:
    prim = [t for t in tasks if not t.get("variant_of")]
    n_var = len(tasks) - len(prim)
    lines = ["# Diversity card", "", f"{len(prim)} documents ({n_var} scan/photo variants on top).", ""]
    for title, key in [("Track", lambda t: t["track"]), ("Source", lambda t: t["source"]),
                       ("Family", lambda t: f"{t['track']} / {t['family']}"), ("Language", lambda t: t["language"]),
                       ("Media type", lambda t: t["document"]["media_type"]),
                       ("Pages", lambda t: str(t["document"]["pages"])),
                       ("Published", lambda t: (t.get("published") or "n/a")[:4])]:
        c = Counter(key(t) for t in prim)
        lines += [f"## {title}", "", "| value | documents |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))] + [""]
    lf = Counter(t.get("layout_family") or t["source"] for t in prim)
    lines += ["## Layout families", "", f"{len(lf)} families; largest {lf.most_common(1)[0][1]} documents.", ""]
    st = defaultdict(Counter)
    tg = defaultdict(Counter)
    for t in prim:
        for r in t["fields"].values():
            st[t["track"]][r["status"]] += 1
            if r["status"] == "present":
                for g in r.get("tags") or []:
                    if not g.startswith("lang:"):
                        tg[t["track"]][g] += 1
    lines += ["## Fields", "", "| track | present | absent | absent share | excluded | lookalike | normalize | late |",
              "|---|---|---|---|---|---|---|---|"]
    for tr, c in sorted(st.items()):
        n = c["present"] + c["absent"]
        lines.append(f"| {tr} | {c['present']} | {c['absent']} | {c['absent'] / n:.1%} | {c['excluded']} | "
                     f"{tg[tr]['lookalike']} | {tg[tr]['normalize']} | {tg[tr]['late']} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", type=Path, nargs="+", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--adjudication", type=Path, nargs=2, metavar=("POOL", "DECISIONS"),
                    help="apply blind-review decisions to the base tasks (variants inherit them); writes the log")
    a = ap.parse_args(argv)
    decided = {}
    if a.adjudication:
        pool = {i["id"]: i for i in json.loads(a.adjudication[0].read_text())}
        for iid, d in json.loads(a.adjudication[1].read_text()).items():
            if iid in pool:
                decided.setdefault(pool[iid]["task_id"], []).append((pool[iid], d))
    log = ["# Adjudication log", "", "Changes to gold after blind review (system names hidden). Each applies to every "
           "system, and to the scan and photo variants of the document.", ""]
    if a.out.exists():
        shutil.rmtree(a.out)
    (a.out / "tasks").mkdir(parents=True)
    tasks, problems, sizes, added = [], [], {}, Counter()
    for src in a.src:
        for f in sorted((src / "tasks").glob("*.json")):
            t = json.loads(f.read_text())
            doc = src / t["document"]["path"]
            text = doc_text(doc, t["document"]["media_type"])
            sizes[t["task_id"]] = doc.stat().st_size
            t, new = inject(t, text, SEED)
            for k in new:
                added[(t["family"], k, t["fields"][f"/{k}"]["status"])] += 1
            for item, d in decided.get(t["task_id"], []):
                msg = _set_field(t["fields"][item["pointer"]], item["unit"], item["pointer"], d)
                if msg:
                    log.append(f"- `{t['task_id']}` `{item['unit']}`: {msg}")
            t = tag_task(t, text)
            t["canary"] = CANARY
            problems += [f"{t['task_id']}: {e}" for e in validate_task(t)]
            problems += [f"{t['task_id']}: PII {p}" for p in pii_problems(t, text)]
            if t["document"]["pages"] > MAX_PAGES:
                problems.append(f"{t['task_id']}: {t['document']['pages']} pages")
            dst = a.out / t["document"]["path"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(doc, dst)
            (a.out / "tasks" / f"{t['task_id']}.json").write_text(json.dumps(t, indent=1, ensure_ascii=False) + "\n")
            tasks.append(t)
        for s in (src / "sources").glob("*.json"):
            (a.out / "sources").mkdir(exist_ok=True)
            shutil.copyfile(s, a.out / "sources" / s.name)
    has_variant = {t["variant_of"] for t in tasks if t.get("variant_of")}
    bases = [t for t in tasks if not t.get("variant_of") and t["task_id"] not in has_variant
             and t["document"]["media_type"] == "application/pdf" and t["document"]["pages"] == 1
             and t["document"]["condition"] == "born_digital"]
    for t in bases:
        v, data = make_variant(t, (a.out / t["document"]["path"]).read_bytes(), SEED)
        problems += [f"{v['task_id']}: {e}" for e in validate_task(v)]
        (a.out / v["document"]["path"]).write_bytes(data)
        (a.out / "tasks" / f"{v['task_id']}.json").write_text(json.dumps(v, indent=1, ensure_ascii=False) + "\n")
        tasks.append(v)
    print(f"variants: {len(bases)} ({dict(Counter(t['document']['condition'] for t in tasks if t.get('variant_of')))})")
    ids = Counter(t["task_id"] for t in tasks)
    problems += [f"duplicate task id {k}" for k, v in ids.items() if v > 1]
    fam = Counter(t.get("layout_family") for t in tasks if t.get("layout_family") and not t.get("variant_of"))
    problems += [f"layout family {k}: {v} documents" for k, v in fam.items() if v > MAX_PER_FAMILY]
    ok, table = rule0.check(tasks, sizes)
    print("absence library:", dict(added))
    print("Rule 0 (NMI above the shuffled floor):\n" + table)
    if not ok:
        problems.append("Rule 0 failed")
    (a.out / "DIVERSITY.md").write_text(diversity(tasks, sizes))
    if a.adjudication:
        n_dec = sum(len(v) for v in decided.values())
        log.append(f"\n{len(log) - 4} change(s) from {n_dec} decision(s) over {len(decided)} document(s).")
        (a.out / "ADJUDICATION_LOG.md").write_text("\n".join(log) + "\n")
    files = sorted(p for p in a.out.rglob("*") if p.is_file() and p.name != "manifest.json")
    (a.out / "manifest.json").write_text(json.dumps(
        {"canary": CANARY, "files": {str(p.relative_to(a.out)): sha256(p) for p in files}}, indent=1) + "\n")
    print(f"release: {len(tasks)} tasks, {len(files)} files")
    for p in problems[:40]:
        print("  GATE:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
