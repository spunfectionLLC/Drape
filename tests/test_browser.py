"""The studio in a real browser: clicks, drags and what the user sees.

Starts its own studio server and drives Chrome with Playwright. Skipped when
Playwright or a browser isn't installed. Slow (an avatar build and drapes):
run with  pytest tests/test_browser.py
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.slow

ST = "window.__studio"


def _chrome():
    for p in (os.environ.get("DRAPE_CHROME"), "/usr/bin/google-chrome", shutil.which("google-chrome"),
              shutil.which("chromium"), shutil.which("chromium-browser")):
        if p and Path(p).exists():
            return p
    return None          # Playwright's own Chromium, if installed


@pytest.fixture(scope="module")
def server():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    proc = subprocess.Popen([sys.executable, "-m", "drape.studio", "--port", str(port), "--no-browser"],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            break
        except OSError:
            time.sleep(0.5)
    else:
        proc.kill()
        pytest.skip("studio server didn't start")
    yield f"http://127.0.0.1:{port}/"
    proc.terminate()
    proc.wait(10)


def _started(pg):
    """Wait until the page has started (/api/init answered, boot done). With four test files draping at once
    the page's start sometimes stalled for minutes (each file passes on its own); one reload, then a clear error
    with what the page said."""
    for attempt in range(2):
        try:
            pg.wait_for_function("() => window.__studio && window.__studio.ST.init", timeout=90000)
            return
        except Exception:
            if attempt:
                raise AssertionError(f"the studio page didn't start; page errors: {getattr(pg, 'errors', [])}")
            pg.reload()


@pytest.fixture(scope="module")
def page(server):
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch(executable_path=_chrome(), args=["--use-gl=swiftshader", "--enable-webgl",
                                                                   "--ignore-gpu-blocklist"])
        except Exception as e:     # no browser available
            pytest.skip(f"no browser: {e}")
        pg = b.new_page(viewport={"width": 1600, "height": 1000})
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.on("dialog", lambda d: d.accept())
        pg.goto(server)
        pg.evaluate("localStorage.clear()")
        pg.reload()
        _started(pg)
        pg.wait_for_timeout(400)
        # these tests drive every tool, so Advanced mode (Simple hides some: tests/test_v25_simple.py)
        pg.click("#mode [data-m=adv]")
        yield pg
        b.close()


def _go_garment(pg, key):
    pg.evaluate(f"{ST}.go('garment')")   # the picker (Garment and Design are one step now)
    pg.wait_for_timeout(300)
    pg.click(f'#gcards [data-k="{key}"]')
    pg.wait_for_function(f"{ST}.ST.draft && {ST}.ST.block === '{key}' && !{ST}.ST.scratch", timeout=60000)
    pg.wait_for_timeout(600)


def _convert(pg, piece):
    pg.click("#toScratch")
    pg.wait_for_function(f"{ST}.ST.scratch && {ST}.ST.design.pieces.some(p => p.name === '{piece}')", timeout=60000)
    pg.wait_for_timeout(1800)


def _verts(pg, name):
    return pg.evaluate(f"JSON.parse(JSON.stringify(pieceBy('{name}').verts))")


def _drag(pg, sel, dx, dy):
    box = pg.locator(sel).bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    pg.mouse.move(x, y)
    pg.mouse.down()
    pg.mouse.move(x + dx, y + dy, steps=6)
    pg.mouse.up()
    pg.wait_for_timeout(2500)


def test_body_step_and_avatar(page):
    pg = page
    pg.click("#moremeas summary")
    keys = pg.eval_on_selector_all("#mfields input, #mfields2 input", "els => els.map(e => e.dataset.k)")
    for k in ("height", "chest", "inseam", "hand_length", "hand_girth", "wrist"):
        assert k in keys
    # Simple mode: no build button, the avatar builds itself from the numbers ("less is more" spec)
    pg.click("#mode [data-m=beg]")
    assert not pg.locator("#build").is_visible()
    pg.evaluate("markStale()")
    pg.wait_for_function(f"{ST}.ST.avatar", timeout=120000)
    pg.click("#mode [data-m=adv]")
    assert pg.locator("#build").is_visible()
    assert not pg.errors


def test_fit_step_layout(page):
    pg = page
    _go_garment(pg, "trousers")
    side = pg.locator("#side").bounding_box()
    btn = pg.locator("#toScratch").bounding_box()
    top = pg.locator("#gpanel").bounding_box()                                     # under the Garments panel (v26)
    assert btn["y"] < top["y"] + top["height"] + 160 and btn["width"] > side["width"] * 0.8      # big, at the top
    assert pg.inner_text("#logcnt") == "0" and "every check passes" in pg.inner_text("#logsum")
    assert not pg.locator("#toolcard").is_visible()                               # tools only in Design


def test_design_layout_toolbar_on_top_selected_piece_on_the_left(page):
    """Design (2026-11-24): the top toolbar has everything not about the selected piece, the left bar
    the selected piece, the pattern most of the screen; the 3D view only when asked for."""
    pg = page
    _convert(pg, "front_r")
    pg.evaluate("document.body.classList.remove('show3d')")
    tools, pat, side = (pg.locator(s).bounding_box() for s in ("#toolcard", "#patcard", "#side"))
    assert tools["y"] + tools["height"] <= pat["y"] + 1 and abs(tools["x"] - pat["x"]) < 2       # toolbar above the pattern
    assert side["x"] + side["width"] <= pat["x"] and pat["width"] > 2 * side["width"]            # pattern: the big area
    assert not pg.locator("#glcard").is_visible()                                                 # no 3D unless asked
    assert pg.locator("#side #inspector").count() == 1 and pg.locator("#side #cutBtn").count() == 1
    for s in ("#tool", "#symBtn", "#shapes", "#bands", "#dsSeams", "#dsPreview", "#show3d"):
        assert pg.locator(f"#toolcard {s}").count() == 1, s
    pg.click("#show3d")
    assert pg.locator("#glcard").is_visible() and pg.locator("#glcard").bounding_box()["x"] > pat["x"]
    pg.click("#show3d")
    assert not pg.locator("#glcard").is_visible()


def test_every_step_opens_and_says_what_it_needs(page, server):
    """Steps aren't locked: one that isn't ready opens greyed out, with a message and a way there."""
    ctx = page.context.browser.new_context(viewport={"width": 1400, "height": 900})   # its own storage: no avatar
    pg = ctx.new_page()
    pg.goto(server)
    pg.wait_for_function(f"{ST} && {ST}.ST.init", timeout=60000)
    pg.evaluate("localStorage.clear()")
    pg.reload(); pg.wait_for_function(f"{ST} && {ST}.ST.init && !{ST}.ST.avatar", timeout=60000)
    assert pg.evaluate("[...document.querySelectorAll('#steps button')].every(b => !b.disabled)")
    for k in ("garment", "fit", "preview", "export"):
        pg.evaluate(f"{ST}.go('{k}')")
        assert pg.evaluate("document.body.dataset.blocked") == "1", k
        assert "Build your avatar first" in pg.inner_text("#blockmsg")
    pg.click("#blockGo")
    assert pg.evaluate(f"{ST}.ST.step") == "body" and pg.evaluate("!document.body.dataset.blocked")
    ctx.close()


def test_symmetric_drag_and_warning_fix(page):
    pg = page
    pg.click('#pattern [data-body="front_r"]')
    pg.wait_for_timeout(400)
    assert "front_l" in pg.inner_text("#toolhint")                                # it says what's linked
    r0, l0 = _verts(pg, "front_r"), _verts(pg, "front_l")
    _drag(pg, '#pattern [data-vert="1"]', -14, 12)
    r1, l1 = _verts(pg, "front_r"), _verts(pg, "front_l")
    moved_r = [i for i in range(len(r0)) if r0[i] != r1[i]]
    moved_l = [i for i in range(len(l0)) if l0[i] != l1[i]]
    assert moved_r == [1] and len(moved_l) == 1
    j = moved_l[0]
    assert abs((r1[1][0] - r0[1][0]) + (l1[j][0] - l0[j][0])) < 1e-6           # mirrored across
    assert abs((r1[1][1] - r0[1][1]) - (l1[j][1] - l0[j][1])) < 1e-6           # same up/down
    # the outseams no longer match: in the log, as badges and as a popup on the edge
    assert int(pg.inner_text("#logcnt")) >= 2
    assert pg.locator("#board .wbadge").count() >= 2
    assert pg.locator("#warnpop").count() == 1
    # the pinned Warnings box never covers the side panel, even on a laptop-size window
    pg.set_viewport_size({"width": 1366, "height": 768})
    pg.wait_for_timeout(300)
    side, log = pg.locator("#side").bounding_box(), pg.locator("#logcard").bounding_box()
    assert side["y"] + side["height"] <= log["y"] + 1
    pg.set_viewport_size({"width": 1600, "height": 1000})
    pg.wait_for_timeout(300)
    # the popup never blocks a handle (scrolled into view: the pattern is the big area now)
    pg.locator('#pattern [data-vert="1"]').scroll_into_view_if_needed()
    box = pg.locator('#pattern [data-vert="1"]').bounding_box()
    hit = pg.evaluate(f"document.elementFromPoint({box['x'] + box['width'] / 2}, {box['y'] + box['height'] / 2}).dataset.vert")
    assert hit == "1"
    # one fix, mirrored: both legs' seams match again
    pg.click("#warnpop [data-f='0']")
    pg.wait_for_timeout(3000)
    assert pg.inner_text("#logcnt") == "0" and pg.locator("#warnpop").count() == 0


def test_symmetry_off(page):
    pg = page
    pg.click("#symBtn")
    pg.wait_for_timeout(300)
    l0 = _verts(pg, "front_l")
    _drag(pg, '#pattern [data-vert="1"]', 6, 0)
    assert _verts(pg, "front_l") == l0
    pg.click("#symBtn")
    pg.wait_for_timeout(300)


def test_self_symmetric_piece_and_curve(page):
    pg = page
    _go_garment(pg, "tee")
    _convert(pg, "front")
    pg.click('#pattern [data-body="front"]')
    pg.wait_for_timeout(400)
    v0 = _verts(pg, "front")
    _drag(pg, '#pattern [data-vert="1"]', 10, 5)
    v1 = _verts(pg, "front")
    moved = [i for i in range(len(v0)) if v0[i] != v1[i]]
    assert sorted(moved) == [0, 1] and abs(v1[0][0] + v1[1][0]) < 1e-6          # both hem corners, mirrored
    names = pg.evaluate("pieceBy('front').edges.map(e => e.name)")
    _drag(pg, f'#pattern [data-mid="{names.index("neck")}"]', 12, 8)
    e = pg.evaluate(f"JSON.parse(JSON.stringify(pieceBy('front').edges[{names.index('neck')}]))")
    xs = [v[0] for v in v1]
    cx = (min(xs) + max(xs)) / 2
    if e.get("pts"):
        P = e["pts"]
        assert max(abs((P[k][0] - cx) + (P[-1 - k][0] - cx)) + abs(P[k][1] - P[-1 - k][1]) for k in range(len(P))) < 1e-6
    else:
        assert abs(e["c1"][0] - cx + (e["c2"][0] - cx)) < 1e-6


def test_mirrored_split(page):
    pg = page
    _go_garment(pg, "trousers")
    _convert(pg, "front_r")
    r = pg.evaluate("""(() => { const A = pieceBy('front_r'); splitEdge(A, A.edges.findIndex(e => e.name === 'outseam'), 0.3);
        return [pieceBy('front_r').edges.map(e => e.name), pieceBy('front_l').edges.map(e => e.name)] })()""")
    assert r[0] == ["hem", "outseam_1", "outseam_2", "waist", "centre", "crotch", "inseam"]
    assert r[1] == ["inseam", "crotch", "centre", "waist", "outseam_2", "outseam_1", "hem"]   # _1 at the hem on both


def test_glove_template_drapes(page):
    pg = page
    pg.evaluate(f"{ST}.go('garment')")   # the picker (Garment and Design are one step now)
    pg.wait_for_timeout(300)
    pg.click('#scats .chip[data-c="Accessories"]')
    pg.click('#scards .gcard[data-s="knit_gloves"]')
    pg.wait_for_function(f"{ST}.ST.design && {ST}.ST.design.from_starter === 'knit_gloves'", timeout=60000)
    pg.wait_for_timeout(1500)
    assert pg.evaluate(f"{ST}.ST.design.body_offset") == 0.002
    pg.click("#dsPreview")
    pg.wait_for_timeout(300)
    pg.click("#drapeBtn")
    pg.wait_for_function(f"{ST}.ST.drape", timeout=900000)
    pg.wait_for_timeout(800)
    advice = pg.inner_text("#advice")
    assert "hands" in advice and "hips" not in advice
    # snug knit gloves are a fit note (neutral), not a warning ("less is more" spec 1.3)
    assert pg.locator("#advice .check.note").count() >= 1 and "hands" not in pg.inner_text("#logbody").lower()
    assert not pg.errors, pg.errors


# ------------------------------------------------------------ v1.5
def _ensure_avatar(pg):
    """These tests can run on their own (pytest -k): build an avatar if none is there yet."""
    if not pg.evaluate(f"!!{ST}.ST.avatar"):
        pg.click("#steps button[data-k=body]")
        pg.evaluate("autoBuild()")              # Simple mode builds by itself; this covers Advanced too
        pg.wait_for_function(f"{ST}.ST.avatar", timeout=180000)


def _two_rects(pg):
    """A clean board: two rectangles a | b sewn side to side (and the tee's avatar)."""
    pg.evaluate("""(() => { const a = makePiece('rect', {w: 40, h: 60}, 'a'), b = makePiece('rect', {w: 40, h: 60}, 'b');
        window.__studio.ST.design = {pieces: [a, b], seams: [{a: 'a.right', b: 'b.left', ease: 0}]};
        const DS = window.__studio.DS; DS.sel = 'a'; DS.view = null; DS.shape = null; tidy(); dsChanged(true, true) })()""")
    pg.wait_for_timeout(800)


def _edge_xy(pg, piece, edge, t=0.5):
    """Where on the screen the spot t along a piece's edge is (the board is SVG, y up)."""
    return pg.evaluate("""([pn, en, t]) => { const P = pieceBy(pn), k = P.edges.findIndex(e => e.name === en), pts = edgePts(P, k, 80);
        const w = boardXY(P, pointAtFrac(pts, arcFrac(pts), t)), sv = document.querySelector('#board'), q = sv.createSVGPoint();
        q.x = w[0]; q.y = -w[1]; const s = q.matrixTransform(sv.getScreenCTM()); return [s.x, s.y] }""", [piece, edge, t])


def _click_edge(pg, piece, edge, t=0.5):
    x, y = _edge_xy(pg, piece, edge, t)
    pg.mouse.move(x, y)
    pg.mouse.click(x, y)
    pg.wait_for_timeout(400)


def test_shape_it_cuts_with_a_dragged_shape(page):
    pg = page
    _ensure_avatar(pg)
    _go_garment(pg, "tee")
    _convert(pg, "front")
    _two_rects(pg)
    pg.click("#pshape")
    assert pg.locator("#shapepanel").is_visible() and pg.locator("#board [data-shape]").count() == 1
    p0 = pg.evaluate(f"{ST}.DS.shape.pos")
    _drag(pg, "#board [data-shape]", 0, 25)                                    # down onto the piece
    p1 = pg.evaluate(f"{ST}.DS.shape.pos")
    assert p1[1] < p0[1] - 2 and abs(p1[0] - p0[0]) < 0.5                       # moved down (y is up on the board)
    assert pg.locator("#toolpop").is_visible() and "Cut it away" in pg.inner_text("#toolpop")
    pg.click("#toolpop >> text=Cancel")
    assert not pg.locator("#shapepanel").is_visible() and pg.locator("#board [data-shape]").count() == 0
    pg.click("#pshape")
    pg.click("#toolpop >> text=Cut it away")
    pg.wait_for_function("pieceBy('a') && pieceBy('a').edges.some(e => e.name === 'cut')", timeout=30000)
    names = pg.evaluate("pieceBy('a').edges.map(e => e.name)")
    assert {"bottom", "right", "left"} <= set(names) and "top_1" in names        # a scoop out of the top
    assert pg.evaluate(f"{ST}.ST.design.seams.some(s => s.a === 'a.right')")      # its seam is still there
    assert not pg.locator("#shapepanel").is_visible() and not pg.locator("#toolpop").is_visible()
    assert not pg.errors, pg.errors


def test_layer_copy_and_join_along_a_seam(page):
    pg = page
    _two_rects(pg)
    pg.click('#pattern [data-body="a"]')
    pg.wait_for_timeout(300)
    pg.click("#playercopy")
    pg.check('[name=lcwho][value=all]')
    pg.click("#lcok")
    pg.wait_for_function("pieceBy('a_over') && pieceBy('b_over')", timeout=30000)
    pl = pg.evaluate("JSON.parse(JSON.stringify(pieceBy('a_over').place))")
    assert pl["layer"] == 1 and pl["layer_of"] == "a"
    assert pg.evaluate(f"{ST}.ST.design.seams.some(s => s.a === 'a_over.right' && s.b === 'b_over.left')")
    pg.evaluate(f"{ST}.DS.sel = 'a'; renderInspector()")
    pg.click('#inspector [data-join]')
    pg.wait_for_function("!pieceBy('b')", timeout=30000)
    assert abs(pg.evaluate("bboxV(pieceBy('a'))[2] - bboxV(pieceBy('a'))[0]") - 80) < 0.1
    assert not pg.errors, pg.errors


def test_file_window_saves_and_opens_a_drape_file(page, tmp_path):
    pg = page
    pg.evaluate("window.showSaveFilePicker = undefined; window.showOpenFilePicker = undefined")   # no system window here: download
    pg.click("#fileBtn")
    assert pg.locator("#fwSave").is_visible()
    pg.fill("#fwName", "Tulle skirt")
    with pg.expect_download() as dl:
        pg.click("#fwSave")
    f = dl.value
    assert f.suggested_filename == "Tulle skirt.drape"
    path = tmp_path / f.suggested_filename
    f.save_as(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format"] == "drape-project" and data["name"] == "Tulle skirt"
    assert data["version"] == 2 and len(data["garments"]) == 1          # project file version 2
    g0 = data["garments"][0]
    assert g0["scratch"] and g0["layer"] == 1 and g0["visible"] and not g0["frozen"]
    assert {p["name"] for p in g0["design"]["pieces"]} >= {"a", "a_over"}
    data["name"] = "Reopened"
    g0["design"]["pieces"] = [p for p in g0["design"]["pieces"] if p["name"] != "a_over"]
    g0["design"]["seams"] = [s for s in g0["design"]["seams"] if "a_over" not in s["a"] + s["b"]]
    path.write_text(json.dumps(data), encoding="utf-8")
    pg.set_input_files("#openproj", str(path))
    pg.wait_for_function(f"{ST}.ST.name === 'Reopened'", timeout=180000)
    assert pg.evaluate("!pieceBy('a_over') && !!pieceBy('a')")
    assert not pg.errors, pg.errors


def test_hood_tapped_from_the_back_opens_at_the_centre_front(page):
    pg = page
    _ensure_avatar(pg)
    _go_garment(pg, "tee")
    _convert(pg, "front")
    pg.click('#bands [data-b="hood"]')
    assert "any order" in pg.inner_text("#toolpop")
    pg.evaluate(f"{ST}.DS.loop = ['back.neck', 'front.neck']; finishBand()")
    pg.wait_for_function("window.__studio.ST.design.pieces.some(p => p.name === 'hood')", timeout=60000)
    loop = pg.evaluate("JSON.parse(JSON.stringify(pieceBy('hood').place.loop))")
    assert loop == ["front.neck_2", "back.neck", "front.neck_1"]
    assert not pg.errors, pg.errors


@pytest.fixture(scope="module")
def gpu_page(server, page):
    """A browser with the real GPU (WebGPU) for live mode; the others use software GL.
    Launched through the same Playwright as `page` (a second one can't start)."""
    try:
        b = page.context.browser.browser_type.launch(executable_path=_chrome(), args=["--enable-unsafe-webgpu", "--enable-gpu"])
    except Exception as e:
        pytest.skip(f"no browser: {e}")
    pg = b.new_page(viewport={"width": 1400, "height": 900})
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("dialog", lambda d: d.accept())
    pg.goto(server)
    pg.evaluate("localStorage.clear()")
    pg.reload()
    _started(pg)
    pg.wait_for_timeout(400)
    pg.click("#mode [data-m=adv]")         # every tool shows (as on `page`)
    yield pg
    b.close()


# mesh edges passing through triangles (live never welds: an edge crossing its seam partner's
# piece right at the seam is the seam, not a tangle, so triangles at a seam partner are skipped)
# Edges passing through triangles. Not counted: a triangle with a corner in the edge's seam
# group (points sewn together through any chain of seams; live mode never welds them). Where
# four pieces meet under the arm, an edge end and a triangle corner are one sewn point 0.03 mm
# apart without being direct partners, and their touch read as a crossing.
_CROSSINGS = """() => { const s = LIVE.sim, X = s.out, T = window.__tris, nt = T.length / 3, P = window.__part, n0 = s.n;
    const par = Int32Array.from({length: n0}, (_, i) => i), f = a => { while (par[a] !== a) { par[a] = par[par[a]]; a = par[a] } return a };
    for (let i = 0; i < n0; i++) for (let q = 0; q < 3; q++) if (P[3*i+q] >= 0) { const a = f(i), b = f(P[3*i+q]); if (a !== b) par[Math.max(a, b)] = Math.min(a, b) }
    const g = Int32Array.from({length: n0}, (_, i) => f(i));
    const v = i => [X[3*i], X[3*i+1], X[3*i+2]], sub = (a, b) => [a[0]-b[0], a[1]-b[1], a[2]-b[2]];
    const cr = (a, b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]], dot = (a, b) => a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
    const edges = new Set(); for (let t = 0; t < nt; t++) for (let q = 0; q < 3; q++) { const a = T[3*t+q], b = T[3*t+(q+1)%3]; edges.add(a < b ? a * 1e6 + b : b * 1e6 + a) }
    let n = 0, raw = 0;
    for (const code of edges) { const a = Math.floor(code / 1e6), b = code % 1e6, o = v(a), d = sub(v(b), o);
      const ga = g[a], gb = g[b], near = q => g[q] === ga || g[q] === gb;
      for (let t = 0; t < nt; t++) { const i = T[3*t], j = T[3*t+1], k = T[3*t+2]; if (i === a || j === a || k === a || i === b || j === b || k === b) continue;
        const A = v(i), e1 = sub(v(j), A), e2 = sub(v(k), A), pv = cr(d, e2), det = dot(e1, pv); if (Math.abs(det) < 1e-14) continue;
        const tv = sub(o, A), u = dot(tv, pv) / det; if (u < 0 || u > 1) continue; const qv = cr(tv, e1), w = dot(d, qv) / det; if (w < 0 || u + w > 1) continue;
        const tt = dot(e2, qv) / det; if (tt >= 0 && tt <= 1) { raw++; if (!near(i) && !near(j) && !near(k)) n++ } } }
    return {crossings: n, raw} }"""


def test_live_yank_raises_substeps_and_cloth_stays_untangled(gpu_page):
    """Live mode on a tee, a 40 cm yank in 2 frames: substeps go up during it and back
    to the base after, positions stay finite and no edge passes through a triangle.
    Needs WebGPU (DRAPE_CHROME = an installed Chrome on Windows): skipped without it."""
    pg = gpu_page
    _ensure_avatar(pg)
    pg.evaluate("LIVE.sim && stopLive(); 0")
    _go_garment(pg, "tee")
    pg.evaluate(f"{ST}.go('preview')")
    pg.wait_for_timeout(300)
    pg.evaluate("""() => { const a0 = api; window.api = async (path, body) => { const s = await a0(path, body);
        if (path === '/api/live') { const b = atob(s.tris), u = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i);
          window.__tris = new Uint32Array(u.buffer); window.__pid = s.panel_id;
          const pb = atob(s.partners), pu = new Uint8Array(pb.length); for (let i = 0; i < pb.length; i++) pu[i] = pb.charCodeAt(i);
          window.__part = new Int32Array(pu.buffer) } return s } }""")
    if not pg.is_visible("#liveBtn"):          # hidden: no GPU the solver can use here
        pytest.skip("no WebGPU here (the Live button is hidden)")
    pg.click("#liveBtn")
    try:
        pg.wait_for_function("(LIVE.sim && LIVE.sim.time > 0.05) || /couldn't start|needs a browser/.test(document.querySelector('.toast')?.innerText || '')", timeout=120000)
    except Exception:
        pytest.skip("live mode didn't start")
    if not pg.evaluate("!!LIVE.sim"):
        pytest.skip("no WebGPU here: " + pg.inner_text(".toast"))
    pg.evaluate("LIVE.run = false; 0")
    pg.wait_for_function("!LIVE.sim.busy", timeout=10000)      # the preview loop's last step
    pg.evaluate("""async () => { while (LIVE.sim.time < 2 && !LIVE.sim.lost)                 // sewn and settled
        if (!(await LIVE.sim.step(1))) await new Promise(r => setTimeout(r, 5)) }""")
    before = pg.evaluate(_CROSSINGS)
    r = pg.evaluate("""async () => { const s = LIVE.sim, X = s.out; let k = 0, best = -1e9;
        for (let i = 0; i < s.n; i++) if (X[3*i+2] > best) { best = X[3*i+2]; k = i }      // the front-most point
        const p0 = [X[3*k], X[3*k+1], X[3*k+2]], subs = [];
        for (let f = 1; f <= 120; f++) {
          if (f <= 2) s.setGrab(k, [p0[0], p0[1], p0[2] + 0.20 * f]); else if (f === 3) s.setGrab(-1);
          await s.step(1); subs.push(s.substeps) }
        return {subs, finite: Array.from(s.out).every(Number.isFinite), base: s.base, peak: s.substepsMax} }""")
    assert r["finite"]
    assert max(r["subs"][:10]) > r["base"]                       # the yank raised the substeps...
    assert all(s == r["base"] for s in r["subs"][70:])           # ...and they're back to the base within ~1 s
    after = pg.evaluate(_CROSSINGS)
    print("crossings before / after the yank:", before, after)
    assert after["crossings"] <= before["crossings"], (before, after)   # the yank tangled nothing
    assert not pg.errors, pg.errors


def test_tool_popup_shows_done_and_cancel_on_the_board(page):
    pg = page
    _ensure_avatar(pg)
    _go_garment(pg, "tee")
    _convert(pg, "front")
    pg.click('#bands [data-b="neckband"]')
    pop = pg.locator("#toolpop")
    assert pop.is_visible() and "Neckband" in pop.inner_text()
    pat, box = pg.locator("#patcard").bounding_box(), pop.bounding_box()
    assert pat["x"] <= box["x"] and box["x"] + box["width"] <= pat["x"] + pat["width"]     # on the pattern board
    assert pg.locator("#toolpop button:has-text('Done')").is_disabled()                    # nothing picked yet
    pg.evaluate(f"{ST}.DS.loop = ['front.neck']; toolHint()")
    assert pg.locator("#toolpop button:has-text('Done')").is_enabled() and "1 picked" in pop.inner_text()
    pg.keyboard.press("Escape")                                                             # Esc cancels
    assert not pop.is_visible() and pg.evaluate(f"{ST}.DS.tool") == "select"
    pg.click("#tool [data-t=sew]")
    assert pop.is_visible() and "Sew" in pop.inner_text()
    pg.click("#toolpop button:has-text('Done')")
    assert not pop.is_visible() and pg.evaluate(f"{ST}.DS.tool") == "select"
    assert not pg.errors, pg.errors


def test_hem_tool_cuts_the_turn_up_on(page):
    pg = page
    _ensure_avatar(pg)
    _two_rects(pg)
    i = pg.evaluate("pieceBy('a').edges.findIndex(e => e.name === 'bottom')")
    if not pg.evaluate("document.body.classList.contains('advanced')"):
        pg.click("#mode [data-m=adv]")
    pg.evaluate(f"{ST}.ST.scratch = true; {ST}.go('fit'); tidy(); dsChanged(true, true)")
    pg.wait_for_timeout(600)
    pg.click('#edgetools [data-et="hem"]')                                                  # the Hem tool, then the edge
    pg.click('#toolpop [data-hs="blind"]')
    assert pg.input_value('#toolpop [data-eo="depth"]') in ("4.0", "1.57")                   # the style's default (cm / in)
    _click_edge(pg, "a", "bottom")
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(300)
    hem = pg.evaluate("JSON.parse(JSON.stringify(pieceBy('a').edges.find(e => e.name === 'bottom').hem))")
    assert hem["style"] == "blind" and abs(hem["depth_cm"] - 4) < 0.01 and abs(hem["turn_cm"] - 1) < 0.01
    assert pg.locator("#board polyline title:has-text('hem turn-up')").count() == 1         # drawn beyond the edge
    assert pg.locator(f'#inspector [data-hem="{i}"]').inner_text().startswith("hem")
    assert not pg.errors, pg.errors


def test_cut_tool_has_two_draggable_dots_on_the_outline(page):
    pg = page
    _two_rects(pg)
    pg.click('#pattern [data-body="a"]')
    pg.wait_for_timeout(300)
    pg.click("#cutBtn")
    assert pg.locator("#board [data-cuth]").count() == 2 and pg.locator("#board line[stroke='#d6453d']").count() == 1
    assert pg.locator("#toolpop button:has-text('Cut here')").is_enabled() and "40.0 cm long" in pg.inner_text("#toolpop")
    before = pg.evaluate(f"JSON.parse(JSON.stringify({ST}.DS.cut))")
    _drag(pg, '#board [data-cuth="0"]', 0, -60)                                      # slide the left dot down its edge
    after = pg.evaluate(f"JSON.parse(JSON.stringify({ST}.DS.cut))")
    assert after[0] != before[0] and after[0][2] < 0.5                                 # moved, and still on the outline
    assert after[1] == before[1]
    pg.click("#toolpop button:has-text('Cut here')")
    pg.wait_for_timeout(800)
    names = pg.evaluate(f"{ST}.ST.design.pieces.map(p => p.name)")
    assert "a_a" in names and "a_b" in names and pg.evaluate(f"{ST}.DS.tool") == "select"
    assert pg.evaluate(f"{ST}.ST.design.seams.some(s => s.a === 'a_a.cut' && s.b === 'a_b.cut')")
    assert not pg.errors, pg.errors


def test_rename_footer_next_button_and_saved_app_stamp(page, server, tmp_path):
    """RENAME_SPEC: the footer's links open their pages; the body step ends in a big Next
    button; a saved project says which app made it, and one without that still opens."""
    pg = page
    links = pg.evaluate("[...document.querySelectorAll('#siteFooter a')].map(a => [a.textContent, a.getAttribute('href')])")
    assert links == [["Terms", "/terms"], ["Privacy", "/privacy"], ["Source code", "https://github.com/spunfectionLLC/Drape"],
                     ["Report a bug", "https://docs.google.com/forms/d/1UtgLtItux0It6J0uolu7vAvpvrKTFt9J8RHhd3S5SeY/viewform"]]
    for _, href in links[:2]:                                    # the pages served here (the others are GitHub)
        r = pg.request.get(pg.url.split("#")[0].rstrip("/") + href)
        assert r.ok and "Spunfection Studio" in r.text()
    _ensure_avatar(pg)
    pg.click("#steps button[data-k=body]")
    b = pg.locator("#toGarment")
    assert b.is_visible() and b.evaluate("e => e.tagName") == "BUTTON"
    box = b.bounding_box()
    assert box["height"] >= 40 and box["width"] >= 250           # a big button, not a text link
    b.click()
    assert pg.evaluate(f"{ST}.ST.step") == "garment"
    pg.evaluate("window.showSaveFilePicker = undefined; window.showOpenFilePicker = undefined")
    pg.click("#fileBtn")
    pg.fill("#fwName", "Stamped")
    with pg.expect_download() as dl:
        pg.click("#fwSave")
    path = tmp_path / "s.drape"
    dl.value.save_as(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["app"] == "Spunfection Studio" and data["format"] == "drape-project"
    for k in ("app", "app_version"):                              # an older file: no app stamp
        data.pop(k, None)
    data["name"] = "Old file"
    path.write_text(json.dumps(data), encoding="utf-8")
    pg.set_input_files("#openproj", str(path))
    pg.wait_for_function(f"{ST}.ST.name === 'Old file'", timeout=180000)
    assert not pg.errors, pg.errors


def test_new_project_warns_to_save_and_keeps_the_measurements(page, server):
    """New (top bar): a warning to save first, Cancel keeps everything, Start new clears the
    garment and design but keeps the measurements. Its own browser context: it reloads."""
    ctx = page.context.browser.new_context(viewport={"width": 1400, "height": 900})
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(server)
    pg.wait_for_function(f"{ST} && {ST}.ST.init", timeout=60000)
    pg.evaluate(f"{ST}.ST.meas = Object.assign({{}}, {ST}.ST.meas, {{height: 171}}); {ST}.ST.block = 'tee'; autosave()")
    nb = pg.locator("#newBtn")
    assert nb.is_visible() and "New" in nb.inner_text()
    nb.click()
    assert "Start a new project?" in pg.inner_text("#mtitle")
    body = pg.inner_text("#mbody")
    assert "Save first?" in body and "will be lost" in body and "measurements stay" in body
    assert pg.locator("#nwSave").is_visible() and pg.locator("#nwGo").is_visible()
    pg.click("#nwCancel")
    assert not pg.locator("#modal.show").count() and pg.evaluate(f"{ST}.ST.block") == "tee"
    nb.click()
    with pg.expect_navigation():
        pg.click("#nwGo")
    pg.wait_for_function(f"{ST} && {ST}.ST.init", timeout=60000)
    assert pg.evaluate(f"{ST}.ST.block") is None and pg.evaluate(f"{ST}.ST.design.pieces.length") == 0
    assert pg.evaluate(f"{ST}.ST.meas.height") == 171
    assert not errors, errors
    ctx.close()


def test_alpha_notice_from_the_badge(page):
    pg = page
    assert pg.locator("#alphaBtn").is_visible() and pg.inner_text("#alphaBtn").startswith("ALPHA v1.")
    pg.click("#alphaBtn")
    assert pg.locator("#modal").is_visible() and "Spunfection Studio is in alpha" in pg.inner_text("#mtitle")
    assert "Save often" in pg.inner_text("#mbody")
    pg.click("#alphaOk")
    assert not pg.locator("#modal.show").count()
    assert pg.evaluate("localStorage.getItem('drape.alphaSeen') || JSON.stringify(LS.get('alphaSeen', ''))") not in ("", '""', None)
    assert not pg.errors, pg.errors


def _tee_with_hood(pg):
    _ensure_avatar(pg)
    _go_garment(pg, "tee")
    _convert(pg, "front")
    pg.click('#bands [data-b="hood"]')
    pg.evaluate(f"{ST}.DS.loop = ['front.neck', 'back.neck']; finishBand()")
    pg.wait_for_function("window.__studio.ST.design.pieces.some(p => p.name === 'hood')", timeout=60000)


def test_sewing_order_shown_and_set_in_advanced_mode(page):
    """Staged sewing: the piece panel (Advanced) has a sewing order (1 / 2 / 3 / auto,
    auto showing the computed stage) and a role; seams say which stage they're sewn in."""
    pg = page
    _tee_with_hood(pg)
    pg.wait_for_function(f"{ST}.DS.resp && {ST}.DS.resp.stages && {ST}.DS.resp.stages.piece.hood === 2", timeout=60000)
    assert pg.evaluate(f"{ST}.ST.design.pieces.find(p => p.name === 'hood').role") == "hood"
    pg.click("#mode button[data-m=adv]")
    pg.evaluate(f"{ST}.DS.sel = 'hood'; renderInspector(); renderDsSeams(); 0")
    assert "Sews in stage 2" in pg.inner_text("#inspector")
    auto = pg.locator('#inspector [data-pstage="auto"]')
    assert auto.count() == 1 and "(2)" in auto.inner_text() and "on" in auto.get_attribute("class")
    assert pg.locator("#prole").input_value() == "hood"
    assert "Sews in stage 2" in pg.inner_text("#dsSeams")
    pg.evaluate("document.querySelector('#inspector [data-pstage=\"1\"]').click()")
    assert pg.evaluate(f"{ST}.ST.design.pieces.find(p => p.name === 'hood').stage") == 1
    pg.wait_for_function(f"{ST}.DS.resp.stages.piece.hood === 1", timeout=60000)
    pg.evaluate("document.querySelector('#inspector [data-pstage=\"auto\"]').click()")
    assert pg.evaluate(f"{ST}.ST.design.pieces.find(p => p.name === 'hood').stage") is None
    pg.select_option("#prole", "body")               # a role changes the automatic stage
    pg.wait_for_function(f"{ST}.DS.resp.stages.piece.hood === 1 && {ST}.ST.design.pieces.find(p => p.name === 'hood').role === 'body'", timeout=60000)
    pg.click("#mode button[data-m=adv]")      # back to the mode these tests run in
    assert not pg.errors, pg.errors


def test_live_hood_waits_frozen_then_sews_on(gpu_page):
    """Live mode, tee + hood: the hood stays still until its stage (~1.6 s), the HUD names
    the stage, positions stay finite, and the shirt's neckline stays put when it's sewn on.
    Needs WebGPU: skipped without it."""
    pg = gpu_page
    pg.evaluate("LIVE.sim && stopLive(); 0")
    _tee_with_hood(pg)
    pg.evaluate(f"{ST}.go('preview')")
    pg.wait_for_timeout(300)
    if not pg.is_visible("#liveBtn"):          # hidden: no GPU the solver can use here
        pytest.skip("no WebGPU here (the Live button is hidden)")
    pg.click("#liveBtn")
    try:
        pg.wait_for_function("(LIVE.sim && LIVE.sim.time > 0.05) || /couldn't start|needs a browser/.test(document.querySelector('.toast')?.innerText || '')", timeout=120000)
    except Exception:
        pytest.skip("live mode didn't start")
    if not pg.evaluate("!!LIVE.sim"):
        pytest.skip("no WebGPU here: " + pg.inner_text(".toast"))
    pg.evaluate("LIVE.run = false; 0")
    pg.wait_for_function("!LIVE.sim.busy", timeout=10000)
    pg.evaluate("LIVE.sim.reset(); 0")
    r = pg.evaluate("""async () => { const s = LIVE.sim, hood = [], top = [];
        for (let i = 0; i < s.n; i++) if (s.vstage[i] === 2) hood.push(i);
        const y = []; for (let i = 0; i < s.n; i++) if (s.vstage[i] === 1) y.push([s.out[3*i+1], i]);
        y.sort((a, b) => b[0] - a[0]); for (let k = 0; k < Math.max(20, y.length * 0.02); k++) top.push(y[k][1]);
        const at = () => hood.map(i => [s.out[3*i], s.out[3*i+1], s.out[3*i+2]]);
        const neck = () => top.reduce((a, i) => a + s.out[3*i+1], 0) / top.length;
        const h0 = at(); let hudMid = '', still = true, labels = new Set(), moved = 0, n0 = 0, f = 0;
        while (s.time < 5.0 && f < 400) { if (!(await s.step(1))) { if (s.lost) break; await new Promise(r => setTimeout(r, 5)); continue }   // busy: the preview loop was mid-step
          f++; labels.add(s.phase()[2]);
          if (s.time < 1.55) { const h = at(); for (let k = 0; k < h.length; k++) for (let q = 0; q < 3; q++) if (h[k][q] !== h0[k][q]) still = false }
          if (!n0 && s.time >= 1.55) n0 = neck()
          if (!hudMid && s.time >= 1.8) { liveStatus(); hudMid = document.querySelector('#liveBar').innerText } }
        const h = at(); for (let k = 0; k < h.length; k++) moved = Math.max(moved, Math.hypot(h[k][0]-h0[k][0], h[k][1]-h0[k][1], h[k][2]-h0[k][2]));
        liveStatus();
        return {frames: f, n: s.nStages, still, moved, labels: [...labels], rise: neck() - n0, finite: Array.from(s.out).every(Number.isFinite),
                hud: hudMid, nh: hood.length, st: s.stage, wz: s.Wd.filter(v => v === 0).length, t: s.time, lost: s.lost, busy: s.busy} }""")
    assert r["n"] == 2 and r["frames"] >= 300 and r["finite"]
    assert r["still"] and r["moved"] > 0.01, json.dumps({k: v for k, v in r.items() if k != "labels"})   # frozen until its stage, then sewn on
    assert {"Sewing the body", "Settling", "Attaching hood", "Draping"} <= set(r["labels"])
    assert "Attaching hood" in r["hud"] and "stage 2 of 2" in r["hud"]
    assert abs(r["rise"]) < 0.015                                         # m: the neckline stays put
    assert not pg.errors, pg.errors


def test_live_springs_drapes_a_tee_on_the_gpu(gpu_page):
    """The springs solver on the GPU (live_springs.js): a tee sews,
    settles and holds, as springs.py does; it follows a pull with the mouse and lets go.
    Needs WebGPU: skipped without it."""
    pg = gpu_page
    _ensure_avatar(pg)
    pg.evaluate("LIVE.sim && stopLive(); 0")
    if not pg.evaluate("(async () => !!(window.LiveSprings && await LiveSprings.supported()))()"):
        pytest.skip("no WebGPU here")
    r = pg.evaluate(f"""async () => {{
        const setup = await api('/api/live', {{avatar: {ST}.ST.avatar.id, block: 'tee', choices: {{}}, params: {{}}, fabric: 'jersey'}});
        const sim = await new LiveSprings().init(setup), SP = setup.springs;
        const b64u = s => {{ const b = atob(s), u = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return u.buffer }};
        const topo = new Uint32Array(b64u(SP.topo)), par = new Float32Array(b64u(SP.param));
        while (sim.time < 2.5) if (!(await sim.step(1))) return {{error: 'step failed'}};
        const X = sim.out, d = (i, j) => Math.hypot(X[3*i] - X[3*j], X[3*i+1] - X[3*j+1], X[3*i+2] - X[3*j+2]);
        const strain = [];
        for (let e = 0; e < SP.ne; e++) {{ const rest = par[SP.poff.spr + 8 * e]; strain.push(Math.abs(d(topo[SP.toff.spr + 2*e], topo[SP.toff.spr + 2*e+1]) - rest) / rest) }}
        strain.sort((a, b) => a - b);
        let gap = 0; for (let e = SP.ne; e < SP.ns; e++) if (par[SP.poff.spr + 8 * e + 4] === 1) gap = Math.max(gap, d(topo[SP.toff.spr + 2*e], topo[SP.toff.spr + 2*e+1]));
        const settled = sim.vMeasured;
        let k = 0, best = -1e9; for (let i = 0; i < sim.n; i++) if (X[3*i+2] > best) {{ best = X[3*i+2]; k = i }}
        const p0 = [X[3*k], X[3*k+1], X[3*k+2]];
        for (let f = 0; f < 10; f++) {{ sim.setGrab(k, [p0[0], p0[1], p0[2] + 0.10]); await sim.step(1) }}
        const pulled = sim.out[3*k+2] - p0[2];
        sim.setGrab(-1); for (let f = 0; f < 45; f++) await sim.step(1);
        const back = sim.out[3*k+2] - p0[2];
        sim.destroy();
        return {{cls: sim.constructor.name, finite: Array.from(sim.out).every(Number.isFinite), p99: strain[Math.floor(0.99 * strain.length)],
                 gap, settled, pulled, back, cg: sim.cgIters}} }}""")
    assert "error" not in r, r
    assert r["cls"] == "LiveSprings" and r["finite"], r
    assert r["p99"] < 0.05, r                 # strain p99 under 5% (springs.py: 2.3% on the bench tee)
    assert r["gap"] < 0.003, r                # m: the seams closed
    assert r["settled"] < 0.15, r             # m/s: the fastest point once settled
    assert 0.05 < r["pulled"] < 0.12, r       # the mouse spring moves the cloth most of the 10 cm...
    assert r["back"] < 0.5 * r["pulled"], r   # ...and it falls back when let go
    assert not pg.errors, pg.errors


def test_switched_off_bands_are_hidden_but_hoods_stay(page, server):
    """Feature switches (drape/features.py): with OPENING_BANDS off, as a build sends it in
    /api/init, "Finish an opening" offers only the hood, and a band can't be made from the
    editor even if asked for (a chip left over from before)."""
    pg = page.context.browser.new_page(viewport={"width": 1600, "height": 1000})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("dialog", lambda d: d.accept())

    def init(route):
        r = route.fetch()
        j = r.json()
        j["features"]["OPENING_BANDS"] = False
        route.fulfill(response=r, json=j)
    pg.route("**/api/init", init)
    try:
        pg.goto(server)
        pg.evaluate("localStorage.clear()")
        pg.reload()
        _started(pg)
        pg.wait_for_timeout(400)
        _ensure_avatar(pg)
        _go_garment(pg, "tee")
        _convert(pg, "front")
        chips = pg.evaluate("[...document.querySelectorAll('#bands [data-b]')].map(b => b.dataset.b)")
        assert chips == ["hood"], chips
        n = pg.evaluate(f"{ST}.ST.design.pieces.length")
        pg.evaluate("DS.loopKind = 'neckband'; DS.loop = ['front.neck', 'back.neck']; finishBand()")
        pg.wait_for_timeout(800)
        assert pg.evaluate(f"{ST}.ST.design.pieces.length") == n
        assert "not available in this build" in pg.locator("#toast").inner_text()
        assert not errors, errors
    finally:
        pg.close()


def test_pocket_tools_preview_before_they_add(page):
    """In-seam and front hip pockets are drawn dashed on the pattern while their form is open; the
    design only changes on 'Add the pocket'."""
    pg = page
    _ensure_avatar(pg)
    _go_garment(pg, "a_line_skirt")
    _convert(pg, "front")
    n0 = pg.evaluate(f"{ST}.ST.design.pieces.length")
    pg.click("#pinseam")
    pg.wait_for_function("document.querySelectorAll('#board .ghost').length > 0", timeout=120000)
    assert "Preview" in pg.inner_text("#pvmsg") and pg.evaluate(f"{ST}.ST.design.pieces.length") == n0
    pg.click("text=Cancel")
    assert pg.evaluate("document.querySelectorAll('#board .ghost').length") == 0
    pg.click("#pinseam")
    pg.wait_for_function("document.querySelectorAll('#board .ghost').length > 0", timeout=120000)
    pg.click("#isok")
    pg.wait_for_function(f"{ST}.ST.design.pieces.length > {n0}", timeout=120000)
    assert pg.evaluate("document.querySelectorAll('#board .ghost').length") == 0
    assert not pg.errors, pg.errors


@pytest.mark.slow
def test_sleeve_tool_drafts_sleeves_for_the_clicked_armholes(page):
    """The Sleeve tool: click the front armhole edge, then the back one; a sleeve drafted to fit is sewn in. With
    Symmetric on the other arm gets one too; with it off, just the one clicked."""
    pg = page
    _ensure_avatar(pg)
    _go_garment(pg, "tee")
    _convert(pg, "front")
    if not pg.evaluate("document.body.classList.contains('advanced')"):
        pg.click("#mode [data-m=adv]")
    strip = f"""(() => {{ const d = {ST}.ST.design; d.pieces = d.pieces.filter(p => !p.name.startsWith('sleeve'));
        d.seams = d.seams.filter(s => !(s.a + s.b).includes('sleeve')); tidy(); dsChanged(true, true) }})()"""
    for sym, want in ((True, 2), (False, 1)):
        pg.evaluate(strip)
        pg.wait_for_timeout(600)
        if pg.evaluate(f"{ST}.DS.sym") != sym:
            pg.click("#symBtn")
        pg.click('#edgetools [data-et="sleeve"]')
        assert "front armhole" in pg.inner_text("#toolpop")
        pg.click('#toolpop [data-sl="length:long"]')
        _click_edge(pg, "front", "arm_r")
        assert "back armhole" in pg.inner_text("#toolpop")
        _click_edge(pg, "back", "arm_l")
        pg.wait_for_function(f"{ST}.ST.design.pieces.filter(p => p.name.startsWith('sleeve')).length === {want}", timeout=30000)
        pg.keyboard.press("Escape")
        sl = pg.evaluate(f"JSON.parse(JSON.stringify({ST}.ST.design.pieces.filter(p => p.name.startsWith('sleeve')).map(p => [p.name, p.place])))")
        assert all(p["wrist"] for _, p in sl) and sorted(p["arm"] for _, p in sl) == ([-1, 1] if sym else [1])
        seams = pg.evaluate(f"{ST}.ST.design.seams.filter(s => s.a.startsWith('sleeve')).map(s => s.a + '>' + s.b)")
        assert "sleeve_r.cap_r>front.arm_r" in seams and "sleeve_r.cap_l>back.arm_l" in seams
        assert ("sleeve_l.cap_r>front.arm_l" in seams) == sym
    assert not pg.errors, pg.errors


def test_curve_handles_symmetric_curve_and_straighten(page):
    """Click an edge's curve dot: two handles (direction and strength at each end) to drag. Right-click it:
    Symmetric curve (both ends alike) and Straighten. A drawn curve (a pattern's armhole) becomes one cubic."""
    pg = page
    _ensure_avatar(pg)
    _two_rects(pg)
    if not pg.evaluate("document.body.classList.contains('advanced')"):
        pg.click("#mode [data-m=adv]")
    pg.evaluate(f"{ST}.ST.scratch = true; {ST}.go('fit'); tidy(); dsChanged(true, true)")
    pg.wait_for_timeout(600)
    if pg.evaluate(f"{ST}.DS.sym"):
        pg.click("#symBtn")
    pg.click('#pattern [data-body="a"]')
    pg.wait_for_timeout(300)
    E = "JSON.parse(JSON.stringify(pieceBy('a').edges.find(e => e.name === 'top')))"
    i = pg.evaluate("pieceBy('a').edges.findIndex(e => e.name === 'top')")
    dot = f'#board [data-mid="{i}"]'
    pg.click(dot)                                                         # a click: the handles show, nothing changes
    assert pg.locator("#board [data-hnd]").count() == 2 and not pg.evaluate(E)["c1"]
    _drag(pg, '#board [data-hnd="0"]', 0, -40)                            # pull the first handle up
    e = pg.evaluate(E)
    assert e["c1"] and e["c2"] and abs(e["c1"][1] - e["c2"][1]) > 3        # only that end bends
    # right-click: symmetric curve -> both ends alike (mirrored across the edge's middle)
    box = pg.locator(dot).bounding_box()
    pg.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, button="right")
    assert pg.locator(".curvemenu").is_visible()
    pg.click(".curvemenu [data-c=sym]")
    pg.wait_for_timeout(600)
    e = pg.evaluate(E)
    mid = pg.evaluate("(() => { const P = pieceBy('a'), i = P.edges.findIndex(e => e.name === 'top'), a = P.verts[i], b = P.verts[(i + 1) % P.verts.length]; return (a[0] + b[0]) / 2 })()")
    assert e["symc"] and abs(e["c1"][1] - e["c2"][1]) < 0.01 and abs((e["c1"][0] + e["c2"][0]) / 2 - mid) < 0.01
    _drag(pg, '#board [data-hnd="1"]', 0, 30)                             # dragging one moves the other the same way
    e = pg.evaluate(E)
    assert abs(e["c1"][1] - e["c2"][1]) < 0.01
    box = pg.locator(dot).bounding_box()
    pg.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, button="right")
    pg.click(".curvemenu [data-c=straight]")
    pg.wait_for_timeout(600)
    e = pg.evaluate(E)
    assert not e["c1"] and not e.get("pts") and not e.get("symc")
    # a drawn curve (points, as a pattern's armhole is) gets handles fitted to it, and dragging the dot keeps it smooth
    pg.evaluate("""(() => { const P = pieceBy('a'), i = P.edges.findIndex(e => e.name === 'top'), a = P.verts[i], b = P.verts[(i + 1) % P.verts.length];
        P.edges[i].pts = Array.from({length: 25}, (_, k) => { const t = k / 24; return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t + 6 * Math.sin(Math.PI * t)] }); P.shape = {type: 'custom'}; dsChanged(true) })()""")
    pg.wait_for_timeout(600)
    pg.click('#pattern [data-body="a"]')
    pg.click(dot)
    assert pg.locator("#board [data-hnd]").count() == 2
    _drag(pg, dot, 0, -20)
    e = pg.evaluate(E)
    assert e["c1"] and not e.get("pts")
    assert not pg.errors, pg.errors


def test_pick_several_corners_and_move_them_together(page):
    """Shift-click corners (or shift-drag a box round them), then drag one: they all move. Arrow keys nudge them,
    Esc lets go."""
    pg = page
    _ensure_avatar(pg)
    _two_rects(pg)
    if not pg.evaluate("document.body.classList.contains('advanced')"):
        pg.click("#mode [data-m=adv]")
    pg.evaluate(f"{ST}.ST.scratch = true; {ST}.go('fit'); tidy(); dsChanged(true, true)")
    pg.wait_for_timeout(600)
    if pg.evaluate(f"{ST}.DS.sym"):
        pg.click("#symBtn")
    pg.evaluate(f"{ST}.DS.sel = 'a'; renderInspector(); drawDesign()")      # (a toast from the test before can cover the piece)
    pg.wait_for_timeout(300)
    V = "JSON.parse(JSON.stringify(pieceBy('a').verts))"
    v0 = pg.evaluate(V)
    top = [i for i, v in enumerate(v0) if v[1] > max(q[1] for q in v0) - 0.01]          # the two top corners
    assert len(top) == 2
    def shift_click(i):          # plain mouse events: a click on a corner redraws the board (no hit-target check)
        bb = pg.locator(f'#board [data-vert="{i}"]').bounding_box()
        pg.keyboard.down("Shift"); pg.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2); pg.keyboard.up("Shift")
        pg.wait_for_timeout(200)
    shift_click(top[0])
    shift_click(top[1])
    assert sorted(pg.evaluate(f"{ST}.DS.vsel.ids")) == sorted(top) and pg.locator("#board .vpicked").count() == 2
    box = pg.locator(f'#board [data-vert="{top[0]}"]').bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    pg.mouse.move(x, y); pg.mouse.down(); pg.mouse.move(x, y - 40, steps=6); pg.mouse.up()
    pg.wait_for_timeout(600)
    v1 = pg.evaluate(V)
    dy = [v1[i][1] - v0[i][1] for i in top]
    assert dy[0] > 1 and abs(dy[0] - dy[1]) < 1e-6                                       # both up by the same
    assert all(v1[i] == v0[i] for i in range(len(v0)) if i not in top)                    # the others stayed
    pg.keyboard.press("ArrowRight")                                                       # a nudge: 0.5 cm
    pg.wait_for_timeout(300)
    v2 = pg.evaluate(V)
    assert all(abs(v2[i][0] - v1[i][0] - 0.5) < 1e-6 for i in top)
    pg.keyboard.press("Escape")
    assert not pg.evaluate(f"{ST}.DS.vsel")
    # a box round the bottom two corners picks them
    bot = [i for i in range(len(v2)) if i not in top]
    pts = [pg.locator(f'#board [data-vert="{i}"]').bounding_box() for i in bot]
    x0, x1 = min(b["x"] for b in pts) - 15, max(b["x"] + b["width"] for b in pts) + 15
    y0, y1 = min(b["y"] for b in pts) - 15, max(b["y"] + b["height"] for b in pts) + 15
    pg.keyboard.down("Shift"); pg.mouse.move(x0, y0); pg.mouse.down(); pg.mouse.move(x1, y1, steps=6); pg.mouse.up(); pg.keyboard.up("Shift")
    pg.wait_for_timeout(400)
    assert sorted(pg.evaluate(f"{ST}.DS.vsel.ids")) == sorted(bot)
    assert pg.evaluate(V) == v2                                                           # picking moved nothing
    assert not pg.errors, pg.errors


