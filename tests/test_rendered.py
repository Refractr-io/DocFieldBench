"""Rendered business documents: one per template builds, validates, scores gold as perfect, and rebuilds identically."""
import pytest

pytest.importorskip("weasyprint")
pytest.importorskip("pypdfium2")

from docfieldbench.build.rendered.build import PLAN, build_one  # noqa: E402
from docfieldbench.metrics import summarize  # noqa: E402
from docfieldbench.outcomes import score_task  # noqa: E402
from docfieldbench.tasks import gold_instance  # noqa: E402


@pytest.mark.parametrize("fam,tn", sorted({(f, t) for f, t, _ in PLAN}))
def test_template_builds_and_gold_is_perfect(fam, tn, tmp_path):
    task, h = build_one(fam, tn, 0, tmp_path / "out", tmp_path)
    s = score_task(task, {"parse_status": "ok", "parsed": gold_instance(task)})
    m = summarize([s], n_boot=50)
    assert m["recall"]["macro"] == 1.0 and m["counts"]["extra"] == 0
    assert all(r["status"] != "excluded" or "text layer" not in r.get("reason", "") for r in task["fields"].values())
    again, h2 = build_one(fam, tn, 0, tmp_path / "out2", tmp_path)
    assert h == h2 and again == task
