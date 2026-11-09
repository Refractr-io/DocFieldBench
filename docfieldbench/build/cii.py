"""Parse UN/CEFACT Cross Industry Invoice XML (ZUGFeRD 1.0, ZUGFeRD 2.x / Factur-X, XRechnung CII) into one record.

Elements are found by local name, so both namespace generations work. Values are taken as the XML states them; which
of them the document actually prints is decided later (visibility).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(node, *steps):
    """First match of a chain of local names, each step searched among all descendants of the previous match."""
    if node is None:
        return None
    cur = [node]
    for s in steps:
        nxt = [d for n in cur for d in n.iter() if d is not n and _local(d.tag) == s]
        if not nxt:
            return None
        cur = nxt
    return cur[0]


def _children(node, name):
    return [c for c in (node if node is not None else []) if _local(c.tag) == name]


def _child(node, name):
    found = _children(node, name)
    return found[0] if found else None


def _txt(node) -> str | None:
    if node is None or node.text is None:
        return None
    s = node.text.strip()
    return s or None


def _date102(node) -> str | None:
    s = _txt(_find(node, "DateTimeString")) if node is not None else None
    if s and re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return None


def _num(s: str | None) -> float | None:
    try:
        return float(s) if s is not None else None
    except ValueError:
        return None


def _name(node) -> str | None:
    s = _txt(node)
    if s and "\n" in s:                      # "GLN 4333741000005\nSupplier no 549910\nSUPPLIER LTD": the last line names it
        s = s.splitlines()[-1].strip()
    return s


def _party(root, role) -> dict:
    p = _find(root, role)
    if p is None:
        return {}
    addr = _child(p, "PostalTradeAddress")
    lines = [_txt(_child(addr, n)) for n in ("LineOne", "LineTwo", "LineThree")]
    lines = [x for x in lines if x]
    # LineOne is sometimes a contact person or "c/o" line; the street is the line with a house number
    street = next((x for x in lines if re.search(r"\d", x)), lines[0] if lines else None)
    out = {
        "name": _name(_child(p, "Name")),
        "id": _txt(_child(p, "ID")),
        "street": street,
        "postcode": _txt(_child(addr, "PostcodeCode")),
        "city": _txt(_child(addr, "CityName")),
        "country": _txt(_child(addr, "CountryID")),
        "vat_id": None,
        "tax_number": None,
    }
    for reg in _children(p, "SpecifiedTaxRegistration"):
        i = _child(reg, "ID")
        if i is not None and i.get("schemeID") == "VA":
            out["vat_id"] = _txt(i)
        elif i is not None and i.get("schemeID") == "FC":
            out["tax_number"] = _txt(i)
    return out


def _line_items(root) -> list[dict]:
    rows = []
    for li in (d for d in root.iter() if _local(d.tag) == "IncludedSupplyChainTradeLineItem"):
        desc = _txt(_find(li, "SpecifiedTradeProduct", "Name"))
        if desc:
            desc = re.sub(r"\s+", " ", desc)
        rows.append({
            "description": desc,
            "quantity": _num(_txt(_find(li, "BilledQuantity"))),
            "unit_price": _num(_txt(_find(li, "NetPriceProductTradePrice", "ChargeAmount"))),
            "line_total": _num(_txt(_find(li, "LineTotalAmount"))),
        })
    return rows


def parse_cii(xml: bytes) -> dict:
    root = ET.fromstring(xml)
    if _local(root.tag) not in ("CrossIndustryInvoice", "CrossIndustryDocument"):
        raise ValueError(f"not a CII invoice: {_local(root.tag)}")
    doc = _find(root, "ExchangedDocument")
    if doc is None:
        doc = _find(root, "HeaderExchangedDocument")
    seller, buyer = _party(root, "SellerTradeParty"), _party(root, "BuyerTradeParty")

    def amount(name):
        return _num(_txt(_find(root, name)))

    return {
        "type_code": _txt(_child(doc, "TypeCode")),
        "invoice_number": _txt(_child(doc, "ID")),
        "invoice_date": _date102(_child(doc, "IssueDateTime")),
        "delivery_date": _date102(_find(root, "ActualDeliverySupplyChainEvent", "OccurrenceDateTime")),
        "due_date": _date102(_find(root, "SpecifiedTradePaymentTerms", "DueDateDateTime")),
        "order_number": _txt(_find(root, "BuyerOrderReferencedDocument", "IssuerAssignedID")),
        "delivery_note_number": _txt(_find(root, "DespatchAdviceReferencedDocument", "IssuerAssignedID")),
        "customer_number": buyer.get("id"),
        "seller": seller,
        "buyer": buyer,
        "iban": _txt(_find(root, "PayeePartyCreditorFinancialAccount", "IBANID")),
        "net_total": amount("TaxBasisTotalAmount"),
        "tax_total": amount("TaxTotalAmount"),
        "total_incl_tax": amount("GrandTotalAmount"),
        "prepaid_amount": amount("TotalPrepaidAmount"),
        "amount_due": amount("DuePayableAmount"),
        "line_items": _line_items(root),
    }
