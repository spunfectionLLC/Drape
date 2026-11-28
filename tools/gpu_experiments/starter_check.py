"""Spec 1.3: every starter x {female_M, male_M} x {cotton jersey, its suggested fabric}, draped the
website's way (the studio's drape job, the cloth on the GPU); prints each red (problem) message.
usage: starter_check.py part total   (splits the starters for parallel runs)"""
import base64, json, sys
from pathlib import Path
sys.path.insert(0, "."); sys.path.insert(0, "tests")
import numpy as np
from drape import gpu, webapi
from drape.live import sim_setup
from drape.starters import STARTERS
from drape.studio import server as S
from test_v9 import S_design

part, total = int(sys.argv[1]), int(sys.argv[2])
init = S.api_init()
keys = sorted(STARTERS)[part::total]
out = Path("out/fit_check") / f"starters_{part}.jsonl"; out.parent.mkdir(parents=True, exist_ok=True)
with open(out, "w", encoding="utf-8") as fh:
    for av_key in ("female_M", "male_M"):
        a = S.api_avatar({"measurements": init["examples"][av_key]})
        for k in keys:
            d = S.api_starter({"avatar": a["id"], "key": k})["design"]
            for fab in dict.fromkeys(["jersey", STARTERS[k].fabric]):
                try:
                    r = webapi.api_drape({"avatar": a["id"], "design": S_design(d), "fabric": fab, "quality": "full"})
                    if r["job"] not in webapi.JOBS:
                        raise RuntimeError(S.api_job(r["job"]).get("error", "")[-300:])
                    job, sim, n = webapi.JOBS[r["job"]]
                    gp = gpu.GPUSprings(sim_setup(sim, sim.body, fab, grid_h=sim.body.h))
                    gp.self_while_sewing = bool(r.get("self_while_sewing"))
                    for _ in range(n):
                        gp.step(1)
                    webapi.api_drape_done({"job": r["job"], "x": base64.b64encode(gp.positions().astype(np.float32).tobytes()).decode(),
                                           "v": base64.b64encode(gp.velocities().astype(np.float32).tobytes()).decode()})
                    res = S.api_job(r["job"])
                    adv = res.get("advice", [])
                    reds = [x["text"] for x in adv if x.get("level") == "problem"]
                    notes = [x["text"] for x in adv if x.get("level") == "note"]
                    row = {"starter": k, "avatar": av_key, "fabric": fab, "red": reds, "notes": notes,
                           "inside": res["metrics"].get("penetrating_verts")}
                except Exception as e:
                    row = {"starter": k, "avatar": av_key, "fabric": fab, "error": str(e)[:300]}
                fh.write(json.dumps(row) + "\n"); fh.flush()
                print(("RED " if row.get("red") else "ok  " if "red" in row else "ERR ") + f"{k} {av_key} {fab}: {row.get('red') or row.get('error') or ''}", flush=True)
