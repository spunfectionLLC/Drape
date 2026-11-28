"""v28: the second bug hunt (2026-11-25), and the items the first one left open.

- the website sends a Content-Security-Policy (tests/test_v23_web.py checks it and drapes under it)
- the 3D view frees a mesh's GPU buffers when it replaces it (the floor was rebuilt every frame of a move test)
- Drape it is busy per garment: another garment can drape meanwhile; the progress and "The drape failed" show only
  on the garment that's draping; coming back to it mid-drape redraws its cloth (the server sends the triangles once)
- undo keeps the newest steps
- numbers typed into forms (My fabric, the editor's closures and pockets, exports) get a message about the number
  instead of saving a fabric with no mass, a million buttons, a negative seam allowance or a nesting job for hours
- the fabric file: an entry this copy can't read is skipped (not the whole file); a damaged file is kept aside
- the server keeps the latest avatars and drapes, not every one of a long session (the website's memory)
"""
import base64
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))


# ------------------------------------------------------------------ server side (no browser)
M = {"sex": "female", "height": 166, "chest": 92, "waist": 74, "hip": 100}


@pytest.fixture(scope="module")
def S():
    from drape.studio import server
    return server


@pytest.fixture(scope="module")
def avatar_id(S):
    return S.api_avatar({"measurements": M})["id"]


@pytest.mark.parametrize("req, says", [
    ({"square_g": 0, "droop_cm": 3}, "square 0 g: it needs to be more than 0 g"),
    ({"square_g": -2, "droop_cm": 3}, "more than 0 g"),
    ({"square_g": "two", "droop_cm": 3}, "isn't a number"),
    ({"square_g": 2, "droop_cm": 30, "overhang_cm": 10}, "Tip hangs down 30 cm: it needs to be at most 10 cm"),
    ({"square_g": 2, "droop_cm": 3, "overhang_cm": -10}, "Sticking out -10 cm"),
    ({"square_g": 2, "droop_cm": 3, "load_g": 500}, "Marks now: fill it in"),
])
def test_my_fabric_numbers_that_would_save_an_unusable_fabric_say_which_number(S, req, says, monkeypatch, tmp_path):
    from drape import calibrate
    monkeypatch.setattr(calibrate, "USER_FILE", tmp_path / "fabrics.json")
    with pytest.raises(ValueError, match=None) as e:
        S.api_fabric(req)
    assert says in str(e.value), str(e.value)
    assert not (tmp_path / "fabrics.json").exists()


def test_the_fabric_file_keeps_what_it_can_and_never_loses_a_damaged_file(monkeypatch, tmp_path):
    from drape import calibrate
    from drape.cloth import Fabric
    f = tmp_path / "fabrics.json"
    monkeypatch.setattr(calibrate, "USER_FILE", f)
    good = {"name": "Linen <b>", "density": 0.2, "stretch_compliance": 1e-7, "bend_compliance": 1e5, "thickness": 0.004}
    f.write_text(json.dumps({"my_linen": good, "my_future": {**good, "name": "Future", "glow": 3},
                             "my_zero": {**good, "density": 0.0}, "my_junk": "?"}), encoding="utf-8")
    got = calibrate.load_user_fabrics()
    assert set(got) == {"my_linen", "my_future"} and got["my_linen"].name == "Linen b"   # a newer field: still read
    f.write_text("{not json", encoding="utf-8")
    calibrate.save_user_fabric("my_new", Fabric("New"))
    assert (tmp_path / "fabrics.json.bad").read_text(encoding="utf-8") == "{not json"
    assert set(json.loads(f.read_text(encoding="utf-8"))) == {"my_new"}
    assert not (tmp_path / "fabrics.json.tmp").exists()


