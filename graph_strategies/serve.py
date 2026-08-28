"""A stateless viewer: POST a workflow report, GET back a page. Nothing else.

    POST /render?token=…     JSON payload      -> {"url": "/r/<sha>", "sha": "..."}
    GET  /r/<sha>?token=…                      -> the HTML page
    POST /render/html?token=…                  -> the HTML directly, no storage

⚠️ It imports NOTHING of yours. It cannot execute a strategy, load a module, or reach a graph. It
takes JSON and returns HTML, so the thing producing the report and the thing viewing it need
share nothing but the payload shape.

## "Stateless" and "a link I can open on my phone" are in tension

A page you can open later needs its data to live somewhere between the POST and the GET. The
smallest honest reconciliation is CONTENT ADDRESSING: the payload is stored under the sha256 of
itself, so the URL *is* the data's identity. There is no session, no config, no mutable state —
the same payload always yields the same URL, and re-POSTing is idempotent.

If you want it truly stateless, `POST /render/html` returns the page in the response body and
stores nothing. That is the CI/machine path. `/r/<sha>` is the phone path.

## The token

`GRAPH_STRATEGIES_TOKEN` — required for every route when bound to anything but localhost.

⚠️ It is not there because someone might guess a URL. There is no URL to guess: scanners sweep
the IPv4 space and connect to `ip:port` directly. Measured on the box this was written for — 842
failed SSH logins in 24 hours, on an address nobody was given.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import secrets
import tempfile
from typing import Any

from graph_strategies.report import PayloadError, render_page, validate_payload

__all__ = ["build_app", "serve"]

TOKEN_ENV = "GRAPH_STRATEGIES_TOKEN"


def _store_dir() -> pathlib.Path:
    d = pathlib.Path(os.getenv("GRAPH_STRATEGIES_STORE")
                     or (pathlib.Path(tempfile.gettempdir()) / "graph-strategies-reports"))
    d.mkdir(parents=True, exist_ok=True)
    return d


ISLAND_PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>__TITLE__</title>
<link rel="stylesheet" href="/static/graph-strategies.css">
<style>
 body{margin:0;background:#0b1020;color:#e8ecf8;
      font:15px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
 header{padding:.9rem 1rem;border-bottom:1px solid #2a3352}
 h1{margin:0;font-size:1rem} .sub{color:#93a0c0;font-size:.78rem;margin-top:.15rem}
 noscript{display:block;padding:1rem;color:#fbbf24}
</style></head><body>
<header><h1>__TITLE__</h1><div class="sub">__SUB__</div></header>
<noscript>This view is a React Flow island and needs JavaScript.
Append <code>&amp;plain=1</code> to the URL for the no-JavaScript version.</noscript>
<!-- The island. One div, one bundle, one data url. Nothing else on this page is React. -->
<div id="graph-strategies-root" data-report-url="__DATA_URL__"></div>
<script src="/static/graph-strategies.js" defer></script>
</body></html>
"""


