"""v0.9: starter designs, closures (buttons, snaps, zippers, hook & loop),
inside pockets (in-seam, front hip, inner patch), design-edit helpers."""
import copy
import io

import numpy as np
import pytest


@pytest.fixture(scope="module")
def av():
    from drape.studio import server as S
    init = S.api_init()
    a = S.api_avatar({"measurements": init["examples"]["female_M"]})
    return S, init, S.S.avatars[a["id"]], a["id"]


def _tpl(A, block):
    from drape.freeform import template_design
    return template_design(block, A["body"], A["meas"])


def _build(d, A):
    from drape.freeform import build_design, editor_to_design
    return build_design(editor_to_design(d), A["body"])


# ------------------------------------------------------------ editing --
def test_split_from_top_splits_both_sides_and_resews(av):
    from drape import dedit as E
    S, init, A, _ = av
    d = _tpl(A, "a_line_skirt")
    n0 = len(d["seams"])
    a, b = E.split_from_top(d, "front.side_r", [10, 25])
    assert len(a) == 3 and len(b) == 3 and len(d["seams"]) == n0 + 2
    for x, y in zip(a, b):     # each part sewn to the matching part, same length
        s, o = E.seam_of(d, f"front.{x}")
        assert s[o] == f"back.{y}"
        assert abs(E.plen(E.epts(d, f"front.{x}")) - E.plen(E.epts(d, f"back.{y}"))) < 0.2
    assert abs(E.plen(E.epts(d, f"front.{a[0]}")) - 10) < 0.05


def test_cut_vertical_keeps_area_and_seams(av):
    from shapely.geometry import Polygon
    from drape import dedit as E
    S, init, A, _ = av
    d = _tpl(A, "tee")
    area = lambda pc: Polygon(np.vstack([P[:-1] for _, P in E.outline(pc)])).area
    a0 = area(E.piece(d, "front"))
    lo, hi = E.cut_vertical(d, "front")
    assert abs(area(E.piece(d, lo)) + area(E.piece(d, hi)) - a0) < 1.0
    refs = {s["a"].split(".")[0] for s in d["seams"]} | {s["b"].split(".")[0] for s in d["seams"]}
    assert "front" not in refs and lo in refs and hi in refs
    assert np.allclose(E.epts(d, f"{lo}.cf")[:, 0], 0, atol=1e-6)


# ------------------------------------------------------------ closures --
def test_buttons_leave_open_part_unsewn_and_mark_the_pieces(av):
    from drape import dedit as E
    S, init, A, _ = av
    d = _tpl(A, "long_sleeve")
    E.open_down_middle(d, "front", "buttons", count=5)
    g = _build(d, A)
    c = g.meta["closures"][0]
    assert c["type"] == "buttons" and c["count"] == 5 and len(c["positions_cm"]) == 5
    P = {p.name: p for p in g.meta["panels"]}
    holes = [m for m in P["front_r"].marks if m["kind"] == "buttonhole"]
    buttons = [m for m in P["front_l"].marks if m["kind"] == "button"]
    assert len(holes) == 5 and len(buttons) == 5
    assert P["front_r"].extend["cf"] > 0.05            # stand + facing past the centre line
    from drape.closures import cut_polygon
    from shapely.geometry import Polygon
    plain = Polygon(np.concatenate([e[:-1] for _, e in P["front_r"].edges]) * 100).buffer(1.5)
    assert cut_polygon(P["front_r"], 1.5).area > plain.area + 50 * 5
    n_closed = len(g.seams)
    d2 = copy.deepcopy(d)
    [s for s in d2["seams"] if s.get("closure")][0]["closure"]["open"] = 1.0
    g2 = _build(d2, A)
    k = len(g.meta["edge_index"][("front_r", "cf")])
    assert n_closed - len(g2.seams) == k                 # unbuttoned: the whole front is apart