def test_editor_numbers_get_a_message_not_a_million_buttons(S, avatar_id):
    d = S.api_to_scratch({"avatar": avatar_id, "block": "tee"})["design"]
    s = d["seams"][0]
    edit = lambda op, **a: S.api_edit({"design": d, "op": op, "args": a})    # noqa: E731
    for op, a, says in [
        ("closure", {"a": "nope.x", "b": "nope.y", "kind": "buttons"}, "isn't a seam in this design any more"),
        ("closure", {"a": s["a"], "b": s["b"], "kind": "buttons", "count": 1000000}, "at most 200"),
        ("closure", {"a": s["a"], "b": s["b"], "kind": "buttons", "size_mm": -5}, "Size -5 mm"),
        ("partial_closure", {"ref": s["a"], "length_cm": -3}, "Length -3 cm"),
        ("inseam_pocket", {"ref": s["a"], "opening_cm": 500}, "Opening 500 cm: it needs to be at most 100 cm"),
        ("inseam_pocket", {"ref": s["a"], "depth_cm": -12}, "Depth -12 cm"),
    ]:
        with pytest.raises(ValueError) as e:
            edit(op, **a)
        assert says in str(e.value), (op, a, str(e.value))
    assert edit("closure", a=s["a"], b=s["b"], kind="buttons", count=6)["design"]["seams"][0]["closure"]["count"] == 6


def test_export_numbers_get_a_message(S, avatar_id):
    base = {"avatar": avatar_id, "block": "tee", "choices": {}, "params": {}}
    for extra, says in [
        ({"kind": "laser_nest", "garments": 5000}, f"Garments 5000: it needs to be at most {S.NEST_MAX}"),
        ({"kind": "laser_nest", "garments": -2}, "at least 1"),
        ({"kind": "laser_nest", "bed_w": 0}, "Bed width 0 cm"),
        ({"kind": "pdf_letter", "seam_allowance_cm": -3}, "Seam allowance -3 cm"),
        ({"kind": "pdf_letter", "seam_allowance_cm": 50}, "at most 10 cm"),
        ({"kind": "pdf_letter", "seam_allowance_cm": "nan"}, "isn't a number"),
        ({"kind": "layout", "fabric_width_cm": -150}, "Fabric width -150 cm"),
    ]:
        with pytest.raises(ValueError) as e:
            S.api_export({**base, **extra})
        assert says in str(e.value), (extra, str(e.value))
    with pytest.raises(ValueError, match="isn't a picture"):
        S.api_trace({"image": "data:image/png;base64,AAAA", "p1": [0, 0], "p2": [10, 0], "length_cm": 10})


def test_the_server_keeps_the_latest_avatars_and_drapes(S, tmp_path):
    st = S._Store("gone", keep=3, drop=S._drop_job)
    for k in range(3):
        (tmp_path / f"j{k}").mkdir()
        st[f"j{k}"] = {"state": "done", "outdir": str(tmp_path / f"j{k}")}
    st["run"] = {"state": "running"}
    assert "j0" not in st and not (tmp_path / "j0").exists()          # the oldest goes, with its folder
    st["j1"]                                                          # used: newest again
    st["new"] = {"state": "done"}
    assert set(st) == {"j1", "run", "new"}                            # j2 went; the running one never does
    with pytest.raises(S.Missing, match="gone"):
        st["j0"]
    assert S.S.avatars.keep == S.AVATARS_KEPT and S.S.jobs.keep == S.JOBS_KEPT


def test_a_piece_typed_ten_times_too_big_gets_a_message_not_minutes_of_meshing(S, avatar_id):
    import copy
    import time
    from drape.freeform import editor_to_design
    d = editor_to_design(S.api_to_scratch({"avatar": avatar_id, "block": "tee"})["design"])
    big = copy.deepcopy(d)
    for e in big["pieces"][0]["edges"]:
        e["pts"] = [[x * 10, y * 10] for x, y in e["pts"]]
    t = time.time()
    r = S.api_scratch({"avatar": avatar_id, "design": big})
    assert time.time() - t < 10 and "more than the studio can work with" in r["error"], r.get("error")
    assert "If a size was typed too big" in r["error"]
    assert S.api_scratch({"avatar": avatar_id, "design": {**d, "spacing_cm": 0.0001}}).get("error") is None   # 5 mm at least


