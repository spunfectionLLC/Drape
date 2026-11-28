"""v1.0: per-edge seam allowance, DXF-AAMA, glTF + Blender kit, tech pack,
anisotropic / strain-stiffening fabric, the live GPU solver's setup, the
fabric tester, stitch lines."""
import base64
import json
import zipfile

import numpy as np
import pytest


@pytest.fixture(scope="module")
def av():
    from drape.studio import server as S
    init = S.api_init()
    a = S.api_avatar({"measurements": init["examples"]["female_M"]})
    return S, init, S.S.avatars[a["id"]], a["id"]


@pytest.fixture(scope="module")
def shirt(av):
    from drape.freeform import build_design, editor_to_design
    from drape.starters import starter
    S, init, A, _ = av
    d = starter("button_up", A["body"], A["meas"])
    d["pieces"][0]["edges"][0]["sa"] = 3.0        # deeper hem on the first front
    return build_design(editor_to_design(d), A["body"]), d


# ------------------------------------------------------------- exports --
def test_per_edge_seam_allowance():
    from drape.closures import cut_polygon
    from drape.pattern import Panel
    sq = np.array([[0, 0], [0.3, 0], [0.3, 0.4], [0, 0.4]])
    p = Panel("t", [("hem", sq[[0, 1]]), ("r", sq[[1, 2]]), ("top", sq[[2, 3]]), ("l", sq[[3, 0]])], lambda uv: uv)
    lo = np.array(cut_polygon(p, 1.5).bounds)
    assert np.allclose(lo, [-1.5, -1.5, 31.5, 41.5])
    p.sa_edges = {"hem": 4.0, "top": 0.6}
    b = np.array(cut_polygon(p, 1.5).bounds)
    assert np.allclose(b, [-1.5, -4.0, 31.5, 40.6], atol=1e-6)


def test_per_edge_sa_reaches_the_panels(shirt):
    g, d = shirt
    P = {p.name: p for p in g.meta["panels"]}
    first = d["pieces"][0]
    assert P[first["name"]].sa_edges == {first["edges"][0]["name"]: 3.0}


def test_aama_export(shirt, tmp_path):
    import ezdxf
    from drape.export_aama import export_aama
    g, _ = shirt
    f = tmp_path / "s.dxf"
    export_aama(f, g.meta["panels"], g.meta["seam_defs"], size="M", style="Button-up")
    doc = ezdxf.readfile(f)
    names = {b.name for b in doc.blocks if not b.name.startswith("*")}
    assert {p.name for p in g.meta["panels"]} <= names
    blk = doc.blocks.get("front_r")
    layers = {e.dxf.layer for e in blk} | {e.dxf.layer for e in doc.blocks.get("front_l")}
    assert {"1", "14", "4", "7", "8", "13"} <= layers           # cut, sew, notch, grain, internal, drill (buttons)
    texts = [e.dxf.text for e in blk if e.dxftype() == "TEXT"]
    assert "Piece Name: front_r" in texts and "Size: M" in texts
    assert len([e for e in doc.modelspace() if e.dxftype() == "INSERT"]) == len(g.meta["panels"])


def test_glb_and_blender_kit(av, tmp_path):
    from drape.blocks import draft_block
    from drape.export_gltf import blender_bundle, garment_meshes, write_glb
    S, init, A, _ = av
    g, _ = draft_block("tee", A["body"], A["meas"])
    z = {"x0": g.x, "tris0": g.tris, "uv0": g.uv, "panel_id0": g.panel_id, "panel_names": np.array(g.panel_names)}

    class Z(dict):
        files = list(z)
    glb = tmp_path / "g.glb"
    write_glb(glb, garment_meshes(Z(z), A["body"], fabric="fleece"))
    raw = glb.read_bytes()
    magic, ver, length = np.frombuffer(raw[:12], np.uint32)
    assert magic == 0x46546C67 and ver == 2 and length == len(raw)
    jlen = int(np.frombuffer(raw[12:16], np.uint32)[0])
    doc = json.loads(raw[20:20 + jlen])
    assert [n["name"] for n in doc["nodes"]] == list(g.panel_names) + ["avatar"]
    assert "KHR_materials_sheen" in doc.get("extensionsUsed", [])          # fleece is fuzzy
    kit = tmp_path / "k.zip"
    blender_bundle(kit, glb, "fleece")
    zf = zipfile.ZipFile(kit)
    assert set(zf.namelist()) == {"garment.glb", "render_in_blender.py", "README.txt"}
    compile(zf.read("render_in_blender.py").decode(), "render_in_blender.py", "exec")


def test_techpack(shirt, av, tmp_path):
    from drape.techpack import points_of_measure, techpack_pdf
    S, init, A, _ = av
    g, _ = shirt
    pom = points_of_measure(g.x, g.panel_id, g.panel_names, A["body"], A["meas"])
    names = [p[0] for p in pom]
    assert any("Chest" in n for n in names) and any("Length" in n for n in names)
    chest = next(p for p in pom if "Chest" in p[0])
    assert chest[1] > chest[2]                                  # a shirt is bigger than the body
    f = tmp_path / "tp.pdf"
    techpack_pdf(f, g, A["body"], A["meas"], "Button-up", "cotton poplin", "M")
    assert f.stat().st_size > 30000


