"""Setup for the live in-browser GPU solver (studio/static/live_springs.js).

The browser runs the springs solver (springs.py: mass-spring forces and bending,
implicit backward Euler, velocity-level contacts) on the GPU with WebGPU, at
interactive rates. This module packs the garment for it (_springs_payload) plus a
cropped body distance grid.

What the live solver leaves out (the full Drape does it): welding the seams into
one mesh. Cloth-on-cloth contact is in (SPR_SELF_WGSL in live_springs.js).
"""
from __future__ import annotations

import base64

import numpy as np

from .cloth import ANCHOR_W


def _b64(a):
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def color_batches(cons):
    """Greedy graph colouring of constraints (rows of vertex ids). Returns
    (order, offsets): constraints sorted by colour and where each colour starts."""
    cons = np.asarray(cons, np.int64)
    if not len(cons):
        return np.zeros(0, np.int64), [0]
    n = int(cons.max()) + 1
    used = [0] * n                  # bitmask of colours already touching each vertex
    col = np.empty(len(cons), np.int64)
    rows = cons.tolist()
    for c, r in enumerate(rows):
        m = 0
        for v in r:
            m |= used[v]
        k = 0
        while m >> k & 1:
            k += 1
        col[c] = k
        bit = 1 << k
        for v in r:
            used[v] |= bit
    order = np.argsort(col, kind="stable")
    counts = np.bincount(col, minlength=int(col.max()) + 1)
    return order, np.r_[0, np.cumsum(counts)].astype(int).tolist()


def _no_igl():
    import os
    if os.environ.get("DRAPE_NO_IGL"):
        return True
    try:
        import igl  # noqa: F401
        return False
    except ImportError:
        return True


def _crop_grid(body, lo, hi, h=0.008, grid=None):
    """Body distance grid resampled at h over the box lo..hi (m), int16 in 0.01 mm.
    grid: (G, origin, h) to sample instead of the body's own (a finer one)."""
    from scipy.ndimage import map_coordinates
    if grid is None and getattr(body, "_grid", 1) is None and _no_igl():
        # in a browser (no libigl) don't build the whole body's grid just to crop it:
        # compute the cropped box directly (10x fewer points)
        from .sdf_numpy import signed_distance_grid
        blo, bhi = body.V.min(0) - 0.05, body.V.max(0) + 0.05
        lo, hi = np.maximum(lo, blo), np.minimum(hi, bhi)
        dims = np.maximum(np.ceil((hi - lo) / h).astype(int) + 1, 2)
        ax = [lo[k] + np.arange(dims[k]) * h for k in range(3)]
        vals = signed_distance_grid(body.V, body.F, *ax)
        q = np.clip(np.round(vals * 1e5), -32767, 32767).astype(np.int16)
        return {"dims": dims.tolist(), "origin": lo.tolist(), "h": h, "data": _b64(q)}
    G, O, H = grid if grid is not None else (body.grid, body.origin, body.h)
    O, H = np.asarray(O, float), float(H)
    lo = np.maximum(lo, O)
    hi = np.minimum(hi, O + (np.array(G.shape) - 1) * H)
    dims = np.maximum(np.ceil((hi - lo) / h).astype(int) + 1, 2)
    ax = [lo[k] + np.arange(dims[k]) * h for k in range(3)]
    X, Y, Z = np.meshgrid(*ax, indexing="ij")
    coords = np.stack([(X - O[0]) / H, (Y - O[1]) / H, (Z - O[2]) / H])
    vals = map_coordinates(G, coords, order=1, mode="nearest")
    q = np.clip(np.round(vals * 1e5), -32767, 32767).astype(np.int16)
    return {"dims": dims.tolist(), "origin": lo.tolist(), "h": h, "data": _b64(q)}


def _csr(n, rows, vals):
    """Per-vertex lists: (start, values sorted by vertex)."""
    rows = np.asarray(rows, np.int64)
    o = np.argsort(rows, kind="stable")
    start = np.zeros(n + 1, np.int64)
    np.add.at(start, rows + 1, 1)
    return np.cumsum(start), np.asarray(vals, np.int64)[o]