def test_closures_from_a_file_stay_within_what_can_be_sewn():
    from drape.closures import sane
    assert sane({"type": "buttons", "count": 1e6, "size_mm": -5, "open": 7}) == {"type": "buttons", "count": 200, "size_mm": 0, "open": 1}
    assert sane({"type": "snaps", "count": "x", "open": float("nan")})["count"] == 1
    assert "size_mm" not in sane({"type": "zipper"})


# ------------------------------------------------------------------ the page
pytest.importorskip("playwright.sync_api")
from test_browser import ST, _click_edge, _ensure_avatar, _go_garment, page, server  # noqa: E402,F401  (fixtures)

pytestmark = pytest.mark.slow


def _b64(a):
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def _garments(pg):
    _ensure_avatar(pg)
    pg.evaluate("loadGarments({garments: [], activeGarmentId: null}); renderGarmentList()")
    _go_garment(pg, "tee")
    pg.evaluate("activeGarment().name = 'Tee'; renderGarmentList()")


def test_the_3d_view_frees_the_buffers_of_what_it_replaces(page):
    pg = page
    _ensure_avatar(pg)
    pg.evaluate("""window.__live = 0;
        for (const P of [WebGLRenderingContext.prototype]) {
          const c = P.createBuffer, d = P.deleteBuffer;
          P.createBuffer = function () { __live++; return c.call(this) };
          P.deleteBuffer = function (b) { if (b) __live--; return d.call(this, b) };
        } 0""")
    # a move test moves the body every frame (and rebuilds the floor under it); the cloth is replaced on every drape
    pg.evaluate("""const m = ST.avatar.mesh, P16 = b64(m.v, Int16Array), P = new Float32Array(P16.length);
        for (let i = 0; i < P.length; i++) P[i] = P16[i] / 1000;
        GL.setBody(m); window.__after1 = __live;
        for (let k = 0; k < 50; k++) { GL.move("body", P); GL.setColored(m, new Float32Array(P.length).fill(0.5)) }
        window.__after50 = __live; 0""")
    a1, a50 = pg.evaluate("[__after1, __after50]")
    assert a50 - a1 <= 6, (a1, a50)          # one cloth's buffers at most, not 50 floors and 50 cloths
    pg.evaluate("GL.setColored(null); showAvatarOnly(); 0")
    assert not pg.errors, pg.errors


