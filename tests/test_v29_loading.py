"""v29: loading indicators, a faster draft, and no GPU buttons where there's no GPU (2026-11-25).

- picking a garment shows that its controls and pattern are on their way (it took seconds with nothing shown)
- the draft is faster: meshing a piece flips only for outline edges the triangulation is missing (each one
  sorted every edge of the piece before, ~40% of a tee's draft), and the avatar's tapes are measured once
- ⚡ Live is hidden where the browser has no GPU the solver can use (an office PC); on the website, where
  Drape it needs the GPU too, Drape it says so instead of failing
"""
import numpy as np
import pytest


def test_meshing_flips_only_for_missing_outline_edges(monkeypatch):
    from drape import mesh2d
    t = np.linspace(0, 2 * np.pi, 90, endpoint=False)
    outline = np.c_[0.3 * np.cos(t) * (1 + 0.3 * np.sin(3 * t)), 0.2 * np.sin(t)]
    calls = []
    real = mesh2d._recover
    monkeypatch.setattr(mesh2d, "_recover", lambda T, V, a, b, **k: calls.append((a, b)) or real(T, V, a, b, **k))
    V, T = mesh2d.triangulate_piece(outline, 0.015)
    E = {tuple(sorted(e)) for tri in T.tolist() for e in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0]))}
    nb = len(outline)
    assert all(tuple(sorted((i, (i + 1) % nb))) in E for i in range(nb))     # the outline is all there
    assert np.array_equal(V[:nb], outline)
    assert len(calls) < nb / 2, f"flipped for {len(calls)} of {nb} segments"


def test_the_avatars_tapes_are_measured_once(monkeypatch):
    from drape.studio import server as S
    from drape.blocks import body_measures
    a = S.api_avatar({"measurements": {"sex": "female", "height": 166, "chest": 92, "waist": 74, "hip": 100}})
    av = S.S.avatars[a["id"]]
    first = body_measures(av["body"], av["meas"])
    first["chest"] = -1                                     # a caller changing its copy changes nothing
    monkeypatch.setattr(type(av["body"].tape), "chest", lambda self: pytest.fail("measured again"))
    again = body_measures(av["body"], av["meas"])
    assert again["chest"] > 0 and again["sex"] == "female"


# ------------------------------------------------------------------ the page
pytest.importorskip("playwright.sync_api")
from test_browser import ST, _ensure_avatar, page, server  # noqa: E402,F401  (fixtures)

pytestmark = pytest.mark.slow

SLOW_API = """(ms) => { const a0 = window.__api0 || (window.__api0 = api);
  window.api = async (path, body) => { if (/draft|starter/.test(path)) await new Promise(r => setTimeout(r, ms)); return a0(path, body) } }"""


def test_picking_a_garment_shows_its_controls_are_on_the_way(page):
    pg = page
    _ensure_avatar(pg)
    pg.evaluate("loadGarments({garments: [], activeGarmentId: null}); renderGarmentList()")
    pg.evaluate(SLOW_API, 2500)
    try:
        pg.evaluate(f"{ST}.go('garment')")
        pg.wait_for_timeout(300)
        pg.click('#gcards [data-k="tee"]')
        pg.wait_for_timeout(400)
        assert pg.is_visible("#choices .loading"), "no loading message where the controls go"
        assert "t-shirt" in pg.inner_text("#choices .loading").lower()
        assert pg.is_visible("#patload"), "no loading message over the pattern"
        assert pg.inner_text("#fitTitle") == "T-shirt"
        pg.wait_for_function(f"() => {ST}.ST.draft && {ST}.ST.block === 'tee'", timeout=60000)
        pg.wait_for_timeout(300)
        assert not pg.query_selector("#patload") and not pg.query_selector("#choices .loading")
        assert pg.query_selector_all("#choices .chip"), "the choices didn't come"
        assert pg.inner_text("#pathint") == ""
        # a change to a pattern already there: it stays (dimmed), a spinner by the title
        pg.click("#choices .chip:not(.on)")
        pg.wait_for_timeout(700)
        assert pg.evaluate("document.querySelector('.pane[data-pane=fit]').classList.contains('busy')")
        assert "updating" in pg.inner_text("#pathint") and pg.query_selector_all("#choices .chip")
        pg.wait_for_function("() => !document.querySelector('.pane[data-pane=fit]').classList.contains('busy')", timeout=60000)
        # a starter: the pattern box says it's being sized
        pg.evaluate(f"{ST}.go('garment')")
        pg.wait_for_timeout(300)
        key = pg.evaluate(f"{ST}.ST.init.starters[0].key")
        pg.evaluate(f"openStarter('{key}'); 0")      # not awaited: look while it's on its way
        pg.wait_for_timeout(400)
        # the card picked spins (the pattern box isn't on the picker), and says why in the toast
        assert pg.evaluate(f"document.querySelector('#scards .gcard[data-s=\"{key}\"]').classList.contains('loadingcard')")
        assert "sizing" in pg.inner_text(".toast").lower()
        pg.wait_for_function(f"() => {ST}.ST.scratch && {ST}.ST.design.from_starter === '{key}'", timeout=60000)
        pg.wait_for_timeout(300)
        assert not pg.query_selector("#patload")
    finally:
        pg.evaluate("window.api = window.__api0 || api; 0")
    assert not pg.errors, pg.errors


def test_no_gpu_hides_live_and_the_website_says_why_drape_it_cant_run(page, server):
    ctx = page.context.browser.new_context(viewport={"width": 1600, "height": 1000})
    try:
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        # an office PC: no WebGPU for this browser
        pg.add_init_script("Object.defineProperty(Navigator.prototype, 'gpu', {get: () => undefined})")
        pg.goto(server)
        pg.wait_for_function(f"() => window.__studio && {ST}.ST.gpu === false", timeout=60000)
        assert not pg.is_visible("#liveBtn")
        pg.evaluate(f"{ST}.go('preview')")
        pg.wait_for_timeout(300)
        assert not pg.is_disabled("#drapeBtn"), "the desktop drapes on the CPU: Drape it stays"
        assert not pg.is_visible("#nogpunote")
        # the website (it drapes on the GPU in the page)
        pg.evaluate(f"{ST}.ST.init.web = true; syncTryOn()")
        assert pg.is_disabled("#drapeBtn") and pg.is_visible("#nogpunote")
        assert "graphics card" in pg.inner_text("#nogpunote")
    finally:
        ctx.close()
    assert not errors, errors
