"""Document families: one hand-written schema per family, the match kind per field, and the labels used to confirm
that a field is absent (de, en, fr, nl).

A field missing from a document's structured data is called absent only when the check can prove it: none of its
labels appear, and (where a pattern exists) no value of its shape is printed beyond the ones accounted for. Otherwise
it is excluded with a reason.
"""
from __future__ import annotations

import re


def _s():
    return {"type": ["string", "null"]}


def _d():
    return {"type": ["string", "null"], "format": "date"}


def _n():
    return {"type": ["number", "null"]}


def _obj(props: dict) -> dict:
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


INVOICE_SCHEMA = _obj({
    "invoice_number": _s(),
    "invoice_date": _d(),
    "delivery_date": _d(),
    "due_date": _d(),
    "order_number": _s(),
    "delivery_note_number": _s(),
    "customer_number": _s(),
    "seller": _obj({"name": _s(), "vat_id": _s(), "tax_number": _s(), "street": _s(), "postcode": _s(), "city": _s()}),
    "buyer": _obj({"name": _s(), "vat_id": _s(), "street": _s(), "postcode": _s(), "city": _s()}),
    "iban": _s(),
    "net_total": _n(),
    "tax_total": _n(),
    "total_incl_tax": _n(),
    "prepaid_amount": _n(),
    "amount_due": _n(),
    "line_items": {"type": ["array", "null"], "items": _obj({
        "description": _s(), "quantity": _n(), "unit_price": _n(), "line_total": _n()})},
})

INVOICE_MATCH = {
    "/invoice_number": "id", "/invoice_date": "date", "/delivery_date": "date", "/due_date": "date",
    "/order_number": "id", "/delivery_note_number": "id", "/customer_number": "id",
    "/seller/name": "name", "/seller/vat_id": "id", "/seller/tax_number": "id", "/seller/street": "short_text",
    "/seller/postcode": "id", "/seller/city": "short_text",
    "/buyer/name": "name", "/buyer/vat_id": "id", "/buyer/street": "short_text", "/buyer/postcode": "id",
    "/buyer/city": "short_text",
    "/iban": "id", "/net_total": "amount", "/tax_total": "amount", "/total_incl_tax": "amount",
    "/prepaid_amount": "amount", "/amount_due": "amount",
}
LINE_ITEM_MATCH = {"description": "short_text", "quantity": "number", "unit_price": "amount", "line_total": "amount"}

INVOICE_LABELS = {
    "/delivery_date": ["lieferdatum", "leistungsdatum", "liefertermin", "leistungszeitraum", "lieferzeitraum",
                       "delivery date", "date of supply", "service date", "date de livraison", "leverdatum",
                       "leveringsdatum"],
    "/due_date": ["fällig", "faellig", "zahlbar bis", "zahlungsziel", "zahlbar innerhalb", "due date", "payable by",
                  "due by", "échéance", "echeance", "vervaldatum", "te betalen voor"],
    "/order_number": ["bestellnummer", "bestell-nr", "bestellnr", "ihre bestellung", "auftragsnummer", "auftrags-nr",
                      "your order", "order number", "order no", "purchase order", "po number", "bon de commande",
                      "numéro de commande", "n° de commande", "commande n", "bestelnummer", "ordernummer",
                      "uw bestelling"],
    "/delivery_note_number": ["lieferschein", "delivery note", "despatch advice", "dispatch note",
                              "bon de livraison", "pakbon", "leverbon"],
    "/customer_number": ["kundennummer", "kunden-nr", "kundennr", "kd.-nr", "kd-nr", "ihre nummer",
                         "customer number", "customer no", "customer id", "customer:", "numéro client", "n° client",
                         "code client", "klantnummer", "klantnr"],
    "/seller/tax_number": ["steuernummer", "steuer-nr", "steuernr", "st.-nr", "st-nr", "tax number", "tax no"],
    "/iban": ["iban"],
    "/prepaid_amount": ["anzahlung", "bereits gezahlt", "bereits bezahlt", "vorauszahlung", "geleistete zahlung",
                        "prepaid", "already paid", "advance payment", "acompte", "déjà payé", "deja paye",
                        "aanbetaling", "vooruitbetaling"],
    "/amount_due": ["zahlbetrag", "zu zahlen", "offener betrag", "fälliger betrag", "amount due", "balance due",
                    "total due", "net à payer", "reste à payer", "montant dû", "te betalen"],
    "/line_items": ["pos.", "menge", "artikel", "bezeichnung", "einzelpreis", "quantity", "qty", "description",
                    "unit price", "quantité", "désignation", "prix unitaire", "aantal", "omschrijving"],
}

# value shapes, each anchored at token boundaries (a label in front, like "IBAN DE75...", stays separate)
_VAT = re.compile(
    r"(?<![A-Z0-9])(?:DE ?\d{3} ?\d{3} ?\d{3}|ATU ?\d{8}|FR ?[0-9A-Z]{2} ?\d{3} ?\d{3} ?\d{3}|NL ?\d{9} ?B ?\d{2}|"
    r"BE ?0?\d{3}[ .]?\d{3}[ .]?\d{3}|LU ?\d{8}|IT ?\d{11}|ES ?[0-9A-Z]\d{7}[0-9A-Z]|"
    r"GB ?\d{3} ?\d{4} ?\d{2}(?: ?\d{3})?|CHE[- ]?\d{3}\.?\d{3}\.?\d{3})(?![A-Z0-9])")
_IBAN = re.compile(r"(?<![A-Z0-9])[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?(?![A-Z0-9])")


def _compact(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def vat_numbers(text: str) -> set[str]:
    return {_compact(m.group(0)) for m in _VAT.finditer(text.upper())}


def ibans(text: str) -> set[str]:
    """IBAN-shaped values printed in the text, grouped or not. No checksum test: example documents print fake IBANs,
    and those are still values a system can extract."""
    return {c for m in _IBAN.finditer(text.upper())
            if 15 <= len(c := _compact(m.group(0))) <= 34 and sum(ch.isdigit() for ch in c[4:]) >= 8}
