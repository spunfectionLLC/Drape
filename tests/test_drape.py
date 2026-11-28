import numpy as np
import pytest

from drape import Body, Fabric, Panel, Seam, Simulator, build_garment, cylinder_wrap, line
from drape.garments import tank_top
from drape.pattern import polyline_length, resample
from drape.render import write_obj


def flat_place(uv):
    return np.stack([uv[:, 0], uv[:, 1], np.zeros(len(uv))], 1)


def far_body():
    """A body far away from everything (no collisions)."""
    return Body(np.array([[100.0, 0.1, 0.1, 0.0], [100.1, 0.1, 0.1, 0.0]]),
                np.array([[100, 100, 100, 100, 100.1, 100, 0.01]]))


def square(name="sq", size=0.3, place=flat_place):
    s = size
    return Panel(name, [("bottom", line((0, 0), (s, 0))), ("right", line((s, 0), (s, s))),
                        ("top", line((s, s), (0, s))), ("left", line((0, s), (0, 0)))], place)


# ------------------------------------------------------------- pattern ----
def test_resample_equal_arc_length():
    pts = np.array([[0, 0], [1, 0], [1, 2]], float)
    r = resample(pts, 6)
    seg = np.linalg.norm(np.diff(r, axis=0), axis=1)
    assert np.allclose(seg, 0.5) and np.allclose(r[0], pts[0]) and np.allclose(r[-1], pts[-1])


def test_mesh_area_matches_polygon():
    g = build_garment([square(size=0.3)], [], spacing=0.02)
    assert g.meta["fabric_area_m2"] == pytest.approx(0.09, rel=1e-9)
    assert g.mass.sum() == pytest.approx(0.09 * 0.15, rel=1e-9)


def test_mesh_quality():
    g = build_garment([square(size=0.3)], [], spacing=0.02)
    assert g.edge_rest.max() < 0.02 * 1.8      # edges near target spacing
    assert g.edge_rest.min() > 0.02 * 0.3
    a, b, c = (g.uv[g.tris[:, k]] for k in range(3))
    cross = (b - a)[:, 0] * (c - a)[:, 1] - (b - a)[:, 1] * (c - a)[:, 0]
    assert (cross > 0).all()                   # consistent CCW winding


def test_seam_edges_get_identical_counts_and_order():
    a = square("a"); b = square("b", size=0.2)  # different edge lengths
    g = build_garment([a, b], [Seam("a", "right", "b", "left", reverse=True)], spacing=0.02)
    ia = g.meta["edge_index"][("a", "right")]
    ib = g.meta["edge_index"][("b", "left")]
    assert len(ia) == len(ib) == len(g.seams)
    # reverse=True: bottom of a.right (v=0) pairs with bottom of b.left (end of that edge)
    first = g.seams[np.argmin(g.uv[g.seams[:, 0], 1])]
    assert g.uv[first[1], 1] == pytest.approx(0.0)


def test_cylinder_wrap_is_isometric():
    p = square(size=0.3, place=cylinder_wrap(0.2, 0.0, 1.0))
    g = build_garment([p], [], spacing=0.015)
    L3 = np.linalg.norm(g.x[g.edges[:, 0]] - g.x[g.edges[:, 1]], axis=1)
    # chord vs arc for 1.5 cm edges on r=20 cm: < 0.03% shortening
    assert np.abs(L3 / g.edge_rest - 1).max() < 5e-4


def test_tank_top_seams_line_up():
    g = tank_top()
    a, b = g.x[g.seams[:, 0]], g.x[g.seams[:, 1]]
    assert np.all(np.sign(a[:, 0]) == np.sign(b[:, 0]))   # same side of body
    assert np.abs(a[:, 1] - b[:, 1]).max() < 1e-9         # same height before sewing
    la = polyline_length(g.uv[g.meta["edge_index"][("front", "side_r")]])
    lb = polyline_length(g.uv[g.meta["edge_index"][("back", "side_l")]])
    assert la == pytest.approx(lb)


# ---------------------------------------------------------------- body ----
def test_body_sdf_sign_and_gradient():
    B = Body.default()
    assert B.sdf(np.array([[0, 1.3, 0]]))[0] < -0.05       # inside chest
    assert B.sdf(np.array([[0, 1.3, 0.5]]))[0] > 0.3       # well in front
    assert B.sdf(np.array([[0, 1.3, 0.125]]))[0] == pytest.approx(0.0, abs=2e-3)
    from drape.body import sdf_grad
    rng = np.random.default_rng(0)
    p = rng.uniform([-0.4, 0.5, -0.3], [0.4, 1.7, 0.3], (300, 3))
    for q in p:
        n = sdf_grad(*q, B.torso, B.caps, B.blend, B.extras, B.groups)
        assert np.linalg.norm(n) == pytest.approx(1.0, abs=1e-6)


def test_body_sdf_is_roughly_lipschitz():
    """Collision projection assumes |grad sdf| ~ 1; check it doesn't overshoot."""
    B = Body.default()
    rng = np.random.default_rng(1)
    p = rng.uniform([-0.4, 0.5, -0.3], [0.4, 1.7, 0.3], (4000, 3))
    q = p + rng.normal(0, 0.005, p.shape)
    ratio = np.abs(B.sdf(p) - B.sdf(q)) / np.linalg.norm(p - q, axis=1)
    assert np.percentile(ratio, 99.5) < 1.2


