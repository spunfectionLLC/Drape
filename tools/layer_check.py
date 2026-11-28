"""Multi-garment phase 4 check: leggings draped and frozen, then a dress draped over them.
How many of the dress's points end up inside the leggings (under their surface), and how close it rests.
    python tools/layer_check.py [--gpu]      (--gpu: the cloth on the GPU, the website's way)
"""
import base64
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
import numpy as np

from drape.studio import server as S

GPU = "--gpu" in sys.argv
NOCOLL = "--no-colliders" in sys.argv     # control: the dress ignores the leggings


def drape(aid, req):
    if GPU:
        from drape import gpu, webapi
        from drape.live import sim_setup
        from test_v9 import S_design
        r = webapi.api_drape({"avatar": aid, **req, **({"design": S_design(req["design"])} if "design" in req else {})})
        job, sim, n = webapi.JOBS[r["job"]]
        gp = gpu.GPUSprings(sim_setup(sim, sim.body, req.get("fabric", "jersey"), grid_h=sim.body.h))
        gp.self_while_sewing = bool(r.get("self_while_sewing"))
        for _ in range(n):
            gp.step(1)
        webapi.api_drape_done({"job": r["job"], "x": base64.b64encode(gp.positions().astype(np.float32).tobytes()).decode(),
                               "v": base64.b64encode(gp.velocities().astype(np.float32).tobytes()).decode()})
        return S.api_job(r["job"])
    jid = S.api_drape({"avatar": aid, **req})["job"]
    while True:
        j = S.api_job(jid)
        if j["state"] != "running":
            assert j["state"] == "done", j.get("error")
            return j
        time.sleep(1)


def main():
    from drape.colliders import decode, garment_field, THICKNESS
    init = S.api_init()
    a = S.api_avatar({"measurements": init["examples"]["female_M"]})
    body = S.S.avatars[a["id"]]["body"]
    t = time.time()
    leg = drape(a["id"], {"block": "trousers", "choices": {"Fit": "Slim", "Length": "Full"}, "fabric": "jersey"})
    print(f"leggings draped in {time.time() - t:.0f} s: {leg['metrics']['penetrating_verts']} points in the body")
    frozen = {"v": leg["cloth"]["v"], "f": leg["cloth"]["f"]}
    t = time.time()
    dress = drape(a["id"], {"block": "shift_dress", "choices": {"Fit": "Fitted", "Length": "Knee"}, "fabric": "jersey",
                            "colliders": [] if NOCOLL else [frozen]})
    print(f"dress draped over them in {time.time() - t:.0f} s: {dress['metrics']['penetrating_verts']} points inside the body or the leggings")
    # the dress's points against the leggings' own field (no thickness): < 0 is under the leggings' surface
    LV, LF = decode(frozen)
    DV, _ = decode(dress["cloth"])
    h = 0.004
    lo, hi = DV.min(0) - 0.02, DV.max(0) + 0.02
    xs, ys, zs = (np.arange(lo[i], hi[i] + h, h) for i in range(3))
    field = garment_field(LV, LF, body, xs, ys, zs, thickness=0.0)
    from drape.meshbody import grid_sdf_batch
    s = grid_sdf_batch(np.ascontiguousarray(DV), field, np.array([xs[0], ys[0], zs[0]]), h)
    near = s < 0.02
    print(f"dress points within 2 cm of the leggings: {near.sum()}; under their surface: {(s < 0).sum()} "
          f"(by > 1 mm: {(s < -0.001).sum()}); gap where they touch: median {np.median(s[near]) * 1000:.1f} mm "
          f"(collision thickness {THICKNESS * 1000:.1f} mm)")
    return int((s < -0.001).sum())


if __name__ == "__main__":
    main()
