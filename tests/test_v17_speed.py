"""Speed-based substeps: substeps follow the fastest point, so fast cloth can't
tunnel through itself between self-collision checks (SPEED_SUBSTEPS_SPEC.md)."""
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from drape.cloth import MAX_SPEED, NSUB_CAP, plan_substeps
from drape import Simulator

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------ the planner --
@pytest.mark.parametrize("v, nsub", [(0.3, 24), (1, 24), (2, 45), (3, 67), (5, 96)])
def test_planner_reproduces_the_worked_numbers(v, nsub):
    n, se, vc, limited = plan_substeps(v, 60, 24, 1, 0.003, cap=96)
    assert n == nsub and se == 1
    if v == 5:   # over the cap: the cloth is slowed so the rule still holds at 96
        assert limited and vc == pytest.approx(96 * 60 * 0.5 * 0.003 / 2)
        assert min(MAX_SPEED, vc) == MAX_SPEED          # 4.32 m/s: the 3 m/s cap is the tighter one
    else:
        assert not limited and vc == math.inf


def test_slow_frames_keep_the_base_count_and_self_every():
    assert plan_substeps(0.3, 60, 24, 2, 0.003, cap=96)[:2] == (24, 2)
    assert plan_substeps(0.6, 60, 24, 2, 0.003, cap=96)[:2] == (24, 1)   # faster: check every substep first


def test_hysteresis_rises_at_once_and_falls_by_a_quarter_at_most():
    seq, prev = [], None
    for v in [5] + [0.1] * 8:
        prev = plan_substeps(v, 60, 24, 2, 0.003, cap=96, prev=prev)[0]
        seq.append(prev)
    assert seq[0] == 96 and seq[-1] == 24
    for a, b in zip(seq, seq[1:]):
        assert b >= math.ceil(0.75 * a - 1e-9) or b == 24


def test_live_planner_matches_the_cpu_one():
    node = shutil.which("node")
    if not node:
        pytest.skip("no node")
    src = (ROOT / "drape" / "studio" / "static" / "live_springs.js").read_text(encoding="utf-8")
    a = src.index("const SPEED_SAFETY"); b = src.index("\n}\n", src.index("function planSubsteps")) + 3
    cases = [(v, base, se, prev) for v in (0, 0.3, 0.6, 1, 2, 3, 5, 9) for base in (24, 40) for se in (1, 2) for prev in (None, 60)]
    js = src[a:b] + "\nconsole.log(JSON.stringify(" + str([list(c) for c in cases]).replace("None", "null") + \
        ".map(([v, b, s, p]) => { const r = planSubsteps(v, 60, b, s, 0.003, 96, p); return [r.nsub, r.se, r.limited] })))"
    out = subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout
    import json
    assert json.loads(out) == [list(plan_substeps(v, 60, b, s, 0.003, cap=96, prev=p)[:2]) + [plan_substeps(v, 60, b, s, 0.003, cap=96, prev=p)[3]]
                               for v, b, s, p in cases]


# ------------------------------------------------------------ the solver --
def _two_sheets(gap=0.01, size=0.20, spacing=0.015):
    from drape.pattern import Panel, build_garment
    c = np.array([[0, 0], [size, 0], [size, size], [0, size]], float)

    def sheet(name, y):
        edges = [(f"e{k}", np.stack([c[k], c[(k + 1) % 4]])) for k in range(4)]
        return Panel(name, edges, lambda uv, y=y: np.c_[uv[:, 0] - size / 2, np.full(len(uv), y), uv[:, 1] - size / 2])
    return build_garment([sheet("top", 3.0 + gap), sheet("bottom", 3.0)], [], spacing=spacing)


