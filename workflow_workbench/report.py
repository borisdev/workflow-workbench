"""A stateless renderer: a workflow report payload in, a web page out.

    render_page(payload) -> str          a complete, self-contained HTML document

⚠️ THIS MODULE IMPORTS NOTHING FROM THE REST OF THE LIBRARY. It does not know what a `GraphSpec`
is, cannot import a strategy, and never executes anything. It takes JSON and returns HTML — so
anything that can produce the payload (a CI job, a Claude run, another language) can use the
viewer, and the viewer can be hosted somewhere that has no access to the code it is describing.

`payload_from_spec()` in `devserver` is one producer. It is not a privileged one.

## The payload

Everything is optional except `nodes` and `edges`, and every optional field degrades to "not
reported" rather than to a plausible zero — `.claude/rules/checks.md`: NOT CHECKED and 0 FOUND
must never render the same.

    {
      "name": "case_build",
      "input_type": "str", "output_type": "CaseGraph",
      "nodes":  [{"id": "propose", "inputs": [...], "outputs": [...]}],
      "edges":  [{"source": "__start__", "target": "propose", "variable": "plan_text"}],
      "layers": [                                  # one per strategy
        {"name": "llm_causal_map",
         "bindings": {"propose": {"impl": "propose_llm", "skipped": false,
                                  "file": "...", "line": 97, "code": "async def ..."}},
         "latency":  {"propose": 12.5},            # seconds, per stage    (optional)
         "scores":   {"ClaimRecall": 0.111},       # eval metrics           (optional)
         "findings": [], "ok": true}
      ],
      "noise_floor": {"ClaimRecall": 0.25}         # optional; the bar a delta must clear
    }
"""
from __future__ import annotations

import json
from typing import Any

from workflow_workbench.payload import WorkflowReport

__all__ = ["render_page", "validate_payload", "PayloadError"]


class PayloadError(ValueError):
    """The payload cannot be rendered, and says why. Never a blank page."""


def validate_payload(payload: Any) -> dict[str, Any]:
    """Parse the payload against the shared schema, or raise with the reason.

    ⚠️ ONE definition, in `workflow_workbench.payload`, used by the producer and by this viewer. The
    hand-rolled dict checks this replaced were a second description of the same shape, which is
    the drift `.claude/rules/spec-as-code.md` exists to prevent.

    ⚠️ A viewer that renders an empty page on bad input is the worst shape available: it looks
    like a workflow with nothing in it rather than like a mistake.
    """
    from pydantic import ValidationError

    if isinstance(payload, WorkflowReport):
        return payload.model_dump(mode="json")
    if not isinstance(payload, dict):
        raise PayloadError(f"payload must be a JSON object, got {type(payload).__name__}")
    try:
        return WorkflowReport.model_validate(payload).model_dump(mode="json")
    except ValidationError as exc:
        bits = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err["loc"]) or "payload"
            bits.append(f"{loc}: {err['msg']}")
        raise PayloadError("; ".join(bits)) from exc


_PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>__TITLE__</title>
<style>
 :root{--bg:#0b1020;--card:#151b30;--ink:#e8ecf8;--dim:#93a0c0;--line:#2a3352;
       --vary:#fbbf24;--ok:#34d399;--bad:#f87171;--skip:#5b6684;}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--ink);
      font:15px/1.55 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
 header{padding:.9rem 1rem;border-bottom:1px solid var(--line);position:sticky;top:0;
        background:var(--bg);z-index:20}
 h1{margin:0;font-size:1rem}
 .sub{color:var(--dim);font-size:.78rem;margin-top:.15rem}
 .wrap{padding:1rem;max-width:1150px;margin:0 auto}
 .card{background:var(--card);border:1px solid var(--line);border-radius:.7rem;
       padding:.9rem;margin-bottom:1rem}
 label{display:block;font-size:.7rem;text-transform:uppercase;letter-spacing:.09em;
       color:var(--dim);margin-bottom:.35rem}
 select{width:100%;padding:.6rem;border-radius:.5rem;background:#0f1528;color:var(--ink);
        border:1px solid var(--line);font-size:16px}
 .row{display:grid;grid-template-columns:1fr 1fr;gap:.7rem}
 @media(max-width:560px){.row{grid-template-columns:1fr}}
 #flow{height:62vh;min-height:340px;border-radius:.5rem;background:#0f1528;
       border:1px solid var(--line);position:relative;overflow:hidden;touch-action:none}
 .nd{position:absolute;border-radius:.55rem;padding:.5rem .6rem;font-size:.78rem;
     border:2px solid var(--line);background:#1b2340;min-width:120px;max-width:210px;
     box-shadow:0 2px 10px #0006}
 .nd.v{border-color:var(--vary);background:#2a2413}
 .nd.term{border-radius:1.2rem;background:#0b1020;color:var(--dim);min-width:0;
          font-size:.7rem;padding:.3rem .7rem}
 .nd b{display:block;font-size:.82rem;margin-bottom:.15rem}
 .nd .im{font-family:ui-monospace,Menlo,monospace;font-size:.7rem;color:var(--dim);
         white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .nd .im.a{color:#7dd3fc}.nd .im.b{color:#fca5a5}
 .nd .mt{font-size:.66rem;color:var(--dim);margin-top:.2rem}
 svg.wires{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
 table{border-collapse:collapse;width:100%;font-size:.82rem}
 th,td{padding:.42rem .5rem;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
 th{color:var(--dim);font-weight:600;font-size:.7rem;text-transform:uppercase}
 .scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
 /* ⚠️ A column that is off-screen with no affordance is invisible, not merely scrolled —
    the same class of defect as rendering onto a screen the reader is not on. On a narrow
    viewport the strategy name wraps instead of forcing the metrics off the right edge. */
 @media(max-width:620px){
   #perf td:first-child,#perf th:first-child{white-space:normal;word-break:break-word;
     max-width:9.5rem}
   #tbl td:first-child,#tbl th:first-child{position:sticky;left:0;background:var(--card)}
 }
 .hint{color:var(--dim);font-size:.7rem;margin-top:.3rem;display:none}
 .hint.on{display:block}
 .varies{color:var(--vary);font-weight:600}
 .skip{color:var(--skip);font-style:italic}
 .mono{font-family:ui-monospace,Menlo,monospace;font-size:.78rem}
 .bad{color:var(--bad)} .ok{color:var(--ok)}
 pre{background:#0f1528;border:1px solid var(--line);border-radius:.5rem;padding:.7rem;
     overflow-x:auto;font-size:.71rem;line-height:1.45;margin:.4rem 0 0}
 details{margin-top:.45rem} summary{cursor:pointer;color:var(--dim);font-size:.8rem}
 .pill{display:inline-block;padding:.08rem .45rem;border-radius:1rem;font-size:.66rem;
       border:1px solid var(--line);color:var(--dim);margin-left:.3rem}
 .nr{color:var(--skip);font-style:italic}
</style></head><body>
<header><h1 id="ttl">workflow report</h1><div class="sub" id="hdr"></div></header>
<div class="wrap">
  <div class="card"><div class="row">
    <div><label>Layer A</label><select id="a"></select></div>
    <div><label>Layer B</label><select id="b"></select></div>
  </div><div class="sub" id="varies" style="margin-top:.6rem"></div></div>
  <div class="card"><label>Graph — drag to pan, pinch/scroll to zoom</label><div id="flow"></div></div>
  <div class="card"><label>Bindings</label><div class="scroll" id="tbl"></div></div>
  <div class="card"><label>Latency &amp; scores</label><div class="scroll" id="perf"></div></div>
  <div class="card"><label>Code</label><div id="code"></div></div>
</div>
<script id="payload" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('payload').textContent);
const E = id => document.getElementById(id);
const esc = s => String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const NR = '<span class="nr">not reported</span>';
const layers = D.layers || [];
const L = n => layers.find(l => l.name === n) || {bindings:{}};

E('ttl').textContent = D.name || 'workflow report';
E('hdr').textContent = [
  (D.input_type||'?') + ' → ' + (D.output_type||'?'),
  (D.nodes.length) + ' stages',
  layers.length + ' strategies'].join('  ·  ');

layers.forEach((l,i)=>{
  E('a').add(new Option(l.name,l.name,false,i===0));
  E('b').add(new Option(l.name,l.name,false,i===Math.min(1,layers.length-1)));
});

/* ── layout: longest-path layering over the declared edges ─────────────────────────────── */
function layout(){
  const idx = {}; D.nodes.forEach((n,i)=>idx[n.id]=i);
  const depth = {__start__:0};
  const order = ['__start__', ...D.nodes.map(n=>n.id), '__end__'];
  for(let pass=0; pass<order.length; pass++){
    D.edges.forEach(e=>{
      if(depth[e.source]!=null){
        depth[e.target] = Math.max(depth[e.target]??0, depth[e.source]+1);
      }
    });
  }
  order.forEach(id=>{ if(depth[id]==null) depth[id]=0; });
  const byD = {};
  order.forEach(id=>{ (byD[depth[id]] ||= []).push(id); });
  const pos = {};
  Object.keys(byD).map(Number).sort((x,y)=>x-y).forEach(d=>{
    byD[d].forEach((id,i)=>{ pos[id] = {x: 60 + i*250, y: 40 + d*120}; });
  });
  return pos;
}
const POS = layout();
let view = {x:0,y:0,k:1};

function draw(){
  const A = L(E('a').value), B = L(E('b').value);
  const varies = D.nodes.filter(n=>(A.bindings[n.id]||{}).impl !== (B.bindings[n.id]||{}).impl)
                        .map(n=>n.id);

  E('varies').innerHTML = varies.length
    ? varies.map(v=>'<span class="mono varies">'+esc(v)+'</span>').join(' · ')
      + ' — ' + varies.length + ' of ' + D.nodes.length + ' stages differ'
    : 'nothing differs — same bindings on every stage (a replicate)';

  const f = E('flow');
  f.innerHTML = '<svg class="wires"><defs><marker id="ah" markerWidth="9" markerHeight="9" '
    + 'refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#3d4a70"/></marker>'
    + '</defs></svg><div id="pan" style="position:absolute;inset:0"></div>';
  const pan = f.querySelector('#pan'), svg = f.querySelector('svg');
  pan.style.transformOrigin='0 0';

  const mk = (id, html, cls) => {
    const d = document.createElement('div');
    d.className = 'nd ' + cls; d.dataset.id = id; d.innerHTML = html;
    d.style.left = POS[id].x + 'px'; d.style.top = POS[id].y + 'px';
    pan.appendChild(d); return d;
  };
  mk('__start__','START','term'); mk('__end__','END','term');
  D.nodes.forEach(n=>{
    const a=A.bindings[n.id]||{}, b=B.bindings[n.id]||{};
    const one = x => x.unbound ? '<span class="bad">UNBOUND</span>'
                  : x.skipped ? '<span class="skip">— skipped</span>' : esc(x.impl);
    let h = '<b>'+esc(n.id)+'</b>';
    h += varies.includes(n.id)
      ? '<div class="im a">'+one(a)+'</div><div class="im b">'+one(b)+'</div>'
      : '<div class="im">'+one(a)+'</div>';
    const lat = (A.latency||{})[n.id];
    if(lat!=null) h += '<div class="mt">'+(+lat).toFixed(1)+'s</div>';
    mk(n.id, h, varies.includes(n.id)?'v':'');
  });

  const wires = () => {
    const r = f.getBoundingClientRect();
    svg.innerHTML = svg.querySelector('defs').outerHTML + D.edges.map(e=>{
      const s = pan.querySelector('[data-id="'+CSS.escape(e.source)+'"]');
      const t = pan.querySelector('[data-id="'+CSS.escape(e.target)+'"]');
      if(!s||!t) return '';
      const sb=s.getBoundingClientRect(), tb=t.getBoundingClientRect();
      const x1=sb.left-r.left+sb.width/2, y1=sb.top-r.top+sb.height;
      const x2=tb.left-r.left+tb.width/2, y2=tb.top-r.top;
      const mid=(y1+y2)/2;
      const lbl = e.variable
        ? '<text x="'+((x1+x2)/2+6)+'" y="'+(mid-2)+'" fill="#93a0c0" font-size="10" '
          + 'font-family="ui-monospace,Menlo,monospace">'+esc(e.variable)+'</text>' : '';
      return '<path d="M'+x1+','+y1+' C'+x1+','+mid+' '+x2+','+mid+' '+x2+','+y2+'" '
           + 'stroke="#3d4a70" stroke-width="1.6" fill="none" marker-end="url(#ah)"/>'+lbl;
    }).join('');
  };
  const apply = () => {
    pan.style.transform='translate('+view.x+'px,'+view.y+'px) scale('+view.k+')';
    wires();
  };
  apply();

  let drag=null;
  f.onpointerdown = ev => { drag={x:ev.clientX-view.x, y:ev.clientY-view.y}; f.setPointerCapture(ev.pointerId); };
  f.onpointermove = ev => { if(drag){ view.x=ev.clientX-drag.x; view.y=ev.clientY-drag.y; apply(); } };
  f.onpointerup   = () => drag=null;
  f.onwheel = ev => { ev.preventDefault();
    view.k = Math.min(2.5, Math.max(0.3, view.k * (ev.deltaY<0?1.1:0.9))); apply(); };

  /* bindings table — every layer at once */
  let t='<table><tr><th>stage</th>'+layers.map(l=>'<th>'+esc(l.name)+'</th>').join('')+'</tr>';
  D.nodes.forEach(n=>{
    t+='<tr><td class="mono">'+esc(n.id)+'</td>';
    layers.forEach(l=>{
      const x=l.bindings[n.id]||{};
      const cls = x.unbound?'bad':(x.skipped?'skip':'mono');
      const txt = x.unbound?'UNBOUND':(x.skipped?'—':(x.impl==null?'?':x.impl));
      const hi = ((l.name===A.name)||(l.name===B.name)) && varies.includes(n.id) ? ' varies':'';
      t+='<td class="'+cls+hi+'">'+esc(txt)+'</td>';
    });
    t+='</tr>';
  });
  E('tbl').innerHTML = t + '</table><div class="sub">— = explicitly skipped by that strategy. '
    + 'UNBOUND = nobody wired it, which check_bindings refuses.</div>'
    + '<div class="hint" id="tblhint">← swipe the table sideways for the other strategies</div>';
  requestAnimationFrame(()=>{
    const box=E('tbl'), tb=box.querySelector('table');
    if(tb && tb.scrollWidth > box.clientWidth+4) E('tblhint').classList.add('on');
  });

  /* latency + scores, with "not reported" rather than a zero */
  const metrics = [...new Set(layers.flatMap(l=>Object.keys(l.scores||{})))];
  let p='<table><tr><th>strategy</th><th>total latency</th>'
      + metrics.map(m=>'<th>'+esc(m)+'</th>').join('')+'</tr>';
  layers.forEach(l=>{
    const lat=l.latency?Object.values(l.latency).reduce((a,b)=>a+(+b||0),0):null;
    p+='<tr><td class="mono">'+esc(l.name)+'</td><td>'+(lat==null?NR:lat.toFixed(1)+'s')+'</td>'
     + metrics.map(m=>{
         const v=(l.scores||{})[m];
         if(v==null) return '<td>'+NR+'</td>';
         const fl=(D.noise_floor||{})[m];
         const noisy = fl!=null && Math.abs(v)<Math.abs(fl);
         return '<td>'+(+v).toFixed(3)+(noisy?' <span class="pill">inside noise</span>':'')+'</td>';
       }).join('')+'</tr>';
  });
  p+='</table>';
  if(D.noise_floor) p+='<div class="sub">noise floor: '+esc(JSON.stringify(D.noise_floor))
    + ' — a delta smaller than this is not a result.</div>';
  else p+='<div class="sub">no noise floor reported — no replicate ran, so no delta here is '
    + 'known to mean anything.</div>';
  E('perf').innerHTML=p;

  /* code for the varying stages */
  let c='';
  (varies.length?varies:D.nodes.map(n=>n.id)).forEach(id=>{
    [A,B].forEach(l=>{
      const x=(l.bindings||{})[id]; if(!x||!x.code) return;
      c+='<details><summary>'+esc(l.name)+' · <span class="mono">'+esc(id)+'</span> → <span '
       + 'class="mono">'+esc(x.impl)+'</span><span class="pill">'
       + esc(String(x.file||'').split('/').pop())+':'+(x.line||0)+'</span></summary><pre>'
       + esc(x.code)+'</pre></details>';
    });
  });
  E('code').innerHTML = c || '<span class="sub">no source in the payload</span>';
}
E('a').onchange=draw; E('b').onchange=draw;
draw();
window.addEventListener('resize', draw);
</script></body></html>
"""


def render_page(payload: Any) -> str:
    """Payload in, a complete self-contained HTML document out. Pure — no I/O, no globals.

    The data is embedded as JSON in a `<script type="application/json">` tag rather than
    interpolated into JavaScript, so a value containing a quote or `</script>` cannot break out
    into code.
    """
    data = validate_payload(payload)
    blob = json.dumps(data, default=str).replace("</", "<\\/")
    title = str(data.get("name") or "workflow report")
    return _PAGE.replace("__DATA__", blob).replace(
        "__TITLE__", title.replace("<", "").replace(">", ""))
