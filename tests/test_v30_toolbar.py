"""v30: the Design toolbar (2026-11-25).

- one row of square buttons in groups, one colour per kind of tool (mode, pieces, edges, openings, view)
- the edge tools are on the toolbar: pick Dart / Pleat / Gathers / Hem / Elastic / Seam allowance / Split, then
  click the spot on an edge (no % to type, no side to pick); with Symmetric on, its mirror image gets the same
- a marker shows where a click would put it, on the edge and its mirror image
- the edge list in the side panel shows what's set on each edge, not the same buttons on every edge
"""
import pytest

pytest.importorskip("playwright.sync_api")
from test_browser import ST, _click_edge, _edge_xy, _ensure_avatar, page, server  # noqa: E402,F401  (fixtures)

pytestmark = pytest.mark.slow


def _board(pg, pieces_js, sel):
    _ensure_avatar(pg)
    if not pg.evaluate("document.body.classList.contains('advanced')"):
        pg.click("#mode [data-m=adv]")
    pg.evaluate("loadGarments({garments: [], activeGarmentId: null}); renderGarmentList()")
    pg.evaluate(f"""() => {{ const S = window.__studio; S.ST.scratch = true; S.ST.design = {{pieces: {pieces_js}, seams: []}};
        S.DS.sel = '{sel}'; S.DS.view = null; toolExit(); S.go('fit'); tidy(); dsChanged(true, true) }}""")
    pg.wait_for_timeout(900)


def _sym(pg, on):
    if pg.evaluate(f"{ST}.DS.sym") != on:
        pg.click("#symBtn")
        pg.wait_for_timeout(200)


def test_the_toolbar_is_square_buttons_in_colour_coded_groups(page):
    pg = page
    _board(pg, "[makePiece('rect', {w: 40, h: 60}, 'front')]", "front")
    groups = pg.evaluate("""[...document.querySelectorAll('#toolcard .tgroup')].map(g => [g.querySelector('.glab').textContent,
        getComputedStyle(g).getPropertyValue('--gc').trim(), g.querySelectorAll('.tb').length])""")
    names = [g[0] for g in groups]
    assert names == ["Mode", "Add a piece", "Edges", "Finish an opening", "View"], names
    assert len({g[1] for g in groups}) == 5, "each group its own colour"
    sizes = pg.evaluate("[...document.querySelectorAll('#toolcard .tb')].filter(b => b.offsetWidth).map(b => [b.offsetWidth, b.offsetHeight])")
    assert len(sizes) >= 20 and all(abs(w - h) <= 10 for w, h in sizes), sizes            # square-ish, all the same
    labels = pg.evaluate("""[...document.querySelectorAll('#toolcard .tb .tl')].filter(l => l.offsetWidth).map(l => l.scrollWidth <= l.clientWidth + 1)""")
    assert all(labels), "a label is cut off"
    # Simple mode: the groups for building from scratch go, Symmetric stays
    pg.click("#mode [data-m=beg]")
    pg.wait_for_timeout(250)
    assert not pg.is_visible("#edgetools") and not pg.is_visible("#shapes") and pg.is_visible("#symBtn")
    pg.click("#mode [data-m=adv]")
    assert not pg.errors, pg.errors


def test_edge_tools_go_where_you_click_and_mirror_with_symmetric(page):
    pg = page
    # a front cut as two halves, mirror images of each other (front_r | front_l)
    # (a slanted side seam: neither half is symmetric in itself, each is the other's mirror image)
    _board(pg, """[(p => { p.shape = {type: 'custom'}; p.verts[2][0] += 5; return p })(makePiece('rect', {w: 40, h: 60}, 'front_r')),
                   (p => { p.shape = {type: 'custom'}; p.verts[3][0] -= 5; return p })(makePiece('rect', {w: 40, h: 60}, 'front_l'))]""", "front_r")
    _sym(pg, True)
    assert pg.locator("#inspector [data-dart], #inspector [data-pleat], #inspector [data-split]").count() == 0   # nothing repeated per edge
    n_r, n_l = pg.evaluate("[pieceBy('front_r').verts.length, pieceBy('front_l').verts.length]")
    pg.click('#edgetools [data-et="dart"]')
    assert pg.is_visible("#toolpop") and "Dart" in pg.inner_text("#toolpop")
    # hovering shows where it would go, here and on the mirror image
    x, y = _edge_xy(pg, "front_r", "top", 0.3)
    pg.mouse.move(x, y)
    pg.wait_for_timeout(300)
    assert pg.locator("#board circle.edgemark").count() >= 2
    _click_edge(pg, "front_r", "top", 0.3)
    assert pg.evaluate("[pieceBy('front_r').verts.length, pieceBy('front_l').verts.length]") == [n_r + 3, n_l + 3]
    # the dart is at the spot clicked: its tip is 30% across front_r, and the mirror image's at the matching spot
    tips = pg.evaluate("""['front_r', 'front_l'].map(n => { const P = pieceBy(n), e = P.edges.findIndex(e => /_dart_a$/.test(e.name));
        const tip = P.verts[(e + 1) % P.verts.length], xs = P.verts.map(v => v[0]); return (tip[0] - Math.min(...xs)) / (Math.max(...xs) - Math.min(...xs)) })""")
    assert abs(tips[0] - tips[1]) > 0.2 and abs(tips[0] + tips[1] - 1) < 0.05, tips       # 0.3 / 0.7 or 0.7 / 0.3: mirror images
    # Symmetric off: one side only
    _sym(pg, False)
    pg.click('#edgetools [data-et="elastic"]')
    _click_edge(pg, "front_r", "bottom")
    assert pg.evaluate("[pieceBy('front_r').edges.find(e => e.name === 'bottom').elastic, !!pieceBy('front_l').edges.find(e => e.name === 'bottom').elastic]") == [True, False]
    assert pg.locator("#inspector [data-el]").count() == 1                                  # shown where it's set
    _sym(pg, True)
    _click_edge(pg, "front_r", "bottom")                                                     # again: off, on both
    assert pg.evaluate("[!!pieceBy('front_r').edges.find(e => e.name === 'bottom').elastic, !!pieceBy('front_l').edges.find(e => e.name === 'bottom').elastic]") == [False, False]
    pg.keyboard.press("Escape")
    assert pg.evaluate(f"{ST}.DS.tool") == "select" and not pg.is_visible("#toolpop")
    assert not pg.errors, pg.errors


def test_a_dart_across_the_centre_line_gets_its_twin_on_the_same_edge(page):
    pg = page
    _board(pg, "[makePiece('rect', {w: 40, h: 60}, 'back')]", "back")                      # one piece, symmetric in itself
    _sym(pg, True)
    n0 = pg.evaluate("pieceBy('back').verts.length")
    pg.click('#edgetools [data-et="dart"]')
    _click_edge(pg, "back", "top", 0.25)
    assert pg.evaluate("pieceBy('back').verts.length") == n0 + 6                            # two darts, mirror images
    xs = pg.evaluate("""(() => { const P = pieceBy('back'); return P.edges.map((e, i) => [e.name, P.verts[(i + 1) % P.verts.length][0]])
        .filter(([n]) => /_dart_a$/.test(n)).map(([, x]) => x) })()""")
    assert len(xs) == 2 and abs(xs[0] + xs[1]) < 0.5, xs                                     # either side of the middle, the same distance
    pg.keyboard.press("Escape")
    assert not pg.errors, pg.errors
