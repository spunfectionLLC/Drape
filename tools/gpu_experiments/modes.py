"""Full GPU drapes in both modes: 'ref' = welds at springs.py's times (gpu.drape_on_gpu), 'end' = the
browser's way (no welds while draping, one at the end). usage: modes.py case [case ...]"""
import sys, time
sys.path.insert(0, "."); sys.path.insert(0, "tools")
import numpy as np
from drape import gpu
from drape.fabrics import get, panel_fabrics
from drape.springs import SpringSimulator
from drape.live import sim_setup

def end_mode(sim, n):
    gp = gpu.GPUSprings(sim_setup(sim, sim.body, "x", grid_h=sim.body.h)); gp.self_while_sewing = False
    for _ in range(n): gp.step(1)
    x = gp.positions(); S = np.asarray(sim.g.seams); gap = np.linalg.norm(x[S[:, 0]] - x[S[:, 1]], axis=1).max() * 1000
    sim.x[:] = x; sim.v[:] = gp.velocities(); sim.time = gp.time
    if sim.n_stages > 1: sim._stage_events(sim.time)
    if sim.do_weld and not sim.welded and len(sim.g.seams): sim.weld()
    return gap

def make(case):
    if case == "gloves":
        from pathlib import Path
        from drape.freeform import build_design, editor_to_design
        from drape.gloves import glove_design
        from drape.human import fit_human
        from drape.measurements import Measurements
        from drape.meshbody import MeshBody
        m = Measurements.load(Path("measurements") / "male_L.json"); h, _ = fit_human(m); body = MeshBody(h, measurements=m)
        g = build_design(editor_to_design(glove_design(body, m, "gloves")), body)
        return lambda: SpringSimulator(g, body, get("jersey")), 2.5, "pen 0"
    if case == "hoodie":
        import stage_report as R
        from drape.freeform import build_design, editor_to_design
        S, a, body = R.avatar(); tee, hooded = R.hooded_tee(S, a)
        g = build_design(editor_to_design(hooded), body); fab = get("jersey")
        return lambda: SpringSimulator(panel_fabrics(g, fab), body, fab, substeps=40), None, "pen 0, strain max < 100"
    from drape.blocks import draft_block
    from drape.studio import server as Srv
    init = Srv.api_init(); a = Srv.api_avatar({"measurements": init["examples"]["female_M"]}); A = Srv.S.avatars[a["id"]]
    blk, fabn = {"tee": ("tee", "jersey"), "trousers_j": ("trousers", "jersey"), "trousers_p": ("trousers", "poplin"),
                 "skirt": ("a_line_skirt", "jersey"), "pencil": ("pencil_skirt", "poplin")}[case]
    g, _ = draft_block(blk, A["body"], A["meas"]); fab = get(fabn)
    return lambda: SpringSimulator(panel_fabrics(g, fab), A["body"], fab), None, "pen 0, p99 < 6 (trousers < 8), KE < 20"

for case in sys.argv[1:]:
    mk, secs, bars = make(case)
    for mode in ("ref", "end"):
        sim = mk(); n = int(secs * sim.fps) if secs else int((3.5 + sim.extra_time) * sim.fps)
        t0 = time.time()
        if mode == "ref": st = gpu.drape_on_gpu(sim, n); gap = st["seam_gap_at_weld_mm"]
        else: gap = end_mode(sim, n)
        m = sim.metrics()
        print(f"{case:10s} {mode}: {time.time()-t0:5.1f} s  inside {m['penetrating_verts']}  p99 {m['strain_p99_pct']:.2f}%  max {m['strain_max_pct']:.0f}%  KE {m['kinetic_energy_uJ']:.2f} uJ  gap at weld {gap:.1f} mm   [bars: {bars}]", flush=True)