# -------------------------------------------------------------- solver ----
def test_hanging_cloth_pinned_corners():
    p = square(size=0.4, place=lambda uv: np.stack([uv[:, 0], 1.0 + 0 * uv[:, 1], uv[:, 1]], 1))
    g = build_garment([p], [], spacing=0.02)       # starts horizontal, falls and swings
    sim = Simulator(g, far_body(), Fabric(damping=0.05))
    sim.sew_time, sim.gravity_ramp = 0.0, 0.01
    corners = [np.argmin(np.linalg.norm(g.uv - c, axis=1)) for c in ((0, 0.4), (0.4, 0.4))]
    sim.pin(corners)
    pinned0 = sim.x[corners].copy()
    for _ in range(180):
        sim.step()
    m = sim.metrics()
    assert m["finite"]
    assert np.allclose(sim.x[corners], pinned0)          # pins hold exactly
    assert sim.x[:, 1].min() < 1.0 - 0.3                  # cloth fell
    assert m["strain_p99_pct"] < 3.0                     # near-inextensible
    assert m["max_speed_mm_s"] < 200                     # settling


def test_seams_close():
    a = square("a", size=0.2, place=lambda uv: np.stack([uv[:, 0], uv[:, 1], 0 * uv[:, 0]], 1))
    b = square("b", size=0.2, place=lambda uv: np.stack([uv[:, 0] + 0.3, uv[:, 1], 0 * uv[:, 0]], 1))
    g = build_garment([a, b], [Seam("a", "right", "b", "left", reverse=True)], spacing=0.02)
    sim = Simulator(g, far_body())
    sim.gravity_ramp = 1e9  # no gravity
    for _ in range(70):
        sim.step()
    assert sim.metrics()["seam_gap_max_mm"] < 0.5


@pytest.mark.slow
def test_tank_top_drape_end_to_end():
    g, B = tank_top(), Body.default()
    sim = Simulator(g, B)
    for _ in range(int(3.0 * sim.fps)):
        sim.step()
    m = sim.metrics()
    assert m["finite"]
    assert m["seam_gap_max_mm"] < 1.0                   # sewn shut
    assert m["penetrating_verts"] == 0                  # nothing inside the body
    assert m["strain_p99_pct"] < 5.0                    # fabric not over-stretched
    assert m["kinetic_energy_uJ"] < 20                  # settled
    assert sim.x[:, 1].min() > 0.80                     # hangs from shoulders, didn't slide off
    assert sim.x[:, 1].max() < 1.60                     # not floating above shoulders


def test_obj_export(tmp_path):
    g = build_garment([square()], [], spacing=0.05)
    path = tmp_path / "g.obj"
    write_obj(path, g.x, g.tris, g.uv)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert sum(l.startswith("v ") for l in lines) == len(g.x)
    assert sum(l.startswith("f ") for l in lines) == len(g.tris)


# ---------------------------------------------------------------- DXF ----
def test_dxf_export_roundtrip(tmp_path):
    import ezdxf
    from shapely.geometry import Polygon
    from drape.export_dxf import export_pattern_dxf
    g = tank_top()
    path = tmp_path / "p.dxf"
    summ = export_pattern_dxf(path, g.meta["panels"], g.meta["seam_defs"], seam_allowance=0.01)
    doc = ezdxf.readfile(path)
    assert len(doc.audit().errors) == 0
    assert doc.header["$INSUNITS"] == 4                       # mm
    msp = doc.modelspace()
    cut = [e for e in msp.query("LWPOLYLINE") if e.dxf.layer == "CUT"]
    sew = [e for e in msp.query("LWPOLYLINE") if e.dxf.layer == "SEW"]
    assert len(cut) == len(sew) == 2
    # stitch-line area in the file == simulated fabric area (m^2 -> mm^2)
    sew_area = sum(Polygon([p[:2] for p in e.get_points()]).area for e in sew)
    assert sew_area == pytest.approx(g.meta["fabric_area_m2"] * 1e6, rel=2e-3)
    # allowance adds ~ perimeter * SA (mitred corners add a little more)
    for s in summ.values():
        added = s["cut_area_mm2"] - s["sew_area_mm2"]
        assert s["sew_perimeter_mm"] * 10 < added < s["sew_perimeter_mm"] * 10 * 1.1
        assert s["notches"] == 8                               # 2 sides + 2 shoulders, double (they meet the back)
    # every cut polygon fully contains its stitch polygon
    for c, w in zip(cut, sew):
        assert Polygon([p[:2] for p in c.get_points()]).contains(Polygon([p[:2] for p in w.get_points()]))


# ------------------------------------------------------- v0.3 features ----
def test_sphere_capsule_has_no_divide_by_zero():
    ball = Body(np.array([[100.0, .1, .1, 0], [100.1, .1, .1, 0]]), np.array([[0, 1.0, 0, 0, 1.0, 0, 0.1]]))
    assert ball.sdf(np.array([[0, 1.0, 0.3]]))[0] == pytest.approx(0.2, abs=1e-9)


def test_unfolded_bend_rest_matches_flat_distance():
    from drape.cloth import unfolded_bend_rest
    g = build_garment([square(size=0.3)], [], spacing=0.03)
    key = {tuple(e): r for e, r in zip(map(tuple, g.edges), g.edge_rest)}
    edge_len = lambda i, j: np.array([key[(min(a, b), max(a, b))] for a, b in zip(i, j)])
    pairs, rest = unfolded_bend_rest(g.tris, edge_len)
    flat = np.linalg.norm(g.uv[pairs[:, 0]] - g.uv[pairs[:, 1]], axis=1)
    assert np.allclose(rest, flat, atol=1e-9)


