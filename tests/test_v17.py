"""v1.5: shaping a piece with another shape (cut it away, join it on, keep the
overlap), joining two sewn pieces into one, copying pieces onto the layer over
them, and .drape project files."""
import copy

import numpy as np
import pytest

from drape import dedit as E


def circle(cx, cy, r, n=16):
    """A circle as the studio sends it: four quarter edges of points (cm)."""
    t = np.linspace(0, 2 * np.pi, 4 * n + 1)
    P = np.stack([cx + r * np.cos(t), cy + r * np.sin(t)], 1)
    return [{"name": f"q{k + 1}", "pts": P[k * n:(k + 1) * n + 1].tolist()} for k in range(4)]


def box(x0, y0, x1, y1):
    c = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    return [{"name": n, "pts": [c[i], c[(i + 1) % 4]]} for i, n in enumerate(("b", "r", "t", "l"))]


def area(pc):
    from shapely.geometry import Polygon
    return Polygon(np.vstack([E.edge_pts(pc, i)[:-1] for i in range(len(pc["edges"]))])).area


def names(pc):
    return [e["name"] for e in pc["edges"]]


def two_panel():
    """A front 40 x 60 sewn to a back along their sides, and a waistband loop."""
    f, b = E.rect("front", 40, 60), E.rect("back", 40, 60)
    return {"pieces": [f, b], "seams": [{"a": "front.left", "b": "back.right", "ease": 0},
                                        {"a": "front.right", "b": "back.left", "ease": 0}]}


# ------------------------------------------------------------ cut it away --
def test_scoop_from_the_top_keeps_the_other_edges_and_their_seams():
    d = two_panel()
    made, notes = E.shape_with(d, "front", [circle(0, 60, 9)], "cut")
    f = E.piece(d, "front")
    assert made == ["front"]
    assert abs((40 * 60 - area(f)) - np.pi * 81 / 2) < 3            # half a 9 cm circle came out
    assert {"bottom", "right", "left", "top_1", "top_2", "cut"} == set(names(f))
    cut = f["edges"][names(f).index("cut")]
    assert len(cut["pts"]) > 10 and E.plen(np.asarray(cut["pts"])) == pytest.approx(np.pi * 9, rel=0.03)   # stays a curve
    assert {"front.left", "front.right"} <= {s["a"] for s in d["seams"]}                                     # side seams kept
    assert not notes                                                     # the top wasn't sewn: nothing to re-sew


def test_notching_a_corner_shortens_two_edges_and_keeps_their_names():
    d = two_panel()
    E.shape_with(d, "front", [box(15, 50, 30, 70)], "cut")
    f = E.piece(d, "front")
    assert {"bottom", "right", "top", "left"} <= set(names(f)) and len([n for n in names(f) if n.startswith("cut")]) == 2
    assert E.plen(E.epts(d, "front.right")) == pytest.approx(50, abs=0.01)
    assert E.plen(E.epts(d, "front.top")) == pytest.approx(35, abs=0.01)
    assert any(s["a"] == "front.right" for s in d["seams"])              # still sewn: the checks will flag the length


def test_cutting_a_sewn_edge_in_two_unsews_it_and_says_so():
    d = two_panel()
    _, notes = E.shape_with(d, "front", [circle(20, 30, 6)], "cut")        # right side, half way up
    f = E.piece(d, "front")
    assert "right_1" in names(f) and "right_2" in names(f)
    assert not any("front.right" in (s["a"], s["b"]) for s in d["seams"])
    assert any("sew them again" in n for n in notes)


def test_a_hole_is_refused():
    d = two_panel()
    with pytest.raises(ValueError, match="hole"):
        E.shape_with(d, "front", [circle(0, 30, 5)], "cut")


def test_a_shape_off_the_piece_is_refused():
    d = two_panel()
    with pytest.raises(ValueError, match="doesn't overlap"):
        E.shape_with(d, "front", [circle(100, 100, 5)], "cut")


def test_cutting_right_through_makes_two_pieces_and_seams_follow():
    d = two_panel()
    made, notes = E.shape_with(d, "front", [box(-30, 28, 30, 32)], "cut")  # a band across the middle
    assert len(made) == 2 and "front_b" in made
    lo, hi = sorted((E.piece(d, n) for n in made), key=lambda p: min(v[1] for v in p["verts"]))
    assert "bottom" in names(lo) and "top" in names(hi)
    assert "right_1" in names(lo) + names(hi) and "right_2" in names(lo) + names(hi)
    assert "right pieces" not in " ".join(notes) and "is now 2 pieces" in notes[0]


