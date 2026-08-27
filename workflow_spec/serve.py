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

`WORKFLOW_SPEC_TOKEN` — required for every route when bound to anything but localhost.

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

from workflow_spec.report import PayloadError, render_page

__all__ = ["build_app", "serve"]

TOKEN_ENV = "WORKFLOW_SPEC_TOKEN"


def _store_dir() -> pathlib.Path:
    d = pathlib.Path(os.getenv("WORKFLOW_SPEC_STORE")
                     or (pathlib.Path(tempfile.gettempdir()) / "workflow-spec-reports"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_app(*, token: str | None = None, require_token: bool = True):
    from fastapi import Body, FastAPI, HTTPException, Query
    from fastapi.responses import HTMLResponse, JSONResponse

    token = token if token is not None else os.getenv(TOKEN_ENV, "")
    app = FastAPI(title="workflow-spec viewer", docs_url=None, redoc_url=None)
    store = _store_dir()

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
        return {"ok": True, "service": "workflow-spec viewer"}

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
        return JSONResponse({"sha": sha, "url": f"/r/{sha}"})

    @app.post("/render/html", response_class=HTMLResponse)
    def render_html(payload: Any = Body(...), token_q: str | None = Query(None, alias="token")):
        """Truly stateless: the page comes back in the response and nothing is written."""
        check(token_q)
        try:
            return render_page(payload)
        except PayloadError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/r/{sha}", response_class=HTMLResponse)
    def get_report(sha: str, token_q: str | None = Query(None, alias="token")):
        check(token_q)
        # Reject anything that is not a plain hex id before it reaches the filesystem.
        if not sha.isalnum() or len(sha) > 64:
            raise HTTPException(400, "bad id")
        p = store / f"{sha}.html"
        if not p.exists():
            raise HTTPException(404, f"no report {sha!r}")
        return p.read_text(encoding="utf-8")

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