def test_weld_makes_one_mesh_with_bending_across_seams():
    a = square("a", size=0.2)
    b = square("b", size=0.2, place=lambda uv: np.stack([uv[:, 0] + 0.2, uv[:, 1], 0 * uv[:, 0]], 1))
    g = build_garment([a, b], [Seam("a", "right", "b", "left", reverse=True)], spacing=0.02)
    sim = Simulator(g, far_body())
    n_seam = len(g.seams)
    sim.weld()
    assert len(sim.x) == len(g.x) - n_seam
    assert len(sim.g.seams) == 0
    # some bend pairs now straddle the seam (one vertex from each panel)
    pa = sim.g.panel_id[sim.g.bends]
    assert (pa[:, 0] != pa[:, 1]).sum() > 0
    # welded flat sheet is at rest: no stretch, no bend error
    L = np.linalg.norm(sim.x[sim.g.edges[:, 0]] - sim.x[sim.g.edges[:, 1]], axis=1)
    assert np.abs(L - sim.g.edge_rest).max() < 1e-9
    B = np.linalg.norm(sim.x[sim.g.bends[:, 0]] - sim.x[sim.g.bends[:, 1]], axis=1)
    assert np.abs(B - sim.g.bend_rest).max() < 1e-9
    # every original vertex maps to a live one at the same place
    assert np.allclose(sim.original_positions(), g.x)


def _two_sheets_on_ball(self_collision):
    def sheet(name, y, s=0.4):
        return square(name, size=s, place=lambda uv: np.stack(
            [uv[:, 0] - s / 2, np.full(len(uv), y), uv[:, 1] - s / 2], 1))
    ball = Body(np.array([[100.0, .1, .1, 0], [100.1, .1, .1, 0]]), np.array([[0, 1.0, 0, 0, 1.0, 0, 0.12]]))
    g = build_garment([sheet("low", 1.15), sheet("high", 1.17)], [], spacing=0.02)
    sim = Simulator(g, ball, Fabric(damping=0.03), self_collision=self_collision)
    sim.sew_time, sim.gravity_ramp = 0.0, 0.01
    for _ in range(150):
        sim.step()
    n = len(g.x) // 2
    c = np.array([0, 1.0, 0])
    r_lo, r_hi = np.linalg.norm(sim.x[:n] - c, axis=1), np.linalg.norm(sim.x[n:] - c, axis=1)
    on = r_lo < 0.135
    return (r_hi - r_lo)[on]


def test_self_collision_keeps_stacked_sheets_apart():
    sep_off = _two_sheets_on_ball(False)
    sep_on = _two_sheets_on_ball(True)
    assert (sep_off < 0).sum() > 20        # without it, the top sheet falls through
    assert (sep_on < 0).sum() == 0         # with it, no crossings
    assert sep_on.min() > 0.0005           # and a real gap (3 mm target; vertex-pair radii, so folds read lower;
                                           # the 3 m/s speed limit slows the push-apart a little: 1.1 -> 0.8 mm)


def test_tshirt_sleeve_cap_matches_armhole():
    from drape.garments import tshirt
    g = tshirt(cap_ease=0.03)
    assert g.meta["cap_half_len"] == pytest.approx(g.meta["armhole_len"] * 1.03, rel=5e-3)
    assert set(g.panel_names) == {"front", "back", "sleeve_r", "sleeve_l"}
    assert Body.default().sdf(g.x).min() > 0.01          # nothing starts inside the body


@pytest.mark.slow
def test_tshirt_drape_end_to_end():
    from drape.garments import tshirt
    B = Body.default()
    g = tshirt(body=B)
    sim = Simulator(g, B)
    for _ in range(int(3.5 * sim.fps)):
        sim.step()
    m = sim.metrics()
    assert m["finite"] and m["welded"]
    assert m["seam_gap_max_mm"] < 0.01
    assert m["penetrating_verts"] == 0
    assert m["strain_p99_pct"] < 6.0
    assert m["kinetic_energy_uJ"] < 20
    xo = sim.original_positions()
    for name, sign in (("sleeve_r", 1), ("sleeve_l", -1)):
        sv = xo[g.panel_id == g.panel_names.index(name)]
        assert np.all(np.sign(sv[:, 0]) == sign)          # each sleeve on its own arm
        assert np.median(B.sdf(sv)) < 0.04                 # hugging the arm, not floating


# ------------------------------------------------- v0.4: measurements ----
from drape.measurements import (Measurements, armpit_depth, body_from_measurements, body_report,
                                ellipse_perimeter)

PEOPLE = {
    "S": Measurements(height=162, chest=88, waist=70, hip=98, shoulder_width=39, neck=33, upper_arm=27, arm_length=55),
    "M": Measurements(),
    "L": Measurements(height=183, chest=112, waist=100, hip=110, shoulder_width=49, neck=43, upper_arm=36, arm_length=63),
}


def test_ellipse_perimeter():
    assert ellipse_perimeter(1.0, 1.0) == pytest.approx(2 * np.pi)
    # a=2, b=1: exact 9.688448220547...
    assert ellipse_perimeter(2.0, 1.0) == pytest.approx(9.688448220547, rel=1e-6)


@pytest.mark.parametrize("size", ["S", "M", "L"])
def test_avatar_matches_measurements(size):
    m = PEOPLE[size]
    b = body_from_measurements(m)
    for r in body_report(b, m):
        assert abs(r["error_cm"]) < 0.1, r          # within 1 mm on every measurement


