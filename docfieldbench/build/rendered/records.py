"""Gold-first records. Every value is decided here; templates only draw them. A field set to None is not drawn, so
it is absent by construction. Decoys are look-alike values a real document prints next to the asked ones (a company
registration number beside the VAT number, a terminal id beside the receipt number); they never fill a field."""
from __future__ import annotations

import datetime as dt
import random
import string

from .vocab import (
    BANKS,
    CARRIERS,
    CITIES,
    CO_PREFIX,
    CO_TRADE,
    FIRST,
    INVOICE_ITEMS,
    LAST,
    LEGAL,
    LOCALES,
    PARTS,
    PAYSLIP,
    SHOP,
    STREETS,
)


def r2(x: float) -> float:
    return round(x + 1e-9, 2)


def lang(loc: str) -> str:
    return LOCALES[loc]["lang"]


def digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(string.digits) for _ in range(n))


def letters(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(string.ascii_uppercase) for _ in range(n))


def person(rng, loc):
    return f"{rng.choice(FIRST[loc])} {rng.choice(LAST[loc])}"


def company(rng, loc, trade=None):
    lg = lang(loc)
    trade = trade or rng.choice(CO_TRADE[lg])
    pre = rng.choice(CO_PREFIX[lg])
    name = f"{pre} {trade}" if lg != "es" else f"{trade} {pre}"
    return f"{name} {rng.choice(LEGAL[loc])}"


def address(rng, loc):
    street = rng.choice(STREETS[loc])
    no = str(rng.randint(1, 180))
    if rng.random() < 0.15:
        no += rng.choice("ab") if loc in ("de-DE", "nl-NL") else ""
    city, region, pc = rng.choice(CITIES[loc])
    if loc in ("en-US", "en-GB"):
        line = f"{no} {street}"
    elif loc == "es-ES":
        line = f"{street}, {no}"
    else:
        line = f"{street} {no}"
    return {"street": line, "postcode": pc, "city": city, "region": region}


def vat_id(rng, loc):
    return {"en-GB": "GB" + digits(rng, 9), "de-DE": "DE" + digits(rng, 9), "nl-NL": "NL" + digits(rng, 9) + "B01",
            "es-ES": "ES" + rng.choice("ABG") + digits(rng, 8)}.get(loc)


def tax_number(rng, loc):
    if loc == "en-US":
        return f"{digits(rng, 2)}-{digits(rng, 7)}"
    if loc == "de-DE":
        return f"{digits(rng, 2)}/{digits(rng, 3)}/{digits(rng, 5)}"
    return None


def _iban_check(country: str, bban: str) -> str:
    s = "".join(str(int(c, 36)) for c in bban + country + "00")
    return f"{98 - int(s) % 97:02d}"


def iban(rng, loc):
    c = {"en-GB": "GB", "de-DE": "DE", "nl-NL": "NL", "es-ES": "ES"}.get(loc)
    if c is None:
        return None
    bban = {"GB": lambda: letters(rng, 4) + digits(rng, 14), "DE": lambda: digits(rng, 18),
            "NL": lambda: letters(rng, 4) + digits(rng, 10), "ES": lambda: digits(rng, 20)}[c]()
    return c + _iban_check(c, bban) + bban


def phone(rng, loc):
    return {"en-US": f"(555) 01{digits(rng, 2)}-{digits(rng, 4)}", "en-GB": f"01632 960{digits(rng, 3)}",
            "de-DE": f"+49 {rng.choice(['40', '221', '341', '711'])} {digits(rng, 6)}",
            "nl-NL": f"+31 {rng.choice(['30', '50', '40', '71'])} {digits(rng, 3)} {digits(rng, 4)}",
            "es-ES": f"+34 9{digits(rng, 2)} {digits(rng, 3)} {digits(rng, 3)}"}[loc]


def day(rng, start=dt.date(2026, 8, 3), span=95) -> dt.date:
    return start + dt.timedelta(days=rng.randint(0, span))


def iso(d: dt.date | None) -> str | None:
    return d.isoformat() if d else None


def maybe(rng, p, value):
    return value if rng.random() < p else None


VAT_RATE = {"en-US": 0.0, "en-GB": 0.20, "de-DE": 0.19, "nl-NL": 0.21, "es-ES": 0.21}
SALES_TAX = [0.0625, 0.0725, 0.08, 0.0825, 0.06]


