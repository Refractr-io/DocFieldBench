"""Locale formatting for rendered documents: dates, amounts, quantities."""
from __future__ import annotations

import datetime as dt

from .vocab import LOCALES

MONTHS = {"en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                 "November", "December"],
          "de": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
                 "November", "Dezember"],
          "nl": ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober",
                 "november", "december"]}


def date(iso: str | None, loc: str, style: str = "num") -> str:
    if not iso:
        return ""
    d = dt.date.fromisoformat(iso)
    lg = LOCALES[loc]["lang"]
    if style == "long" and lg in MONTHS:
        m = MONTHS[lg][d.month - 1]
        return {"en-US": f"{m} {d.day}, {d.year}", "en-GB": f"{d.day} {m} {d.year}", "de-DE": f"{d.day}. {m} {d.year}",
                "nl-NL": f"{d.day} {m} {d.year}"}[loc]
    if style == "short" and lg == "en":
        m = MONTHS["en"][d.month - 1][:3]
        return f"{m} {d.day}, {d.year}" if loc == "en-US" else f"{d.day:02d} {m} {d.year}"
    if style == "iso":
        return iso
    return {"en-US": f"{d.month:02d}/{d.day:02d}/{d.year}", "en-GB": f"{d.day:02d}/{d.month:02d}/{d.year}",
            "de-DE": f"{d.day:02d}.{d.month:02d}.{d.year}", "nl-NL": f"{d.day:02d}-{d.month:02d}-{d.year}",
            "es-ES": f"{d.day:02d}/{d.month:02d}/{d.year}"}[loc]


def number(x: float, loc: str, decimals: int = 2, group: bool = True) -> str:
    s = f"{abs(x):,.{decimals}f}" if group else f"{abs(x):.{decimals}f}"
    if LOCALES[loc]["decimal"] == ",":
        s = s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return ("-" if x < 0 else "") + s


def money(x: float | None, loc: str, symbol: bool = True) -> str:
    if x is None:
        return ""
    s = number(x, loc)
    if not symbol:
        return s
    c = LOCALES[loc]
    neg = s.startswith("-")
    s = s.lstrip("-")
    out = f"{s} {c['cur']}" if c["cur_after"] else (f"{c['cur']} {s}" if loc == "nl-NL" else f"{c['cur']}{s}")
    return ("-" if neg else "") + out


def qty(x: float, loc: str) -> str:
    if float(x).is_integer():
        return str(int(x))
    return number(x, loc, decimals=2 if round(x, 2) != round(x, 1) else 1, group=False)


def pct(rate: float, loc: str) -> str:
    v = rate * 100
    s = str(int(v)) if float(v).is_integer() else number(v, loc, decimals=2, group=False).rstrip("0")
    return f"{s}%" if LOCALES[loc]["lang"] == "en" else f"{s} %"
