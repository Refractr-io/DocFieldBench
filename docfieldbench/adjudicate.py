"""Blind adjudication: review gold against the answers systems gave, without system names.

  docfieldbench adjudicate build POOL.json --data DIR --out DIR/review.html
  docfieldbench adjudicate apply POOL.json DECISIONS.json --data DIR [--log ADJUDICATION_LOG.md]

POOL.json is a list of items {"id", "task_id", "pointer", "unit", "kind", "gold", "answers": [...]} (answers
shuffled, without names or counts; whoever builds the pool keeps the mapping). The review page shows each document
beside its items, grouped by document, with four decisions per item: gold stands, gold is fixed (enter the value),
an answer is also accepted (alias), or the field is excluded (enter a reason). Decisions stay in the browser
(localStorage) and download as JSON. `apply` patches the task files and writes the adjudication log.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>DocFieldBench adjudication</title><style>
body{margin:0;font:14px system-ui,sans-serif;display:flex;height:100vh}
#docs{width:240px;overflow:auto;border-right:1px solid #ccc}#docs div{padding:4px 8px;cursor:pointer}
#docs div.cur{background:#dde}#docs div.done{color:#888}
#view{flex:1;display:flex;flex-direction:column}#frame{flex:1;border:0}#items{height:42%;overflow:auto;padding:8px;border-top:2px solid #444}
.item{border:1px solid #ccc;margin:6px 0;padding:6px}.item.decided{background:#eef7ee}.g{font-weight:600}
.a{font-family:monospace;background:#f4f4f4;padding:1px 4px;margin:2px;display:inline-block}
button{margin:2px}input{width:260px}#bar{padding:6px;border-bottom:1px solid #ccc}
</style></head><body><div id="docs"></div><div id="view"><div id="bar"><b id="title"></b> <span id="count"></span>
<button onclick="dl()">download decisions</button></div><iframe id="frame"></iframe><div id="items"></div></div>
<script>
const POOL=__POOL__, DOCS=__DOCS__, KEY="dfb-adj-"+__KEY__;
let dec={};try{dec=JSON.parse(localStorage.getItem(KEY)||"{}")}catch(e){}
const byDoc={};POOL.forEach(i=>(byDoc[i.task_id]=byDoc[i.task_id]||[]).push(i));
const order=Object.keys(byDoc);let cur=0;
function save(){try{localStorage.setItem(KEY,JSON.stringify(dec))}catch(e){}render()}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
function set(id,d){dec[id]=d;save()}
function render(){const d=document.getElementById("docs");d.innerHTML="";order.forEach((t,k)=>{const e=document.createElement("div");
e.textContent=t+" ("+byDoc[t].length+")";if(k==cur)e.className="cur";else if(byDoc[t].every(i=>dec[i.id]))e.className="done";
e.onclick=()=>{cur=k;render()};d.appendChild(e)});const t=order[cur];document.getElementById("title").textContent=t;
const f=document.getElementById("frame");if(f.dataset.t!==t){f.src=DOCS[t];f.dataset.t=t}
const n=Object.keys(dec).length;document.getElementById("count").textContent=n+" / "+POOL.length+" decided";
const box=document.getElementById("items");box.innerHTML="";byDoc[t].forEach(i=>{const x=dec[i.id];const e=document.createElement("div");
e.className="item"+(x?" decided":"");e.innerHTML="<div>"+esc(i.pointer)+" <small>("+esc(i.kind)+")</small></div>"+
"<div>gold: <span class=g>"+esc(JSON.stringify(i.gold))+"</span></div><div>answers: "+i.answers.map(a=>"<span class=a>"+esc(JSON.stringify(a))+"</span>").join("")+"</div>"+
(x?"<div><i>"+esc(JSON.stringify(x))+"</i></div>":"");
const b=(lab,fn)=>{const q=document.createElement("button");q.textContent=lab;q.onclick=fn;e.appendChild(q)};
b("gold stands",()=>set(i.id,{decision:"stands"}));
b("fix gold",()=>{const v=prompt("correct value (JSON, e.g. \\"ABC\\" or 12.5 or null)",JSON.stringify(i.gold));if(v!==null)set(i.id,{decision:"fix",value:JSON.parse(v)})});
i.answers.forEach(a=>b("accept "+JSON.stringify(a).slice(0,30),()=>set(i.id,{decision:"accept",value:a})));
b("exclude",()=>{const r=prompt("reason");if(r)set(i.id,{decision:"exclude",reason:r})});box.appendChild(e)})}
function dl(){const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([JSON.stringify(dec,null,1)],{type:"application/json"}));
a.download="decisions.json";a.click()}
document.addEventListener("keydown",e=>{if(e.key=="ArrowDown"||e.key=="j"){cur=Math.min(order.length-1,cur+1);render()}
if(e.key=="ArrowUp"||e.key=="k"){cur=Math.max(0,cur-1);render()}});render();
</script></body></html>"""


