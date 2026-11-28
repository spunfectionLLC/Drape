"""The mass-spring solver (springs.py, SPRING_SOLVER_SPEC.md): stability-limited
substeps, never exploding, the fit bars XPBD had, and no XPBD code path in it."""
from pathlib import Path

import numpy as np
import pytest

from drape.springs import (SAFETY, SpringSimulator, _spring_forces, gershgorin_omega, plan_stable)

ROOT = Path(__file__).resolve().parents[1]


def _far_body():
    from drape.measurements import Measurements, body_from_measurements
    return body_from_measurements(Measurements.load(ROOT / "measurements" / "male_M.json"))


def _sheet_garment(n_sheets=1, size=0.20, spacing=0.02, seam=False):
    """Vertical sheets 3 m up (nowhere near the body); with seam=True two of them side
    by side, 2 cm apart, sewn along the gap."""
    from drape.pattern import Panel, Seam, build_garment
    c = np.array([[0, 0], [size, 0], [size, size], [0, size]], float)

    def sheet(name, x0):
        edges = [(f"e{k}", np.stack([c[k], c[(k + 1) % 4]])) for k in range(4)]
        return Panel(name, edges, lambda uv, x0=x0: np.c_[uv[:, 0] + x0, uv[:, 1] + 3.0, np.zeros(len(uv))])
    if seam:
        return build_garment([sheet("a", -size - 0.01), sheet("b", 0.01)], [Seam("a", "e1", "b", "e3", reverse=True)], spacing=spacing)
    return build_garment([sheet("a", -size / 2)], [], spacing=spacing)


def _pin_top_corners(sim):
    x = sim.x
    top = x[:, 1] > x[:, 1].max() - 1e-6
    idx = np.nonzero(top)[0]
    sim.pin([idx[np.argmin(x[idx, 0])], idx[np.argmax(x[idx, 0])]])


# ------------------------------------------------------------ the bound --
def test_gershgorin_is_exact_for_a_chain():
    n, k, m = 200, 300.0, 3e-5
    S = np.stack([np.arange(n - 1), np.arange(1, n)], 1)
    om, _ = gershgorin_omega(np.full(n, 1 / m), S, np.full(n - 1, k))
    assert om == pytest.approx(2 * np.sqrt(k / m), rel=1e-12)
    K = np.zeros((n, n))                    # 1-D chain: the true top frequency
    for i, j in S:
        K[i, i] += k; K[j, j] += k; K[i, j] -= k; K[j, i] -= k
    true = np.sqrt(np.linalg.eigvalsh(K / m).max())
    assert om == pytest.approx(true, rel=0.01)


def _free_sheet(nx=6, k=300.0, m=3e-5, a=0.02):
    """A free square sheet of springs (grid + diagonals) and its true top frequency."""
    P = np.array([[i * a, j * a, 0.0] for j in range(nx) for i in range(nx)])
    S = []
    for j in range(nx):
        for i in range(nx):
            v = j * nx + i
            if i + 1 < nx: S.append((v, v + 1))
            if j + 1 < nx: S.append((v, v + nx))
            if i + 1 < nx and j + 1 < nx: S.append((v, v + nx + 1))
            if i > 0 and j + 1 < nx: S.append((v, v + nx - 1))
    S = np.array(S)
    rest = np.linalg.norm(P[S[:, 0]] - P[S[:, 1]], axis=1)
    n = len(P)
    K = np.zeros((3 * n, 3 * n))            # linearised at rest: k d d^T blocks
    for (i, j), r in zip(S, rest):
        d = (P[i] - P[j]) / r
        B = k * np.outer(d, d)
        for p_, q_, s_ in ((i, i, 1), (j, j, 1), (i, j, -1), (j, i, -1)):
            K[3 * p_:3 * p_ + 3, 3 * q_:3 * q_ + 3] += s_ * B
    om_true = np.sqrt(max(np.linalg.eigvalsh(K / m).max(), 0))
    return P, S, rest, np.full(len(S), k), np.full(n, 1 / m), om_true


def _integrate(P, S, rest, sk, w, h, steps):
    """Plain symplectic Euler on the springs alone (no clamp, no collisions)."""
    rng = np.random.default_rng(0)
    x = P + rng.normal(0, 1e-5, P.shape)
    v = np.zeros_like(x)
    F = np.zeros_like(x)
    z = np.zeros((0, 4), np.int64); zf = np.zeros(0); z4 = np.zeros((0, 4)); z3 = np.zeros((0, 3), np.int64); z33 = np.zeros((0, 3))
    for _ in range(steps):
        _spring_forces(x, F, S, rest, sk, z, z4, zf, zf, np.zeros(0, np.int64), z3, z33, zf, zf)
        v += h * w[:, None] * F
        x += h * v
        if not np.isfinite(x).all() or np.abs(x - P).max() > 1.0:
            return False
    return True


def test_the_planned_step_is_stable_and_just_past_the_limit_blows_up():
    P, S, rest, sk, w, om_true = _free_sheet()
    om, _ = gershgorin_omega(w, S, sk)
    assert om >= om_true                                       # it's a bound
    assert not _integrate(P, S, rest, sk, w, 1.05 * 2 / om_true, 600 * 10)
    assert _integrate(P, S, rest, sk, w, SAFETY * 2 / om, 600 * 10)


