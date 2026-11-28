"""Pattern library, layout, printing, instructions and the studio API."""
import json
import time

import numpy as np
import pytest

from drape.blocks import BLOCKS, PRESETS, body_measures, draft_block, preset_values
from drape.measurements import Measurements
load = Measurements.load
from drape.seamcheck import check_seams  # noqa


@pytest.fixture(scope="module")
def studio():
    from drape.studio import server as S
    init = S.api_init()
    av = {s: S.api_avatar({"measurements": init["examples"][f"{s}_M"]}) for s in ("female", "male")}
    return S, init, av


@pytest.mark.parametrize("sex", ["female", "male"])
@pytest.mark.parametrize("key", list(BLOCKS))
def test_every_block_seams_check_out(studio, sex, key):
    S, init, av = studio
    a = S.S.avatars[av[sex]["id"]]
    for choice_set in [{}] + [{c: o} for c, opts in PRESETS.get(key, {}).items() for o in opts]:
        bm = body_measures(a["body"], a["meas"])
        g, _ = draft_block(key, a["body"], a["meas"], preset_values(key, choice_set, bm))
        rep = check_seams(g.meta["panels"], g.meta["seam_defs"])
        assert rep["ok"], (key, sex, choice_set, rep["problems"])


def test_presets_set_real_parameters():
    m = load("measurements/female_M.json")
    bm = body_measures(None, m)
    for key, controls in PRESETS.items():
        names = {p.name for p in BLOCKS[key].params}
        for c, opts in controls.items():
            for o in opts:
                vals = preset_values(key, {c: o}, bm)
                assert vals and set(vals) <= names, (key, c, o)


def test_draft_api_plain_language_and_fixes(studio):
    S, init, av = studio
    d = S.api_draft({"avatar": av["female"]["id"], "block": "tee", "choices": {"Fit": "Snug"}})
    json.dumps(d, default=S._jsonable)
    tight = [r for r in d["ease"] if "TIGHT" in r["status"]]
    assert tight and all("fix" in r for r in tight)          # snug tee on hips 100: offers a fix
    p, v = tight[0]["fix"]["param"], tight[0]["fix"]["value"]
    d2 = S.api_draft({"avatar": av["female"]["id"], "block": "tee", "choices": {"Fit": "Snug"}, "params": {p: v}})
    assert not any(r["line"] == tight[0]["line"] and "TIGHT" in r["status"] for r in d2["ease"])
    assert d["choices"]["Fit"] == {"option": "Snug", "exact": True}
    assert d["instructions"][0]["title"].lower().startswith("cut")
    assert d["yardage"]["150"]["yards"] > 0.5


def test_trouser_ease_rows(studio):
    S, init, av = studio
    d = S.api_draft({"avatar": av["female"]["id"], "block": "trousers"})
    lines = {r["line"]: r for r in d["ease"]}
    assert set(lines) == {"waist", "hip", "thigh"}
    assert 0 < lines["waist"]["ease_cm"] < 6 and 3 < lines["hip"]["ease_cm"] < 12


@pytest.mark.parametrize("kind", ["pdf_letter", "pdf_a4", "projector", "dxf", "dxf_laser", "layout"])
def test_exports(studio, kind):
    S, init, av = studio
    name, mime, data = S.api_export({"avatar": av["male"]["id"], "block": "trousers", "kind": kind})
    assert len(data) > 5000
    assert data[:4] in (b"%PDF", b"\x89PNG") or b"SECTION" in data[:200]


def test_laser_dxf_layers(studio, tmp_path):
    import ezdxf
    S, init, av = studio
    _, _, data = S.api_export({"avatar": av["female"]["id"], "block": "tee", "kind": "dxf_laser"})
    f = tmp_path / "l.dxf"; f.write_bytes(data)
    doc = ezdxf.readfile(f)
    assert doc.layers.get("CUT").color == 1                # red = cut in LightBurn
    for ln in doc.modelspace().query('LINE[layer=="NOTCH"]'):
        assert ln.dxf.start.distance(ln.dxf.end) <= 4.01    # notches only snip the allowance


def test_tiled_pdf_is_true_scale(tmp_path):
    from pdf2image import convert_from_path
    from drape.printpdf import tiled_pdf
    m = load("measurements/female_M.json")
    g, _ = draft_block("a_line_skirt", None, m)
    f = tmp_path / "s.pdf"
    tiled_pdf(g.meta["panels"], g.meta["seam_defs"], f, "skirt")
    assert f.stat().st_size > 1000
    img = np.asarray(convert_from_path(str(f), dpi=100, first_page=1, last_page=1)[0].convert("L"))
    assert img.shape[1] == 850                               # letter width at 100 dpi


