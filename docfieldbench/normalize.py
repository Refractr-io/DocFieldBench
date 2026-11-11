"""Normalisation shared by the matchers: null-like values, text, identifiers, names, numbers, dates."""
from __future__ import annotations

import datetime as _dt
import re
import unicodedata

# Strings that mean "no value". Scored as null; a conformance failure, since the contract's null is JSON null.
NULL_STRINGS = {
    "", "null", "none", "nil", "n/a", "na", "nan", "-", "--", "—", "–", "unknown", "not found", "not available",
    "not specified", "not provided", "not stated", "not applicable", "not present", "not given",
}

TITLES = {
    "mr", "mrs", "ms", "miss", "mx", "dr", "prof", "sir", "madam", "hon", "honorable", "jr", "sr", "esq",
    "dhr", "mevr", "mw", "ir", "drs", "herr", "frau", "sra", "srta", "don", "dona", "lic", "ing", "m", "mme", "mlle",
    "justice", "judge", "presiding", "chief", "associate", "magistrate", "acting",
    "herrn", "monsieur", "madame", "heer", "mevrouw", "senor", "senora", "señor", "señora",
}

# legal forms, optional at the end of a company name ('Au bon moulin SARL' = 'Au bon moulin')
LEGAL_SUFFIXES = [tuple(s.split()) for s in (
    "gmbh", "ag", "kg", "ohg", "ug", "ek", "ev", "eg", "ag", "kgaa", "se", "mbh", "gmbh co kg", "co kg",
    "sarl", "sas", "sasu", "sa", "eurl", "sca", "snc",
    "ltd", "limited", "plc", "llp", "llc", "inc", "corp", "corporation", "co", "company",
    "bv", "nv", "vof", "cv",
    "srl", "spa", "sl", "slu", "sa de cv", "s de rl de cv", "s de rl", "de cv", "sapi de cv",
    # judicial suffixes ('COFFEE, J.' = 'COFFEE') and 'et al.'
    "j", "pj", "cj", "jj", "aj", "p j", "c j", "j j", "a j", "et al", "et als", "et at",
)]


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s).replace("−", "-")


def is_null_like_string(v) -> bool:
    return isinstance(v, str) and nfkc(v).strip().casefold() in NULL_STRINGS


def is_nullish(v) -> bool:
    """None, an empty container, or a null-like string."""
    return v is None or v == [] or v == {} or is_null_like_string(v)


def _strip_edge_punct(s: str) -> str:
    i, j = 0, len(s)
    while i < j and unicodedata.category(s[i])[0] in "PS":
        i += 1
    while j > i and unicodedata.category(s[j - 1])[0] in "PS":
        j -= 1
    return s[i:j]


def text_norm(v) -> str:
    """Casefolded, whitespace collapsed, punctuation stripped at both ends."""
    s = re.sub(r"\s+", " ", nfkc(str(v)).casefold()).strip()
    return _strip_edge_punct(s).strip()


_ID_LABEL = re.compile(r"^\s*(?:no|nos|nr|number|num|n°|nº)\s*[.:]?\s+(?=\S)", re.IGNORECASE)


def id_core(v) -> str:
    """An identifier without a leading number label: 'No. H034702' -> 'h034702' ('NO123' keeps its letters)."""
    return alnum(_ID_LABEL.sub("", nfkc(str(v)), count=1))


def alnum(v) -> str:
    """Letters and digits only, casefolded: 'DE 232 446 240' -> 'de232446240'."""
    return "".join(ch for ch in nfkc(str(v)).casefold() if ch.isalnum())


def bare_name(v) -> str:
    """A name without titles, a trailing legal form, and punctuation: 'Dr. Jane O'Brien' -> 'janeobrien',
    'Au bon moulin SARL' -> 'aubonmoulin', 'Acme S.A. de C.V.' -> 'acme'."""
    s = text_norm(v).replace("'", "").replace("’", "").replace(".", "")
    toks = [t for t in re.findall(r"\w+", s) if t not in TITLES]
    stripped = True
    while stripped and len(toks) > 1:
        stripped = False
        for suf in sorted(LEGAL_SUFFIXES, key=len, reverse=True):
            if len(toks) > len(suf) and tuple(toks[-len(suf):]) == suf:
                toks = toks[: -len(suf)]
                stripped = True
                break
    return "".join(toks)


def tokens(v) -> set[str]:
    return set(re.findall(r"\w+", text_norm(v)))


# ---------------------------------------------------------------------------------------------------------------
# numbers

_CURRENCY = re.compile(r"[€$£¥₹₽₩₺]|\b(?:eur|usd|gbp|mxn|chf|jpy|cad|aud|nzd|sek|nok|dkk|pln|czk|brl|inr|cny)\b")


