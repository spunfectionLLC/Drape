"""v31: split pieces with a shape, keeping every part (2026-11-25).

Tyler: "a split function where it keeps all the pieces but splits based on a shape: if I have a dress and I
want the mid section to be a different fabric". A cut and a join in one: every piece the shape overlaps is cut
into the parts outside it and the parts inside it; they're sewn back together along the shape's line; seams
the cut went across are sewn again part to part; the parts stay where their piece was on the body.
"""
import copy

import numpy as np
import pytest

from drape import dedit as E


def _rect(name, w, h):
    return {"name": name, "verts": [[-w / 2, 0], [w / 2, 0], [w / 2, h], [-w / 2, h]], "at": [0, 0], "shape": {"type": "custom"},
            "edges": [{"name": n, "c1": None, "c2": None, "elastic": False} for n in ("hem", "side_r", "top", "side_l")],
            "place": {"mode": "wrap", "rotate": 0, "offset_cm": 1.5, "at": "center", "landmark": "chest_front"}}


def _dress():
    f, b = _rect("front", 44, 100), _rect("back", 44, 100)
    b["place"]["landmark"] = "chest_back"
    return {"pieces": [f, b], "seams": [{"a": "front.side_r", "b": "back.side_l", "ease": 0},
                                        {"a": "front.side_l", "b": "back.side_r", "ease": 0}]}


def _band(y0, y1, x0=-40, x1=40):
    pts = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    return [[{"name": f"s{k}", "pts": [pts[k], pts[(k + 1) % 4]]} for k in range(4)]]


def _len(d, ref):
    pn, en = ref.split(".", 1)
    pc = E.piece(d, pn)
    return E.plen(E.edge_pts(pc, E.eidx(pc, en)))


def _check_seams(d):
    """Every edge sewn at most once, and every seam's two edges the same length (the parts match)."""
    used = [r for s in d["seams"] for r in (s["a"], s["b"])]
    assert len(used) == len(set(used)), "an edge is in two seams"
    for s in d["seams"]:
        la, lb = _len(d, s["a"]), _len(d, s["b"])
        ratio = max(la, lb) / max(min(la, lb), 1e-9)              # an eased seam (a sleeve cap) is longer on purpose
        assert abs(ratio - (1 + float(s.get("ease") or 0))) < 0.01 or abs(la - lb) < 0.1, (s, la, lb)


def test_a_band_across_a_dress_splits_front_and_back_and_sews_every_part_back():
    d = _dress()
    jobs = [{"piece": "front", "tools": _band(40, 55)}, {"piece": "back", "tools": _band(40, 55)}]
    inside, made, notes = E.split_with(d, jobs, fabric="denim")
    names = sorted(p["name"] for p in d["pieces"])
    assert len(names) == 6 and sorted(inside) == ["back_mid", "front_mid"], names
    assert all(E.piece(d, n).get("fabric") == "denim" for n in inside)
    assert not any(E.piece(d, n).get("fabric") for n in names if n not in inside)
    _check_seams(d)
    # the side seams: three parts each side, top to top, middle to middle, hem part to hem part
    side = [s for s in d["seams"] if "side" in s["a"] and "side" in s["b"]]
    assert len(side) == 6, d["seams"]
    for s in side:
        ya = [np.mean(E.epts(d, s["a"])[:, 1])]
        yb = [np.mean(E.epts(d, s["b"])[:, 1])]
        assert abs(ya[0] - yb[0]) < 0.5, s                  # sewn at the same height
    # along the band's lines: each outside part sewn to the middle
    along = [s for s in d["seams"] if s not in side]
    assert len(along) == 4 and all(("_mid." in s["a"]) != ("_mid." in s["b"]) for s in along), along
    # no edge left unsewn that was sewn before (the dress still closes at the sides)
    sewn = {r for s in d["seams"] for r in (s["a"], s["b"])}
    for p in d["pieces"]:
        for e in p["edges"]:
            if e["name"].startswith("side"):
                assert f"{p['name']}.{e['name']}" in sewn
    # every part keeps the spot its piece had on the body
    centres = {tuple(E.piece(d, n)["place"]["center_cm"]) for n in names if n.startswith("front")}
    assert centres == {(0.0, 50.0)}


