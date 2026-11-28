"""v1.2: inseam measurement, tools beside the pattern, warnings log with fixes,
popups on the pattern, symmetric editing."""
import dataclasses

import numpy as np
import pytest

from drape.measurements import Measurements


@pytest.mark.parametrize("delta", [+4.0, -4.0])
def test_avatar_follows_inseam(delta):
    from drape.human import fit_human
    from drape.meshmeasure import Tape
    m = Measurements.load("measurements/female_M.json")
    own = Tape(fit_human(m)[0]).crotch_height() * 100
    h, rows = fit_human(dataclasses.replace(m, inseam=round(own + delta, 1)))
    r = {x["measurement"]: x for x in rows}
    assert abs(r["inseam"]["error_cm"]) < 0.5
    for k in ("chest", "waist", "hip"):               # longer legs don't throw the girths off
        assert abs(r[k]["error_cm"]) < 1.5, k
    assert abs(r["height"]["avatar_cm"] - m.height) < 0.5


def test_inseam_validation_and_guide():
    from drape.meshmeasure import tape_paths  # noqa
    m = Measurements.load("measurements/male_L.json")
    assert not [w for w in dataclasses.replace(m, inseam=82).validate() if "inseam" in w.lower()]
    assert [w for w in dataclasses.replace(m, inseam=32).validate() if "inseam" in w.lower()]      # inches typed as cm
    from drape.render import LABELS
    assert LABELS["inseam"] == "Inseam"


def test_inseam_on_body_and_techpack():
    from drape.blocks import draft_block
    from drape.human import fit_human
    from drape.meshbody import MeshBody
    from drape.meshmeasure import Tape, tape_paths
    from drape.techpack import points_of_measure
    m = Measurements.load("measurements/male_L.json")
    h, _ = fit_human(m)
    body = MeshBody(h, measurements=m)
    T = Tape(h)
    assert abs(T.all()["inseam"] - T.crotch_height() * 100) < 1e-6
    p = [x for x in tape_paths(T) if x["name"] == "inseam"][0]
    assert p["pts"][0][1] > 0.6 and p["pts"][-1][1] == 0.0 and len(p["pts"]) > 8     # crotch down to the floor
    g, _ = draft_block("trousers", body, m)
    pom = {k: v for k, v, *_ in points_of_measure(g.x, g.panel_id, g.panel_names, body, m)}
    ins = pom.get("Inseam (crotch to hem)")
    assert ins and 55 < ins < T.crotch_height() * 100 + 2
    gt, _ = draft_block("tee", body, m)
    assert "Inseam (crotch to hem)" not in {k for k, *_ in points_of_measure(gt.x, gt.panel_id, gt.panel_names, body, m)}


def _html():
    from drape.studio import server as S
    return S.studio_source()


def test_tools_beside_pattern_and_convert_button():
    h = _html()
    stage = h.split('<section class="stage">')[1].split("</section>")[0]
    # Design layout (2026-11-24): the toolbar above the pattern, the selected piece in the left bar
    for i in ('id="toolcard"', 'id="tool"', 'id="shapes"', 'id="bands"', 'id="symBtn"'):
        assert i in stage, i
    side = h.split('<section class="card side" id="side">')[1].split('<section class="stage">')[0]
    assert 'id="shapes"' not in side and 'id="inspector"' in side and 'id="inspector"' not in stage
    assert 'class="btn primary bigbtn" id="toScratch"' in side and "Convert to free edit" in side
    assert ".stage.tooled" in h and 'classList.toggle("tooled", pane === "design" && !need)' in h


def test_warnings_log_and_popup():
    h = _html()
    assert 'id="logcard"' in h and "function renderLog" in h and "function placePop" in h and "function drawBadges" in h
    body = h.split("function logItems()")[1].split("\nfunction ")[0]
    assert 'matchSeam(s, "a")' in body and 'matchSeam(s, "b")' in body and "gatherSeam(s)" in body
    assert ".pop{pointer-events:none}" in h          # never blocks a handle on the board


def test_symmetry_engine():
    h = _html()
    for f in ("function symImages", "function moveVertexSym", "function mirrorCurve", "function symEdge"):
        assert f in h
    drag = h.split("function bindBoard()")[1]
    assert "moveVertexSym(d.pc" in drag and "mirrorCurve(d.pc" in drag
    assert "moveVertexSym(P," in h.split("function extendEdge")[1].split("\n}\n")[0]   # seam fixes stay mirrored
