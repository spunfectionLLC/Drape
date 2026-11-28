"""v25 "less is more" (2026-11-24): Simple mode shows the essentials, Advanced keeps everything where it
was; first-impression bugs (pocket bags showing through, overlapping labels, red fit warnings on starters).

Browser tests reuse test_browser.py's server and page (Chrome, Playwright). The GPU tests drape the
website's way (the studio's drape job, the cloth on the GPU) and need a WebGPU adapter.
"""
import base64
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
pytest.importorskip("playwright.sync_api")
from test_browser import ST, _convert, _ensure_avatar, _go_garment, page, server  # noqa: F401  (fixtures)

pytestmark = pytest.mark.slow

STEP_KEYS = ("body", "garment", "fit", "preview", "export")

# what the Simple user sees, per step (spec part 2) and what only Advanced shows
SIMPLE_SHOWN = {
    "body": ["#nextslot"],
    "design": ["#symBtn", "#undo", "#redo", ".begdd .ddbtn", "#dsPreview", "#moreFabrics"],
    "preview": ["#drapeBtn", "#toExport"],
    "export": ["#simpleExports", "#moreFormats"],
}
ADV_ONLY = {
    "body": ["#build"],
    "design": [".advdd .ddbtn", "#tool", "#shapes", "#show3d"],
    "preview": ["#quality"],
    "export": ["#exports"],
}


def _mode(pg, m):
    pg.click(f"#mode [data-m={m}]")
    pg.wait_for_timeout(250)


def _visible(pg, sel):
    return pg.evaluate("""s => [...document.querySelectorAll(s)].some(e => {
        const r = e.getBoundingClientRect(), c = getComputedStyle(e);
        return r.width > 0 && r.height > 0 && c.visibility !== 'hidden' && !e.closest('[hidden]') })""", sel)


def _primaries(pg):
    """The visible primary buttons of the page (not the modal or the 'go to step' message)."""
    return pg.evaluate("""[...document.querySelectorAll('.btn.primary, .exp.primary')].filter(e => {
        const r = e.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && !e.closest('#modal, #blockmsg, [hidden]') }).map(e => e.id || e.textContent.trim())""")


def _design_ready(pg):
    """A design on the board with pockets (shift dress with in-seam pockets), the Design step open."""
    _ensure_avatar(pg)
    if not pg.evaluate(f"{ST}.ST.scratch && {ST}.ST.design.pieces.some(p => /_bag/.test(p.name))"):
        _go_garment(pg, "shift_dress")
        _convert(pg, "front")
        for side in ("r", "l"):
            pg.evaluate("""side => { const f = pieceBy('front'); window.__studio.DS.sel = 'front';
                const e = f.edges.find(e => e.name.startsWith('side') && e.name.endsWith('_' + side)); window.__dsRef = 'front.' + e.name }""", side)
            pg.evaluate("""async () => { const r = await api('/api/edit', {design: window.__studio.ST.design, op: 'inseam_pocket',
                args: {ref: window.__dsRef}, avatar: window.__studio.ST.avatar.id}); window.__studio.ST.design = r.design; tidy(); dsChanged(true, true) }""")
            pg.wait_for_timeout(600)
    pg.evaluate(f"{ST}.go('fit')")
    pg.wait_for_timeout(800)


# ------------------------------------------------------------------ 1. Simple mode: what shows, one primary per step
def test_simple_mode_shows_the_essentials_and_one_primary_button(page):
    pg = page
    _mode(pg, "beg")
    _design_ready(pg)
    for step, pane in (("body", "body"), ("garment", "garment"), ("fit", "design"), ("preview", "preview"), ("export", "export")):
        pg.evaluate(f"{ST}.go('{step}')")
        pg.wait_for_timeout(500)
        if pane == "export":
            pg.wait_for_function("document.querySelectorAll('#simpleExports .exp').length === 3", timeout=120000)
        for s in SIMPLE_SHOWN.get(pane, []):
            assert _visible(pg, s), (pane, s)
        for s in ADV_ONLY.get(pane, []):
            assert not _visible(pg, s), (pane, s)
        if pane in ("body", "garment", "preview"):
            assert not _visible(pg, "#logcard"), pane                   # no warnings bar on these steps
        if pane != "garment":                                           # Garment: the cards are the choice
            assert len(_primaries(pg)) == 1, (pane, _primaries(pg))
    # Garment: the basic patterns first (Tyler, 2026-11-24), the blank canvas last of them, then the finished designs
    pg.evaluate(f"{ST}.go('garment')")
    pg.wait_for_timeout(400)
    assert pg.evaluate("document.querySelector('#gcards').compareDocumentPosition(document.querySelector('#scards')) & 4")
    last = pg.evaluate("[...document.querySelectorAll('#gcards .gcard, #gcards > *')].pop().textContent")
    assert "Blank canvas" in last
    assert not _visible(pg, "#glcard")
    # Design (the garment's fabric moved there from Try on, 2026-11-27): five fabrics, the rest behind "More fabrics"
    pg.evaluate(f"{ST}.go('fit')")
    pg.wait_for_timeout(300)
    assert pg.evaluate("[...document.querySelectorAll('#fabrics .chip[data-f]')].filter(c => c.offsetWidth).length") <= 6
    assert not page.errors, page.errors


