"""The drape on the GPU: live_springs.js's solver (the same WGSL, exported to
data/springs_wgsl.json by tools/export_wgsl.py), run from Python through wgpu
(wgpu-native: Vulkan / D3D12 / Metal). The studio's "Drape it" uses it when a GPU is
there; springs.py's SpringSimulator stays the reference and the fallback.

`GPUSprings` is LiveSprings (studio/static/live_springs.js) line for line: the same
buffers, uniform, dispatch order, substep plan, candidate rebuilds and CG budget. Keep
the two in step. Velocity level (SPRING_VELOCITY_LEVEL_SPEC section 0) is the shaders'
(tests/test_v20_gpu_springs.py guards them); nothing here touches positions.

`drape_on_gpu(sim, frames)` runs a SpringSimulator's drape on the GPU and hands the
result back to it (positions, velocities, time, stages, welds) as if sim.step() had run
`frames` times. Everything after (metrics, fit, ease, the pose, exports) uses sim as
before. The welds are springs.py's: at each weld time the GPU stops, sim welds, and the
GPU carries on from the welded mesh.
"""
from __future__ import annotations

import base64
import json
import math
import os
import time
from pathlib import Path

import numpy as np

WGSL_FILE = Path(__file__).parent / "data" / "springs_wgsl.json"
_W = None
_DEVICE = None


def _wgsl():
    global _W
    if _W is None:
        _W = json.loads(WGSL_FILE.read_text(encoding="utf-8"))
    return _W


def _b64(s, dt):
    return np.frombuffer(base64.b64decode(s), dt)


def gpu_info():
    """(available, adapter summary or the reason not). DRAPE_GPU=0 turns it off."""
    if os.environ.get("DRAPE_GPU", "1") == "0":
        return False, "turned off (DRAPE_GPU=0)"
    try:
        import wgpu
        ad = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
    except Exception as e:                      # no wgpu, or no driver
        return False, f"{type(e).__name__}: {e}"
    if ad is None:
        return False, "no GPU adapter"
    if "cpu" in str(ad.info.get("adapter_type", "")).lower():
        return False, f"only a software adapter ({ad.summary})"
    return True, ad.summary


def _device():
    global _DEVICE
    if _DEVICE is None:
        import wgpu
        ad = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
        # only the size limits are raised; storage buffers per stage stay at WebGPU's 8
        _DEVICE = (ad.request_device_sync(required_limits={
            "max-storage-buffer-binding-size": min(ad.limits["max-storage-buffer-binding-size"], 1 << 30),
            "max-buffer-size": min(ad.limits["max-buffer-size"], 1 << 30)}), ad.summary)
    return _DEVICE


def plan_substeps(vmax, fps, base, self_every, thick, cap, prev, safety):
    """live_springs.js planSubsteps (cloth.py plan_substeps): (nsub, self_every, speed cap, limited)."""
    need = lambda se: math.ceil(2 * vmax * se / (fps * safety * thick) - 1e-9)
    se, ns = self_every, need(self_every)
    if ns > base and se != 1:
        se, ns = 1, need(1)
    nsub = min(max(base, ns), cap)
    if prev is not None and prev > nsub:      # falls by 25% a frame at most
        nsub = min(max(nsub, math.ceil(0.75 * prev - 1e-9)), cap)
    if nsub > base:
        se = 1
    limited = ns > cap
    return nsub, se, (cap * fps * safety * thick / (2 * se) if limited else math.inf), limited


