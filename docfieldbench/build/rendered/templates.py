"""HTML templates, written for this repository. Each takes (record, decoys, locale, rng) and returns HTML; a field
that is None in the record is not drawn. Layout choices that vary per document (date style, column order, accents)
come from the seeded rng, so a rebuild draws the same document."""
from __future__ import annotations

import html
from pathlib import Path

from . import fmt
from .labels import labels

FONTS = Path(__file__).parent / "fonts"


def e(s) -> str:
    return html.escape(str(s)) if s is not None else ""


def base_css(page: str = "A4", margin: str = "18mm 16mm") -> str:
    faces = "".join(
        f"@font-face{{font-family:'{fam}';src:url('{(FONTS / f).as_uri()}');font-weight:{w}}}"
        for fam, f, w in [("DV Sans", "DejaVuSans.ttf", 400), ("DV Sans", "DejaVuSans-Bold.ttf", 700),
                          ("DV Serif", "DejaVuSerif.ttf", 400), ("DV Serif", "DejaVuSerif-Bold.ttf", 700),
                          ("DV Mono", "DejaVuSansMono.ttf", 400), ("DV Mono", "DejaVuSansMono-Bold.ttf", 700)])
    return (f"{faces}@page{{size:{page};margin:{margin}}}body{{margin:0;font-size:9.5pt;color:#222}}"
            "table{border-collapse:collapse;width:100%}td,th{padding:3px 5px;vertical-align:top}"
            ".r{text-align:right}.b{font-weight:700}.muted{color:#666}.small{font-size:8pt}")


