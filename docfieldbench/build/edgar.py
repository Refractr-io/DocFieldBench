"""SEC EDGAR filings made on or after 2026-11-02 (class T: newer than any model trained before November 2026).

Two families:
- sec_cover: the cover page of a 10-Q or 10-K, shipped as HTML. Gold comes from the filing's inline XBRL cover tags
  (dei:*); the shipped page has every ix tag, the hidden ix:header and the XBRL namespaces removed, so the markup
  can't hand out the answer (a gate checks it), and is cut at the first page break.
- form4: an insider transaction report, shipped as the SEC's own HTML rendering. Gold comes from the XML it renders.

SEC asks automated clients for a contact User-Agent. It is read from a local file (--user-agent-file) and used only
in request headers; it is never written anywhere. Requests are paced to at most 4 per second and cached.

  python -m docfieldbench.build.edgar --cache CACHE_DIR --out data/v1.0.0-new
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import random
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

from ..normalize import parse_date
from ..tasks import validate_task
from .common import write_bytes_task
from .families import _d, _obj, _s
from .visibility import TextIndex

SEED = 20261111
DAYS = ["20261102", "20261103", "20261104", "20261105", "20261106", "20261109", "20261110"]
N_COVER, N_FORM4, MAX_PER_FAMILY = 19, 6, 6
LEAK = re.compile(r"ix:|dei:|us-gaap|xbrli|contextref|ix-|xbrl\.org", re.I)


class Sec:
    def __init__(self, cache: Path, ua_file: Path):
        self.cache = cache
        self.ua = ua_file.expanduser().read_text().strip()
        self.last = 0.0

    def get(self, url: str) -> bytes:
        p = self.cache / re.sub(r"^https://(www\.)?sec\.gov/", "", url)
        if p.exists():
            return p.read_bytes()
        wait = 0.25 - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": self.ua, "Accept-Encoding": "identity"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        self.last = time.time()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return data


def index_entries(sec: Sec, day: str, forms: set[str]) -> list[dict]:
    t = sec.get(f"https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/form.{day}.idx").decode("latin-1")
    out = []
    for line in (x.strip() for x in t.splitlines()):
        m = re.match(r"^(\S+)\s+(.*?)\s{2,}(\d+)\s+(\d{8})\s+(\S+)$", line)
        if m and m.group(1) in forms:
            acc = m.group(5).rsplit("/", 1)[1][:-4]
            out.append({"form": m.group(1), "company": m.group(2), "cik": m.group(3), "filed": m.group(4),
                        "accession": acc})
    return out


def filing_docs(sec: Sec, e: dict) -> list[tuple[str, str]]:
    """(type, url) for each document in the filing index."""
    base = f"https://www.sec.gov/Archives/edgar/data/{e['cik']}/{e['accession'].replace('-', '')}"
    idx = sec.get(f"{base}/{e['accession']}-index.htm").decode("latin-1")
    out = []
    for row in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", idx):
        cells = re.findall(r"(?is)<td[^>]*>(.*?)</td>", row)
        if len(cells) < 4:
            continue
        href = re.search(r'href="([^"]+)"', cells[2])
        if href:
            url = "https://www.sec.gov" + href.group(1).replace("/ix?doc=", "")
            out.append((re.sub(r"<[^>]+>", "", cells[3]).strip(), url))
    return out


def html_text(h: str) -> list[str]:
    """Readable text of an HTML fragment, one line per block element."""
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d|table)>", "\n", h)
    h = re.sub(r"(?i)</t[dh]>", " \t ", h)
    t = htmllib.unescape(re.sub(r"<[^>]+>", " ", h)).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", x).strip() for x in t.splitlines()]
    return ["\n".join(x for x in lines if x)]


def inner(fragment: str) -> str:
    """A tag's printed text; the separator a filer tagged along ("New York,") is not part of the value."""
    t = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment)).replace("\xa0", " "))
    return t.strip().rstrip(",;:").strip()


# ------------------------------------------------------------------------------------------------ sec_cover

