"""v1.1: cloth-on-cloth collision in live mode, live editing, pose-test
stability (speed limit, more iterations, untangle), desktop packaging."""
import base64

import numpy as np
import pytest


@pytest.fixture(scope="module")
def av():
    from drape.studio import server as S
    init = S.api_init()
    a = S.api_avatar({"measurements": init["examples"]["female_M"]})
    return S, init, S.S.avatars[a["id"]], a["id"]


def test_live_setup_has_self_collision_and_uv(av):
    S, init, A, aid = av
    r = S.api_live({"avatar": aid, "block": "trousers", "choices": {}, "params": {}, "fabric": "poplin"})
    n = r["n"]
    part = np.frombuffer(base64.b64decode(r["partners"]), np.int32).reshape(n, 3)
    has = part >= 0
    assert has.any()
    for a, b in zip(*np.nonzero(has)):                         # seam partners: both ways
        assert a in part[part[a, b]]
    assert (part >= -1).all() and (part < n).all()
    uv = np.frombuffer(base64.b64decode(r["uv"]), np.float32).reshape(n, 2)
    assert np.isfinite(uv).all() and 0.01 < r["self_cell"] < 0.08
    src = (S.STATIC / "live_springs.js").read_text(encoding="utf-8")
    assert "fn selfimp" in src and "fn hinsert" in src and "closestOnTri" in src


def test_live_editing_is_wired():
    from drape.studio import server as S
    html = S.studio_source()
    assert "function liveRefresh" in html and "the piece hangs from its top" in html
    assert "liveRefresh()" in html.split("async function redraft")[1].split("function ")[0] + html.split("function dsChanged")[1][:400]


def test_speed_limit():
    from drape.cloth import MAX_SPEED
    from drape.springs import _spring_substeps
    import inspect
    assert 1.0 < MAX_SPEED < 10.0
    assert "vmax" in inspect.signature(_spring_substeps.py_func).parameters


@pytest.mark.slow
def test_pose_test_is_calm(av):
    """Sitting in trousers: no buzzing cloth (v1.0 had vertices at 150 m/s)."""
    from drape.blocks import draft_block
    from drape.fabrics import get
    from drape.pose import PosedCollider, smooth
    from drape.cloth import MAX_SPEED
    from drape import Simulator
    S, init, A, _ = av
    g, _ = draft_block("trousers", A["body"], A["meas"])
    sim = Simulator(g, A["body"], get("poplin"))
    for _ in range(int(3.5 * sim.fps)):
        sim.step()
    col = PosedCollider(A["body"], "sit")
    sim.set_posed(col)
    sim.untangle = True
    for f in range(int(2.4 * sim.fps)):
        col.advance(smooth(min((f + 1) / (1.4 * sim.fps), 1.0)))
        sim.step()
    sp = np.linalg.norm(sim.v, axis=1)
    m = sim.metrics()
    assert sp.max() <= MAX_SPEED + 1e-6
    assert m["kinetic_energy_uJ"] < 20000 and m["penetrating_verts"] <= 2
    assert sim.untangle_events > 0


def test_untangle_gives_slack_where_caught():
    from drape import Simulator
    from drape.blocks import draft_block
    from drape.fabrics import get
    from drape.measurements import Measurements
    from drape.human import fit_human
    from drape.meshbody import MeshBody
    m = Measurements.load("measurements/female_M.json"); h, _ = fit_human(m); body = MeshBody(h, measurements=m)
    g, _ = draft_block("tee", body, m)
    sim = Simulator(g, body, get("jersey"), untangle=True)
    for _ in range(60):
        sim.step()
    sim.x[100] = sim.x[100] - np.array([0, 0, 0.03]) * np.sign(sim.x[100, 2])     # shove one point into the body
    sim.x[100] = sim.x[100] * np.array([0.5, 1, 0.5])
    sim._untangle_step()
    assert sim._relax is not None and sim._relax.max() > 1.1
    e = sim.g.edges
    assert (sim._relax[(e[:, 0] == sim.vmap[100]) | (e[:, 1] == sim.vmap[100])] > 1.1).all()


def test_packaging_files():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    spec = (root / "packaging" / "drape.spec").read_text(encoding="utf-8")
    assert "launcher.py" in spec and "drape/studio/static" in spec and "measurements" in spec
    wf = (root / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
    assert "windows-latest" in wf and "macos-latest" in wf and "pyinstaller" in wf
