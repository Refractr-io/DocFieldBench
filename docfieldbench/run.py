"""docfieldbench run: send every task to one system, once, and write a predictions file for `docfieldbench score`.

The system config is a JSON file:
  {"name": "my-system", "adapter": "openai_compat", "reader": "native",
   "options": {"model": "vendor/model", "base_url": "https://openrouter.ai/api/v1",
               "api_key_env": "OPENROUTER_API_KEY"}}

Protocol: the published prompt (prompt.py), one request per task, the first reply is the one scored. Only transport
failures (network, rate limit, server error) are retried, up to 3 times; the retries are recorded. Latency is the
client's wall time for the request that produced the reply. Replies are appended as they arrive, so `--resume` never
pays twice. `--pilot N` runs the N largest tasks first and projects the cost of the full run; `--budget` stops a run
once it has spent that much.
"""
from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import __version__
from .adapters import TransportError, get_adapter
from .prompt import PROMPT_ID
from .readers import READERS, read
from .responses import parse_response

RETRIES = 3


def config_hash(cfg: dict, adapter) -> str:
    key = {"adapter": cfg["adapter"], "reader": cfg.get("reader", "native"), "prompt": PROMPT_ID,
           "options": adapter.describe()}
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:12]


def task_size(task: dict, root: Path) -> tuple:
    d = task["document"]
    return (d.get("pages") or 1, (root / d["path"]).stat().st_size, len(json.dumps(task["schema"])))


def run_one(task: dict, root: Path, adapter, reader: str, sleep=time.sleep) -> dict:
    d = task["document"]
    doc = read(root / d["path"], d["media_type"], reader)
    failures = []
    for attempt in range(1, RETRIES + 1):
        t0 = time.perf_counter()
        try:
            reply = adapter.extract(task["schema"], doc)
        except TransportError as e:
            failures.append(str(e)[:200])
            if not e.retryable:
                break
            sleep(2 * attempt)
            continue
        status, parsed = parse_response(reply.raw)
        return {"task_id": task["task_id"], "parse_status": status, "parsed": parsed, "raw": reply.raw,
                "latency_s": round(time.perf_counter() - t0, 3), "attempts": attempt, "failures": failures,
                "cost_usd": reply.cost_usd, "usage": reply.usage, "served_by": reply.served_by,
                "finish_reason": reply.finish_reason}
    return {"task_id": task["task_id"], "parse_status": "transport", "parsed": None, "raw": None, "latency_s": None,
            "attempts": len(failures), "failures": failures, "cost_usd": None}


def run(tasks: list[dict], root: Path, cfg: dict, out: Path, *, resume=False, concurrency=1, budget=None,
        transport=None, log=print) -> list[dict]:
    reader = cfg.get("reader", "native")
    if reader not in READERS:
        raise ValueError(f"reader must be one of {READERS}")
    adapter = get_adapter(cfg["adapter"], cfg.get("options", {}), transport=transport)
    h = config_hash(cfg, adapter)
    done = {}
    if resume and out.exists():
        for line in out.read_text().splitlines():
            p = json.loads(line)
            if p.get("config_hash") != h:
                raise SystemExit(f"{out} was written by another config ({p.get('config_hash')} vs {h})")
            if p["parse_status"] != "transport":
                done[p["task_id"]] = p
    elif out.exists():
        raise SystemExit(f"{out} exists; pass --resume to continue it")
    todo = [t for t in tasks if t["task_id"] not in done]
    spent = sum(p.get("cost_usd") or 0 for p in done.values())
    log(f"{cfg['name']}: {len(todo)} to run, {len(done)} already done (config {h}, prompt {PROMPT_ID})")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "a") as f, ThreadPoolExecutor(concurrency) as ex:
        it = iter(todo)
        pending = {}
        while True:
            while len(pending) < concurrency and (budget is None or spent < budget):
                t = next(it, None)
                if t is None:
                    break
                pending[ex.submit(run_one, t, root, adapter, reader)] = t
            if not pending:
                break
            fut = next(iter(pending))
            pending.pop(fut)
            p = fut.result() | {"system": cfg["name"], "config_hash": h, "harness": __version__}
            spent += p.get("cost_usd") or 0
            done[p["task_id"]] = p
            f.write(json.dumps(p, ensure_ascii=False, default=str) + "\n")
            f.flush()
            log(f"  {p['task_id']} {p['parse_status']} {p['latency_s']}s ${(p.get('cost_usd') or 0):.4f}")
        if budget is not None and spent >= budget and len(done) < len(tasks):
            log(f"budget reached: ${spent:.4f} spent, {len(tasks) - len(done)} tasks not run")
    return [done[t["task_id"]] for t in tasks if t["task_id"] in done]


def _pct(xs, q):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 3) if xs else None


def run_summary(preds: list[dict], cfg: dict) -> dict:
    """Spend and time, measured the same way for every system. Local systems report no cost; add your hardware's
    price per hour in the config (`usd_per_hour`) to get one from the wall time."""
    lat = [p["latency_s"] for p in preds if p.get("latency_s") is not None]
    costs = [p.get("cost_usd") for p in preds]
    cost = sum(c or 0 for c in costs)
    if cfg.get("usd_per_hour") and not any(costs):
        cost = sum(lat) / 3600 * cfg["usd_per_hour"]
    n = len(preds)
    return {"system": cfg["name"], "tasks": n, "cost_usd": round(cost, 4),
            "usd_per_1k_docs": round(cost / n * 1000, 3) if n else None,
            "latency_p50_s": _pct(lat, 0.5), "latency_p90_s": _pct(lat, 0.9), "latency_mean_s":
            round(sum(lat) / len(lat), 3) if lat else None,
            "transport_failures": sum(p["parse_status"] == "transport" for p in preds),
            "retried": sum(len(p.get("failures") or []) > 0 for p in preds),
            "reader": cfg.get("reader", "native"), "prompt": PROMPT_ID, "harness": __version__,
            "hardware": cfg.get("hardware")}


def pilot(tasks: list[dict], root: Path, n: int) -> list[dict]:
    return sorted(tasks, key=lambda t: task_size(t, root), reverse=True)[:n]


def projection(preds: list[dict], n_total: int) -> dict:
    costs = [p.get("cost_usd") or 0 for p in preds if p["parse_status"] != "transport"]
    if not costs:
        return {"mean": None, "worst": None}
    return {"pilot_tasks": len(costs), "pilot_cost": round(sum(costs), 4),
            "projected_mean": round(sum(costs) / len(costs) * n_total, 2),
            "projected_worst": round(max(costs) * n_total, 2)}