def build(pool_path: Path, data: Path, out: Path) -> int:
    pool = json.loads(pool_path.read_text())
    docs = {}
    for i in pool:
        if i["task_id"] not in docs:
            t = json.loads((data / "tasks" / f"{i['task_id']}.json").read_text())
            docs[i["task_id"]] = str(Path(t["document"]["path"]))
    page = (PAGE.replace("__POOL__", json.dumps(pool, ensure_ascii=False))
            .replace("__DOCS__", json.dumps(docs)).replace("__KEY__", json.dumps(pool_path.stem)))
    out.write_text(page)
    print(f"{out}: {len(pool)} items over {len(docs)} documents (open it from {data} so document paths resolve)")
    return 0


def _set_field(rec: dict, unit: str, pointer: str, d: dict) -> str:
    """Apply one decision to a field record; returns a log line."""
    sub = unit[len(pointer):].strip("/")
    if d["decision"] == "stands":
        return ""
    if d["decision"] == "exclude":
        rec.clear()
        rec.update({"status": "excluded", "value": None, "match": rec.get("match", "short_text"),
                    "reason": f"adjudication: {d['reason']}"})
        return f"excluded: {d['reason']}"
    if not sub:                                            # a scalar field
        if d["decision"] == "accept":
            rec.setdefault("accept", []).append(d["value"])
            return f"also accepted: {json.dumps(d['value'], ensure_ascii=False)}"
        old = rec.get("value")
        if d["value"] is None:
            rec.update({"status": "absent", "value": None, "evidence": {"check": "adjudication: not stated"}})
        else:
            rec.update({"status": "present", "value": d["value"]})
        return f"gold fixed: {json.dumps(old, ensure_ascii=False)} -> {json.dumps(d['value'], ensure_ascii=False)}"
    parts = sub.split("/")                                   # a row cell or a list item: rows/<i>/<col> or <i>
    rows = rec.get("value") or []
    if len(parts) == 2 and parts[0].isdigit() and int(parts[0]) < len(rows) and isinstance(rows[int(parts[0])], dict):
        old = rows[int(parts[0])].get(parts[1])
        if d["decision"] == "fix":
            rows[int(parts[0])][parts[1]] = d["value"]
            return f"row {parts[0]} {parts[1]}: {json.dumps(old, ensure_ascii=False)} -> {json.dumps(d['value'], ensure_ascii=False)}"
    if len(parts) == 1 and parts[0].isdigit() and int(parts[0]) < len(rows) and d["decision"] == "fix":
        old = rows[int(parts[0])]
        rows[int(parts[0])] = d["value"]
        return f"item {parts[0]}: {json.dumps(old, ensure_ascii=False)} -> {json.dumps(d['value'], ensure_ascii=False)}"
    return f"not applied ({d['decision']} on a row or list cell needs a human edit)"


def apply(pool_path: Path, decisions_path: Path, data: Path, log: Path | None) -> int:
    pool = {i["id"]: i for i in json.loads(pool_path.read_text())}
    decisions = json.loads(decisions_path.read_text())
    by_task = defaultdict(list)
    for iid, d in decisions.items():
        if iid in pool:
            by_task[pool[iid]["task_id"]].append((pool[iid], d))
    lines = ["# Adjudication log", "", "Changes to gold after blind review (system names were hidden). Each applies to "
             "every system.", ""]
    changed = 0
    for tid, items in sorted(by_task.items()):
        f = data / "tasks" / f"{tid}.json"
        t = json.loads(f.read_text())
        for i, d in items:
            rec = t["fields"][i["pointer"]]
            msg = _set_field(rec, i["unit"], i["pointer"], d)
            if msg:
                lines.append(f"- `{tid}` `{i['unit']}`: {msg}")
                changed += 1
        f.write_text(json.dumps(t, indent=1, ensure_ascii=False) + "\n")
    lines.append(f"\n{changed} change(s) over {len(by_task)} document(s); {len(decisions)} decision(s) in all.")
    if log:
        log.write_text("\n".join(lines) + "\n")
    print(f"applied {changed} change(s); decisions {len(decisions)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="docfieldbench adjudicate", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("pool", type=Path)
    b.add_argument("--data", type=Path, required=True)
    b.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("apply")
    p.add_argument("pool", type=Path)
    p.add_argument("decisions", type=Path)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--log", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "build":
        return build(a.pool, a.data, a.out)
    return apply(a.pool, a.decisions, a.data, a.log)
