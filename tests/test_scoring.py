"""Scorer sanity suite: the scorer gives the answers we can work out by hand."""
import copy
from pathlib import Path

import pytest

from docfieldbench import baselines
from docfieldbench.metrics import bootstrap_ci, doc_counts, headline, paired_bootstrap, summarize
from docfieldbench.outcomes import score_task
from docfieldbench.tasks import gold_instance, load_tasks, validate_task

FIX = Path(__file__).parent / "fixtures" / "tasks"


@pytest.fixture(scope="module")
def tasks():
    return {t["task_id"]: t for t in load_tasks(FIX)}


def pred(obj, status="ok"):
    return {"parse_status": status, "parsed": obj}


def outcomes(scored):
    return {u["unit"]: u["outcome"] for u in scored["units"]}


def test_fixtures_are_valid(tasks):
    for t in tasks.values():
        assert validate_task(t) == []


def test_document_record_is_checked(tasks):
    t = copy.deepcopy(tasks["fixture-invoice-1"])
    t["document"]["pages"] = 11
    t["document"]["media_type"] = "application/msword"
    errs = validate_task(t)
    assert any("pages" in e for e in errs) and any("media_type" in e for e in errs)
    del t["document"]
    assert any("document" in e for e in validate_task(t))


def test_gold_scores_perfectly(tasks):
    scored = [score_task(t, pred(gold_instance(t))) for t in tasks.values()]
    m = summarize(scored, n_boot=200)
    for k in ("precision", "recall", "abstention", "clean_docs", "exact_docs", "conformance", "item_count_accuracy"):
        assert m[k]["macro"] == 1.0, k
    assert m["swap_rate"]["macro"] == 0.0
    assert m["counts"]["extra"] == 0


def test_all_null(tasks):
    scored = [score_task(t, baselines.null_all(t)) for t in tasks.values()]
    m = summarize(scored, n_boot=200)
    assert m["recall"]["macro"] == 0.0
    assert m["abstention"]["macro"] == 1.0
    assert m["precision"]["macro"] is None          # no answers at all
    assert m["conformance"]["macro"] == 1.0


def test_fabricating_every_absent_field(tasks):
    t = tasks["fixture-invoice-1"]
    g = gold_instance(t)
    g["seller"]["postcode"] = "EC1A 1BB"
    g["buyer_vat_id"] = "GB987654321"
    c = doc_counts(score_task(t, pred(g)))
    assert c["absent"] == 2 and c["fabricated"] == 2 and c["abstained"] == 0
    assert c["correct"] == c["present"]


def test_swapped_dates(tasks):
    t = tasks["fixture-invoice-1"]
    g = gold_instance(t)
    g["invoice_date"], g["due_date"] = g["due_date"], g["invoice_date"]
    o = outcomes(score_task(t, pred(g)))
    assert o["/invoice_date"] == "swapped" and o["/due_date"] == "swapped"


def test_failed_response(tasks):
    t = tasks["fixture-invoice-1"]
    s = score_task(t, {"parse_status": "unparseable", "parsed": None})
    assert s["doc"]["failed"] and not s["doc"]["conformant"]
    assert {u["outcome"] for u in s["units"]} == {"failed"}
    c = doc_counts(s)
    assert c["correct"] == 0 and c["abstained"] == 0 and c["answers"] == 0
    assert score_task(t, None)["doc"]["failed"]


def test_extra_row_never_moves_the_absent_denominator(tasks):
    t = tasks["fixture-invoice-1"]
    g = gold_instance(t)
    base = doc_counts(score_task(t, pred(g)))
    g["line_items"].append({"description": "Stapler", "quantity": 1, "line_total": 12.0})
    c = doc_counts(score_task(t, pred(g)))
    assert c["extra"] == 3
    assert (c["absent"], c["present"]) == (base["absent"], base["present"])
    assert c["item_count_ok"] == 0 and c["clean"] == 0


def test_rows_are_aligned_not_indexed(tasks):
    t = tasks["fixture-invoice-1"]
    g = gold_instance(t)
    g["line_items"].reverse()
    c = doc_counts(score_task(t, pred(g)))
    assert c["correct"] == c["present"] and c["extra"] == 0


def test_item_sign_either(tasks):
    t = copy.deepcopy(tasks["fixture-invoice-1"])
    g = gold_instance(t)
    g["line_items"][1]["line_total"] = -189.5
    assert outcomes(score_task(t, pred(g)))["/line_items/1/line_total"] == "wrong"
    t["fields"]["/line_items"]["item_sign_either"] = ["line_total"]
    assert outcomes(score_task(t, pred(g)))["/line_items/1/line_total"] == "correct"


def test_missing_row_is_omitted(tasks):
    t = tasks["fixture-invoice-1"]
    g = gold_instance(t)
    g["line_items"] = g["line_items"][:1]
    c = doc_counts(score_task(t, pred(g)))
    assert c["omitted"] == 3


def test_lenient_values_but_strict_conformance(tasks):
    t = tasks["fixture-invoice-1"]
    g = gold_instance(t)
    g["invoice_date"] = "12.03.2024"                  # day-first, as the locale says
    g["total_incl_tax"] = "1.234,56 €"
    g["buyer_vat_id"] = "N/A"
    s = score_task(t, pred(g))
    o = outcomes(s)
    assert o["/invoice_date"] == "correct" and o["/total_incl_tax"] == "correct"
    assert o["/buyer_vat_id"] == "abstained"
    assert not s["doc"]["conformant"]
    assert any(u["null_like"] for u in s["units"])


