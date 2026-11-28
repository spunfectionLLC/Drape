"""How much pocket bag shows from outside after the website's drape (spec 1.1): the studio's own
drape job, the cloth on the GPU (as the page does), the result as the studio shows it (inside
pieces tucked). Renders front / right / back / left with the bags pure red and counts red pixels.
usage: visible_bags.py starter [starter ...]  (or block:shift_dress for the block + 2 pockets)"""
import base64, sys
from pathlib import Path
sys.path.insert(0, "."); sys.path.insert(0, "tests")
import numpy as np
import matplotlib.pyplot as plt
from drape import dedit as E, gpu, webapi
from drape.render import Renderer
from drape.live import sim_setup
from drape.studio import server as S
from test_v9 import S_design

OUT = Path("out/fit_check/bags")
OUT.mkdir(parents=True, exist_ok=True)
init = S.api_init()
a = S.api_avatar({"measurements": init["examples"]["female_M"]}); A = S.S.avatars[a["id"]]


def design_of(what):
    if what.startswith("block:"):
        blk = what.split(":", 1)[1]
        d = S.api_to_scratch({"avatar": a["id"], "block": blk, "choices": {"Shape": "Swing"} if blk == "shift_dress" else {}})["design"]
        for side in ("r", "l"):
            ref = next(f"front.{e['name']}" for e in E.piece(d, "front")["edges"] if e["name"].startswith("side") and e["name"].endswith(side))
            d = S.api_edit({"design": d, "op": "inseam_pocket", "args": {"ref": ref}, "avatar": a["id"]})["design"]
        return d, "jersey"
    from drape.starters import STARTERS
    return S.api_starter({"avatar": a["id"], "key": what})["design"], STARTERS[what].fabric


def drape(d, fabric):
    r = webapi.api_drape({"avatar": a["id"], "design": S_design(d), "fabric": fabric, "quality": "full"})
    if r["job"] not in webapi.JOBS:
        raise RuntimeError(S.api_job(r["job"]).get("error", "")[-800:])
    job, sim, n = webapi.JOBS[r["job"]]
    gp = gpu.GPUSprings(sim_setup(sim, sim.body, fabric, grid_h=sim.body.h))
    import os
    layered = bool(sim.self_collision and (sim._group is not None or sim._layer_pairs is not None))
    gp.self_while_sewing = layered          # as the website does (webapi: self_while_sewing for layered designs)
    print(f"   layered design: {layered}; contact while sewing: {gp.self_while_sewing}", flush=True)
    for _ in range(n):
        gp.step(1)
    webapi.api_drape_done({"job": r["job"], "x": base64.b64encode(gp.positions().astype(np.float32).tobytes()).decode(),
                           "v": base64.b64encode(gp.velocities().astype(np.float32).tobytes()).decode()})
    res = S.api_job(r["job"])
    assert res["state"] == "done", res.get("error")
    return np.load(Path(S.S.jobs[r["job"]]["outdir"]) / "result.npz"), res


def visible(z, tag):
    x, tris, pid, names = z["x"], z["tris"], z["panel_id"], list(z["panel_names"])
    bag = np.isin(pid, [k for k, nm in enumerate(names) if "_bag" in nm])
    if not bag.any():
        return None
    col = np.where(bag[:, None], [1.0, 0.0, 0.0], [0.2, 0.45, 0.9])
    R = Renderer(A["body"], width=360, height=540, scale=300, center=(0.0, float(x[:, 1].mean())))
    counts, imgs = {}, []
    for yaw, nm in ((0, "front"), (90, "right"), (180, "back"), (270, "left")):
        im = R.render(x, tris, col, yaw=yaw).astype(float)
        if im.max() > 1.5:
            im = im / 255.0
        red = (im[..., 0] > 0.35) & (im[..., 1] < 0.45 * im[..., 0]) & (im[..., 2] < 0.45 * im[..., 0])
        counts[nm] = int(red.sum()); imgs.append(im)
    plt.imsave(OUT / f"{tag}.png", np.clip(np.hstack(imgs), 0, 1))
    return counts


for what in sys.argv[1:]:
    d, fab = design_of(what)
    z, res = drape(d, fab)
    c = visible(z, what.replace(":", "_"))
    m = res["metrics"]
    # geometric check: a bag point is outside when it's farther from the body than the nearest shell point
    from scipy.spatial import cKDTree
    from drape.meshbody import grid_sdf_batch
    B = A["body"]; x, pid, names = z["x"], z["panel_id"], list(z["panel_names"])
    bag = np.isin(pid, [k for k, nm in enumerate(names) if "_bag" in nm])
    sd = grid_sdf_batch(np.ascontiguousarray(x), B.grid, B.origin, B.h) * 1000
    d_, j = cKDTree(x[~bag]).query(x[bag])
    shell_sd = sd[~bag][j]
    out = sd[bag] > shell_sd + 0.5
    print(f"   geometric: {out.mean()*100:.1f}% of bag points outside the shell (by > 0.5 mm); median bag-shell gap "
          f"{np.median(shell_sd - sd[bag]):.1f} mm; nearest shell point median {np.median(d_)*1000:.1f} mm away", flush=True)
    np.save(OUT / f"{what.replace(':', '_')}_x.npy", x)
    xb = x[bag]; wy = B.section_y("waist")
    bagtop = np.array([x[pid == k, 1].max() for k in np.unique(pid[bag])]).mean()
    print(f"   outside points: height vs waist (cm) p10/50/90 {np.round(np.percentile((xb[out, 1] - wy) * 100, [10, 50, 90]), 1)}; "
          f"all bag points {np.round(np.percentile((xb[:, 1] - wy) * 100, [10, 50, 90]), 1)}; bag top {(bagtop - wy) * 100:.1f}; "
          f"outside points' distance to the shell {np.round(np.percentile(sd[bag][out] - shell_sd[out], [50, 90]), 1)} mm", flush=True)
    print(f"{what} ({fab}): bag pixels visible {c} | inside {m['penetrating_verts']} KE {m['kinetic_energy_uJ']:.0f}", flush=True)
