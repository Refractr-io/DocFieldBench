"""Rule 0: whether a field is empty must not be predictable from anything but the document.

For each track, the normalised mutual information between a scored field's status (absent or present) and each
shortcut feature (its type, its position in the schema, its depth, the schema's size, the document's length), minus
the same measure with the statuses shuffled (the floor a finite sample gives by chance). The gate fails when a
feature exceeds its limit. Field names that are always empty are listed: a name that is never present invites
answering null without reading.
"""
from __future__ import annotations

import math
import random
from collections import Counter, defaultdict

from ..schema import base_type, iter_fields

LIMITS = {"type": 0.12, "position": 0.05, "depth": 0.05, "schema_size": 0.05, "doc_length": 0.05}


def _nmi(xs, ys) -> float:
    n = len(xs)
    if n == 0:
        return 0.0
    px, py, pxy = Counter(xs), Counter(ys), Counter(zip(xs, ys, strict=True))
    hx = -sum(c / n * math.log(c / n) for c in px.values())
    hy = -sum(c / n * math.log(c / n) for c in py.values())
    mi = sum(c / n * math.log((c / n) / (px[x] / n * py[y] / n)) for (x, y), c in pxy.items())
    return 0.0 if hx + hy == 0 else 2 * mi / (hx + hy)


def _bucket(x: float, edges) -> int:
    return sum(x > e for e in edges)


def rows(tasks: list[dict], doc_sizes: dict[str, int]) -> list[dict]:
    out = []
    for t in tasks:
        if t.get("variant_of"):
            continue
        fields = list(iter_fields(t["schema"]))
        top = list(t["schema"]["properties"])
        for p, node in fields:
            r = t["fields"].get(p)
            if not r or r["status"] == "excluded":
                continue
            key = p.strip("/").split("/")[0]
            pos = top.index(key) / max(1, len(top) - 1) if key in top else 0
            typ = "date" if node.get("format") == "date" else base_type(node)
            out.append({"track": t["track"], "absent": r["status"] == "absent", "name": p, "family": t.get("family"),
                        "type": typ, "position": _bucket(pos, (0.25, 0.5, 0.75)), "depth": p.count("/"),
                        "schema_size": _bucket(len(fields), (8, 15, 25)),
                        "doc_length": _bucket(doc_sizes.get(t["task_id"], 0), (20_000, 80_000, 300_000))})
    return out


def check(tasks: list[dict], doc_sizes: dict[str, int], n_shuffle: int = 50, seed: int = 0) -> tuple[bool, str]:
    rs = rows(tasks, doc_sizes)
    rng = random.Random(seed)
    lines, ok = [f"{'track':9} {'n':>5} {'absent':>7}  " + "  ".join(f"{f:>11}" for f in LIMITS)], True
    by = defaultdict(list)
    for r in rs:
        by[r["track"]].append(r)
    for track in sorted(by):
        rr = by[track]
        ys = [r["absent"] for r in rr]
        cells = []
        for f, lim in LIMITS.items():
            xs = [r[f] for r in rr]
            raw = _nmi(xs, ys)
            floor = sum(_nmi(xs, rng.sample(ys, len(ys))) for _ in range(n_shuffle)) / n_shuffle
            v = raw - floor
            ok &= v < lim
            cells.append(f"{v:+.3f}{'!' if v >= lim else ' '}")
        lines.append(f"{track:9} {len(rr):5d} {sum(ys) / len(rr):7.1%}  " + "  ".join(f"{c:>11}" for c in cells))
    names = defaultdict(Counter)
    for r in rs:
        names[(r["family"], r["name"])][r["absent"]] += 1
    always = [f"{fam} {n} ({c[True]}x)" for (fam, n), c in sorted(names.items()) if c[True] >= 3 and not c[False]]
    lines.append("always empty: " + (", ".join(always) if always else "none"))
    return ok, "\n".join(lines)
