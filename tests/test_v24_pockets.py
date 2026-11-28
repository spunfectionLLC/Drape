"""In-seam pockets on any seam (2026-11-23): placed by the avatar's waist, on whatever part of the
seam is at that height (a dress's side seam below the bust dart), the opening following the seam's
shape, the bags hanging straight down whatever the seam's angle, inside the piece. On the GPU the
bags' stay stitches are capped at their stability limit (they shook the dress front)."""
import re
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import LineString, Polygon

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def av():
    from drape.studio import server as S
    init = S.api_init()
    a = S.api_avatar({"measurements": init["examples"]["female_M"]})
    return S, a["id"], S.S.avatars[a["id"]]


def _with_pockets(S, aid, block, choices=None, side_prefix="side"):
    from drape import dedit as E
    d = S.api_to_scratch({"avatar": aid, "block": block, "choices": choices or {}})["design"]
    for side in ("r", "l"):
        ref = next(f"front.{e['name']}" for e in E.piece(d, "front")["edges"]
                   if e["name"].startswith(side_prefix) and e["name"].endswith(side))
        d = S.api_edit({"design": d, "op": "inseam_pocket", "args": {"ref": ref}, "avatar": aid})["design"]
    return d


def _piece_poly(E, pc):
    return Polygon(np.vstack([P for _, P in E.outline(pc)]))


def _bags(d):
    return [p for p in d["pieces"] if "_bag" in p["name"]]


def test_a_dress_pocket_opens_3_cm_under_the_waist_on_the_seam_at_the_hips(av):
    from drape import dedit as E
    S, aid, A = av
    d = _with_pockets(S, aid, "shift_dress", {"Shape": "Swing"})
    off = E.body_height_offsets(d, A["body"])["front"]
    waist = A["body"].section_y("waist") * 100
    bags = _bags(d)
    assert len(bags) == 4
    for b in bags:
        op = dict((e["name"], P) for e, P in E.outline(b))["opening"]
        top, bot = op[:, 1].max() + off - waist, op[:, 1].min() + off - waist
        assert top == pytest.approx(-3.0, abs=0.3)                 # 3 cm under the waist (was: near the bust)
        assert bot < -14                                             # a hand-sized opening, down toward the hip
    # the seam split for the opening is the part below the bust dart, not the one above it
    opened = [s for s in d["seams"] if any(b["name"] + ".opening" in (s["a"], s["b"]) for b in bags)]
    assert all(re.search(r"front\.side_1|back\.side_1", s["a"] + s["b"]) for s in opened)


@pytest.mark.parametrize("block,choices", [("shift_dress", {"Shape": "Swing"}), ("a_line_skirt", {}),
                                           ("pencil_skirt", {})])
def test_bags_hang_straight_down_inside_the_piece_on_any_seam(av, block, choices):
    """A-line and swing seams slant out, a pencil skirt's narrows in below the hip, a dress's curves:
    the bag follows the seam over the opening, hangs straight down past it, and stays in the piece."""
    from drape import dedit as E
    S, aid, A = av
    d = _with_pockets(S, aid, block, choices)
    front = _piece_poly(E, E.piece(d, "front")).buffer(0.6)          # 6 mm: on the seam is inside
    for b in _bags(d):
        parts = dict((e["name"], P) for e, P in E.outline(b))
        op, bag = parts["opening"], parts["bag"]
        from shapely.geometry import Point
        assert all(front.contains(Point(q)) for P in parts.values() for q in P), (block, b["name"])
        # the opening is the seam itself: its points lie on one of the front's edges
        edges = [LineString(P) for _, P in E.outline(E.piece(d, "front"))]
        assert min(max(L.distance(Point(q)) for q in op) for L in edges) < 0.05
        # hangs down: the bag reaches well below the opening, its inner side vertical
        assert op[:, 1].min() - bag[:, 1].min() > 0.9 * 12
        # (the outline is stored counter-clockwise, so the inner side is at one end or the other)
        assert abs(bag[0, 0] - bag[1, 0]) < 0.01 or abs(bag[-1, 0] - bag[-2, 0]) < 0.01


def test_placing_by_distance_from_the_top_still_works(av):
    from drape import dedit as E
    S, aid, A = av
    d = S.api_to_scratch({"avatar": aid, "block": "a_line_skirt"})["design"]
    bags = E.add_inseam_pocket(d, "front.side_r", from_top_cm=6, opening_cm=15)
    op = dict((e["name"], P) for e, P in E.outline(E.piece(d, bags[0])))["opening"]
    P = E._top_first_pts(d, "front.side_r_1")                       # the part above the opening
    assert E.plen(P) == pytest.approx(6.0, abs=0.05) and E.plen(op) == pytest.approx(15.0, abs=0.05)


def test_the_studio_sends_the_avatar_and_asks_below_the_waist():
    js = (ROOT / "drape" / "studio" / "static" / "js" / "13_seams.js").read_text(encoding="utf-8")
    assert "avatar: ST.avatar ? ST.avatar.id : undefined" in js
    pieces = (ROOT / "drape" / "studio" / "static" / "js" / "12_pieces.js").read_text(encoding="utf-8")
    assert "Opening starts below the waist" in pieces and "below_waist_cm:" in pieces


def test_gpu_stitches_are_capped_at_their_stability_limit():
    src = (ROOT / "drape" / "studio" / "static" / "live_springs.js").read_text(encoding="utf-8")
    body = src[src.index("fn attach("):src.index("fn cgInit(")]
    assert "let kc = min(PARAM[p0 + 4u], 0.5 / (F.h * F.h * max(W, 1e-12)));" in body
    assert "let f = D * (kc * (L - rest) / L);" in body


@pytest.mark.slow
def test_a_pocketed_dress_drapes_calmly_on_the_gpu(av):
    """The website's drape of a dress with in-seam pockets: before the stitch cap the front shook
    against the stitched bags (KE ~1900 uJ, crumpled); now it settles like the dress alone."""
    gpu = pytest.importorskip("drape.gpu")
    ok, why = gpu.gpu_info()
    if not ok:
        pytest.skip(why)
    from drape.fabrics import get, panel_fabrics
    from drape.freeform import build_design, editor_to_design
    from drape.springs import SpringSimulator
    from drape.live import sim_setup
    S, aid, A = av
    d = _with_pockets(S, aid, "shift_dress", {"Shape": "Swing"})
    g = build_design(editor_to_design(d), A["body"])
    fab = get("jersey")
    sim = SpringSimulator(panel_fabrics(g, fab), A["body"], fab)
    gp = gpu.GPUSprings(sim_setup(sim, sim.body, "jersey", grid_h=sim.body.h))
    gp.self_while_sewing = False
    for _ in range(int((3.5 + sim.extra_time) * sim.fps)):
        gp.step(1)
    sim.x[:] = gp.positions(); sim.v[:] = gp.velocities(); sim.time = gp.time
    sim.weld()
    m = sim.metrics()
    assert m["penetrating_verts"] == 0 and m["strain_p99_pct"] < 8
    assert m["kinetic_energy_uJ"] < 150          # GPU settling is a known issue (KNOWN_ISSUES.md); was ~1900
