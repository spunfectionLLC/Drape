"""Where a starter's red fit message comes from: per piece, its hot points' strain vs its fabric.
usage: diag.py starter fabric [avatar_key] [param=value ...]"""
import base64, sys
sys.path.insert(0, "."); sys.path.insert(0, "tests")
import numpy as np
from scipy.spatial import cKDTree
from drape import gpu, webapi
from drape.live import sim_setup
from drape.freeform import _surf
from drape.studio import server as S
from test_v9 import S_design

key, fab = sys.argv[1], sys.argv[2]
avk = sys.argv[3] if len(sys.argv) > 3 and "=" not in sys.argv[3] else "female_M"
over_params = dict(a.split("=") for a in sys.argv[3:] if "=" in a)
from drape import starters as STM
from drape.blocks import preset_values
def _T(block, body, m, bm, **choices):
    from drape.freeform import template_design
    v = preset_values(block, choices, bm); v.update({k: float(x) for k, x in over_params.items()})
    print("drafting overrides:", v, flush=True)
    return template_design(block, body, m, v)
STM._T = _T
over_params = dict(over_params)
CAP = {}
_adv0, _vc0 = S._advise, S.vertex_comfort
def _vc(sim, fab):
    CAP['sim'] = sim; return _vc0(sim, fab)
def _adv(body, x, vs, *a, **k):
    if 'inside' in k: CAP.update(body=body, x=x.copy(), vs=vs.copy(), comfy=k.get('comfy'), lock=k.get('lock'))
    return _adv0(body, x, vs, *a, **k)
S._advise, S.vertex_comfort = _adv, _vc
init = S.api_init()
a = S.api_avatar({"measurements": init["examples"][avk]})
req = {"avatar": a["id"], "key": key}
if over_params:
    req["params"] = {k: float(v) for k, v in over_params.items()}
st = S.api_starter(req)
d = st["design"]
print("params:", {k: v for k, v in (st.get("params") or {}).items()} if st.get("params") else "(none)")
r = webapi.api_drape({"avatar": a["id"], "design": S_design(d), "fabric": fab, "quality": "full"})
job, sim, n = webapi.JOBS[r["job"]]
gp = gpu.GPUSprings(sim_setup(sim, sim.body, fab, grid_h=sim.body.h))
gp.self_while_sewing = bool(r.get("self_while_sewing"))
for _ in range(n):
    gp.step(1)
sim.x[:] = gp.positions(); sim.v[:] = gp.velocities()
webapi.api_drape_done({"job": r["job"], "x": base64.b64encode(gp.positions().astype(np.float32).tobytes()).decode(),
                       "v": base64.b64encode(gp.velocities().astype(np.float32).tobytes()).decode()})
res = S.api_job(r["job"])
for x_ in res.get("advice", []):
    print(f"  [{x_.get('level')}] {x_['text']}")
sim = CAP['sim']; x, vs, comfy, lock = CAP['x'], CAP['vs'], np.broadcast_to(CAP['comfy'], CAP['vs'].shape), np.broadcast_to(CAP['lock'], CAP['vs'].shape)
hot = vs > S.SNUG_STRAIN
Sf = _surf(CAP['body']); near = cKDTree(Sf.V).query(x)[1]
reg = np.where(Sf.regions['hand'][near] > 0.5, 'hand', np.where(Sf.regions['arm'][near] > 0.5, 'arm', 'body'))
names = sim.g.panel_names; pid = sim.g.panel_id
print(f'hot points {hot.sum()} of {len(vs)}')
for rg in ('hand', 'arm', 'body'):
    for p in np.unique(pid[hot & (reg == rg)]):
        s = hot & (reg == rg) & (pid == p)
        if s.sum() < 3: continue
        print(f'  {rg:5s} {names[p]:22s} n={s.sum():4d} strain p50/p90 {np.percentile(vs[s],50)*100:5.1f}/{np.percentile(vs[s],90)*100:5.1f}%  comfy {comfy[s][0]*100:.0f}% lock {lock[s][0]*100:.0f}%  y p10/p90 {np.percentile(x[s,1],10):.2f}/{np.percentile(x[s,1],90):.2f}')