# --------------------------------------------------------------------------------------------- invoice

def invoice(rng, loc):
    lg = lang(loc)
    seller_trade = rng.choice(CO_TRADE[lg])
    s_addr, b_addr = address(rng, loc), address(rng, loc)
    d = day(rng)
    items = rng.sample(INVOICE_ITEMS[lg], rng.randint(1, 6))
    rows = []
    for desc, unit, price in items:
        q = rng.choice([1, 1, 2, 3, 5, 10]) if unit not in ("h", "Std.", "uur") else rng.choice([2, 4, 6.5, 8, 12, 16])
        up = r2(price * rng.uniform(0.85, 1.2))
        rows.append({"description": desc, "unit": unit, "quantity": q, "unit_price": up, "line_total": r2(q * up)})
    net = r2(sum(r["line_total"] for r in rows))
    rate = VAT_RATE[loc] if loc != "en-US" else rng.choice([0.0, 0.0] + SALES_TAX)
    tax = r2(net * rate)
    total = r2(net + tax)
    prepaid = r2(total * rng.choice([0.3, 0.5])) if rng.random() < 0.15 else None
    due_amount = r2(total - (prepaid or 0)) if (prepaid or rng.random() < 0.7) else None
    seller = {"name": company(rng, loc, seller_trade), **s_addr, "vat_id": maybe(rng, 0.95, vat_id(rng, loc)),
              "tax_number": maybe(rng, 0.6, tax_number(rng, loc)), "phone": phone(rng, loc)}
    if loc == "es-ES" and seller["vat_id"]:
        seller["nif_only"] = rng.random() < 0.5            # print just "NIF B12345678": vat_id excluded then
    b2b = rng.random() < 0.85
    buyer = {"name": company(rng, loc) if b2b else person(rng, loc), **b_addr,
             "vat_id": maybe(rng, 0.45, vat_id(rng, loc)) if b2b else None,
             "attn": person(rng, loc) if b2b and rng.random() < 0.4 else None}
    rec = {
        "invoice_number": rng.choice([f"INV-{d.year}-{digits(rng, 4)}", f"RE-{d.year % 100}-{digits(rng, 4)}",
                                      f"F{d.year}/{digits(rng, 4)}", f"{d.year}-{d.month:02d}-{digits(rng, 4)}",
                                      f"{digits(rng, 6)}"]),
        "invoice_date": iso(d),
        "delivery_date": iso(maybe(rng, 0.45, d - dt.timedelta(days=rng.randint(0, 10)))),
        "due_date": iso(maybe(rng, 0.65, d + dt.timedelta(days=rng.choice([14, 30, 30, 45])))),
        "order_number": maybe(rng, 0.45, rng.choice([f"PO-{digits(rng, 5)}", f"{digits(rng, 7)}",
                                                     f"B{digits(rng, 2)}-{digits(rng, 4)}"])),
        "delivery_note_number": maybe(rng, 0.2, f"LS-{digits(rng, 6)}" if lg == "de" else f"DN-{digits(rng, 6)}"),
        "customer_number": maybe(rng, 0.6, rng.choice([f"C{digits(rng, 5)}", f"{digits(rng, 5)}",
                                                       f"KD-{digits(rng, 4)}"])),
        "seller": seller, "buyer": buyer, "iban": maybe(rng, 0.8, iban(rng, loc)),
        "net_total": net, "tax_total": tax if rate else None, "tax_rate": rate, "total_incl_tax": total,
        "prepaid_amount": prepaid, "amount_due": due_amount, "line_items": rows,
    }
    decoys = {"buyer_reference": maybe(rng, 0.35, f"REF {letters(rng, 2)}{digits(rng, 4)}"),
              "company_reg": {"en-GB": f"{digits(rng, 8)}", "nl-NL": f"{digits(rng, 8)}",
                              "de-DE": f"HRB {digits(rng, 5)}"}.get(loc) if rng.random() < 0.6 else None,
              "routing": f"0{digits(rng, 8)}" if loc == "en-US" and rng.random() < 0.6 else None,
              "account": digits(rng, 10) if loc == "en-US" else None,
              "terms_days": rng.choice([14, 30]) if not rec["due_date"] and rng.random() < 0.5 else None,
              "bic": letters(rng, 6) + letters(rng, 2) if rec["iban"] and rng.random() < 0.5 else None}
    return rec, decoys


# --------------------------------------------------------------------------------------------- receipt

