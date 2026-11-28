"""Staged sewing (STAGED_SEWING_SPEC.md): the body garment is sewn and settles first,
then the hood / collar / cuffs / pockets are sewn onto it, so a hood no longer drags
the shirt up to meet it halfway."""
import copy
import sys
from pathlib import Path

import numpy as np
import pytest

from drape import stages
from drape.stages import assign, region

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


# ------------------------------------------------------------ the rules --
def _pc(name, role=None, stage=None, **place):
    pc = {"name": name, "edges": [], "place": place}
    if role:
        pc["role"] = role
    if stage is not None:
        pc["stage"] = stage
    return pc


def _tee(*extra):
    """front/back/sleeves of a tee, plus `extra` pieces."""
    return [_pc("front", "body", template={"piece": "front"}), _pc("back", "body", template={"piece": "back"}),
            _pc("sleeve_r", "sleeve", template={"piece": "sleeve_r"}),
            _pc("sleeve_l", "sleeve", template={"piece": "sleeve_l"})] + list(extra)


def _st(pieces):
    return assign(pieces)[0]


def test_a_tee_alone_is_all_stage_one():
    assert set(_st(_tee()).values()) == {1}


def test_the_hood_is_stage_two_and_the_tee_stage_one():
    p = _st(_tee(_pc("hood", "hood", loop=["front.neck", "back.neck"])))
    assert p["hood"] == 2 and p["front"] == p["back"] == p["sleeve_r"] == 1


def test_cuffs_are_stage_two_and_the_sleeves_stay_in_one():
    p = _st(_tee(_pc("cuff", "cuff", loop=["sleeve_r.hem"]), _pc("cuff_2", "cuff", loop=["sleeve_l.hem"])))
    assert p["cuff"] == p["cuff_2"] == 2 and p["sleeve_r"] == 1


def test_a_pocket_is_stage_three():
    p = _st(_tee(_pc("hood", "hood", loop=["front.neck"]), _pc("pocket", "pocket", on="front")))
    assert p["pocket"] == 3
    # with nothing in stage 2, the stages close up: the pocket is the second (and last)
    assert _st(_tee(_pc("pocket", "pocket", on="front")))["pocket"] == 2


def test_the_role_wins_over_the_region_and_untagged_pieces_use_the_region():
    p = _st(_tee(_pc("hood", "hood", loop=["front.neck"]), _pc("patch", "body", on="front"),
                 _pc("band", loop=["front.hem"]), _pc("tab", on="front")))
    assert p["patch"] == 1 and p["band"] == 2 and p["tab"] == 3


def test_an_untagged_piece_with_no_region_is_stage_one():
    p = _st(_tee(_pc("hood", "hood", loop=["front.neck"]), _pc("loose")))
    assert region(_pc("loose")) is None and p["loose"] == 1


def test_pocket_bags_and_linings_go_with_their_piece():
    p = _st(_tee(_pc("bag", "other", on="front", inside=1), _pc("hood", "hood", loop=["front.neck"]),
                 _pc("hood_lining", loop=["front.neck"], _lining_of="hood"), _pc("over", layer_of="hood")))
    assert p["bag"] == 1 and p["hood_lining"] == 2 and p["over"] == 2


def test_gloves_on_their_own_are_the_garment_and_on_a_garment_stage_two():
    gl = [_pc("palm_r", glove={"hand": "right"}), _pc("back_r", glove={"hand": "right"})]
    assert set(_st(gl).values()) == {1}
    p = _st(_tee(*gl))
    assert p["palm_r"] == p["back_r"] == 2 and p["front"] == 1


def test_the_users_choice_wins():
    p = _st(_tee(_pc("hood", "hood", 1, loop=["front.neck"]), _pc("pocket", "pocket", 1, on="front")))
    assert set(p.values()) == {1}
    st, auto = assign(_tee(_pc("hood", "hood", "auto", loop=["front.neck"]), _pc("collar", "collar", 3, loop=["back.neck"])))
    assert st["hood"] == 2 and st["collar"] == 3 and auto["hood"] and not auto["collar"]


def test_region_from_the_placement():
    assert region(_pc("x", landmark="head_back")) == "head"
    assert region(_pc("x", landmark="neck_front")) == "neck"
    assert region(_pc("x", landmark="hip_front")) == "body"
    assert region(_pc("x", on="front")) == "surface"
    assert region(_pc("x", on="front", inside=1)) == ("on", "front")
    assert region(_pc("x", loop=["front.neck"])) == "band"
    assert region(_pc("x", glove={"hand": "left"})) == "hands"


def test_old_designs_without_stages_or_roles_load_and_auto_assign(av):
    """A v1.4 file: no roles, no stages. Stages come from where the pieces are placed."""
    _, _, body, _, hooded = av
    from drape.freeform import build_design, editor_to_design
    d = copy.deepcopy(hooded)
    for pc in d["pieces"]:
        pc.pop("role", None); pc.pop("stage", None)
    g = build_design(editor_to_design(d), body)
    ps = dict(zip(g.panel_names, g.meta["piece_stage"]))
    hood = [n for n in ps if n.startswith("hood")]
    assert hood and all(ps[n] == 2 for n in hood) and all(v == 1 for n, v in ps.items() if n not in hood)