def test_plan_stable_softens_past_the_cap():
    n, ks = plan_stable(1e5, 60, max_substeps=20)
    assert n == 20 and ks < 1
    need = 1e5 / 60 / (2 * SAFETY)
    assert np.sqrt(ks) * need == pytest.approx(20)             # omega ~ sqrt(k): exactly on the cap
    assert plan_stable(1000, 60) == (int(np.ceil(1000 / 60 / 1.4)), 1.0)


# ------------------------------------------------------------ the solver --
def test_never_explodes_when_the_substeps_are_capped():
    from drape.fabrics import get
    from drape.cloth import MAX_SPEED
    sim = SpringSimulator(_sheet_garment(), _far_body(), get("poplin"), max_substeps=20, implicit=False)
    _pin_top_corners(sim)
    for _ in range(120):
        sim.step()
    m = sim.metrics()
    assert m["stiffness_scale"] < 1 and m["finite"]
    assert m["max_speed_mm_s"] <= MAX_SPEED * 1000 + 1e-6


def test_hanging_sheet_settles():
    from drape.fabrics import get
    sim = SpringSimulator(_sheet_garment(), _far_body(), get("jersey"))
    _pin_top_corners(sim)
    for _ in range(180):
        sim.step()
    m = sim.metrics()
    assert m["finite"] and m["kinetic_energy_uJ"] < 20 and m["stiffness_scale"] == 1.0
    assert m["strain_p99_pct"] < 31                             # jersey locks at 30%


def test_substeps_replan_at_the_weld():
    from drape.fabrics import get
    sim = SpringSimulator(_sheet_garment(seam=True), _far_body(), get("jersey"), implicit=False)
    before, after = set(), set()
    for _ in range(int(sim.sew_time * sim.fps) + 6):
        was = sim.welded
        sim.step()
        (after if sim.welded else before).add(sim.nsub_stable)
        if sim.welded and not was:
            assert list(sim._omega_cache) == [(True, False)]    # cleared at the weld, then refilled
    assert before and after and before != after
    assert sim.metrics()["seam_gap_max_mm"] < 0.01