def test_drape_it_is_busy_per_garment_and_its_progress_stays_on_its_garment(page):
    pg = page
    _garments(pg)
    a = pg.evaluate(f"{ST}.PROJECT.activeGarmentId")
    pg.evaluate("duplicateGarment()")
    b = pg.evaluate(f"{ST}.PROJECT.activeGarmentId")
    # hidden: two visible garments drape together now (v33); this is about two separate drapes
    pg.evaluate(f"garmentBy('{b}').visible = false; renderGarmentList()")
    pg.evaluate(f"setActiveGarment('{a}')")
    v = np.array([0, 1000, 0, 100, 1000, 0, 0, 1100, 0], np.int16)
    full = {"v": _b64(v), "nv": 3, "f": _b64(np.array([0, 1, 2], np.uint32)), "nf": 1, "panel": _b64(np.full(9, 200, np.uint8))}
    moved = {"v": _b64(v + 5), "nv": 3}
    # a stand-in server: the drape job answers whatever window.__j holds
    pg.evaluate("""window.__a0 = api; window.__j = {state: "running", progress: 0.1, stage: "Sewing"};
        window.__toasts = []; window.__t0 = toast; window.toast = (m, ms) => (__toasts.push(m), __t0(m, ms));
        window.__calls = []; window.__gl = {sc: GL.setColored, mv: GL.move};
        GL.setColored = (...x) => (__calls.push("set"), __gl.sc(...x)); GL.move = (...x) => (__calls.push("move"), __gl.mv(...x));
        window.api = async (p, b) => {
          if (p === "/api/drape") return {job: "J"};
          if (p === "/api/job/J") { const j = __j; __j = {...__j, frame: undefined}; return j }
          return __a0(p, b) }; 0""")
    try:
        pg.evaluate("startDrape(); 0")
        pg.wait_for_function("document.querySelector('#drapeBtn').disabled")
        pg.evaluate(f"window.__j = {{state: 'running', progress: 0.2, stage: 'Sewing', frame: {json.dumps(full)}}}; 0")
        pg.wait_for_function("__calls.includes('set')", timeout=5000)
        # another garment: its own button works, the first one's progress isn't drawn over it
        pg.evaluate(f"setActiveGarment('{b}')")
        assert not pg.evaluate("document.querySelector('#drapeBtn').disabled")
        assert pg.evaluate("getComputedStyle(document.querySelector('#glov')).display") == "none"
        pg.evaluate(f"__calls.length = 0; window.__j = {{state: 'running', progress: 0.4, stage: 'Sewing', frame: {json.dumps(moved)}}}; 0")
        pg.wait_for_timeout(1200)
        assert pg.evaluate("__calls") == [] and pg.evaluate("getComputedStyle(document.querySelector('#glov')).display") == "none"
        # back to the first: positions alone come next, and the 3D view no longer holds its cloth: redrawn whole
        pg.evaluate(f"setActiveGarment('{a}')")
        assert pg.evaluate("document.querySelector('#drapeBtn').disabled")
        pg.evaluate(f"window.__j = {{state: 'running', progress: 0.6, stage: 'Sewing', frame: {json.dumps(moved)}}}; 0")
        pg.wait_for_function("__calls.length > 0", timeout=5000)
        assert pg.evaluate("__calls[0]") == "set", pg.evaluate("__calls")
        # it fails while the other garment is on screen: a message, not an overlay on the other garment
        pg.evaluate(f"setActiveGarment('{b}')")
        pg.evaluate("window.__j = {state: 'error', progress: 0.6, stage: 'Sewing', error: 'the graphics card stopped'}; 0")
        pg.wait_for_function("__toasts.some(t => t.includes('the drape failed'))", timeout=5000)
        assert pg.evaluate("getComputedStyle(document.querySelector('#glov')).display") == "none"
        pg.evaluate(f"setActiveGarment('{a}')")
        assert not pg.evaluate("document.querySelector('#drapeBtn').disabled")
        assert pg.evaluate("activeGarment().draping") is False
        assert "draping" not in pg.evaluate("garmentData(activeGarment())")
    finally:
        pg.evaluate("window.api = __a0; window.toast = __t0; GL.setColored = __gl.sc; GL.move = __gl.mv; 0")
    assert not pg.errors, pg.errors


def test_undo_keeps_the_newest_steps_in_a_long_session(page):
    pg = page
    _garments(pg)
    pg.evaluate(f"for (let k = 1; k <= 320; k++) {{ {ST}.ST.params = {{...{ST}.ST.params, n: k}}; pushHist() }} 0")
    assert pg.evaluate("H.stack.length") == pg.evaluate("UNDO_MAX") == 300
    assert pg.evaluate("H.i") == 299 and pg.evaluate("JSON.parse(H.stack[299].after).params.n") == 320
    pg.evaluate("goHist(-1)")
    pg.wait_for_function("activeGarment().params.n === 319", timeout=10000)
    # big snapshots: about UNDO_CHARS of them are kept
    pg.evaluate(f"H.stack = []; H.i = -1; for (let k = 1; k <= 12; k++) {{ {ST}.ST.params = {{...{ST}.ST.params, n: k, pad: 'x'.repeat(5e6)}}; pushHist() }} 0")
    n = pg.evaluate("H.stack.length")
    assert 6 <= n <= 8 and pg.evaluate("JSON.parse(H.stack[H.i].after).params.n") == 12, n
    pg.evaluate(f"delete {ST}.ST.params.pad; delete {ST}.ST.params.n; H.stack = []; H.i = -1; H.last = {{}}; pushHist(); updUndo(); 0")
    assert not pg.errors, pg.errors