def build_app(*, token: str | None = None, require_token: bool = True):
    from fastapi import Body, FastAPI, HTTPException, Query
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles

    token = token if token is not None else os.getenv(TOKEN_ENV, "")
    app = FastAPI(title="graph-strategies viewer", docs_url=None, redoc_url=None)
    store = _store_dir()

    # The built island. Committed into the package, because `pip install pydantic-graph-strategies` runs no
    # node step — an un-built island would be a 404 with no way to fix it at install time.
    static = pathlib.Path(__file__).parent / "static"
    if static.is_dir():
        # Unauthenticated: it is a public JS bundle with no report data in it. Gating it would
        # only mean the token travels in a second place.
        app.mount("/static", StaticFiles(directory=static), name="static")

    def check(supplied: str | None) -> None:
        if not require_token:
            return
        if not token:
            raise HTTPException(500, f"{TOKEN_ENV} is not set, so every request must be refused. "
                                     f"Set it, or run with require_token=False on localhost.")
        # Constant-time: a timing side-channel on a token check is free to avoid.
        if not supplied or not secrets.compare_digest(supplied, token):
            raise HTTPException(401, "bad or missing token")

    @app.get("/health")
    def health() -> dict[str, Any]:
        """Liveness only, and unauthenticated ON PURPOSE — it reports that the process is up and
        nothing about what it holds. `.claude/rules/checks.md`: liveness is not readiness, and a
        health endpoint that leaks state is not a health endpoint."""
        return {"ok": True, "service": "graph-strategies viewer"}

    @app.post("/render")
    def render(payload: Any = Body(...), token_q: str | None = Query(None, alias="token")):
        check(token_q)
        try:
            html = render_page(payload)
        except PayloadError as exc:
            raise HTTPException(422, str(exc)) from exc
        blob = json.dumps(payload, sort_keys=True, default=str).encode()
        sha = hashlib.sha256(blob).hexdigest()[:16]
        (store / f"{sha}.html").write_text(html, encoding="utf-8")
        # The island fetches this. Stored as the VALIDATED payload, not the raw body, so the
        # renderer and the island are guaranteed to be looking at the same document.
        (store / f"{sha}.json").write_text(
            json.dumps(validate_payload(payload), default=str), encoding="utf-8")
        return JSONResponse({"sha": sha, "url": f"/r/{sha}"})

    @app.post("/render/html", response_class=HTMLResponse)
    def render_html(payload: Any = Body(...), token_q: str | None = Query(None, alias="token")):
        """Truly stateless: the page comes back in the response and nothing is written."""
        check(token_q)
        try:
            return render_page(payload)
        except PayloadError as exc:
            raise HTTPException(422, str(exc)) from exc

    def _safe(sha: str) -> str:
        # Reject anything that is not a plain hex id before it reaches the filesystem.
        if not sha.isalnum() or len(sha) > 64:
            raise HTTPException(400, "bad id")
        return sha

    @app.get("/r/{sha}/data")
    def report_data(sha: str, token_q: str | None = Query(None, alias="token")):
        """What the island fetches. The same validated payload the plain renderer used."""
        check(token_q)
        p = store / f"{_safe(sha)}.json"
        if not p.exists():
            raise HTTPException(404, f"no report {sha!r}")
        return JSONResponse(json.loads(p.read_text(encoding="utf-8")))

    @app.get("/r/{sha}", response_class=HTMLResponse)
    def get_report(sha: str, token_q: str | None = Query(None, alias="token"),
                   plain: int = Query(0)):
        """The React Flow island by default; `?plain=1` for the dependency-free rendering.

        ⚠️ Both are kept, and the plain one is not a legacy path. It is one self-contained file
        with no bundle, which is what makes `POST /render/html` usable from a CI job or an email —
        and it is the only thing that still works if the island fails to load.
        """
        check(token_q)
        sha = _safe(sha)
        html_p, json_p = store / f"{sha}.html", store / f"{sha}.json"
        if not html_p.exists():
            raise HTTPException(404, f"no report {sha!r}")
        if plain or not (static / "graph-strategies.js").exists() or not json_p.exists():
            return html_p.read_text(encoding="utf-8")
        data = json.loads(json_p.read_text(encoding="utf-8"))
        title = str(data.get("name") or "workflow report")
        sub = (f"{data.get('input_type') or '?'} \u2192 {data.get('output_type') or '?'}"
               f"  \u00b7  {len(data.get('nodes') or [])} stages"
               f"  \u00b7  {len(data.get('layers') or [])} strategies")
        url = f"/r/{sha}/data" + (f"?token={token_q}" if token_q else "")
        return (ISLAND_PAGE.replace("__TITLE__", title.replace("<", ""))
                .replace("__SUB__", sub).replace("__DATA_URL__", url))

    @app.get("/")
    def index(token_q: str | None = Query(None, alias="token")):
        check(token_q)
        reports = sorted(store.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]
        return JSONResponse({
            "post": "/render  (JSON body) -> {url}",
            "stateless": "/render/html (JSON body) -> HTML, stores nothing",
            "reports": [f"/r/{p.stem}" for p in reports],
        })

    return app


def serve(*, host: str = "127.0.0.1", port: int = 8800, token: str | None = None) -> None:
    import uvicorn

    tok = token if token is not None else os.getenv(TOKEN_ENV, "")
    local = host in ("127.0.0.1", "localhost", "::1")
    if not local and not tok:
        raise SystemExit(
            f"refusing to bind {host} with no token. Set {TOKEN_ENV}, or bind 127.0.0.1.\n"
            f"  export {TOKEN_ENV}=$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')")
    uvicorn.run(build_app(token=tok, require_token=bool(tok) or not local),
                host=host, port=port, log_level="info")