def receipt(rng, loc):
    lg = lang(loc)
    kind = rng.choice(list(SHOP))
    trade, items = SHOP[kind][lg]
    pre = rng.choice(CO_PREFIX[lg])
    name = f"{pre} {trade}" if lg != "es" else f"{trade} {pre}"
    if rng.random() < 0.4:
        name += " " + rng.choice(LEGAL[loc])
    addr = address(rng, loc)
    picks = rng.sample(items, rng.randint(2, min(7, len(items))))
    rows = []
    for desc, price in picks:
        q = 1 if rng.random() < 0.7 else rng.randint(2, 4)
        rows.append({"description": desc, "quantity": q, "unit_price": price, "line_total": r2(q * price)})
    gross = r2(sum(r["line_total"] for r in rows))
    if loc == "en-US":
        rate = rng.choice(SALES_TAX)
        subtotal, tax = gross, r2(gross * rate)
        total = r2(subtotal + tax)
    else:
        rate = {"cafe": 0.07, "grocery": 0.07}.get(kind, 0.19) if loc == "de-DE" else (
            {"cafe": 0.09, "grocery": 0.09}.get(kind, 0.21) if loc == "nl-NL" else (
                {"cafe": 0.10, "grocery": 0.10}.get(kind, 0.21) if loc == "es-ES" else
                {"cafe": 0.20, "grocery": 0.0}.get(kind, 0.20)))
        total = gross
        tax = r2(total - total / (1 + rate)) if rate else None
        subtotal = r2(total - (tax or 0)) if rate and rng.random() < 0.5 else None
    tip = r2(total * rng.choice([0.15, 0.18, 0.2])) if kind == "cafe" and loc == "en-US" and rng.random() < 0.5 else None
    pay = rng.choice(["card", "card", "cash"])
    method = {"cash": {"en": "Cash", "de": "Bar", "nl": "Contant", "es": "Efectivo"}[lg],
              "card": rng.choice({"en": ["Visa", "Mastercard", "Debit card"], "de": ["Girocard", "Visa", "Mastercard"],
                                  "nl": ["PIN", "Maestro", "Visa"], "es": ["Tarjeta", "Visa", "Mastercard"]}[lg])}[pay]
    d = day(rng)
    rec = {"merchant": {"name": name, "street": addr["street"], "postcode": addr["postcode"], "city": addr["city"],
                        "region": addr["region"], "vat_id": maybe(rng, 0.8, vat_id(rng, loc)),
                        "phone": maybe(rng, 0.6, phone(rng, loc))},
           "receipt_number": maybe(rng, 0.8, rng.choice([digits(rng, 4), f"{digits(rng, 3)}-{digits(rng, 4)}",
                                                         f"R{digits(rng, 6)}"])),
           "date": iso(d), "time": f"{rng.randint(7, 20):02d}:{rng.randint(0, 59):02d}",
           "payment_method": maybe(rng, 0.9, method), "card_last4": digits(rng, 4) if pay == "card" and
           rng.random() < 0.8 else None, "subtotal": subtotal, "tax_total": tax, "tax_rate": rate, "total": r2(total + (tip or 0)),
           "tip": tip, "line_items": rows, "kind": kind, "cash_given": None}
    if pay == "cash" and rec["payment_method"]:
        rec["cash_given"] = float(int(rec["total"] / 5 + 1) * 5)
    if not rec["payment_method"]:
        rec["card_last4"] = None                 # a card number without a payment line would state the method
    decoys = {"terminal": maybe(rng, 0.6, f"T{digits(rng, 6)}"), "auth": maybe(rng, 0.5, letters(rng, 2) + digits(rng, 4)),
              "cashier": maybe(rng, 0.5, rng.choice(FIRST[loc])), "till": maybe(rng, 0.5, str(rng.randint(1, 9))),
              "trans": maybe(rng, 0.5, digits(rng, 6))}
    return rec, decoys


# --------------------------------------------------------------------------------------------- statements

