"""In-browser groundwork: drape runs without numba and libigl (neither exists in
Pyodide), with a numpy/SciPy body collision grid that matches libigl's."""
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def body():
    from drape.human import fit_human
    from drape.measurements import Measurements
    from drape.meshbody import MeshBody
    m = Measurements.load("measurements/male_M.json")
    h, _ = fit_human(m)
    return MeshBody(h, measurements=m)


def test_numpy_sdf_matches_libigl(body):
    igl = pytest.importorskip("igl")
    from drape.sdf_numpy import signed_distance_grid
    V, F = body.V, body.F
    lo, hi, step = np.array([-0.25, 1.0, -0.18]), np.array([0.25, 1.5, 0.18]), 0.01
    xs, ys, zs = (np.arange(lo[i], hi[i] + step, step) for i in range(3))
    S = signed_distance_grid(V, F, xs, ys, zs).reshape(-1)
    P = np.stack(np.meshgrid(xs, ys, zs, indexing="ij"), -1).reshape(-1, 3)
    R = np.clip(igl.signed_distance(P, V, F.astype(np.int64), sign_type=igl.SIGNED_DISTANCE_TYPE_FAST_WINDING_NUMBER)[0], -0.06, 0.06)
    assert (np.sign(S) == np.sign(R)).all()                       # inside/outside: exact (watertight body)
    near = np.abs(R) < 0.02
    assert np.abs(S - R)[near].max() < 0.0005                     # within 0.5 mm near the skin
    assert np.abs(S - R).max() < 0.002


BROWSER_LIKE = r'''
import sys, os, importlib.abc, json
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.split(".")[0] in ("numba", "igl", "llvmlite"):
            raise ImportError("not in a browser: " + name)
sys.meta_path.insert(0, Block())
sys.path.insert(0, sys.argv[1]); os.chdir(sys.argv[1])
os.environ["DRAPE_SDF_CACHE"] = sys.argv[2]; os.makedirs(sys.argv[2], exist_ok=True)
from drape._jit import HAVE_NUMBA
from drape.measurements import Measurements
from drape.human import fit_human
from drape.meshbody import MeshBody
from drape.blocks import draft_block
from drape.live import live_setup
m = Measurements.load("measurements/male_M.json"); h, _ = fit_human(m); body = MeshBody(h, measurements=m)
g, _ = draft_block("tee", body, m)
s = live_setup(g, body, "jersey")
from drape.export_dxf import export_pattern_dxf
export_pattern_dxf(os.path.join(sys.argv[2], "t.dxf"), g.meta["panels"], g.meta["seam_defs"], laser=True)
print(json.dumps({"numba": HAVE_NUMBA, "n": s["n"], "full_grid_built": body._grid is not None, "sdf_dims": s["sdf"]["dims"]}))
'''


@pytest.mark.slow
def test_runs_from_the_web_bundle_without_numba_or_libigl(tmp_path):
    subprocess.run([sys.executable, str(ROOT / "tools" / "build_web_proof.py")], check=True, cwd=ROOT)
    out = ROOT / "out" / "web_proof"
    assert {"index.html", "live_springs.js", "drape_bundle.zip"} <= {p.name for p in out.iterdir()}
    app = tmp_path / "app"
    zipfile.ZipFile(out / "drape_bundle.zip").extractall(app)
    assert (app / "drape" / "data" / "makehuman.npz").exists() and (app / "measurements" / "male_M.json").exists()
    env = {"MPLBACKEND": "Agg", "PATH": "/usr/bin:/bin"}
    # Windows needs these to find the home folder (ezdxf reads its config there) and system DLLs
    env.update({k: os.environ[k] for k in ("USERPROFILE", "HOMEDRIVE", "HOMEPATH", "SYSTEMROOT", "TEMP", "TMP")
                if k in os.environ})
    r = subprocess.run([sys.executable, "-I", "-c", BROWSER_LIKE, str(app), str(tmp_path / "sdf")],
                       capture_output=True, text=True, timeout=900, env=env)
    assert r.returncode == 0, r.stderr[-2000:]
    import json
    res = json.loads(r.stdout.strip().splitlines()[-1])
    assert res["numba"] is False and res["n"] > 1000
    assert res["full_grid_built"] is False                        # only the box around the garment is computed


def test_proof_page_uses_allowed_parts():
    html = (ROOT / "web" / "proof.html").read_text(encoding="utf-8")
    assert "cdn.jsdelivr.net/pyodide/v" in html and "LiveSprings" in html and "drape_bundle.zip" in html
