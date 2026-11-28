"""v1.6.13 (2026-11-27): fabric and print are set in Design (the garment's, and each piece's own look: a print,
a solid colour, an image), not on Try on; a cuff or hem band can flare (Flare slider); the alpha badge shows the
version."""
import copy

import numpy as np
import pytest

pytest.importorskip("playwright.sync_api")
from test_browser import ST, _convert, _ensure_avatar, _go_garment, page, server  # noqa: F401  (fixtures)

pytestmark = pytest.mark.slow


def _visible(pg, sel):
    return pg.evaluate("""s => [...document.querySelectorAll(s)].some(e => { const r = e.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && !e.closest('[hidden]') })""", sel)


def _adv(pg):
    if not pg.evaluate("document.body.classList.contains('advanced')"):
        pg.click("#mode [data-m=adv]")


def test_fabric_and_print_are_in_design_not_try_on_and_the_badge_shows_the_version(page):
    pg = page
    _ensure_avatar(pg)
    assert pg.inner_text("#alphaBtn").startswith("ALPHA v1.")
    _go_garment(pg, "tee")
    assert _visible(pg, "#fabrics .chip[data-f]") and _visible(pg, "#prints .chip")      # a pattern's Design step
    _convert(pg, "front")
    assert _visible(pg, "#fabrics .chip[data-f]") and _visible(pg, "#prints .chip")      # the free editor
    pg.evaluate(f"{ST}.go('preview')")
    pg.wait_for_timeout(300)
    assert not _visible(pg, "#fabrics") and not _visible(pg, "#prints") and pg.locator(".pane[data-pane=preview] .tab").count() == 0
    assert not page.errors, page.errors


def test_a_piece_has_its_own_look_mirrored_and_drawn_on_the_drape(page):
    pg = page
    _ensure_avatar(pg)
    _go_garment(pg, "tee")
    _convert(pg, "front")
    _adv(pg)
    if not pg.evaluate(f"{ST}.DS.sym"):
        pg.click("#symBtn")
    pg.click('#pattern [data-body="sleeve_r"]')
    pg.wait_for_timeout(300)
    pg.click('#plook [data-look="plaid"]')
    pg.wait_for_timeout(300)
    looks = pg.evaluate(f"Object.fromEntries({ST}.ST.design.pieces.map(p => [p.name, p.look ? p.look.print : null]))")
    assert looks["sleeve_r"] == "plaid" and looks["sleeve_l"] == "plaid" and not looks["front"]     # mirrored (Symmetric)
    pg.click('#pattern [data-body="back"]')
    pg.wait_for_timeout(300)
    pg.click('#plook [data-look="none"]')
    pg.wait_for_timeout(300)
    pg.fill("#plookc", "#111111")
    pg.dispatch_event("#plookc", "input")
    assert pg.evaluate(f"JSON.parse(JSON.stringify({ST}.ST.design.pieces.find(p => p.name === 'back').look))") == {"print": "none", "color": "#111111"}
    # drape it: the 3D view gets one tile per look and each point the tile of its piece
    pg.evaluate("""window.__prints = []; const sp = GL.setPrint.bind(GL);
        GL.setPrint = (m, t, c, cells, n) => { window.__prints.push({n, cells: cells ? [...new Set(cells)] : null}); return sp(m, t, c, cells, n) }; 0""")
    pg.evaluate(f"{ST}.ST.quality = 'quick'")
    pg.click("#dsPreview")
    pg.wait_for_timeout(300)
    pg.click("#drapeBtn")
    pg.wait_for_function(f"{ST}.ST.drape && {ST}.ST.drape.cloth_uv", timeout=900000)
    pg.wait_for_function("window.__prints.length > 0", timeout=30000)
    last = pg.evaluate("window.__prints[window.__prints.length - 1]")
    assert last["n"] == 3 and sorted(last["cells"]) == [0, 1, 2]       # the garment's plain, the plaid, the black
    names = pg.evaluate(f"{ST}.ST.drape.cloth_uv.names")
    assert {"front", "back", "sleeve_r", "sleeve_l"} <= set(names)
    assert not page.errors, page.errors


def test_a_cuff_flares_and_drapes_as_a_cone(page):
    pg = page
    _ensure_avatar(pg)
    _go_garment(pg, "tee")
    _convert(pg, "front")
    _adv(pg)
    r = pg.evaluate(f"""(async () => {{ const ok = await serverEdit('band', {{kind: 'cuff', loop: ['sleeve_r.hem'], avatar: {ST}.ST.avatar.id}});
        return ok }})()""")
    pg.wait_for_timeout(800)
    cuff = pg.evaluate(f"{ST}.ST.design.pieces[{ST}.ST.design.pieces.length - 1].name")
    pg.click(f'#pattern [data-body="{cuff}"]')
    pg.wait_for_timeout(300)
    assert _visible(pg, "#pflare")
    lens = "(() => { const P = pieceBy('%s'); return Object.fromEntries(P.edges.map((e, i) => [e.name, plen(edgePts(P, i))])) })()" % cuff
    before = pg.evaluate(lens)
    pg.fill("#pflare", "60")
    pg.dispatch_event("#pflare", "input")
    pg.wait_for_timeout(500)
    after = pg.evaluate(lens)
    assert after["join_1"] == pytest.approx(before["join_1"], abs=0.05)            # the seam keeps its length
    assert after["top"] == pytest.approx(1.6 * before["join_1"], rel=0.02)         # the open edge 60% longer
    assert after["end_r"] == pytest.approx(before["end_r"], abs=0.05)              # and the cuff as tall
    pl = pg.evaluate(f"JSON.parse(JSON.stringify(pieceBy('{cuff}').place))")
    assert pl["flare"] == pytest.approx(0.6) and pl["flare_r"] > 0
    pg.fill("#pflare", "0")                                                          # back to a plain band
    pg.dispatch_event("#pflare", "input")
    pg.wait_for_timeout(300)
    assert "flare" not in pg.evaluate(f"JSON.parse(JSON.stringify(pieceBy('{cuff}').place))")
    pg.fill("#pflare", "60")
    pg.dispatch_event("#pflare", "input")
    pg.wait_for_timeout(1500)
    # placed as a cone: its open edge starts further from the arm than its seam
    d = pg.evaluate(f"JSON.parse(JSON.stringify({ST}.ST.design))")
    assert not page.errors, page.errors
    from drape.freeform import build_design, editor_to_design
    from drape.studio import server as S
    init = S.api_init()
    body = S.S.avatars[S.api_avatar({"measurements": init["examples"]["female_M"]})["id"]]["body"]          # the page's avatar is in the test server's process
    g = build_design(editor_to_design(d), body)
    k = g.panel_names.index(cuff)
    X = g.x[g.panel_id == k]
    # a band hangs straight down from its opening: compare the ring round the vertical at its seam and its open edge
    top, low = X[X[:, 1] > np.percentile(X[:, 1], 85)], X[X[:, 1] < np.percentile(X[:, 1], 15)]
    c = top[:, [0, 2]].mean(0)
    near = np.linalg.norm(top[:, [0, 2]] - c, axis=1).mean()
    far = np.linalg.norm(low[:, [0, 2]] - low[:, [0, 2]].mean(0), axis=1).mean()
    assert far > near + 0.01, (near, far)
