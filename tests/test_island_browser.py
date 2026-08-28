"""The React Flow island, RUN in Chromium against a live server.

⛔ Not a template test. Every assertion queries the DOM React Flow actually produced — if the
bundle fails to load, or ELK never resolves, or a hook throws, these go red. `checks.md`: if the
assertion would still hold with the browser turned off, it is not testing the UI.
"""
from __future__ import annotations

import json
import socket
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
pytest.importorskip("fastapi")
import uvicorn
from playwright.sync_api import sync_playwright

from workflow_workbench.serve import build_app

BOOT_TIMEOUT_MS = int(__import__("os").getenv("WS_BOOT_TIMEOUT_MS", "15000"))
"""Lowered in the falsification run, where every test is EXPECTED to time out."""

REPORT = {
    "name": "case_build",
    "input_type": "str", "output_type": "CaseGraph",
    "nodes": [{"id": "propose"}, {"id": "cite"}, {"id": "enrich"}],
    "edges": [{"source": "__start__", "target": "propose", "variable": "plan_text"},
              {"source": "propose", "target": "cite", "variable": "draft_graph"},
              {"source": "cite", "target": "enrich", "variable": "cited_graph"},
              {"source": "enrich", "target": "__end__", "variable": "case_graph"}],
    "layers": [
        {"name": "llm_only",
         "bindings": {"propose": {"impl": "propose_llm", "file": "b.py", "line": 10,
                                  "code": "async def propose_llm(ctx): ..."},
                      "cite": {"impl": "skip", "skipped": True},
                      "enrich": {"impl": "skip", "skipped": True}},
         "latency": {"propose": 12.5, "cite": 0.0, "enrich": 0.0},
         "scores": {"Recall": 0.11}},
        {"name": "evidence_corrected",
         "bindings": {"propose": {"impl": "propose_llm", "file": "b.py", "line": 10,
                                  "code": "async def propose_llm(ctx): ..."},
                      "cite": {"impl": "cite_medline_kg", "file": "b.py", "line": 20,
                               "code": "async def cite_medline_kg(ctx): ..."},
                      "enrich": {"impl": "enrich_from_literature", "file": "b.py", "line": 30,
                                 "code": "async def enrich_from_literature(ctx): ..."}}},
    ],
    "noise_floor": {"Recall": 0.25},
}


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    import os
    os.environ["WORKFLOW_WORKBENCH_STORE"] = str(tmp_path_factory.mktemp("reports"))
    port = _free_port()
    app = build_app(token="", require_token=False)
    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(cfg)
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    t.join(timeout=5)


@pytest.fixture(scope="module")
def report_url(server):
    import urllib.request
    req = urllib.request.Request(f"{server}/render", data=json.dumps(REPORT).encode(),
                                 headers={"Content-Type": "application/json"})
    res = json.loads(urllib.request.urlopen(req, timeout=15).read())
    return f"{server}{res['url']}"


class Island:
    def __init__(self, url):
        self.url = url

    def __enter__(self):
        # ⛔ EVERY FAILURE PATH MUST STILL STOP PLAYWRIGHT.
        #
        # Without the try/except, a timeout inside __enter__ means __exit__ never runs, the driver
        # is never stopped, and every LATER test dies with "Please use the Async API instead."
        # Measured: one real failure (a corrupt bundle) produced 14 failures, 13 of them lying
        # about their own cause. `.claude/rules/checks.md` — a swallowed/leaked failure in a
        # fan-out manufactures agreement, and a unanimous result is the most convincing shape a
        # broken check can take.
        self._pw = sync_playwright().start()
        try:
            self.browser = self._pw.chromium.launch()
            self.page = self.browser.new_page(viewport={"width": 390, "height": 844})
            self.errors: list[str] = []
            self.page.on("pageerror", lambda e: self.errors.append(str(e)))
            self.page.goto(self.url, wait_until="networkidle")
            # React Flow mounts, then ELK resolves asynchronously and positions land.
            self.page.wait_for_selector(".react-flow__node", timeout=BOOT_TIMEOUT_MS)
            self.page.wait_for_timeout(500)
        except BaseException:
            try:
                self.browser.close()
            except BaseException:
                pass
            self._pw.stop()
            raise
        return self

    def __exit__(self, *a):
        self.browser.close()
        self._pw.stop()


