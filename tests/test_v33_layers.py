"""v33: several garments in one simulation, layered by simulation (2026-11-26).

MULTI_GARMENT_SPEC's design-around constraints: layer order is the user's, layering is by simulation (no garment is
pushed outward to make room), freezing is all or nothing per garment. So, in one simulation:
- each garment sews in its own stages, after the garments under it (stages.assign, the user's layer order);
- when a garment starts, the garments under it freeze where they hang and go into the collision grid as frozen
  garments do (colliders.layered_grid); the new garment starts against the plain body and is pushed out over them;
- while a stage sews, contacts are planned for pieces flying in at the speed cap (start_speed).
And the sphere experiment (Tyler's idea): a collision sphere at each point between garments, velocity impulses
only, off unless asked for.
"""
import numpy as np
import pytest

from drape.studio import server as S


@pytest.fixture(scope="module")
def av():
    a = S.api_avatar({"measurements": {"sex": "female", "height": 166, "chest": 92, "waist": 74, "hip": 100}})
    return S.S.avatars[a["id"]]


TEE = {"block": "tee", "choices": {}, "params": {}}
LONG = {"block": "long_sleeve", "choices": {}, "params": {}}


def test_merged_garments_keep_their_own_placement_and_sew_in_layer_order(av):
    one, _ = S._merged_design([LONG], av["body"], av["meas"])
    two, _ = S._merged_design([TEE, LONG], av["body"], av["meas"])
    assert two.get("garments_merged") and "layer_gap_cm" not in two
    outer = {p["name"].split("~", 1)[1]: p["place"] for p in two["pieces"] if p["name"].startswith("1~")}
    alone = {p["name"].split("~", 1)[1]: p["place"] for p in one["pieces"]}
    for n, pl in outer.items():                     # placed exactly as on its own: nothing pushed outward
        assert pl.get("layer", 0) == alone[n].get("layer", 0), n
    from drape.freeform import build_design
    g = build_design(two, av["body"], spacing=0.03)
    st = dict(zip(g.panel_names, g.meta["piece_stage"]))
    assert max(v for n, v in st.items() if n.startswith("0~")) < min(v for n, v in st.items() if n.startswith("1~"))
    assert g.meta["piece_garment"] == [int(n.split("~")[0]) for n in g.panel_names]


def test_the_inner_garment_freezes_into_the_grid_when_the_outer_one_starts(av):
    import queue
    import tempfile
    d, _ = S._merged_design([TEE, LONG], av["body"], av["meas"])
    job = S._drape_job(queue.Queue(), av["shape"], av["meas"], {"design": d, "quality": "quick"}, "jersey", 3.5,
                       tempfile.mkdtemp())
    sim, n = next(job)
    assert sim.garment_freeze and sim.start_speed > 0
    start2 = sim.timeline()[1][0]
    while sim.time < start2 - 1e-9:
        sim.step()
    assert not sim._frozen_gar.any()
    while not sim._frozen_gar.any() and sim.time < start2 + 0.1:     # the outer garment's stage begins
        sim.step()
    inner = sim._vgar == 0
    assert sim._frozen_gar[inner].all() and not sim._frozen_gar[~inner].any()
    assert (sim.w[inner] == 0).all() and getattr(sim, "_grid_override", None) is not None
    x_inner = sim.x[inner].copy()
    for _ in range(5):
        sim.step()
    assert np.array_equal(sim.x[sim._vgar == 0], x_inner)          # frozen: never moved


def test_spheres_are_velocity_impulses_between_garments_only():
    from drape.springs import _sphere_impulses
    x = np.array([[0.0, 0, 0], [0.01, 0, 0], [0.5, 0, 0]])
    v = np.array([[1.0, 0, 0], [-1.0, 0, 0], [0.0, 0, 0]])
    w = np.ones(3)
    x0 = x.copy()
    _sphere_impulses(x, v, w, 1e-3, np.array([0]), np.array([1]), 0.01)
    assert np.array_equal(x, x0)                                      # positions untouched
    assert abs(v[0, 0]) < 1e-12 and abs(v[1, 0]) < 1e-12              # the approach is gone
    v2 = np.array([[-1.0, 0, 0], [1.0, 0, 0], [0.0, 0, 0]])           # moving apart: left alone
    _sphere_impulses(x, v2, w, 1e-3, np.array([0]), np.array([1]), 0.01)
    assert v2[0, 0] == -1.0 and v2[1, 0] == 1.0
    from drape.springs import SpringSimulator
    assert not getattr(SpringSimulator, "sphere_r", 0)                # off unless asked for


