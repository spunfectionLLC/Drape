"""v1.4: seam markings that only fit one way (the first sewn shirt had its
sleeves in upside down): numbered, coloured seams, one-sided notches (single =
front, double = back) and a match dot at the top of a sleeve cap."""
import numpy as np
import pytest

from drape.measurements import Measurements


@pytest.fixture(scope="module")
def tee():
    from drape.blocks import draft_block
    from drape.human import fit_human
    from drape.meshbody import MeshBody
    m = Measurements.load("measurements/male_M.json")
    h, _ = fit_human(m)
    body = MeshBody(h, measurements=m)
    g, _ = draft_block("tee", body, m)
    return g


def _arcfrac(e, q):
    """Where along the edge (0..1 of its length) the point q lies: projected onto each segment."""
    seg = np.diff(e, axis=0)
    L = np.linalg.norm(seg, axis=1)
    S = np.concatenate([[0], np.cumsum(L)])
    best, at = 1e9, 0.0
    for k in range(len(seg)):
        t = np.clip((q - e[k]) @ seg[k] / max(L[k] ** 2, 1e-12), 0, 1)
        d = np.linalg.norm(e[k] + t * seg[k] - q)
        if d < best:
            best, at = d, S[k] + t * L[k]
    return at / S[-1]


def test_both_edges_of_a_seam_share_number_colour_and_notches(tee):
    from drape.seammarks import NOTCH_AT, seam_color, seam_marks
    panels, seams = tee.meta["panels"], tee.meta["seam_defs"]
    SM = seam_marks(panels, seams)
    for i, s in enumerate(seams):
        A, B = SM[s.panel_a]["edges"][s.edge_a], SM[s.panel_b]["edges"][s.edge_b]
        assert A["num"] == B["num"] == i + 1 and A["color"] == B["color"] == seam_color(i)
        back = "back" in s.panel_a or "back" in s.panel_b
        assert len(A["notches"]) == len(B["notches"]) == (2 if back else 1)
        # sewn together, A's notch lands on B's: 40% along A is 40% along B in the seam's direction
        fa = np.mean([_arcfrac(A["pts"], q) for q, _ in A["notches"]])
        fb = np.mean([_arcfrac(B["pts"], q) for q, _ in B["notches"]])
        assert abs(fa - NOTCH_AT) < 0.02
        assert abs(fb - ((1 - NOTCH_AT) if s.reverse else NOTCH_AT)) < 0.02
        assert A["partner"] in ("ITS OTHER SIDE", s.panel_b.replace("_", " ").upper())


def test_sleeve_goes_in_one_way_only(tee):
    from drape.seammarks import seam_marks
    SM = seam_marks(tee.meta["panels"], tee.meta["seam_defs"])
    sl = SM["sleeve_r"]
    assert len(sl["edges"]["cap_r"]["notches"]) == 1 and sl["edges"]["cap_r"]["partner"] == "FRONT"
    assert len(sl["edges"]["cap_l"]["notches"]) == 2 and sl["edges"]["cap_l"]["partner"] == "BACK"
    assert len(sl["dots"]) == 1                                  # the top of the cap: to the shoulder seam
    top = sl["dots"][0]["point"]
    cap = sl["edges"]["cap_r"]["pts"]
    assert np.allclose(top, cap[-1]) and top[1] >= cap[:, 1].max() - 1e-6
    assert SM["front"]["dots"] == [] and SM["back"]["dots"] == []  # corners, not curves: no dots


def test_outward_notches_and_tags_inside(tee):
    from shapely.geometry import Point, Polygon
    from drape.seammarks import seam_marks
    SM = seam_marks(tee.meta["panels"], tee.meta["seam_defs"])
    for p in tee.meta["panels"]:
        poly = Polygon(np.concatenate([e[:-1] for _, e in p.edges]) * 100)
        for mk in SM[p.name]["edges"].values():
            assert poly.contains(Point(*mk["tag"]))
            for q, n in mk["notches"]:
                assert not poly.contains(Point(*(q + n * 1.0)))     # notches point out, into the allowance


def test_exports_carry_the_markings(tee, tmp_path):
    import ezdxf
    from drape.export_dxf import export_pattern_dxf
    from drape.printpdf import _piece_geoms
    panels, seams = tee.meta["panels"], tee.meta["seam_defs"]
    G = {g["name"]: g for g in _piece_geoms(panels, seams, 1.5)}
    assert sum(len(g["tags"]) for g in G.values()) == 2 * len(seams)
    assert len(G["sleeve_r"]["dots"]) == 1
    for laser in (False, True):
        f = tmp_path / f"t{laser}.dxf"
        export_pattern_dxf(str(f), panels, seams, laser=laser)
        msp = ezdxf.readfile(f).modelspace()
        nums = sorted(int(t.dxf.text) for t in msp.query('TEXT[layer=="SEAMNO"]'))
        assert nums == sorted(list(range(1, len(seams) + 1)) * 2)
        assert len(msp.query('CIRCLE[layer=="NOTCH"]')) == 2


def test_studio_pattern_view_shows_them(tee):
    from drape.studio import server as S
    P = {p["name"]: p for p in S._pieces_payload(tee)}
    e = {x["name"]: x for x in P["sleeve_r"]["edges"]}
    assert e["cap_l"]["num"] == 8 and len(e["cap_l"]["notches"]) == 2 and len(P["sleeve_r"]["dots"]) == 1
    src = S.studio_source()
    assert "e.notches" in src and "q.p.dots" in src
