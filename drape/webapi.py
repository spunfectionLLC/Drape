"""The studio's API inside the browser (the website build: no server).

The page runs this module in Pyodide (a Web Worker, site/py_worker.js); site/web_shim.js
sends it every `/api/...` request the studio makes and turns the answer back into a
fetch Response, so the studio's own code doesn't change. The routes are the server's
(studio/server.py Handler), calling the same api_* functions.

The one difference is the drape. On the desktop it runs in a separate process on the
CPU. Here `/api/drape` prepares the job (server._drape_job) and answers with the GPU
setup (live.sim_setup) and the frame count; the page runs the cloth on the GPU (the
live mode solver, live_springs.js), then posts the result to `/api/drape_done`, which
hands it to the job's simulator and lets the job finish (fit, ease, result.npz) as it
does on the desktop. `/api/job/<id>` then answers as usual.
"""
from __future__ import annotations

import base64
import json
import os
import queue
import tempfile
import traceback
import uuid

import numpy as np

WEB = True          # the studio page asks /api/init for this (web build: no poses yet)


def _server():
    from .studio import server as S
    return S


def _ok(obj, status=200):
    return {"status": status, "type": "application/json", "body": json.dumps(obj, default=_server()._jsonable)}


def _err(msg, status=500, trace=""):
    return {"status": status, "type": "application/json", "body": json.dumps({"error": msg, "trace": trace})}


def handle(method: str, path: str, body: str | None = None) -> dict:
    """One request: (method, path, JSON body) -> {status, type, body (str) or bytes_b64, filename}."""
    S = _server()
    from .features import FeatureOff
    path = path.split("?")[0]
    try:
        req = json.loads(body) if body else {}
        if method == "GET":
            if path == "/api/init":
                out = S.api_init()
                out["web"] = True
                return _ok(out)
            if path.startswith("/api/job/"):
                return _ok(S.api_job(path.rsplit("/", 1)[1]))
            if path.startswith("/api/guide/"):
                png = S.api_guide(path.rsplit("/", 1)[1].split(".")[0])
                return {"status": 200, "type": "image/png", "bytes_b64": base64.b64encode(png).decode()}
            return _err("not found", 404)
        routes = {
            "/api/avatar": S.api_avatar, "/api/draft": S.api_draft, "/api/scratch": S.api_scratch,
            "/api/to_scratch": S.api_to_scratch, "/api/tester_fit": S.api_tester_fit, "/api/live": S.api_live,
            "/api/starter": S.api_starter, "/api/edit": S.api_edit, "/api/explain": S.api_explain,
            "/api/costing": S.api_costing, "/api/fabric": S.api_fabric, "/api/trace": S.api_trace,
            "/api/girth": S.api_pick_girth, "/api/drape": api_drape, "/api/drape_done": api_drape_done,
            "/api/drape_cancel": api_drape_cancel,
        }
        if path in routes:
            return _ok(routes[path](req))
        if path == "/api/export":
            fname, mime, data = S.api_export(req)
            return {"status": 200, "type": mime, "bytes_b64": base64.b64encode(data).decode(), "filename": fname}
        return _err("not found", 404)
    except FeatureOff as e:
        return _err(str(e), 403)
    except Exception as e:
        return _err(str(e), 500, traceback.format_exc())


# ------------------------------------------------------------------ the drape --
JOBS = {}           # job id -> the generator, waiting for the GPU's result


