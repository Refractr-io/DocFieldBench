import copy
from pathlib import Path

from docfieldbench.responses import parse_response
from docfieldbench.schema import (
    check_schema,
    conformance_errors,
    iter_fields,
    to_anthropic_tool,
    to_gemini,
    to_json_schema,
    to_openai_response_format,
)
from docfieldbench.tasks import gold_instance, load_tasks

FIX = Path(__file__).parent / "fixtures" / "tasks"


def _schema():
    return load_tasks(FIX / "t_invoice.json")[0]["schema"]


def test_fixture_schemas_conform():
    for t in load_tasks(FIX):
        assert check_schema(t["schema"]) == []


def test_rejections():
    s = _schema()
    bad = copy.deepcopy(s)
    bad["required"] = bad["required"][:-1]
    assert any("required" in e for e in check_schema(bad))
    bad = copy.deepcopy(s)
    bad["properties"]["paid"]["description"] = "whether it was paid"
    assert any("not allowed" in e for e in check_schema(bad))
    bad = copy.deepcopy(s)
    bad["properties"]["paid"] = {"type": "boolean"}
    assert check_schema(bad)
    bad = copy.deepcopy(s)
    bad["properties"]["paid"]["enum"] = [True, False, None]
    assert check_schema(bad)
    bad = copy.deepcopy(s)
    bad["properties"]["total_incl_tax"]["format"] = "date"
    assert check_schema(bad)
    bad = copy.deepcopy(s)
    bad["properties"]["line_items"]["items"]["properties"]["sub"] = {"type": "object", "properties": {},
                                                                      "required": [], "additionalProperties": False}
    bad["properties"]["line_items"]["items"]["required"].append("sub")
    assert any("flat" in e for e in check_schema(bad))


def test_iter_fields_pointers():
    assert [p for p, _ in iter_fields(_schema())] == [
        "/invoice_number", "/invoice_date", "/due_date", "/total_incl_tax", "/seller/name", "/seller/vat_id",
        "/seller/postcode", "/buyer_vat_id", "/line_items", "/paid"]


def test_conformance():
    t = load_tasks(FIX / "t_invoice.json")[0]
    g = gold_instance(t)
    assert conformance_errors(t["schema"], g) == []
    g2 = copy.deepcopy(g)
    g2["invoice_date"] = "2024-03"                     # reduced precision is ISO
    assert conformance_errors(t["schema"], g2) == []
    g2["invoice_date"] = "12/03/2024"
    assert conformance_errors(t["schema"], g2)
    g3 = copy.deepcopy(g)
    g3["total_incl_tax"] = "1234.56"
    assert conformance_errors(t["schema"], g3)
    g4 = copy.deepcopy(g)
    g4["extra_key"] = 1
    assert conformance_errors(t["schema"], g4)
    g5 = copy.deepcopy(g)
    g5["buyer_vat_id"] = "n/a"
    assert any("null-like" in e for e in conformance_errors(t["schema"], g5))


def test_converters():
    s = _schema()
    js = to_json_schema(s)
    assert "format" not in js["properties"]["invoice_date"]
    assert to_json_schema(s, keep_format=True)["properties"]["invoice_date"]["format"] == "date"
    assert to_openai_response_format(s)["json_schema"]["strict"] is True
    assert to_anthropic_tool(s)["input_schema"]["type"] == "object"
    g = to_gemini(s)
    assert g["type"] == "OBJECT" and g["propertyOrdering"] == list(s["properties"])
    assert g["properties"]["paid"] == {"type": "BOOLEAN", "nullable": True}
    assert g["properties"]["line_items"]["items"]["properties"]["quantity"]["nullable"] is True
    assert "nullable" not in g["properties"]["seller"]
    # the gold still validates against the converted plain schema
    t = load_tasks(FIX / "t_invoice.json")[0]
    assert conformance_errors(js, gold_instance(t)) == []


def test_parse_response():
    assert parse_response('{"a": 1}') == ("ok", {"a": 1})
    assert parse_response('```json\n{"a": 1}\n```') == ("fenced", {"a": 1})
    assert parse_response('Here you go: {"a": 1}')[0] == "unparseable"
    assert parse_response('{"a": 1')[0] == "unparseable"
    assert parse_response("   ") == ("empty", None)
    assert parse_response(None) == ("empty", None)