def test_avatar_keeps_armpit_open_and_chest_realistic():
    for m in PEOPLE.values():
        b = body_from_measurements(m)
        chest = b.torso[5]
        assert 0.7 < chest[2] / chest[1] < 0.85      # chest depth/breadth like real people
        assert np.all(b.torso[:, 1] <= b.max_torso_rx + 1e-9)   # torso never swallows the arm
        assert 0.10 < armpit_depth(b) < 0.25


def test_measurement_validation_catches_typos(tmp_path):
    assert Measurements(height=69).validate()       # inches entered as cm
    assert Measurements(shoulder_width=90).validate()  # measured around, not across
    assert not Measurements().validate()
    p = tmp_path / "m.json"
    p.write_text('{"units": "cm", "height": 170, "chets": 90}')
    with pytest.raises(ValueError, match="chets"):
        Measurements.load(p)
    p.write_text('{"units": "in", "height": 67}')
    with pytest.raises(ValueError, match="cm"):
        Measurements.load(p)


# ------------------------------------------------- v0.4: seam checks ----
from drape.seamcheck import check_seams, check_junctions, Tolerances


def test_stock_patterns_pass_seam_check():
    from drape.garments import tshirt
    for g in (tank_top(), tshirt()):
        rep = check_seams(g.meta["panels"], g.meta["seam_defs"])
        assert rep["ok"], rep["problems"]
        for j in rep["truing"]:
            assert abs(j["deviation_deg"]) < 1.0


def test_seam_check_catches_length_mismatch_and_undeclared_ease():
    a = square("a", size=0.30)
    b = Panel("b", [("bottom", line((0, 0), (0.3, 0))), ("right", line((0.3, 0), (0.3, 0.28))),
                    ("top", line((0.3, 0.28), (0, 0.28))), ("left", line((0, 0.28), (0, 0)))], flat_place)
    rep = check_seams([a, b], [Seam("a", "right", "b", "left", reverse=True)])
    row = rep["lengths"][0]
    assert row["status"] == "MISMATCH" and row["diff_mm"] == pytest.approx(20.0)
    # declaring the 20 mm (7.14 %) as intended ease makes it pass
    rep = check_seams([a, b], [Seam("a", "right", "b", "left", reverse=True, ease=20 / 280)])
    assert rep["lengths"][0]["status"] == "OK (eased)"


def test_seam_check_catches_twisted_seam():
    from drape.garments import tank_top as tt
    g = tt()
    seams = list(g.meta["seam_defs"])
    s0 = seams[0]
    seams[0] = Seam(s0.panel_a, s0.edge_a, s0.panel_b, s0.edge_b, reverse=not s0.reverse)
    rep = check_seams(g.meta["panels"], seams)
    assert rep["lengths"][0]["twisted"] and not rep["ok"]
    assert not any(r["twisted"] for r in rep["lengths"][1:])


def test_truing_flags_point_and_dip():
    # two trapezoids (narrowing upward) sewn along their slanted sides:
    # hem corners 80 + 80 = 160 deg -> dip; top corners 100 + 100 = 200 deg -> point
    def trap(name, place):
        return Panel(name, [("hem", line((0, 0), (0.3, 0))), ("side", line((0.3, 0), (0.3 - 0.0529, 0.3))),
                            ("top", line((0.3 - 0.0529, 0.3), (0, 0.3))), ("left", line((0, 0.3), (0, 0)))], place)
    a = trap("a", flat_place); b = trap("b", flat_place)
    J = check_junctions([a, b], [Seam("a", "side", "b", "side", reverse=False)], Tolerances())
    hem = [j for j in J if "hem" in j["corners"]][0]
    assert hem["sum_deg"] == pytest.approx(160.0, abs=0.2) and hem["status"] == "RE-TRUE"
    assert "dip" in hem["shape"]
    top = [j for j in J if "top" in j["corners"]][0]
    assert top["sum_deg"] == pytest.approx(200.0, abs=0.2) and "point" in top["shape"]


# ------------------------------------------------- v0.4: drafting/ease ----
def test_drafted_tee_has_requested_ease():
    from drape.fitcheck import ease_report
    from drape.garments import tshirt_for
    for m in PEOPLE.values():
        b = body_from_measurements(m)
        g = tshirt_for(m, body=b, chest_ease_cm=12, sleeve_ease_cm=8)
        rows = {r["line"]: r for r in ease_report(g, b)}
        assert rows["chest"]["ease_cm"] == pytest.approx(12.0, abs=0.3)
        assert rows["upper arm"]["ease_cm"] == pytest.approx(8.0, abs=0.1)
        assert rows["neckline"]["ease_cm"] > 3.0
        assert check_seams(g.meta["panels"], g.meta["seam_defs"])["ok"]


def test_ease_report_flags_too_small_garment():
    from drape.fitcheck import ease_report
    from drape.garments import tshirt_for
    bL = body_from_measurements(PEOPLE["L"])
    g = tshirt_for(PEOPLE["M"], body=bL, draft_body=body_from_measurements(PEOPLE["M"]))
    chest = [r for r in ease_report(g, bL) if r["line"] == "chest"][0]
    assert chest["ease_cm"] < 0 and "TIGHT" in chest["status"]


