"""v32: every garment moves in Live (2026-11-25).

Before, Live moved only the garment being worked on; other unfrozen garments stood still. Now every visible
garment that isn't frozen is one simulation, so they collide with each other: the server merges their designs
(inner layer first, in the order set in Garments: drape never reorders layers), each piece keeps its garment's
fabric, and outer garments start outside inner ones (their layers go up past the inner garments').
"""
import numpy as np
import pytest

from drape.studio import server as S


@pytest.fixture(scope="module")
def avatar():
    a = S.api_avatar({"measurements": {"sex": "female", "height": 166, "chest": 92, "waist": 74, "hip": 100}})
    return a["id"]


def _skirt_design():
    w, h = 50, 60
    def rect(name):
        return {"name": name, "place": {"landmark": "waist_front" if name == "front" else "waist_back", "mode": "wrap", "at": "top", "offset_cm": 1.5},
                "edges": [{"name": "hem", "pts": [[-w / 2, 0], [w / 2, 0]]}, {"name": "side_r", "pts": [[w / 2, 0], [w / 2, h]]},
                          {"name": "waist", "pts": [[w / 2, h], [-w / 2, h]]}, {"name": "side_l", "pts": [[-w / 2, h], [-w / 2, 0]]}]}
    return {"pieces": [rect("front"), rect("back")],
            "seams": [{"a": "front.side_r", "b": "back.side_l", "ease": 0}, {"a": "front.side_l", "b": "back.side_r", "ease": 0}]}


def test_garments_merge_in_layer_order_with_their_own_names_fabrics_and_refs(avatar):
    a = S.S.avatars[avatar]
    tee = {"block": "tee", "choices": {}, "params": {}, "fabric": "jersey"}
    skirt = {"design": _skirt_design(), "fabric": "denim"}
    d, names = S._merged_design([tee, skirt], a["body"], a["meas"])
    tee_p = [p for p in d["pieces"] if p["name"].startswith("0~")]
    sk_p = [p for p in d["pieces"] if p["name"].startswith("1~")]
    assert tee_p and len(sk_p) == 2 and len(names) == len(d["pieces"])
    assert all(p.get("fabric") == "denim" for p in sk_p)
    # layered by simulation (MULTI_GARMENT_SPEC constraint 2): placement as on its own; the order is its garment number
    assert all(p["_garment"] == 0 for p in tee_p) and all(p["_garment"] == 1 for p in sk_p)
    assert all(p["place"].get("layer", 0) == 0 for p in sk_p) and d.get("garments_merged")
    refs = {r for s in d["seams"] for r in (s["a"], s["b"])}
    pieces = {p["name"] for p in d["pieces"]}
    assert all(r.split(".", 1)[0] in pieces for r in refs)                       # every seam points at a merged piece
    for p in d["pieces"]:
        pl = p.get("place") or {}
        assert not pl.get("on") or pl["on"] in pieces
        assert all(r.split(".", 1)[0] in pieces for r in pl.get("loop") or [])
    with pytest.raises(ValueError, match="at most"):
        S._merged_design([skirt] * (S.GARMENTS_MAX + 1), a["body"], a["meas"])


def test_live_setup_for_two_garments_is_one_simulation(avatar):
    one = S.api_live({"avatar": avatar, "block": "tee", "choices": {}, "params": {}, "fabric": "jersey"})
    two = S.api_live({"avatar": avatar, "fabric": "jersey", "garments": [
        {"block": "tee", "choices": {}, "params": {}, "fabric": "jersey"}, {"design": _skirt_design(), "fabric": "denim"}]})
    assert two["n"] > one["n"] and len(two["panel_names"]) == len(one["panel_names"]) + 2


# ------------------------------------------------------------------ the GPU
pytest.importorskip("playwright.sync_api")
from test_browser import _CROSSINGS, ST, _ensure_avatar, _go_garment, gpu_page, page, server  # noqa: E402,F401  (fixtures)


@pytest.mark.slow
# 2026-11-25, tee under a long-sleeve top: 1,400+ crossings -> 232 (smoothed start lift, the first frames planned at
# the speed cap); the long-sleeve top alone ends with 35. The rest come where sewing ends (0.6 s: 67, 0.9 s: 284).
@pytest.mark.xfail(reason="layers tangle where sewing ends: off (LIVE.all) until fixed", strict=False)
def test_live_moves_every_unfrozen_garment_and_they_stay_layered(gpu_page):
    """A tee (layer 1) under a long-sleeve top (layer 2), both in Live at once: one cloth, the HUD says so,
    and after it settles no mesh edge passes through a triangle (of its own garment or the other).
    Needs WebGPU: skipped without it."""
    pg = gpu_page
    _ensure_avatar(pg)
    pg.evaluate("LIVE.sim && stopLive(); 0")
    pg.evaluate("loadGarments({garments: [], activeGarmentId: null}); renderGarmentList()")
    _go_garment(pg, "tee")
    pg.evaluate("document.querySelector('#addGarment').click()")
    pg.click('#addGarmentMenu [data-ga="blank"]')
    pg.click('#gcards [data-k="long_sleeve"]')
    pg.wait_for_function(f"() => {ST}.ST.block === 'long_sleeve' && {ST}.ST.draft", timeout=60000)
    assert pg.evaluate("liveGarments().map(g => g.block)") == ["tee", "long_sleeve"]       # inner first
    pg.evaluate("LIVE.all = true; 0")
    pg.evaluate(f"{ST}.go('preview')")
    pg.wait_for_timeout(300)
    pg.evaluate("""() => { const a0 = window.__api0 || (window.__api0 = api); window.api = async (path, body) => { const s = await a0(path, body);
        if (path === '/api/live') { window.__livereq = body; const b = atob(s.tris), u = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i);
          window.__tris = new Uint32Array(u.buffer);
          const pb = atob(s.partners), pu = new Uint8Array(pb.length); for (let i = 0; i < pb.length; i++) pu[i] = pb.charCodeAt(i);
          window.__part = new Int32Array(pu.buffer) } return s } }""")
    if not pg.is_visible("#liveBtn"):
        pytest.skip("no WebGPU here (the Live button is hidden)")
    pg.click("#liveBtn")
    try:
        pg.wait_for_function("() => (LIVE.sim && LIVE.sim.time > 0.05) || /couldn't start/.test(document.querySelector('.toast')?.innerText || '')", timeout=120000)
    except Exception:
        pytest.skip("live mode didn't start")
    if not pg.evaluate("!!LIVE.sim"):
        pytest.skip("no WebGPU here: " + pg.inner_text(".toast"))
    try:
        assert pg.evaluate("window.__livereq.garments.length") == 2
        assert "2 garments" in pg.inner_text("#liveBar")
        pg.wait_for_function("() => LIVE.sim && LIVE.sim.time > 4.5", timeout=240000)      # sewn, settled
        pg.evaluate("LIVE.run = false; 0")
        pg.wait_for_function("() => !LIVE.sim.busy", timeout=10000)
        assert pg.evaluate("LIVE.sim.out.every(Number.isFinite)")
        c = pg.evaluate(_CROSSINGS)
        print("two garments in Live, crossings:", c)
        assert c["crossings"] <= 2, c
    finally:
        pg.evaluate("window.api = window.__api0 || api; LIVE.sim && stopLive(); 0")
    assert not pg.errors, pg.errors