def doc(css: str, body: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{body}</body></html>"


def place(p: dict, loc: str) -> list[str]:
    """Address lines after the name, in the locale's order."""
    if loc == "en-US":
        return [p["street"], f"{p['city']}, {p.get('region') or ''} {p['postcode']}".replace(" ,", ",")]
    if loc == "en-GB":
        return [p["street"], p["city"], p["postcode"]]
    return [p["street"], f"{p['postcode']} {p['city']}"]


def lines(*xs) -> str:
    return "<br>".join(e(x) for x in xs if x)


def kv(rows, cls="") -> str:
    """A two-column label/value table, skipping rows whose value is empty."""
    body = "".join(f"<tr><td class='muted'>{e(k)}</td><td class='{cls}'>{e(v)}</td></tr>" for k, v in rows if v)
    return f"<table class='kv'>{body}</table>"


# =============================================================================================== invoices

def _invoice_ids(rec, dec, loc, T):
    s = rec["seller"]
    out = []
    if s.get("vat_id"):
        out.append((T["tax_no"], s["vat_id"][2:]) if s.get("nif_only") else (T["vat_id"], s["vat_id"]))
    if s.get("tax_number"):
        out.append((T["tax_no"], s["tax_number"]))
    if dec.get("company_reg"):
        out.append((T["company_reg"], dec["company_reg"]))
    return out


def _invoice_meta(rec, dec, loc, T, ds):
    return [(T["invoice_no"], rec["invoice_number"]), (T["invoice_date"], fmt.date(rec["invoice_date"], loc, ds)),
            (T["delivery_date"], fmt.date(rec["delivery_date"], loc, ds)),
            (T["customer_no"], rec["customer_number"]), (T["order_no"], rec["order_number"]),
            (T["your_ref"], dec.get("buyer_reference")), (T["dn_no"], rec["delivery_note_number"]),
            (T["due_date"], fmt.date(rec["due_date"], loc, ds))]


def _invoice_items(rec, loc, T, unit_col, sym):
    head = (f"<tr><th>#</th><th>{T['description']}</th><th class='r'>{T['qty']}</th>"
            + (f"<th>{T['unit']}</th>" if unit_col else "")
            + f"<th class='r'>{T['unit_price']}</th><th class='r'>{T['amount']}</th></tr>")
    body = "".join(
        f"<tr><td>{i}</td><td>{e(r['description'])}</td><td class='r'>{fmt.qty(r['quantity'], loc)}</td>"
        + (f"<td>{e(r['unit'])}</td>" if unit_col else "")
        + f"<td class='r'>{fmt.money(r['unit_price'], loc, sym)}</td><td class='r'>{fmt.money(r['line_total'], loc, sym)}</td></tr>"
        for i, r in enumerate(rec["line_items"], 1))
    return f"<table class='items'>{head}{body}</table>"


def _invoice_totals(rec, loc, T):
    rows = [(T["net"], fmt.money(rec["net_total"], loc))]
    if rec["tax_total"] is not None:
        lab = T["sales_tax"] if loc == "en-US" else T["vat"]
        rows.append((f"{lab} {fmt.pct(rec['tax_rate'], loc)}", fmt.money(rec["tax_total"], loc)))
    rows.append((T["total"], fmt.money(rec["total_incl_tax"], loc)))
    if rec["prepaid_amount"] is not None:
        rows.append((T["prepaid"], fmt.money(-rec["prepaid_amount"], loc)))
    if rec["amount_due"] is not None:
        rows.append((T["amount_due"], fmt.money(rec["amount_due"], loc)))
    body = "".join(f"<tr><td>{e(k)}</td><td class='r'>{e(v)}</td></tr>" for k, v in rows)
    return f"<table class='totals'>{body}</table>"


def _bank(rec, dec, loc, T):
    rows = [(T["iban"], rec["iban"] and " ".join(rec["iban"][i:i + 4] for i in range(0, len(rec["iban"]), 4))),
            (T["bic"], dec.get("bic")), (T["routing"], dec.get("routing")),
            (T["account"], dec.get("account") if dec.get("routing") else None)]
    return rows


def _terms(rec, dec, T):
    return T["terms"].format(n=dec["terms_days"]) if dec.get("terms_days") else ""


def inv_letter(rec, dec, loc, rng):
    """A business letter: sender line over the address window, details block on the right, serif type."""
    T, s, b = labels(loc), rec["seller"], rec["buyer"]
    ds = rng.choice(["num", "num", "long"])
    css = base_css(margin="16mm 20mm 22mm 24mm") + (
        "body{font-family:'DV Serif'}.head{text-align:right;font-size:15pt;font-weight:700;margin-bottom:6mm}"
        ".sender{font-size:7pt;text-decoration:underline;margin-top:8mm}.window{height:32mm;width:85mm;float:left}"
        ".meta{float:right;width:70mm}.meta td{padding:1px 4px}.clear{clear:both}h1{font-size:14pt;margin:8mm 0 4mm}"
        ".items th{border-bottom:1px solid #000;text-align:left}.items td{border-bottom:0.5px solid #bbb}"
        ".totals{width:75mm;margin-left:auto;margin-top:4mm}.totals tr:last-child td{font-weight:700;border-top:1px solid #000}"
        ".foot{position:fixed;bottom:-14mm;left:0;right:0;font-size:7pt;color:#555;border-top:0.5px solid #999;padding-top:2mm}")
    sender = " · ".join([s["name"], *place(s, loc)])
    window = lines(b["name"], T["attn"] + " " + b["attn"] if b.get("attn") else None, *place(b, loc))
    foot_cols = [lines(s["name"], *place(s, loc), f"{T['phone']} {s['phone']}"),
                 lines(*[f"{k}: {v}" for k, v in _invoice_ids(rec, dec, loc, T)]),
                 lines(T["bank"], *[f"{k}: {v}" for k, v in _bank(rec, dec, loc, T) if v])]
    body = (f"<div class='head'>{e(s['name'])}</div><div class='window'><div class='sender'>{e(sender)}</div>"
            f"<div style='margin-top:3mm'>{window}</div></div><div class='meta'>{kv(_invoice_meta(rec, dec, loc, T, ds))}</div>"
            + (f"<div class='clear'></div><div class='meta'>{kv([(T['vat_id'], b['vat_id'])])}</div>" if b.get("vat_id") else "")
            + f"<div class='clear'></div><h1>{T['invoice']} {e(rec['invoice_number'])}</h1>"
            + _invoice_items(rec, loc, T, rng.random() < 0.5, False) + _invoice_totals(rec, loc, T)
            + f"<p>{e(_terms(rec, dec, T))}</p><p>{e(T['thanks'])}</p>"
            + "<table class='foot'><tr>" + "".join(f"<td>{c}</td>" for c in foot_cols) + "</tr></table>")
    return doc(css, body)


def inv_band(rec, dec, loc, rng):
    """A coloured header band, the parties side by side, sans type."""
    T, s, b = labels(loc), rec["seller"], rec["buyer"]
    color = rng.choice(["#1f4e79", "#2e6b3a", "#6b2e5a", "#7a4a12", "#333"])
    ds = rng.choice(["num", "short", "long"])
    css = base_css(margin="0 0 18mm 0") + (
        f"body{{font-family:'DV Sans'}}.band{{background:{color};color:#fff;padding:10mm 16mm}}"
        ".band .t{font-size:22pt;font-weight:700;letter-spacing:1px}.wrap{padding:6mm 16mm}"
        ".cols{display:flex;gap:10mm}.cols>div{flex:1}.cap{font-size:7.5pt;text-transform:uppercase;color:#888;margin-bottom:1mm}"
        f".items th{{background:{color};color:#fff;text-align:left}}.items tr:nth-child(even) td{{background:#f3f3f3}}"
        ".totals{width:80mm;margin-left:auto;margin-top:5mm}.totals tr:last-child td{font-weight:700;font-size:11pt}")
    ids = "<br>".join(f"{e(k)} {e(v)}" for k, v in _invoice_ids(rec, dec, loc, T))
    body = (f"<div class='band'><span class='t'>{e(T['invoice']).upper()}</span><br>{e(s['name'])}</div><div class='wrap'>"
            f"<div class='cols'><div><div class='cap'>{e(T['from'])}</div>{lines(s['name'], *place(s, loc), s['phone'])}"
            f"<br><span class='small'>{ids}</span></div>"
            f"<div><div class='cap'>{e(T['bill_to'])}</div>{lines(b['name'], b.get('attn'), *place(b, loc))}"
            + (f"<br><span class='small'>{e(T['vat_id'])} {e(b['vat_id'])}</span>" if b.get("vat_id") else "")
            + f"</div><div>{kv(_invoice_meta(rec, dec, loc, T, ds))}</div></div><br>"
            + _invoice_items(rec, loc, T, False, True) + _invoice_totals(rec, loc, T)
            + f"<p class='small'>{e(_terms(rec, dec, T))}</p>"
            + f"<p class='small'>{'<br>'.join(f'{e(k)}: {e(v)}' for k, v in _bank(rec, dec, loc, T) if v)}</p></div>")
    return doc(css, body)


def inv_grid(rec, dec, loc, rng):
    """A boxed form: ruled cells for every block, monospaced amounts."""
    T, s, b = labels(loc), rec["seller"], rec["buyer"]
    ds = rng.choice(["num", "iso", "num"])
    css = base_css() + (
        "body{font-family:'DV Sans';font-size:9pt}.box{border:1px solid #444;padding:2mm 3mm;margin-bottom:-1px}"
        ".row{display:flex}.row>.box{flex:1;margin-right:-1px}.t{font-size:16pt;font-weight:700;text-align:center}"
        ".cap{font-size:7pt;color:#555}.items td,.items th{border:1px solid #444}.items td.r{font-family:'DV Mono'}"
        ".totals td{border:1px solid #444}.totals td.r{font-family:'DV Mono'}.totals{width:90mm;margin-left:auto}")
    meta = "".join(f"<div class='box'><div class='cap'>{e(k)}</div>{e(v)}</div>"
                   for k, v in _invoice_meta(rec, dec, loc, T, ds) if v)
    ids = "<br>".join(f"{e(k)}: {e(v)}" for k, v in _invoice_ids(rec, dec, loc, T))
    body = (f"<div class='box t'>{e(T['invoice'])}</div><div class='row'>"
            f"<div class='box'><div class='cap'>{e(T['from'])}</div>{lines(s['name'], *place(s, loc), T['phone'] + ' ' + s['phone'])}"
            f"<br><span class='small'>{ids}</span></div>"
            f"<div class='box'><div class='cap'>{e(T['bill_to'])}</div>{lines(b['name'], b.get('attn'), *place(b, loc))}"
            + (f"<br><span class='small'>{e(T['vat_id'])}: {e(b['vat_id'])}</span>" if b.get("vat_id") else "")
            + f"</div></div><div class='row'>{meta}</div><br>" + _invoice_items(rec, loc, T, True, False)
            + "<br>" + _invoice_totals(rec, loc, T)
            + f"<div class='box small' style='margin-top:6mm'>{e(_terms(rec, dec, T))}<br>"
            + "<br>".join(f"{e(k)}: {e(v)}" for k, v in _bank(rec, dec, loc, T) if v) + "</div>")
    return doc(css, body)


# =============================================================================================== receipts

def _receipt_height(rec, extra=0):
    return f"{68 + 7 * len(rec['line_items']) + extra}mm"


def _pay_lines(rec, dec, loc, T):
    rows = []
    if rec["payment_method"]:
        rows.append((T["payment"], rec["payment_method"]))
    if rec["card_last4"]:
        rows.append((T["card"], "**** **** **** " + rec["card_last4"]))
    if rec["cash_given"]:
        rows += [(T["cash_given"], fmt.money(rec["cash_given"], loc)),
                 (T["change"], fmt.money(rec["cash_given"] - rec["total"], loc))]
    rows += [(T["terminal"], dec.get("terminal")), (T["auth"], dec.get("auth")), (T["trans"], dec.get("trans"))]
    return [(k, v) for k, v in rows if v]


def _receipt_tax_lines(rec, loc, T):
    rows = []
    if rec["subtotal"] is not None:
        rows.append((T["subtotal"], fmt.money(rec["subtotal"], loc)))
    if rec["tax_total"] is not None:
        lab = T["tax"] if loc == "en-US" else f"{T['incl_vat']} {fmt.pct(rec['tax_rate'], loc)}"
        rows.append((lab, fmt.money(rec["tax_total"], loc)))
    if rec["tip"] is not None:
        rows.append((T["tip"], fmt.money(rec["tip"], loc)))
    return rows


def _merchant_head(rec, loc, T):
    m = rec["merchant"]
    return lines(*place(m, loc), m.get("phone") and f"{T['phone']} {m['phone']}",
                 m.get("vat_id") and f"{T['vat_id']} {m['vat_id']}")


def rc_thermal(rec, dec, loc, rng):
    """An 80 mm till roll in a monospaced font."""
    T, m = labels(loc), rec["merchant"]
    css = base_css(f"80mm {_receipt_height(rec)}", "5mm 4mm") + (
        "body{font-family:'DV Mono';font-size:8pt}.c{text-align:center}hr{border:0;border-top:1px dashed #000}"
        ".big{font-size:11pt;font-weight:700}")
    items = "".join(
        f"<tr><td>{e(r['description'])}" + (f"<br>&nbsp;&nbsp;{r['quantity']} x {fmt.money(r['unit_price'], loc, False)}"
                                            if r["quantity"] != 1 else "")
        + f"</td><td class='r'>{fmt.money(r['line_total'], loc, False)}</td></tr>" for r in rec["line_items"])
    taxes = "".join(f"<tr><td>{e(k)}</td><td class='r'>{e(v)}</td></tr>" for k, v in _receipt_tax_lines(rec, loc, T))
    pays = "".join(f"<tr><td>{e(k)}</td><td class='r'>{e(v)}</td></tr>" for k, v in _pay_lines(rec, dec, loc, T))
    head = [(T["receipt_no"], rec["receipt_number"]), (T["till"], dec.get("till")), (T["cashier"], dec.get("cashier"))]
    body = (f"<div class='c big'>{e(m['name'])}</div><div class='c'>{_merchant_head(rec, loc, T)}</div><hr>"
            f"<div>{fmt.date(rec['date'], loc)} {rec['time']}</div>"
            + "".join(f"<div>{e(k)}: {e(v)}</div>" for k, v in head if v)
            + f"<hr><table>{items}</table><hr><table>{taxes}<tr class='big'><td>{e(T['total'])}</td>"
            f"<td class='r'>{fmt.money(rec['total'], loc)}</td></tr></table><hr><table>{pays}</table><hr>"
            f"<div class='c'>{e(T['thanks'])}</div>")
    return doc(css, body)


def rc_store(rec, dec, loc, rng):
    """A shop receipt in sans type with a header bar and a VAT summary block."""
    T, m = labels(loc), rec["merchant"]
    css = base_css(f"80mm {_receipt_height(rec, 15)}", "6mm 5mm") + (
        "body{font-family:'DV Sans';font-size:8pt}.bar{background:#000;color:#fff;text-align:center;padding:2mm;"
        "font-size:12pt;font-weight:700}.c{text-align:center}.items td{border-bottom:0.3px solid #ccc}"
        ".tot td{font-size:11pt;font-weight:700;border-top:1.5px solid #000}.vat{font-size:7pt;margin-top:2mm}")
    items = "".join(f"<tr><td>{r['quantity']}</td><td>{e(r['description'])}</td>"
                    f"<td class='r'>{fmt.money(r['line_total'], loc, False)}</td></tr>" for r in rec["line_items"])
    taxes = "".join(f"<tr><td colspan='2'>{e(k)}</td><td class='r'>{e(v)}</td></tr>"
                    for k, v in _receipt_tax_lines(rec, loc, T))
    pays = "<br>".join(f"{e(k)}: {e(v)}" for k, v in _pay_lines(rec, dec, loc, T))
    rn = f"{e(T['receipt_no'])} {e(rec['receipt_number'])}" if rec["receipt_number"] else ""
    body = (f"<div class='bar'>{e(m['name'])}</div><div class='c'>{_merchant_head(rec, loc, T)}</div><br>"
            f"<table><tr><td>{fmt.date(rec['date'], loc)}</td><td class='r'>{rec['time']}</td></tr>"
            f"<tr><td>{rn}</td><td class='r'>{e(dec.get('till') and T['till'] + ' ' + dec['till'])}</td></tr></table>"
            f"<table class='items'>{items}</table><table>{taxes}<tr class='tot'><td colspan='2'>{e(T['total'])}</td>"
            f"<td class='r'>{fmt.money(rec['total'], loc)}</td></tr></table><div class='vat'>{pays}</div><br>"
            f"<div class='c small'>{e(T['thanks'])}</div>")
    return doc(css, body)


def rc_slip(rec, dec, loc, rng):
    """A café or shop bill on an A6 page, serif, with a qty/price/amount table."""
    T, m = labels(loc), rec["merchant"]
    ds = rng.choice(["num", "long"]) if loc != "es-ES" else "num"
    css = base_css("A6", "8mm 8mm") + (
        "body{font-family:'DV Serif';font-size:8pt}h2{text-align:center;margin:0 0 1mm;font-size:12pt}"
        ".c{text-align:center}.items th{border-bottom:1px solid #000;text-align:left}"
        ".tot td{font-weight:700;border-top:1px solid #000}")
    items = "".join(f"<tr><td>{e(r['description'])}</td><td class='r'>{r['quantity']}</td>"
                    f"<td class='r'>{fmt.money(r['unit_price'], loc, False)}</td>"
                    f"<td class='r'>{fmt.money(r['line_total'], loc, False)}</td></tr>" for r in rec["line_items"])
    taxes = "".join(f"<tr><td colspan='3'>{e(k)}</td><td class='r'>{e(v)}</td></tr>"
                    for k, v in _receipt_tax_lines(rec, loc, T))
    meta = kv([(T["receipt_no"], rec["receipt_number"]), (T["date"], f"{fmt.date(rec['date'], loc, ds)}, {rec['time']}"),
               (T["cashier"], dec.get("cashier"))])
    body = (f"<h2>{e(m['name'])}</h2><div class='c'>{_merchant_head(rec, loc, T)}</div><br>{meta}"
            f"<table class='items'><tr><th>{e(T['description'])}</th><th class='r'>{e(T['qty'])}</th>"
            f"<th class='r'>{e(T['unit_price'])}</th><th class='r'>{e(T['amount'])}</th></tr>{items}{taxes}"
            f"<tr class='tot'><td colspan='3'>{e(T['total'])}</td><td class='r'>{fmt.money(rec['total'], loc)}</td></tr>"
            f"</table><br>{kv(_pay_lines(rec, dec, loc, T))}")
    return doc(css, body)


# =============================================================================================== statements

def bs_bank(rec, dec, loc, rng):
    """A bank statement: holder block, account panel, transactions with a running balance."""
    T = labels(loc)
    color = rng.choice(["#0b5394", "#38761d", "#990000", "#134f5c"])
    ds = rng.choice(["num", "short"])
    css = base_css() + (
        f"body{{font-family:'DV Sans'}}.bank{{font-size:16pt;font-weight:700;color:{color}}}"
        ".top{display:flex;justify-content:space-between;margin:6mm 0}.panel{border:1px solid #bbb;padding:3mm;width:80mm}"
        f".tx th{{border-bottom:2px solid {color};text-align:left}}.tx td{{border-bottom:0.3px solid #ddd}}")
    h = rec["holder_address"]
    acct = [(T["account_holder"], rec["account_holder"]), (T["iban"], rec["iban"]), (T["bic"], rec["bic"]),
            (T["sort_code"], rec["sort_code"]), (T["account"], rec["account_number"]),
            (T["routing"], dec.get("routing")), (T["statement_no"], rec["statement_number"]),
            (T["period"], f"{fmt.date(rec['period_start'], loc, ds)} {T['to']} {fmt.date(rec['period_end'], loc, ds)}"),
            (T["customer_id"], dec.get("customer_id"))]
    tx = "".join(f"<tr><td>{fmt.date(r['date'], loc, ds)}</td><td>{e(r['description'])}</td>"
                 f"<td class='r'>{fmt.money(r['amount'], loc, False)}</td><td class='r'>{fmt.money(r['balance'], loc, False)}</td></tr>"
                 for r in rec["transactions"])
    body = (f"<div class='bank'>{e(rec['bank_name'])}</div><div class='muted'>{e(T['statement'])}</div>"
            f"<div class='top'><div>{lines(rec['account_holder'], *place(h, loc))}</div><div class='panel'>{kv(acct)}</div></div>"
            f"<table class='tx'><tr><th>{e(T['date'])}</th><th>{e(T['description'])}</th><th class='r'>{e(T['amount'])}</th>"
            f"<th class='r'>{e(T['balance'])}</th></tr><tr><td></td><td class='b'>{e(T['opening'])}</td><td></td>"
            f"<td class='r b'>{fmt.money(rec['opening_balance'], loc, False)}</td></tr>{tx}"
            f"<tr><td></td><td class='b'>{e(T['closing'])}</td><td></td><td class='r b'>{fmt.money(rec['closing_balance'], loc)}</td></tr></table>")
    return doc(css, body)


def as_supplier(rec, dec, loc, rng):
    """A supplier's statement of account to a customer: open items and the balance due."""
    T, s, c = labels(loc), rec["supplier"], rec["customer"]
    ds = rng.choice(["num", "long", "short"])
    css = base_css() + (
        "body{font-family:'DV Serif'}.hd{display:flex;justify-content:space-between}.co{font-size:14pt;font-weight:700}"
        "h1{font-size:13pt;margin:8mm 0 3mm}.it th{border-bottom:1px solid #000;text-align:left}"
        ".it td{border-bottom:0.3px dotted #999}.due{margin-top:5mm;font-size:11pt}")
    it = "".join(f"<tr><td>{fmt.date(r['date'], loc, ds)}</td><td>{e(r['reference'])}</td><td>{e(r['description'])}</td>"
                 f"<td class='r'>{fmt.money(r['amount'], loc)}</td></tr>" for r in rec["entries"])
    meta = kv([(T["statement_date"], fmt.date(rec["statement_date"], loc, ds)), (T["customer_no"], c["customer_number"]),
               (T["credit_limit"], dec.get("credit_limit") and fmt.money(dec["credit_limit"], loc))])
    opening = (f"<tr><td></td><td></td><td class='b'>{e(T['opening'])}</td><td class='r'>{fmt.money(rec['opening_balance'], loc)}</td></tr>"
               if rec["opening_balance"] is not None else "")
    body = (f"<div class='hd'><div><div class='co'>{e(s['name'])}</div>{lines(*place(s, loc))}</div><div>{meta}</div></div><br>"
            f"<div>{lines(c['name'], *place(c, loc))}</div><h1>{e(T['soa'])}</h1>"
            f"<table class='it'><tr><th>{e(T['date'])}</th><th>{e(T['reference'])}</th><th>{e(T['type'])}</th>"
            f"<th class='r'>{e(T['amount'])}</th></tr>{opening}{it}</table>"
            f"<div class='due'>{e(T['balance_due'])}: <b>{fmt.money(rec['closing_balance'], loc)}</b></div>"
            + (f"<p>{e(T['pay_by'])} {fmt.date(rec['due_date'], loc, ds)}.</p>" if rec["due_date"] else ""))
    return doc(css, body)


# =============================================================================================== delivery notes

def _dn_meta(rec, dec, loc, T, ds):
    w = rec["gross_weight"]
    return [(T["dn_no"], rec["delivery_note_number"]), (T["delivery_date"], fmt.date(rec["delivery_date"], loc, ds)),
            (T["order_no"], rec["order_number"]), (T["order_date"], fmt.date(dec.get("order_date"), loc, ds)),
            (T["customer_no"], rec["customer_number"]), (T["carrier"], rec["carrier"]),
            (T["tracking"], rec["tracking_number"]),
            (T["packages"], rec["package_count"] and str(rec["package_count"])),
            (T["weight"], w and f"{fmt.number(w, loc)} {rec['weight_unit']}"), (T["contact"], dec.get("contact"))]


def dn_classic(rec, dec, loc, rng):
    T, s, r = labels(loc), rec["shipper"], rec["recipient"]
    ds = rng.choice(["num", "long"])
    css = base_css() + (
        "body{font-family:'DV Serif'}.co{font-size:14pt;font-weight:700}.cols{display:flex;gap:12mm;margin:8mm 0}"
        ".cols>div{flex:1}h1{font-size:15pt}.it th{border-bottom:1px solid #000;text-align:left}"
        ".it td{border-bottom:0.3px solid #bbb}.sig{margin-top:18mm;border-top:1px solid #000;width:70mm;font-size:8pt}")
    it = "".join(f"<tr><td>{i}</td><td>{e(x['article_number'])}</td><td>{e(x['description'])}</td>"
                 f"<td class='r'>{fmt.qty(x['quantity'], loc)}</td></tr>" for i, x in enumerate(rec["line_items"], 1))
    body = (f"<div class='co'>{e(s['name'])}</div>{lines(*place(s, loc))}<div class='cols'>"
            f"<div><b>{e(T['ship_to'])}</b><br>{lines(r['name'], *place(r, loc))}</div>"
            f"<div>{kv(_dn_meta(rec, dec, loc, T, ds))}</div></div><h1>{e(T['delivery_note'])}</h1>"
            f"<table class='it'><tr><th>#</th><th>{e(T['article'])}</th><th>{e(T['description'])}</th>"
            f"<th class='r'>{e(T['qty'])}</th></tr>{it}</table><div class='sig'>{e(T['received'])}</div>")
    return doc(css, body)


def dn_warehouse(rec, dec, loc, rng):
    T, s, r = labels(loc), rec["shipper"], rec["recipient"]
    ds = rng.choice(["num", "iso"])
    css = base_css() + (
        "body{font-family:'DV Sans'}.big{font-size:20pt;font-weight:700}.no{font-family:'DV Mono';font-size:14pt}"
        ".boxes{display:flex;gap:4mm;margin:5mm 0}.boxes>div{flex:1;border:2px solid #000;padding:3mm}"
        ".cap{font-size:7pt;text-transform:uppercase}.it td,.it th{border:1px solid #000}.it th{background:#ddd}")
    it = "".join(f"<tr><td>{e(x['article_number'])}</td><td>{e(x['description'])}</td>"
                 f"<td class='r'>{fmt.qty(x['quantity'], loc)} {e(T['pcs'])}</td><td></td></tr>" for x in rec["line_items"])
    body = (f"<div class='big'>{e(T['delivery_note']).upper()}</div><div class='no'>{e(rec['delivery_note_number'])}</div>"
            f"<div class='boxes'><div><div class='cap'>{e(T['shipper'])}</div>{lines(s['name'], *place(s, loc))}</div>"
            f"<div><div class='cap'>{e(T['ship_to'])}</div>{lines(r['name'], *place(r, loc))}</div></div>"
            f"{kv([x for x in _dn_meta(rec, dec, loc, T, ds) if x[0] != T['dn_no']])}<br>"
            f"<table class='it'><tr><th>{e(T['article'])}</th><th>{e(T['description'])}</th><th>{e(T['qty'])}</th>"
            f"<th>✓</th></tr>{it}</table><p class='small'>{e(T['received'])}: ____________________</p>")
    return doc(css, body)


# =============================================================================================== payslips

def _ps_blocks(rec, dec, loc, T, ds):
    emp = rec["employee"]
    return [(T["employee"], emp["name"]), (T["employee_id"], emp["employee_id"]),
            (T["pay_period"], f"{fmt.date(rec['pay_period_start'], loc, ds)} {T['to']} {fmt.date(rec['pay_period_end'], loc, ds)}"),
            (T["pay_date"], fmt.date(rec["pay_date"], loc, ds)), (T["tax_code"], dec.get("tax_code"))]


def _ps_tail(rec, dec, loc, T):
    rows = [(T["gross_pay"], fmt.money(rec["gross_pay"], loc))]
    if rec["total_deductions"] is not None:
        rows.append((T["total_deductions"], fmt.money(rec["total_deductions"], loc)))
    rows.append((T["net_pay"], fmt.money(rec["net_pay"], loc)))
    if rec["iban"]:
        rows.append((T["paid_to"], rec["iban"]))
    if dec.get("dd_last4"):
        rows.append((T["dd"], dec["dd_last4"]))
    if dec.get("ytd_gross"):
        rows.append((T["ytd_gross"], fmt.money(dec["ytd_gross"], loc)))
    return rows


def ps_twocol(rec, dec, loc, rng):
    T, er = labels(loc), rec["employer"]
    ds = rng.choice(["num", "short"])
    css = base_css() + (
        "body{font-family:'DV Sans'}.hd{display:flex;justify-content:space-between;border-bottom:2px solid #000;padding-bottom:3mm}"
        ".t{font-size:16pt;font-weight:700}.cols{display:flex;gap:6mm;margin-top:5mm}.cols>div{flex:1}"
        ".cols th{background:#eee;text-align:left}.net td{font-size:12pt;font-weight:700}")
    earn = "".join(f"<tr><td>{e(x['description'])}</td><td class='r'>{fmt.money(x['amount'], loc, False)}</td></tr>"
                   for x in rec["earnings"])
    ded = "".join(f"<tr><td>{e(x['description'])}</td><td class='r'>{fmt.money(x['amount'], loc, False)}</td></tr>"
                  for x in rec["deductions"])
    body = (f"<div class='hd'><div><div class='t'>{e(T['payslip'])}</div>{lines(er['name'], *place(er, loc))}</div>"
            f"<div>{kv(_ps_blocks(rec, dec, loc, T, ds))}</div></div><div class='cols'>"
            f"<div><table><tr><th colspan='2'>{e(T['earnings'])}</th></tr>{earn}</table></div>"
            f"<div><table><tr><th colspan='2'>{e(T['deductions'])}</th></tr>{ded}</table></div></div><br>"
            f"{kv(_ps_tail(rec, dec, loc, T), 'r b')}")
    return doc(css, body)


def ps_list(rec, dec, loc, rng):
    T, er = labels(loc), rec["employer"]
    ds = rng.choice(["num", "long"]) if loc != "es-ES" else "num"
    css = base_css() + (
        "body{font-family:'DV Serif'}.co{font-size:13pt;font-weight:700}.box{border:1px solid #999;padding:3mm;margin:4mm 0}"
        ".l td{border-bottom:0.3px dotted #aaa}.l td:first-child{width:70%}.sec{font-weight:700;margin-top:4mm}")
    rows = "".join(f"<tr><td>{e(x['description'])}</td><td class='r'>{fmt.money(x['amount'], loc)}</td></tr>"
                   for x in rec["earnings"])
    drows = "".join(f"<tr><td>{e(x['description'])}</td><td class='r'>-{fmt.money(x['amount'], loc)}</td></tr>"
                    for x in rec["deductions"])
    body = (f"<div class='co'>{e(er['name'])}</div>{lines(*place(er, loc))}<h2>{e(T['payslip'])}</h2>"
            f"<div class='box'>{kv(_ps_blocks(rec, dec, loc, T, ds))}</div>"
            f"<div class='sec'>{e(T['earnings'])}</div><table class='l'>{rows}</table>"
            f"<div class='sec'>{e(T['deductions'])}</div><table class='l'>{drows}</table>"
            f"<div class='box'>{kv(_ps_tail(rec, dec, loc, T), 'r b')}</div>")
    return doc(css, body)


TEMPLATES = {
    "invoice": {"inv_letter": inv_letter, "inv_band": inv_band, "inv_grid": inv_grid},
    "receipt": {"rc_thermal": rc_thermal, "rc_store": rc_store, "rc_slip": rc_slip},
    "bank_statement": {"bs_bank": bs_bank},
    "account_statement": {"as_supplier": as_supplier},
    "delivery_note": {"dn_classic": dn_classic, "dn_warehouse": dn_warehouse},
    "payslip": {"ps_twocol": ps_twocol, "ps_list": ps_list},
}