def test_the_hoods_seams_to_the_neckline_are_stage_two(av):
    _, _, body, _, hooded = av
    from drape.freeform import build_design, editor_to_design
    g = build_design(editor_to_design(hooded), body)
    st = g.meta["design_seam_stage"]
    for s, k in zip(hooded["seams"], st):
        assert k == (2 if "hood" in s["a"] + s["b"] else 1), (s, k)


# --- design guard (STAGED_SEWING_SPEC section 0): a piece's
# stage must come only from its placement, its role and the user's choice, never from
# the seams or which pieces are sewn to which. These tests exist to keep it that way.
def _starter_designs(av):
    from drape import starters
    S, a, body, _, hooded = av
    m = S.S.avatars[a]["meas"]
    return body, [hooded] + [starters.starter(k, body, m) for k in ("hoodie", "button_up", "jeans", "pocket_tee", "knit_gloves")]


def test_assignment_ignores_the_seams(av):
    import random
    from drape.freeform import build_design, editor_to_design, piece_regions
    body, designs = _starter_designs(av)
    rnd = random.Random(7)
    for d in designs:
        want = assign(d["pieces"], piece_regions(d, body))[0]
        names = [p["name"] for p in d["pieces"]]
        shuffled, none, extra = copy.deepcopy(d), copy.deepcopy(d), copy.deepcopy(d)
        rnd.shuffle(shuffled["seams"])
        none["seams"] = []
        for _ in range(6):
            extra["seams"].append({"a": rnd.choice(names) + ".x", "b": rnd.choice(names) + ".y"})
        for v in (shuffled, none, extra):
            assert assign(v["pieces"], piece_regions(v, body))[0] == want
        g0 = build_design(editor_to_design(d), body)              # and through the whole build
        g1 = build_design(editor_to_design(shuffled), body)
        assert dict(zip(g0.panel_names, g0.meta["piece_stage"])) == dict(zip(g1.panel_names, g1.meta["piece_stage"]))


def test_assignment_code_never_mentions_seams_or_connectivity():
    """A static check (spec section 0): the code that picks stages must not read seams,
    edges or any connectivity. Docstrings and comments are left out (they may explain why)."""
    import ast
    import inspect
    import textwrap
    from drape import freeform
    banned = ("seam", "edges", "nbr", "neighbo", "connect", "graph", "union", "find(", "sewn")
    for f in (stages.region, stages._body_region, stages._user_stage, stages.assign, freeform.piece_regions):
        tree = ast.parse(textwrap.dedent(inspect.getsource(f)))
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                    and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
                body.pop(0)
        code = ast.unparse(tree).lower()
        for w in banned:
            assert w not in code, (f.__name__, w)


# ----------------------------------------------------------- the solver --
@pytest.fixture(scope="module")
def av():
    import stage_report as R
    S, a, body = R.avatar()
    tee, hooded = R.hooded_tee(S, a)
    return S, a, body, tee, hooded


def _sim(d, body, spacing=0.03, fabric="jersey"):
    from drape.fabrics import get, panel_fabrics
    from drape.freeform import build_design, editor_to_design
    from drape.springs import SpringSimulator
    g = build_design(editor_to_design(d), body, spacing=spacing)
    fab = get(fabric)
    return g, SpringSimulator(panel_fabrics(g, fab), body, fab, substeps=24)


def test_one_stage_is_bit_identical_to_before(av):
    """The guard: a garment with nothing attached runs the old code path, and the staged
    path with one stage gives exactly the same numbers (through the weld and gravity)."""
    _, _, body, tee, _ = av
    g, a = _sim(tee, body)
    _, b = _sim(tee, body)
    assert a.n_stages == 1 and a.extra_time == 0.0
    b._force_staged = True
    for _ in range(int(1.3 * a.fps)):
        a.step(); b.step()
    assert a.welded and b.welded
    assert np.array_equal(a.x, b.x) and np.array_equal(a.v, b.v)


def test_partial_weld_bookkeeping(av):
    _, _, body, _, hooded = av
    g, sim = _sim(hooded, body)
    assert sim.n_stages == 2 and sim.extra_time == pytest.approx(1.4)
    st0 = sim.seam_stage.copy()
    s2 = g.seams[st0 == 2]
    while sim.weld_stage < 1:
        sim.step()
    assert not sim.welded and len(sim.vmap) == len(g.x) and sim.vmap.max() < len(sim.x)
    want = {tuple(p) for p in sim.vmap[s2] if p[0] != p[1]}
    assert {tuple(p) for p in sim.g.seams} == want and set(sim.seam_stage) == {2}      # only stage 2, renumbered
    assert len(sim.seam_rest0) == len(sim.g.seams)
    m = sim.metrics()
    assert m["finite"] and m["weld_stage"] == 1 and m["n_stages"] == 2
    while not sim.welded:
        sim.step()
    _, once = _sim(hooded, body)
    once.weld()
    assert len(sim.x) == len(once.x) and len(sim.g.seams) == 0 and sim.weld_stage == 2
    assert sim.metrics()["seam_gap_max_mm"] < 1e-6