COVER_SCHEMA = _obj({
    "registrant_name": _s(), "period_end_date": _d(), "commission_file_number": _s(),
    "state_of_incorporation": _s(), "irs_employer_id": _s(),
    "address": _obj({"street": _s(), "city": _s(), "state": _s(), "postal_code": _s()}),
    "phone": _s(), "former_name": _s(),
    "securities": {"type": ["array", "null"], "items": _obj({"title": _s(), "trading_symbol": _s(), "exchange": _s()})},
    "shares_outstanding": {"type": ["integer", "null"]}, "shares_outstanding_date": _d(),
})
COVER_MATCH = {"/registrant_name": "name", "/period_end_date": "date", "/commission_file_number": "id",
               "/state_of_incorporation": "short_text", "/irs_employer_id": "id", "/address/street": "short_text",
               "/address/city": "short_text", "/address/state": "short_text", "/address/postal_code": "id",
               "/phone": "id", "/former_name": "short_text", "/shares_outstanding": "integer",
               "/shares_outstanding_date": "date"}
SECURITY_MATCH = {"title": "short_text", "trading_symbol": "id", "exchange": "short_text"}
TAGS = {"dei:EntityRegistrantName": "/registrant_name", "dei:DocumentPeriodEndDate": "/period_end_date",
        "dei:EntityFileNumber": "/commission_file_number", "dei:EntityIncorporationStateCountryCode":
        "/state_of_incorporation", "dei:EntityTaxIdentificationNumber": "/irs_employer_id",
        "dei:EntityAddressCityOrTown": "/address/city", "dei:EntityAddressStateOrProvince": "/address/state",
        "dei:EntityAddressPostalZipCode": "/address/postal_code", "dei:EntityFormerName": "/former_name"}
_TAG = re.compile(r'<ix:(nonNumeric|nonFraction)\b([^>]*)>(.*?)</ix:\1>', re.S)


def _attr(attrs: str, name: str) -> str | None:
    m = re.search(rf'\b{name}="([^"]*)"', attrs)
    return m.group(1) if m else None


def cover_cut(h: str) -> tuple[str, str] | None:
    """(the cover fragment with tags, the hidden header) or None."""
    hdr = re.search(r"<ix:header>.*?</ix:header>", h, re.S)
    body = re.search(r"<body[^>]*>", h, re.I)
    if not hdr or not body:
        return None
    start = h.find("dei:EntityRegistrantName", hdr.end())
    if start < 0:
        return None
    pb = re.compile(r"page-break-(?:after|before)\s*:\s*always|break-(?:after|before)\s*:\s*page", re.I)
    m = next((m for m in pb.finditer(h, start)), None)
    if m is None:
        return None
    cut = h.rfind("<", 0, m.start())
    return h[body.end():cut], hdr.group(0)


def sanitise(fragment: str, header: str) -> str:
    f = fragment.replace(header, "")
    f = re.sub(r'<div[^>]*display:\s*none[^>]*>\s*</div>', "", f)
    f = re.sub(r"</?ix:[^>]*>", "", f)
    f = re.sub(r"(?is)<img[^>]*>", "", f)
    f = re.sub(r"(?is)<a\b[^>]*>(.*?)</a>", r"\1", f)
    attrs = r"contextref|unitref|xmlns(?::\w+)?|escape|format|scale|decimals|name|id"
    f = re.sub(rf'\s(?:{attrs})="[^"]*"', "", f, flags=re.I)
    return ("<!doctype html><html><head><meta charset='utf-8'></head><body>" + f + "</body></html>")


