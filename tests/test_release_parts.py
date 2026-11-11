"""Absence library, Rule 0, tags, variants and the headline's treatment of variants."""
import copy
from pathlib import Path

import pytest

from docfieldbench.absence import inject
from docfieldbench.build import rule0
from docfieldbench.build.tags import tag_task
from docfieldbench.metrics import headline
from docfieldbench.outcomes import score_task
from docfieldbench.tasks import gold_instance, load_tasks, validate_task

FIX = Path(__file__).parent / "fixtures" / "tasks"


@pytest.fixture(scope="module")
def tasks():
    return {t["task_id"]: t for t in load_tasks(FIX)}


def opinion(tasks):
    t = copy.deepcopy(tasks["fixture-opinion-1"])
    t["family"] = "court_opinion"
    return t


def test_absence_adds_a_stated_field_as_present(tasks):
    text = "SMITH v. JONES\nRehearing denied June 13, 2007.\nOKAFOR, J., dissenting in part.\n"
    t, added = inject(opinion(tasks), text, "s")
    assert set(added) == {"rehearing_denied_date", "dissenting_judge"}
    assert t["fields"]["/rehearing_denied_date"] == {**t["fields"]["/rehearing_denied_date"], "status": "present",
                                                     "value": "2007-06-13"}
    assert validate_task(t) == []


def test_absence_only_where_provable(tasks):
    t, added = inject(opinion(tasks), "An opinion that mentions a petition for review and amicus briefs.", "s")
    for k in added:
        assert k not in ("supreme_court_review_denied_date", "amicus_curiae")
        assert t["fields"][f"/{k}"]["status"] == "absent"


def test_absence_is_seeded(tasks):
    a, _ = inject(opinion(tasks), "Plain opinion text.", "s")
    b, _ = inject(opinion(tasks), "Plain opinion text.", "s")
    assert a == b


def test_rule0_flags_a_type_shortcut(tasks):
    base = tasks["fixture-invoice-1"]
    many = []
    for i in range(30):
        t = copy.deepcopy(base)
        t["task_id"] = f"x{i}"
        for p, r in t["fields"].items():                       # every date absent, everything else present
            if r["match"] == "date":
                t["fields"][p] = {"status": "absent", "value": None, "match": "date", "provenance": "x"}
        many.append(t)
    ok, table = rule0.check(many, {t["task_id"]: 1000 for t in many}, n_shuffle=5)
    assert not ok and "!" in table


def test_tags(tasks):
    t = tag_task(copy.deepcopy(tasks["fixture-invoice-1"]), "")
    tags = {p: r["tags"] for p, r in t["fields"].items()}
    assert "lookalike" in tags["/invoice_date"] and all(any(g.startswith("lang:") for g in v) for v in tags.values())


def test_headline_ignores_variants(tasks):
    t = tasks["fixture-invoice-1"]
    v = copy.deepcopy(t)
    v["task_id"], v["variant_of"] = "fixture-invoice-1-scan", t["task_id"]
    good = score_task(t, {"parse_status": "ok", "parsed": gold_instance(t)})
    bad = score_task(v, None)
    assert headline([good, bad], n_boot=50)["score"] == headline([good], n_boot=50)["score"]


def test_variant_is_deterministic(tmp_path):
    pytest.importorskip("weasyprint")
    from docfieldbench.build.rendered.build import build_one
    from docfieldbench.build.variants import make_variant
    task, _ = build_one("receipt", "rc_thermal", 0, tmp_path / "o", tmp_path)
    pdf_bytes = (tmp_path / "o" / task["document"]["path"]).read_bytes()
    v1, d1 = make_variant(task, pdf_bytes, "s")
    v2, d2 = make_variant(task, pdf_bytes, "s")
    assert d1 == d2 and v1 == v2 and v1["variant_of"] == task["task_id"] and validate_task(v1) == []