def bank_statement(rng, loc):
    lg = lang(loc)
    start = dt.date(2026, rng.choice([8, 9, 10]), 1)
    end = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    opening = r2(rng.uniform(800, 9000))
    desc = {"en": ["Card payment {m}", "Direct debit {m}", "Transfer from {p}", "ATM withdrawal", "Salary {c}",
                   "Standing order rent", "Online payment {m}", "Interest"],
            "de": ["Kartenzahlung {m}", "Lastschrift {m}", "Überweisung von {p}", "Bargeldauszahlung", "Gehalt {c}",
                   "Dauerauftrag Miete", "Online-Zahlung {m}", "Zinsen"],
            "nl": ["Betaalpas {m}", "Incasso {m}", "Overboeking van {p}", "Geldopname", "Salaris {c}",
                   "Periodieke overboeking huur", "iDEAL {m}", "Rente"],
            "es": ["Pago con tarjeta {m}", "Recibo {m}", "Transferencia de {p}", "Retirada de efectivo", "Nómina {c}",
                   "Orden permanente alquiler", "Compra online {m}", "Intereses"]}[lg]
    rows, bal = [], opening
    for d in sorted(start + dt.timedelta(days=rng.randint(0, (end - start).days)) for _ in range(rng.randint(6, 16))):
        t = rng.choice(desc)
        amt = r2(rng.uniform(2500, 4200)) if t.startswith(("Salary", "Gehalt", "Salaris", "Nómina")) else (
            r2(rng.uniform(20, 400)) if "{p}" in t else -r2(rng.uniform(4, 320)))
        text = t.format(m=company(rng, loc).split(" ")[0] + " " + rng.choice(CO_TRADE[lg]), p=person(rng, loc),
                        c=company(rng, loc))
        bal = r2(bal + amt)
        rows.append({"date": iso(d), "description": text, "amount": amt, "balance": bal})
    holder = person(rng, loc)
    a = address(rng, loc)
    rec = {"bank_name": rng.choice(BANKS[loc]), "account_holder": holder, "holder_address": a,
           "iban": iban(rng, loc) if loc != "en-US" and (loc != "en-GB" or rng.random() < 0.5) else None,
           "bic": maybe(rng, 0.7, letters(rng, 6) + letters(rng, 2)) if loc not in ("en-US",) else None,
           "account_number": digits(rng, 10) if loc == "en-US" else (digits(rng, 8) if loc == "en-GB" else None),
           "sort_code": f"{digits(rng, 2)}-{digits(rng, 2)}-{digits(rng, 2)}" if loc == "en-GB" else None,
           "statement_number": maybe(rng, 0.6, f"{rng.randint(1, 12)}/{start.year}"),
           "period_start": iso(start), "period_end": iso(end), "opening_balance": opening, "closing_balance": bal,
           "transactions": rows}
    decoys = {"customer_id": maybe(rng, 0.5, digits(rng, 8)),
              "routing": f"0{digits(rng, 8)}" if loc == "en-US" else None}
    return rec, decoys


def account_statement(rng, loc):
    lg = lang(loc)
    sd = day(rng, dt.date(2026, 9, 1), 60)
    sup, cus = address(rng, loc), address(rng, loc)
    words = {"en": ("Invoice", "Payment received", "Credit note"), "de": ("Rechnung", "Zahlungseingang", "Gutschrift"),
             "nl": ("Factuur", "Betaling ontvangen", "Creditnota"), "es": ("Factura", "Cobro recibido", "Abono")}[lg]
    opening = r2(rng.choice([0, rng.uniform(100, 3000)]))
    rows, bal = [], opening
    for d in sorted(sd - dt.timedelta(days=rng.randint(3, 75)) for _ in range(rng.randint(4, 10))):
        kind = rng.choices(words, [0.6, 0.3, 0.1])[0]
        amt = r2(rng.uniform(80, 2400))
        if kind != words[0]:
            amt = -amt
        ref = {words[0]: f"INV-{digits(rng, 5)}", words[1]: f"PMT-{digits(rng, 5)}", words[2]: f"CN-{digits(rng, 4)}"}[kind]
        bal = r2(bal + amt)
        rows.append({"date": iso(d), "reference": ref, "description": kind, "amount": amt})
    rec = {"supplier": {"name": company(rng, loc), **{k: sup[k] for k in ("street", "postcode", "city", "region")}},
           "customer": {"name": company(rng, loc), "customer_number": maybe(rng, 0.85, f"C-{digits(rng, 5)}"),
                        **{k: cus[k] for k in ("street", "postcode", "city", "region")}},
           "statement_date": iso(sd), "opening_balance": opening if rng.random() < 0.6 else None,
           "closing_balance": bal, "due_date": iso(maybe(rng, 0.5, sd + dt.timedelta(days=14))), "entries": rows}
    decoys = {"credit_limit": maybe(rng, 0.4, float(rng.choice([5000, 10000, 25000])))}
    return rec, decoys