def test_a_two_garment_drape_comes_back_as_a_finished_drape_per_garment(av, tmp_path):
    """Drape it with two garments: one job (merged, layered by simulation); when it's done, a finished job per
    garment, with its own points, triangles, pieces under their own names and fit colours: what the 3D view and
    every export read for a garment draped on its own."""
    import queue
    import tempfile
    from pathlib import Path
    d, _ = S._merged_design([TEE, LONG], av["body"], av["meas"])
    q, out = queue.Queue(), tempfile.mkdtemp()
    S._drape_worker(q, av["shape"], av["meas"], {"design": d, "quality": "quick"}, "jersey", 1.0, out)
    msgs = []
    while not q.empty():
        msgs.append(q.get())
    done = [m for m in msgs if m[0] == "done"]
    assert done, [m for m in msgs if m[0] == "error"]
    jid = "multi_test"
    S.S.jobs[jid] = dict(proc=None, q=queue.Queue(), progress=1.0, stage="Done", state="done", result=done[0][1], outdir=out,
                         avatar=None, block=None, garments=[TEE, LONG])
    r = S.api_job(jid)
    assert r["state"] == "done" and len(r["garment_jobs"]) == 2
    whole = np.load(Path(out) / "result.npz")
    total = 0
    for k, cid in enumerate(r["garment_jobs"]):
        c = S.api_job(cid)
        assert c["state"] == "done" and c["cloth"]["nv"] > 0 and c["cloth"]["nf"] > 0
        z = np.load(Path(S.S.jobs[cid]["outdir"]) / "result.npz")
        assert not any("~" in str(n) for n in z["panel_names"])                     # its pieces' own names
        assert z["tris"].max() < len(z["x"]) and z["vmap"].max() < len(z["x"]) and z["tris0"].max() < len(z["x0"])
        assert z["panel_id"].max() < len(z["panel_names"]) and (z["vmap"] >= 0).all()
        total += len(z["x"])
    assert total == len(whole["x"])                                                  # every point, once
    assert S.api_job(jid)["garment_jobs"] == r["garment_jobs"]                       # split once


# ------------------------------------------------------------------ the page
pytest.importorskip("playwright.sync_api")
from test_browser import ST, _ensure_avatar, _go_garment, page, server  # noqa: E402,F401  (fixtures)


@pytest.mark.slow
def test_drape_it_with_two_garments_is_one_drape_inner_layer_first(page):
    pg = page
    _ensure_avatar(pg)
    pg.evaluate("loadGarments({garments: [], activeGarmentId: null}); renderGarmentList()")
    _go_garment(pg, "tee")
    pg.evaluate("activeGarment().name = 'Tee'")
    pg.evaluate("document.querySelector('#addGarment').click()")
    pg.click('#addGarmentMenu [data-ga="blank"]')
    pg.click('#gcards [data-k="long_sleeve"]')
    pg.wait_for_function(f"() => {ST}.ST.block === 'long_sleeve' && {ST}.ST.draft", timeout=60000)
    pg.evaluate("activeGarment().name = 'Top'; renderGarmentList()")
    assert pg.is_visible("#layernote") is False or "drape together" in pg.inner_text("#layernote")
    pg.evaluate(f"{ST}.go('preview')")
    pg.evaluate("""() => { window.__a0 = api; window.__reqs = []; window.__step = 0;
        window.__sd = showDrape; showDrape = () => {}; window.__ra = renderAdvice; renderAdvice = () => {};
        window.api = async (p, b) => {
          if (p === '/api/drape') { __reqs.push(b); return {job: 'M'} }
          if (p === '/api/job/M') return __step++ < 2 ? {state: 'running', progress: 0.5, stage: 'Sewing the body'} : {state: 'done', progress: 1, stage: 'Done', garment_jobs: ['M-0', 'M-1']};
          if (p === '/api/job/M-0' || p === '/api/job/M-1') return {state: 'done', progress: 1, stage: 'Done', advice: [], metrics: {}, who: p.slice(-1)};
          return __a0(p, b) } }""")
    try:
        pg.evaluate("startDrape(); 0")
        pg.wait_for_function("() => window.__reqs.length === 1", timeout=10000)
        req = pg.evaluate("window.__reqs[0]")
        assert [g.get("name") for g in req["garments"]] == ["Tee", "Top"]                 # inner layer first
        assert req["garments"][0]["block"] == "tee" and req["garments"][1]["block"] == "long_sleeve"
        assert pg.evaluate("PROJECT.garments.every(g => g.draping)")                      # both busy
        pg.wait_for_function("() => PROJECT.garments.every(g => g.drape && !g.draping)", timeout=20000)
        got = pg.evaluate("[...PROJECT.garments].sort((a, b) => a.layer - b.layer).map(g => [g.name, g.drape.who, g.drapeJob])")
        assert got == [["Tee", "0", "M-0"], ["Top", "1", "M-1"]]
        assert "draped together" in pg.inner_text(".toast")
    finally:
        pg.evaluate("window.api = __a0; showDrape = __sd; renderAdvice = __ra; 0")
    assert not pg.errors, pg.errors
