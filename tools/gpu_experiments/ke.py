"""Where the GPU's leftover motion is after a trouser drape (browser mode), and what stops it.
usage: ke.py variant   (base | noee | noself | lateself)"""
import sys; sys.path.insert(0, ".")
import numpy as np
from drape import gpu
from drape.blocks import draft_block
from drape.fabrics import get, panel_fabrics
from drape.springs import SpringSimulator
from drape.live import sim_setup
from drape.meshbody import grid_sdf_batch
from drape.studio import server as Srv
variant = sys.argv[1]; fabn = sys.argv[2] if len(sys.argv) > 2 else "poplin"
init = Srv.api_init(); a = Srv.api_avatar({"measurements": init["examples"]["female_M"]}); A = Srv.S.avatars[a["id"]]
g, _ = draft_block("trousers", A["body"], A["meas"]); fab = get(fabn)
sim = SpringSimulator(panel_fabrics(g, fab), A["body"], fab)
n = int((3.5 + sim.extra_time) * sim.fps)
setup = sim_setup(sim, sim.body, fabn, grid_h=sim.body.h); C = setup["springs"]["consts"]
print("consts:", {k: C[k] for k in ("contact_damp", "self_tau", "ref_substeps")})
if variant == "cdamp": C["contact_damp"] = min(0.6, 2 * C["contact_damp"])
if variant == "tau": C["self_tau"] = 2 * C["self_tau"]
gp = gpu.GPUSprings(setup); gp.self_while_sewing = False
if variant == "noee": gp.ee_on = False
if variant == "noself": gp.self_on = False
ke = []
for f in range(n):
    gp.step(1)
    if f >= n - 30:
        v = gp.velocities(); m = 1.0 / np.where(gp.Wfull > 0, gp.Wfull, np.inf)
        ke.append(0.5 * (m * (v ** 2).sum(1)).sum() * 1e6)
x, v = gp.positions(), gp.velocities()
sp = np.linalg.norm(v, axis=1) * 1000
d = grid_sdf_batch(x, sim.body.grid, sim.body.origin, sim.body.h) * 1000
print(f"{variant}: KE last 30 frames {min(ke):.1f}..{max(ke):.1f} uJ (mean {np.mean(ke):.1f}) | speed p99 {np.percentile(sp, 99):.0f} max {sp.max():.0f} mm/s")
top = np.argsort(-sp)[:400]
print(f"  fastest 400: height y {np.percentile(x[top,1],10):.2f}..{np.percentile(x[top,1],90):.2f} m, skin distance median {np.median(d[top]):.1f} mm, "
      f"on the skin (<5 mm) {np.mean(d[top] < 5)*100:.0f}% | all points on the skin {np.mean(d < 5)*100:.0f}%")
pid = sim.g.panel_id; print("  by piece:", {sim.g.panel_names[k]: int((pid[top] == k).sum()) for k in range(len(sim.g.panel_names))})