class GPUSprings:
    """LiveSprings in Python (no mouse grab). setup: live.sim_setup(); v, t: the
    velocities and time to start from (a drape carried on after a weld)."""

    def __init__(self, setup, v=None, t=0.0):
        import wgpu
        W = _wgsl()
        self.W = W
        SU = wgpu.BufferUsage
        dev, self.adapter = _device()
        self.dev = dev
        S, SP = setup, setup["springs"]
        self.prm = prm = S["params"]
        self.consts = C = SP["consts"]
        self.n = n = S["n"]
        self.time = float(t)
        self.base = self.substeps = C["substeps"]
        self.h = 1 / prm["fps"] / self.base
        self.sp = SP
        self.wg = W["wg"]
        self.nwg = -(-n // self.wg)
        CGB, CAND, ECAND = W["cg_budget"], W["cand"], W["ecand"]
        self.x0 = _b64(S["x"], np.float32).copy()

        def mk(a, usage=SU.STORAGE):
            b = np.ascontiguousarray(a).tobytes()
            size = max(16, -(-len(b) // 4) * 4)
            return dev.create_buffer_with_data(data=b + bytes(size - len(b)), usage=usage | SU.COPY_DST | SU.COPY_SRC)

        def zeros(nbytes, usage=SU.STORAGE):
            return dev.create_buffer(size=max(16, nbytes), usage=usage | SU.COPY_DST | SU.COPY_SRC)
        self.X = mk(self.x0)
        v0 = np.zeros((n, 3)) if v is None else np.asarray(v, float).reshape(n, 3)
        self.V = mk(v0.astype(np.float32))
        param = _b64(SP["param"], np.float32).copy()
        self.Wfull = param[:n].copy()
        pid = _b64(S["panel_id"], np.uint32)
        ps = S.get("piece_stage") or []
        self.vstage = np.array([ps[p] if p < len(ps) else 1 for p in pid], np.int64)
        self.stages = prm["stages"] if prm.get("stages") else [[0, prm["sew_time"]]]
        self.n_stages = len(self.stages)
        self.stage = self.phase()[0]
        param[:n] = self._w_for(self.stage)
        self.PARAM = mk(param)
        self.TOPO = mk(_b64(SP["topo"], np.uint32))
        self.VEC = zeros(W["vb_count"] * n * 16)
        self.TMP = zeros((3 * SP["ns"] + 2 * SP["nnz"]) * 16)
        self.SCAL = zeros((4 * self.nwg + 8 + 3 * (CGB + 2)) * 4)
        sd = S["sdf"]
        q16 = _b64(sd["data"], np.int16)
        packed = np.zeros(len(q16) + (len(q16) & 1), np.int16)
        packed[:len(q16)] = q16
        self.SDF = mk(packed.view(np.int32))
        self.sdf_info = sd
        self.ntri = S["ntris"]
        self.ncells, self.slots = 1 << 16, 24
        self.cell = (S.get("self_cell") or 0.035) + 0.008
        TR = _b64(S["tris"], np.uint32).reshape(-1, 3)
        X = self.x0.reshape(-1, 3)
        lmax = max(float(np.linalg.norm(X[TR[:, a]] - X[TR[:, b]], axis=1).max(initial=0.0))
                   for a, b in ((0, 1), (1, 2), (2, 0)))
        self.ecell, self.eslots = 1.2 * lmax + 0.016, 48
        self.eHashAt = self.ncells * self.slots + n * (CAND + 1)
        self.eCandAt = self.eHashAt + self.ncells * self.eslots
        self.CNT = zeros(2 * self.ncells * 4)
        self.DVA = zeros(n * 16)
        self.SLOT = zeros((self.eCandAt + SP["ne"] * (ECAND + 1)) * 4)
        self.frameBuf = zeros(W["ubytes"], SU.UNIFORM)
        # batches (dynamic-offset uniforms, 256-byte stride): slot 0 = none, then CG iterations, strain, topstitch
        slots = [[0, 0, 0, 0]]
        self.itSlot = []
        for it in range(CGB + 1):
            self.itSlot.append(len(slots))
            slots.append([0, 0, 0, it])

        def batch_slots(offs):
            r = []
            for k in range(len(offs) - 1):
                r.append((len(slots), offs[k + 1] - offs[k]))
                slots.append([offs[k], offs[k + 1] - offs[k], 0, 0])
            return r
        self.strainSlots = batch_slots(SP["edge_batches"])
        self.attachSlots = batch_slots(SP["attach_batches"]) if SP["na"] else []
        ub = np.zeros(len(slots) * 64, np.uint32)
        for k, s in enumerate(slots):
            ub[k * 64:k * 64 + 4] = s
        self.batchBuf = mk(ub, SU.UNIFORM)
        BT = wgpu.BufferBindingType
        T = {"u": BT.uniform, "r": BT.read_only_storage, "s": BT.storage}

        def layout(types):
            return dev.create_bind_group_layout(entries=[
                {"binding": b, "visibility": wgpu.ShaderStage.COMPUTE, "buffer": {"type": T[t]}} for b, t in enumerate(types)])
        LB = dev.create_bind_group_layout(entries=[{"binding": 0, "visibility": wgpu.ShaderStage.COMPUTE,
                                                    "buffer": {"type": BT.uniform, "has_dynamic_offset": True}}])

        def group(L, bufs):
            return dev.create_bind_group(layout=L, entries=[
                {"binding": i, "resource": {"buffer": b, "offset": 0, "size": b.size}} for i, b in enumerate(bufs)])

        def pipes(code, Ls, names):
            m = dev.create_shader_module(code=code)
            pl = dev.create_pipeline_layout(bind_group_layouts=Ls)
            return {e: dev.create_compute_pipeline(layout=pl, compute={"module": m, "entry_point": e}) for e in names}
        LA = layout("ursrrsss")                 # module A: the solve (7 storage buffers)
        self.pA = pipes(W["solve"], [LA, LB], ["forces", "attach", "cgInit", "cgW", "cgStep", "applyDv", "strain"])
        self.gA = group(LA, [self.frameBuf, self.X, self.V, self.PARAM, self.TOPO, self.VEC, self.TMP, self.SCAL])
        self.gB = dev.create_bind_group(layout=LB, entries=[
            {"binding": 0, "resource": {"buffer": self.batchBuf, "offset": 0, "size": 16}}])
        LBo = layout("ussrsr")                  # module B: the body + finish (5)
        self.pB = pipes(W["body"], [LBo], ["body", "finish"])
        self.gBo = group(LBo, [self.frameBuf, self.X, self.V, self.PARAM, self.VEC, self.SDF])
        LC = layout("urrrrssss")                # module C: cloth on cloth (8)
        self.pC = pipes(W["self"], [LC], ["frameStart", "hinsert", "candidates", "selfimp", "ehinsert", "ecand", "eeimp", "gather"])
        self.gC = group(LC, [self.frameBuf, self.X, self.V, self.PARAM, self.TOPO, self.VEC, self.CNT, self.SLOT, self.DVA])
        self.fidx = {k: (i, t) for i, (k, t) in enumerate(W["fields"])}
        self.self_on = True
        self.self_while_sewing = True
        self.self_every = self.self_every_base = 1
        self.ee_on = True
        self.v_measured = float(np.sqrt((v0 ** 2).sum(1).max(initial=0.0)))
        self.v_clamp = prm.get("max_speed") or 3
        self.speed_limited = False
        self.substeps_max = self.substeps
        self.cg_iters = 0
        self.cg_budget_hit = False
        self.cg_budget = CGB
        self.d_rebuild = None
        self.rebuild_every = self.substeps
        self.steps = 0

    # -------------------------------------------------------------- stages --
    def _w_for(self, k):
        w = self.Wfull.copy()
        w[self.vstage > k] = 0
        return w

    def _set_stage(self, k):
        if k == self.stage and k != 1:
            return
        self.stage = k
        self.dev.queue.write_buffer(self.PARAM, 0, self._w_for(k).astype(np.float32).tobytes())

    def phase(self):
        """(stage, 'sew' | 'settle'), as ClothSim.phase()."""
        t, S = self.time, self.stages
        k = 1
        for i in range(self.n_stages):
            if t >= S[i][0]:
                k = i + 1
        return k, ("sew" if t < S[k - 1][0] + S[k - 1][1] else "settle")

    def frozen_panels(self, panel_id):
        return np.unique(panel_id[self.vstage > self.stage]).tolist()

    # ---------------------------------------------------------------- plan --
    def _plan(self):
        W, fps = self.W, self.prm["fps"]
        st = self.prm.get("self_thickness") or 0.003
        v_est = W["speed_headroom"] * self.v_measured
        k, ph = self.phase()      # speed substeps only while cloth-on-cloth runs (as springs.py; live_springs.js _plan)
        if self.self_on and (not (k == 1 and ph == "sew") or self.self_while_sewing):
            nsub, se, vc, lim = plan_substeps(v_est, fps, self.base, self.self_every_base, st, W["nsub_cap"],
                                              self.substeps if self.substeps > self.base else None, W["speed_safety"])
        else:
            nsub, se, vc, lim = self.base, self.self_every_base, math.inf, False
        self.substeps, self.self_every, self.h = nsub, se, 1 / fps / nsub
        self.v_clamp = min(self.prm.get("max_speed") or 3, vc)
        self.speed_limited = lim
        self.substeps_max = max(self.substeps_max, nsub)
        fit = (0.015 - st) / 2
        d_frame = min(self.v_clamp, 1.25 * self.v_measured) / fps
        n_reb = min(self.substeps, max(1, math.ceil(d_frame / fit)))
        self.rebuild_every = math.ceil(self.substeps / n_reb)
        self.d_rebuild = d_frame * self.rebuild_every / self.substeps

    def _frame(self):
        p, C, SP, t = self.prm, self.consts, self.sp, self.time
        sew = p["sew_time"]
        tight = min(t / sew, 1) if sew > 0 else 1
        k, ph = self.phase()
        if k != self.stage:
            self._set_stage(k)
        sewing_now = ph == "sew"
        gs = min(max((t - sew) / p["gravity_ramp"], 0), 1) if p["gravity_ramp"] > 0 else 1
        ns, ref = self.substeps, C.get("ref_substeps") or 40
        damp = 1 - (1 - p["damping"]) ** (1 / ns)
        if sewing_now:
            damp = max(damp, 1 - 0.99 ** (ref / ns))     # as springs.py step()
        cdamp = 1 - (1 - C["contact_damp"]) ** (ref / ns)
        buf = np.zeros(self.W["ubytes"] // 4, np.uint32)
        fv, iv = buf.view(np.float32), buf.view(np.int32)

        def put(name, val):
            i, ty = self.fidx[name]
            (fv if ty == "f32" else iv if ty == "i32" else buf)[i] = val
        s, T, P = self.sdf_info, SP["toff"], SP["poff"]
        st = p.get("self_thickness") or 0.003
        dreb = self.d_rebuild if self.d_rebuild is not None else self.v_measured / p["fps"]
        vals = dict(
            h=self.h, g=-9.81 * gs, damp=damp, ease=1 - tight, cdamp=cdamp, thick=p["thickness"], mu=p["friction"],
            n=self.n, grab=-1, grabK=0, selfThick=st, cell=self.cell, tx=0, ty=0, tz=0, vmax=self.v_clamp,
            sox=s["origin"][0], soy=s["origin"][1], soz=s["origin"][2], soh=s["h"],
            sdx=s["dims"][0], sdy=s["dims"][1], sdz=s["dims"][2],
            ntri=self.ntri, ncells=self.ncells, slots=self.slots, ns=SP["ns"], nh=SP["nh"], ne=SP["ne"],
            sewStage=k if k > 1 and sewing_now else 0, unfoldOn=1 if k == 1 and t < sew else 0, nwg=self.nwg,
            tau=C["self_tau"], deep=C["deep"], tol2=C["cg_tol"] ** 2, cgMax=self.cg_budget,
            cmargin=min(max(st + 2 * dreb, st + 0.001), 0.015),
            candAt=self.ncells * self.slots, ecell=self.ecell, eslots=self.eslots, eHashAt=self.eHashAt,
            eCandAt=self.eCandAt, oSpr=T["spr"], oIncs=T["incs"], oInc=T["inc"], oIncslot=T["incslot"],
            oRows=T["rows"], oRcol=T["rcol"], oAtt=T["att"], oTri=T["tri"], oGid=T["gid"],
            pSpr=P["spr"], pAtt=P["att"], pBk=P["bk"])
        for name, v in vals.items():
            put(name, v)
        for q in range(4):   # per stage: seam rest scale (-1: not started), the sewn side's share while it sews
            stg = self.stages[q] if q < len(self.stages) else None
            tk = (min(max((t - stg[0]) / stg[1], 0), 1) if stg[1] > 0 else 1) if stg else 1
            put(f"seamS{q}", 1 - tk if stg and q + 1 <= k else -1)
            put(f"seamA{q}", (p.get("anchor_w") or 0.05) if stg and q > 0 and q + 1 == k and sewing_now else 1)
        self.dev.queue.write_buffer(self.frameBuf, 0, buf.tobytes())
        return sewing_now and k == 1

    # ---------------------------------------------------------------- step --
    def step(self, frames=1):
        """`frames` frames on the GPU (one plan for all of them, as LiveSprings.step)."""
        dev, SP, CGB = self.dev, self.sp, self.W["cg_budget"]
        wg = lambda m: -(-m // 64)
        self._plan()
        for _ in range(frames):
            sewing = self._frame()
            dev.queue.write_buffer(self.SCAL, (4 * self.nwg + 2) * 4, np.zeros(2, np.float32).tobytes())
            selfc = self.self_on and (not sewing or self.self_while_sewing)
            enc = dev.create_command_encoder()
            ps = enc.begin_compute_pass()

            def A(e, m, slot=0):
                ps.set_pipeline(self.pA[e]); ps.set_bind_group(0, self.gA)
                ps.set_bind_group(1, self.gB, [slot * 256]); ps.dispatch_workgroups(m)

            def Bo(e):
                ps.set_pipeline(self.pB[e]); ps.set_bind_group(0, self.gBo); ps.dispatch_workgroups(wg(self.n))

            def Cs(e, m):
                ps.set_pipeline(self.pC[e]); ps.set_bind_group(0, self.gC); ps.dispatch_workgroups(m)
            reb = self.rebuild_every or self.substeps
            for s in range(self.substeps):
                if s % reb == 0:   # frame start (and, moving fast, every reb substeps): the lists and the sides
                    Cs("frameStart", wg(max(self.n, 2 * self.ncells)))
                    if selfc:
                        Cs("hinsert", wg(self.ntri)); Cs("candidates", wg(self.n))
                        if self.ee_on:
                            Cs("ehinsert", wg(SP["ne"])); Cs("ecand", wg(SP["ne"]))
                for slot, cnt in self.attachSlots:
                    A("attach", wg(cnt), slot)
                A("forces", wg(SP["ns"]))
                A("cgInit", self.nwg); A("cgW", self.nwg, self.itSlot[0])
                for it in range(self.cg_budget):
                    A("cgStep", self.nwg, self.itSlot[it])
                    if it + 1 < self.cg_budget:
                        A("cgW", self.nwg, self.itSlot[it + 1])
                A("applyDv", wg(self.n))
                for _ in range(self.consts["limit_iters"]):
                    for slot, cnt in self.strainSlots:
                        A("strain", wg(cnt), slot)
                Bo("body")
                if selfc and s % self.self_every == self.self_every - 1:
                    Cs("selfimp", wg(self.n))
                    if self.ee_on:
                        Cs("eeimp", wg(SP["ne"]))
                    Cs("gather", wg(self.n))
                Bo("finish")
            ps.end()
            dev.queue.submit([enc.finish()])
            self.time += 1 / self.prm["fps"]
            self.steps += 1
        sc = np.frombuffer(dev.queue.read_buffer(self.SCAL, (4 * self.nwg + 1) * 4, 12), np.float32)
        # CG iterations: the most any substep used; the next call's budget follows it
        self.cg_iters, self.cg_budget_hit = int(sc[1]), bool(sc[2] > 0.5)
        self.cg_budget = (min(CGB, self.cg_budget + 8) if self.cg_budget_hit
                          else min(CGB, max(8, int(sc[1]) + 2)))
        v = self.velocities()
        self.v_measured = float(np.sqrt((v ** 2).sum(1).max(initial=0.0)))

    def positions(self):
        return np.frombuffer(self.dev.queue.read_buffer(self.X), np.float32)[:3 * self.n].reshape(-1, 3).astype(np.float64)

    def velocities(self):
        return np.frombuffer(self.dev.queue.read_buffer(self.V), np.float32)[:3 * self.n].reshape(-1, 3).astype(np.float64)


def seam_gap_mm(sim, x):
    """Largest distance between two points sewn together (before the weld), mm."""
    S = np.asarray(sim.g.seams, np.int64).reshape(-1, 2)
    return float(np.linalg.norm(x[S[:, 0]] - x[S[:, 1]], axis=1).max(initial=0.0) * 1000)


def _next_weld(sim):
    """When sim welds next (s), as ClothSim does it: at the start of the first frame
    with t >= that time (one stage: _prepare; staged: _stage_events). inf: no more."""
    if not sim.do_weld or sim.welded or not len(sim.g.seams):
        return math.inf
    if sim.n_stages > 1 or sim._force_staged:
        T = sim.timeline()
        return sum(T[sim.weld_stage]) if sim.weld_stage < sim.n_stages else math.inf
    return sim.sew_time


def _weld_now(sim):
    """The weld sim.step() would do at the start of this frame."""
    if sim.n_stages > 1 or sim._force_staged:
        sim._stage_events(sim.time)
    else:
        sim.weld()


def drape_on_gpu(sim, frames, on_frame=None, every=12, fabric_key="jersey"):
    """Run `frames` frames of sim's drape on the GPU and hand the result back to sim, as
    if sim.step() had run `frames` times. The welds happen when springs.py does them:
    the GPU stops there, sim welds (ClothSim.weld / _stage_events), and the GPU carries on
    from the welded mesh (live mode never welds; draping on unwelded seams, a trouser
    outseam sometimes caught at the hem and stayed up to 58 mm open).
    on_frame(f, gpu, x): every `every` frames and at the end, with the positions on
    sim.g's current vertices. Returns the GPU's stats."""
    from .live import sim_setup
    if sim.time != 0:
        raise ValueError("drape_on_gpu needs a simulator that hasn't stepped yet")
    t0 = time.perf_counter()
    t_setup, f, gaps, welds, gp = 0.0, 0, [], 0, None
    while f < frames:
        ts = time.perf_counter()
        gp = GPUSprings(sim_setup(sim, sim.body, fabric_key, grid_h=getattr(sim.body, "h", None)), v=sim.v, t=sim.time)
        # cloth on cloth while the first stage sews only where springs.py has it then
        # (ClothSim._prepare: `pre`, layered garments); live mode keeps it on (it never welds)
        gp.self_while_sewing = bool(sim.self_collision and (sim._group is not None or sim._layer_pairs is not None))
        gp.self_on = bool(sim.self_collision)
        t_setup += time.perf_counter() - ts
        tw = _next_weld(sim)
        while f < frames and gp.time < tw:
            gp.step(1)
            f += 1
            if on_frame and ((f - 1) % every == 0 or f == frames):
                on_frame(f - 1, gp, gp.positions())
        x, v = gp.positions(), gp.velocities()
        if not np.isfinite(x).all() or not np.isfinite(v).all():
            raise FloatingPointError("the GPU drape went non-finite")
        sim.x[:] = x
        sim.v[:] = v
        sim.time = gp.time
        if f < frames or gp.time >= tw:      # the weld at the start of the next frame
            gaps.append(seam_gap_mm(sim, x))
            _weld_now(sim)
            welds += 1
    if gp is None:
        raise ValueError("no frames")
    if sim.n_stages > 1 or sim._force_staged:
        sim._stage_events(sim.time)          # the pieces the GPU woke: woken in sim too
    sim.nsub_frame = gp.substeps
    sim.substeps_max = max(sim.substeps_max, gp.substeps_max)
    sim.cg_iters = gp.cg_iters
    sim.solver_device = "gpu"
    return {"device": "gpu", "gpu_adapter": gp.adapter, "gpu_setup_s": round(t_setup, 2),
            "gpu_s": round(time.perf_counter() - t0 - t_setup, 2), "gpu_welds": welds,
            "seam_gap_at_weld_mm": max(gaps, default=0.0),
            "substeps_max": int(gp.substeps_max), "cg_iters_frame": int(gp.cg_iters)}
