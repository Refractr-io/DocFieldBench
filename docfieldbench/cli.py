"""docfieldbench command line.

  docfieldbench validate TASKS              check every task file
  docfieldbench score TASKS PREDICTIONS     score a predictions file (JSONL, one object per task)
  docfieldbench baseline TASKS --out FILE   the all-null baseline (calibrates the absence metric)
  docfieldbench run TASKS --system CFG --out FILE   send every task to one system (see run.py for the config)
  docfieldbench adjudicate build|apply ...   blind review of gold against systems' answers (adjudicate.py)

A predictions line is {"task_id", "parse_status", "parsed"} or {"task_id", "raw"} (parsed here). A task without a
line scores as a failed response.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import baselines
from .metrics import headline, summarize
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
    primaries = [s for s in scored if not s.get("variant_of")]
    groups = {"all": primaries}
    for s in primaries:
        groups.setdefault(f"track={s['track']}", []).append(s)
    if len({s.get("condition") for s in scored}) > 1:                         # variants included: per condition
        for s in scored:
            groups.setdefault(f"condition={s.get('condition') or '?'}", []).append(s)
    tags = sorted({t for s in primaries for u in s["units"] for t in (u.get("tags") or [])})
    h = headline(scored, n_boot=a.n_boot)
    if h["score"] is not None:
        tracks = ", ".join(f"{t} {100 * v:.1f}" for t, v in h["tracks"].items())
        ci = f"95% CI {100 * h['lo']:.1f}-{100 * h['hi']:.1f}"
        print(f"DocFieldBench score: {100 * h['score']:.1f}  ({ci}; {tracks})\n")
    print(f"{'group':22} {'docs':>5} {'score':>6} {'prec':>6} {'recall':>6} {'abst':>6} {'silent':>6} {'swap':>6} "
          f"{'exact':>6} {'conf':>6}")
    summary = {"score": h}
    for name, ss in groups.items():
        m = summarize(ss, n_boot=a.n_boot)
        summary[name] = m
        print(f"{name:22} {len(ss):5d} {_fmt(m['field_score']['macro'])}  {_fmt(m['precision']['macro'])}  "
              f"{_fmt(m['recall']['macro'])}  "
              f"{_fmt(m['abstention']['macro'])}  {_fmt(m['silent_error_rate']['macro'])}  "
              f"{_fmt(m['swap_rate']['macro'])}  {_fmt(m['exact_docs']['macro'])}  {_fmt(m['conformance']['macro'])}")
    for tag in tags:
        m = summarize(primaries, unit_filter=lambda u, tag=tag: tag in (u.get("tags") or []), n_boot=a.n_boot)
        summary[f"tag={tag}"] = m
        cols = [m[k]["macro"] for k in ("field_score", "precision", "recall", "abstention", "silent_error_rate",
                                         "swap_rate")]
        print(f"{'tag=' + tag:22} {'':5} " + "  ".join(_fmt(x) for x in cols))
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


def cmd_run(a) -> int:
    from . import run as runner
    cfg = json.loads(Path(a.system).read_text())
    tasks = load_tasks(a.tasks)
    if a.only:
        tasks = [t for t in tasks if t["task_id"].startswith(tuple(a.only.split(",")))]
    if a.skip:
        tasks = [t for t in tasks if not t["task_id"].startswith(tuple(a.skip.split(",")))]
    root = Path(a.tasks).resolve().parent
    n_total = len(tasks)
    if a.pilot:
        tasks = runner.pilot(tasks, root, a.pilot)
    preds = runner.run(tasks, root, cfg, Path(a.out), resume=a.resume, concurrency=a.concurrency, budget=a.budget)
    summ = runner.run_summary(preds, cfg)
    if cfg.get("reader") == "text":
        from .readers import ocr_version
        summ["ocr"] = ocr_version()
    Path(str(a.out) + ".run.json").write_text(json.dumps(summ, indent=1) + "\n")
    print(f"{summ['tasks']} replies, ${summ['cost_usd']:.4f} (${summ['usd_per_1k_docs']}/1k docs), "
          f"latency p50 {summ['latency_p50_s']} s / p90 {summ['latency_p90_s']} s")
    if a.pilot:
        print("projection for all", n_total, "tasks:", json.dumps(runner.projection(preds, n_total)))
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["adjudicate"]:
        from . import adjudicate
        return adjudicate.main(argv[1:])
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
    r = sub.add_parser("run")
    r.add_argument("tasks", type=Path)
    r.add_argument("--system", required=True, help="system config (JSON)")
    r.add_argument("--out", required=True, help="predictions file (JSONL), appended as replies arrive")
    r.add_argument("--resume", action="store_true")
    r.add_argument("--only", help="comma-separated task_id prefixes")
    r.add_argument("--skip", help="comma-separated task_id prefixes")
    r.add_argument("--concurrency", type=int, default=1)
    r.add_argument("--budget", type=float, help="stop once this many USD are spent")
    r.add_argument("--pilot", type=int, help="run only the N largest tasks and project the full run's cost")
    r.set_defaults(func=cmd_run)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