def test_zipper_in_part_of_a_seam(av):
    from drape import dedit as E
    S, init, A, _ = av
    d = _tpl(A, "a_line_skirt")
    lo, hi = E.cut_vertical(d, "back")
    d["seams"].append({"a": f"{lo}.cf", "b": f"{hi}.cf", "ease": 0})
    E.add_zipper(d, f"{lo}.cf", 18)
    g = _build(d, A)
    (c,) = g.meta["closures"]
    assert c["type"] == "zipper" and abs(c["length_cm"] - 18) < 0.1 and c["zip_cm"] == 20
    assert sum(1 for p in g.meta["panels"] for m in p.marks if m["kind"] == "zip_stop") == 2
    from drape.closures import trims
    t = trims(g)
    assert t[0]["type"] == "zip" and len(t[0]["a"]) == len(t[0]["b"]) > 3


def test_exports_carry_closure_marks(av, tmp_path):
    import ezdxf
    from drape import dedit as E
    from drape.export_dxf import export_pattern_dxf
    from drape.nest import nest_dxf
    from drape.printpdf import tiled_pdf
    S, init, A, _ = av
    d = _tpl(A, "long_sleeve")
    E.open_down_middle(d, "front", "buttons", count=6)
    g = _build(d, A)
    f = tmp_path / "s.dxf"
    export_pattern_dxf(f, g.meta["panels"], g.meta["seam_defs"], laser=True)
    marks = [e for e in ezdxf.readfile(f).modelspace() if e.dxf.layer == "MARK"]
    assert len(marks) == 6 + 6 + 2                     # holes, buttons, two fold lines
    f2 = tmp_path / "n.dxf"
    nest_dxf(str(f2), g.meta["panels"], g.meta["seam_defs"], 150, 120)
    assert sum(1 for e in ezdxf.readfile(f2).modelspace() if e.dxf.layer == "MARK") == 14
    tiled_pdf(g.meta["panels"], g.meta["seam_defs"], tmp_path / "t.pdf", "shirt")
    assert (tmp_path / "t.pdf").stat().st_size > 10000


def test_costing_and_instructions_know_the_notions(av):
    from drape import dedit as E
    from drape.costing import materials
    from drape.instructions import instructions
    S, init, A, _ = av
    d = _tpl(A, "long_sleeve")
    E.open_down_middle(d, "front", "buttons", count=6)
    g = _build(d, A)
    M = materials(g)
    assert M["notions"][0]["qty"] == 6 and "15 mm" in M["notions"][0]["label"]
    titles = [s["title"] for s in instructions(g)]
    assert "Buttonholes and buttons" in titles


# ------------------------------------------------------- inside pockets --
def test_inseam_pocket_bags_inside_the_seam(av):
    from drape import dedit as E
    from drape.freeform import design_check
    S, init, A, _ = av
    d = _tpl(A, "a_line_skirt")
    bags = E.add_inseam_pocket(d, "front.side_r", from_top_cm=6, opening_cm=15)
    assert len(bags) == 2
    g = _build(d, A)
    assert design_check(g)[0]["ok"], design_check(g)
    # the opening isn't sewn front-to-back; each side is sewn to its bag; the bags to each other
    pairs = {frozenset((s.panel_a, s.panel_b)) for s in g.meta["seam_defs"]}
    assert frozenset(bags) in pairs and frozenset(("front", bags[0])) in pairs and frozenset(("back", bags[1])) in pairs
    # bags start under the front (closer to the body than it)
    idx = {n: i for i, n in enumerate(g.panel_names)}
    sd = A["body"].sdf if hasattr(A["body"], "sdf") else None
    front = g.x[g.panel_id == idx["front"]]
    bag = g.x[g.panel_id == idx[bags[0]]]
    from scipy.spatial import cKDTree
    dist, j = cKDTree(front).query(bag)
    c = np.array([0, bag[:, 1].mean(), 0])
    assert np.mean(np.linalg.norm((bag - c)[:, [0, 2]], axis=1) < np.linalg.norm((front[j] - c)[:, [0, 2]], axis=1)) > 0.8
    titles = [s["title"] for s in __import__("drape.instructions", fromlist=["x"]).instructions(g)]
    assert "In-seam pockets" in titles


