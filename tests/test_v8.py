"""v0.8: layers, pockets, bands, bending, calibration, poses, tracing, size
runs, nesting, costing, explain."""
import base64
import io
import json

import numpy as np
import pytest

from drape.measurements import Measurements


@pytest.fixture(scope="module")
def av():
    from drape.studio import server as S
    init = S.api_init()
    a = S.api_avatar({"measurements": init["examples"]["female_M"]})
    return S, init, S.S.avatars[a["id"]], a["id"]


def _rect(name, w, h, place, **kw):
    x0, x1 = -w / 2, w / 2
    return {"name": name, "place": place, **kw, "edges": [
        {"name": "bottom", "pts": [[x0, 0], [x1, 0]]}, {"name": "right", "pts": [[x1, 0], [x1, h]]},
        {"name": "top", "pts": [[x1, h], [x0, h]]}, {"name": "left", "pts": [[x0, h], [x0, 0]]}]}


# ------------------------------------------------------------- layers --
def test_lining_twins_pieces_and_ties_edges(av):
    from drape.freeform import build_design, example_design, design_check
    from drape.fabrics import panel_fabrics, get
    S, init, A, _ = av
    d = example_design()
    for p in d["pieces"]:
        p["lining"] = {"fabric": "lining", "open": ["hem"]}
    g = build_design(d, A["body"])
    assert g.panel_names == ["front", "back", "front_lining", "back_lining"]
    assert len(g.meta["attach"]["v"]) > 20 and sorted(g.meta["lining_joins"]) == ["back_lining.waist", "front_lining.waist"]
    assert len(g.meta["seam_defs"]) == 4                     # shell sides + lining sides
    assert design_check(g)[0]["ok"]
    g = panel_fabrics(g, get("poplin"))
    assert g.meta["panel_fabrics"][2].name == "poly lining"
    # the lining starts inside the shell
    from drape.freeform import _surf
    d0 = _surf(A["body"]).dist(g.x)[0]
    assert np.median(d0[g.panel_id == 2]) < np.median(d0[g.panel_id == 0])


def test_interfacing_stiffens(av):
    from drape.fabrics import FABRICS, INTERFACINGS, fused
    f = fused(FABRICS["poplin"], INTERFACINGS["medium"])
    assert f.bend_compliance < FABRICS["poplin"].bend_compliance / 2
    assert f.density == pytest.approx(FABRICS["poplin"].density + INTERFACINGS["medium"].density)


def test_pocket_sits_on_its_piece_and_is_tied(av):
    from drape.freeform import build_design, design_check
    S, init, A, _ = av
    d = {"pieces": [_rect("front", 50, 60, {"landmark": "chest_front", "mode": "wrap"}),
                    _rect("pocket", 14, 16, {"on": "front", "pos": [8, 15]})], "seams": []}
    g = build_design(d, A["body"])
    pk, fr = g.x[g.panel_id == 1], g.x[g.panel_id == 0]
    from scipy.spatial import cKDTree
    dist = cKDTree(fr).query(pk)[0]
    assert dist.max() < 0.02                                  # on the front, a few mm out
    assert g.meta["topstitched"][0]["sewn"] == ["bottom", "right", "left"]   # top is the opening
    d["pieces"][1]["place"]["pos"] = [40, 15]                 # half off the front
    g = build_design(d, A["body"])
    assert any("hangs off" in c["text"] for c in design_check(g))


def test_band_follows_its_opening(av):
    from drape.freeform import build_design
    S, init, A, _ = av
    d = {"pieces": [_rect("skirt", 60, 50, {"landmark": "waist_front", "mode": "wrap", "at": "top"}),
                    _rect("band", 60, 4, {"loop": ["skirt.top"], "dir": "up"})],
         "seams": [{"a": "band.bottom", "b": "skirt.top"}]}
    g = build_design(d, A["body"])
    top = g.x[g.meta["edge_index"][("skirt", "top")]]
    bot = g.x[g.meta["edge_index"][("band", "bottom")]]
    from scipy.spatial import cKDTree
    assert cKDTree(top).query(bot)[0].max() < 0.02
    assert g.x[g.panel_id == 1][:, 1].mean() > top[:, 1].mean()   # stands up from it


