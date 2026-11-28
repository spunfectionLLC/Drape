"""v27: bugs found in a review of the multi-garment studio (2026-11-25).

- a shared .drape / .garment file is someone else's text: its names can't put markup in the page; ids, colours
  and units must have their own shape; a pattern or fabric this copy doesn't have still opens
- renaming a garment: Escape cancels
- deleting a garment keeps undo / redo in step
- Live simulates one garment: switching stops it; a frozen garment doesn't go live
- a piece fabric the server doesn't have: a clear message, not a KeyError
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

EVIL = '<img src=x onerror="window.__pwn=1">'


# ------------------------------------------------------------------ server side (no browser)
def test_an_unknown_piece_fabric_says_so():
    from drape import fabrics

    class G:
        meta = {"panel_fabric_keys": [("not_a_fabric", None)]}
    with pytest.raises(ValueError, match="unknown fabric 'not_a_fabric'"):
        fabrics.panel_fabrics(G(), fabrics.get("jersey"))

    class H:
        meta = {"panel_fabric_keys": [("jersey", "not_an_interfacing")]}
    with pytest.raises(ValueError, match="unknown interfacing"):
        fabrics.panel_fabrics(H(), fabrics.get("jersey"))


@pytest.mark.parametrize("change, says", [
    ({"waist": -70}, "Waist -70 cm: a measurement can't be zero or less"),
    ({"height": 0}, "Height 0 cm: a measurement can't be zero or less"),
    ({"chest": "abc"}, 'Chest "abc": type a number'),
    # every number typed in inches into cm fields: the typo message, not the fit's crash
    ({"height": 65, "chest": 36, "waist": 29, "hip": 39}, "Height 65 cm: if you measured in inches"),
])
def test_numbers_an_avatar_cant_be_built_from_say_which_number(change, says):
    from drape import webapi
    from drape.studio import server as S
    m = {**S.api_init()["examples"]["female_M"], **change}
    r = webapi.handle("POST", "/api/avatar", json.dumps({"measurements": m}))
    assert r["status"] == 500 and says in json.loads(r["body"])["error"], r["body"][:300]
    err = json.loads(r["body"])["error"].lower()
    assert not any(w in err for w in ("ratio", "unusual", "too large", "too big", "proportion"))   # about the number only


@pytest.fixture(scope="module")
def avatar_id():
    from drape.studio import server as S
    return S.api_avatar({"measurements": S.api_init()["examples"]["female_M"]})["id"]


def test_a_damaged_or_far_flung_frozen_garment_from_a_file_is_handled(avatar_id):
    import base64
    import numpy as np
    from drape.colliders import layered_body
    from drape.studio import server as S
    body = S.S.avatars[avatar_id]["body"]
    b64 = lambda a: base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()
    # a sheet in front of the body, plus one stray point 30 m away (int16 mm allows +-32 m)
    V = np.array([[-200, 1000, 250], [200, 1000, 250], [0, 1400, 250], [30000, 30000, 30000]], np.int16)
    F = np.array([[0, 1, 2], [0, 1, 3]], np.uint32)
    lb = layered_body(body, [{"v": b64(V), "f": b64(F)}])
    assert lb.grid.size < 4 * body.grid.size, (lb.grid.shape, body.grid.shape)     # not billions of cells
    for bad in ({"v": b64(V), "f": b64(np.array([[0, 1, 99]], np.uint32))},       # a corner that isn't there
                {"v": b64(V)[:-4], "f": b64(F)}, {"v": "not base64!", "f": b64(F)}):
        with pytest.raises(ValueError, match="damaged"):
            layered_body(body, [bad])


def test_pattern_values_from_a_file_stay_within_sanity_limits(avatar_id):
    import time
    from drape.blocks import BLOCKS
    from drape.studio import server as S
    t = time.time()
    d = S.api_draft({"avatar": avatar_id, "block": "a_line_skirt", "choices": {},
                     "params": {"length": 1e6, "hip_ease": float("nan"), "waist_ease": "lots", "bogus": 3}})
    assert time.time() - t < 60
    P = {p.name: p for p in BLOCKS["a_line_skirt"].params}
    span = P["length"].hi - P["length"].lo
    assert d["params"]["length"] <= P["length"].hi + 2 * span
    assert d["params"]["hip_ease"] == d["defaults"]["hip_ease"] or abs(d["params"]["hip_ease"]) < 1e3
    # Shorts' hem fits its slider (it was 48.5 cm on a slider that stopped at 40)
    tr = S.api_draft({"avatar": avatar_id, "block": "trousers", "choices": {"Length": "Shorts"}, "params": {}})
    hp = {p.name: p for p in BLOCKS["trousers"].params}["hem_above_floor"]
    assert hp.lo <= tr["params"]["hem_above_floor"] <= hp.hi


def test_an_avatar_or_drape_the_server_lost_says_so_in_words():
    from drape import webapi
    r = json.loads(webapi.handle("POST", "/api/draft", '{"avatar": "gone", "block": "tee"}')["body"])
    assert "isn't on the studio's server any more" in r["error"] and "Body" in r["error"]
    r = json.loads(webapi.handle("GET", "/api/job/gone")["body"])
    assert "Press Drape it again" in r["error"]


def test_a_drape_worker_that_dies_ends_its_job_with_an_error(avatar_id):
    import time
    from drape.studio import server as S
    jid = S.api_drape({"avatar": avatar_id, "block": "tee", "choices": {}, "params": {}, "quality": "quick"})["job"]
    p = S.S.jobs[jid]["proc"]
    p.kill()
    p.join(30)
    for _ in range(5):
        j = S.api_job(jid)
        if j["state"] != "running":
            break
        time.sleep(0.2)
    assert j["state"] == "error" and "stopped unexpectedly" in j["error"], j


def test_another_website_cannot_drive_the_desktop_studio():
    """The studio listens on 127.0.0.1 (or the home network): a page in another tab could POST to it. Only the
    studio's own JSON requests, to an IP address or this computer's name, from its own origin, are answered."""
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer
    from drape.studio import server as S
    srv = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/api/costing"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def post(headers):
        try:
            with opener.open(urllib.request.Request(url, b"{}", headers), timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    try:
        assert post({"Content-Type": "text/plain"})[0] == 403                        # a form / simple fetch
        assert post({"Content-Type": "application/json", "Origin": "https://evil.example"})[0] == 403
        assert post({"Content-Type": "application/json", "Origin": "null"})[0] == 403
        code, body = post({"Content-Type": "application/json", "Host": "evil.example:8765"})   # DNS rebinding
        assert code == 403 and "host" in body["error"]
        code, body = post({"Content-Type": "application/json"})                       # the page's own request
        assert code != 403, body
        o = f"http://127.0.0.1:{srv.server_address[1]}"
        assert post({"Content-Type": "application/json; charset=utf-8", "Origin": o})[0] != 403
    finally:
        srv.shutdown()


def test_an_export_name_from_the_request_stays_a_file_name(avatar_id, tmp_path):
    import tempfile
    from drape.freeform import editor_to_design
    from drape.studio import server as S
    d = editor_to_design(S.api_starter({"avatar": avatar_id, "key": "crop_tee"})["design"])
    before = len(list(Path(tempfile.gettempdir()).glob("drape_export_*")))
    for bad in ("../../escape", 'x"; filename="evil.exe', "a/b\\c"):
        fname, mime, data = S.api_export({"avatar": avatar_id, "design": d, "block": bad, "kind": "dxf"})
        assert "/" not in fname and "\\" not in fname and '"' not in fname and ".." not in fname, fname
        assert data[:1] and fname.endswith(".dxf")
    assert not list(Path(tempfile.gettempdir()).parent.glob("escape*"))
    assert len(list(Path(tempfile.gettempdir()).glob("drape_export_*"))) <= before   # export folders are removed


def test_the_website_drape_ends_in_an_error_not_running_for_ever(avatar_id):
    import base64
    import numpy as np
    from drape import webapi
    from drape.studio import server as S
    req = {"avatar": avatar_id, "block": "tee", "choices": {}, "params": {}, "fabric": "jersey", "quality": "quick"}
    # the GPU's result is not a number: drape_done fails, and so does the job the page is polling
    r = webapi.api_drape(req)
    n = len(webapi.JOBS[r["job"]][1].x)
    bad = base64.b64encode(np.full((n, 3), np.nan, np.float32).tobytes()).decode()
    assert webapi.handle("POST", "/api/drape_done", json.dumps({"job": r["job"], "x": bad}))["status"] == 500
    j = S.api_job(r["job"])
    assert j["state"] == "error" and "not a number" in j["error"] and r["job"] not in webapi.JOBS
    # the GPU stopped in the page: the prepared job is freed and ends with the page's reason
    r = webapi.api_drape(req)
    webapi.handle("POST", "/api/drape_cancel", json.dumps({"job": r["job"], "reason": "the graphics card stopped"}))
    j = S.api_job(r["job"])
    assert r["job"] not in webapi.JOBS and j["state"] == "error" and j["error"] == "the graphics card stopped"


# ------------------------------------------------------------------ the page
pytest.importorskip("playwright.sync_api")
from test_browser import ST, _ensure_avatar, _go_garment, page, server  # noqa: E402,F401  (fixtures)

pytestmark = pytest.mark.slow


def _evil_project(pg):
    a = pg.evaluate(f"makePiece('rect', {{w: 40, h: 60}}, {json.dumps(EVIL)})")
    b = pg.evaluate("makePiece('rect', {w: 40, h: 60}, 'b & c')")
    a["edges"][1]["name"] = 'right"><b>x</b>'
    return {"format": "drape-project", "version": 2, "name": EVIL, "avatar": {"measurements": {"sex": "female", "height": 166,
            "chest": 92, "waist": 74, "hip": 100}}, "scene": {"units": 'cm"]'},
            "garments": [{"id": 'g1" onmouseover="window.__pwn=2', "name": EVIL, "color": 'red;"><img src=x onerror="window.__pwn=3">',
                          "layer": 1, "visible": True, "frozen": False, "block": None, "scratch": True, "fabric": "jersey",
                          "design": {"format": 2, "pieces": [a, b], "seams": [{"a": a["name"] + '.right"><b>x</b>', "b": "b & c.left"}]}},
                         {"id": 'g1" onmouseover="window.__pwn=2', "name": "Same id", "layer": 2, "block": "tee"}],
            "activeGarmentId": 'g1" onmouseover="window.__pwn=2'}


def test_a_shared_file_cannot_put_markup_in_the_page(page):
    pg = page
    _ensure_avatar(pg)
    pg.evaluate(f"openProject({json.dumps(_evil_project(pg))})")
    pg.wait_for_function(f"{ST}.PROJECT.garments.length === 2 && {ST}.ST.scratch", timeout=120000)
    pg.evaluate(f"{ST}.go('fit')")                                   # the design editor: inspector, board, seam list
    pg.wait_for_timeout(1500)
    pg.evaluate("document.querySelectorAll('#glist .grow').forEach(r => r.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}))); 0")
    assert pg.evaluate("window.__pwn") is None
    assert pg.evaluate("document.querySelectorAll('img[src=x], #side b:not([class]) + b').length") == 0
    gs = pg.evaluate(f"{ST}.PROJECT.garments.map(g => [g.id, g.color, g.name])")
    assert gs[0][0] != gs[1][0]                                       # ids are unique, and plain
    assert all(set(i) <= set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-") for i, _, _ in gs), gs
    assert gs[0][1].startswith("#") and "<" not in gs[0][2]
    names = pg.evaluate(f"{ST}.ST.design.pieces.map(p => p.name)")
    assert all("<" not in n and '"' not in n and "&" not in n for n in names), names
    assert "b and c" in names
    seam = pg.evaluate(f"{ST}.ST.design.seams[0]")                   # both ends cleaned the same way: still the same edges
    pa, ea = seam["a"].rsplit(".", 1)
    assert pg.evaluate(f"pieceBy({json.dumps(pa)}).edges.some(e => e.name === {json.dumps(ea)})"), seam
    assert pg.evaluate(f"{ST}.ST.units") in ("cm", "in")             # the odd units didn't break the open
    assert not pg.errors, pg.errors


def test_a_pattern_or_fabric_this_copy_lacks_still_opens(page):
    pg = page
    _ensure_avatar(pg)
    proj = {"format": "drape-project", "version": 2, "name": "From the future", "avatar": {"measurements": {"sex": "female",
            "height": 166, "chest": 92, "waist": 74, "hip": 100}}, "scene": {"units": "cm"},
            "garments": [{"id": "fut", "name": "Cape", "layer": 1, "block": "cape_2030", "fabric": "my_silk_from_elsewhere"}],
            "activeGarmentId": "fut"}
    pg.evaluate("window.__toasts = []; const t0 = toast; window.toast = (m, ms) => (__toasts.push(m), t0(m, ms)); 0")
    pg.evaluate(f"openText({json.dumps(json.dumps(proj))}, 'future.drape')")
    pg.wait_for_function(f"{ST}.ST.name === 'From the future'", timeout=120000)
    pg.wait_for_timeout(500)
    g = pg.evaluate(f"{ST}.PROJECT.garments[0]")
    assert g["block"] is None and g["fabric"] == "jersey"
    assert pg.evaluate(f"{ST}.ST.step") in ("garment", "body")        # it opens; you pick another pattern
    assert any("cape_2030" in t and "my_silk_from_elsewhere" in t for t in pg.evaluate("__toasts")), pg.evaluate("__toasts")
    assert not pg.errors, pg.errors


def _garments(pg):
    _ensure_avatar(pg)
    pg.evaluate(f"loadGarments({{garments: [], activeGarmentId: null}}); renderGarmentList()")
    _go_garment(pg, "tee")
    pg.evaluate(f"activeGarment().name = 'Tee'; renderGarmentList()")


def test_escape_cancels_a_rename(page):
    pg = page
    _garments(pg)
    pg.dblclick("#glist .grow .gname")
    pg.fill("#glist .gnamein", "Not this")
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(200)
    assert pg.evaluate(f"{ST}.PROJECT.garments[0].name") == "Tee"
    pg.dblclick("#glist .grow .gname")
    pg.fill("#glist .gnamein", "Long tee")
    pg.keyboard.press("Enter")
    assert pg.evaluate(f"{ST}.PROJECT.garments[0].name") == "Long tee"
    assert not pg.errors, pg.errors


def test_deleting_a_garment_keeps_undo_and_redo_in_step(page):
    pg = page
    _garments(pg)
    a = pg.evaluate(f"{ST}.PROJECT.activeGarmentId")
    pg.evaluate("duplicateGarment()")
    b = pg.evaluate(f"{ST}.PROJECT.activeGarmentId")
    # undo stack: [A: x=1, B: y=1, A: x=2]; then undo once (A back to x=1, redo available)
    for gid, k, v in ((a, "x", 1), (b, "y", 1), (a, "x", 2)):
        pg.evaluate(f"setActiveGarment('{gid}', {{quiet: true}}); {ST}.ST.params = {{...{ST}.ST.params, {k}: {v}}}; pushHist()")
    pg.evaluate("goHist(-1)")
    pg.wait_for_function(f"garmentBy('{a}').params.x === 1", timeout=10000)
    pg.evaluate(f"window.confirm = () => true; deleteGarment(garmentBy('{b}'))")
    assert pg.evaluate("H.stack.every(e => e.gid !== '%s')" % b)
    assert pg.evaluate("!document.querySelector('#redo').disabled")   # A's x=2 can still be redone
    pg.evaluate("goHist(1)")
    pg.wait_for_function(f"garmentBy('{a}').params.x === 2", timeout=10000)
    pg.evaluate("goHist(-1)")
    pg.wait_for_function(f"garmentBy('{a}').params.x === 1", timeout=10000)
    assert not pg.errors, pg.errors


def test_switching_garments_stops_live_and_a_frozen_garment_does_not_go_live(page):
    pg = page
    _garments(pg)
    a = pg.evaluate(f"{ST}.PROJECT.activeGarmentId")
    pg.evaluate("duplicateGarment()")
    # a stand-in for a running Live sim (these tests may have no WebGPU)
    pg.evaluate("window.__destroyed = 0; LIVE.sim = {destroy() { __destroyed++ }}; LIVE.run = true; 0")
    pg.evaluate(f"setActiveGarment('{a}')")
    assert pg.evaluate("LIVE.sim") is None and pg.evaluate("__destroyed") == 1
    pg.evaluate(f"activeGarment().frozen = true; window.__live = 0; window.__a2 = api; window.api = (p, b) => (p === '/api/live' && __live++, __a2(p, b)); 0")
    pg.evaluate("startLive()")
    pg.wait_for_timeout(300)
    assert pg.evaluate("__live") == 0 and "frozen" in pg.inner_text("#toast")
    pg.evaluate("activeGarment().frozen = false; window.api = __a2; 0")
    assert not pg.errors, pg.errors


def test_a_project_too_big_for_the_browser_is_kept_without_frozen_shapes_and_says_so(page):
    pg = page
    _garments(pg)
    big = "A" * 400000
    pg.evaluate(f"activeGarment().frozen = true; activeGarment().frozenMesh = {{v: '{big}', f: 'AAAA'}}; 0")
    # a browser whose storage takes 200 kB at most
    pg.evaluate("""window.__setItem = Storage.prototype.setItem; window.__toasts = [];
        Storage.prototype.setItem = function (k, v) { if (String(v).length > 200000) throw new DOMException('full', 'QuotaExceededError'); return __setItem.call(this, k, v) };
        const t0 = toast; window.toast = (m, ms) => (__toasts.push(m), t0(m, ms)); 0""")
    try:
        assert pg.evaluate("autosave()") is True
        kept = pg.evaluate("JSON.parse(localStorage.getItem('drape.project'))")
        assert kept["garments"][0]["name"] == "Tee" and not kept["garments"][0].get("frozenMesh") and not kept["garments"][0]["frozen"]
        assert any("Save it to a file" in t for t in pg.evaluate("__toasts"))
    finally:
        pg.evaluate("Storage.prototype.setItem = __setItem; activeGarment().frozen = false; activeGarment().frozenMesh = undefined; autosave(); 0")
    assert not pg.errors, pg.errors


def test_exports_and_taps_use_the_drape_on_screen_not_a_redrape_that_failed(page):
    pg = page
    _garments(pg)
    # the drape on screen came from job "good"; a later re-drape (job "failed") didn't finish
    pg.evaluate(f"activeGarment().drapeJob = 'good'; activeGarment().job = 'failed'; 0")
    assert pg.evaluate("exportReq('glb', {}).job") == "good"
    pg.evaluate("activeGarment().drapeJob = undefined; 0")
    assert not pg.errors, pg.errors


def test_odd_drops_and_half_frozen_files_dont_break_the_panel(page):
    pg = page
    _garments(pg)
    tee = pg.evaluate(f"{ST}.PROJECT.activeGarmentId")
    pg.evaluate(f"moveGarment('some dragged text', '{tee}'); moveGarment('{tee}', 'nope'); 0")      # nothing happens
    assert pg.evaluate(f"{ST}.PROJECT.garments.map(g => g.layer)") == [1]
    # frozen, but the file has no frozen shape: it opens unfrozen (it could neither drape nor collide)
    p = pg.evaluate("migrateProject({version: 2, garments: [{id: 'a', name: 'A', layer: 1, frozen: true}], activeGarmentId: 'a'})")
    assert p["garments"][0]["frozen"] is False
    # a piece renamed with HTML's characters keeps the rest
    pg.evaluate(f"""(() => {{ window.__studio.ST.design = {{pieces: [makePiece('rect', {{w: 40, h: 60}}, 'a')], seams: []}};
        window.__studio.ST.scratch = true; renamePiece(pieceBy('a'), '<b>"x&y"</b>') }})()""")
    assert pg.evaluate(f"{ST}.ST.design.pieces[0].name") == "bxy/b"
    pg.evaluate(f"{ST}.ST.scratch = false; 0")
    assert not pg.errors, pg.errors