def test_the_parts_sit_where_the_piece_was_on_the_body():
    from drape.freeform import _piece_place, editor_to_design
    from drape.studio import server as S
    a = S.api_avatar({"measurements": {"sex": "female", "height": 166, "chest": 92, "waist": 74, "hip": 100}})
    body = S.S.avatars[a["id"]]["body"]
    d0 = _dress()
    d = copy.deepcopy(d0)
    E.split_with(d, [{"piece": "front", "tools": _band(40, 55)}], fabric=None)
    D = {p["name"]: p for p in editor_to_design(d)["pieces"]}
    D0 = {p["name"]: p for p in editor_to_design(d0)["pieces"]}
    f0 = _piece_place(D0["front"], body)[1]
    probe = np.array([[0.10, 0.47], [-0.05, 0.47], [0.0, 0.20]])          # m, in the front's own coords
    for nm in ("front", "front_mid", "front_b"):
        if nm in D:
            f = _piece_place(D[nm], body)[1]
            assert np.abs(f(probe) - f0(probe)).max() < 0.004, nm            # the same spot as on the whole piece


def test_a_shape_over_one_piece_cuts_its_partner_to_match():
    d = _dress()
    E.split_with(d, [{"piece": "front", "tools": _band(40, 55)}])
    assert sorted(p["name"] for p in d["pieces"]) == ["back", "front", "front_b", "front_mid"]
    _check_seams(d)
    backs = [s for s in d["seams"] if s["a"].startswith("back.") or s["b"].startswith("back.")]
    assert len(backs) == 6, backs                             # the back's side edges cut where the front's were


def test_a_piece_used_as_the_shape_goes_and_a_pocket_goes_with_its_part(monkeypatch):
    from drape.studio import server as S
    d = _dress()
    band = _rect("piece", 90, 15)
    band["verts"] = [[x, y + 40] for x, y in band["verts"]]
    pocket = _rect("pocket", 14, 14)
    pocket["place"] = {"on": "front", "pos": [8, 5], "rotate": 0, "sewn": ["hem", "side_r", "side_l"]}
    d["pieces"] += [band, pocket]
    jobs = [{"piece": "front", "tools": _band(40, 55)}, {"piece": "back", "tools": _band(40, 55)}]
    r = S.api_edit({"design": d, "op": "split", "args": {"jobs": jobs + [{"piece": "piece", "tools": _band(40, 55)}],
                                                          "remove": "piece", "fabric": "denim"}})
    out = r["design"]
    assert "piece" not in [p["name"] for p in out["pieces"]]
    assert "front_mid" in r["message"] and "Split into 6 parts" in r["message"]
    pk = next(p for p in out["pieces"] if p["name"] == "pocket")
    hosts = {p["name"]: p for p in out["pieces"]}
    assert pk["place"]["on"] in hosts
    host = hosts[pk["place"]["on"]]
    ys = [v[1] for v in host["verts"]]
    assert min(ys) < 7 + 5 < max(ys)                          # it's on the part it sits on (the hem part)
    with pytest.raises(ValueError, match="unknown fabric"):
        S.api_edit({"design": _dress(), "op": "split", "args": {"jobs": jobs, "fabric": "unobtainium"}})


def test_a_shape_over_the_whole_piece_only_gives_it_the_fabric_and_one_over_nothing_says_so():
    d = _dress()
    inside, made, _ = E.split_with(d, [{"piece": "front", "tools": _band(-10, 120, -60, 60)}], fabric="denim")
    assert inside == ["front"] and len(d["pieces"]) == 2 and E.piece(d, "front")["fabric"] == "denim"
    _check_seams(d)
    with pytest.raises(ValueError, match="doesn't overlap"):
        E.split_with(_dress(), [{"piece": "front", "tools": _band(200, 220)}])


