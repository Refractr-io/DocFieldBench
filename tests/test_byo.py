"""Bring your own: init, fill, validate, inject-absent, run an offline extractor, score."""
import json
from pathlib import Path

import pytest

pytest.importorskip("pypdfium2")

from docfieldbench import byo, run  # noqa: E402
from docfieldbench.tasks import load_tasks, validate_task  # noqa: E402

EX = Path(__file__).resolve().parents[1] / "examples"


def test_byo_end_to_end(tmp_path):
    out = tmp_path / "bench"
    assert byo.init(EX / "my_docs", EX / "receipt_schema.json", out, "business", "receipt") == 0
    tasks = load_tasks(out / "tasks")
    assert len(tasks) == 3 and all(validate_task(t) for t in tasks)          # stubs are not valid until filled
    for t in tasks:                                                           # "fill" every field as absent
        for r in t["fields"].values():
            r.pop("todo")
            r.update({"status": "absent", "value": None, "evidence": {"check": "test"}})
        (out / "tasks" / f"{t['task_id']}.json").write_text(json.dumps(t))
    assert all(validate_task(t) == [] for t in load_tasks(out / "tasks"))
    assert byo.inject_absent(out / "tasks", EX / "absent_fields.json", 1, "s") == 0
    tasks = load_tasks(out / "tasks")
    assert all(validate_task(t) == [] for t in tasks)
    cfg = {"name": "offline", "adapter": "python", "reader": "text",
           "options": {"callable": f"{EX / 'extractor_text_layer.py'}:extract_offline"}}
    preds = run.run(tasks, out, cfg, tmp_path / "p.jsonl", log=lambda *a: 0)
    assert len(preds) == 3 and {p["parse_status"] for p in preds} == {"ok"}