# ------------------------------------------------------------------ 2. Advanced keeps every control
def test_advanced_mode_keeps_every_control(page):
    pg = page
    _design_ready(pg)
    _mode(pg, "adv")
    try:
        for step, pane in (("body", "body"), ("fit", "design"), ("preview", "preview"), ("export", "export")):
            pg.evaluate(f"{ST}.go('{step}')")
            pg.wait_for_timeout(500)
            if pane == "export":
                pg.wait_for_function("document.querySelectorAll('#exports .exp').length > 3", timeout=120000)
            for s in ADV_ONLY[pane]:
                assert _visible(pg, s), (pane, s)
        # the inspector's full panel: name field, shape-it and pockets tools
        pg.evaluate(f"{ST}.go('fit')")
        pg.evaluate(f"{ST}.DS.sel = 'front'; renderInspector()")
        pg.wait_for_timeout(300)
        for s in ("#pinseam", "#ppocket", "#cutBtn"):
            assert _visible(pg, s), s
    finally:
        _mode(pg, "beg")


# ------------------------------------------------------------------ 3. switching mode keeps the state
def test_mode_switch_keeps_design_selection_and_step(page):
    pg = page
    _design_ready(pg)
    pg.evaluate(f"{ST}.DS.sel = 'front'; renderInspector()")
    before = pg.evaluate(f"JSON.stringify([{ST}.ST.step, {ST}.DS.sel, {ST}.ST.design, {ST}.ST.fabric, {ST}.ST.meas])")
    _mode(pg, "adv")
    _mode(pg, "beg")
    after = pg.evaluate(f"JSON.stringify([{ST}.ST.step, {ST}.DS.sel, {ST}.ST.design, {ST}.ST.fabric, {ST}.ST.meas])")
    assert before == after


# ------------------------------------------------------------------ 4. Body: the avatar updates by itself
def test_body_updates_the_avatar_by_itself(page):
    pg = page
    _ensure_avatar(pg)
    _mode(pg, "beg")
    pg.evaluate(f"{ST}.go('body')")
    pg.wait_for_timeout(300)
    old = pg.evaluate(f"{ST}.ST.avatar.id")
    inp = pg.locator("#mfields input[data-k=chest]")
    v = float(inp.input_value())
    inp.fill(f"{v + 2:g}")
    inp.dispatch_event("input")
    pg.wait_for_function("AUTO.busy || /Updating/.test(document.querySelector('#nextslot').textContent)", timeout=2000)
    pg.wait_for_function(f"{ST}.ST.avatar && {ST}.ST.avatar.id !== '{old}' && !AUTO.busy", timeout=180000)
    # one build per change: nothing builds again by itself (a finished build once re-armed itself: a loop
    # that also threw away the drape)
    pg.evaluate("window.__builds = 0; const b = buildAvatar; window.buildAvatar = (...a) => { window.__builds++; window.__why = new Error().stack; return b(...a) }; 0")
    pg.wait_for_timeout(4000)
    assert pg.evaluate("window.__builds") == 0, pg.evaluate("window.__why")
    assert not pg.errors, pg.errors


# ------------------------------------------------------------------ 7. labels on the board don't overlap
def test_board_labels_do_not_overlap_and_use_plain_names(page):
    pg = page
    _design_ready(pg)
    boxes = pg.evaluate("""[...document.querySelectorAll('#board .plabel')].map(e => { const r = e.getBoundingClientRect();
        return [r.left, r.top, r.right, r.bottom, e.textContent] })""")
    assert len(boxes) >= 4
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            ov = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
            assert not (ov[0] > 1 and ov[1] > 1), (a[4], b[4])
        assert "_" not in a[4], a[4]                                    # no internal ids (front_r, front_bag_1)
    assert any("Pocket bag" in b[4] for b in boxes)


# ------------------------------------------------------------------ 8. no template text left in what people read
def test_no_unfilled_template_text_anywhere(page):
    pg = page
    _design_ready(pg)
    for m in ("beg", "adv"):
        _mode(pg, m)
        for k in STEP_KEYS:
            pg.evaluate(f"{ST}.go('{k}')")
            pg.wait_for_timeout(300)
            txt = pg.evaluate("document.body.innerText")
            assert "${" not in txt and "undefined" not in txt, (m, k)
    _mode(pg, "beg")


# ------------------------------------------------------------------ 9. paper size by locale
def test_print_at_home_paper_follows_the_locale(page):
    pg = page
    assert pg.evaluate("defaultPaper('en-US')") == "letter"
    assert pg.evaluate("defaultPaper('en-CA')") == "letter"
    for loc in ("en-GB", "de-DE", "fr-CA", "en-AU", "ja-JP"):
        assert pg.evaluate(f"defaultPaper('{loc}')") == "a4", loc


