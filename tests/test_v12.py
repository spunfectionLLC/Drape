"""v1.1.1: glove templates in the gallery, and gloves that fit the hand."""
import numpy as np
import pytest


@pytest.fixture(scope="module")
def male():
    from drape.human import fit_human
    from drape.measurements import Measurements
    from drape.meshbody import MeshBody
    m = Measurements.load("measurements/male_L.json")
    h, _ = fit_human(m)
    return MeshBody(h, measurements=m), m


def test_glove_starters_in_gallery(male):
    from drape.starters import STARTERS, starter
    body, m = male
    keys = [k for k, s in STARTERS.items() if s.category == "Accessories"]
    assert set(keys) == {"knit_gloves", "mittens", "fingerless_gloves", "opera_gloves"}
    for k in keys:
        d = starter(k, body, m)
        assert len(d["pieces"]) == 4 and len(d["seams"]) >= 2
        assert d["spacing_cm"] and d["fine_sdf"] and d["body_offset"]
        assert all(p["place"].get("glove") for p in d["pieces"])


def test_studio_sends_glove_settings():
    """The studio rebuilt designs from pieces and seams only, so gloves were draped on
    a 2.5 cm mesh with a 4 mm air gap: fingers poked through."""
    from drape.studio import server as S
    html = S.studio_source()
    body = html.split("function serverDesign()")[1].split("\n}\n")[0]
    for k in ("spacing_cm", "fine_sdf", "body_offset"):
        assert k in body
    assert "pc.place.glove" in html                 # not flagged "not on the body"


def test_body_offset_reaches_solver(male):
    from drape.fabrics import get
    from drape.freeform import build_design, editor_to_design
    from drape.gloves import glove_design
    from drape import Simulator
    body, m = male
    g = build_design(editor_to_design(glove_design(body, m, "mittens")), body)
    assert g.meta["body_offset"] == pytest.approx(0.002)
    sim = Simulator(g, body, get("fleece"))
    assert sim.fabric.thickness == pytest.approx(0.002)
    assert get("fleece").thickness > 0.002          # the preset itself is untouched


def test_palm_and_thumb_follow_the_hand(male):
    from drape.gloves import THUMB_ROOT, glove_outline, hand_sizes
    body, m = male
    hs = hand_sizes(body, m)
    poly, chords, lobes, dims = glove_outline(hs, "gloves")
    straight = dims["Wr"] + (dims["P"] - dims["Wr"]) * 0.6
    assert dims["Pm"] >= straight and dims["Pm"] * 4 >= hs["palm_mid"]   # room over the ball of the thumb
    assert THUMB_ROOT > 1.2


@pytest.mark.slow
def test_gloves_fit(male):
    """Male L, knit gloves: nothing through the cloth, and the thumb no longer
    pulls 30%+ (v1.1: thumb p95 31%, palm p95 17.5%)."""
    from drape.fabrics import get
    from drape.freeform import build_design, editor_to_design
    from drape.gloves import _joint, glove_design
    from drape import Simulator
    body, m = male
    g = build_design(editor_to_design(glove_design(body, m, "gloves")), body)
    sim = Simulator(g, body, get("jersey"))
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


def test_fit_advice_names_the_hands(male):
    from drape.studio.server import _advise
    from drape.gloves import _hand_verts
    body, m = male
    x = _hand_verts(body, "r")[:400] * 1.0
    adv = _advise(body, x, np.full(len(x), 0.2), None, {})
    assert "hands" in adv[0]["text"] and "hips" not in " ".join(a["text"] for a in adv)
