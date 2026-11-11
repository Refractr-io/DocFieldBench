"""Adjudication: the review page builds, and decisions patch gold."""
import json
from pathlib import Path

from docfieldbench import adjudicate

FIX = Path(__file__).parent / "fixtures" / "tasks"


def test_build_and_apply(tmp_path):
    data = tmp_path / "data"
    (data / "tasks").mkdir(parents=True)
    t = json.loads((FIX / "t_invoice.json").read_text())
    (data / "tasks" / f"{t['task_id']}.json").write_text(json.dumps(t))
    pool = [{"id": "a1", "task_id": t["task_id"], "pointer": "/invoice_number", "unit": "/invoice_number",
             "kind": "id", "gold": t["fields"]["/invoice_number"]["value"], "answers": ["X-1"]},
            {"id": "a2", "task_id": t["task_id"], "pointer": "/seller/name", "unit": "/seller/name",
             "kind": "name", "gold": "N", "answers": ["Northwind"]},
            {"id": "a3", "task_id": t["task_id"], "pointer": "/due_date", "unit": "/due_date", "kind": "date",
             "gold": None, "answers": ["2024-04-01"]}]
    (tmp_path / "pool.json").write_text(json.dumps(pool))
    assert adjudicate.build(tmp_path / "pool.json", data, tmp_path / "review.html") == 0
    assert "a1" in (tmp_path / "review.html").read_text()
    (tmp_path / "dec.json").write_text(json.dumps({"a1": {"decision": "stands"},
                                                   "a2": {"decision": "accept", "value": "Northwind"},
                                                   "a3": {"decision": "exclude", "reason": "unclear"}}))
    adjudicate.apply(tmp_path / "pool.json", tmp_path / "dec.json", data, tmp_path / "log.md")
    t2 = json.loads((data / "tasks" / "fixture-invoice-1.json").read_text())
    assert t2["fields"]["/invoice_number"] == t["fields"]["/invoice_number"]
    assert "Northwind" in t2["fields"]["/seller/name"]["accept"]
    assert t2["fields"]["/due_date"]["status"] == "excluded"
    log = (tmp_path / "log.md").read_text()
    assert "2 change(s)" in log and "system" in log