def _crossings(x, g):
    """Edges of one sheet passing through triangles of the other (segment vs triangle)."""
    tot = 0
    for pa, pb in ((0, 1), (1, 0)):
        E = g.edges[(g.panel_id[g.edges[:, 0]] == pa) & (g.panel_id[g.edges[:, 1]] == pa)]
        T = g.tris[g.panel_id[g.tris[:, 0]] == pb]
        o, d = x[E[:, 0]][:, None], (x[E[:, 1]] - x[E[:, 0]])[:, None]
        a, b, c = x[T[:, 0]][None], x[T[:, 1]][None], x[T[:, 2]][None]
        e1, e2 = b - a, c - a
        pv = np.cross(d, e2)
        det = (e1 * pv).sum(-1)
        ok = np.abs(det) > 1e-14
        inv = np.where(ok, 1 / np.where(ok, det, 1), 0)
        tv = o - a
        u = (tv * pv).sum(-1) * inv
        qv = np.cross(tv, e1)
        v = (d * qv).sum(-1) * inv
        t = (e2 * qv).sum(-1) * inv
        tot += int((ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t >= 0) & (t <= 1)).sum())
    return tot


def _sheets_sim(speed_substeps, substeps, self_every):
    from drape.fabrics import get
    from drape.measurements import Measurements, body_from_measurements
    body = body_from_measurements(Measurements.load(ROOT / "measurements" / "male_M.json"))   # 3 m below: never touched
    g = _two_sheets()
    sim = Simulator(g, body, get("jersey"), substeps=substeps, weld=False)
    sim.speed_substeps, sim.self_every = speed_substeps, self_every
    sim.sew_time, sim.gravity_ramp = 0.0, 1e9          # no sewing, no gravity
    sim.v[g.panel_id == 0] = [0.0, -3.0, 0.0]          # the top sheet flies at the bottom one
    worst = 0
    for _ in range(30):
        sim.step()
        worst = max(worst, _crossings(sim.x, g))
    return sim, worst


def test_fast_sheets_dont_tunnel_with_the_planner():
    """On the CPU the side test is against where a point was at the start of the frame,
    so even live mode's old fixed settings don't tunnel here (checked: 0 crossings);
    the GPU tests against the start of each substep, which is where the planner
    matters. Here: the planner raises the substeps and nothing crosses."""
    sim, after = _sheets_sim(True, 24, 2)
    assert after == 0
    m = sim.metrics()
    assert m["finite"] and m["substeps_max"] > 24


@pytest.mark.slow
def test_calm_drape_is_unchanged_until_the_weld_and_still_fits():
    """Slow frames must use exactly the base count: the tee is bit-identical to the
    fixed-substep solver while sewing. Right after the weld, merging seam pairs leaves
    a few points at ~1.5 m/s as self-collision switches on: the rule may add a substep
    or two there (it should), and the tee still meets its fit bars."""
    import sys
    sys.path.insert(0, str(ROOT / "tests"))
    from test_drape import PEOPLE
    from drape.garments import tshirt_for
    from drape.measurements import body_from_measurements
    m = PEOPLE["M"]
    b = body_from_measurements(m)
    a, c = Simulator(tshirt_for(m, body=b), b), Simulator(tshirt_for(m, body=b), b)
    c.speed_substeps = False
    fired = []
    for k in range(210):
        a.step(); c.step()
        if a.nsub_frame != a.nsub:
            fired.append(k)
        if not a.welded:
            assert np.array_equal(a.x, c.x)
    assert len(fired) <= 3 and all(a.sew_time * 60 - 1 <= k <= a.sew_time * 60 + 6 for k in fired)
    r = a.metrics()
    assert r["penetrating_verts"] == 0 and r["seam_gap_max_mm"] < 0.01
    assert r["strain_p99_pct"] < 6.0 and r["kinetic_energy_uJ"] < 20
    assert r["substeps"] == a.nsub and not r["speed_limited"]


def test_cap_constants():
    assert NSUB_CAP == 160
    src = (ROOT / "drape" / "studio" / "static" / "live_springs.js").read_text(encoding="utf-8")
    assert "NSUB_CAP_LIVE = 96" in src