def test_no_xpbd_code_path_in_springs():
    src = (ROOT / "drape" / "springs.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    body = code[code.index("from __future__"):]                  # past the module docstring
    for name in ("_solve_edges", "_solve_dist", "_solve_hinges", "_solve_attach", "_substeps(", "elam", "blam", "lam"):
        assert name not in body.replace("_spring_substeps(", ""), name


# ------------------------------------------------------- fit parity (slow) --
@pytest.mark.slow
def test_tee_fits():
    import sys
    sys.path.insert(0, str(ROOT / "tests"))
    from test_drape import PEOPLE
    from drape.garments import tshirt_for
    from drape.measurements import body_from_measurements
    m = PEOPLE["M"]
    b = body_from_measurements(m)
    sim = SpringSimulator(tshirt_for(m, body=b), b)
    for _ in range(210):
        sim.step()
    r = sim.metrics()
    assert r["penetrating_verts"] == 0 and r["seam_gap_max_mm"] < 0.01
    assert r["strain_p99_pct"] < 6.0 and r["kinetic_energy_uJ"] < 20


@pytest.mark.slow
def test_gloves_fit():
    from drape.fabrics import get
    from drape.freeform import build_design, editor_to_design
    from drape.gloves import _joint, glove_design
    from drape.human import fit_human
    from drape.measurements import Measurements
    from drape.meshbody import MeshBody
    m = Measurements.load(ROOT / "measurements" / "male_L.json")
    h, _ = fit_human(m)
    body = MeshBody(h, measurements=m)
    g = build_design(editor_to_design(glove_design(body, m, "gloves")), body)
    sim = SpringSimulator(g, body, get("jersey"))
    for _ in range(int(2.5 * sim.fps)):
        sim.step()
    mt = sim.metrics()
    assert mt["welded"] and mt["penetrating_verts"] == 0 and mt["seam_gap_max_mm"] < 0.01
    x, e = sim.x, sim.g.edges
    s = (np.linalg.norm(x[e[:, 0]] - x[e[:, 1]], axis=1) - sim.g.edge_rest) / sim.g.edge_rest
    mid = x[e].mean(1)

    def near(a, b):
        a, b = np.asarray(_joint(body, a)), np.asarray(_joint(body, b))
        t = np.clip(((mid - a) @ (b - a)) / ((b - a) @ (b - a)), 0, 1)
        return np.linalg.norm(mid - (a + t[:, None] * (b - a)), axis=1)
    thumb = np.min([near(f"r-finger-1-{i}", f"r-finger-1-{i + 1}") for i in (1, 2, 3)], 0) < 0.015
    assert np.percentile(s[thumb], 95) < 0.25
    assert np.percentile(s, 95) < 0.15


# ------------------------------------------------------- hems cut on --
def _hem_panel(bottom, top, h=55.0, style="double", depth=3.0, turn=1.0):
    """A trapezoid piece (cm in, m out) hemmed along its bottom edge."""
    from drape.hems import normalise
    from drape.pattern import Panel
    c = np.array([[-bottom / 2, 0], [bottom / 2, 0], [top / 2, h], [-top / 2, h]]) / 100
    edges = [(n, np.stack([c[k], c[(k + 1) % 4]])) for k, n in enumerate(["hem", "right", "top", "left"])]
    return Panel("p", edges, lambda uv: uv, hems={"hem": normalise({"style": style, "depth_cm": depth, "turn_cm": turn})})


def _width(poly, y):
    from shapely.geometry import LineString
    return poly.intersection(LineString([(-500, y), (500, y)])).length


@pytest.mark.parametrize("bottom, top", [(60, 40), (40, 60), (50, 50)])   # flared, tapered, straight
def test_hem_turn_up_is_the_mirror_of_the_piece(bottom, top):
    """Folded up along the hem line, the cut-on allowance lands exactly on the piece
    (side seam allowances included): its raw edge is as wide as the cut 4 cm up."""
    from drape.closures import cut_polygon
    cut = cut_polygon(_hem_panel(bottom, top), 1.5)
    assert np.asarray(cut.exterior.coords)[:, 1].min() == pytest.approx(-4.0, abs=1e-6)
    assert _width(cut, -3.999) == pytest.approx(_width(cut, 3.999), abs=0.02)
    assert _width(cut, -0.001) == pytest.approx(_width(cut, 0.001), abs=0.02)        # no step at the fold


def test_hem_marks_and_styles():
    from drape.hems import STYLES, fold_marks, normalise
    E = np.array([[0, 0], [50, 0]], float)
    assert len(fold_marks(E, normalise({"style": "double"}))) == 2                     # the hem line and the turn-under
    assert len(fold_marks(E, normalise({"style": "single"}))) == 1
    assert normalise({"style": "narrow"}) == {"style": "narrow", "depth_cm": 0.6, "turn_cm": 0.6}
    assert {"double", "single", "narrow", "blind", "casing"} <= set(STYLES)


def test_curved_hems_too_deep_to_lie_flat_are_caught():
    from drape.hems import curve_excess, max_flat_depth
    t = np.linspace(np.pi, 2 * np.pi, 41)
    arc = np.stack([30 * np.cos(t), 30 * np.sin(t)], 1)                                  # a 30 cm radius curve, bulging out
    assert curve_excess(arc, 4.0) > 0.1                                                  # a 4 cm hem ripples
    d = max_flat_depth(arc)
    assert 1.0 < d < 2.0 and curve_excess(arc, d) == pytest.approx(0.05, abs=0.002)


def test_studio_has_the_hem_tool():
    from drape.studio.server import studio_source, api_init
    src = studio_source()
    for needle in ("data-hem=", "function setHem", "hem: e.hem || undefined", "hem turn-up, cut on"):
        assert needle in src, needle
    assert set(api_init()["hem_styles"]) >= {"double", "casing"}


@pytest.mark.slow
def test_hemmed_design_builds_with_folds_steps_and_checks():
    from drape import dedit as E
    from drape.closures import cut_polygon
    from drape.freeform import build_design, design_check, editor_to_design
    from drape.instructions import instructions
    from drape.studio import server as S
    init = S.api_init()
    a = S.api_avatar({"measurements": init["examples"]["female_M"]})
    body = S.S.avatars[a["id"]]["body"]
    sk = E.rect("skirt", 110, 55)
    sk["place"] = {"landmark": "waist_front", "at": "top", "mode": "wrap", "rotate": 0, "offset_cm": 1.5}
    sk["edges"][0]["hem"] = {"style": "double", "depth_cm": 3, "turn_cm": 1}           # bottom
    sk["edges"][2]["hem"] = {"style": "casing", "depth_cm": 3, "turn_cm": 1}           # top: an elastic casing
    sk["edges"][2]["elastic"] = True
    d = {"pieces": [sk], "seams": [{"a": "skirt.right", "b": "skirt.left", "ease": 0}]}
    g = build_design(editor_to_design(d), body)
    p = g.meta["panels"][0]
    assert set(p.hems) == {"bottom", "top"} and sum(m["kind"] == "fold" for m in p.marks) == 4
    plain = cut_polygon(type(p)(p.name, p.edges, p.place), 1.5)
    # two 4 cm turn-ups replace two 1.5 cm allowances, each as wide as the piece plus its side allowances
    assert cut_polygon(p, 1.5).area - plain.area == pytest.approx((110 + 2 * 1.5) * (4 - 1.5) * 2, rel=1e-3)
    steps = " ".join(s["title"] + " " + s["text"] for s in instructions(g))
    assert "Double-fold hem" in steps and "3 cm deep, 1 cm turned under first" in steps and "Elastic casing" in steps
    assert design_check(g)[0]["ok"]
    d["seams"].append({"a": "skirt.bottom", "b": "skirt.top", "ease": 0})                # a hemmed edge sewn: flagged
    assert any("hemmed and sewn" in c["text"] for c in design_check(build_design(editor_to_design(d), body)))
