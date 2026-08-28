"""The page, RUN. Not the template, read.

⛔ Every assertion here is about what a reader SEES after the JavaScript has executed. A string
test over the HTML cannot make any of them: both branches of every conditional are present in the
source, so `"not reported" in html` is true whether or not that branch runs.

`.claude/rules/checks.md` — "if the assertion would still hold with the browser turned off, it is
not testing the UI." Each test below fails with the browser turned off, because there is nothing
to query.
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

from workflow_workbench.report import render_page

BASE = {
    "name": "demo",
    "input_type": "str", "output_type": "int",
    "nodes": [{"id": "propose"}, {"id": "cite"}],
    "edges": [{"source": "__start__", "target": "propose", "variable": "plan_text"},
              {"source": "propose", "target": "cite", "variable": "draft"},
              {"source": "cite", "target": "__end__"}],
    "layers": [
        {"name": "arm_a",
         "bindings": {"propose": {"impl": "llm"}, "cite": {"impl": "skip", "skipped": True}},
         "latency": {"propose": 12.5}, "scores": {"Recall": 0.5}},
        {"name": "arm_b",
         "bindings": {"propose": {"impl": "llm"}, "cite": {"impl": "medline_kg"}}},
    ],
}


class Page:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch()
        self.page = self.browser.new_page(viewport={"width": 390, "height": 844})  # a phone
        self.errors: list[str] = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("console", lambda m: self.errors.append(m.text)
                     if m.type == "error" else None)
        self.page.set_content(render_page(self.payload))
        self.page.wait_for_timeout(350)
        return self

    def __exit__(self, *a):
        self.browser.close()
        self._pw.stop()

    def text(self, sel="body"):
        return self.page.inner_text(sel)


def test_the_page_has_no_javascript_errors_at_all():
    """One unbalanced brace makes every script on the page inert while the HTML still looks
    perfect to curl. This is the test that catches it."""
    with Page(BASE) as p:
        assert p.errors == [], p.errors


def test_nodes_are_actually_drawn_not_merely_present_in_the_source():
    with Page(BASE) as p:
        drawn = p.page.eval_on_selector_all(".nd", "els => els.map(e => e.dataset.id)")
        assert set(drawn) == {"__start__", "__end__", "propose", "cite"}
        assert p.page.locator('.nd[data-id="propose"]').is_visible()


def test_edges_are_drawn_as_real_svg_paths():
    with Page(BASE) as p:
        paths = p.page.eval_on_selector_all("svg.wires path", "els => els.length")
        assert paths >= len(BASE["edges"]), f"only {paths} wires drawn"


def test_the_varying_stage_is_highlighted_and_the_shared_one_is_not():
    with Page(BASE) as p:
        assert p.page.locator('.nd[data-id="cite"].v').count() == 1, "varying stage not marked"
        assert p.page.locator('.nd[data-id="propose"].v').count() == 0, "shared stage marked"


def test_switching_the_layer_dropdown_changes_what_is_highlighted():
    """A replicate — the same layer on both sides — must highlight NOTHING."""
    with Page(BASE) as p:
        p.page.select_option("#b", "arm_a")
        p.page.wait_for_timeout(250)
        assert p.page.locator(".nd.v").count() == 0
        assert "nothing differs" in p.text("#varies")


def test_a_skipped_stage_reads_as_skipped_not_as_missing():
    with Page(BASE) as p:
        assert "skipped" in p.page.inner_text('.nd[data-id="cite"]').lower()


def test_an_unbound_stage_shouts():
    payload = {**BASE, "layers": [
        {"name": "broken", "bindings": {"propose": {"unbound": True}}},
        BASE["layers"][1]]}
    with Page(payload) as p:
        assert "UNBOUND" in p.text("#tbl")


def test_a_metric_nobody_measured_renders_as_not_reported_never_as_zero():
    """⛔ THE ONE THAT NEEDED A BROWSER. `arm_b` has no scores; the cell must say so rather than
    show 0.000. Both strings exist in the source, so only running it can tell them apart."""
    with Page(BASE) as p:
        perf = p.text("#perf")
        assert "not reported" in perf
        assert "0.000" not in perf


def test_a_missing_noise_floor_is_stated_rather_than_omitted():
    with Page(BASE) as p:
        assert "no noise floor reported" in p.text("#perf")


def test_a_present_noise_floor_flags_a_delta_inside_it():
    payload = {**BASE, "noise_floor": {"Recall": 0.9}}     # 0.5 is inside a floor of 0.9
    with Page(payload) as p:
        perf = p.text("#perf")
        assert "inside noise" in perf
        assert "no noise floor reported" not in perf


def test_latency_appears_on_the_node():
    with Page(BASE) as p:
        assert "12.5s" in p.page.inner_text('.nd[data-id="propose"]')


def test_it_is_usable_on_a_phone_viewport():
    """390px wide. The graph must be on screen and the controls stacked, not clipped."""
    with Page(BASE) as p:
        box = p.page.locator("#flow").bounding_box()
        assert box["width"] <= 390, box
        assert box["height"] > 200
        assert p.page.locator("#a").is_visible() and p.page.locator("#b").is_visible()


def test_a_hostile_name_cannot_execute():
    payload = {**BASE, "name": "</script><script>window.__pwned=1</script>"}
    with Page(payload) as p:
        assert p.page.evaluate("window.__pwned === undefined")
        assert p.errors == []


def test_no_column_is_stranded_off_screen_on_a_phone():
    """⛔ A column you cannot see and are not told to scroll for is invisible, not scrolled.

    Measured before the fix: the latency table was 439px inside a 327px container, so the only
    column carrying numbers was off the right edge with no affordance. `checks.md` — it rendered
    perfectly, invisibly.
    """
    payload = {**BASE, "layers": [
        {**BASE["layers"][0], "name": "evidence_corrected (verify ON, enrich ON)"},
        BASE["layers"][1]]}
    with Page(payload) as p:
        w = p.page.eval_on_selector("#perf table", "e => e.scrollWidth")
        c = p.page.eval_on_selector("#perf", "e => e.clientWidth")
        assert w <= c + 4, f"perf table {w}px overflows its {c}px container"


def test_a_wide_bindings_table_says_it_is_scrollable():
    """The bindings table legitimately grows with the strategy count, so it scrolls — but it
    must SAY so rather than silently truncate."""
    many = [{"name": f"strategy_number_{i}",
             "bindings": {"propose": {"impl": f"impl_{i}"}, "cite": {"impl": "skip",
                                                                     "skipped": True}}}
            for i in range(8)]
    with Page({**BASE, "layers": many}) as p:
        assert p.page.locator("#tblhint.on").count() == 1, "wide table gave no scroll affordance"
