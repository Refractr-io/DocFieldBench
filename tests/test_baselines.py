from pathlib import Path

from docfieldbench import baselines
from docfieldbench.outcomes import score_task
from docfieldbench.tasks import load_tasks

FIX = Path(__file__).parent / "fixtures" / "tasks"

TEXT = """Northwind Supplies Ltd   VAT GB123456789
Invoice INV-2024-0042        Date 12.03.2024
Due 11.04.2024
Paper A4          10     45,00
Toner cartridge    2    189,50
Total                 1.234,56
"""


def test_first_candidate_takes_the_first_of_each_type():
    t = load_tasks(FIX / "t_invoice.json")[0]
    p = baselines.first_candidate(t, TEXT)["parsed"]
    assert p["invoice_date"] == "2024-03-12"
    assert p["due_date"] == "2024-03-12"              # the look-alike trap: a heuristic can't tell them apart
    assert p["total_incl_tax"] == 45.0
    assert p["invoice_number"] == "GB123456789"
    assert p["line_items"] == []
    s = score_task(t, {"parse_status": "ok", "parsed": p})
    o = {u["unit"]: u["outcome"] for u in s["units"]}
    assert o["/invoice_date"] == "correct" and o["/due_date"] == "swapped"


def test_null_all_shape():
    t = load_tasks(FIX / "t_invoice.json")[0]
    p = baselines.null_all(t)["parsed"]
    assert p["seller"] == {"name": None, "vat_id": None, "postcode": None}
    assert p["line_items"] == []