def _seam_groups(n, seams):
    """Group id per vertex: vertices joined by seams (directly or through others) share one,
    as the weld would merge them. Ids are 0 .. groups - 1."""
    parent = np.arange(n)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a, b in np.asarray(seams, np.int64).reshape(-1, 2):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    roots = np.array([find(i) for i in range(n)], np.int64)
    return np.unique(roots, return_inverse=True)[1].astype(np.int64)


def _springs_payload(sim, fab):
    """The springs solver's data for live_springs.js (velocity level, implicit springs;
    springs.py is the reference). One integer buffer `topo` and one float buffer
    `param` (inverse masses first), with offsets, so no shader stage needs more than
    8 storage buffers. Springs: the mesh edges first, sorted by colour (the strain
    limit runs on them in colour batches), then the seams, then the fold springs.
    Forces are gathered per vertex (incidence lists), never scattered.

    The implicit solve's matrix is stored as 3x3 blocks per (vertex, neighbour) pair, in
    rows (CSR `rows` / `rcol`): neighbours through a spring or a bending hinge. The bending
    part is linear in x, so it is the same every substep: `bk` (one scalar times the
    identity per slot) is computed here once; the GPU adds the springs' blocks each substep.
    Each spring end also gets the slot of its partner in its row (`incslot`)."""
    from .springs import CG_MAX_ITER, CG_TOL, DEEP_PEN, IMPLICIT_SUBSTEPS, LIMIT_ITERS, SEAM_K, SELF_TAU, UNFOLD_K
    G, n = sim.g, len(sim.x)
    E = np.asarray(G.edges, np.int64)
    eorder, eoffs = color_batches(E)
    E = E[eorder]
    ke = sim._edge_k()[eorder]
    kv = np.zeros(n)
    np.maximum.at(kv, E[:, 0], ke)
    np.maximum.at(kv, E[:, 1], ke)
    flat = np.linalg.norm(G.uv[E[:, 0]] - G.uv[E[:, 1]], axis=1)
    rest = G.edge_rest[eorder]
    now = np.linalg.norm(sim.x[E[:, 0]] - sim.x[E[:, 1]], axis=1)
    start = np.where(rest < 0.97 * flat, now, rest)          # as ClothSim._prepare: eased in while sewing
    S = np.asarray(G.seams, np.int64).reshape(-1, 2)
    sst = np.asarray(sim.seam_stage, np.int64) if len(S) else np.zeros(0, np.int64)
    vst = sim._vstage
    anchor = ((vst[S[:, 0]] < sst) * 1 + (vst[S[:, 1]] < sst) * 2) if len(S) else np.zeros(0)
    B = np.asarray(G.bends, np.int64).reshape(-1, 2)
    pairs = np.vstack([E, S, B])
    ne, nse, nb = len(E), len(S), len(B)
    ns = len(pairs)
    # per spring: rest, start, k, lock, kind (0 edge, 1 seam, 2 fold), stage - 1, anchor bits, 0
    sp = np.zeros((ns, 8), np.float32)
    sp[:ne, 0], sp[:ne, 1], sp[:ne, 2], sp[:ne, 3] = rest, start, ke, sim._edge_lock()[eorder]
    if nse:
        sp[ne:ne + nse, 0] = sp[ne:ne + nse, 1] = sim.seam_rest0
        sp[ne:ne + nse, 2] = SEAM_K * np.maximum(kv[S[:, 0]], kv[S[:, 1]])
        sp[ne:ne + nse, 4], sp[ne:ne + nse, 5], sp[ne:ne + nse, 6] = 1, sst - 1, anchor
    if nb:
        sp[ne + nse:, 0] = sp[ne + nse:, 1] = G.bend_rest
        sp[ne + nse:, 2], sp[ne + nse:, 4] = UNFOLD_K, 2
    H = np.asarray(sim._hinges, np.int64).reshape(-1, 4)
    nh = len(H)
    _, bc = sim._compliances()
    hp = np.zeros((nh, 8), np.float32)
    if nh:
        hp[:, :4], hp[:, 4], hp[:, 5] = sim._hK, sim._hs, 1.0 / bc
    # the matrix rows: every vertex pair joined by a spring or sharing a hinge, plus the diagonal
    hq = np.stack(np.meshgrid(np.arange(4), np.arange(4), indexing="ij"), -1).reshape(-1, 2)
    ri = np.r_[np.arange(n), pairs[:, 0], pairs[:, 1], H[:, hq[:, 0]].reshape(-1)]
    rj = np.r_[np.arange(n), pairs[:, 1], pairs[:, 0], H[:, hq[:, 1]].reshape(-1)]
    keys = np.unique(ri * n + rj)
    rcol = keys % n
    rstart = np.searchsorted(keys, np.arange(n + 1) * n)
    slot = lambda a, b: np.searchsorted(keys, np.asarray(a, np.int64) * n + np.asarray(b, np.int64))

    bk = np.zeros(len(keys))
    if nh:
        c = (hp[:, 5] * hp[:, 4] ** 2).astype(float)
        hK = sim._hK
        np.add.at(bk, slot(H[:, hq[:, 0]], H[:, hq[:, 1]]).reshape(-1),
                  (c[:, None] * hK[:, hq[:, 0]] * hK[:, hq[:, 1]]).reshape(-1))
    # per vertex: the springs it is in (2 e + end), and its partner's slot in its row
    rows_ = np.r_[pairs[:, 0], pairs[:, 1]]
    vals = np.r_[2 * np.arange(ns), 2 * np.arange(ns) + 1]
    inc_start, inc = _csr(n, rows_, vals)
    e_, side = inc >> 1, inc & 1
    me = np.where(side == 0, pairs[e_, 0], pairs[e_, 1])
    other = np.where(side == 0, pairs[e_, 1], pairs[e_, 0])
    incslot = slot(me, other)
    av, abc, bary = sim._att
    na = len(av)
    att_idx = np.concatenate([np.asarray(av)[:, None], abc], 1) if na else np.zeros((0, 4), np.int64)
    aorder, aoffs = color_batches(att_idx) if na else (np.zeros(0, np.int64), [0])
    ap = np.zeros((na, 8), np.float32)
    if na:
        ap[:, :3], ap[:, 3] = bary, sim._att_rest0
        ap[:, 4], ap[:, 5] = SEAM_K * kv[av], vst[av] - 1
        att_idx, ap = att_idx[aorder], ap[aorder]
    # cloth on cloth (live never welds): points sewn together are one group, as the weld would
    # make them one point, and a point skips triangles touching its own group. Otherwise a
    # point where seams meet (an armpit) is pushed off the pieces it's sewn to and buzzes.
    gid = _seam_groups(n, S)
    topo_parts = [("spr", pairs.reshape(-1)), ("incs", inc_start), ("inc", inc), ("incslot", incslot),
                  ("rows", rstart), ("rcol", rcol),
                  ("att", att_idx.reshape(-1)), ("tri", np.asarray(G.tris, np.int64).reshape(-1)),
                  ("gid", gid)]
    offs, at, chunks = {}, 0, []
    for k, a in topo_parts:
        offs[k] = at; chunks.append(np.asarray(a, np.int64)); at += len(a)
    topo = np.concatenate(chunks + [np.zeros(4, np.int64)]).astype(np.uint32)
    w_full = np.where(sim._frozen, 1.0 / G.mass, sim.w)
    poffs = {"w": 0, "spr": n, "att": n + 8 * ns, "bk": n + 8 * ns + 8 * na}
    param = np.concatenate([w_full, sp.reshape(-1), ap.reshape(-1), bk, np.zeros(4)]).astype(np.float32)
    return {
        "topo": _b64(topo), "param": _b64(param), "toff": offs, "poff": poffs,
        "ns": int(ns), "ne": int(ne), "nh": int(nh), "na": int(na), "nnz": int(len(keys)),
        "edge_batches": [int(v) for v in eoffs], "attach_batches": [int(v) for v in aoffs],
        "consts": {"substeps": IMPLICIT_SUBSTEPS, "cg_max": CG_MAX_ITER, "cg_tol": CG_TOL, "limit_iters": LIMIT_ITERS,
                   "self_tau": SELF_TAU, "deep": DEEP_PEN, "contact_damp": float(sim.contact_damp), "ref_substeps": 40},
    }


