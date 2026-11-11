"""Filled US federal forms: fillable IRS PDFs (public domain) filled with seeded, visibly fake values and flattened,
so the values sit in the page content like a form filled in software. The gold is what we filled; a box left blank
is absent (its label is printed, the box is empty).

Forms are chosen outside VAREX's form list. Only fields whose printed label names what they hold are mapped; boxes
labelled by a line number alone are left out. Fake values: SSNs and ITINs in the 9xx range, 555-01xx phone numbers,
example.com emails, names and places from the rendered documents' word lists.

  python -m docfieldbench.build.formfill --forms DIR_WITH_IRS_PDFS --out data/v1.0.0-new
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import random
from collections import Counter
from pathlib import Path

from ..tasks import validate_task
from .common import sha256, write_bytes_task
from .families import _obj
from .rendered.records import address, company, digits
from .rendered.vocab import FIRST, LAST
from .visibility import TextIndex

SEED = 20261111
US = "en-US"

# ------------------------------------------------------------------------------------------------ value makers


class Person:
    def __init__(self, rng, loc=US):
        self.first = rng.choice(FIRST[loc])
        self.mi = rng.choice("ABCDEFGHJKLMNPRSTW")
        self.last = rng.choice(LAST[loc])
        a = address(rng, loc)
        self.street, self.city, self.state, self.zip = a["street"], a["city"], a["region"], a["postcode"]
        self.ssn = f"9{digits(rng, 2)}-{digits(rng, 2)}-{digits(rng, 4)}"
        self.phone = f"(555) 01{digits(rng, 2)}-{digits(rng, 4)}"


def us_date(d: dt.date) -> str:
    return f"{d.month:02d}/{d.day:02d}/{d.year}"


def money(x: float, rng) -> str:
    return rng.choice([f"{x:,.2f}", f"{x:.2f}"]) if x != int(x) else f"{int(x):,}"


def ein(rng):
    return f"{digits(rng, 2)}-{digits(rng, 7)}"


# kinds: id, name, short_text, date, amount, integer
def fill_values(form: str, rng: random.Random):
    """[(page, partial field name, key, kind, printed text, gold value)]; a printed text of None leaves the box
    blank, so the field is absent."""
    p, s = Person(rng), Person(rng)
    joint = rng.random() < 0.45
    out = []

    def add(page, name, key, kind, text, gold=None, blank=False):
        out.append((page, name, key, kind, None if blank else text,
                    None if blank else (gold if gold is not None else text)))

    if form == "f9465":
        yrs = rng.choice(["2024", "2025", "2024 and 2025"])
        add(0, "f1_01[0]", "request_for_forms", "short_text", rng.choice(["1040", "1040-SR"]))
        add(0, "f1_02[0]", "tax_periods", "short_text", yrs)
        add(0, "f1_03[0]", "first_name_and_initial", "name", f"{p.first} {p.mi}")
        add(0, "f1_04[0]", "last_name", "name", p.last)
        add(0, "f1_05[0]", "ssn", "id", p.ssn)
        add(0, "f1_06[0]", "spouse_first_name_and_initial", "name", f"{s.first} {s.mi}", blank=not joint)
        add(0, "f1_07[0]", "spouse_last_name", "name", p.last, blank=not joint)
        add(0, "f1_08[0]", "spouse_ssn", "id", s.ssn, blank=not joint)
        add(0, "f1_09[0]", "street_address", "short_text", p.street)
        add(0, "f1_10[0]", "apt_number", "id", str(rng.randint(2, 40)), blank=rng.random() < 0.7)
        add(0, "f1_11[0]", "city_state_zip", "short_text", f"{p.city}, {p.state} {p.zip}")
        add(0, "f1_12[0]", "foreign_country_name", "short_text", None, blank=True)
        biz = rng.random() < 0.3
        add(0, "f1_15[0]", "sole_proprietorship_name", "name", company(rng, US), blank=not biz)
        add(0, "f1_16[0]", "sole_proprietorship_ein", "id", ein(rng), blank=not biz)
        dd = rng.random() < 0.6
        add(0, "f1_29[0]", "routing_number", "id", f"0{digits(rng, 8)}", blank=not dd)
        add(0, "f1_30[0]", "account_number", "id", digits(rng, rng.randint(8, 12)), blank=not dd)
    elif form == "f1040v":
        add(0, "f1_1[0]", "ssn", "id", p.ssn)
        add(0, "f1_2[0]", "spouse_ssn", "id", s.ssn, blank=not joint)
        amt = round(rng.uniform(120, 9800), 2)
        add(0, "f1_3[0]", "amount_paying", "amount", money(amt, rng), amt)
        add(0, "f1_5[0]", "first_name_and_initial", "name", f"{p.first} {p.mi}")
        add(0, "f1_6[0]", "last_name", "name", p.last)
        add(0, "f1_7[0]", "spouse_first_name_and_initial", "name", f"{s.first} {s.mi}", blank=not joint)
        add(0, "f1_8[0]", "spouse_last_name", "name", p.last, blank=not joint)
        add(0, "f1_9[0]", "home_address", "short_text", p.street)
        add(0, "f1_10[0]", "apt_number", "id", str(rng.randint(2, 40)), blank=rng.random() < 0.7)
        add(0, "f1_11[0]", "city", "short_text", p.city)
        add(0, "f1_12[0]", "state", "id", p.state)
        add(0, "f1_13[0]", "zip_code", "id", p.zip)
        add(0, "f1_14[0]", "foreign_country_name", "short_text", None, blank=True)
    elif form == "f8453":
        add(0, "f1_1[0]", "first_name_and_initial", "name", f"{p.first} {p.mi}")
        add(0, "f1_2[0]", "last_name", "name", p.last)
        add(0, "f1_3[0]", "ssn", "id", p.ssn)
        add(0, "f1_4[0]", "spouse_first_name_and_initial", "name", f"{s.first} {s.mi}", blank=not joint)
        add(0, "f1_5[0]", "spouse_last_name", "name", p.last, blank=not joint)
        add(0, "f1_6[0]", "spouse_ssn", "id", s.ssn, blank=not joint)
        add(0, "f1_7[0]", "home_address", "short_text", p.street)
        add(0, "f1_8[0]", "apt_number", "id", str(rng.randint(2, 40)), blank=rng.random() < 0.7)
        add(0, "f1_9[0]", "city", "short_text", p.city)
        add(0, "f1_10[0]", "state", "id", p.state)
        add(0, "f1_11[0]", "zip_code", "id", p.zip)
        add(0, "f1_12[0]", "foreign_country_name", "short_text", None, blank=True)
    elif form in ("f8879", "f8878"):
        names = f"{p.first} {p.mi}. {p.last}"
        add(0, "f1_02[0]" if form == "f8879" else "f1_2[0]", "taxpayer_name", "name", names)
        add(0, "f1_03[0]" if form == "f8879" else "f1_3[0]", "ssn", "id", p.ssn)
        add(0, "f1_04[0]" if form == "f8879" else "f1_4[0]", "spouse_name", "name", f"{s.first} {p.last}", blank=not joint)
        add(0, "f1_05[0]" if form == "f8879" else "f1_5[0]", "spouse_ssn", "id", s.ssn, blank=not joint)
        ero = company(rng, US, "Tax Services")
        pin = digits(rng, 5)
        if form == "f8879":
            add(0, "f1_06[0]", "tax_year", "integer", "2025", 2025)
            agi = round(rng.uniform(28000, 160000))
            tax = round(agi * rng.uniform(0.06, 0.16))
            wh = round(tax * rng.uniform(0.7, 1.3))
            refund = wh > tax
            add(0, "f1_07[0]", "adjusted_gross_income", "amount", money(agi, rng), agi)
            add(0, "f1_08[0]", "total_tax", "amount", money(tax, rng), tax)
            add(0, "f1_09[0]", "federal_income_tax_withheld", "amount", money(wh, rng), wh)
            add(0, "f1_10[0]", "amount_refunded", "amount", money(wh - tax, rng), wh - tax, blank=not refund)
            add(0, "f1_11[0]", "amount_owed", "amount", money(tax - wh, rng), tax - wh, blank=refund)
            add(0, "f1_12[0]", "ero_firm_name", "name", ero)
            add(0, "f1_13[0]", "taxpayer_pin", "id", pin)
        else:
            add(0, "f1_9[0]", "ero_firm_name", "name", ero)
            add(0, "f1_10[0]", "taxpayer_pin", "id", pin)
    elif form == "f8888":
        add(0, "f1_2[0]", "name_shown_on_return", "name", f"{p.first} {p.mi}. {p.last}")
        add(0, "f1_3[0]", "ssn", "id", p.ssn)
        total = 0
        for i, (a_, r_, c_) in enumerate([("f1_4[0]", "f1_5[0]", "f1_6[0]"), ("f1_7[0]", "f1_8[0]", "f1_9[0]"),
                                          ("f1_10[0]", "f1_11[0]", "f1_12[0]")], 1):
            on = i == 1 or (i == 2 and rng.random() < 0.6) or (i == 3 and rng.random() < 0.25)
            amt = round(rng.uniform(150, 2500))
            total += amt if on else 0
            add(0, a_, f"deposit_{i}_amount", "amount", money(amt, rng), amt, blank=not on)
            add(0, r_, f"deposit_{i}_routing_number", "id", f"0{digits(rng, 8)}", blank=not on)
            add(0, c_, f"deposit_{i}_account_number", "id", digits(rng, rng.randint(8, 12)), blank=not on)
        add(0, "f1_14[0]", "total_allocation", "amount", money(total, rng), total)
    elif form == "f8919":
        add(0, "f1_1[0]", "name", "name", f"{p.first} {p.mi}. {p.last}")
        add(0, "f1_2[0]", "ssn", "id", p.ssn)
        rows = []
        for (n_, e_, c_, d_) in [("f1_3[0]", "f1_4[0]", "f1_5[0]", "f1_6[0]"), ("f1_8[0]", "f1_9[0]", "f1_10[0]", "f1_11[0]")][:rng.randint(1, 2)]:
            d = dt.date(2025, rng.randint(1, 12), rng.randint(1, 28))
            row = {"firm_name": company(rng, US), "firm_ein": ein(rng), "reason_code": rng.choice("ACGH"),
                   "determination_date": d.isoformat()}
            rows.append(row)
            out.append((0, n_, None, None, row["firm_name"], None))
            out.append((0, e_, None, None, row["firm_ein"], None))
            out.append((0, c_, None, None, row["reason_code"], None))
            out.append((0, d_, None, None, us_date(d), None))
        out.append(("rows", "firms", rows))
    elif form == "f8379":
        add(0, "f1_1[0]", "tax_year", "integer", "2025", 2025)
        add(0, "f1_3[0]", "name_shown_first", "name", f"{p.first} {p.mi} {p.last}")
        add(0, "f1_4[0]", "ssn_shown_first", "id", p.ssn)
        add(0, "f1_5[0]", "name_shown_second", "name", f"{s.first} {s.mi} {p.last}")
        add(0, "f1_6[0]", "ssn_shown_second", "id", s.ssn)
        paid = rng.random() < 0.6
        firm = company(rng, US, "Tax Services")
        add(1, "f2_28[0]", "phone_number", "id", p.phone)
        add(1, "f2_29[0]", "preparer_name", "name", f"{rng.choice(FIRST[US])} {rng.choice(LAST[US])}", blank=not paid)
        add(1, "f2_30[0]", "preparer_ptin", "id", f"P{digits(rng, 8)}", blank=not paid)
        add(1, "f2_31[0]", "firm_name", "name", firm, blank=not paid)
        add(1, "f2_34[0]", "firm_ein", "id", ein(rng), blank=not paid)
        add(1, "f2_33[0]", "firm_phone", "id", f"(555) 01{digits(rng, 2)}-{digits(rng, 4)}", blank=not paid)
    elif form == "f8655":
        tp, ag = company(rng, US), company(rng, US, "Payroll Services")
        a1, a2 = address(rng, US), address(rng, US)
        trade = rng.random() < 0.4
        add(0, "f1_01[0]", "taxpayer_name", "name", tp)
        add(0, "f1_02[0]", "trade_name", "name", tp.split()[0] + " " + rng.choice(["Supply", "Works", "Group"]), blank=not trade)
        add(0, "f1_03[0]", "taxpayer_ein", "id", ein(rng))
        add(0, "f1_04[0]", "taxpayer_address", "short_text", a1["street"])
        add(0, "f1_05[0]", "taxpayer_city_state_zip", "short_text", f"{a1['city']}, {a1['region']} {a1['postcode']}")
        add(0, "f1_07[0]", "taxpayer_contact_person", "name", f"{p.first} {p.last}")
        add(0, "f1_08[0]", "taxpayer_phone", "id", p.phone)
        add(0, "f1_09[0]", "taxpayer_fax", "id", f"(555) 01{digits(rng, 2)}-{digits(rng, 4)}", blank=rng.random() < 0.6)
        add(0, "f1_10[0]", "agent_name", "name", ag)
        add(0, "f1_11[0]", "agent_ein", "id", ein(rng))
        add(0, "f1_12[0]", "agent_address", "short_text", a2["street"])
        add(0, "f1_13[0]", "agent_city_state_zip", "short_text", f"{a2['city']}, {a2['region']} {a2['postcode']}")
        add(0, "f1_14[0]", "agent_contact_person", "name", f"{s.first} {s.last}")
        add(0, "f1_15[0]", "agent_phone", "id", s.phone)
        add(0, "f1_16[0]", "agent_fax", "id", f"(555) 01{digits(rng, 2)}-{digits(rng, 4)}", blank=rng.random() < 0.6)
    elif form == "f8857":
        years = sorted(rng.sample([2021, 2022, 2023, 2024], rng.randint(1, 2)))
        for i, y in enumerate(years):
            add(0, f"f1_{i + 1}[0]", f"tax_year_{i + 1}", "integer", str(y), y)
        if len(years) == 1:
            add(0, "f1_2[0]", "tax_year_2", "integer", None, blank=True)
        add(0, "f1_8[0]", "current_name", "name", f"{p.first} {p.mi}. {p.last}")
        add(0, "f1_9[0]", "ssn", "id", p.ssn)
        add(0, "f1_10[0]", "street_address", "short_text", p.street)
        add(0, "f1_11[0]", "apt_number", "id", str(rng.randint(2, 40)), blank=rng.random() < 0.7)
        add(0, "f1_12[0]", "county", "short_text", rng.choice(["Travis", "Franklin", "Multnomah", "Dane", "Wake", "Ada"]) + " County")
        add(0, "f1_13[0]", "city_state_zip", "short_text", f"{p.city}, {p.state} {p.zip}")
        add(0, "f1_14[0]", "daytime_phone", "id", p.phone)
        add(1, "f2_1[0]", "spouse_current_name", "name", f"{s.first} {s.last}")
        add(1, "f2_2[0]", "spouse_ssn", "id", s.ssn, blank=rng.random() < 0.3)
        add(1, "f2_3[0]", "spouse_home_address", "short_text", s.street, blank=rng.random() < 0.3)
        add(1, "f2_5[0]", "spouse_city_state_zip", "short_text", f"{s.city}, {s.state} {s.zip}")
    elif form == "f8233":
        loc = rng.choice(["de-DE", "nl-NL", "es-ES"])
        f_ = Person(rng, loc)
        country = {"de-DE": "Germany", "nl-NL": "Netherlands", "es-ES": "Spain"}[loc]
        entry = dt.date(2025, rng.randint(1, 9), rng.randint(1, 28))
        add(0, "f1_4[0]", "beneficial_owner_name", "name", f"{f_.first} {f_.last}")
        add(0, "f1_5[0]", "us_taxpayer_id", "id", f"9{digits(rng, 2)}-7{digits(rng, 1)}-{digits(rng, 4)}")
        add(0, "f1_6[0]", "foreign_tax_id", "id", digits(rng, 11), blank=rng.random() < 0.4)
        add(0, "f1_7[0]", "permanent_residence_street", "short_text", f_.street)
        add(0, "f1_8[0]", "permanent_residence_city_postal", "short_text", f"{f_.zip} {f_.city}")
        add(0, "f1_9[0]", "permanent_residence_country", "short_text", country)
        add(0, "f1_10[0]", "us_address", "short_text", p.street)
        add(0, "f1_11[0]", "us_city_state_zip", "short_text", f"{p.city}, {p.state} {p.zip}")
        visa = rng.choice(["F-1", "J-1", "H-1B"])
        add(0, "f1_12[0]", "visa_type", "id", visa)
        add(0, "f1_13[0]", "passport_country", "short_text", country)
        add(0, "f1_14[0]", "passport_number", "id", rng.choice("CKLX") + digits(rng, 8))
        add(0, "f1_15[0]", "date_of_entry", "date", us_date(entry), entry.isoformat())
        add(0, "f1_16[0]", "nonimmigrant_status", "id", visa)
        exp = entry.replace(year=entry.year + rng.choice([1, 2, 3]))
        add(0, "f1_17[0]", "status_expiration_date", "date", us_date(exp), exp.isoformat())
        add(1, "f2_29[0]", "withholding_agent_name", "name", company(rng, US))
        add(1, "f2_30[0]", "withholding_agent_ein", "id", ein(rng))
        a2 = address(rng, US)
        add(1, "f2_31[0]", "withholding_agent_address", "short_text", a2["street"])
        add(1, "f2_32[0]", "withholding_agent_city_state_zip", "short_text", f"{a2['city']}, {a2['region']} {a2['postcode']}")
        add(1, "f2_33[0]", "withholding_agent_phone", "id", s.phone)
    elif form == "f56":
        dece = rng.random() < 0.5
        add(0, "f1_01[0]", "name_of_person", "name", f"{p.first} {p.mi}. {p.last}")
        add(0, "f1_02[0]", "identifying_number", "id", p.ssn)
        add(0, "f1_03[0]", "decedent_ssn", "id", p.ssn, blank=not dece)
        add(0, "f1_04[0]", "person_address", "short_text", p.street)
        add(0, "f1_05[0]", "person_room_or_suite", "id", None, blank=True)
        add(0, "f1_06[0]", "person_city", "short_text", p.city)
        add(0, "f1_07[0]", "person_state", "id", p.state)
        add(0, "f1_09[0]", "person_zip", "id", p.zip)
        add(0, "f1_10[0]", "fiduciary_name", "name", f"{s.first} {s.last}")
        add(0, "f1_11[0]", "fiduciary_phone", "id", s.phone)
        add(0, "f1_12[0]", "fiduciary_address", "short_text", s.street)
        add(0, "f1_14[0]", "fiduciary_city", "short_text", s.city)
        add(0, "f1_15[0]", "fiduciary_state", "id", s.state)
        add(0, "f1_17[0]", "fiduciary_zip", "id", s.zip)
        dod = dt.date(2025, rng.randint(1, 12), rng.randint(1, 28))
        add(0, "f1_19[0]", "date_of_death", "date", us_date(dod), dod.isoformat(), blank=not dece)
    elif form == "f4852":
        er = company(rng, US)
        a2 = address(rng, US)
        wages = round(rng.uniform(18000, 120000), 2)
        add(0, "f1_1[0]", "name_shown_on_return", "name", f"{p.first} {p.mi}. {p.last}")
        add(0, "f1_2[0]", "ssn", "id", p.ssn)
        add(0, "f1_3[0]", "address", "short_text", f"{p.street}, {p.city}, {p.state} {p.zip}")
        add(0, "f1_4[0]", "tax_year", "integer", "2025", 2025)
        add(0, "f1_5[0]", "employer_name", "name", er, er)
        out[-1] = (0, "f1_5[0]", "employer_name", "name", f"{er}, {a2['street']}, {a2['city']}, {a2['region']} {a2['postcode']}", er)
        add(0, "f1_6[0]", "employer_tin", "id", ein(rng), blank=rng.random() < 0.3)
        add(0, "f1_7[0]", "wages_tips_other_compensation", "amount", money(wages, rng), wages)
        ss = round(wages * 0.062, 2)
        add(0, "f1_8[0]", "social_security_wages", "amount", money(wages, rng), wages)
        add(0, "f1_9[0]", "medicare_wages_and_tips", "amount", money(wages, rng), wages)
        fit = round(wages * rng.uniform(0.08, 0.15), 2)
        add(0, "f1_11[0]", "federal_income_tax_withheld", "amount", money(fit, rng), fit)
        state_tax = rng.random() < 0.6
        sit = round(wages * 0.04, 2)
        add(0, "f1_12[0]", "state_income_tax_withheld", "amount", money(sit, rng), sit, blank=not state_tax)
        add(0, "f1_16[0]", "social_security_tax_withheld", "amount", money(ss, rng), ss)
        mc = round(wages * 0.0145, 2)
        add(0, "f1_17[0]", "medicare_tax_withheld", "amount", money(mc, rng), mc)
        add(0, "f1_18[0]", "gross_distribution", "amount", None, blank=True)
    elif form == "f3911":
        rd = dt.date(2026, rng.randint(1, 6), rng.randint(1, 28))
        add(0, "your_name[0]", "your_name", "name", f"{p.first} {p.mi}. {p.last}")
        add(0, "your_TIN[0]", "your_tin", "id", p.ssn)
        add(0, "spouses_name[0]", "spouse_name", "name", f"{s.first} {p.last}", blank=not joint)
        add(0, "spouses_TIN[0]", "spouse_tin", "id", s.ssn, blank=not joint)
        add(0, "street[0]", "street", "short_text", p.street)
        add(0, "apartment_number[0]", "apartment_number", "id", str(rng.randint(2, 40)), blank=rng.random() < 0.7)
        add(0, "city[0]", "city", "short_text", p.city)
        add(0, "state[0]", "state", "id", p.state)
        add(0, "zip_code[0]", "zip_code", "id", p.zip)
        add(0, "area_code[0]", "phone_area_code", "id", "555")
        add(0, "phone_number[0]", "phone_number", "id", f"01{digits(rng, 2)}-{digits(rng, 4)}")
        add(0, "form[0]", "type_of_return_form", "id", rng.choice(["1040", "1040-SR"]))
        amt = round(rng.uniform(200, 4800), 2)
        add(0, "refund_amount[0]", "refund_amount", "amount", money(amt, rng), amt)
        add(0, "tax_period[0]", "tax_period", "short_text", str(rd.year - 1))
        add(0, "name_of_bank[0]", "name_of_bank", "name", rng.choice(["First Prairie Bank", "Cascade Federal Credit Union",
                                                                       "Lakeshore Savings Bank"]), blank=rng.random() < 0.5)
    elif form == "f4506t":
        add(0, "f1_1[0]", "name_shown_on_return", "name", f"{p.first} {p.mi}. {p.last}")
        add(0, "f1_2[0]", "ssn", "id", p.ssn)
        add(0, "f1_3[0]", "spouse_name", "name", f"{s.first} {p.last}", blank=not joint)
        add(0, "f1_4[0]", "spouse_ssn", "id", s.ssn, blank=not joint)
        add(0, "f1_5[0]", "current_name_and_address", "short_text",
            f"{p.first} {p.last}, {p.street}, {p.city}, {p.state} {p.zip}")
        add(0, "f1_6[0]", "previous_address", "short_text", None, blank=True)
        add(0, "customer_file_number[0]", "customer_file_number", "id", digits(rng, 10), blank=rng.random() < 0.6)
        add(0, "f1_13[0]", "phone_number", "id", p.phone)
    elif form == "f13844":
        add(0, "familyUnit[0]", "family_unit_size", "integer", str(rng.randint(1, 6)), None)
        out[-1] = out[-1][:5] + (int(out[-1][4]),)
        agi = round(rng.uniform(9000, 70000))
        add(0, "totalIncome[0]", "adjusted_gross_income", "amount", money(agi, rng), agi)
        add(1, "yourName[0]", "your_name", "name", f"{p.last}, {p.first} {p.mi}")
        add(1, "yourSSNTIN[0]", "your_ssn_or_tin", "id", p.ssn)
        add(1, "spouseName[0]", "spouse_name", "name", f"{p.last}, {s.first} {s.mi}", blank=not joint)
        add(1, "spousesSSNTIN[0]", "spouse_ssn_or_tin", "id", s.ssn, blank=not joint)
        d = dt.date(2026, rng.randint(1, 10), rng.randint(1, 28))
        add(1, "yourDate[0]", "date_signed", "date", us_date(d), d.isoformat())
    elif form == "f14157":
        firm = company(rng, US, "Tax Services")
        a2 = address(rng, US)
        add(0, "Preparers_Name_Address[0]", "preparer_name_and_address", "short_text",
            f"{s.first} {s.last}, {a2['street']}, {a2['city']}, {a2['region']} {a2['postcode']}")
        add(0, "Preparers_Business_Name_Address[0]", "preparer_business_name", "name", firm, blank=rng.random() < 0.3)
        add(0, "Preparers_Telephone_Number[0]", "preparer_phone", "id", s.phone)
        user = f"{s.first.lower()}.{s.last.lower().replace(' ', '')}"
        add(0, "Preparers_Email_Address[0]", "preparer_email", "id", f"{user}@example.com", blank=rng.random() < 0.4)
        add(0, "Preparers_Website[0]", "preparer_website", "id", None, blank=True)
        add(0, "Preparers_EFIN[0]", "preparer_efin", "id", digits(rng, 6), blank=rng.random() < 0.5)
        add(0, "PTIN[0]", "preparer_ptin", "id", f"P{digits(rng, 8)}", blank=rng.random() < 0.3)
        add(0, "EIN[0]", "preparer_ein", "id", ein(rng), blank=rng.random() < 0.5)
        add(0, "Tax_Years_Impacted[0]", "tax_years_impacted", "short_text", rng.choice(["2024", "2025", "2024, 2025"]))
    else:
        raise ValueError(form)
    return out


SCHEMA_TYPE = {"id": "string", "name": "string", "short_text": "string", "date": "string", "amount": "number",
               "integer": "integer"}
ROW_MATCH = {"firm_name": "name", "firm_ein": "id", "reason_code": "id", "determination_date": "date"}
FORMS = ["f1040v", "f13844", "f14157", "f3911", "f4506t", "f4852", "f56", "f8233", "f8379", "f8453", "f8655",
         "f8857", "f8878", "f8879", "f8888", "f8919", "f9465", "f9465", "f3911", "f8879"]


def widget_names(reader) -> dict:
    """(page index, partial name) -> (fully qualified field name, rect), for names that are unique on their page."""
    seen, out = Counter(), {}
    for pi, page in enumerate(reader.pages):
        for a in page.get("/Annots") or []:
            a = a.get_object()
            if a.get("/Subtype") != "/Widget":
                continue
            parts, n = [], a
            while n is not None:
                if "/T" in n:
                    parts.append(str(n["/T"]))
                n = n.get("/Parent")
                n = n.get_object() if n is not None else None
            if parts:
                key = (pi, parts[0])
                seen[key] += 1
                out[key] = (".".join(reversed(parts)), [float(v) for v in a["/Rect"]])
    return {k: v for k, v in out.items() if seen[k] == 1}


def fill_pdf(src: Path, values: dict[int, dict[str, str]]) -> bytes:
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter(clone_from=PdfReader(src))
    af = w._root_object.get("/AcroForm")
    af = af.get_object() if af is not None else None
    if af is not None and "/XFA" in af:
        del af["/XFA"]
    for pi, page in enumerate(w.pages):
        if values.get(pi):
            w.update_page_form_field_values(page, values[pi], auto_regenerate=False, flatten=True)
    w.remove_annotations(subtypes="/Widget")
    w.compress_identical_objects()
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def build_one(form: str, n: int, forms_dir: Path):
    from pypdf import PdfReader

    rng = random.Random(f"{SEED}-{form}-{n}")
    src = forms_dir / f"{form}.pdf"
    names = widget_names(PdfReader(src))
    spec = fill_values(form, rng)
    rows = next((x[2] for x in spec if x[0] == "rows"), None)
    spec = [x for x in spec if x[0] != "rows"]
    values: dict[int, dict[str, str]] = {}
    for page, partial, _key, _kind, text, _gold in spec:
        if text is None:
            continue
        hit = names.get((page, partial))
        if hit is None:
            raise SystemExit(f"{form}: no unique field {partial} on page {page + 1}")
        values.setdefault(page, {})[hit[0]] = text
    data = fill_pdf(src, values)
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(data)
    pages = len(doc)
    idx = TextIndex([doc[i].get_textpage().get_text_range() for i in range(pages)])

    def in_box(page, partial, kind, gold):
        """The value read back from inside its own box (the text layer may glue neighbouring boxes together)."""
        x0, y0, x1, y1 = names[(page, partial)][1]
        got = doc[page].get_textpage().get_text_bounded(left=x0 - 1, bottom=y0 - 1, right=x1 + 1, top=y1 + 1)
        return TextIndex([got]).visible(kind, gold), {"page": page + 1, "text": got.strip()[:200]}
    props, fields = {}, {}
    for page, partial, key, kind, _text, gold in spec:
        if key is None:
            continue
        props[key] = {"type": [SCHEMA_TYPE[kind], "null"], **({"format": "date"} if kind == "date" else {})}
        base = {"match": kind, "provenance": "form_fill"}
        if gold is None:
            fields[f"/{key}"] = {"status": "absent", "value": None, **base,
                                 "evidence": {"check": "the box is printed empty: nothing was filled in"}}
        elif (seen := in_box(page, partial, kind, gold))[0]:
            fields[f"/{key}"] = {"status": "present", "value": gold, **base, "evidence": seen[1]}
        else:
            fields[f"/{key}"] = {"status": "excluded", "value": None, **base,
                                 "reason": "filled but not read back from its box; needs a human check"}
    if rows is not None:
        props["firms"] = {"type": ["array", "null"], "items": _obj({k: {"type": ["string", "null"],
                                                                     **({"format": "date"} if v == "date" else {})}
                                                                 for k, v in ROW_MATCH.items()})}
        ok = all(idx.visible(k, r[c]) for r in rows for c, k in ROW_MATCH.items() if k != "date") and all(
            TextIndex([doc[0].get_textpage().get_text_range()]).has_date(r["determination_date"]) for r in rows)
        fields["/firms"] = ({"status": "present", "value": rows, "match": "array_objects", "item_match": ROW_MATCH,
                             "provenance": "form_fill"} if ok else
                            {"status": "excluded", "value": None, "match": "array_objects", "item_match": ROW_MATCH,
                             "provenance": "form_fill", "reason": "rows not found in the text layer"})
    tid = f"irsform-{form[1:]}-{n:02d}"
    task = {"task_id": tid, "doc_id": tid, "track": "forms", "family": f"irs_{form}", "source": "irs-form-fill",
            "source_ref": {"form_url": f"https://www.irs.gov/pub/irs-pdf/{form}.pdf", "form_sha256": sha256(src),
                           "seed": f"{SEED}-{form}-{n}"},
            "license": "form: US government public domain; fill values: CC-BY-4.0 (synthetic)", "published": None,
            "language": "en", "locale": {"date_order": "MDY", "decimal": "."},
            "document": {"path": f"docs/{tid}.pdf", "media_type": "application/pdf", "pages": pages,
                         "condition": "born_digital"},
            "variant_of": None, "layout_family": f"irs/{form}", "doc_type": "us_government_form",
            "schema": _obj(props), "fields": fields}
    return task, data


def main(argv=None) -> int:
    import os
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--forms", type=Path, required=True, help="directory with the blank IRS PDFs (fNNNN.pdf)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    os.environ["SOURCE_DATE_EPOCH"] = "1793404800"
    tasks, count = [], Counter()
    for form in FORMS:
        task, data = build_one(form, count[form], a.forms)
        count[form] += 1
        errs = validate_task(task)
        if errs:
            raise SystemExit(f"{task['task_id']}: {errs[:3]}")
        write_bytes_task(a.out, task, data)
        tasks.append(task)
    (a.out / "sources").mkdir(parents=True, exist_ok=True)
    (a.out / "sources" / "formfill.json").write_text(json.dumps(
        {"source": "irs-form-fill", "seed": SEED,
         "documents": [{"task_id": t["task_id"], **t["source_ref"]} for t in tasks]}, indent=1) + "\n")
    st = Counter(r["status"] for t in tasks for r in t["fields"].values())
    print(f"formfill: {len(tasks)} tasks; fields {dict(st)}")
    for t in tasks:
        bad = [p for p, r in t["fields"].items() if r["status"] == "excluded"]
        if bad:
            print(f"  {t['task_id']}: excluded {bad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