def api_drape(req):
    """Prepare a drape for the GPU in the page. No poses on the web yet (they need the
    moving body on the GPU): a pose in the request is left out."""
    S = _server()
    from .live import sim_setup
    a = S.S.avatars[req["avatar"]]
    q = queue.Queue()
    outdir = tempfile.mkdtemp(prefix="drape_job_")
    sub = {k: req.get(k) for k in ("block", "choices", "params", "design", "quality", "colliders", "collider_mm")}
    fabric = req.get("fabric", "jersey")
    import time
    t0 = time.perf_counter()
    job = S._drape_job(q, a["shape"], a["meas"], sub, fabric, float(req.get("seconds", 3.5)), outdir)
    first = next(job, None)
    print(f"[drape] prepared in {time.perf_counter() - t0:.1f} s")
    jid = uuid.uuid4().hex[:10]
    S.S.jobs[jid] = dict(proc=None, q=q, progress=0.0, stage="Starting", state="running", result=None, outdir=outdir,
                         avatar=req["avatar"], block=req.get("block"))
    if first is None:              # it failed while preparing: the error is in q
        return {"job": jid}
    sim, n = first
    JOBS[jid] = (job, sim, n)
    t1 = time.perf_counter()
    setup = sim_setup(sim, sim.body, fabric)
    print(f"[drape] GPU setup in {time.perf_counter() - t1:.1f} s, {len(sim.x)} points, {n} frames")
    stages = None
    if sim.n_stages > 1:
        nm = [sim.stage_names.get(k) or "the rest" for k in range(2, sim.n_stages + 1)]
        stages = " · ".join(["Sewing body", "Settling"] + [f"Attaching {x}" for x in nm] + ["Draping"])
    # cloth on cloth while the first stage sews only where springs.py has it then (layered designs:
    # pocket bags, linings, layer copies). Off for them, a pocket bag passed through the dress front
    # while sewing and stayed outside it (10.6% of its points; with it on, 0.2%)
    layered = bool(sim.self_collision and (sim._group is not None or sim._layer_pairs is not None))
    return {"job": jid, "gpu": setup, "frames": int(n), "fps": float(sim.fps), "self_while_sewing": layered,
            "stage": stages or "Sewing and draping", "pose_skipped": bool(req.get("pose"))}


def _fail(jid, msg):
    """The job ends with an error the page's /api/job polling will see (not "running" for ever)."""
    j = _server().S.jobs.get(jid)
    if j is not None and j.get("state") == "running":
        j["q"].put(("error", msg))


def api_drape_cancel(req):
    """The GPU drape failed or was abandoned in the page: free the prepared job (its simulator and body grid
    hold a lot of the browser's memory) and end it."""
    jid = req.get("job") or ""
    item = JOBS.pop(jid, None)
    if item is not None:
        item[0].close()
    _fail(jid, req.get("reason") or "the drape was stopped")
    return {"job": jid}


def api_drape_done(req):
    """The GPU's result for a job: positions (and velocities), float32 base64, on the
    simulator's unwelded vertices. Welds as springs.py would have by now, then finishes."""
    jid = req["job"]
    if jid not in JOBS:
        raise LookupError("that drape isn't waiting for a result (it finished, failed or the page reloaded)")
    job, sim, n = JOBS.pop(jid)
    try:
        _finish(job, sim, n, req)
    except Exception as e:      # the page polls /api/job: it must end in an error, not stay "running"
        job.close()
        _fail(jid, f"{type(e).__name__}: {e}")
        raise
    return {"job": jid}


def _finish(job, sim, n, req):
    x = np.frombuffer(base64.b64decode(req["x"]), np.float32).reshape(-1, 3).astype(np.float64)
    v = (np.frombuffer(base64.b64decode(req["v"]), np.float32).reshape(-1, 3).astype(np.float64)
         if req.get("v") else np.zeros_like(x))
    if not np.isfinite(x).all():
        raise FloatingPointError("the drape went wrong on the graphics card (not a number)")
    sim.x[:] = x
    sim.v[:] = v
    sim.time = n / sim.fps
    sim.solver_device = "gpu (browser)"
    if sim.n_stages > 1 or sim._force_staged:
        sim._stage_events(sim.time)     # every stage's weld and wake-up, as stepping would have
    if sim.do_weld and not sim.welded and len(sim.g.seams):
        sim.weld()
    try:
        job.send(True)                  # the job finishes: fit, ease, result.npz -> q
    except StopIteration:
        pass


def cleanup_tmp():
    """Free the job folders (the browser's memory file system)."""
    import shutil
    for j in _server().S.jobs.values():
        d = j.get("outdir")
        if d and os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