def test_the_island_boots_with_no_javascript_errors(report_url):
    with Island(report_url) as i:
        assert i.errors == [], i.errors


def test_react_flow_actually_rendered_the_nodes(report_url):
    """`.react-flow__node` exists only if the bundle loaded, React mounted and ELK resolved."""
    with Island(report_url) as i:
        ids = i.page.eval_on_selector_all(".react-flow__node",
                                          "els => els.map(e => e.dataset.id)")
        assert set(ids) == {"__start__", "__end__", "propose", "cite", "enrich"}


def test_elk_gave_every_node_a_real_position(report_url):
    """A layout failure leaves every node stacked at 0,0 — which still renders."""
    with Island(report_url) as i:
        boxes = i.page.eval_on_selector_all(
            ".react-flow__node", "els => els.map(e => e.getBoundingClientRect().top)")
        assert len(set(round(b) for b in boxes)) > 1, "all nodes at one y — ELK did not lay out"


def test_react_flow_drew_the_edges(report_url):
    with Island(report_url) as i:
        paths = i.page.eval_on_selector_all(".react-flow__edge-path", "els => els.length")
        assert paths == len(REPORT["edges"])


def test_edge_labels_name_the_variable_that_crosses(report_url):
    with Island(report_url) as i:
        text = i.page.inner_text(".react-flow__edges, .react-flow")
        assert "draft_graph" in text and "plan_text" in text


def test_the_varying_stages_are_highlighted_and_the_shared_one_is_not(report_url):
    with Island(report_url) as i:
        assert i.page.locator('.react-flow__node[data-id="cite"] .ws-varies').count() == 1
        assert i.page.locator('.react-flow__node[data-id="propose"] .ws-varies').count() == 0
        assert i.page.locator('.react-flow__node[data-id="propose"] .ws-shared').count() == 1


def test_switching_a_layer_changes_the_highlighting_without_moving_a_box(report_url):
    """⚠️ The layout must NOT re-run on a layer switch: topology is fixed by the design, so a
    box that jumps is pure noise in the one comparison this page exists to make."""
    with Island(report_url) as i:
        before = i.page.eval_on_selector_all(
            ".react-flow__node", "els => els.map(e => e.getAttribute('transform') || e.style.transform)")
        i.page.select_option(".ws-bar select >> nth=1", "llm_only")   # replicate
        i.page.wait_for_timeout(400)
        assert i.page.locator(".ws-varies").count() == 0
        assert "nothing differs" in i.page.inner_text('[data-testid="varies"]')
        after = i.page.eval_on_selector_all(
            ".react-flow__node", "els => els.map(e => e.getAttribute('transform') || e.style.transform)")
        assert before == after, "boxes moved on a layer switch"


def test_a_skipped_stage_reads_as_skipped(report_url):
    with Island(report_url) as i:
        assert "skipped" in i.page.inner_text('.react-flow__node[data-id="cite"]').lower()


def test_latency_shows_on_the_node_and_absent_latency_shows_nothing(report_url):
    with Island(report_url) as i:
        assert "12.5s" in i.page.inner_text('.react-flow__node[data-id="propose"]')
        i.page.select_option(".ws-bar select >> nth=0", "evidence_corrected")
        i.page.wait_for_timeout(400)
        # evidence_corrected reports no latency at all — the node must print NOTHING, not 0.0s
        assert "0.0s" not in i.page.inner_text('.react-flow__node[data-id="propose"]')


def test_a_metric_nobody_measured_says_not_reported_never_zero(report_url):
    with Island(report_url) as i:
        perf = i.page.inner_text(".ws-panel")
        assert "not reported" in perf
        assert "0.000" not in perf


