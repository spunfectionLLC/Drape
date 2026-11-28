"""The springs solver on the GPU (studio/static/live_springs.js, live.live_setup()):
the velocity-level guards on the shader source, and the data it gets.
The GPU run itself is a browser test (test_browser.py: test_live_springs_*)."""
import base64
import re
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "drape" / "studio" / "static" / "live_springs.js").read_text(encoding="utf-8")


def _kernels(src):
    """{entry point name: body} for every @compute function in the file."""
    out = {}
    for m in re.finditer(r"@compute[^\n]*?fn (\w+)\(", src):
        i = src.index("{", src.index(")", m.end()))   # the body, after the parameter list
        depth, j = 0, i
        while True:
            depth += {"{": 1, "}": -1}.get(src[j], 0)
            if depth == 0:
                break
            j += 1
        out[m.group(1)] = src[i:j + 1]
    return out


# --- design guards (SPRING_VELOCITY_LEVEL_SPEC section 0): the GPU
# port must keep the velocity level exactly as springs.py does. Don't loosen them.
def test_positions_are_written_only_by_x_plus_h_v():
    ks = _kernels(SRC)
    assert {"forces", "cgInit", "cgW", "cgStep", "strain", "body", "finish", "selfimp"} <= set(ks)
    writes_x = re.compile(r"\bX\[[^\]]*\]\s*[-+*/]?=")
    for name, body in ks.items():
        if name != "finish":
            assert not writes_x.search(body), name
    fin = ks["finish"]
    assert "var x = xg(i) + F.h * v;" in fin                    # the position update...
    assert fin.count("X[3u*i] =") == 1                          # ...written once, after the safety net
    # the safety net moves a point out of the body but never sets its velocity from the move
    net = fin[fin.index("if (d < -F.deep)"):]
    assert "v -= vn * n" in net and not re.search(r"v\s*=\s*\(?\s*x", net)
    # the solve and the self-collision modules can't write positions at all
    for mod in ("SPR_SOLVE_WGSL", "SPR_SELF_WGSL"):
        block = SRC[SRC.index(f"const {mod}"):]
        assert "var<storage, read> X: array<f32>;" in block.split("`;")[0], mod


def test_no_velocity_from_a_position_difference_in_the_shaders():
    ks = _kernels(SRC)
    diff_over_h = re.compile(r"\(\s*(x\w*|xg\([^)]*\)|x0g\([^)]*\))\s*-\s*[^)]*\)\s*/\s*F\.h\b")
    v_write = re.compile(r"(\bV\[[^\]]*\]\s*=|\bvs\(|\bv\s*=)")
    for name, body in ks.items():
        code = "\n".join(l.split("//")[0] for l in body.splitlines())
        assert not diff_over_h.search(code), name
        for line in code.splitlines():
            if v_write.search(line):
                # a velocity is set from velocities, impulses and forces, never from positions
                assert "xg(" not in line and "X[" not in line and "x0g(" not in line, (name, line)
    for word in ("xprev", "x_old", "compliance", "lambda", "Lagrange"):
        assert word not in SRC, word
    # the speed the planner uses comes from the solver's velocities, not from positions
    assert "this.vStaging" in SRC and "this.vMeasured = Math.sqrt(v2);" in SRC


def test_storage_buffers_per_stage_within_8():
    for mod in ("SPR_SOLVE_WGSL", "SPR_BODY_WGSL", "SPR_SELF_WGSL"):
        block = SRC[SRC.index(f"const {mod}"):].split("`;")[0]
        assert block.count("var<storage") <= 8, mod


# --- the data
@pytest.fixture(scope="module")
def tee_setup():
    from drape.blocks import draft_block
    from drape.human import fit_human
    from drape.live import live_setup
    from drape.measurements import Measurements
    from drape.meshbody import MeshBody
    m = Measurements.load(str(ROOT / "measurements" / "male_M.json"))
    h, _ = fit_human(m)
    b = MeshBody(h, measurements=m)
    g, _ = draft_block("tee", b, m)
    return g, b, live_setup(g, b, "jersey")