def test_mirror_pair_of_shapes_cut_together():
    d = two_panel()
    E.shape_with(d, "front", [box(14, 54, 22, 62), box(-22, 54, -14, 62)], "cut")   # both shoulders
    f = E.piece(d, "front")
    assert E.plen(E.epts(d, "front.top")) == pytest.approx(28, abs=0.01)
    assert abs(area(f) - (2400 - 2 * 6 * 6)) < 0.5


# --------------------------------------------------------- join / keep --
def test_join_a_drawn_shape_on_adds_edges():
    d = two_panel()
    E.shape_with(d, "front", [circle(0, 0, 10)], "join")                   # a curved tab below the hem
    f = E.piece(d, "front")
    assert "added" in names(f) and "bottom_1" in names(f) and "bottom_2" in names(f)
    assert abs(area(f) - (2400 + np.pi * 100 / 2)) < 3


def test_join_another_piece_takes_its_edges_and_seams():
    d = two_panel()
    flare = E.rect("flare", 20, 10, x0=-10, y0=-8)                        # overlaps the hem by 2 cm
    d["pieces"].append(flare)
    d["seams"].append({"a": "flare.bottom", "b": "back.bottom", "ease": 0})
    tool = [{"name": e["name"], "pts": E.edge_pts(flare, i).tolist()} for i, e in enumerate(flare["edges"])]
    E.shape_with(d, "front", [tool], "join", src="flare")
    assert "flare" not in [p["name"] for p in d["pieces"]]
    f = E.piece(d, "front")
    assert "flare_bottom" in names(f) or "bottom" in names(f)
    assert any(s["b"] == "back.bottom" and s["a"].startswith("front.") for s in d["seams"])   # the seam came along


def test_keep_the_overlap_trims_to_the_shape():
    d = two_panel()
    E.shape_with(d, "front", [box(-10, -5, 10, 70)], "keep")
    f = E.piece(d, "front")
    assert abs(area(f) - 20 * 60) < 0.5 and "trim" in names(f)
    assert not any("front.left" in (s["a"], s["b"]) for s in d["seams"])   # the side edges are gone, and their seams


# ---------------------------------------------------- join along a seam --
def test_join_two_sewn_pieces_into_one():
    d = two_panel()
    d["pieces"].append(E.rect("yoke", 40, 10))
    d["seams"].append({"a": "yoke.bottom", "b": "front.top", "ease": 0})
    d["pieces"].append(E.rect("band", 40, 4))
    d["seams"].append({"a": "band.bottom", "b": "yoke.top", "ease": 0})
    E.add_patch_pocket(d, "yoke", w=8, h=6)
    note = E.join_along_seam(d, "front.top", "yoke.bottom")
    assert "yoke" not in [p["name"] for p in d["pieces"]] and "seam is gone" in note
    f = E.piece(d, "front")
    assert abs(area(f) - 40 * 70) < 0.5
    ys = [v[1] for v in f["verts"]]
    assert max(ys) == pytest.approx(70, abs=0.01)                          # the yoke sits on top
    assert any(s["a"] == "band.bottom" and s["b"].startswith("front.") for s in d["seams"])
    assert E.piece(d, "pocket")["place"]["on"] == "front"
    assert {"front.left", "front.right"} <= {s["a"] for s in d["seams"]}


def test_join_refuses_mismatched_or_gathered_seams():
    d = two_panel()
    d["pieces"].append(E.rect("yoke", 30, 10))
    d["seams"].append({"a": "yoke.bottom", "b": "front.top", "ease": 0})
    with pytest.raises(ValueError, match="make them match"):
        E.join_along_seam(d, "front.top", "yoke.bottom")
    d2 = two_panel()
    d2["pieces"].append(E.rect("yoke", 40, 10))
    d2["seams"].append({"a": "yoke.bottom", "b": "front.top", "ease": 0.3})
    with pytest.raises(ValueError, match="gathered"):
        E.join_along_seam(d2, "front.top", "yoke.bottom")


def test_join_refuses_differently_curved_edges():
    d = two_panel()
    y = E.rect("yoke", 40, 10)
    y["edges"][0]["c1"], y["edges"][0]["c2"] = [-10, -4], [10, -4]         # a curved bottom
    d["pieces"].append(y)
    d["seams"].append({"a": "yoke.bottom", "b": "front.top", "ease": 0})
    with pytest.raises(ValueError, match="shaped differently|make them match"):
        E.join_along_seam(d, "front.top", "yoke.bottom")