def test_page_number_typos_dont_break_pieces_or_lose_closures(page):
    pg = page
    _ensure_avatar(pg)
    pg.evaluate("loadGarments({garments: [], activeGarmentId: null}); renderGarmentList()")
    pg.evaluate(f"{ST}.ST.scratch = true; {ST}.ST.design = {{format: 2, pieces: [makePiece('rect', {{w: 40, h: 60}}, 'front')], seams: []}}; "
                f"DS.sel = 'front'; {ST}.go('fit')")
    pg.wait_for_function("document.querySelector('#board')", timeout=30000)
    pg.wait_for_timeout(500)
    if not pg.evaluate("document.body.classList.contains('advanced')"):
        pg.click("#mode [data-m=adv]")
    n0 = pg.evaluate("pieceBy('front').verts.length")
    pg.click('#edgetools [data-et="dart"]')                         # the Dart tool on the toolbar, then the edge
    pg.fill('#toolpop [data-eo="w"]', "")                            # emptied: NaN would make NaN corners
    _click_edge(pg, "front", "bottom", 0.3)
    assert pg.evaluate("pieceBy('front').verts.length") == n0
    assert pg.evaluate("pieceBy('front').verts.flat().every(Number.isFinite)")
    pg.keyboard.press("Escape")
    # zoom has limits: a long scroll can't shrink the board to nothing
    for _ in range(80):
        pg.evaluate("document.querySelector('#board').dispatchEvent(new WheelEvent('wheel', {deltaY: -400, clientX: 300, clientY: 300, bubbles: true, cancelable: true}))")
    assert pg.evaluate("Math.max(DS.view[2], DS.view[3])") >= 1.99
    # a refused "top part only" keeps the seam's closure
    pg.evaluate(f"{ST}.ST.design.pieces.push(makePiece('rect', {{w: 40, h: 60}}, 'back')); "
                f"{ST}.ST.design.seams.push({{a: 'front.' + pieceBy('front').edges[1].name, b: 'back.' + pieceBy('back').edges[3].name, ease: 0, "
                f"closure: {{type: 'buttons', count: 5, size_mm: 15, open: 0}}}}); renderDsSeams(); 0")
    pg.evaluate("window.__p0 = prompt; window.prompt = () => 'abc'; 0")
    try:
        pg.evaluate("document.querySelector('#dsSeams [data-cpart]').click()")
        pg.wait_for_timeout(1500)
        assert pg.evaluate(f"{ST}.ST.design.seams[0].closure && {ST}.ST.design.seams[0].closure.count") == 5
    finally:
        pg.evaluate("window.prompt = __p0; 0")
    assert not pg.errors, pg.errors


def test_a_free_edit_just_before_a_switch_gets_its_own_undo_step(page):
    pg = page
    _ensure_avatar(pg)
    pg.evaluate("loadGarments({garments: [], activeGarmentId: null}); renderGarmentList()")
    pg.evaluate(f"{ST}.ST.scratch = true; {ST}.ST.design = {{format: 2, pieces: [makePiece('rect', {{w: 40, h: 60}}, 'front')], seams: []}}; "
                f"{ST}.go('fit'); pushHist(); 0")
    a = pg.evaluate(f"{ST}.PROJECT.activeGarmentId")
    pg.evaluate("duplicateGarment()")
    b = pg.evaluate(f"{ST}.PROJECT.activeGarmentId")
    pg.evaluate(f"setActiveGarment('{a}'); H.stack = []; H.i = -1; H.last = {{}}; pushHist(); pushHist(garmentBy('{b}')); 0")
    pg.evaluate(f"pieceBy('front').at = [55, 0]; dsSoon(); setActiveGarment('{b}'); 0")   # switched within the 250 ms
    pg.wait_for_timeout(800)
    st = pg.evaluate("H.stack.map(e => e.gid)")
    assert st == [a], st
    assert pg.evaluate(f"JSON.parse(H.stack[0].after).design.pieces[0].at[0]") == 55
    assert not pg.errors, pg.errors