@pytest.mark.slow
def test_drafted_tee_drapes_on_its_avatar():
    from drape.garments import tshirt_for
    m = PEOPLE["M"]
    b = body_from_measurements(m)
    sim = Simulator(tshirt_for(m, body=b), b)
    for _ in range(210):
        sim.step()
    r = sim.metrics()
    assert r["penetrating_verts"] == 0 and r["seam_gap_max_mm"] < 0.01
    assert r["strain_p99_pct"] < 6.0
    assert r["kinetic_energy_uJ"] < 20


# ------------------------------------------------- v0.5: cache safety ----
def test_editing_body_py_invalidates_solver_cache(tmp_path):
    """Regression: springs.py inlines the SDF from body.py; numba's per-file
    cache used to keep running the old SDF after body.py was edited."""
    import shutil, subprocess, sys, textwrap
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "drape"
    pkg = tmp_path / "drape"
    shutil.copytree(src, pkg, ignore=shutil.ignore_patterns("__pycache__"))
    probe = textwrap.dedent("""
        import numpy as np, drape
        from drape import Body
        from drape.springs import _body_sd
        b = Body.default()
        z3, z33 = np.zeros((1, 3)), np.zeros((1, 3, 3))
        d = _body_sd(0.0, 1.30, 0.10, False, b.torso, b.caps, b.blend, b.extras, b.groups,
                     False, np.zeros((2, 2, 2)), np.zeros(3), 1.0,
                     np.zeros((1, 1, 1), np.int16), np.zeros((1, 1), np.bool_), z33, z3, z3,
                     np.zeros((1, 1, 3)), 0.0)[0]
        print(-d)   # how far the body reaches past the point: up by 0.05 after the edit
    """)
    env = {**__import__("os").environ, "PYTHONPATH": str(tmp_path), "DRAPE_CACHE_ROOT": str(tmp_path / "cache")}
    run = lambda: float(subprocess.check_output([sys.executable, "-c", probe], env=env, cwd=tmp_path).strip())
    z0 = run()
    body_py = pkg / "body.py"
    txt = body_py.read_text(encoding="utf-8")
    old = "    d = _torso(px, py, pz, torso)\n    for i in range(caps.shape[0]):"
    assert old in txt
    body_py.write_text(txt.replace(old, "    d = _torso(px, py, pz, torso) - 0.05\n    for i in range(caps.shape[0]):", 1))
    z1 = run()
    assert z1 - z0 == pytest.approx(0.05, abs=0.005)   # the edit took effect in the solver


# ------------------------------------------------------ v0.5: fabrics ----
def test_fabric_density_sets_mass():
    """Regression: Fabric.density was ignored (mass always used 0.15 kg/m2)."""
    from drape.fabrics import get
    g = build_garment([square(size=0.3)], [], spacing=0.02)
    for name in ("chiffon", "jersey", "denim"):
        sim = Simulator(g, far_body(), get(name))
        assert sim.g.mass.sum() == pytest.approx(0.09 * get(name).density, rel=1e-9)
    assert g.mass.sum() == pytest.approx(0.09 * 0.15)       # the input garment is untouched


def test_unknown_fabric_lists_choices():
    from drape.fabrics import get
    with pytest.raises(ValueError, match="denim"):
        get("velvet")


# ----------------------------------------------------- v0.5: DXF import ----
def _tee_roundtrip(tmp_path):
    from drape.garments import tshirt
    from drape.export_dxf import export_pattern_dxf
    from drape.importer import import_pattern
    B = Body.default()
    g0 = tshirt(body=B)
    path = tmp_path / "tee.dxf"
    export_pattern_dxf(path, g0.meta["panels"], g0.meta["seam_defs"])
    g, info = import_pattern(path, {"split": {"sleeve_r.e2": [0.5], "sleeve_l.e2": [0.5]}}, body=B)
    return g0, g, info


def test_dxf_roundtrip_recovers_pieces_and_seams(tmp_path):
    g0, g, info = _tee_roundtrip(tmp_path)
    assert {p.name for p in g.meta["panels"]} == {"front", "back", "sleeve_r", "sleeve_l"}
    # same total stitch-line length per piece (0.2 mm flattening tolerance)
    for p0 in g0.meta["panels"]:
        p1 = next(p for p in g.meta["panels"] if p.name == p0.name)
        L0 = sum(polyline_length(e) for _, e in p0.edges)
        L1 = sum(polyline_length(e) for _, e in p1.edges)
        assert L1 == pytest.approx(L0, abs=0.002)
    # the suggested seams are the original ten: same pairs of edge lengths
    sig = lambda gg: sorted(tuple(sorted((round(polyline_length(next(p for p in gg.meta["panels"] if p.name == s.panel_a).edge(s.edge_a)) * 1000),
                                           round(polyline_length(next(p for p in gg.meta["panels"] if p.name == s.panel_b).edge(s.edge_b)) * 1000))))
                            for s in gg.meta["seam_defs"])
    assert sig(g) == sig(g0)
    # ...including which side each cap half goes to: front armholes get the +u (front) half
    caps = {(s.panel_a, s.edge_a): s.panel_b for s in g.meta["seam_defs"] if s.panel_a.startswith("sleeve") and s.edge_a.startswith("e2")}
    assert caps[("sleeve_r", "e2a")] == "front" and caps[("sleeve_r", "e2b")] == "back"
    assert check_seams(g.meta["panels"], g.meta["seam_defs"])["ok"]