def test_a_warning_badge_sits_beside_the_edge_not_on_its_curve_dot(page):
    """Tyler (2026-11-28): the "!" of a seam warning sat on the edge's curve dot, so it couldn't be clicked."""
    pg = page
    _ensure_avatar(pg)
    pg.evaluate("""(() => { const a = makePiece('rect', {w: 40, h: 60}, 'a'), b = makePiece('rect', {w: 40, h: 45}, 'b');
        window.__studio.ST.design = {pieces: [a, b], seams: [{a: 'a.right', b: 'b.left', ease: 0}]};
        const DS = window.__studio.DS; DS.sel = null; DS.view = null; DS.shape = null; tidy(); dsChanged(true, true) })()""")
    if not pg.evaluate("document.body.classList.contains('advanced')"):
        pg.click("#mode [data-m=adv]")
    pg.evaluate(f"{ST}.ST.scratch = true; {ST}.go('fit'); tidy(); dsChanged(true, true)")
    pg.wait_for_function("document.querySelectorAll('#board .wbadge').length > 0", timeout=30000)
    pg.evaluate(f"{ST}.DS.sel = 'a'; renderInspector(); drawDesign()")
    pg.wait_for_timeout(800)
    i = pg.evaluate("pieceBy('a').edges.findIndex(e => e.name === 'right')")
    hit = pg.evaluate("""i => { const d = document.querySelector(`#board [data-mid="${i}"]`), r = d.getBoundingClientRect();
        const e = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2); return e === d }""", i)
    assert hit                                                     # the curve dot is on top: it can be clicked
    assert pg.locator("#board .wbadge").count() >= 1
    assert not pg.errors, pg.errors