def test_layout_fits_width_and_counts_every_piece():
    from drape.layout import layout_pieces
    m = load("measurements/male_M.json")
    g, _ = draft_block("tee", None, m)
    lay = layout_pieces(g.meta["panels"], 150, 1.5)
    assert len(lay["placements"]) == len(g.meta["panels"])
    for _, poly, _ in lay["placements"]:
        assert poly.bounds[0] >= -0.6 and poly.bounds[2] <= 150.6
    polys = [p for _, p, _ in lay["placements"]]
    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            assert polys[i].intersection(polys[j]).area < 2.0  # cm^2 of raster slack


def test_http_server_roundtrip():
    import threading, urllib.request
    from http.server import ThreadingHTTPServer
    from drape.studio.server import Handler
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    html = urllib.request.urlopen(base + "/").read()
    assert b"<title>Spunfection Studio</title>" in html
    init = json.loads(urllib.request.urlopen(base + "/api/init").read())
    assert {b["key"] for b in init["blocks"]} == set(BLOCKS)
    srv.shutdown()


@pytest.mark.slow
def test_drape_job_runs_in_background(studio):
    S, init, av = studio
    jid = S.api_drape({"avatar": av["male"]["id"], "block": "tee", "seconds": 2.5})["job"]
    t = time.time()
    while S.api_job(jid)["state"] == "running":
        assert time.time() - t < 600
        time.sleep(1)
    r = S.api_job(jid)
    assert r["state"] == "done", r.get("error")
    assert r["metrics"]["finite"] and r["metrics"]["penetrating_verts"] < 20
    assert r["advice"] and r["cloth"]["nv"] > 1000


# ------------------------------------------------------- design from scratch --
def _rect(name, w, h, place):
    x0, x1 = -w / 2, w / 2
    return {"name": name, "place": place, "edges": [
        {"name": "bottom", "pts": [[x0, 0], [x1, 0]]}, {"name": "right", "pts": [[x1, 0], [x1, h]]},
        {"name": "top", "pts": [[x1, h], [x0, h]]}, {"name": "left", "pts": [[x0, h], [x0, 0]]}]}


def test_landmarks_sit_on_the_skin(studio):
    from drape.freeform import LANDMARKS, landmark, _surf
    S, init, av = studio
    for sex in ("female", "male"):
        body = S.S.avatars[av[sex]["id"]]["body"]
        for name in LANDMARKS:
            p, n = landmark(body, name)
            d = _surf(body).dist(p[None])[0][0]
            assert abs(d) < 0.01, (sex, name, d)
        f, b = landmark(body, "chest_front")[0], landmark(body, "chest_back")[0]
        assert f[2] > b[2] + 0.1                                    # front is +z
        assert landmark(body, "hip_right")[0][0] < 0 < landmark(body, "hip_left")[0][0]   # avatar's right is -x


def test_wrap_placement_keeps_lengths_and_stays_outside(studio):
    from drape.freeform import build_design, _surf
    S, init, av = studio
    body = S.S.avatars[av["female"]["id"]]["body"]
    d = {"pieces": [_rect("band", 40, 10, {"landmark": "waist_front", "mode": "wrap", "offset_cm": 2}),
                    _rect("cuff", 20, 8, {"landmark": "forearm_right", "mode": "wrap"}),
                    _rect("patch", 15, 15, {"landmark": "hip_left", "mode": "flat", "rotate": 30})], "seams": []}
    g = build_design(d, body)
    assert _surf(body).dist(g.x)[0].min() > 0.004                   # nothing starts inside the body
    # wrapping is isometric away from push-out: the band's bottom edge keeps its length
    idx = g.meta["edge_index"][("band", "bottom")]
    L3 = np.linalg.norm(np.diff(g.x[idx], axis=0), axis=1).sum()
    assert abs(L3 - 0.40) < 0.02
    cuff = g.x[g.panel_id == 1].mean(0)
    assert cuff[0] < -0.25                                          # on the right arm (-x), out from the torso


def test_auto_seam_direction_and_mismatch_check(studio):
    from drape.freeform import build_design, design_check, example_design
    S, init, av = studio
    body = S.S.avatars[av["male"]["id"]]["body"]
    g = build_design(example_design(), body)
    assert all(s.reverse for s in g.meta["seam_defs"])              # side seams run opposite ways: auto-detected
    assert design_check(g)[0]["ok"]
    d = example_design()
    d["pieces"][1]["edges"][1]["pts"][1][1] = 50                   # back 'right' 5 cm short (and waist slants)
    d["pieces"][1]["edges"][2]["pts"][0][1] = 50
    chk = design_check(build_design(d, body))
    assert any(not c["ok"] and "gather" in c for c in chk)
    d["seams"][1]["ease"] = 0.1                                     # gather on purpose: accepted
    assert all(c["ok"] or "gather" not in c for c in design_check(build_design(d, body)))