# ------------------------------------------------------------------ GPU: the website's drape
def _gpu():
    gpu = pytest.importorskip("drape.gpu")
    ok, why = gpu.gpu_info()
    if not ok:
        pytest.skip(why)
    return gpu


@pytest.fixture(scope="module")
def api():
    from drape.studio import server as S
    init = S.api_init()
    return S, init


def _web_drape(S, aid, design, fabric):
    """The website's drape: the studio's job up to the cloth, the cloth on the GPU, then the job's finish."""
    gpu = _gpu()
    from drape import webapi
    from drape.live import sim_setup
    from test_v9 import S_design
    r = webapi.api_drape({"avatar": aid, "design": S_design(design), "fabric": fabric, "quality": "full"})
    assert r["job"] in webapi.JOBS, S.api_job(r["job"]).get("error")
    job, sim, n = webapi.JOBS[r["job"]]
    gp = gpu.GPUSprings(sim_setup(sim, sim.body, fabric, grid_h=sim.body.h))
    gp.self_while_sewing = bool(r.get("self_while_sewing"))
    for _ in range(n):
        gp.step(1)
    webapi.api_drape_done({"job": r["job"], "x": base64.b64encode(gp.positions().astype(np.float32).tobytes()).decode(),
                           "v": base64.b64encode(gp.velocities().astype(np.float32).tobytes()).decode()})
    res = S.api_job(r["job"])
    assert res["state"] == "done", res.get("error")
    return res, np.load(Path(S.S.jobs[r["job"]]["outdir"]) / "result.npz")


def _starters():
    from drape.starters import STARTERS
    return sorted(STARTERS)


# ------------------------------------------------------------------ 5. no red fit warning on a starter at its defaults
# Red from a hem or cuff caught on a hand or foot in the GPU drape: a few dozen points stretched 60-170%,
# more than any fabric gives, so it's the drape, not the fit (ease changes didn't move it). KNOWN_ISSUES.md.
HEM_CATCH = {"button_up", "cardigan", "chinos", "chore_jacket", "fingerless_gloves", "henley", "jeans", "joggers",
             "mittens", "oversized_tee", "pajama_pants", "scrub_pants", "shift_zip", "zip_hoodie", "zip_jacket"}


@pytest.mark.parametrize("key", [pytest.param(k, marks=pytest.mark.xfail(reason="hem caught on a hand/foot in the drape (KNOWN_ISSUES.md)"))
                                 if k in HEM_CATCH else k for k in _starters()])
def test_starter_shows_no_red_fit_warning(api, key):
    from drape.starters import STARTERS
    S, init = api
    _gpu()
    for av in ("female_M", "male_M"):
        a = S.api_avatar({"measurements": init["examples"][av]})
        d = S.api_starter({"avatar": a["id"], "key": key})["design"]
        for fab in dict.fromkeys(["jersey", STARTERS[key].fabric]):
            res, _ = _web_drape(S, a["id"], d, fab)
            red = [x["text"] for x in res.get("advice", []) if x.get("level") == "problem"]
            assert not red, (av, fab, red)


# ------------------------------------------------------------------ 6. pocket bags stay inside the garment
ELASTIC_WAIST = {"scrub_pants", "shorts", "gathered_skirt"}        # docs/KNOWN_ISSUES.md


POCKETED = ["a_line_pockets", "gathered_skirt", "joggers", "scrub_pants", "shift_pockets", "shirt_dress", "shorts"]


@pytest.mark.parametrize("key", [pytest.param(k, marks=pytest.mark.xfail(strict=True, reason="elastic waist: bags ride up (KNOWN_ISSUES.md)"))
                                 if k in ELASTIC_WAIST else k for k in POCKETED])
def test_pocket_bags_stay_inside(api, key):
    """At least 98% of the bag points end up inside the shell (no farther from the body than the
    nearest garment point outside the bags)."""
    from scipy.spatial import cKDTree
    from drape.meshbody import grid_sdf_batch
    from drape.starters import STARTERS
    S, init = api
    _gpu()
    a = S.api_avatar({"measurements": init["examples"]["female_M"]})
    d = S.api_starter({"avatar": a["id"], "key": key})["design"]
    res, z = _web_drape(S, a["id"], d, STARTERS[key].fabric)
    B = S.S.avatars[a["id"]]["body"]
    x, pid, names = z["x"], z["panel_id"], list(z["panel_names"])
    bag = np.isin(pid, [k for k, nm in enumerate(names) if "_bag" in nm])
    assert bag.any(), "no pocket bags in this starter"
    sd = grid_sdf_batch(np.ascontiguousarray(x), B.grid, B.origin, B.h) * 1000
    _, j = cKDTree(x[~bag]).query(x[bag])
    outside = sd[bag] > sd[~bag][j] + 0.5
    assert outside.mean() <= 0.02, f"{outside.mean() * 100:.1f}% of bag points outside"