def parse_number(v, decimal_hint: str | None = None) -> float | None:
    """A number from a JSON number or a formatted string ('1.234,56 €', '(12.50)', '1,234.56').

    `decimal_hint` (',' or '.') settles the one ambiguous shape, a single separator followed by exactly three digits
    ('1,234' or '1.234'): with ',' as the decimal mark it is a decimal, otherwise a thousands separator.
    """
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        x = float(v)
        return None if x != x else x
    if not isinstance(v, str):
        return None
    s = nfkc(v).strip().casefold()
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    s = _CURRENCY.sub("", s)
    s = re.sub(r"[\s'’_]", "", s)
    if s.endswith("-"):
        neg, s = True, s[:-1]
    if s.startswith("-"):
        neg, s = True, s[1:]
    elif s.startswith("+"):
        s = s[1:]
    if not s or not re.fullmatch(r"[0-9.,]+", s) or not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
    elif "," in s:
        parts = s.split(",")
        if len(parts) > 2:
            dec = "."
        elif len(parts[1]) == 3:
            dec = "," if decimal_hint == "," else "."
        else:
            dec = ","
    elif "." in s:
        parts = s.split(".")
        if len(parts) > 2:
            dec = ","
        elif len(parts[1]) == 3 and decimal_hint == ",":
            dec = ","
        else:
            dec = "."
    else:
        dec = "."
    thousands = "." if dec == "," else ","
    s = s.replace(thousands, "")
    if dec == ",":
        s = s.replace(",", ".")
    if s.count(".") > 1 or s in (".", ""):
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


# ---------------------------------------------------------------------------------------------------------------
# dates

_MONTH_WORDS = {
    1: "january jan januari januar janvier janv enero ene",
    2: "february feb februari februar fevrier février fevr févr febrero",
    3: "march mar maart mrt marz märz mär mars marzo",
    4: "april apr avril avr abril abr",
    5: "may mei mai mayo",
    6: "june jun juni juin junio",
    7: "july jul juli juillet juil julio",
    8: "august aug augustus aout août agosto ago",
    9: "september sep sept septembre septiembre setiembre set",
    10: "october oct oktober okt octobre octubre",
    11: "november nov novembre noviembre",
    12: "december dec dezember dez decembre décembre diciembre dic",
}
MONTHS = {w: m for m, words in _MONTH_WORDS.items() for w in words.split()}
_ISO = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")
_ISO_DT = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ]\d{2}:\d{2}")


def _valid(y: int, m: int | None = None, d: int | None = None) -> str | None:
    if not 1000 <= y <= 2999:
        return None
    if m is None:
        return f"{y:04d}"
    if not 1 <= m <= 12:
        return None
    if d is None:
        return f"{y:04d}-{m:02d}"
    try:
        _dt.date(y, m, d)
    except ValueError:
        return None
    return f"{y:04d}-{m:02d}-{d:02d}"


def _year(tok: str) -> int | None:
    if len(tok) == 4:
        return int(tok)
    if len(tok) == 2:
        yy = int(tok)
        return 2000 + yy if yy < 70 else 1900 + yy
    return None


def parse_date(v, order: str | None = None) -> tuple[str, bool] | None:
    """(ISO date at the precision given, whether the input already was that ISO string), or None.

    Accepts ISO dates (YYYY, YYYY-MM, YYYY-MM-DD), ISO date-times, numeric dates (D/M/Y, M/D/Y, Y/M/D with '.', '/'
    or '-'), and dates with month names in English, Dutch, German, Spanish and French. A numeric day/month that could
    be either is resolved by `order` ('DMY' or 'MDY'); without it, it stays unresolved (None).
    """
    if not isinstance(v, str):
        return None
    s = nfkc(v).strip()
    m = _ISO.match(s)
    if m:
        y, mo, d = (int(x) if x else None for x in m.groups())
        iso = _valid(y, mo, d)
        return (iso, True) if iso else None
    m = _ISO_DT.match(s)
    if m:
        iso = _valid(*(int(x) for x in m.groups()))
        return (iso, False) if iso else None
    m = re.fullmatch(r"(\d{1,4})[./-](\d{1,2})[./-](\d{1,4})", s)
    if m:
        a, b, c = m.groups()
        if len(a) == 4:
            iso = _valid(int(a), int(b), int(c))
            return (iso, False) if iso else None
        y = _year(c)
        if y is None:
            return None
        a, b = int(a), int(b)
        if a > 12 and b <= 12:
            day, mon = a, b
        elif b > 12 and a <= 12:
            day, mon = b, a
        elif a == b:
            day = mon = a
        elif order == "DMY":
            day, mon = a, b
        elif order == "MDY":
            day, mon = b, a
        else:
            return None
        iso = _valid(y, mon, day)
        return (iso, False) if iso else None
    # month names: '12 March 2024', 'March 12, 2024', '12-Mar-2024', '16/Oct/26', '12 de marzo de 2024'
    t = s.casefold()
    t = re.sub(r"\b(de|del|of|the|le|den|der)\b", " ", t)
    t = re.sub(r"(\d+)(st|nd|rd|th|er|e|º|°)\b", r"\1", t)
    toks = [x for x in re.split(r"[\s,./-]+", t) if x]
    months = [MONTHS[x] for x in toks if x in MONTHS]
    nums = [x for x in toks if x.isdigit()]
    if len(months) != 1 or not nums or len(toks) != len(nums) + 1:
        return None
    mon = months[0]
    if len(nums) == 1:
        y = _year(nums[0]) if len(nums[0]) == 4 else None
        iso = _valid(y, mon) if y else None
        return (iso, False) if iso else None
    if len(nums) != 2:
        return None
    x, z = nums
    if len(x) == 4:
        y, day = int(x), int(z)
    elif len(z) in (2, 4) and len(x) <= 2:
        y, day = _year(z), int(x)
    else:
        return None
    iso = _valid(y, mon, day) if y else None
    return (iso, False) if iso else None