def test_a_starter_dress_split_through_the_middle_still_builds_and_closes():
    """The tee dress (pieces placed by its template): a band across every body piece; it builds, every
    seam matches and the drape's body pieces are all still there."""
    from drape.freeform import build_design, editor_to_design
    from drape.studio import server as S
    a = S.api_avatar({"measurements": {"sex": "female", "height": 166, "chest": 92, "waist": 74, "hip": 100}})
    body = S.S.avatars[a["id"]]["body"]
    d = S.api_starter({"avatar": a["id"], "key": "tee_dress"})["design"]
    n_pieces = len(d["pieces"])
    jobs = []
    for p in d["pieces"]:
        if (p.get("place") or {}).get("on") or (p.get("place") or {}).get("loop"):
            continue
        P = np.vstack([E.edge_pts(p, i) for i in range(len(p["edges"]))])
        lo, hi = P.min(0), P.max(0)
        if hi[1] - lo[1] < 60:
            continue                                            # sleeves, facings: the band misses them
        ym = lo[1] + 0.55 * (hi[1] - lo[1])
        jobs.append({"piece": p["name"], "tools": _band(ym - 6, ym + 6, lo[0] - 5, hi[0] + 5)})
    assert jobs
    inside, made, notes = E.split_with(d, jobs, fabric="denim")
    assert len(d["pieces"]) == n_pieces + 2 * len(jobs) and len(inside) == len(jobs)
    _check_seams(d)
    g = build_design(editor_to_design(d), body)
    assert len(g.panel_names) == len(d["pieces"])


# ------------------------------------------------------------------ the page
pw = pytest.importorskip("playwright.sync_api")
from test_browser import ST, _ensure_avatar, page, server  # noqa: E402,F401  (fixtures)


@pytest.mark.slow
def test_a_rectangle_drawn_across_a_dress_splits_it_from_its_piece_panel(page):
    pg = page
    _ensure_avatar(pg)
    if not pg.evaluate("document.body.classList.contains('advanced')"):
        pg.click("#mode [data-m=adv]")
    pg.evaluate("loadGarments({garments: [], activeGarmentId: null}); renderGarmentList()")
    pg.evaluate("""() => { const S = window.__studio, f = makePiece('rect', {w: 44, h: 100}, 'front'), b = makePiece('rect', {w: 44, h: 100}, 'back');
        b.at = [50, 0]; const band = makePiece('rect', {w: 110, h: 15}, 'piece'); band.at = [25, 40];
        S.ST.scratch = true; S.ST.design = {pieces: [f, b, band], seams: [{a: 'front.right', b: 'back.left', ease: 0}, {a: 'front.left', b: 'back.right', ease: 0}]};
        S.DS.sel = 'piece'; S.DS.view = null; toolExit(); S.go('fit'); drawDesign(); renderInspector() }""")
    pg.wait_for_timeout(900)
    pg.click("#psplit")
    pg.select_option("#spfab", "denim")
    pg.click("#spok")
    pg.wait_for_function(f"() => {ST}.ST.design.pieces.length === 6", timeout=30000)
    names = pg.evaluate(f"{ST}.ST.design.pieces.map(p => p.name).sort()")
    assert "piece" not in names and {"front_mid", "back_mid"} <= set(names), names
    assert pg.evaluate(f"{ST}.ST.design.pieces.filter(p => p.fabric === 'denim').map(p => p.name).sort()") == ["back_mid", "front_mid"]
    assert pg.evaluate(f"{ST}.ST.design.seams.length") == 10            # 2 x 3 side seams + 4 along the band
    assert "Split into 6 parts" in pg.inner_text(".toast")
    assert not pg.errors, pg.errors