def test_pieces_wait_frozen_and_out_of_self_collision(av):
    _, _, body, _, hooded = av
    g, sim = _sim(hooded, body)
    hood = np.nonzero(sim._vstage == 2)[0]
    x0 = sim.x[hood].copy()
    orig = sim._prepare_staged
    seen = {"cands": 0}

    def checked(t):
        P = orig(t)
        if len(P["cand_v"]):
            seen["cands"] += len(P["cand_v"])
            fr = sim._frozen
            assert not fr[P["cand_v"]].any() and not fr[sim.g.tris[P["cand_t"]]].any()
        return P
    sim._prepare_staged = checked
    T = sim.timeline()
    while sim.time + 1 / sim.fps < T[1][0]:
        sim.step()
    hood_now = sim.vmap[hood]                  # (the stage-1 weld renumbered the vertices)
    # spec 2c, no re-arrangement: a piece waiting to be sewn is exactly where it was placed
    assert np.array_equal(sim.x[hood_now], x0)
    assert seen["cands"] > 0                   # self-collision ran (after the first weld), never on the hood
    assert sim._frozen[hood_now].all() and (sim.w[hood_now] == 0).all()
    sim.step(); sim.step()
    assert not sim._frozen.any() and (sim.w[hood_now] > 0).all()


def test_sewing_on_the_hood_hardly_moves_the_shirt(av):
    """Anchor weighting is for the seams only: during the hood's sewing, the shirt moves
    little and its stretch stays under the lock strain (it still has its real masses)."""
    _, _, body, _, hooded = av
    g, sim = _sim(hooded, body)
    T = sim.timeline()
    while sim.time < T[1][0]:
        sim.step()
    shirt = np.nonzero(sim._vstage == 1)[0]
    xs = sim.x[shirt].copy()
    while sim.time < T[1][0] + T[1][1]:
        sim.step()
    move = np.linalg.norm(sim.x[shirt] - xs, axis=1)
    assert np.percentile(move, 95) < 0.01 and move.max() < 0.04            # m
    e = sim.g.edges
    on = (sim._vstage[e[:, 0]] == 1) & (sim._vstage[e[:, 1]] == 1)
    L = np.linalg.norm(sim.x[e[on, 0]] - sim.x[e[on, 1]], axis=1)
    strain = (L - sim.g.edge_rest[on]) / sim.g.edge_rest[on]
    assert np.percentile(strain, 99) < np.percentile(sim._edge_lock()[on], 50)


def test_forcing_the_hood_into_stage_one_sews_it_all_at_once(av):
    import stage_report as R
    _, _, body, _, hooded = av
    g, sim = _sim(R.all_at_once(hooded), body)
    assert sim.n_stages == 1 and sim.extra_time == 0
    for _ in range(int(1.0 * sim.fps)):
        sim.step()
    assert sim.welded and sim.metrics()["finite"]


def test_a_pocket_set_to_stage_one_sews_with_the_body(av):
    from drape import starters
    S, a, body, _, _ = av
    d = starters.starter("pocket_tee", body, S.S.avatars[a]["meas"])
    g, sim = _sim(d, body)
    assert sim.n_stages == 3                      # tee, neckband, pocket
    for pc in d["pieces"]:
        if pc.get("role") == "pocket":
            pc["stage"] = 1
    g, sim = _sim(d, body)
    assert sim.n_stages == 2 and sim._vstage[g.panel_id == g.panel_names.index("chest_pocket")].max() == 1
    for _ in range(int(1.0 * sim.fps)):
        sim.step()
    assert sim.metrics()["finite"]


def test_progress_labels(av):
    _, _, body, _, hooded = av
    g, sim = _sim(hooded, body)
    labels = [sim.phase(t)[2] for t in (0.1, 1.0, 1.7, 2.6)]
    assert labels == ["Sewing the body", "Settling", "Attaching hood", "Draping"]


@pytest.mark.slow
def test_the_hoodie_fix(av):
    """Tee + 41 cm hood (curved crown) vs the tee alone: the shirt stays where it was."""
    import stage_report as R
    _, _, body, tee, hooded = av
    g0, s0 = R.drape(tee, body)
    g1, s1 = R.drape(hooded, body)
    c = R.compare(R.measures(g0, s0), R.measures(g1, s1))
    m = s1.metrics()
    assert c["neck_rise_cm"] < 1.0
    assert c["armhole_r_cm"] < 1.0 and c["armhole_l_cm"] < 1.0
    assert c["hem_rise_cm"] < 1.5
    assert m["penetrating_verts"] == 0 and m["strain_max_pct"] < 100
    assert c["extra_sim_s"] == pytest.approx(1.4, abs=0.05)