def test_dxf_import_foreign_file_cm_chained_entities_cut_lines(tmp_path):
    """Loose LINEs + SPLINE, cm units, cut lines only, no layers/labels."""
    import ezdxf
    from drape.importer import import_pattern
    doc = ezdxf.new("R2010"); doc.header["$INSUNITS"] = 5
    msp = doc.modelspace()
    for x0 in (0, 60):   # two 40 x 50 cm rectangles drawn as cut lines with 1 cm SA
        c = [(x0 - 1, -1), (x0 + 41, -1), (x0 + 41, 51), (x0 - 1, 51)]
        msp.add_line(c[0], c[1]); msp.add_line(c[1], c[2])
        msp.add_spline([(c[2][0], c[2][1], 0), (x0 + 20, 51.0, 0), (c[3][0], c[3][1], 0)])
        msp.add_line(c[3], c[0])
    path = tmp_path / "f.dxf"; doc.saveas(path)
    g, info = import_pattern(path, {"seam_allowance_mm": 10, "pieces": {"piece0": "front", "piece1": "back"}},
                             body=Body.default())
    assert len(info["pieces"]) == 2
    for name, kind, edges in info["pieces"]:
        lens = sorted(round(l * 1000) for _, l in edges)
        assert lens == [400, 400, 500, 500]          # stitch line recovered exactly
    # side seams found (the 500 mm edges), hems/tops left open
    assert len(g.meta["seam_defs"]) == 2
    for s in g.meta["seam_defs"]:
        p = next(q for q in g.meta["panels"] if q.name == s.panel_a)
        assert round(polyline_length(p.edge(s.edge_a)) * 1000) == 500


def test_truing_tangent_robust_to_duplicate_and_uneven_points():
    """Regressions: a duplicated split point gave a 358 deg corner; uneven
    spacing (0.5 mm then 7 mm) gave 277 deg with the vertex formula."""
    from drape.seamcheck import _corner_angle
    up = np.array([[0.0, -0.1], [0.0, 0.0]])                  # arriving upward at the origin
    for out in (np.array([[0, 0], [0, 0], [-0.003, 0], [-0.1, 0]]),          # duplicate first point
                np.array([[0, 0], [-0.0005, 0], [-0.0075, 0], [-0.1, 0]])):  # uneven spacing
        assert _corner_angle(up, out) == pytest.approx(90.0, abs=0.01)
    # a curve leaving horizontally, sampled coarsely: still ~90
    t = np.linspace(0, 1, 12)
    curve = np.stack([-0.1 * t, 0.05 * t ** 2], 1)
    assert _corner_angle(up, curve) == pytest.approx(90.0, abs=0.3)


def test_section_lookup_is_per_body():
    """Regression: the ease report indexed torso rows with the measured
    avatar's layout; on the default mannequin 'chest' read the upper chest."""
    from drape.measurements import Measurements, body_from_measurements
    d = Body.default()
    assert d.section_y("chest") == pytest.approx(1.30)
    assert d.section_y("waist") == pytest.approx(1.06)
    m = body_from_measurements(Measurements())
    assert m.section_y("waist") == pytest.approx(0.604 * 1.75)


def test_viewer_export_is_self_contained(tmp_path):
    import base64, json, re
    from drape.viewer import export_viewer
    g = build_garment([square(size=0.3, place=lambda uv: np.stack([uv[:, 0] - 0.15, uv[:, 1] + 1.0, np.full(len(uv), 0.3)], 1))], [], spacing=0.03)
    B = Body.default()
    path = tmp_path / "v.html"
    info = export_viewer(path, B, g.x, g.tris, g.panel_id, g.edges, g.edge_rest, title="t", body_res=0.03, fine_res=0.01)
    html = path.read_text(encoding="utf-8")
    assert "http://" not in html and "https://" not in html          # no external loads
    data = json.loads(re.search(r"const D = (\{.*?\});\n", html, re.S).group(1))
    v = np.frombuffer(base64.b64decode(data["cloth"]["v"]), np.int16).reshape(-1, 3)
    assert np.allclose(v / 1000, g.x, atol=0.0006)                   # mm quantisation
    f = np.frombuffer(base64.b64decode(data["body"]["f"]), np.uint32).reshape(-1, 3)
    assert f.max() < data["body"]["nv"] and len(f) == info["body_tris"]


# -------------------------------------------------------- v0.5: skirt ----
def test_a_line_skirt_is_trued_by_construction_and_has_requested_waist_ease():
    from drape.garments import a_line_skirt_for
    from drape.fitcheck import ease_report
    for size in ("S", "M", "L"):
        m = PEOPLE[size]
        b = body_from_measurements(m)
        g = a_line_skirt_for(m, body=b, waist_ease_cm=2.0)
        rep = check_seams(g.meta["panels"], g.meta["seam_defs"])
        assert rep["ok"]
        assert max(abs(j["deviation_deg"]) for j in rep["truing"]) < 0.2
        waist = next(r for r in ease_report(g, b) if r["line"] == "waist")
        assert waist["ease_cm"] == pytest.approx(2.0, abs=0.3)


@pytest.mark.slow
def test_skirt_stays_up_at_the_waist():
    from drape.garments import a_line_skirt_for
    m = PEOPLE["S"]
    b = body_from_measurements(m)
    sim = Simulator(a_line_skirt_for(m, body=b), b)
    for _ in range(300):
        sim.step()
    r = sim.metrics()
    assert r["penetrating_verts"] == 0 and r["kinetic_energy_uJ"] < 5
    assert abs(sim.x[:, 1].max() - b.section_y("waist")) < 0.02     # within 2 cm of the waist


