"""docfieldbench command line.

  docfieldbench validate TASKS              check every task file
  docfieldbench score TASKS PREDICTIONS     score a predictions file (JSONL, one object per task)
  docfieldbench baseline TASKS --out FILE   the all-null baseline (calibrates the absence metric)

A predictions line is {"task_id", "parse_status", "parsed"} or {"task_id", "raw"} (parsed here). A task without a
line scores as a failed response.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import baselines
from .metrics import summarize
from .outcomes import score_task
from .responses import parse_response
from .tasks import load_tasks, validate_task


def _load_predictions(path: Path) -> dict:
    preds = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        p = json.loads(line)
        if "parsed" not in p and "raw" in p:
            p["parse_status"], p["parsed"] = parse_response(p["raw"])
        preds[p["task_id"]] = p
    return preds


def _fmt(x):
    return "   -" if x is None else f"{100 * x:5.1f}"


def cmd_validate(a) -> int:
    bad = 0
    for t in load_tasks(a.tasks):
        for e in validate_task(t):
            print(f"{t.get('task_id', '?')}: {e}")
            bad += 1
    print(f"{bad} problem(s)")
    return 1 if bad else 0


def cmd_score(a) -> int:
    tasks = load_tasks(a.tasks)
    preds = _load_predictions(a.predictions)
    scored = [score_task(t, preds.get(t["task_id"])) for t in tasks]
    groups = {"all": scored}
    for s in scored:
        groups.setdefault(f"track={s['track']}", []).append(s)
    print(f"{'group':22} {'docs':>5} {'prec':>6} {'recall':>6} {'abst':>6} {'silent':>6} {'swap':>6} "
          f"{'exact':>6} {'conf':>6}")
    summary = {}
    for name, ss in groups.items():
        m = summarize(ss, n_boot=a.n_boot)
        summary[name] = m
        print(f"{name:22} {len(ss):5d} {_fmt(m['precision']['macro'])}  {_fmt(m['recall']['macro'])}  "
              f"{_fmt(m['abstention']['macro'])}  {_fmt(m['silent_error_rate']['macro'])}  "
              f"{_fmt(m['swap_rate']['macro'])}  {_fmt(m['exact_docs']['macro'])}  {_fmt(m['conformance']['macro'])}")
    if a.out:
        with open(a.out, "w") as f:
            for s in scored:
                f.write(json.dumps(s, ensure_ascii=False, default=str) + "\n")
    if a.summary:
        Path(a.summary).write_text(json.dumps(summary, indent=1))
    return 0


def cmd_baseline(a) -> int:
    with open(a.out, "w") as f:
        for t in load_tasks(a.tasks):
            f.write(json.dumps(baselines.null_all(t), ensure_ascii=False) + "\n")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="docfieldbench", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("tasks", type=Path)
    v.set_defaults(func=cmd_validate)
    s = sub.add_parser("score")
    s.add_argument("tasks", type=Path)
    s.add_argument("predictions", type=Path)
    s.add_argument("--out", help="write per-unit verdicts (JSONL)")
    s.add_argument("--summary", help="write the metric summary (JSON)")
    s.add_argument("--n-boot", type=int, default=10_000)
    s.set_defaults(func=cmd_score)
    b = sub.add_parser("baseline")
    b.add_argument("tasks", type=Path)
    b.add_argument("--out", required=True)
    b.set_defaults(func=cmd_baseline)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
