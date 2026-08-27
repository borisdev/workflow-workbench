"""A dev tool: browse a GraphSpec's strategies in a browser. Phone-friendly.

    from workflow_spec.devserver import serve
    serve({"case_build": (spec, [strategy_a, strategy_b, ...])}, port=8800)

## Why a JSON endpoint and not just an HTML page

`/api/spec/{name}` is the durable half. The HTML below renders it with mermaid because that is
twenty lines and works on a phone today — but the payload is deliberately React-Flow-shaped
(`nodes` with ids, `edges` with source/target, `layers` keyed by strategy), so swapping the
renderer never means re-deriving the data. Same split as the website's causal-graph island: one
div, one JSON url, and the projection is a pure function of the IR.

⚠️ DEV TOOL. Binds to localhost by default and has no auth. It reads a declaration and reports it;
it never builds, runs or deploys anything.
"""
from __future__ import annotations

import inspect
from typing import Any

from workflow_spec.diagram import impl_name
from workflow_spec.graph_spec import GraphSpec
from workflow_spec.spec import StrategySpec, is_sentinel

__all__ = ["spec_payload", "build_app", "serve"]


def _endpoint_id(ep: Any) -> str:
    from workflow_spec.spec import _End, _Start
    if isinstance(ep, _Start):
        return "__start__"
    if isinstance(ep, _End):
        return "__end__"
    return ep.name


def _source_of(impl: Any) -> dict[str, Any]:
    """Where an implementation lives, and its body. `.claude/rules/checks.md`: show the thing, do
    not describe it — a strategy table that names `cite_medline_kg` without showing what it calls
    is asking to be believed."""
    try:
        src = inspect.getsource(impl)
    except (OSError, TypeError):
        src = ""
    try:
        file = inspect.getsourcefile(impl) or ""
        line = inspect.getsourcelines(impl)[1]
    except (OSError, TypeError):
        file, line = "", 0
    return {"file": file, "line": line, "code": src}


def spec_payload(spec: GraphSpec, strategies: list[StrategySpec]) -> dict[str, Any]:
    """One GraphSpec plus every strategy over it, as React-Flow-shaped JSON.

    `layers` is the toggleable part: one entry per strategy, each naming what it binds to every
    node — including the stages it explicitly declines to run.
    """
    nodes = [
        {
            "id": n.name,
            "kind": "step",
            "inputs": [{"name": v.name, "type": getattr(v.type, "__name__", str(v.type))}
                       for v in n.inputs],
            "outputs": [{"name": v.name, "type": getattr(v.type, "__name__", str(v.type))}
                        for v in n.outputs],
        }
        for n in spec.nodes
    ]
    edges = [
        {
            "id": f"{_endpoint_id(e.source)}->{_endpoint_id(e.target)}",
            "source": _endpoint_id(e.source),
            "target": _endpoint_id(e.target),
            "variable": e.variable.name if e.variable else None,
            "type": getattr(e.variable.type, "__name__", None) if e.variable else None,
        }
        for e in spec.edges
    ]

    layers = []
    for s in strategies:
        bindings = {}
        for n in spec.nodes:
            if n not in s.bindings:
                bindings[n.name] = {"impl": None, "skipped": False, "unbound": True}
                continue
            impl = s[n]
            name = impl_name(impl)
            bindings[n.name] = {
                "impl": name,
                # An explicit decline, which is a different fact from "nobody wired it".
                "skipped": name == "skip",
                "unbound": False,
                **_source_of(impl),
            }
        findings = spec.check(s)
        layers.append({
            "name": s.name,
            "bindings": bindings,
            "findings": findings,
            "ok": not [f for f in findings if not f.startswith("NOT CHECKED")],
        })

    return {
        "name": spec.name or type(spec).__name__,
        "input_type": getattr(spec.input_type, "__name__", str(spec.input_type)),
        "output_type": getattr(spec.output_type, "__name__", str(spec.output_type)),
        "nodes": nodes,
        "edges": edges,
        "layers": layers,
        "design_findings": spec.check(),
        "mermaid": spec.diagram(),
    }


PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>workflow-spec — strategies</title>
<style>
 :root{--bg:#0b1020;--card:#151b30;--ink:#e8ecf8;--dim:#93a0c0;--line:#2a3352;
       --vary:#fbbf24;--ok:#34d399;--skip:#5b6684;}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--ink);
      font:15px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
 header{padding:1rem;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--bg);z-index:9}
 h1{margin:0;font-size:1.05rem;letter-spacing:.01em}
 .sub{color:var(--dim);font-size:.8rem;margin-top:.2rem}
 .wrap{padding:1rem;max-width:1100px;margin:0 auto}
 .card{background:var(--card);border:1px solid var(--line);border-radius:.7rem;
       padding:.9rem;margin-bottom:1rem;overflow-x:auto}
 label{display:block;font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;
       color:var(--dim);margin-bottom:.35rem}
 select{width:100%;padding:.6rem;border-radius:.5rem;background:#0f1528;color:var(--ink);
        border:1px solid var(--line);font-size:1rem}
 .row{display:grid;grid-template-columns:1fr 1fr;gap:.7rem}
 @media(max-width:560px){.row{grid-template-columns:1fr}}
 table{border-collapse:collapse;width:100%;font-size:.83rem}
 th,td{padding:.45rem .5rem;text-align:left;border-bottom:1px solid var(--line);
       white-space:nowrap}
 th{color:var(--dim);font-weight:600;font-size:.72rem;text-transform:uppercase}
 .varies{color:var(--vary);font-weight:600}
 .skip{color:var(--skip);font-style:italic}
 .mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.8rem}
 pre{background:#0f1528;border:1px solid var(--line);border-radius:.5rem;padding:.7rem;
     overflow-x:auto;font-size:.72rem;line-height:1.45;margin:.4rem 0 0}
 details{margin-top:.5rem}
 summary{cursor:pointer;color:var(--dim);font-size:.8rem}
 .pill{display:inline-block;padding:.1rem .45rem;border-radius:1rem;font-size:.68rem;
       border:1px solid var(--line);color:var(--dim);margin-left:.3rem}
 .mermaid{background:#fff;border-radius:.5rem;padding:.5rem}
 .warn{color:#fbbf24;font-size:.78rem}
</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
</head><body>
<header>
  <h1>workflow-spec — strategy layers</h1>
  <div class="sub" id="hdr">loading…</div>
</header>
<div class="wrap">
  <div class="card">
    <div class="row">
      <div><label>Layer A</label><select id="a"></select></div>
      <div><label>Layer B</label><select id="b"></select></div>
    </div>
  </div>
  <div class="card"><label>What varies</label><div id="varies"></div></div>
  <div class="card"><label>Diagram</label><div class="mermaid" id="mmd">flowchart TD</div></div>
  <div class="card"><label>Bindings</label><div id="tbl"></div></div>
  <div class="card"><label>Code</label><div id="code"></div></div>
</div>
<script>
mermaid.initialize({startOnLoad:false,theme:'default'});
const SPEC_URL = window.location.pathname.replace(/\\/$/,'') + '/data';
let D=null;

function esc(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}

function layer(n){return D.layers.find(l=>l.name===n);}

function render(){
  const A=layer(document.getElementById('a').value), B=layer(document.getElementById('b').value);
  const varies=D.nodes.filter(n=>A.bindings[n.id].impl!==B.bindings[n.id].impl).map(n=>n.id);

  document.getElementById('varies').innerHTML = varies.length
    ? varies.map(v=>`<span class="mono varies">${esc(v)}</span>`).join(' · ')
      + `<div class="sub">${varies.length} of ${D.nodes.length} stages differ</div>`
    : '<span class="sub">nothing — same bindings on every stage (this is a replicate)</span>';

  // diagram
  const L=['flowchart TD','  __start__([START])'];
  D.nodes.forEach(n=>{
    const a=A.bindings[n.id], b=B.bindings[n.id];
    const lbl = varies.includes(n.id)
      ? `${n.id}<br/>${esc(A.name)}: ${esc(a.impl||'—')}<br/>${esc(B.name)}: ${esc(b.impl||'—')}`
      : `${n.id}<br/>${esc(a.impl||'—')}`;
    L.push(`  ${n.id}["${lbl}"]:::${varies.includes(n.id)?'v':'s'}`);
  });
  L.push('  __end__([END])');
  D.edges.forEach(e=>{
    L.push(`  ${e.source} ${e.variable?`-- ${e.variable} -->`:'-->'} ${e.target}`);
  });
  L.push('  classDef v fill:#fde68a,stroke:#b45309,stroke-width:3px,color:#111;');
  L.push('  classDef s fill:#f1f5f9,stroke:#94a3b8,color:#111;');
  const el=document.getElementById('mmd');
  el.removeAttribute('data-processed'); el.innerHTML=L.join('\\n');
  mermaid.run({nodes:[el]});

  // table — every layer at once, so the toggle is a comparison not a slideshow
  let t='<table><tr><th>stage</th>'+D.layers.map(l=>`<th>${esc(l.name)}</th>`).join('')+'</tr>';
  D.nodes.forEach(n=>{
    t+=`<tr><td class="mono">${esc(n.id)}</td>`;
    D.layers.forEach(l=>{
      const b=l.bindings[n.id];
      const cls = b.unbound?'warn':(b.skipped?'skip':'mono');
      const txt = b.unbound?'UNBOUND':(b.skipped?'—':b.impl);
      const hi = (l.name===A.name||l.name===B.name)&&varies.includes(n.id)?' varies':'';
      t+=`<td class="${cls}${hi}">${esc(txt)}</td>`;
    });
    t+='</tr>';
  });
  t+='</table><div class="sub">— = the stage is explicitly skipped by that strategy. '
   + 'UNBOUND would mean nobody wired it, which check_bindings refuses.</div>';
  document.getElementById('tbl').innerHTML=t;

  // code for the varying stages
  let c='';
  (varies.length?varies:D.nodes.map(n=>n.id)).forEach(id=>{
    [A,B].forEach(l=>{
      const b=l.bindings[id];
      if(!b.code) return;
      c+=`<details><summary>${esc(l.name)} · <span class="mono">${esc(id)}</span> → `
       + `<span class="mono">${esc(b.impl)}</span>`
       + `<span class="pill">${esc((b.file||'').split('/').slice(-1)[0])}:${b.line}</span>`
       + `</summary><pre>${esc(b.code)}</pre></details>`;
    });
  });
  document.getElementById('code').innerHTML=c||'<span class="sub">no source available</span>';
}

fetch(SPEC_URL).then(r=>r.json()).then(d=>{
  D=d;
  document.getElementById('hdr').textContent =
    `${d.name}  ·  ${d.input_type} → ${d.output_type}  ·  ${d.nodes.length} stages  ·  `
    + `${d.layers.length} strategies`;
  const a=document.getElementById('a'), b=document.getElementById('b');
  d.layers.forEach((l,i)=>{
    a.add(new Option(l.name,l.name,false,i===0));
    b.add(new Option(l.name,l.name,false,i===Math.min(1,d.layers.length-1)));
  });
  a.onchange=render; b.onchange=render;
  render();
});
</script>
</body></html>
"""


def build_app(registry: dict[str, tuple[GraphSpec, list[StrategySpec]]]):
    """A FastAPI app serving every registered spec. `fastapi` is an optional extra."""
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, JSONResponse

    app = FastAPI(title="workflow-spec devserver", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        links = "".join(
            f'<li style="margin:.5rem 0"><a style="color:#7dd3fc" href="/spec/{k}">{k}</a></li>'
            for k in registry)
        return (f"<body style='background:#0b1020;color:#e8ecf8;font-family:system-ui;padding:2rem'>"
                f"<h1 style='font-size:1.1rem'>workflow-spec devserver</h1><ul>{links}</ul></body>")

    @app.get("/spec/{name}", response_class=HTMLResponse)
    def page(name: str) -> str:
        if name not in registry:
            raise HTTPException(404, f"no spec {name!r}; have {sorted(registry)}")
        return PAGE

    @app.get("/spec/{name}/data")
    def data(name: str) -> JSONResponse:
        if name not in registry:
            raise HTTPException(404, f"no spec {name!r}; have {sorted(registry)}")
        spec, strategies = registry[name]
        return JSONResponse(spec_payload(spec, strategies))

    return app


def serve(registry: dict[str, tuple[GraphSpec, list[StrategySpec]]],
          *, host: str = "127.0.0.1", port: int = 8800) -> None:
    """Run the dev server. Localhost by default — there is no auth on this."""
    import uvicorn
    uvicorn.run(build_app(registry), host=host, port=port, log_level="info")