def test_design_errors_are_plain(studio):
    S, init, av = studio
    d = init["example_design"]
    bad = json.loads(json.dumps(d)); bad["seams"].append({"a": "front.left", "b": "back.bottom"})
    r = S.api_scratch({"avatar": av["female"]["id"], "design": bad})
    assert "two seams" in r["error"]
    bad = json.loads(json.dumps(d)); bad["pieces"][0]["edges"][0]["pts"] = [[-30, 0], [30, 70]]   # crosses itself
    assert "crosses itself" in S.api_scratch({"avatar": av["female"]["id"], "design": bad})["error"]


def test_elastic_gathers_to_the_body(studio):
    from drape.freeform import build_design, example_design
    S, init, av = studio
    body = S.S.avatars[av["female"]["id"]]["body"]
    g = build_design(example_design(), body)
    (e,) = g.meta["elastic"]
    waist = body.girth_at_y(body.lines["waist"]) * 100
    assert abs(e["elastic_cm"] - 0.92 * waist) < 0.08 * waist


def test_scratch_api_full_and_exports(studio):
    S, init, av = studio
    req = {"avatar": av["female"]["id"], "design": init["example_design"]}
    r = S.api_scratch({**req, "full": True})
    titles = [s["title"] for s in r["instructions"]]
    assert "Sew the seams" in titles and "Add the elastic" in titles
    assert r["yardage"]["150"]["yards"] > 0.4
    for kind in ("pdf_letter", "dxf_laser", "layout"):
        name, _, data = S.api_export({**req, "kind": kind})
        assert name.startswith("my_design") and len(data) > 5000


@pytest.mark.slow
def test_scratch_skirt_drapes_and_stays_up(studio):
    from drape.freeform import build_design, example_design
    from drape import Simulator
    from drape.fabrics import get
    S, init, av = studio
    body = S.S.avatars[av["female"]["id"]]["body"]
    g = build_design(example_design(), body)
    sim = Simulator(g, body, get("jersey"))
    for _ in range(150):
        sim.step()
    m = sim.metrics()
    assert m["finite"] and m["penetrating_verts"] < 10
    assert sim.x[:, 1].max() > body.lines["waist"] - 0.06            # the elastic holds it at the waist


@pytest.mark.parametrize("key", list(BLOCKS))
def test_template_converts_to_an_editable_design(studio, key):
    """Converting a template keeps every outline, seam (direction, ease) and
    the placement on the body: the converted design builds the same garment."""
    from drape.freeform import build_design, design_check, editor_to_design
    S, init, av = studio
    a = S.S.avatars[av["female"]["id"]]
    d = S.api_to_scratch({"avatar": av["female"]["id"], "block": key})["design"]
    json.dumps(d)
    g = build_design(editor_to_design(d), a["body"])
    g0, _ = draft_block(key, a["body"], a["meas"], d["pieces"][0]["place"]["template"]["params"])
    assert check_seams(g.meta["panels"], g.meta["seam_defs"])["ok"]
    assert design_check(g)[0]["ok"]
    for i in range(len(g0.meta["panels"])):
        assert np.abs(g.x[g.panel_id == i].mean(0) - g0.x[g0.panel_id == i].mean(0)).max() < 0.003
    for s, s0 in zip(g.meta["seam_defs"], g0.meta["seam_defs"]):
        assert s.reverse == s0.reverse and abs(s.ease - s0.ease) < 1e-3


def test_converted_piece_can_be_reshaped_and_mirrored(studio):
    from drape.freeform import build_design, editor_to_design
    S, init, av = studio
    a = S.S.avatars[av["male"]["id"]]
    d = S.api_to_scratch({"avatar": av["male"]["id"], "block": "tee"})["design"]
    front = next(p for p in d["pieces"] if p["name"] == "front")
    i = front["verts"].index(min(front["verts"], key=lambda v: (v[1], -v[0])))   # a hem corner
    front["verts"][i] = [front["verts"][i][0] * 1.2, front["verts"][i][1] - 10]  # longer, flared
    g = build_design(editor_to_design(d), a["body"])
    assert np.isfinite(g.x).all()
    # a mirrored copy of the right sleeve sits on the other arm
    sl = next(p for p in d["pieces"] if p["name"] == "sleeve_r")
    m = json.loads(json.dumps(sl)); m["name"] = "sleeve_copy"
    m["verts"] = [[-x, y] for x, y in m["verts"]][::-1]
    m["edges"] = []      # outline only matters for placement here: straight edges
    n = len(m["verts"])
    m["edges"] = [{"name": f"e{k}"} for k in range(n)]
    m["place"]["template"]["mirror"] = True
    d2 = {"pieces": [sl, m], "seams": []}
    g2 = build_design(editor_to_design(d2), a["body"])
    c0, c1 = g2.x[g2.panel_id == 0].mean(0), g2.x[g2.panel_id == 1].mean(0)
    assert np.sign(c0[0]) == -np.sign(c1[0]) and abs(abs(c0[0]) - abs(c1[0])) < 0.03