def cover_gold(fragment: str, header: str):
    vals, sec_rows, shares = {}, defaultdict(list), []
    for _kind, attrs, body in _TAG.findall(fragment):
        name = _attr(attrs, "name")
        text = inner(body)
        if not text:
            continue
        if name in TAGS and TAGS[name] not in vals:
            vals[TAGS[name]] = text
        elif name == "dei:EntityAddressAddressLine1":
            vals["/address/street"] = text
        elif name in ("dei:CityAreaCode", "dei:LocalPhoneNumber"):
            vals.setdefault("phone_parts", []).append(text)
        elif name in ("dei:Security12bTitle", "dei:TradingSymbol", "dei:SecurityExchangeName"):
            sec_rows[name].append(text)
        elif name == "dei:EntityCommonStockSharesOutstanding":
            shares.append((text, _attr(attrs, "contextRef"), _attr(attrs, "scale")))
    if "/period_end_date" in vals:
        d = parse_date(vals["/period_end_date"], "MDY")
        vals["/period_end_date"] = d[0] if d else None
    parts = vals.pop("phone_parts", [])
    if len(parts) == 2:
        area = parts[0].strip("() ")
        vals["/phone"] = f"({area}) {parts[1]}"
    rows = []
    n = len(sec_rows["dei:TradingSymbol"])
    if n and len(sec_rows["dei:Security12bTitle"]) == n and len(sec_rows["dei:SecurityExchangeName"]) == n:
        rows = [{"title": sec_rows["dei:Security12bTitle"][i], "trading_symbol": sec_rows["dei:TradingSymbol"][i],
                 "exchange": sec_rows["dei:SecurityExchangeName"][i]} for i in range(n)]
    share_val = share_date = None
    if len(shares) == 1:
        text, ctx, scale = shares[0]
        try:
            share_val = int(round(float(text.replace(",", "")) * 10 ** int(scale or 0)))
        except ValueError:
            share_val = None
        ctx_rx = rf'<xbrli:context id="{re.escape(ctx or "")}">.*?<xbrli:instant>(\d{{4}}-\d{{2}}-\d{{2}})'
        m = re.search(ctx_rx, header, re.S)
        share_date = m.group(1) if m else None
    return vals, rows, (share_val, share_date, len(shares)), bool(n)


def layout_family(h: str) -> str:
    head = h[:6000].lower()
    agents = [("workiva", "workiva"), ("toppan-merrill", "toppan|merrill"), ("donnelley", "donnelley|dfin"),
              ("broadridge", "broadridge"), ("edgar-agents", "edgar agents"), ("novaworks", "novaworks|gofiler"),
              ("certent", "certent"), ("ez-xbrl", "ez-xbrl|ezxbrl"), ("inline-xbrl-tool", "generated by")]
    for name, pat in agents:
        if re.search(pat, head):
            return f"edgar/{name}"
    m = re.search(r'<meta[^>]*name="generator"[^>]*content="([^"]+)"', h[:6000], re.I)
    return "edgar/" + (re.sub(r"[^a-z0-9]+", "-", m.group(1).lower())[:30] if m else "unknown")