# ------------------------------------------------------------ bending --
def _elastica_drop(B, q, L, N=200):
    """Tip drop (m) of the heavy elastica: a strip of bending stiffness B (N m) and
    weight q (N/m^2) clamped flat at a table edge, L out, by minimising its energy."""
    from scipy.optimize import minimize
    ds = L / N
    k = np.arange(N)

    def E(th):
        d = np.diff(np.concatenate([[0.0], th]))
        y = -np.cumsum(np.sin(th)) * ds + 0.5 * np.sin(th) * ds       # segment midpoints
        return 0.5 * B * (d * d).sum() / ds + q * ds * y.sum()

    def G(th):
        d = np.diff(np.concatenate([[0.0], th])) / ds
        g = B * d
        g[:-1] -= B * d[1:]
        return g - q * ds * ds * np.cos(th) * (N - k - 0.5)
    best = min((minimize(E, s, jac=G, method="L-BFGS-B", bounds=[(0, np.pi / 2)] * N,
                         options={"maxiter": 20000, "ftol": 1e-15, "gtol": 1e-12})
                for s in (np.zeros(N), np.full(N, 1.2), np.linspace(0, 1.5, N))), key=lambda r: r.fun)
    return float(np.sin(best.x).sum() * ds)


def test_bending_stiffness_matters():
    """Floppier fabrics droop more, and each droops like the heavy elastica (the
    textbook cantilever, B = 1 / bend compliance) within 8%. The old margin (jersey
    10 mm below denim at 8 cm) was XPBD's, stiffened by locking: the elastica gives
    8.9 mm with these presets (79.0 / 70.1 mm)."""
    from drape.calibrate import droop_sim
    from drape.fabrics import FABRICS
    d = {}
    for k in ("chiffon", "jersey", "denim"):
        f = FABRICS[k]
        d[k] = droop_sim(f.bend_compliance, f.density, overhang=0.08)
        ref = _elastica_drop(1.0 / f.bend_compliance, f.density * 9.81, 0.08)
        assert abs(d[k] - ref) < 0.08 * ref, (k, d[k], ref)
    assert d["chiffon"] > d["jersey"] > d["denim"] + 0.005      # floppier fabrics droop more


def test_calibration_recovers_a_known_fabric():
    from drape.calibrate import calibrate, droop_sim
    true = 3e4
    droop = droop_sim(true, 0.25, overhang=0.10) * 100
    fab, chk = calibrate("test", 2.5, droop, overhang_cm=10)
    assert abs(chk["droop_cm"] - droop) < 0.3
    assert 0.3 < fab.bend_compliance / true < 3


# -------------------------------------------------------------- poses --
def test_posed_collider_maps_limbs_rigidly(av):
    from drape.pose import PosedCollider
    from drape.meshbody import grid_sdf_batch
    S, init, A, _ = av
    c = PosedCollider(A["body"], "sit")
    c.advance(1.0)
    V = c.sk.pose("sit", 1.0)
    W = c.sk.W
    g = c.groups.index("calf_l")
    sel = np.nonzero(W[:, c.sk.bones.index("calf_l")] > 0.999)[0]   # fully on the shin
    q = (V[sel] - c.P1[g]) @ c.R1[g] + c.H[g]
    assert np.abs(q - c.sk.V0[sel]).max() < 0.002            # back to rest exactly
    assert np.abs(grid_sdf_batch(np.ascontiguousarray(q), c.grid, c.origin, c.h)).max() < 0.01


@pytest.mark.slow
def test_trousers_follow_the_legs_when_sitting(av):
    from drape.blocks import draft_block
    from drape import Simulator
    from drape.fabrics import get
    from drape.pose import PosedCollider, smooth
    S, init, A, _ = av
    g, _ = draft_block("trousers", A["body"], A["meas"])
    sim = Simulator(g, A["body"], get("jersey"))
    for _ in range(120):
        sim.step()
    c = PosedCollider(A["body"], "sit"); sim.set_posed(c)
    for f in range(84):
        c.advance(smooth(min((f + 1) / 84, 1))); sim.step()
    V = c.sk.pose("sit", 1.0)
    knee_z = V[:, 2].max()
    assert sim.x[:, 2].max() > knee_z - 0.15                  # the cloth went forward with the thighs
    assert np.isfinite(sim.x).all()