# ------------------------------------------------------------- physics --
def test_anisotropy_factor():
    from drape.blocks import draft_block
    from drape.fabrics import get
    from drape.measurements import Measurements
    from drape.human import fit_human
    from drape.meshbody import MeshBody
    from drape import Simulator
    m = Measurements.load("measurements/female_M.json"); h, _ = fit_human(m); body = MeshBody(h, measurements=m)
    g, _ = draft_block("tee", body, m)
    sim = Simulator(g, body, get("poplin"))
    f = sim._aniso()
    d = g.uv[g.edges[:, 1]] - g.uv[g.edges[:, 0]]
    ang = np.degrees(np.arctan2(np.abs(d[:, 0]), np.abs(d[:, 1])))       # 0 = along the grain
    assert np.allclose(f[ang < 1], 1.0, atol=0.02)
    assert np.allclose(f[ang > 89], get("poplin").weft_ratio, atol=0.05)
    diag = (ang > 40) & (ang < 50)
    assert diag.any() and f[diag].mean() > 4                               # poplin gives on the bias


def test_lock_strain_stiffens():
    from drape.calibrate import stretch_sim
    # the same strip and load: a fabric that locks at 2 % stretches far less than one that doesn't
    import drape.calibrate as C
    from drape.cloth import Fabric
    orig = C.Fabric
    try:
        C.Fabric = lambda *a, **k: Fabric(*a, lock_strain=0.02)
        locked = stretch_sim(2e-3, 0.15, 0.5, seconds=1.5)
    finally:
        C.Fabric = orig
    free = stretch_sim(2e-3, 0.15, 0.5, seconds=1.5)
    assert free > 0.015 and locked < 0.6 * free, (free, locked)


# ---------------------------------------------------------------- live --
def test_live_setup_sends_the_mesh_and_body_grid(av):
    """(The springs payload's batches: test_v20_gpu_springs.)"""
    S, init, A, aid = av
    r = S.api_live({"avatar": aid, "block": "tee", "choices": {}, "params": {}, "fabric": "jersey", "quality": "quick"})
    n = r["n"]
    assert len(np.frombuffer(base64.b64decode(r["x"]), np.float32)) == 3 * n
    sd = r["sdf"]
    q = np.frombuffer(base64.b64decode(sd["data"]), np.int16)
    assert q.size == np.prod(sd["dims"]) and q.min() < 0 < q.max()       # inside and outside the body


def test_live_js_is_served():
    from drape.studio import server as S
    src = (S.STATIC / "live_springs.js").read_text(encoding="utf-8")
    assert "fn forces" in src and "fn body" in src and "fn finish" in src and "class LiveSprings" in src
    html = S.studio_source()
    assert '<script src="live_springs.js"></script>' in html and "setClothRaw" in html
    assert 'src="live.js"' not in html and not (S.STATIC / "live.js").exists()      # XPBD is gone


# -------------------------------------------------------------- tester --
def _synth(k0, lock, k1, n=120, maxe=0.08, gauge=100, width=50):
    e = np.linspace(0, maxe, n)
    T = np.where(e < lock, k0 * e, k0 * lock + k1 * (e - lock))
    return np.c_[e * gauge, T * width / 1000 + np.random.default_rng(0).normal(0, 0.01, n)]


def test_tester_curve_fit():
    from drape.tester import fit_curve, parse_csv
    f = fit_curve(_synth(800, 0.03, 8000), 100, 50)
    assert abs(f["k0_N_per_m"] - 800) < 40 and abs(f["lock_strain"] - 0.03) < 0.004
    assert fit_curve(_synth(800, 0.5, 8000), 100, 50)["lock_strain"] is None     # never locks in range
    csv = "# drape fabric tester\nms,ext_mm,force_N\n0,0.0,0.00\n50,0.5,0.10\n100,1.0,0.21\n"
    assert parse_csv(csv).shape == (3, 2)


@pytest.mark.slow
def test_tester_makes_a_fabric():
    from drape.tester import fabric_from_tests
    tests = [{"dir": "warp", "samples": _synth(800, 0.03, 8000).tolist()},
             {"dir": "weft", "samples": _synth(500, 0.04, 6000).tolist()},
             {"dir": "bias", "samples": _synth(100, 0.2, 3000, maxe=0.3).tolist()}]
    fab, rep = fabric_from_tests("Test", tests, 1.6, 6.5)
    assert 1.4 < fab.weft_ratio < 1.8 and 6 < fab.bias_ratio < 10 and abs(fab.lock_strain - 0.03) < 0.005
    assert abs(rep["check"]["droop_cm"] - 6.5) < 0.5


# ------------------------------------------------------------ stitches --
def test_stitch_lines(shirt):
    from drape.stitches import stitch_lines
    g, _ = shirt
    L = stitch_lines(g, np.arange(len(g.x)))
    kinds = {l["kind"] for l in L}
    assert kinds == {"seam", "topstitch"}
    top = [l for l in L if l["kind"] == "topstitch"]
    for l in top:
        b = np.asarray(l["bary"])
        assert np.allclose(b.sum(1), 1, atol=1e-3) and (b >= -1e-6).all()
    # topstitching lands on the same piece as its hem
    pid = g.panel_id
    for l in top[:3]:
        ids = np.asarray(l["ids"])
        assert len(np.unique(pid[ids])) == 1