def build_cover(sec: Sec, e: dict) -> tuple[dict, bytes] | str:
    docs = filing_docs(sec, e)
    main = next((u for t, u in docs if t == e["form"] and u.endswith(".htm")), None)
    if not main:
        return "no primary htm"
    h = sec.get(main).decode("utf-8", "replace")
    cut = cover_cut(h)
    if not cut:
        return "no inline XBRL cover"
    frag, header = cut
    page = sanitise(frag, header)
    if LEAK.search(page):
        return "markup leak after sanitising"
    idx = TextIndex(html_text(page))
    vals, rows, (shares, share_date, n_share), has_12b = cover_gold(frag, header)
    if not vals.get("/registrant_name"):
        return "no registrant name"
    fields = {}
    for ptr, kind in COVER_MATCH.items():
        base = {"match": kind, "provenance": "source_markup"}
        v = {"/shares_outstanding": shares, "/shares_outstanding_date": share_date}.get(ptr, vals.get(ptr))
        if ptr.startswith("/shares") and n_share > 1:
            fields[ptr] = {"status": "excluded", "value": None, **base,
                           "reason": "several share classes are reported; one value can't hold them"}
        elif ptr == "/former_name" and v is None:
            m = re.search(r"former (?:name|address)[^\n]{0,120}", idx.text, re.I)
            near = idx.text[max(0, m.start() - 120): m.end() + 60] if m else ""
            na = re.search(r"\b(n/?a|not applicable|none)\b", near, re.I)
            fields[ptr] = ({"status": "absent", "value": None, **base,
                            "evidence": {"check": "the former-name line reads N/A or is left blank"}} if m and na else
                           {"status": "excluded", "value": None, **base, "reason": "former-name line not found"})
        elif v is None:
            fields[ptr] = {"status": "excluded", "value": None, **base, "reason": "not tagged on the cover"}
        elif idx.visible(kind, v):
            fields[ptr] = {"status": "present", "value": v, **base, "evidence": idx.evidence(kind, v)}
        else:
            fields[ptr] = {"status": "excluded", "value": None, **base,
                           "reason": "tagged but not found in the shipped text; needs a human check"}
    sbase = {"match": "array_objects", "provenance": "source_markup", "item_match": dict(SECURITY_MATCH)}
    if rows and all(idx.visible(k, r[c]) for r in rows for c, k in SECURITY_MATCH.items()):
        fields["/securities"] = {"status": "present", "value": rows, **sbase}
    elif not has_12b and re.search(r"section 12\(b\)", idx.text, re.I) and re.search(r"\bnone\b", idx.text, re.I):
        fields["/securities"] = {"status": "absent", "value": None, **sbase,
                                 "evidence": {"check": "no Section 12(b) security tagged; the table reads None"}}
    else:
        fields["/securities"] = {"status": "excluded", "value": None, **sbase,
                                 "reason": "Section 12(b) rows not verifiable"}
    tid = f"edgar-{e['form'].lower().replace('-', '')}-{e['cik']}"
    filed = f"{e['filed'][:4]}-{e['filed'][4:6]}-{e['filed'][6:]}"
    task = {"task_id": tid, "doc_id": tid, "track": "records", "family": "sec_cover", "source": "sec-edgar",
            "source_ref": {"url": main, "accession": e["accession"], "form": e["form"]},
            "license": "public domain (US government filing system; content filed by the registrant)",
            "published": filed, "language": "en", "locale": {"date_order": "MDY", "decimal": "."},
            "document": {"path": f"docs/{tid}.html", "media_type": "text/html", "pages": 1,
                         "condition": "born_digital"},
            "variant_of": None, "layout_family": layout_family(h), "doc_type": e["form"],
            "schema": json.loads(json.dumps(COVER_SCHEMA)), "fields": fields}
    if sum(r["status"] == "present" for r in fields.values()) < 7:
        return "too few verifiable fields"
    return task, page.encode("utf-8")


# ------------------------------------------------------------------------------------------------ form 4

FORM4_SCHEMA = _obj({
    "issuer_name": _s(), "issuer_trading_symbol": _s(),
    "reporting_owner": _obj({"name": _s(), "street": _s(), "city": _s(), "state": _s(), "postal_code": _s()}),
    "is_director": {"type": ["boolean", "null"]}, "is_officer": {"type": ["boolean", "null"]},
    "is_ten_percent_owner": {"type": ["boolean", "null"]}, "officer_title": _s(), "earliest_transaction_date": _d(),
    "transactions": {"type": ["array", "null"], "items": _obj({
        "security_title": _s(), "date": _d(), "code": _s(), "shares": {"type": ["number", "null"]},
        "price": {"type": ["number", "null"]}, "acquired_or_disposed": _s(),
        "owned_after": {"type": ["number", "null"]}})},
})
FORM4_MATCH = {"/issuer_name": "name", "/issuer_trading_symbol": "id", "/reporting_owner/name": "name",
               "/reporting_owner/street": "short_text", "/reporting_owner/city": "short_text",
               "/reporting_owner/state": "id", "/reporting_owner/postal_code": "id", "/is_director": "boolean",
               "/is_officer": "boolean", "/is_ten_percent_owner": "boolean", "/officer_title": "short_text",
               "/earliest_transaction_date": "date"}
TX_MATCH = {"security_title": "short_text", "date": "date", "code": "id", "shares": "number", "price": "amount",
            "acquired_or_disposed": "id", "owned_after": "number"}


def _x(node, path):
    el = node.find(path)
    return el.text.strip() if el is not None and el.text and el.text.strip() else None


def _num(s):
    try:
        return float(s) if s is not None else None
    except ValueError:
        return None


