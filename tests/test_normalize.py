import pytest

from docfieldbench.matchers import same
from docfieldbench.normalize import alnum, bare_name, is_nullish, parse_date, parse_number


@pytest.mark.parametrize("raw,hint,want", [
    (1234.56, None, 1234.56),
    ("1234.56", None, 1234.56),
    ("1,234.56", None, 1234.56),
    ("1.234,56", None, 1234.56),
    ("1.234,56 €", ",", 1234.56),
    ("€ 1.234,56", ",", 1234.56),
    ("$1,234", None, 1234.0),
    ("1,234", ",", 1.234),
    ("1.234", ",", 1234.0),
    ("12,50", None, 12.5),
    ("(12.50)", None, -12.5),
    ("12.50-", None, -12.5),
    ("−7,00", None, -7.0),
    ("1'234.50", None, 1234.5),
    ("1 234 567,89", None, 1234567.89),
    ("abc", None, None),
    ("", None, None),
    (True, None, None),
])
def test_parse_number(raw, hint, want):
    got = parse_number(raw, hint)
    assert (got is None and want is None) or abs(got - want) < 1e-9


@pytest.mark.parametrize("raw,order,want", [
    ("2024-03-12", None, ("2024-03-12", True)),
    ("2024-03", None, ("2024-03", True)),
    ("2024", None, ("2024", True)),
    ("2024-02-30", None, None),
    ("2024-03-12T10:00:00Z", None, ("2024-03-12", False)),
    ("12.03.2024", "DMY", ("2024-03-12", False)),
    ("03/12/2024", "MDY", ("2024-03-12", False)),
    ("03/12/2024", None, None),
    ("25/12/2024", None, ("2024-12-25", False)),
    ("12 March 2024", None, ("2024-03-12", False)),
    ("March 12, 2024", None, ("2024-03-12", False)),
    ("12. März 2024", None, ("2024-03-12", False)),
    ("12 de marzo de 2024", None, ("2024-03-12", False)),
    ("16/Oct/26", None, ("2026-10-16", False)),
    ("3 nov. 2026", None, ("2026-11-03", False)),
    ("1er janvier 2025", None, ("2025-01-01", False)),
    ("maart 2024", None, ("2024-03", False)),
    ("not a date", None, None),
])
def test_parse_date(raw, order, want):
    assert parse_date(raw, order) == want


def test_text_helpers():
    assert alnum("DE 232 446 240") == "de232446240"
    assert bare_name("Dr. Jane O'Brien") == "janeobrien"
    assert is_nullish("N/A") and is_nullish("") and is_nullish(None) and is_nullish([])
    assert not is_nullish("0")


@pytest.mark.parametrize("kind,gold,pred,ok", [
    ("id", "DE232446240", "DE 232 446 240", True),
    ("id", "INV-001", "INV-002", False),
    ("id", "471102", 471102, True),
    ("amount", 19.0, "19,00", True),
    ("amount", 19.0, 19.004, True),
    ("amount", 19.0, 19.01, False),
    ("integer", 3, "3", True),
    ("integer", 3, 3.5, False),
    ("boolean", True, "yes", True),
    ("boolean", False, True, False),
    ("name", "O'BRIEN", "Justice O'Brien", True),
    ("name", "Acme Corp.", "acme corp", True),
    ("short_text", "Ave. Sta Margarita #3600", "Ave Sta Margarita 3600", True),
    ("short_text", "Paper A4", "Paper A3", False),
    ("date", "2024-03", "2024-03-01", False),
    ("name", "Au bon moulin", "Au bon moulin SARL", True),
    ("name", "MUSTER-Autovermietung GMBH", "Muster-Autovermietung", True),
    ("name", "Acme S.A. de C.V.", "ACME", True),
    ("name", "Max Mustermann", "Herrn Max Mustermann", True),
    ("name", "MUSTERLIEFERANT GMBH", "KOSTENLIEFERANT GMBH", False),
    ("short_text", "Au bon moulin", "Au bon moulin SARL", False),
])
def test_same(kind, gold, pred, ok):
    assert same(kind, gold, pred, {"decimal": ","}) is ok