def _arrays(S):
    sp = S["springs"]
    topo = np.frombuffer(base64.b64decode(sp["topo"]), np.uint32).astype(np.int64)
    par = np.frombuffer(base64.b64decode(sp["param"]), np.float32).astype(float)
    return sp, topo, par


def test_springs_setup_is_consistent(tee_setup):
    g, body, S = tee_setup
    sp, topo, par = _arrays(S)
    n, T, P, ns, nnz = S["n"], sp["toff"], sp["poff"], sp["ns"], sp["nnz"]
    assert sp["edge_batches"][-1] == sp["ne"]
    pairs = topo[T["spr"]:T["spr"] + 2 * ns].reshape(-1, 2)
    # strain batches: no two edges in a batch share a point (they update velocities in parallel)
    eb = sp["edge_batches"]
    for a, b in zip(eb[:-1], eb[1:]):
        v = pairs[a:b].reshape(-1)
        assert len(np.unique(v)) == len(v)
    # every spring end knows its partner's slot in its own matrix row
    incs, inc = topo[T["incs"]:T["incs"] + n + 1], topo[T["inc"]:T["inc"] + 2 * ns]
    slot = topo[T["incslot"]:T["incslot"] + 2 * ns]
    rows, rcol = topo[T["rows"]:T["rows"] + n + 1], topo[T["rcol"]:T["rcol"] + nnz]
    owner = np.repeat(np.arange(n), np.diff(incs))
    e, side = inc >> 1, inc & 1
    assert (np.where(side == 0, pairs[e, 0], pairs[e, 1]) == owner).all()
    assert (rcol[slot] == np.where(side == 0, pairs[e, 1], pairs[e, 0])).all()
    assert ((slot >= rows[owner]) & (slot < rows[owner + 1])).all()
    # inverse masses first in the float buffer (every piece's, frozen ones too)
    from drape.fabrics import get, panel_fabrics
    from drape.springs import SpringSimulator
    fab = get("jersey")
    sim = SpringSimulator(panel_fabrics(g, fab), body, fab)
    assert np.allclose(par[:n], 1.0 / sim.g.mass, rtol=1e-6)


def test_bending_blocks_match_springs_py(tee_setup):
    """The constant bending part of the GPU's matrix is springs._apply_K's bending part."""
    g, b, S = tee_setup
    from drape.fabrics import get, panel_fabrics
    from drape.springs import SpringSimulator, _apply_K
    sp, topo, par = _arrays(S)
    n, T, P, nnz = S["n"], sp["toff"], sp["poff"], sp["nnz"]
    rows, rcol = topo[T["rows"]:T["rows"] + n + 1], topo[T["rcol"]:T["rcol"] + nnz]
    bk = par[P["bk"]:P["bk"] + nnz]
    fab = get("jersey")
    sim = SpringSimulator(panel_fabrics(g, fab), b, fab)
    _, bc = sim._compliances()
    u = np.random.default_rng(0).normal(size=(n, 3))
    ref = np.zeros((n, 3))
    _apply_K(u, ref, np.zeros((0, 2), np.int64), np.zeros(0), np.zeros((0, 3)), np.zeros(0),
             sim._hinges, sim._hK, sim._hs, 1.0 / bc)
    mine = np.zeros((n, 3))
    np.add.at(mine, np.repeat(np.arange(n), np.diff(rows)), bk[:, None] * u[rcol])
    assert np.abs(mine - ref).max() <= 1e-5 * np.abs(ref).max()


def test_studio_uses_live_springs(tee_setup):
    html = (ROOT / "drape" / "studio" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'src="live_springs.js"' in html and 'src="live.js"' not in html     # XPBD (live.js) is gone
    pre = (ROOT / "drape" / "studio" / "static" / "js" / "05_preview.js").read_text(encoding="utf-8")
    assert "new LiveSprings()" in pre and "LiveSim" not in pre
