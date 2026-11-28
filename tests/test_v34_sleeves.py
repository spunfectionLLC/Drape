"""The sleeve generator (dedit.add_sleeve, the studio's "sleeve" edit): a set-in sleeve drafted to fit the armhole."""
import copy

import numpy as np
import pytest

from drape import dedit as E

SIDES = [{"front": "front.arm_r", "back": "back.arm_l"}, {"front": "front.arm_l", "back": "back.arm_r"}]


@pytest.fixture(scope="module")
def tee():
    from drape.studio import server as S
    init = S.api_init()
    a = S.api_avatar({"measurements": init["examples"]["female_M"]})
    d = S.api_to_scratch({"avatar": a["id"], "block": "tee"})["design"]
    bare = copy.deepcopy(d)
    bare["pieces"] = [p for p in bare["pieces"] if not p["name"].startswith("sleeve")]
    bare["seams"] = [s for s in bare["seams"] if "sleeve" not in s["a"] + s["b"]]
    return S, a["id"], d, bare


def _edges(p):
    return {e["name"]: E.plen(E.edge_pts(p, i)) for i, e in enumerate(p["edges"])}


def _sleeve(S, av, bare, **kw):
    return S.api_edit({"design": copy.deepcopy(bare), "op": "sleeve", "args": {"avatar": av, "sides": SIDES, **kw}})["design"]


def test_a_short_sleeve_is_drafted_like_the_tees_own(tee):
    S, av, d, bare = tee
    r = _sleeve(S, av, bare)
    own, new = _edges(E.piece(d, "sleeve_r")), _edges(E.piece(r, "sleeve_r"))
    assert new["cap_r"] == pytest.approx(own["cap_r"], abs=0.3) and new["cap_l"] == pytest.approx(own["cap_l"], abs=0.3)
    assert new["hem"] == pytest.approx(own["hem"], abs=1.0)                   # the upper arm plus the regular fit's ease
    # sewn as the tee's: both caps in, the left arm's armholes run the other way, closed under the arm
    want = {(s["a"], s["b"]): bool(s.get("reverse")) for s in d["seams"] if s["a"].startswith("sleeve")}
    got = {(s["a"], s["b"]): bool(s.get("reverse")) for s in r["seams"] if s["a"].startswith("sleeve")}
    assert got == want


def test_lengths_fits_and_a_puff_cap(tee):
    S, av, d, bare = tee
    L = {k: _edges(E.piece(_sleeve(S, av, bare, length=k), "sleeve_r"))["underarm_r"] for k in E.SLEEVE_LENGTHS}
    assert L["short"] < L["elbow"] < L["three_quarter"] < L["long"]
    long_ = _edges(E.piece(_sleeve(S, av, bare, length="long"), "sleeve_r"))
    assert long_["hem"] < _edges(E.piece(d, "sleeve_r"))["hem"]                # tapers to the wrist
    H = {k: _edges(E.piece(_sleeve(S, av, bare, fit=k), "sleeve_r"))["hem"] for k in E.SLEEVE_FIT}
    assert H["fitted"] < H["regular"] < H["loose"]
    p = _sleeve(S, av, bare, cap="puff")
    s = next(x for x in p["seams"] if x["a"] == "sleeve_r.cap_r")
    assert s["ease"] == pytest.approx(0.25, abs=0.02)                       # gathered in


def test_one_side_and_refusals(tee):
    S, av, d, bare = tee
    r = S.api_edit({"design": copy.deepcopy(bare), "op": "sleeve", "args": {"avatar": av, "sides": SIDES[1:]}})["design"]
    sl = [p for p in r["pieces"] if p.get("role") == "sleeve"]
    assert len(sl) == 1 and sl[0]["name"] == "sleeve_l" and sl[0]["place"]["arm"] == -1
    with pytest.raises(ValueError, match="already sewn"):
        S.api_edit({"design": copy.deepcopy(d), "op": "sleeve", "args": {"avatar": av, "sides": SIDES}})
    with pytest.raises(ValueError, match="no edge"):
        S.api_edit({"design": copy.deepcopy(bare), "op": "sleeve", "args": {"avatar": av, "sides": [{"front": "front.nope", "back": "back.arm_l"}]}})
    with pytest.raises(ValueError, match="Sleeve: length"):
        S.api_edit({"design": copy.deepcopy(bare), "op": "sleeve", "args": {"avatar": av, "sides": SIDES, "length": "ankle"}})