def test_front_hip_pocket_on_trousers(av):
    from drape import dedit as E
    from drape.freeform import design_check
    S, init, A, _ = av
    d = _tpl(A, "trousers")
    y = E.add_hip_pocket(d, "front_r", across_cm=10, down_cm=16)
    names = [e["name"] for e in E.piece(d, "front_r")["edges"]]
    assert "pocket_edge" in names
    assert abs(E.plen(E.epts(d, f"{y}.side")) - 16) < 0.1
    s, o = E.seam_of(d, f"{y}.side")
    assert s[o].startswith("back_r.outseam")
    g = _build(d, A)
    assert design_check(g)[0]["ok"], design_check(g)
    with pytest.raises(ValueError):       # band first, then the pocket: say so
        d2 = _tpl(A, "trousers")
        E.add_band(d2, "waistband", ["front_r.waist", "back_r.waist", "back_l.waist", "front_l.waist"])
        E.add_hip_pocket(d2, "front_r")


def test_inside_patch_pocket_sits_under_its_host(av):
    from drape import dedit as E
    S, init, A, _ = av
    d = _tpl(A, "tee")
    E.add_patch_pocket(d, "front", 12, 12, inside=True, name="inner")
    g = _build(d, A)
    idx = {n: i for i, n in enumerate(g.panel_names)}
    inner, front = g.x[g.panel_id == idx["inner"]], g.x[g.panel_id == idx["front"]]
    from scipy.spatial import cKDTree
    _, j = cKDTree(front).query(inner)
    assert np.mean(inner[:, 2] < front[j, 2]) > 0.9 and not g.meta.get("off_host")


# ------------------------------------------------------------ starters --
@pytest.mark.parametrize("sex", ["female_M", "male_M"])
def test_every_starter_builds_and_checks_out(sex):
    from drape.studio import server as S
    from drape.freeform import build_design, design_check, editor_to_design
    from drape.starters import STARTERS
    init = S.api_init()
    a = S.api_avatar({"measurements": init["examples"][sex]})
    A = S.S.avatars[a["id"]]
    assert len(STARTERS) >= 25
    for k in STARTERS:
        d = S.api_starter({"avatar": a["id"], "key": k})["design"]
        g = build_design(editor_to_design(d), A["body"])
        c = design_check(g)
        assert c[0]["ok"], (k, c)


def test_api_edit_ops(av):
    S, init, A, aid = av
    d = S.api_to_scratch({"avatar": aid, "block": "a_line_skirt"})["design"]
    r = S.api_edit({"design": d, "op": "inseam_pocket", "args": {"ref": "front.side_r"}})
    assert "hidden in the seam" in r["message"]
    r = S.api_edit({"design": r["design"], "op": "open_middle", "args": {"piece": "back", "kind": "zipper"}})
    d = r["design"]
    s = next(x for x in d["seams"] if x.get("closure"))
    r = S.api_edit({"design": d, "op": "closure", "args": {"a": s["a"], "b": s["b"], "kind": "buttons", "count": 4}})
    s = next(x for x in r["design"]["seams"] if x.get("closure"))
    assert s["closure"]["type"] == "buttons" and s["closure"]["count"] == 4
    out = S.api_scratch({"avatar": aid, "design": S_design(r["design"]), "full": True})
    assert out["check"][0]["ok"], out["check"]
    assert "starters" in init and len(init["starters"]) >= 25


def S_design(d):
    """Editor format -> what the studio sends (polylines)."""
    from drape.freeform import editor_to_design
    e = editor_to_design(d)
    for pc, src in zip(e["pieces"], d["pieces"]):
        for k in ("fabric", "interfacing", "lining"):
            if src.get(k):
                pc[k] = src[k]
    return e


# --------------------------------------------------------------- solver --
@pytest.mark.slow
def test_trousers_unfold_before_the_weld(av):
    """Pieces that start crumpled (trouser legs) open out while sewing (v0.8 regression)."""
    from drape.blocks import draft_block
    from drape.fabrics import get
    from drape import Simulator
    S, init, A, _ = av
    g, _ = draft_block("trousers", A["body"], A["meas"])
    sim = Simulator(g, A["body"], get("poplin"))
    for _ in range(int(3.5 * sim.fps)):
        sim.step()
    m = sim.metrics()
    assert m["strain_p99_pct"] < 8, m
    crotch = sim.x[np.isin(np.arange(len(sim.x)), sim.vmap[g.meta["edge_index"][("front_r", "crotch")]])]
    assert crotch[:, 1].min() > 0.62        # the crotch is up between the legs, not at the knees