def test_a_score_inside_the_noise_floor_is_flagged(report_url):
    """Recall 0.11 against a floor of 0.25 — the number is real and means nothing."""
    with Island(report_url) as i:
        assert "inside noise" in i.page.inner_text(".ws-panel")


def test_tapping_a_stage_reveals_its_code(report_url):
    with Island(report_url) as i:
        assert "tap a stage" in i.page.inner_text(".ws-panel").lower()
        i.page.click('.react-flow__node[data-id="cite"]')
        i.page.wait_for_timeout(300)
        panel = i.page.inner_text(".ws-panel")
        assert "cite_medline_kg" in panel
        assert "b.py:20" in panel


def test_it_fits_a_phone_and_the_canvas_is_on_screen(report_url):
    with Island(report_url) as i:
        box = i.page.locator(".ws-canvas").bounding_box()
        assert box["width"] <= 390 and box["height"] > 200
        assert i.page.locator(".react-flow__controls").is_visible()


def test_plain_fallback_still_works_and_needs_no_bundle(report_url):
    """`?plain=1` is not legacy: it is the only rendering that survives the island failing.

    ⚠️ It waits for `.nd`, NOT `.react-flow__node` — the plain page has no React Flow in it at
    all, which is the entire point of keeping it.
    """
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 390, "height": 844})
        errs: list[str] = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(report_url + "?plain=1", wait_until="networkidle")
        pg.wait_for_selector(".nd", timeout=10000)
        assert errs == [], errs
        drawn = pg.eval_on_selector_all(".nd", "els => els.map(e => e.dataset.id)")
        assert {"propose", "cite", "enrich"} <= set(drawn)
        # No bundle was involved.
        assert pg.locator(".react-flow").count() == 0
        b.close()


def test_the_minimap_does_not_cover_the_graph_on_a_phone(report_url):
    """⛔ Measured: the MiniMap floated over the canvas and hid an entire stage. A control that
    obscures the content it navigates is worse than not having it."""
    with Island(report_url) as i:
        assert i.page.locator(".ws-mini").count() == 0 or not i.page.locator(
            ".ws-mini").is_visible(), "minimap is visible at 390px and overlaps the graph"


def test_no_panel_column_is_stranded_off_screen_on_a_phone(report_url):
    """The same overflow already fixed in the plain renderer — the island panel did not inherit
    it, so it had to be fixed and tested again here."""
    with Island(report_url) as i:
        # ⚠️ Find the metrics table BY ITS HEADING, not by nth-of-type — a section added above it
        # would silently move the index and the assertion would start grading a different table.
        perf_overflow = i.page.evaluate("""() => {
            const s = [...document.querySelectorAll('.ws-panel section')]
              .find(x => x.querySelector('h3')?.textContent?.toLowerCase().includes('latency'));
            if (!s) return null;
            const box = s.querySelector('.ws-scroll'), t = box.querySelector('table');
            return t.scrollWidth - box.clientWidth;
        }""")
        assert perf_overflow is not None, "no latency section found — the selector is wrong"
        assert perf_overflow <= 4, f"latency table overflows by {perf_overflow}px on a phone"


def test_the_bindings_table_is_not_wrapped_into_one_letter_per_line(report_url):
    """⛔ The fix for the metrics overflow leaked onto the BINDINGS table and broke "propose" into
    a vertical column of single letters. A first column narrower than its own text is not a
    layout, and the overflow test could not see it — it only measured the other table."""
    with Island(report_url) as i:
        w = i.page.evaluate("""() => {
            const s = [...document.querySelectorAll('.ws-panel section')]
              .find(x => x.querySelector('h3')?.textContent?.toLowerCase().includes('binding'));
            const cell = s.querySelector('tbody td');
            return { w: cell.getBoundingClientRect().width, text: cell.textContent };
        }""")
        # "propose" at ~11px monospace needs ~55px. One letter per line would be under 20.
        assert w["w"] > 45, f"bindings first column is {w['w']}px for {w['text']!r} — wrapped"
