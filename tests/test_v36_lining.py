"""v1.6.16 (2026-11-28): linings cut like real ones: shorter than the shell at their open edges (a hem), and tacked
to the shell at each end of those edges (French tacks at the seams)."""
import copy

import numpy as np
import pytest

from drape import freeform as F


@pytest.fixture(scope="module")
def dress():
    from drape.studio import server as S
    init = S.api_init()
    a = S.api_avatar({"measurements": init["examples"]["female_M"]})
    d = F.editor_to_design(S.api_to_scratch({"avatar": a["id"], "block": "shift_dress"})["design"])
    return S.S.avatars[a["id"]]["body"], d


def _lined(d, **kw):
    d = copy.deepcopy(d)
    for p in d["pieces"]:
        p["lining"] = {"fabric": "lining", "open": ["hem"], **kw}
    return d


def _edge(pc, name):
    return np.asarray(next(e["pts"] for e in pc["edges"] if e["name"] == name), float)


def test_the_lining_is_shorter_at_its_hem_and_its_seams_still_match(dress):
    body, d = dress
    ex, _ = F._expand_linings(_lined(d))
    P = {p["name"]: p for p in ex["pieces"]}
    for pn in ("front", "back"):
        shell, lin = P[pn], P[pn + "_lining"]
        assert _edge(lin, "hem")[:, 1].mean() == pytest.approx(_edge(shell, "hem")[:, 1].mean() + F.LINING_SHORTER_CM, abs=0.05)
        assert [e["name"] for e in lin["edges"]] == [e["name"] for e in shell["edges"]]              # same edges
        ring = [(_edge(lin, e["name"])[0], _edge(lin, e["name"])[-1]) for e in lin["edges"]]
        assert all(np.allclose(ring[k][1], ring[(k + 1) % len(ring)][0], atol=1e-3) for k in range(len(ring)))
    # the linings' own side seams (sewn to each other) are still the same length on both sides
    from drape.dedit import plen
    for s in ex["seams"]:
        if s["a"].endswith("side_1_r") and "_lining" in s["a"]:
            a, b = s["a"].split("."), s["b"].split(".")
            assert plen(_edge(P[a[0]], a[1])) == pytest.approx(plen(_edge(P[b[0]], b[1])), abs=0.3)
    assert ex["_lining_tacks"] == [("front_lining", "hem", "front"), ("back_lining", "hem", "back")]


def test_tacked_at_the_seams_and_shorter_cm_zero_keeps_the_old_lining(dress):
    body, d = dress
    g = F.build_design(_lined(d), body)
    assert g.meta["lining_tacks"] == ["front_lining.hem", "back_lining.hem"]
    n_att = len(g.meta["attach"]["v"])
    g0 = F.build_design(_lined(d, shorter_cm=0), body)
    assert g0.meta["lining_tacks"] == [] and len(g0.meta["attach"]["v"]) < n_att
    ex0, _ = F._expand_linings(_lined(d, shorter_cm=0))
    P0 = {p["name"]: p for p in ex0["pieces"]}
    assert np.allclose(_edge(P0["front_lining"], "hem"), _edge(P0["front"], "hem"))