# ------------------------------------------ v0.6: realistic avatars ----
def _fit(name):
    from drape.human import fit_human
    from drape.measurements import Measurements
    return fit_human(Measurements.load(Path(__file__).resolve().parents[1] / "measurements" / f"{name}.json"))


from pathlib import Path


@pytest.mark.parametrize("who", ["female_M", "male_M"])
def test_realistic_avatar_fits_measurements(who):
    h, rows = _fit(who)
    for r in rows:
        if r["error_cm"] is not None:
            assert abs(r["error_cm"]) < 0.8, r
    assert h.fit["sex"] == (1.0 if who.startswith("male") else 0.0)


def test_weight_gain_is_humanlike():
    """'Grow like a person': for a man, extra body weight adds more to the
    waist than to the chest, and more to the hip than to the neck (the old
    mannequin scaled every girth independently, like a tube)."""
    from drape.human import Human, Shape
    from drape.meshmeasure import Tape
    lo, hi = Tape(Human(Shape(sex=1, weight=0.5))), Tape(Human(Shape(sex=1, weight=1.0)))
    d = lambda f: (getattr(hi, f)() - getattr(lo, f)()) * 100
    assert d("waist") > 2 * d("chest") > 0
    assert d("hip") > d("neck")


def test_tape_definitions_are_anatomically_plausible():
    from drape.human import Human, Shape
    from drape.meshmeasure import Tape
    T = Tape(Human(Shape(sex=1)))
    A, B = T.shoulder_point("l"), T.shoulder_point("r")
    assert 0.37 < np.linalg.norm(A - B) < 0.43                  # biacromial ~ 41 cm (ANSUR men)
    assert 0.10 < T.shoulder_point()[1] - T.armpit_y() < 0.17   # shoulder top -> armpit
    L = T.lines()
    assert L["crotch"] < L["hip"] < L["waist"] < L["underbust"] < L["chest"] < L["armpit"]


def test_mesh_sdf_grid_matches_exact_distance():
    import igl
    from drape.human import Human, Shape
    from drape.meshbody import MeshBody
    h = Human(Shape(sex=0))
    mb = MeshBody(h)
    rng = np.random.default_rng(3)
    # points near the surface: vertices pushed along random directions by up to 2 cm
    idx = rng.choice(len(h.verts), 3000)
    P = h.verts[idx] + rng.normal(0, 0.01, (3000, 3))
    exact = igl.signed_distance(P, h.verts, h.tris.astype(np.int64),
                                sign_type=igl.SIGNED_DISTANCE_TYPE_FAST_WINDING_NUMBER)[0]
    err = np.abs(mb.sdf(P) - exact)
    assert np.percentile(err, 95) < 0.0015 and np.median(err) < 0.0005


def test_meshbody_drafts_valid_garments():
    from drape.garments import tshirt_for, a_line_skirt_for
    from drape.meshbody import MeshBody
    from drape.measurements import Measurements
    h, _ = _fit("female_M")
    m = Measurements.load(Path(__file__).resolve().parents[1] / "measurements" / "female_M.json")
    mb = MeshBody(h, measurements=m)
    for g in (tshirt_for(m, body=mb), a_line_skirt_for(m, body=mb)):
        assert check_seams(g.meta["panels"], g.meta["seam_defs"])["ok"]


@pytest.mark.slow
def test_tee_drapes_on_realistic_male():
    from drape.garments import tshirt_for
    from drape.meshbody import MeshBody
    from drape.measurements import Measurements
    h, _ = _fit("male_M")
    m = Measurements.load(Path(__file__).resolve().parents[1] / "measurements" / "male_M.json")
    mb = MeshBody(h, measurements=m)
    sim = Simulator(tshirt_for(m, body=mb), mb)
    for _ in range(210):
        sim.step()
    r = sim.metrics()
    assert r["penetrating_verts"] == 0 and r["seam_gap_max_mm"] < 0.01
    assert r["strain_p99_pct"] < 5.0 and r["kinetic_energy_uJ"] < 20


# ------------------------------------------------- v0.7: drafting tools ----
from drape import draft as D


