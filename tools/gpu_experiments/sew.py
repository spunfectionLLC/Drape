"""GPU sewing, frame by frame: seam gap, CG iterations, budget hits. usage: sew.py budget [block fabric]"""
import json, subprocess, sys
from pathlib import Path
sys.path.insert(0, "."); sys.path.insert(0, "tools")
import numpy as np
budget = int(sys.argv[1]); block = sys.argv[2] if len(sys.argv) > 2 else "trousers"; fabn = sys.argv[3] if len(sys.argv) > 3 else "jersey"
from drape import gpu
if budget != 48:     # the shaders with another CG budget (it sizes SCAL's layout)
    import export_wgsl as E
    src = E.SRC.read_text(encoding="utf-8").replace("const SPR_CG_BUDGET = 48;", f"const SPR_CG_BUDGET = {budget};")
    tmp = Path(sys.argv[0]).parent / f"lsp_{budget}.js"; tmp.write_text(src, encoding="utf-8")
    out = subprocess.run(["node", "-e", E.NODE_SCRIPT, str(tmp)], capture_output=True, text=True, encoding="utf-8", check=True)
    gpu._W = json.loads(out.stdout)
from drape.blocks import draft_block
from drape.fabrics import get, panel_fabrics
from drape.springs import SpringSimulator
from drape.live import sim_setup
from drape.studio import server as Srv
init = Srv.api_init(); a = Srv.api_avatar({"measurements": init["examples"]["female_M"]}); A = Srv.S.avatars[a["id"]]
g, _ = draft_block(block, A["body"], A["meas"]); fab = get(fabn)
sim = SpringSimulator(panel_fabrics(g, fab), A["body"], fab)
gp = gpu.GPUSprings(sim_setup(sim, sim.body, fabn, grid_h=sim.body.h))
gp.self_while_sewing = False
variant = sys.argv[4] if len(sys.argv) > 4 else ""
if variant == "nospeed":         # as springs.py: speed substeps only while cloth-on-cloth runs
    _plan0 = gp._plan
    def _plan():
        k, ph = gp.phase(); on = gp.self_on
        if ph == "sew" and k == 1 and not gp.self_while_sewing: gp.self_on = False
        _plan0(); gp.self_on = on
    gp._plan = _plan
if variant == "fixed":
    _step0 = gp.step
    def step(n=1):
        gp.cg_budget = 48; _step0(n); gp.cg_budget = 48
    gp.step = step
S = np.asarray(sim.g.seams)
f = 0
while gp.time < sim.sew_time:
    gp.step(1); f += 1
    if f >= 36 or f % 12 == 0:
        x = gp.positions(); d = np.linalg.norm(x[S[:, 0]] - x[S[:, 1]], axis=1) * 1000
        print(f"{variant or 'base'} frame {f}: gap max {d.max():6.1f} p99 {np.percentile(d, 99):5.1f} mm | cg {gp.cg_iters:3d} hit {gp.cg_budget_hit} next budget {gp.cg_budget} | substeps {gp.substeps} v {gp.v_measured:.2f}", flush=True)
x = gp.positions(); v = gp.velocities(); d = np.linalg.norm(x[S[:, 0]] - x[S[:, 1]], axis=1)
ei = g.meta["edge_index"]; owner = {}
for (pn, en), ids in ei.items():
    for q in ids: owner.setdefault(int(q), f"{pn}.{en}")
from drape.meshbody import grid_sdf_batch
B = sim.body
for k in np.argsort(-d)[:4]:
    a, b = S[k]; mid = 0.5 * (x[a] + x[b])
    sd = grid_sdf_batch(np.array([x[a], x[b], mid]), B.grid, B.origin, B.h) * 1000
    print(f"pair {a}-{b} {owner.get(int(a))}|{owner.get(int(b))} gap {d[k]*1000:.1f} mm  a={np.round(x[a],3)} b={np.round(x[b],3)} skin a/b/mid {np.round(sd,1)} mm  |v| {np.linalg.norm(v[a]):.2f} {np.linalg.norm(v[b]):.2f}  w {gp.Wfull[a]:.0f} {gp.Wfull[b]:.0f}")
