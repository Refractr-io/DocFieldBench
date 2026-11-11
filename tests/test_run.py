"""The run harness against a mock API: request shape, retries, resume, budget. No keys, no network."""
import json
from pathlib import Path

import httpx
import pytest

from docfieldbench import run as runner
from docfieldbench.prompt import SYSTEM
from docfieldbench.schema import to_json_schema
from docfieldbench.tasks import gold_instance, load_tasks

FIX = Path(__file__).parent / "fixtures" / "tasks"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "k")
    tasks = load_tasks(FIX)
    root = tmp_path / "data"
    for t in tasks:                                         # stand-in documents
        p = root / t["document"]["path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"%PDF-1.4 stand-in" if t["document"]["media_type"] == "application/pdf" else b"text")
    return tasks, root


def cfg(**opt):
    return {"name": "mock", "adapter": "openai_compat", "reader": "native",
            "options": {"model": "m", "base_url": "https://mock.test/v1", "api_key_env": "TEST_KEY", **opt}}


def answering(tasks, seen, fail_first=0):
    gold = {json.dumps(to_json_schema(t["schema"])["properties"], sort_keys=True): gold_instance(t) for t in tasks}
    calls = {"n": 0}

    def handler(req: httpx.Request):
        calls["n"] += 1
        if calls["n"] <= fail_first:
            return httpx.Response(503, text="busy")
        body = json.loads(req.content)
        seen.append(body)
        text = body["messages"][1]["content"]
        text = text if isinstance(text, str) else text[0]["text"]
        schema = json.loads(text.split("JSON Schema:\n", 1)[1].split("\n\n", 1)[0])
        answer = gold[json.dumps(schema["properties"], sort_keys=True)]
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)},
                                                      "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.01}})
    return httpx.MockTransport(handler)


def test_run_scores_gold_and_sends_the_published_prompt(setup, tmp_path):
    tasks, root = setup
    seen = []
    preds = runner.run(tasks, root, cfg(), tmp_path / "p.jsonl", transport=answering(tasks, seen), log=lambda *a: 0)
    assert {p["parse_status"] for p in preds} == {"ok"} and len(preds) == len(tasks)
    assert all(b["messages"][0]["content"] == SYSTEM and b["temperature"] == 0 for b in seen)
    assert all("response_format" not in b for b in seen)          # plain call by default
    assert sum(p["cost_usd"] for p in preds) == pytest.approx(0.01 * len(tasks))


def test_transport_errors_are_retried_and_recorded(setup, tmp_path, monkeypatch):
    tasks, root = setup
    monkeypatch.setattr(runner.time, "sleep", lambda s: None)
    preds = runner.run(tasks[:1], root, cfg(), tmp_path / "p.jsonl",
                       transport=answering(tasks, [], fail_first=2), log=lambda *a: 0)
    assert preds[0]["parse_status"] == "ok" and preds[0]["attempts"] == 3 and len(preds[0]["failures"]) == 2


def test_client_error_is_not_retried(setup, tmp_path):
    tasks, root = setup
    t = httpx.MockTransport(lambda r: httpx.Response(401, text="no"))
    preds = runner.run(tasks[:1], root, cfg(), tmp_path / "p.jsonl", transport=t, log=lambda *a: 0)
    assert preds[0]["parse_status"] == "transport" and preds[0]["attempts"] == 1


def test_resume_never_repeats_a_reply(setup, tmp_path):
    tasks, root = setup
    out = tmp_path / "p.jsonl"
    runner.run(tasks[:1], root, cfg(), out, transport=answering(tasks, []), log=lambda *a: 0)
    seen = []
    preds = runner.run(tasks, root, cfg(), out, resume=True, transport=answering(tasks, seen), log=lambda *a: 0)
    assert len(seen) == len(tasks) - 1 and len(preds) == len(tasks)
    with pytest.raises(SystemExit):                                # another config can't resume this file
        runner.run(tasks, root, cfg(max_tokens=10), out, resume=True, transport=answering(tasks, []),
                   log=lambda *a: 0)


def test_budget_stops_the_run(setup, tmp_path):
    tasks, root = setup
    preds = runner.run(tasks, root, cfg(), tmp_path / "p.jsonl", budget=0.005, transport=answering(tasks, []),
                       log=lambda *a: 0)
    assert len(preds) == 1


def test_python_adapter(setup, tmp_path):
    tasks, root = setup
    mod = tmp_path / "ext.py"
    mod.write_text("def extract(schema, document):\n    return {k: None for k in schema['properties']}\n")
    c = {"name": "py", "adapter": "python", "options": {"callable": f"{mod}:extract"}}
    preds = runner.run(tasks, root, c, tmp_path / "p.jsonl", log=lambda *a: 0)
    assert {p["parse_status"] for p in preds} == {"ok"}


def test_run_summary_measures_spend_and_time(setup, tmp_path):
    tasks, root = setup
    preds = runner.run(tasks, root, cfg(), tmp_path / "p.jsonl", transport=answering(tasks, []), log=lambda *a: 0)
    s = runner.run_summary(preds, cfg())
    assert s["cost_usd"] == pytest.approx(0.01 * len(tasks)) and s["usd_per_1k_docs"] == pytest.approx(10)
    assert s["latency_p50_s"] is not None and s["transport_failures"] == 0
