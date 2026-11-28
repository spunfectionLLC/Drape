"""Design rules (2026-11-20). These guard:
feature switches, seam colours that mean identity only, ease from the drape (or the
drafting) instead of summed 2D pattern lengths, and no piece creation from the 3D view.
The CG guard (no contact filtering inside the implicit solve) is in test_v19_velocity.py. The browser side of the switches is in
test_browser.py (test_switched_off_bands_are_hidden_but_hoods_stay)."""
import json
import re
import threading
import urllib.request
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "drape" / "studio" / "static" / "js"


@pytest.fixture(scope="module")
def studio():
    from drape.studio import server as S
    init = S.api_init()
    a = S.api_avatar({"measurements": init["examples"]["female_M"]})
    return S, a["id"]


@pytest.fixture
def bands_off(monkeypatch):
    from drape import features
    monkeypatch.setitem(features.FEATURES, "OPENING_BANDS", False)


# ------------------------------------------------------------ A1: switches --
def test_switch_defaults_and_the_js_mirror():
    """Free alpha: cloud drapes off, everything else on; the studio's mirror matches."""
    from drape.features import FEATURES
    assert FEATURES == {"OPENING_BANDS": True, "BINDING_TOOL": True, "FACING_TOOL": True, "CLOUD_DRAPE": False}
    src = (JS / "01_core.js").read_text(encoding="utf-8")
    m = re.search(r"const FEATURES = (\{[^}]*\});", src)
    js = json.loads(re.sub(r"(\w+):", r'"\1":', m.group(1)))
    assert js == FEATURES
    from drape.studio import server as S
    assert S.api_init()["features"] == FEATURES


def test_bands_off_blocks_the_route_but_not_the_hood(studio, bands_off):
    S, aid = studio
    from drape.features import FeatureOff
    d = S.api_starter({"avatar": aid, "key": "classic_tee"})["design"]
    d["pieces"] = [p for p in d["pieces"] if p.get("role") != "collar"]
    d["seams"] = [s for s in d["seams"] if not s["a"].startswith("neckband") and not s["b"].startswith("neckband")]
    with pytest.raises(FeatureOff):
        S.api_edit({"design": d, "op": "band", "args": {"kind": "neckband", "loop": ["front.neck", "back.neck"], "avatar": aid}})
    r = S.api_edit({"design": d, "op": "band", "args": {"kind": "hood", "loop": ["front.neck", "back.neck"], "avatar": aid}})
    assert any(p.get("role") == "hood" for p in r["design"]["pieces"])