# ------------------------------------------------------------ tracing --
def test_trace_photo_scale_and_corners():
    from PIL import Image, ImageDraw
    from drape.trace import trace
    im = Image.new("RGB", (1200, 900), (176, 140, 96)); dr = ImageDraw.Draw(im)
    dr.polygon([(300, 200), (700, 200), (800, 700), (200, 700)], fill=(30, 60, 140))   # 10 px = 1 cm
    buf = io.BytesIO(); im.save(buf, "PNG")
    r = trace("data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), (100, 800), (400, 800), 30)
    assert r["width_cm"] == pytest.approx(60, rel=0.03) and r["height_cm"] == pytest.approx(50, rel=0.03)
    assert len(r["verts"]) == 4


# ---------------------------------------------------------- size runs --
def test_size_run_grades_and_prints(tmp_path):
    from drape.sizerun import grade_block, sizerun_pdf
    G = grade_block("a_line_skirt", {}, {}, "misses")
    w = [sum(np.ptp(np.concatenate([e for _, e in p.edges])[:, 0]) for p in g.meta["panels"]) for _, g, _, _ in G]
    assert all(b > a for a, b in zip(w, w[1:]))               # every size wider than the last
    f = tmp_path / "s.pdf"
    r = sizerun_pdf([(l, g.meta["panels"], m, fin) for l, g, m, fin in G], f, "Skirt")
    assert r["sizes"][0] == "2" and f.stat().st_size > 20000


# ------------------------------------------------------------ nesting --
def test_nesting_sheets_and_errors(tmp_path):
    import ezdxf
    from drape.blocks import draft_block
    from drape.nest import nest_dxf
    g, _ = draft_block("tee", None, Measurements.load("measurements/female_M.json"))
    with pytest.raises(ValueError, match="wider than the bed"):
        nest_dxf(tmp_path / "a.dxf", g.meta["panels"], g.meta["seam_defs"], 40, 30)
    r = nest_dxf(tmp_path / "b.dxf", g.meta["panels"], g.meta["seam_defs"], 130, 90, garments=2)
    assert r["pieces"] == 8 and r["sheets"] >= 2
    doc = ezdxf.readfile(tmp_path / "b.dxf")
    assert doc.layers.get("CUT").color == 1 and doc.layers.get("BED").color == 8
    assert len(doc.modelspace().query('LWPOLYLINE[layer=="CUT"]')) == 8


# ------------------------------------------------------------ costing --
def test_costing_and_etsy_price():
    from drape.blocks import draft_block
    from drape.costing import ETSY, materials, price
    g, _ = draft_block("tee", None, Measurements.load("measurements/female_M.json"))
    M = materials(g)
    assert 0.8 < M["fabrics"][0]["yards"] < 2 and 30 < M["minutes"] < 150
    p = price(20.0, profit=10.0)
    pct = ETSY["transaction"] + ETSY["processing_pct"]
    keep = p["price"] - (p["price"] * pct + ETSY["listing"] + ETSY["processing_fixed"])
    assert keep == pytest.approx(30.0, abs=0.02)


# ------------------------------------------------------------ explain --
def test_explain_reads_the_strain_direction(av):
    from drape.explain import explain
    from drape.pattern import Panel, build_garment, line
    S, init, A, _ = av
    p = Panel("p", [("a", line((0, 0), (0.3, 0))), ("b", line((0.3, 0), (0.3, 0.3))),
                    ("c", line((0.3, 0.3), (0, 0.3))), ("d", line((0, 0.3), (0, 0)))],
              lambda uv: np.c_[uv[:, 0] - 0.15, uv[:, 1] + 1.1, np.full(len(uv), 0.2)])
    g = build_garment([p], [])
    v = int(np.argmin(np.linalg.norm(g.uv - [0.15, 0.15], axis=1)))
    X = g.x.copy(); X[:, 0] *= 1.12                          # stretched sideways
    r = explain(A["body"], X, g.x, g.edges, g.edge_rest, g.uv, g.panel_id, v, {"chest_ease": 8})
    assert r["title"].startswith("Too tight across") and r["fixes"][0]["param"] == "chest_ease"
    X = g.x.copy(); X[:, 1] = (X[:, 1] - 1.1) * 1.12 + 1.1   # stretched up and down
    r = explain(A["body"], X, g.x, g.edges, g.edge_rest, g.uv, g.panel_id, v, {})
    assert r["title"].startswith("Pulled up and down")


# ---------------------------------------------------------- streaming --
def test_quick_drape_streams_frames(av):
    import time
    S, init, A, aid = av
    jid = S.api_drape({"avatar": aid, "block": "a_line_skirt", "quality": "quick", "seconds": 1.5})["job"]
    frames, t = 0, time.time()
    while True:
        r = S.api_job(jid)
        frames += "frame" in r
        if r["state"] != "running":
            break
        assert time.time() - t < 300
        time.sleep(0.5)
    assert r["state"] == "done", r.get("error")
    assert frames >= 1 and "cloth_uv" in r