# ---------------------------------------------------- copy onto a layer --
def test_layer_copy_sews_copies_together_and_holds_outside_seams():
    d = two_panel()
    d["pieces"].append(E.rect("band", 80, 4))
    d["seams"] += [{"a": "band.bottom", "b": "front.top", "ease": 0}]
    E.piece(d, "back")["edges"][2]["elastic"] = True                        # back.top gathered with elastic
    made = E.layer_copy(d, ["front", "back"], fabric="chiffon")
    assert made == ["front_over", "back_over"]
    fo, bo = E.piece(d, "front_over"), E.piece(d, "back_over")
    assert fo["place"]["layer"] == 1 and fo["place"]["layer_of"] == "front" and fo["fabric"] == "chiffon"
    assert {(s["a"], s["b"]) for s in d["seams"]} >= {("front_over.left", "back_over.right"), ("front_over.right", "back_over.left")}
    assert fo["place"]["held"] == ["top"] and bo["place"]["held"] == ["top"]       # waistband / elastic: held
    assert [p["name"] for p in d["pieces"]][:4] == ["front", "front_over", "back", "back_over"]


def test_layer_copy_stops_at_the_outermost_layer():
    d = two_panel()
    E.piece(d, "front")["place"]["layer"] = 2
    with pytest.raises(ValueError, match="outermost"):
        E.layer_copy(d, ["front"])


def test_layer_joins_skip_edges_that_were_renamed():
    from drape.freeform import _layer_joins
    d = two_panel()
    E.layer_copy(d, ["front"])
    fo = E.piece(d, "front_over")
    fo["place"]["held"] = ["left", "gone"]
    plain = {"pieces": [{"name": p["name"], "edges": p["edges"], "place": p["place"]} for p in d["pieces"]]}
    assert _layer_joins(plain) == [("front_over", "left", "front", "left")]


# ---------------------------------------------------------- the studio --
def test_studio_edit_ops():
    from drape.studio.server import api_edit
    d = two_panel()
    r = api_edit({"design": d, "op": "shape", "args": {"how": "cut", "jobs": [{"piece": "front", "tools": [circle(0, 60, 9)]}]}})
    assert "cut" in names(E.piece(r["design"], "front")) and "Cut the shape away from front" in r["message"]
    assert d == two_panel()                                                 # the request's design isn't changed
    r = api_edit({"design": r["design"], "op": "layer_copy", "args": {"pieces": ["front", "back"]}})
    assert "front_over" in r["message"]
    d3 = two_panel()
    d3["pieces"].append(E.rect("yoke", 40, 10))
    d3["seams"].append({"a": "yoke.bottom", "b": "front.top", "ease": 0})
    r = api_edit({"design": d3, "op": "join_seam", "args": {"seams": [["front.top", "yoke.bottom"]]}})
    assert "part of 'front'" in r["message"]


def test_studio_has_the_tools_and_the_file_window():
    from drape.studio.server import studio_source
    src = studio_source()
    for needle in ('id="pshape"', "Cut it away", "Join it on", "Keep the overlap", 'id="playercopy"',
                   'id="fileBtn"', ".drape", "showSaveFilePicker", "drape-project"):
        assert needle in src, needle


@pytest.mark.slow
def test_layer_copy_drapes_held_to_its_original():
    """An overlay copy of a skirt panel builds, starts outside it, and is tied to it at the waist."""
    from drape.freeform import build_design, editor_to_design
    from drape.studio import server as S
    init = S.api_init()
    a = S.api_avatar({"measurements": init["examples"]["female_M"]})
    A = S.S.avatars[a["id"]]
    d = {"pieces": [E.rect("skirt", 110, 55)], "seams": [{"a": "skirt.right", "b": "skirt.left", "ease": 0}]}
    d["pieces"][0]["place"] = {"landmark": "waist_front", "at": "top", "mode": "wrap", "rotate": 0, "offset_cm": 1.5}
    d["pieces"][0]["edges"][2]["elastic"] = True
    E.layer_copy(d, ["skirt"])
    g = build_design(editor_to_design(copy.deepcopy(d)), A["body"])
    assert "skirt_over.top" in g.meta["lining_joins"]
    assert len(g.meta["attach"]["v"]) > 10
    pid = g.panel_id
    i0, i1 = g.panel_names.index("skirt"), g.panel_names.index("skirt_over")
    axis = g.x[pid == i0][:, [0, 2]].mean(0)                                # the skirt's middle, seen from above
    r0 = np.linalg.norm(g.x[pid == i0][:, [0, 2]] - axis, axis=1).mean()
    r1 = np.linalg.norm(g.x[pid == i1][:, [0, 2]] - axis, axis=1).mean()
    assert r1 > r0                                                          # the copy starts outside the skirt


