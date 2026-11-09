"""Is a gold value printed in the document? Build-time checks over the text layer, generous by design.

A value counts as visible when any reading the scorer would accept appears in the text: the same date in any common
format, the same amount in any common notation, the same identifier ignoring spaces and punctuation. Visibility
decides between `present` and `excluded`: a value we can't find is excluded (to be checked by a human), never
turned into an absent field, so a correct answer can't be scored as invented.
"""
from __future__ import annotations

import re

from ..normalize import alnum, parse_date, parse_number, text_norm

_NUMBER_TOKENS = [
    re.compile(r"(?<![\w.,])\d+(?:[.,'’]\d+)*(?![\w])"),
    re.compile(r"(?<![\w.,])\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?(?![\w])"),
]
_NEGATIVE = re.compile(r"[-−–]\s?(\d[\d.,'’]*\d|\d)(?![\d])|(?<![\w.,])(\d[\d.,'’]*\d)\s?-(?![\w\d])|"
                       r"\((\d[\d.,'’]*\d)\)")
_DATE_TOKENS = [
    re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)"),
    re.compile(r"(?<!\d)\d{1,2}[./-]\d{1,2}[./-]\d{2,4}(?!\d)"),
    re.compile(r"(?<!\d)\d{1,2}\.?\s+[A-Za-zÀ-ÿ]{3,10}\.?\s+\d{2,4}(?!\d)"),
    re.compile(r"\b[A-Za-zÀ-ÿ]{3,10}\.?\s+\d{1,2},?\s+\d{4}(?!\d)"),
]


class TextIndex:
    """Numbers and dates readable in a document's text, plus normalised forms for string lookups."""

    def __init__(self, pages: list[str]):
        self.pages = pages
        self.text = "\n".join(pages)
        self.norm = text_norm(self.text.replace("\n", " "))
        self.alnum = alnum(self.text)
        self.numbers: set[float] = set()
        for rx in _NUMBER_TOKENS:
            for m in rx.finditer(self.text):
                for hint in (",", "."):
                    x = parse_number(m.group(0), hint)
                    if x is not None:
                        self.numbers.add(round(abs(x), 4))
        self.negatives: set[float] = set()           # numbers printed with a minus or in parentheses
        for m in _NEGATIVE.finditer(self.text):
            tok = next(g for g in m.groups() if g)
            for hint in (",", "."):
                x = parse_number(tok, hint)
                if x is not None:
                    self.negatives.add(round(abs(x), 4))
        self.dates: set[str] = set()
        for rx in _DATE_TOKENS:
            for m in rx.finditer(self.text):
                for order in ("DMY", "MDY"):
                    d = parse_date(m.group(0), order)
                    if d:
                        self.dates.add(d[0])

    def has_number(self, value) -> bool:
        v = parse_number(value)
        return v is not None and any(abs(abs(v) - n) <= 0.005 for n in self.numbers)

    def printed_negative(self, value) -> bool:
        """The amount appears with a minus sign or in parentheses (a deduction, a credit note line)."""
        v = parse_number(value)
        return v is not None and v != 0 and any(abs(abs(v) - n) <= 0.005 for n in self.negatives)

    def has_date(self, value) -> bool:
        d = parse_date(str(value))
        return d is not None and d[0] in self.dates

    def has_string(self, value, min_alnum: int = 4) -> bool:
        n = text_norm(value)
        if n and n in self.norm:
            return True
        a = alnum(value)
        return len(a) >= min_alnum and a in self.alnum

    def visible(self, kind: str, value) -> bool:
        if value is None:
            return False
        if kind in ("amount", "number", "integer"):
            return self.has_number(value)
        if kind == "date":
            return self.has_date(value)
        return self.has_string(value)

    def has_label(self, labels) -> bool:
        return any(text_norm(lb) in self.norm for lb in labels)

    def label_with_value(self, labels, kind: str, window: int = 80) -> bool:
        """Some label is followed (within `window` characters of reading order) by a value of this kind.

        "Zahlbar innerhalb 30 Tagen" prints a due-date label but no date: computing one would be inference, so the
        field is absent. A label with a value after it means the document may state the field: not provably absent.
        """
        flat = re.sub(r"\s+", " ", self.text)
        low = flat.casefold()
        for lb in labels:
            for m in re.finditer(re.escape(lb.casefold()), low):
                after = flat[m.end():m.end() + window]
                if kind == "date":
                    if TextIndex([after]).dates:
                        return True
                elif kind in ("amount", "number", "integer"):
                    if re.search(r"\d", after):
                        return True
                elif re.search(r"[0-9]", after) or re.search(r"[A-Za-z]{2,}\d|\d[A-Za-z]", after):
                    return True
        return False

    def evidence(self, kind: str, value) -> dict | None:
        """The first page and line where the value can be read (for the gold record)."""
        for p, page in enumerate(self.pages, 1):
            for line in page.splitlines():
                if line.strip() and TextIndex([line]).visible(kind, value):
                    return {"page": p, "text": line.strip()[:200]}
        return None
