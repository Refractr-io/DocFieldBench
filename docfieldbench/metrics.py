"""Metrics from scored tasks: per-document counts, then document-macro and field-micro rates with bootstrap CIs.

Every rate weighs each document the same (document-macro, the headline) and is also given field-micro. CIs resample
documents, because errors cluster inside documents: a system that fails a document fails many of its fields.

The headline, the DocFieldBench score (`headline`), folds precision, recall and abstention into one number:
  per document   max(0, correct + abstained - SILENT_PENALTY * silent errors) / (present + absent fields)
  per track      the mean over its documents
  score          the mean over the tracks (each track weighs the same, whatever its size)
A right value or a right empty field earns a point; an omitted present field earns none; a silent error (wrong,
swapped, fabricated or extra value) costs a point. With SILENT_PENALTY = 1, answering pays only when the system is
more likely right than wrong, so neither answering everything nor answering nothing scores well (the all-null
baseline scores the share of absent fields). A failed response scores 0.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np

SILENT_PENALTY = 1.0
OUTCOMES = ("correct", "swapped", "wrong", "omitted", "abstained", "fabricated", "extra", "failed")

# metric: (numerator, denominator) over per-document counts
RATES = {
    "precision": ("correct", "answers"),
    "recall": ("correct", "present"),
    "abstention": ("abstained", "absent"),
    "silent_error_rate": ("silent", "answers"),
    "swap_rate": ("swapped", "present"),
    "item_count_accuracy": ("item_count_ok", "item_arrays"),
    "clean_docs": ("clean", "one"),
    "exact_docs": ("exact", "one"),
    "conformance": ("conformant", "one"),
    "fenced": ("fenced", "one"),
    "field_score": ("score_points", "scored"),
}


def doc_counts(scored: dict, unit_filter: Callable[[dict], bool] | None = None) -> dict:
    """Counts for one scored task; `unit_filter` restricts to some units (e.g. one tag)."""
    units = [u for u in scored["units"] if unit_filter is None or unit_filter(u)]
    c = {o: 0 for o in OUTCOMES}
    for u in units:
        c[u["outcome"]] += 1
    c["present"] = sum(u["status"] == "present" for u in units)
    c["absent"] = sum(u["status"] == "absent" for u in units)
    c["answers"] = c["correct"] + c["swapped"] + c["wrong"] + c["fabricated"] + c["extra"]
    c["silent"] = c["swapped"] + c["wrong"] + c["fabricated"] + c["extra"]
    c["partial"] = sum(bool(u.get("partial")) for u in units)
    c["scored"] = c["present"] + c["absent"]
    c["score_points"] = max(0.0, c["correct"] + c["abstained"] - SILENT_PENALTY * c["silent"])
    d = scored["doc"]
    failed = d["failed"]
    c["one"] = 1 if units else 0
    c["clean"] = int(bool(units) and not failed and c["silent"] == 0)
    c["exact"] = int(bool(units) and not failed and c["correct"] == c["present"]
                     and c["abstained"] == c["absent"] and c["extra"] == 0)
    c["conformant"] = int(bool(units) and d["conformant"])
    c["fenced"] = int(bool(units) and d["fenced"])
    arrays = d.get("item_counts") or []
    c["item_arrays"] = len(arrays) if unit_filter is None else 0
    c["item_count_ok"] = sum(a["gold"] == a["pred"] for a in arrays) if unit_filter is None else 0
    return c


def _rates(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, num / np.where(den > 0, den, 1), np.nan)


def macro(num, den) -> float | None:
    r = _rates(np.asarray(num, float), np.asarray(den, float))
    return None if np.all(np.isnan(r)) else float(np.nanmean(r))


def micro(num, den) -> float | None:
    d = float(np.sum(den))
    return None if d == 0 else float(np.sum(num)) / d


def bootstrap_ci(num, den, n_boot: int = 10_000, seed: int = 0, alpha: float = 0.05):
    """Percentile CI of the document-macro rate, resampling documents."""
    num, den = np.asarray(num, float), np.asarray(den, float)
    keep = den > 0
    if keep.sum() == 0:
        return None, None
    r = num[keep] / den[keep]
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(r), size=(n_boot, len(r)))
    means = r[idx].mean(axis=1)
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def paired_bootstrap(num_a, den_a, num_b, den_b, n_boot: int = 10_000, seed: int = 0, alpha: float = 0.05):
    """Difference A - B of document-macro rates over the documents both have, with a paired percentile CI and the
    share of resamples on the other side of zero (two-sided)."""
    na, da, nb, db = (np.asarray(x, float) for x in (num_a, den_a, num_b, den_b))
    keep = (da > 0) & (db > 0)
    if keep.sum() == 0:
        return None
    ra, rb = na[keep] / da[keep], nb[keep] / db[keep]
    diff = float(ra.mean() - rb.mean())
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, keep.sum(), size=(n_boot, int(keep.sum())))
    d = ra[idx].mean(axis=1) - rb[idx].mean(axis=1)
    lo, hi = np.quantile(d, alpha / 2), np.quantile(d, 1 - alpha / 2)
    p = 2 * min(float(np.mean(d <= 0)), float(np.mean(d >= 0)))
    return {"diff": diff, "lo": float(lo), "hi": float(hi), "p": min(1.0, p), "n_docs": int(keep.sum())}


def summarize(scored_tasks: list[dict], unit_filter=None, n_boot: int = 10_000, seed: int = 0) -> dict:
    """{metric: {macro, micro, lo, hi, n_docs}} plus F1 from the macro precision and recall."""
    counts = [doc_counts(s, unit_filter) for s in scored_tasks]
    out = {}
    for name, (n, d) in RATES.items():
        num = [c[n] for c in counts]
        den = [c[d] for c in counts]
        lo, hi = bootstrap_ci(num, den, n_boot, seed)
        out[name] = {"macro": macro(num, den), "micro": micro(num, den), "lo": lo, "hi": hi,
                     "n_docs": int(sum(x > 0 for x in den))}
    p, r = out["precision"]["macro"], out["recall"]["macro"]
    out["f1"] = {"macro": (2 * p * r / (p + r)) if p and r else None}
    out["counts"] = {o: int(sum(c[o] for c in counts)) for o in (*OUTCOMES, "present", "absent", "answers")}
    return out


def headline(scored_tasks: list[dict], n_boot: int = 10_000, seed: int = 0, alpha: float = 0.05) -> dict:
    """The DocFieldBench score (module docstring): the mean over tracks of the document-macro field score, with a
    percentile CI from a bootstrap that resamples documents within each track."""
    by_track: dict[str, list[float]] = {}
    for s in scored_tasks:
        c = doc_counts(s)
        if c["scored"] > 0:
            by_track.setdefault(s.get("track") or "all", []).append(c["score_points"] / c["scored"])
    if not by_track:
        return {"score": None, "lo": None, "hi": None, "tracks": {}, "n_docs": 0}
    names = sorted(by_track)
    arrs = [np.asarray(by_track[t]) for t in names]
    point = float(np.mean([a.mean() for a in arrs]))
    rng = np.random.default_rng(seed)
    boots = np.mean([a[rng.integers(0, len(a), size=(n_boot, len(a)))].mean(axis=1) for a in arrs], axis=0)
    return {"score": point, "lo": float(np.quantile(boots, alpha / 2)), "hi": float(np.quantile(boots, 1 - alpha / 2)),
            "tracks": {t: float(a.mean()) for t, a in zip(names, arrs, strict=True)},
            "n_docs": int(sum(len(a) for a in arrs)), "silent_penalty": SILENT_PENALTY}


def selective_prediction(answers: list[tuple[bool, float | None]], targets=(0.01, 0.02, 0.05)) -> dict:
    """Coverage at a target silent-error rate, and AURC, over non-null answers (correct?, confidence).

    Without confidences, a system can only accept everything or nothing: coverage is 1 if its overall error is
    within the target, else 0.
    """
    if not answers:
        return {"aurc": None, **{f"coverage@{t}": None for t in targets}}
    n = len(answers)
    has_conf = all(c is not None for _, c in answers)
    if not has_conf:
        err = 1 - sum(ok for ok, _ in answers) / n
        return {"aurc": None, **{f"coverage@{t}": (1.0 if err <= t else 0.0) for t in targets}}
    order = sorted(answers, key=lambda x: -x[1])
    wrong = np.cumsum([not ok for ok, _ in order])
    k = np.arange(1, n + 1)
    risk = wrong / k
    out = {"aurc": float(risk.mean())}
    for t in targets:
        ok_k = k[risk <= t]
        out[f"coverage@{t}"] = float(ok_k.max() / n) if len(ok_k) else 0.0
    return out