def test_bands_off_answers_403_over_http(studio, bands_off):
    S, aid = studio
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        d = S.api_starter({"avatar": aid, "key": "crop_tee"})["design"]
        body = json.dumps({"design": d, "op": "band", "args": {"kind": "cuff", "loop": ["front.hem"], "avatar": aid}}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/api/edit", body,
                                     {"Content-Type": "application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with pytest.raises(urllib.error.HTTPError) as e:
            opener.open(req, timeout=60)
        assert e.value.code == 403 and "not available in this build" in json.loads(e.value.read())["error"]
    finally:
        srv.shutdown()


def test_starters_leave_bands_off_but_keep_hoods(studio, bands_off):
    S, aid = studio
    from drape.dedit import BAND_ROLE
    for key in ("classic_tee", "hoodie", "button_up", "joggers"):
        d = S.api_starter({"avatar": aid, "key": key})["design"]
        roles = [p.get("role") for p in d["pieces"]]
        names = [p["name"] for p in d["pieces"]]
        assert not any(n.startswith(tuple(BAND_ROLE)) for n in names), (key, names)
        if key == "hoodie":
            assert "hood" in roles
        if key == "joggers":      # its elastic waistband becomes an elastic casing in the waist edges
            waist = [e for p in d["pieces"] for e in p["edges"] if e["name"] == "waist"]
            assert waist and all(e.get("elastic") for e in waist)


def test_a_design_with_a_neckband_still_loads_drapes_and_exports(studio, bands_off, tmp_path):
    S, aid = studio
    from drape import features
    from drape.export_dxf import export_pattern_dxf
    from drape.fabrics import get, panel_fabrics
    from drape.freeform import build_design, editor_to_design
    from drape.springs import SpringSimulator
    features.FEATURES["OPENING_BANDS"] = True          # made while bands were on (saved earlier)
    d = S.api_starter({"avatar": aid, "key": "classic_tee"})["design"]
    features.FEATURES["OPENING_BANDS"] = False         # opened in a build with them off
    assert any(p["name"].startswith("neckband") for p in d["pieces"])
    body = S.S.avatars[aid]["body"]
    g = build_design(editor_to_design(d), body, spacing=0.03)
    fab = get("jersey")
    sim = SpringSimulator(panel_fabrics(g, fab), body, fab, substeps=24)
    for _ in range(6):
        sim.step()
    assert np.isfinite(sim.x).all()
    export_pattern_dxf(tmp_path / "tee.dxf", g.meta["panels"], g.meta["seam_defs"])
    assert "neckband" in (tmp_path / "tee.dxf").read_text(errors="ignore").lower()


# ------------------------------------------------- A2: seam colours = identity --
def test_no_seam_or_edge_colour_comes_from_a_length_match():
    """Seam colours and numbers say which
    edges sew together and must never change to show whether the lengths match. A
    mismatch is shown in words. This greps the studio's JS for any colour, background,
    stroke, fill or ok/bad style chosen on the same line as a seam-length comparison."""
    length = re.compile(r"diff_cm|len_a_cm|len_b_cm")
    paint = re.compile(r"color\s*:|background\s*:|stroke|fill=|\"ok\"\s*:\s*\"bad\"|check \$\{")
    bad = []
    for f in sorted(JS.glob("*.js")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if length.search(line) and paint.search(line):
                bad.append(f"{f.name}:{i}: {line.strip()[:120]}")
    assert not bad, bad
    seams = (JS / "13_seams.js").read_text(encoding="utf-8")
    assert '${ok ? "ok" : "bad"}' not in seams                    # the seam list's rows look the same
    log = (JS / "14_log.js").read_text(encoding="utf-8")
    focus = log[log.index("function drawBadges"):]
    focus = focus[:focus.index("const m0 = edgeMidBoard")]
    assert '"stroke", "#e0603f"' not in focus                    # a focused seam isn't painted the warning colour


# ------------------------------------------------------------ A3: ease --
def _cylinder(r, y0=0.0, y1=1.0, n=96, rows=12):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ys = np.linspace(y0, y1, rows)
    x = np.array([[r * np.cos(t), y, r * np.sin(t)] for y in ys for t in a])
    tris = []
    for j in range(rows - 1):
        for i in range(n):
            p, q = j * n + i, j * n + (i + 1) % n
            tris += [[p, q, p + n], [q, q + n, p + n]]
    return x, np.array(tris)


def test_section_girth_of_a_cylinder_garment():
    """Unit check: a garment cylinder 2 cm out from a body cylinder: ease = 2 pi dr."""
    from drape.fitcheck import section_girth
    xb, tb = _cylinder(0.15)
    xg, tg = _cylinder(0.17)
    ease = section_girth(xg, tg, 0.43) - section_girth(xb, tb, 0.43)
    assert abs(ease - 2 * np.pi * 0.02) < 0.002
    assert section_girth(xg, tg, 2.0) is None                  # it doesn't reach that height


def test_ease_report_never_sums_2d_pattern_lengths():
    """The garment's girth comes from the drafting
    (meta girths) or from the drape, never from adding up 2D pattern lengths across pieces."""
    import inspect
    from drape import fitcheck
    src = inspect.getsource(fitcheck)
    for word in ("polyline_length", "_width_at", "LineString", ".intersection(", "_waistband"):
        assert word not in src, word


@pytest.mark.slow
def test_tee_ease_on_the_drape(studio):
    """After a drape, chest and waist ease are measured on the draped tee (a tape round its
    3D cross-section), close to what it was drafted with."""
    S, aid = studio
    from drape.blocks import draft_block
    from drape.fabrics import get, panel_fabrics
    from drape.fitcheck import drape_ease, ease_report
    from drape.springs import SpringSimulator
    A = S.S.avatars[aid]
    g, _ = draft_block("tee", A["body"], A["meas"])
    fab = get("jersey")
    sim = SpringSimulator(panel_fabrics(g, fab), A["body"], fab)
    for _ in range(int(3.5 * sim.fps)):
        sim.step()
    on = {r["line"]: r for r in drape_ease(sim, A["body"])}
    drafted = {r["line"]: r for r in ease_report(g, A["body"]) if "ease_cm" in r}
    for line in ("chest", "waist"):
        assert on[line]["source"] == "drape"
        assert abs(on[line]["ease_cm"] - drafted[line]["ease_cm"]) < 6, (line, on[line], drafted[line])


# ------------------------------------------------ A4: no pieces from the 3D view --
def _fn_body(src, start):
    """The text of the function or callback starting at `start` (brace matched)."""
    i = src.index(start)
    j = src.index("{", i)
    depth = 0
    for k in range(j, len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError(start)


CREATE = ("pieces.push", "serverEdit(", "finishBand", "bandHere", "addShape", "layer_copy", "add_band", "splitEdge")


def test_the_3d_view_never_creates_pieces():
    """Facings and bindings start in the 2D editor only: no
    3D-view handler creates a piece. The 3D view's handlers: orbit / grab (07_viewer.js),
    tap to place a selected piece (GL.onClick) and tap to explain (GL.onClothClick)."""
    viewer = (JS / "07_viewer.js").read_text(encoding="utf-8")
    for word in CREATE:
        assert word not in viewer, word
    pieces = (JS / "12_pieces.js").read_text(encoding="utf-8")
    preview = (JS / "05_preview.js").read_text(encoding="utf-8")
    m = re.search(r"GL\.onClothClick\((\w+)\)", (JS / "16_board.js").read_text(encoding="utf-8"))
    handlers = [_fn_body(pieces, "GL.onClick("), _fn_body(preview, f"const {m.group(1)} ="),
                _fn_body(preview, "GL.setGrab(")]
    for h in handlers:
        for word in CREATE:
            assert word not in h, (word, h[:80])


def test_facing_and_binding_tools_are_not_built():
    """A4's checks on the facing polygon and the binding piece apply once those tools exist.
    Until then: nothing in the editor makes them."""
    from drape import dedit
    for name in ("add_facing", "add_binding", "facing", "binding"):
        assert not hasattr(dedit, name), name
    if hasattr(dedit, "add_facing") or hasattr(dedit, "add_binding"):
        pytest.fail("facing / binding tool built: add test_v21's A4 checks for it")


# (the check that the private docs keep their notes is in tests/test_private_docs.py, private only)
