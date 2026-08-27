"""The stateless viewer: payload in, page out. No imports of the thing being described."""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from workflow_spec.report import PayloadError, render_page, validate_payload
from workflow_spec.serve import build_app

GOOD = {
    "name": "demo",
    "input_type": "str", "output_type": "int",
    "nodes": [{"id": "a"}, {"id": "b"}],
    "edges": [{"source": "__start__", "target": "a", "variable": "t"},
              {"source": "a", "target": "b"},
              {"source": "b", "target": "__end__"}],
    "layers": [
        {"name": "x", "bindings": {"a": {"impl": "one"}, "b": {"impl": "skip", "skipped": True}},
         "latency": {"a": 1.5}, "scores": {"Recall": 0.5}},
        {"name": "y", "bindings": {"a": {"impl": "two"}, "b": {"impl": "skip", "skipped": True}}},
    ],
    "noise_floor": {"Recall": 0.25},
}


def client(token="t0k"):
    return TestClient(build_app(token=token, require_token=bool(token)))


# ── the renderer is pure and domain-free ────────────────────────────────────────────────────

def test_report_module_imports_nothing_from_the_library():
    """The whole point of the split: the viewer can be hosted where the code is not."""
    import pathlib
    src = pathlib.Path(render_page.__code__.co_filename).read_text()
    assert "from workflow_spec.graph_spec" not in src
    assert "from workflow_spec.spec" not in src
    assert "import pydantic_graph" not in src


def test_render_is_pure_and_self_contained():
    html = render_page(GOOD)
    assert html == render_page(GOOD)                 # same in, same out
    assert "<!DOCTYPE html>" in html
    assert "cdn." not in html and "http://" not in html and "https://" not in html


def test_payload_is_embedded_as_json_not_interpolated_into_js():
    """A value containing a quote or `</script>` must not be able to break into code."""
    hostile = {**GOOD, "name": '</script><script>alert(1)</script>'}
    html = render_page(hostile)
    assert "<script>alert(1)</script>" not in html
    assert "<\\/script>" in html


def test_bad_payloads_say_why_rather_than_rendering_an_empty_page():
    with pytest.raises(PayloadError, match="nodes"):
        validate_payload({"edges": []})
    with pytest.raises(PayloadError, match="not a declared node id"):
        validate_payload({"nodes": [{"id": "a"}],
                          "edges": [{"source": "a", "target": "ghost"}]})
    with pytest.raises(PayloadError, match="two nodes share"):
        validate_payload({"nodes": [{"id": "a"}, {"id": "a"}], "edges": []})
    with pytest.raises(PayloadError, match="not a declared node"):
        validate_payload({**GOOD, "layers": [{"name": "z", "bindings": {"nope": {}}}]})


# ⚠️ NOT tested by string-matching the HTML. Both branches of every `if` live in the source, so
# `assert "not reported" in html` passes whether or not that branch ever executes — the exact
# failure `.claude/rules/checks.md` names ("a UI test that reads the template has not run the UI").
# The real assertions are in test_browser.py, which runs the page.


# ── the endpoint ────────────────────────────────────────────────────────────────────────────

def test_render_then_fetch_roundtrip():
    c = client()
    r = c.post("/render?token=t0k", json=GOOD)
    assert r.status_code == 200
    url = r.json()["url"]
    page = c.get(f"{url}?token=t0k")
    assert page.status_code == 200
    assert "<!DOCTYPE html>" in page.text


def test_content_addressed_so_the_same_payload_is_the_same_url():
    c = client()
    a = c.post("/render?token=t0k", json=GOOD).json()["sha"]
    b = c.post("/render?token=t0k", json=GOOD).json()["sha"]
    d = c.post("/render?token=t0k", json={**GOOD, "name": "other"}).json()["sha"]
    assert a == b and a != d


def test_stateless_route_stores_nothing():
    c = client()
    r = c.post("/render/html?token=t0k", json=GOOD)
    assert r.status_code == 200 and "<!DOCTYPE html>" in r.text
    # nothing new is fetchable by id, because nothing was written
    import hashlib
    sha = hashlib.sha256(json.dumps(GOOD, sort_keys=True, default=str).encode()).hexdigest()[:16]
    assert c.get(f"/r/{sha}xx?token=t0k").status_code in (400, 404)


def test_every_data_route_refuses_without_the_token():
    c = client()
    assert c.post("/render", json=GOOD).status_code == 401
    assert c.post("/render?token=wrong", json=GOOD).status_code == 401
    assert c.get("/r/abc").status_code == 401
    assert c.get("/").status_code == 401


def test_health_is_unauthenticated_and_leaks_nothing():
    c = client()
    r = c.get("/health")
    assert r.status_code == 200
    assert set(r.json()) == {"ok", "service"}


def test_a_bad_payload_is_422_not_500():
    c = client()
    assert c.post("/render?token=t0k", json={"nodes": []}).status_code == 422


def test_path_traversal_on_the_id_is_refused():
    c = client()
    assert c.get("/r/..%2F..%2Fetc%2Fpasswd?token=t0k").status_code in (400, 404)


def test_serve_refuses_a_public_bind_with_no_token(monkeypatch):
    from workflow_spec import serve as srv
    monkeypatch.delenv("WORKFLOW_SPEC_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="refusing to bind"):
        srv.serve(host="0.0.0.0", token="")