def reorder(name: str) -> str | None:
    """'ALEXANDER PATRICK L' -> 'PATRICK L ALEXANDER' (EDGAR prints persons last name first)."""
    parts = name.split()
    return " ".join(parts[1:] + parts[:1]) if 2 <= len(parts) <= 4 and "," not in name else None


def build_form4(sec: Sec, e: dict) -> tuple[dict, bytes] | str:
    docs = filing_docs(sec, e)
    xml_u = next((u for t, u in docs if t == "4" and u.endswith(".xml") and "/xsl" not in u), None)
    htm_u = next((u for t, u in docs if t == "4" and "/xsl" in u), None)
    if not xml_u or not htm_u:
        return "no XML or rendering"
    root = ET.fromstring(sec.get(xml_u))
    owners = root.findall("reportingOwner")
    if len(owners) != 1 or root.find("derivativeTable/derivativeTransaction") is not None:
        return "several owners or derivative rows"
    o = owners[0]
    rel = o.find("reportingOwnerRelationship")
    gold = {"/issuer_name": _x(root, "issuer/issuerName"),
            "/issuer_trading_symbol": _x(root, "issuer/issuerTradingSymbol"),
            "/reporting_owner/name": _x(o, "reportingOwnerId/rptOwnerName"),
            "/reporting_owner/street": _x(o, "reportingOwnerAddress/rptOwnerStreet1"),
            "/reporting_owner/city": _x(o, "reportingOwnerAddress/rptOwnerCity"),
            "/reporting_owner/state": _x(o, "reportingOwnerAddress/rptOwnerState"),
            "/reporting_owner/postal_code": _x(o, "reportingOwnerAddress/rptOwnerZipCode"),
            "/is_director": _x(rel, "isDirector") in ("1", "true"),
            "/is_officer": _x(rel, "isOfficer") in ("1", "true"),
            "/is_ten_percent_owner": _x(rel, "isTenPercentOwner") in ("1", "true"),
            "/officer_title": _x(rel, "officerTitle"), "/earliest_transaction_date": _x(root, "periodOfReport")}
    rows = [{"security_title": _x(t, "securityTitle/value"), "date": _x(t, "transactionDate/value"),
             "code": _x(t, "transactionCoding/transactionCode"),
             "shares": _num(_x(t, "transactionAmounts/transactionShares/value")),
             "price": _num(_x(t, "transactionAmounts/transactionPricePerShare/value")),
             "acquired_or_disposed": _x(t, "transactionAmounts/transactionAcquiredDisposedCode/value"),
             "owned_after": _num(_x(t, "postTransactionAmounts/sharesOwnedFollowingTransaction/value"))}
            for t in root.findall("nonDerivativeTable/nonDerivativeTransaction")]
    if not rows or len(rows) > 12:
        return "no or too many transactions"
    page = sec.get(htm_u).decode("utf-8", "replace")
    page = re.sub(r"(?is)<script[^>]*>.*?</script>", "", page)
    idx = TextIndex(html_text(page))
    fields = {}
    for ptr, kind in FORM4_MATCH.items():
        base = {"match": kind, "provenance": "source_markup"}
        v = gold[ptr]
        if kind == "boolean":
            fields[ptr] = {"status": "present", "value": v, **base, "evidence": {"check": "checkbox in the rendering"}}
        elif v is None:
            ok = ptr == "/officer_title" and not gold["/is_officer"]
            fields[ptr] = ({"status": "absent", "value": None, **base,
                            "evidence": {"check": "the owner is not an officer; no title is printed"}} if ok else
                           {"status": "excluded", "value": None, **base, "reason": "not in the XML"})
        elif idx.visible(kind, v):
            fields[ptr] = {"status": "present", "value": v, **base, "evidence": idx.evidence(kind, v)}
            if ptr == "/reporting_owner/name" and reorder(v):
                fields[ptr]["accept"] = [reorder(v)]
        else:
            fields[ptr] = {"status": "excluded", "value": None, **base,
                           "reason": "in the XML but not found in the rendering; needs a human check"}
    keep = {c: k for c, k in TX_MATCH.items() if all(r[c] is not None and idx.visible(k, r[c]) for r in rows)}
    schema = json.loads(json.dumps(FORM4_SCHEMA))
    items = schema["properties"]["transactions"]["items"]
    for c in TX_MATCH:
        if c not in keep:
            del items["properties"][c]
            items["required"].remove(c)
    tbase = {"match": "array_objects", "provenance": "source_markup", "item_match": keep}
    if "date" in keep and "shares" in keep:
        fields["/transactions"] = {"status": "present", "value": [{c: r[c] for c in keep} for r in rows], **tbase}
    else:
        return "transactions not verifiable"
    tid = f"edgar-form4-{e['accession']}"
    filed = f"{e['filed'][:4]}-{e['filed'][4:6]}-{e['filed'][6:]}"
    task = {"task_id": tid, "doc_id": tid, "track": "records", "family": "form4", "source": "sec-edgar",
            "source_ref": {"url": htm_u, "accession": e["accession"], "form": "4"},
            "license": "public domain (US government filing system; content filed by the reporting person)",
            "published": filed, "language": "en", "locale": {"date_order": "MDY", "decimal": "."},
            "document": {"path": f"docs/{tid}.html", "media_type": "text/html", "pages": 1,
                         "condition": "born_digital"},
            "variant_of": None, "layout_family": "edgar/form4-sec-rendering", "doc_type": "form4",
            "schema": schema, "fields": fields}
    return task, page.encode("utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cache", type=Path, required=True, help="where downloads are kept (outside the repo)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--user-agent-file", type=Path, default=Path("~/.config/docfieldbench/sec_user_agent"))
    a = ap.parse_args(argv)
    sec = Sec(a.cache, a.user_agent_file)
    rng = random.Random(SEED)
    covers = [x for d in DAYS for x in index_entries(sec, d, {"10-Q", "10-K"})]
    form4 = [x for d in DAYS for x in index_entries(sec, d, {"4"})]
    rng.shuffle(covers)
    rng.shuffle(form4)
    tasks, skipped, fam = [], Counter(), Counter()
    seen = set()
    for e in covers:
        if sum(t["family"] == "sec_cover" for t, _ in tasks) >= N_COVER:
            break
        if e["cik"] in seen:
            continue
        seen.add(e["cik"])
        r = build_cover(sec, e)
        if isinstance(r, str):
            skipped[f"cover: {r}"] += 1
            continue
        task, data = r
        if fam[task["layout_family"]] >= MAX_PER_FAMILY:
            skipped["cover: family cap"] += 1
            continue
        fam[task["layout_family"]] += 1
        tasks.append((task, data))
    issuers = set()
    for e in form4:
        if sum(t["family"] == "form4" for t, _ in tasks) >= N_FORM4:
            break
        r = build_form4(sec, e)
        if isinstance(r, str):
            skipped[f"form4: {r}"] += 1
            continue
        task, data = r
        if task["fields"]["/issuer_name"].get("value") in issuers:
            continue
        issuers.add(task["fields"]["/issuer_name"].get("value"))
        tasks.append((task, data))
    ua = sec.ua
    for task, data in tasks:
        errs = validate_task(task)
        if errs:
            raise SystemExit(f"{task['task_id']}: {errs[:3]}")
        blob = json.dumps(task) + data.decode("utf-8", "replace")
        if ua in blob or any(tok in blob for tok in ua.split() if "@" in tok):
            raise SystemExit("the User-Agent contact would be written to the dataset; stopping")
        write_bytes_task(a.out, task, data)
    (a.out / "sources").mkdir(parents=True, exist_ok=True)
    (a.out / "sources" / "edgar.json").write_text(json.dumps(
        {"source": "sec-edgar", "days": DAYS, "seed": SEED,
         "documents": [{"task_id": t["task_id"], **t["source_ref"], "filed": t["published"]} for t, _ in tasks]},
        indent=1) + "\n")
    st = Counter((t["family"], r["status"]) for t, _ in tasks for r in t["fields"].values())
    print(f"edgar: {len(tasks)} tasks; skipped {dict(skipped)}")
    print("families:", dict(Counter(t["layout_family"] for t, _ in tasks)))
    print("statuses:", dict(st))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