@pytest.mark.slow
def test_long_sleeves_drape_to_the_wrists(tee):
    gpu = pytest.importorskip("drape.gpu")
    ok, why = gpu.gpu_info()
    if not ok:
        pytest.skip(why)
    from drape.fabrics import get, panel_fabrics
    from drape.freeform import build_design, editor_to_design
    from drape.live import sim_setup
    from drape.springs import SpringSimulator
    S, av, d, bare = tee
    body = S.S.avatars[av]["body"]
    g = build_design(editor_to_design(_sleeve(S, av, bare, length="long")), body)
    fab = get("jersey")
    sim = SpringSimulator(panel_fabrics(g, fab), body, fab)
    gp = gpu.GPUSprings(sim_setup(sim, sim.body, "jersey", grid_h=sim.body.h))
    gp.self_while_sewing = False
    for _ in range(int((3.5 + sim.extra_time) * sim.fps)):
        gp.step(1)
    sim.x[:] = gp.positions(); sim.v[:] = gp.velocities(); sim.time = gp.time
    sim.weld()
    m = sim.metrics()
    assert m["penetrating_verts"] == 0 and m["strain_p99_pct"] < 8 and m["kinetic_energy_uJ"] < 150
    reach = []
    for s, nm in ((1, "sleeve_r"), (-1, "sleeve_l")):
        sj = body.arm_axis(s)[0]
        reach.append(100 * np.linalg.norm(sim.x[sim.g.panel_id == sim.g.panel_names.index(nm)] - sj, axis=1).max())
    assert min(reach) > 45 and abs(reach[0] - reach[1]) < 2                  # down to the wrist, both arms alike


def test_front_and_back_armholes_of_different_lengths_get_their_own_cap_halves():
    """A shift dress's front armhole is shorter than its back one (18 vs 21 cm): each cap half is drafted to its own
    armhole (the crown off the middle), so both seams get the same ease (equal halves gathered the front 12% and
    stretched the back 4%, pulling the sleeve and the dress's back)."""
    from drape.studio import server as S
    init = S.api_init()
    a = S.api_avatar({"measurements": init["examples"]["female_M"]})
    d = S.api_to_scratch({"avatar": a["id"], "block": "shift_dress"})["design"]
    r = S.api_edit({"design": d, "op": "sleeve", "args": {"avatar": a["id"], "length": "long",
                    "sides": [{"front": "front.armhole_r", "back": "back.armhole_l"}]}})["design"]
    ease = {s["b"]: s["ease"] for s in r["seams"] if s["a"].startswith("sleeve_r.cap")}
    assert ease["front.armhole_r"] == pytest.approx(0.03, abs=0.005) and ease["back.armhole_l"] == pytest.approx(0.03, abs=0.005)
    p = E.piece(r, "sleeve_r")
    assert p["place"]["top_cm"] == pytest.approx(max(v[1] for v in p["verts"]), abs=0.2)     # placed by its real crown


def test_drafted_sleeves_count_as_placed_and_sew_with_the_body(tee):
    from drape.freeform import build_design, design_check, editor_to_design, piece_regions
    S, av, d, bare = tee
    body = S.S.avatars[av]["body"]
    dd = editor_to_design(_sleeve(S, av, bare))
    assert not any("isn't on the body" in c["text"] for c in design_check(build_design(dd, body)))
    assert piece_regions(dd, body)["sleeve_r"] == "body" == piece_regions(dd, body)["sleeve_l"]


def test_clicking_the_back_armhole_first_still_sews_the_caps_front_half_to_the_front(tee):
    """Tyler's dress (2026-11-27): the back armhole clicked first sewed each cap's front half to the back armhole,
    and the seams crossed over the shoulder. Which armhole is the front comes from the body, not the click order."""
    S, av, d, bare = tee
    swapped = [{"front": s["back"], "back": s["front"]} for s in SIDES]
    r = S.api_edit({"design": copy.deepcopy(bare), "op": "sleeve", "args": {"avatar": av, "sides": swapped}})["design"]
    got = {(s["a"], s["b"]): bool(s.get("reverse")) for s in r["seams"] if s["a"].startswith("sleeve")}
    want = {(s["a"], s["b"]): bool(s.get("reverse")) for s in _sleeve(S, av, bare)["seams"] if s["a"].startswith("sleeve")}
    assert got == want and ("sleeve_r.cap_r", "front.arm_r") in got