# --------------------------------------------------------------------------------------------- delivery note

def delivery_note(rng, loc):
    lg = lang(loc)
    d = day(rng)
    rows = [{"article_number": rng.choice([f"{digits(rng, 3)}-{digits(rng, 4)}-{digits(rng, 2)}", f"ART{digits(rng, 5)}",
                                           f"{letters(rng, 2)}{digits(rng, 6)}"]),
             "description": desc, "quantity": float(rng.choice([1, 2, 4, 5, 10, 12, 20, 25, 50, 100]))}
            for desc in rng.sample(PARTS[lg], rng.randint(2, 8))]
    s, r = address(rng, loc), address(rng, loc)
    rec = {"delivery_note_number": rng.choice([f"DN-{digits(rng, 6)}", f"LS{digits(rng, 7)}", f"{digits(rng, 8)}"]),
           "delivery_date": iso(d), "order_number": maybe(rng, 0.75, f"PO-{digits(rng, 5)}"),
           "customer_number": maybe(rng, 0.6, f"{digits(rng, 6)}"),
           "shipper": {"name": company(rng, loc), **{k: s[k] for k in ("street", "postcode", "city", "region")}},
           "recipient": {"name": company(rng, loc), **{k: r[k] for k in ("street", "postcode", "city", "region")}},
           "carrier": maybe(rng, 0.7, rng.choice(CARRIERS[loc])),
           "tracking_number": None, "package_count": maybe(rng, 0.7, rng.randint(1, 6)),
           "gross_weight": maybe(rng, 0.55, r2(rng.uniform(1.5, 180))),
           "weight_unit": "lb" if loc == "en-US" else "kg", "line_items": rows}
    if rec["carrier"] and rng.random() < 0.7:
        rec["tracking_number"] = rng.choice([f"1Z{letters(rng, 3)}{digits(rng, 13)}", digits(rng, 14),
                                             f"JJD{digits(rng, 15)}"])
    decoys = {"order_date": iso(d - dt.timedelta(days=rng.randint(2, 20))) if rng.random() < 0.6 else None,
              "contact": person(rng, loc) if rng.random() < 0.5 else None}
    return rec, decoys


# --------------------------------------------------------------------------------------------- payslip

def payslip(rng, loc):
    earn_labels, ded = PAYSLIP[loc]
    start = dt.date(2026, rng.choice([8, 9, 10]), 1)
    end = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    base = r2(rng.uniform(2400, 6500))
    earnings = [{"description": earn_labels[0], "amount": base}]
    for lb in earn_labels[1:]:
        if rng.random() < 0.4:
            earnings.append({"description": lb, "amount": r2(rng.uniform(80, 600))})
    gross = r2(sum(e["amount"] for e in earnings))
    deductions = [{"description": lb, "amount": r2(gross * share)} for lb, share in ded if rng.random() < 0.9]
    total_ded = r2(sum(x["amount"] for x in deductions))
    e = address(rng, loc)
    rec = {"employer": {"name": company(rng, loc), **{k: e[k] for k in ("street", "postcode", "city", "region")}},
           "employee": {"name": person(rng, loc), "employee_id": maybe(rng, 0.8, f"{rng.choice(['E', 'P', ''])}{digits(rng, 5)}")},
           "pay_period_start": iso(start), "pay_period_end": iso(end),
           "pay_date": iso(maybe(rng, 0.8, end - dt.timedelta(days=rng.choice([0, 1, 2])))),
           "gross_pay": gross, "total_deductions": total_ded if rng.random() < 0.75 else None,
           "net_pay": r2(gross - total_ded), "iban": maybe(rng, 0.7, iban(rng, loc)),
           "earnings": earnings, "deductions": deductions}
    decoys = {"ytd_gross": r2(gross * rng.randint(7, 10)) if rng.random() < 0.5 else None,
              "tax_code": {"en-GB": "1257L", "de-DE": f"Steuerklasse {rng.choice('1345')}"}.get(loc),
              "dd_last4": digits(rng, 4) if loc == "en-US" else None}
    return rec, decoys


FAMILIES = {"invoice": invoice, "receipt": receipt, "bank_statement": bank_statement,
            "account_statement": account_statement, "delivery_note": delivery_note, "payslip": payslip}
