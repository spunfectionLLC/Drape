"""Velocity-level contacts and strain limiting in the springs solver
(docs/specs/SPRING_VELOCITY_LEVEL_SPEC.md): positions change only by x += h v,
nothing sets a velocity from a position change, and the cloth still locks, holds
on the body, grips with friction and swings like it has weight."""
import inspect
import re
import sys
from pathlib import Path

import numpy as np
import pytest

from drape import springs
from drape.springs import SpringSimulator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import _vel_helpers as V   # noqa: E402


# --- design guards (spec section 0): these tests exist to prove
# the springs path never derives a velocity from positions. Don't loosen them.
def _check_follows(sim, frames):
    sim.debug_check = True
    for _ in range(frames):
        sim.step()
    assert sim.debug_residual < 1e-12, sim.debug_residual       # x_new == x_old + h v_new
    assert sim.debug_ke_gain <= 1e-12, sim.debug_ke_gain         # the strain step never adds energy
    assert sim.metrics()["finite"]


def test_positions_follow_velocities_with_contacts_and_friction():
    sim, _ = V.sleeve_on_arm(SpringSimulator, 0.4, ease=0.0, seconds=0.2)
    _check_follows(sim, 20)


def test_positions_follow_velocities_cloth_on_cloth():
    sim = _fling(frames=0)
    _check_follows(sim, 12)
    assert sim.self_hits > 0 or sim.metrics()["finite"]


@pytest.mark.slow
def test_positions_follow_velocities_tee_2s():
    from test_drape import PEOPLE
    from drape.garments import tshirt_for
    from drape.measurements import body_from_measurements
    m = PEOPLE["M"]
    b = body_from_measurements(m)
    sim = SpringSimulator(tshirt_for(m, body=b), b)
    _check_follows(sim, 120)


def test_no_velocity_from_a_position_difference_in_the_source():
    """Static guard: no position difference divided by h, no xprev, and no velocity
    assignment that reads positions, in the springs substep and impulse kernels."""
    fns = (springs._spring_substeps, springs._strain_impulses, springs._body_impulses,
           springs._self_impulses, springs._sphere_impulses)
    diff_over_h = re.compile(r"\(\s*x\w*\[[^\]]*\]\s*-\s*\w+\[[^\]]*\]\s*\)\s*/\s*h\b")
    v_from_x = re.compile(r"^\s*v\[[^\]]*\]\s*[-+*]?=.*\bx0?\[")
    for f in fns:
        src = inspect.getsource(f)
        code = "\n".join(l.split("#")[0] for l in src.splitlines())
        code = re.sub(r'"""[\s\S]*?"""', "", code)
        assert "xprev" not in code and "x_old" not in code and "x_new" not in code, f.__name__
        assert not diff_over_h.search(code), f.__name__
        for line in code.splitlines():
            assert not v_from_x.search(line), (f.__name__, line)
    assert not hasattr(springs, "_strain_limit")     # the position clamp is gone


# ------------------------------------------------------------- behaviour --
def test_strain_still_locks():
    """30 x 30 cm poplin (locks at 4%), top edge held, a 50 g weight on its bottom edge."""
    sim, worst = V.hanging_load(SpringSimulator)
    assert worst <= 0.045, worst
    assert sim.safety_total == 0 and sim.metrics()["finite"]


def test_friction_holds_a_sleeve_on_a_tilted_arm_and_lets_it_slide_when_slippery():
    _, held = V.sleeve_on_arm(SpringSimulator, 0.4, ease=0.0)
    _, slid = V.sleeve_on_arm(SpringSimulator, 0.05, ease=0.0)
    assert abs(held) < 0.005, held
    assert slid > 0.05, slid


def _fling(frames=30):
    from drape.fabrics import get
    from test_v17_speed import _two_sheets
    g = _two_sheets()
    sim = SpringSimulator(g, V.far_body(), get("jersey"), weld=False)
    sim.speed_substeps = True
    sim.sew_time, sim.gravity_ramp = 0.0, 1e9          # no sewing, no gravity
    sim.v[g.panel_id == 0] = [0.0, -3.0, 0.0]          # the top sheet flies at the bottom one
    sim._worst = 0
    for _ in range(frames):
        sim.step()
        sim._worst = max(sim._worst, _cross(sim))
    return sim


def _cross(sim):
    from test_v17_speed import _crossings
    return _crossings(sim.x, sim.g)


def test_fast_sheets_dont_tunnel():
    sim = _fling()
    assert sim._worst == 0
    assert sim.metrics()["finite"] and sim.safety_total == 0


def test_hanging_sheet_settles():
    from drape.fabrics import get
    from test_v18 import _pin_top_corners, _sheet_garment
    sim = SpringSimulator(_sheet_garment(), V.far_body(), get("jersey"))
    _pin_top_corners(sim)
    for _ in range(180):
        sim.step()
    assert sim.metrics()["kinetic_energy_uJ"] < 20


@pytest.mark.slow
def test_tee_holds_on_the_body_with_no_safety_pushes():
    from test_drape import PEOPLE
    from drape.garments import tshirt_for
    from drape.measurements import body_from_measurements
    m = PEOPLE["M"]
    b = body_from_measurements(m)
    sim = SpringSimulator(tshirt_for(m, body=b), b)
    late = 0
    for k in range(210):
        sim.step()
        if k >= 150:
            late += sim.safety_pushes
    r = sim.metrics()
    assert r["penetrating_verts"] == 0 and late == 0
    assert r["seam_gap_max_mm"] < 0.01 and r["strain_p99_pct"] < 6.0 and r["kinetic_energy_uJ"] < 20


@pytest.mark.slow
def test_gloves_few_safety_pushes():
    from drape.fabrics import get
    from drape.freeform import build_design, editor_to_design
    from drape.gloves import glove_design
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
    assert sim.safety_total <= 5 and sim.metrics()["penetrating_verts"] == 0


@pytest.mark.slow
def test_it_still_swings_like_it_has_weight():
    """A 50 cm strip let go from 20 degrees: a hanging strip's period is about 1.2 s."""
    T, _ = V.pendulum(SpringSimulator)
    assert abs(T - 1.2) < 0.12, T


# ------------------------------------------- C2: no contact filtering in CG --
def test_no_contact_filter_or_projection_inside_the_implicit_solve():
    """Design rule 2: contacts stay separate velocity impulses after
    the solve; nothing inside CG reads the body, the contact lists or a filter/projection.
    (Pinned and frozen points, w = 0, are left out of the system by their mass.)"""
    import inspect
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[1]
    from drape import springs
    for f in (springs._implicit_dv, springs._apply_K, springs._spring_frames):
        src = inspect.getsource(f.py_func if hasattr(f, "py_func") else f)
        for word in ("_body_sd", "sdf", "bnorm", "ws_bn", "ws_bf", "touched", "cand_", "_self_impulses",
                     "_body_impulses", "_sphere_impulses", "sp_i", "filter", "project", "pushed"):
            assert word not in src, (f.__name__, word)
    js = (ROOT / "drape" / "studio" / "static" / "live_springs.js").read_text(encoding="utf-8")
    cg = js[js.index("// 2a. per vertex row"):js.index("// 3. strain limit")]
    for word in ("SDF", "sdf(", "DVA", "CAND", "cand", "selfimp", "eeimp", "filter", "project"):
        assert word not in cg, word