def live_setup(g, body, fabric_key="jersey"):
    """Everything live_springs.js needs: the mesh, colours, the cropped body grid, the
    stages and timing, the seam partners, and the springs payload (_springs_payload)."""
    from .fabrics import get, panel_fabrics
    from .springs import SpringSimulator
    fab = get(fabric_key)
    sim = SpringSimulator(panel_fabrics(g, fab), body, fab)
    return sim_setup(sim, body, fabric_key, g.meta)


def sim_setup(sim, body, fabric_key, meta=None, grid_h=None):
    """live_setup for a SpringSimulator that already exists (not stepped yet): the GPU
    drape (gpu.py) uses the drape's own simulator. grid_h: the body grid's spacing
    (None: live mode's 8 mm crop; the drape passes the body's own, as springs.py uses)."""
    g = sim.g0
    meta = g.meta if meta is None else meta
    fab = sim.fabric                 # the garment may ask for a thinner body offset (gloves)
    G = sim.g
    n = len(sim.x)
    lo = sim.x.min(0) - 0.15
    hi = sim.x.max(0) + 0.15
    hi[1] = sim.x[:, 1].max() + 0.05
    # seam partners of each vertex (up to 3)
    part = -np.ones((n, 3), np.int32)
    cnt = np.zeros(n, int)
    for a, b in np.asarray(G.seams, int):
        for u, v in ((a, b), (b, a)):
            if cnt[u] < 3 and v not in part[u]:
                part[u, cnt[u]] = v; cnt[u] += 1
    rest_max = float(np.percentile(G.edge_rest, 99))
    self_cell = rest_max * 0.8 + fab.self_thickness + 0.004
    from .studio.server import _panel_colors
    cols = (_panel_colors(G.panel_id) * 255).astype(np.uint8)
    return {
        "n": n, "x": _b64(sim.x.astype(np.float32)),
        "tris": _b64(G.tris.astype(np.uint32)), "ntris": int(len(G.tris)), "colors": _b64(cols),
        "panel_id": _b64(G.panel_id.astype(np.uint32)), "uv": _b64(G.uv.astype(np.float32)),
        "sdf": (_crop_grid(body, lo, hi, 0.004, sim._grid_override) if getattr(sim, "_grid_override", None) is not None
                else _crop_grid(body, lo, hi) if grid_h is None else _crop_grid(body, lo, hi, grid_h)),
        "params": {"fps": sim.fps, "sew_time": sim.sew_time, "gravity_ramp": sim.gravity_ramp, "damping": fab.damping,
                   "thickness": fab.thickness, "friction": fab.friction,
                   "self_thickness": fab.self_thickness, "max_speed": float(sim.max_speed),
                   "start_speed": float(getattr(sim, "start_speed", 0.0)),
                   # [start, sewing time] per stage (s), as ClothSim.timeline()
                   "stages": [list(map(float, t)) for t in sim.timeline()], "anchor_w": ANCHOR_W,
                   "stage_names": {str(k): v for k, v in sim.stage_names.items()}},
        "piece_stage": [int(k) for k in ((meta or {}).get("piece_stage") or [1] * len(G.panel_names))],
        "fabric": fabric_key, "panel_names": list(G.panel_names),
        "partners": _b64(part), "self_cell": self_cell,
        "springs": _springs_payload(sim, fab),
    }