def test_accept_and_partial(tasks):
    t = tasks["fixture-invoice-1"]
    g = gold_instance(t)
    g["seller"]["name"] = "Northwind Supplies Limited"
    assert outcomes(score_task(t, pred(g)))["/seller/name"] == "correct"
    g["seller"]["name"] = "Northwind Supplies"            # the legal form is optional
    assert outcomes(score_task(t, pred(g)))["/seller/name"] == "correct"
    g["seller"]["name"] = "Northwind"
    s = score_task(t, pred(g))
    u = next(u for u in s["units"] if u["unit"] == "/seller/name")
    assert u["outcome"] == "wrong" and u["partial"]


def test_excluded_fields_are_not_scored(tasks):
    t = tasks["fixture-opinion-1"]
    s = score_task(t, pred(gold_instance(t)))
    assert all(u["pointer"] != "/attorney" for u in s["units"])


def test_array_of_scalars(tasks):
    t = tasks["fixture-opinion-1"]
    g = gold_instance(t)
    g["judges"] = ["Daniel Okafor", "Judge Maria Lopez"]
    o = outcomes(score_task(t, pred(g)))
    assert o["/judges/0"] == "correct" and o["/judges/1"] == "correct"
    g["judges"] = ["Daniel Okafor", "Ruth Bader"]
    s = score_task(t, pred(g))
    o = outcomes(s)
    assert o["/judges/0"] == "omitted" and o["/judges/+1"] == "extra"


def test_month_first_locale(tasks):
    t = tasks["fixture-opinion-1"]
    g = gold_instance(t)
    g["decision_date"] = "06/30/2023"
    assert outcomes(score_task(t, pred(g)))["/decision_date"] == "correct"


def test_swapped_parties(tasks):
    t = tasks["fixture-opinion-1"]
    g = gold_instance(t)
    g["appellant"], g["appellee"] = g["appellee"], g["appellant"]
    o = outcomes(score_task(t, pred(g)))
    assert o["/appellant"] == "swapped" and o["/appellee"] == "swapped"


def test_fenced_counts_apart(tasks):
    t = tasks["fixture-opinion-1"]
    s = score_task(t, pred(gold_instance(t), status="fenced"))
    assert s["doc"]["fenced"] and s["doc"]["conformant"]
    assert doc_counts(s)["correct"] == doc_counts(s)["present"]


def test_bootstrap_and_paired(tasks):
    num, den = [3, 1, 4, 0, 2], [4, 2, 4, 1, 2]
    lo, hi = bootstrap_ci(num, den, n_boot=2000)
    point = sum(n / d for n, d in zip(num, den, strict=True)) / len(num)
    assert lo <= point <= hi
    r = paired_bootstrap(num, den, num, den, n_boot=500)
    assert r["diff"] == 0 and r["lo"] == 0 and r["hi"] == 0


def test_scoring_does_not_mutate_inputs(tasks):
    t = tasks["fixture-invoice-1"]
    before = copy.deepcopy(t)
    g = gold_instance(t)
    g["line_items"].append({"description": "Stapler", "quantity": 1, "line_total": 12.0})
    g["line_items"][0]["quantity"] = 99
    score_task(t, pred(g))
    assert t == before


def test_headline_score(tasks):
    gold = [score_task(t, pred(gold_instance(t))) for t in tasks.values()]
    h = headline(gold, n_boot=200)
    assert h["score"] == 1.0 and h["lo"] == 1.0 and set(h["tracks"]) == {t["track"] for t in tasks.values()}
    nulls = [score_task(t, baselines.null_all(t)) for t in tasks.values()]
    hn = headline(nulls, n_boot=200)
    for s in nulls:                                  # the all-null baseline earns exactly the absent share
        c = doc_counts(s)
        assert c["score_points"] == c["absent"]
    assert 0 < hn["score"] < 1
    failed = [score_task(t, None) for t in tasks.values()]
    assert headline(failed, n_boot=200)["score"] == 0.0


def test_silent_error_costs_a_point(tasks):
    t = tasks["fixture-invoice-1"]
    g = gold_instance(t)
    g["seller"]["postcode"] = "EC1A 1BB"            # one fabricated value
    c = doc_counts(score_task(t, pred(g)))
    assert c["score_points"] == c["correct"] + c["abstained"] - 1
    g2 = gold_instance(t)
    g2["seller"]["postcode"] = None                  # the same field left empty instead: a right abstention
    c2 = doc_counts(score_task(t, pred(g2)))
    assert c2["score_points"] == c["score_points"] + 2


def test_headline_weighs_tracks_equally(tasks):
    by_track = {}
    for t in tasks.values():
        by_track.setdefault(t["track"], t)
    if len(by_track) < 2:
        pytest.skip("fixtures hold one track")
    a, b = list(by_track.values())[:2]
    good, bad = score_task(a, pred(gold_instance(a))), score_task(b, None)
    h1 = headline([good, bad], n_boot=100)
    h3 = headline([good, good, good, bad], n_boot=100)
    assert h1["score"] == h3["score"] == 0.5


def test_item_accept_alternative_for_a_row_value():
    from docfieldbench.outcomes import _item_accept
    rec = {"item_accept": [{"field": "exchange", "gold": "Nasdaq", "value": "The Nasdaq Stock Market LLC"}]}
    assert _item_accept(rec, "exchange", "Nasdaq") == ["The Nasdaq Stock Market LLC"]
    assert _item_accept(rec, "exchange", "NYSE") == []
    assert _item_accept(rec, "name", "Nasdaq") == []