# ------------------------------------------------------------ hood order --
@pytest.fixture(scope="module")
def tee_design():
    from drape.studio import server as S
    init = S.api_init()
    a = S.api_avatar({"measurements": init["examples"]["female_M"]})
    return S, a["id"], S.api_to_scratch({"avatar": a["id"], "block": "tee"})["design"]


@pytest.mark.slow
@pytest.mark.parametrize("tapped", [["back.neck", "front.neck"], ["front.neck", "back.neck"]])
def test_hood_starts_at_the_centre_front_whatever_the_tap_order(tee_design, tapped):
    S, av, d = tee_design
    r = S.api_edit({"design": copy.deepcopy(d), "op": "band", "args": {"kind": "hood", "loop": tapped, "avatar": av}})
    hood = r["design"]["pieces"][-1]
    assert hood["place"]["loop"] == ["front.neck_2", "back.neck", "front.neck_1"]     # as the Hoodie starter has it
    f = E.piece(r["design"], "front")
    assert abs(f["verts"][[e["name"] for e in f["edges"]].index("neck_2")][0]) < 0.05  # split on the middle line


@pytest.mark.slow
def test_hood_round_an_open_front_starts_after_the_gap(tee_design):
    S, av, d = tee_design
    d = copy.deepcopy(d)
    E.split_edge_at(d, "front", "neck", [5, 15])                                       # middle of the front left out
    r = S.api_edit({"design": d, "op": "band", "args": {"kind": "hood", "loop": ["back.neck", "front.neck_3", "front.neck_1"], "avatar": av}})
    assert r["design"]["pieces"][-1]["place"]["loop"] == ["front.neck_3", "back.neck", "front.neck_1"]


@pytest.mark.slow
def test_neckband_follows_the_neckline_from_the_first_tap(tee_design):
    from drape.freeform import order_loop
    S, av, d = tee_design
    body = S.S.avatars[av]["body"]
    d = copy.deepcopy(d)
    E.split_edge_at(d, "back", "neck", [8])
    E.split_edge_at(d, "front", "neck", [8])
    tapped = ["back.neck_1", "front.neck_1", "back.neck_2", "front.neck_2"]                  # halves not next to each other
    loop, split = order_loop(d, body, tapped)
    assert split is None and loop[0] == "back.neck_1" and sorted(loop) == sorted(tapped)
    nxt = {loop[k]: {loop[k - 1], loop[(k + 1) % 4]} for k in range(4)}
    assert "back.neck_2" in nxt["back.neck_1"] and "front.neck_2" in nxt["front.neck_1"]     # each neckline's halves meet


# ------------------------------------------------- live mode speed cap --
def test_live_solver_caps_speed_like_the_full_drape():
    """Without the cap, a hood squeezed between its seams and the head buzzed and was
    flung onto the chest in live mode (the full Drape caps speed at 3 m/s)."""
    from drape.studio.server import STATIC
    src = (STATIC / "live_springs.js").read_text(encoding="utf-8")
    assert '["vmax", "f32"]' in src                                      # in the Frame uniform
    assert "sp > F.vmax" in src and "vmax: this.vClamp" in src
    assert "this.vClamp = Math.min(this.prm.max_speed || 3, r.vClamp)" in src   # never above the 3 m/s cap


@pytest.mark.slow
def test_live_setup_sends_the_speed_cap(tee_design):
    from drape.freeform import build_design, editor_to_design
    from drape.live import live_setup
    from drape.cloth import MAX_SPEED
    S, av, d = tee_design
    g = build_design(editor_to_design(copy.deepcopy(d)), S.S.avatars[av]["body"], spacing=0.03)
    setup = live_setup(g, S.S.avatars[av]["body"])
    assert setup["params"]["max_speed"] == MAX_SPEED
    # cloth-on-cloth skips a point's own seam group (cuffs buzzed without it): the group ids are sent
    assert "gid" in setup["springs"]["toff"]