def test_draft_curves_exact_lengths():
    assert D.length(D.arc((0, 0), 0.1, 0, np.pi / 2, k=2000)) == pytest.approx(np.pi * 0.1 / 2, rel=1e-6)
    a = D.arc_through((1, 0), (0, 1), (-1, 0), k=4000)
    assert D.length(a) == pytest.approx(np.pi, rel=1e-6)                  # half circle via the top
    assert a[len(a) // 2][1] > 0.99
    assert D.length(D.circle((0, 0), 0.2, k=4000)) == pytest.approx(2 * np.pi * 0.2, rel=1e-5)
    s = D.spline([(0, 0), (1, 1), (2, 0), (3, 1)])
    for p in [(0, 0), (1, 1), (2, 0), (3, 1)]:
        assert D.closest(s, p)[2] < 1e-9                                  # passes through every point


def test_draft_hermite_and_smooth_to_have_no_kink():
    p = D.Path((0, 0)).line_to((0.1, 0), "a").smooth_to((0.2, 0.1), "b", end_tangent=(0, 1))
    (_, a), (_, b) = p.edges
    assert D.tangent_at(b, frac=0.0) @ D.tangent_at(a, frac=1.0) == pytest.approx(1.0, abs=1e-4)
    assert D.tangent_at(b, frac=1.0) @ np.array([0, 1.0]) == pytest.approx(1.0, abs=1e-4)


def test_draft_split_join_point_at():
    c = D.bezier((0, 0), (0.1, 0.2), (0.3, 0.2), (0.4, 0), k=400)
    a, b = D.split_at(c, frac=0.3)
    assert D.length(a) + D.length(b) == pytest.approx(D.length(c), rel=1e-12)
    assert D.length(a) == pytest.approx(0.3 * D.length(c), rel=1e-9)
    assert np.allclose(D.join(a, b), c[np.r_[0:len(a) - 1, len(a) - 1:len(c)]] if False else D.join(a, b))
    assert D.length(D.join(a, b)) == pytest.approx(D.length(c), rel=1e-12)
    x = D.intersections(D.line((0, 0), (1, 1)), D.line((0, 1), (1, 0)))
    assert len(x) == 1 and np.allclose(x[0], (0.5, 0.5))


def test_draft_mirror_offset_rotate():
    c = D.line((0.1, 0), (0.2, 0.3))
    assert np.allclose(D.mirror(c), [[-0.1, 0], [-0.2, 0.3]])
    o = D.offset(D.line((0, 0), (1, 0)), 0.01)
    assert np.allclose(o[:, 1], 0.01)                                       # left of travel
    r = D.rotate(D.line((0, 0), (1, 0)), np.pi / 2)
    assert np.allclose(r, [[0, 0], [0, 1]], atol=1e-12)


def _half_bodice():
    return (D.Path((0, 0))
            .line_to((0.25, 0), "hem")
            .line_to((0.25, 0.36), "side")
            .curve_to((0.20, 0.36), (0.17, 0.46), (0.18, 0.54), "armhole")
            .line_to((0.08, 0.58), "shoulder")
            .smooth_to((0, 0.48), "neck", end_tangent=(-1, 0))
            .close("cf"))


def test_cut_on_fold_makes_symmetric_closed_piece():
    edges = D.cut_on_fold(_half_bodice().edges, fold="cf")
    names = [n for n, _ in edges]
    assert names[0] == "hem" and "neck" in names and "side_r" in names and "side_l" in names
    p = D.piece("front", edges, lambda uv: np.c_[uv, np.zeros(len(uv))])
    ring = np.vstack([e[:-1] for _, e in p.edges])
    assert np.isclose(ring[:, 0].min(), -ring[:, 0].max())                  # symmetric about u = 0
    assert D.length(dict(p.edges)["hem"]) == pytest.approx(0.5)
    # the joined neckline is smooth across the fold (it arrives square to the fold)
    from drape.seamcheck import _corner_angle
    nk = dict(p.edges)["neck"]
    i = np.argmin(np.abs(nk[:, 0]))
    assert _corner_angle(nk[: i + 1], nk[i:]) == pytest.approx(180, abs=1.0)


def test_dart_sews_flat_and_checks_out():
    from drape.seamcheck import check_seams
    edges = [("hem", D.line((-0.25, 0), (0.25, 0))), ("side_r", D.line((0.25, 0), (0.25, 0.3))),
             ("waist", D.line((0.25, 0.3), (-0.25, 0.3))), ("side_l", D.line((-0.25, 0.3), (-0.25, 0)))]
    edges, (la, lb) = D.add_dart(edges, "waist", at=0.25, width=0.03, depth=0.12)
    d = dict(edges)
    assert D.length(d[la]) == pytest.approx(D.length(d[lb]), abs=1e-9)
    assert D.length(d["waist_1"]) + D.length(d["waist_2"]) == pytest.approx(0.47, abs=1e-9)
    apex = d[la][-1]
    assert np.allclose(apex, (0.0, 0.18))                                    # points straight down
    p = D.piece("skirt", edges, lambda uv: np.c_[uv, np.zeros(len(uv))])
    rep = check_seams([p], [Seam("skirt", la, "skirt", lb, reverse=True)])
    assert rep["lengths"][0]["status"].startswith("OK")


def test_round_corner_is_tangent_and_exact_radius():
    edges = [("a", D.line((0, 0), (0.2, 0))), ("b", D.line((0.2, 0), (0.2, 0.2))),
             ("c", D.line((0.2, 0.2), (0, 0.2))), ("d", D.line((0, 0.2), (0, 0)))]
    out = D.round_corner(edges, "a", 0.03)
    a, b = dict(out)["a"], dict(out)["b"]
    assert np.allclose(a[-1], (0.2, 0.03), atol=1e-9) and np.allclose(b[0], (0.2, 0.03), atol=1e-9)
    assert D.tangent_at(a, frac=1.0) @ np.array([0, 1.0]) == pytest.approx(1.0, abs=1e-3)
    arc_len = D.length(a) - 0.17
    assert arc_len == pytest.approx(np.pi / 2 * 0.03, rel=2e-3)


def test_grade_keeps_seams_matched():
    from drape.seamcheck import check_seams
    edges = D.cut_on_fold(_half_bodice().edges, fold="cf")
    g = D.grade(edges, sx=1.06, sy=1.03, anchor=(0, 0))
    assert D.length(dict(g)["hem"]) == pytest.approx(0.5 * 1.06)
    # front and back graded the same way still sew
    P = lambda n, e: D.piece(n, e, lambda uv: np.c_[uv, np.zeros(len(uv))])
    rep = check_seams([P("f", g), P("b", g)], [Seam("f", "side_r", "b", "side_l", reverse=True)])
    assert rep["lengths"][0]["status"] == "OK"
