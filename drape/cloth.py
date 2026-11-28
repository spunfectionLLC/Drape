"""Cloth simulation code shared by the solvers: the fabric, constants, the
per-frame setup (weld, staged sewing, contact candidates) and topology helpers.

springs.py (mass-spring, implicit) builds on ClothSim. Nothing here is XPBD (removed
by design): no constraint projection, no Lagrange multipliers. The fabric's
"compliances" are just its stiffness inputs (spring_k, 1 / bend compliance).
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from ._jit import njit

from .body import Body, EXTRA_COLS
from .meshbody import grid_sdf
from .pattern import Garment


@dataclass
class Fabric:
    """Compliance = 1/stiffness. Smaller = stiffer."""
    name: str = "cotton jersey"
    density: float = 0.15           # kg/m^2
    stretch_compliance: float = 1e-7
    bend_compliance: float = 2e6    # isometric-bending compliance (see fabrics.py)
    thickness: float = 0.004        # body collision offset (m)
    self_thickness: float = 0.003   # cloth-cloth separation (m)
    friction: float = 0.4
    damping: float = 0.02           # velocity damping per frame-equivalent
    # anisotropy: compliance across the grain (weft / crosswise) and on the bias,
    # as multiples of the lengthwise (warp) compliance; and the strain where the
    # yarns straighten and the fabric locks up (much stiffer beyond it)
    weft_ratio: float = 1.0
    bias_ratio: float = 1.0
    lock_strain: float = 10.0
    # mass-spring solver (springs.py) only: in-plane stiffness along the grain, N/m.
    # 0 = derived from stretch_compliance (spring_k). Placeholders until the fabric
    # tester measures real values. TODO: calibrate.py should fit this too.
    stretch_k: float = 0.0


K_PER_COMPLIANCE = 3e-5   # spring_k = this / stretch_compliance: jersey ~300, poplin ~1500, denim ~3000, rib ~50 N/m


def spring_k(f) -> float:
    """In-plane spring stiffness (N/m) of a fabric for the mass-spring solver. Not
    1/stretch_compliance: those near-rigid values would need thousands of substeps
    as springs; strain limiting does that job instead."""
    return float(f.stretch_k) if f.stretch_k > 0 else K_PER_COMPLIANCE / f.stretch_compliance


# -------------------------------------------------------------- constants --
MAX_SPEED = 3.0         # m/s: cloth on a person never moves faster (a dropped skirt hem: ~2 m/s)
# staged sewing (stages.py): the body garment is sewn and settles first, then what's
# sewn onto it (hood, collar, cuffs, pockets), so the shirt isn't dragged to the hood
SEW2_TIME = 0.6         # s: sewing time of each stage after the first (the first: sim.sew_time)
SETTLE_TIME = 0.5       # s: settling after a stage's weld (on top of gravity_ramp) before the next
ANCHOR_W = 0.01         # while sewing stage k > 1: share of its seams' force on the already-sewn side.
                        # The spec's 0.05 was XPBD's (a share of each correction); as a share of a
                        # spring force over the whole sewing time it lifted the shirt (hood window
                        # p95 15.6 mm; 0.01: 5.7 mm, the tee alone 1.7 mm)
# Speed-based substeps: two layers closing at 2 v must not get more than half the
# self-contact thickness closer between self-collision checks, or a point jumps clean
# past a triangle and the side test then holds the crossing (a knot). Substeps
# follow the fastest point; what the cap can't cover is slowed down instead.
SPEED_SAFETY = 0.5
SPEED_HEADROOM = 1.25   # velocity can grow within the frame (gravity, a seam snapping in)
NSUB_CAP = 160          # CPU; live.js has its own (96)


SELF_MARGIN_MAX = 0.015      # the furthest a frame's cloth-on-cloth contact list reaches (m)


def plan_substeps(v_max, fps, nsub_base, self_every, thickness, cap=NSUB_CAP, prev=None):
    """Substeps for this frame from the fastest point's speed (m/s, headroom
    already added). Returns (nsub, self_every, v_clamp, speed_limited).
    Slow frames get exactly nsub_base and self_every; above it, self-collision
    runs every substep. nsub may rise at once but falls by at most 25% a frame."""
    def need(se):
        return int(np.ceil(2.0 * v_max * se / (fps * SPEED_SAFETY * thickness) - 1e-9))
    se = self_every
    ns = need(se)
    if ns > nsub_base and se != 1:
        se = 1
        ns = need(1)
    nsub = min(max(nsub_base, ns), cap)
    if prev is not None and prev > nsub:
        nsub = min(max(nsub, int(np.ceil(0.75 * prev - 1e-9))), cap)
    if nsub > nsub_base:
        se = 1
    limited = ns > cap
    v_clamp = cap * fps * SPEED_SAFETY * thickness / (2.0 * se) if limited else float("inf")
    return nsub, se, v_clamp, limited


UNFOLD_COMPLIANCE = 1e-2   # the springs across folds while sewing (m/N)


# ---------------------------------------------------------------- bending --
def hinge_setup(tris, edge_len):
    """Hinges (v0, v1 = shared edge, v2, v3 = opposite) with cotangent
    weights K and scale sqrt(3 / area) from the flat (unfolded) rest shape."""
    e_all = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    opp_all = np.concatenate([tris[:, 2], tris[:, 0], tris[:, 1]])
    key = np.sort(e_all, axis=1)
    order = np.lexsort((key[:, 1], key[:, 0]))
    key, opp = key[order], opp_all[order]
    same = np.all(key[1:] == key[:-1], axis=1)
    i, j = key[:-1][same, 0], key[:-1][same, 1]
    k, l = opp[:-1][same], opp[1:][same]
    e = edge_len(i, j)
    a, b = edge_len(i, k), edge_len(j, k)
    c, d = edge_len(i, l), edge_len(j, l)
    # unfold flat: i at 0, j at (e, 0), k above, l below
    P0 = np.zeros((len(e), 2)); P1 = np.stack([e, np.zeros_like(e)], 1)
    xk = (a * a - b * b + e * e) / (2 * e); yk = np.sqrt(np.maximum(a * a - xk * xk, 1e-14))
    xl = (c * c - d * d + e * e) / (2 * e); yl = -np.sqrt(np.maximum(c * c - xl * xl, 1e-14))
    P2 = np.stack([xk, yk], 1); P3 = np.stack([xl, yl], 1)

    def cot(u, v):
        cr = np.abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0])
        return (u * v).sum(1) / np.maximum(cr, 1e-12)
    e0 = P1 - P0; e1 = P2 - P0; e2 = P3 - P0; e3 = P2 - P1; e4 = P3 - P1
    c01, c02 = cot(e0, e1), cot(e0, e2)
    c03, c04 = cot(-e0, e3), cot(-e0, e4)
    A = 0.5 * (np.abs(e0[:, 0] * e1[:, 1] - e0[:, 1] * e1[:, 0]) + np.abs(e0[:, 0] * e2[:, 1] - e0[:, 1] * e2[:, 0]))
    K = np.stack([c03 + c04, c01 + c02, -c01 - c03, -c02 - c04], 1)
    ok = np.isfinite(K).all(1) & (A > 1e-12)
    hinges = np.stack([i, j, k, l], 1)[ok].astype(np.int64)
    return hinges, np.ascontiguousarray(K[ok]), np.sqrt(3.0 / A[ok])


# ------------------------------------------------------------- posed body --
@njit(cache=True)
def _label_at(px, py, pz, lab, origin, h):
    nx, ny, nz = lab.shape
    i = min(max(int(round((px - origin[0]) / h)), 0), nx - 1)
    j = min(max(int(round((py - origin[1]) / h)), 0), ny - 1)
    k = min(max(int(round((pz - origin[2]) / h)), 0), nz - 1)
    return lab[i, j, k]


@njit(cache=True)
def posed_distance(x, grid, origin, h, lab, adj, Rg, Pg, Hg, J, jr):
    """Signed distance of each point to the posed body (same rule as _collide_posed)."""
    G = Rg.shape[0]
    out = np.empty(x.shape[0])
    for i in range(x.shape[0]):
        best = 1e9
        for g in range(G):
            dx = x[i, 0] - Pg[g, 0]; dy = x[i, 1] - Pg[g, 1]; dz = x[i, 2] - Pg[g, 2]
            q0 = Rg[g, 0, 0] * dx + Rg[g, 1, 0] * dy + Rg[g, 2, 0] * dz + Hg[g, 0]
            q1 = Rg[g, 0, 1] * dx + Rg[g, 1, 1] * dy + Rg[g, 2, 1] * dz + Hg[g, 1]
            q2 = Rg[g, 0, 2] * dx + Rg[g, 1, 2] * dy + Rg[g, 2, 2] * dz + Hg[g, 2]
            lb = _label_at(q0, q1, q2, lab, origin, h)
            if not adj[g, lb]:
                continue
            if lb != g:
                ex = q0 - J[g, lb, 0]; ey = q1 - J[g, lb, 1]; ez = q2 - J[g, lb, 2]
                if ex * ex + ey * ey + ez * ez > jr * jr:
                    continue
            d = grid_sdf(q0, q1, q2, grid, origin, h)
            if d < best:
                best = d
        out[i] = best
    return out


# --------------------------------------------------------- self-collision --
@njit(cache=True)
def _hcell(ix, iy, iz, size):
    h = (ix * 92837111) ^ (iy * 689287499) ^ (iz * 283923481)
    return abs(h) % size


@njit(cache=True)
def _tri_cells(x, tris, t, cell, margin):
    lo = np.empty(3, np.int64); hi = np.empty(3, np.int64)
    for a in range(3):
        mn = min(x[tris[t, 0], a], x[tris[t, 1], a], x[tris[t, 2], a]) - margin
        mx = max(x[tris[t, 0], a], x[tris[t, 1], a], x[tris[t, 2], a]) + margin
        lo[a] = int(np.floor(mn / cell)); hi[a] = int(np.floor(mx / cell))
    return lo, hi


@njit(cache=True)
def _build_tri_hash(x, tris, cell, margin, size):
    """Counting-sort spatial hash: every triangle is listed in each cell its
    margin-inflated AABB overlaps. Returns (start[size+1], entries)."""
    count = np.zeros(size + 1, np.int64)
    for t in range(tris.shape[0]):
        lo, hi = _tri_cells(x, tris, t, cell, margin)
        for ix in range(lo[0], hi[0] + 1):
            for iy in range(lo[1], hi[1] + 1):
                for iz in range(lo[2], hi[2] + 1):
                    count[_hcell(ix, iy, iz, size) + 1] += 1
    for i in range(size):
        count[i + 1] += count[i]
    entries = np.empty(count[size], np.int64)
    fill = count[:-1].copy()
    for t in range(tris.shape[0]):
        lo, hi = _tri_cells(x, tris, t, cell, margin)
        for ix in range(lo[0], hi[0] + 1):
            for iy in range(lo[1], hi[1] + 1):
                for iz in range(lo[2], hi[2] + 1):
                    h = _hcell(ix, iy, iz, size)
                    entries[fill[h]] = t
                    fill[h] += 1
    return count, entries


@njit(cache=True)
def _is_near(v, a, nbr_start, nbr):
    if v == a:
        return True
    for k in range(nbr_start[v], nbr_start[v + 1]):
        if nbr[k] == a:
            return True
    return False


@njit(cache=True)
def _find_candidates(x, tris, start, entries, cell, size, margin, nbr_start, nbr):
    """Once per frame: (vertex, triangle) pairs that could touch this frame.
    Each substep then only processes this short list."""
    cap = 1024
    pv = np.empty(cap, np.int64); pt = np.empty(cap, np.int64)
    n = 0
    for v in range(x.shape[0]):
        px, py, pz = x[v, 0], x[v, 1], x[v, 2]
        h = _hcell(int(np.floor(px / cell)), int(np.floor(py / cell)), int(np.floor(pz / cell)), size)
        for e in range(start[h], start[h + 1]):
            t = entries[e]
            a, b, c = tris[t, 0], tris[t, 1], tris[t, 2]
            if _is_near(v, a, nbr_start, nbr) or _is_near(v, b, nbr_start, nbr) or _is_near(v, c, nbr_start, nbr):
                continue
            # cheap reject: outside the triangle's margin-inflated AABB
            out = False
            for k in range(3):
                q = x[v, k]
                lo = min(x[a, k], x[b, k], x[c, k]) - margin
                hi = max(x[a, k], x[b, k], x[c, k]) + margin
                if q < lo or q > hi:
                    out = True
                    break
            if out:
                continue
            e1x = x[b, 0] - x[a, 0]; e1y = x[b, 1] - x[a, 1]; e1z = x[b, 2] - x[a, 2]
            e2x = x[c, 0] - x[a, 0]; e2y = x[c, 1] - x[a, 1]; e2z = x[c, 2] - x[a, 2]
            nx = e1y * e2z - e1z * e2y; ny = e1z * e2x - e1x * e2z; nz = e1x * e2y - e1y * e2x
            nl = np.sqrt(nx * nx + ny * ny + nz * nz)
            if nl < 1e-14:
                continue
            dist = ((px - x[a, 0]) * nx + (py - x[a, 1]) * ny + (pz - x[a, 2]) * nz) / nl
            if abs(dist) >= margin:
                continue
            if n == cap:
                cap *= 2
                pv2 = np.empty(cap, np.int64); pt2 = np.empty(cap, np.int64)
                pv2[:n] = pv[:n]; pt2[:n] = pt[:n]
                pv, pt = pv2, pt2
            pv[n] = v; pt[n] = t; n += 1
    return pv[:n], pt[:n]



# ------------------------------------------------------------- topology --
def unfolded_bend_rest(tris: np.ndarray, edge_len) -> tuple[np.ndarray, np.ndarray]:
    """Bending pairs (opposite vertices across each interior edge) with rest
    length = their distance when the two triangles are unfolded flat.
    edge_len(i, j) -> rest length arrays. Works across welded seams where no
    single flat (u,v) chart contains both triangles."""
    e_all = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    opp_all = np.concatenate([tris[:, 2], tris[:, 0], tris[:, 1]])
    key = np.sort(e_all, axis=1)
    order = np.lexsort((key[:, 1], key[:, 0]))
    key, opp = key[order], opp_all[order]
    same = np.all(key[1:] == key[:-1], axis=1)
    i, j = key[:-1][same, 0], key[:-1][same, 1]
    k, l = opp[:-1][same], opp[1:][same]
    e = edge_len(i, j)
    a, b = edge_len(i, k), edge_len(j, k)
    c, d = edge_len(i, l), edge_len(j, l)
    xk = (a * a - b * b + e * e) / (2 * e); yk = np.sqrt(np.maximum(a * a - xk * xk, 0))
    xl = (c * c - d * d + e * e) / (2 * e); yl = -np.sqrt(np.maximum(c * c - xl * xl, 0))
    rest = np.hypot(xk - xl, yk - yl)
    return np.stack([k, l], 1), rest


def _neighbors_csr(n, edges):
    both = np.concatenate([edges, edges[:, ::-1]])
    both = both[np.lexsort((both[:, 1], both[:, 0]))]
    start = np.zeros(n + 1, np.int64)
    np.add.at(start, both[:, 0] + 1, 1)
    return np.cumsum(start), both[:, 1].astype(np.int64).copy()


class ClothSim:
    """The solver-independent part of the cloth simulation (springs.py builds on it):
    fabrics and masses, the weld, staged sewing (STAGED_SEWING_SPEC), the body,
    contact candidates, the per-frame setup (_prepare), speed-based substeps and
    metrics. The solver adds step()."""
    def __init__(self, garment: Garment, body: Body, fabric: Fabric | None = None,
                 fps: int = 60, substeps: int = 40, self_collision: bool = True,
                 weld: bool = True, untangle: bool = False):
        self.fabric = fabric or Fabric()
        # Mass follows the fabric's weight (the garment was meshed with some
        # density; rescale). Bug fixed: Fabric.density used to be ignored.
        built = garment.meta.get("density", 0.15) if garment.meta else 0.15
        if abs(self.fabric.density - built) > 1e-12:
            garment = replace(garment, mass=garment.mass * self.fabric.density / built,
                              meta={**garment.meta, "density": self.fabric.density})
        # per-piece fabrics (linings, interfacing, rib cuffs...): garment.meta
        # "panel_fabrics" lists a Fabric (or None = the main fabric) per piece
        pf = (garment.meta or {}).get("panel_fabrics")
        if pf:
            fabs = [f or self.fabric for f in pf]
            dens = np.array([f.density for f in fabs])
            # mass was built with the main density above: rescale piece by piece
            garment = replace(garment, mass=garment.mass * dens[garment.panel_id] / self.fabric.density)
            self._vstretch = np.array([f.stretch_compliance for f in fabs])[garment.panel_id]
            self._vbend = np.array([f.bend_compliance for f in fabs])[garment.panel_id]
            self._vweft = np.array([f.weft_ratio for f in fabs])[garment.panel_id]
            self._vbias = np.array([f.bias_ratio for f in fabs])[garment.panel_id]
            self._vlock = np.array([f.lock_strain for f in fabs])[garment.panel_id]
        else:
            n0 = len(garment.x)
            self._vstretch = np.full(n0, self.fabric.stretch_compliance)
            self._vbend = np.full(n0, self.fabric.bend_compliance)
            self._vweft = np.full(n0, self.fabric.weft_ratio)
            self._vbias = np.full(n0, self.fabric.bias_ratio)
            self._vlock = np.full(n0, self.fabric.lock_strain)
        att = (garment.meta or {}).get("attach")
        if att is not None and len(att["v"]):
            self._att = [np.asarray(att["v"], np.int64), np.asarray(att["abc"], np.int64),
                         np.asarray(att["bary"], np.float64)]
            self._att_rest0 = np.linalg.norm(
                garment.x[self._att[0]] - (garment.x[self._att[1]] * self._att[2][..., None]).sum(1), axis=1)
        else:
            self._att = [np.zeros(0, np.int64), np.zeros((0, 3), np.int64), np.zeros((0, 3))]
            self._att_rest0 = np.zeros(0)
        self.g0 = garment                     # original, per-panel (for UV/OBJ)
        self.g, self.body = replace(garment), body
        self.fps, self.nsub = fps, substeps
        self.h = 1.0 / (fps * substeps)
        self.x = garment.x.astype(np.float64).copy()
        self.v = np.zeros_like(self.x)
        self.w = 1.0 / garment.mass
        # elastic casings (freeform._shrink_band): edges made shorter than the flat pattern
        e = garment.edges
        flat = np.linalg.norm(garment.uv[e[:, 0]] - garment.uv[e[:, 1]], axis=1)
        self._elastic_e = garment.edge_rest < 0.97 * flat
        self.vmap = np.arange(len(self.x))    # original vertex -> current vertex
        self.welded = False
        self.do_weld = weld and len(garment.seams) > 0
        self.self_collision = self_collision
        # several garments at once (server._merged_design): sewing starts with pieces flying together at up to the
        # speed cap; planned from rest the contacts didn't reach far enough and the garments went through each other
        # in the first 3 frames (two shirts: 1,282 crossings at 0.05 s). > 0: while a stage sews, contacts reach
        # SELF_MARGIN_MAX and no point moves further than that in a frame. 0 (one garment): as before, bit for bit.
        self.start_speed = 0.0
        self.self_every = 1   # run self-collision every Nth substep
        self.contact_damp = 0.15   # per-substep velocity damping for cloth-cloth contacts
        self.n_candidates = 0
        self.self_hits = 0
        self._set_hinges(self.g.tris, self.g.edges, self.g.edge_rest)
        s = garment.seams
        self.seam_rest0 = np.linalg.norm(self.x[s[:, 0]] - self.x[s[:, 1]], axis=1) if len(s) else np.zeros(0)
        self._nbrs = _neighbors_csr(len(self.x), self.g.edges)
        self._body_args = self._pack_body(body)
        self.time = 0.0
        self.untangle = untangle
        self.max_speed = MAX_SPEED
        self.speed_substeps = True      # substeps follow the fastest point (plan_substeps)
        self.nsub_frame = substeps      # substeps used in the last frame (nsub is the base)
        self.substeps_max = substeps
        self.v_max = 0.0
        self.speed_limited = False
        self.speed_limited_frames = 0
        off = (garment.meta or {}).get("body_offset")
        if off:
            # small garments on thin body parts (gloves): the usual 4 mm air gap adds
            # 2*pi*4 mm = 2.5 cm round a 5.5 cm finger, i.e. 40% tension that no real
            # glove has; keep the cloth closer to the skin there
            self.fabric = replace(self.fabric, thickness=min(self.fabric.thickness, float(off)))
        fine = (garment.meta or {}).get("fine_sdf")
        if fine and getattr(body, "kind", "") == "mesh":
            # small garments on thin body parts (gloves): a 3 mm distance grid just
            # round the garment, so fingertips aren't rounded off by the 6 mm one
            from .meshbody import build_grid
            lo, hi = garment.x.min(0) - 0.04, garment.x.max(0) + 0.04
            gr, go, gh = build_grid(body.V, body.F, h=float(fine), box=(lo, hi), clamp=0.03)
            self.set_grid(np.ascontiguousarray(gr, dtype=np.float64), go, gh)
        self._relax = None          # per-edge rest-length factor while untangling
        self.untangle_events = 0
        # separate garments (pieces not joined by any seam path) may already
        # collide with each other while the seams pull in: e.g. a top worn over
        # a skirt. Within one garment, seam partners would fight, so not there.
        self._group = self._garment_groups(garment)
        # pieces that lie under another one in the same garment (pocket bags):
        # kept apart from it before the weld too, except right at their seams
        lp = (garment.meta or {}).get("layer_pairs") or []
        if lp:
            npan = int(garment.panel_id.max()) + 1
            M = np.zeros((npan, npan), bool)
            for a, b in lp:
                M[a, b] = M[b, a] = True
            self._layer_pairs = M
            sv = np.zeros((len(garment.x), npan), bool)     # vertex v is sewn to piece p
            if len(garment.seams):
                a, b = garment.seams[:, 0], garment.seams[:, 1]
                sv[a, garment.panel_id[b]] = True
                sv[b, garment.panel_id[a]] = True
            self._seamv = sv
        else:
            self._layer_pairs = None
        self.sew_time = 0.8
        self.gravity_ramp = 0.3
        # staged sewing: per-seam-pair and per-piece stage (freeform.build_design, stages.py)
        meta = garment.meta or {}
        ss, ps = meta.get("seam_stage"), meta.get("piece_stage")
        npan = int(garment.panel_id.max()) + 1 if len(garment.panel_id) else 1
        self.seam_stage = (np.asarray(ss, np.int64) if ss is not None and len(ss) == len(garment.seams)
                           else np.ones(len(garment.seams), np.int64))
        pstage = np.asarray(ps, np.int64) if ps is not None and len(ps) == npan else np.ones(npan, np.int64)
        self.n_stages = int(max(self.seam_stage.max(initial=1), pstage.max(initial=1))) if self.do_weld else 1
        self.stage_names = {int(k): v for k, v in (meta.get("stage_names") or {}).items()}
        self._vstage = pstage[garment.panel_id] if self.n_stages > 1 else np.ones(len(self.x), np.int64)
        # several garments (server._merged_design), garment_freeze: when a garment's first stage starts, the garments
        # under it freeze (all of each garment: MULTI_GARMENT_SPEC constraint 3) and go into the collision grid as
        # frozen garments do (colliders.layered_grid). The new garment starts against the plain body (constraint 2:
        # nothing is pushed outward to make room) and the body contact, signed, pushes it out over them.
        pg = meta.get("piece_garment")
        self._vgar = (np.asarray(pg, np.int64)[garment.panel_id] if pg is not None and len(pg) == npan
                      else np.zeros(len(self.x), np.int64))
        self.garment_freeze = False
        self._frozen_gar = np.zeros(len(self.x), bool)    # points of garments frozen into the grid
        self.cur_stage = 1              # the stage being sewn / settled now
        self._force_staged = False
        self.weld_stage = 0             # the last stage welded
        self._pins = np.zeros(0, np.int64)        # pinned (original vertex ids)
        self._frozen = self._vstage > 1           # pieces not sewn on yet: still, not on the body
        if self._frozen.any():
            self.w = np.where(self._frozen, 0.0, self.w)

    # ----------------------------------------------------- staged sewing --
    def timeline(self):
        """[(start, sewing time)] for each stage (s). Stage 1 sews over sew_time with
        gravity off; each later one starts after the previous one's weld plus
        gravity_ramp + SETTLE_TIME, and sews over SEW2_TIME with gravity on."""
        out, t = [], 0.0
        for k in range(1, self.n_stages + 1):
            d = self.sew_time if k == 1 else SEW2_TIME
            out.append((t, d))
            t += d + self.gravity_ramp + SETTLE_TIME
        return out

    @property
    def extra_time(self):
        """Simulated time staging adds (s): add it to the seconds to simulate."""
        if self.n_stages < 2:
            return 0.0
        T = self.timeline()
        return T[-1][0] + T[-1][1] - self.sew_time

    def last_weld_time(self):
        T = self.timeline()
        return T[-1][0] + T[-1][1]

    def phase(self, t=None):
        """(stage, 'sew' | 'settle', label) at time t, e.g. (2, 'sew', 'Attaching hood')."""
        t = self.time if t is None else t
        T = self.timeline()
        k = max([i + 1 for i, (s0, _) in enumerate(T) if t >= s0] or [1])
        s0, d = T[k - 1]
        sew = t < s0 + d
        if sew and k == 1:
            lab = "Sewing the body" if self.n_stages > 1 else "Sewing"
        elif sew:
            lab = f"Attaching {self.stage_names.get(k) or 'the rest'}"
        else:
            lab = "Settling" if k < self.n_stages else "Draping"
        return k, ("sew" if sew else "settle"), lab

    def _stage_events(self, t):
        """Weld every stage whose sewing is done; wake the pieces of a stage that starts."""
        T = self.timeline()
        while self.weld_stage < self.n_stages and t >= sum(T[self.weld_stage]):
            k = self.weld_stage + 1
            mask = self.seam_stage <= k
            if mask.any():
                self.weld(mask=mask)
            self.weld_stage = max(self.weld_stage, k)
            if self.weld_stage >= self.n_stages:
                self.welded = True
        while self.cur_stage < self.n_stages and t >= T[self.cur_stage][0]:
            self.cur_stage += 1
            wake = self._frozen & (self._vstage == self.cur_stage)
            pinned = np.zeros(len(self.x), bool)
            pinned[self.vmap[self._pins]] = True
            self.w = np.where(wake & ~pinned, 1.0 / self.g.mass, self.w)
            self.v[wake] = 0.0
            self._frozen = self._frozen & ~wake
            self.__dict__.pop("_erest_start", None)
            if self.garment_freeze and wake.any():
                self._freeze_garments_under(int(self._vgar[wake].min()))

    def _freeze_garments_under(self, k):
        """Garment k starts: every garment under it (a lower number: the user's layer order) freezes where it hangs
        and goes into the collision grid. Only w, v and the grid change; no point moves."""
        from .colliders import layered_grid
        inner = (self._vgar < k) & ~self._frozen_gar
        if not inner.any():
            return
        self.w = np.where(inner, 0.0, self.w)
        self.v[inner] = 0.0
        self._frozen_gar |= inner
        T = np.asarray(self.g.tris)
        F = T[self._frozen_gar[T].all(1)]
        if not len(F):
            return
        grid, origin, h = layered_grid(self.body, [(np.array(self.x, np.float64), F)])
        self.set_grid(grid, origin, h)

    @staticmethod
    def _garment_groups(g):
        """Per-vertex id of the garment it belongs to (connected through seams)."""
        npan = int(g.panel_id.max()) + 1 if len(g.panel_id) else 0
        parent = list(range(npan))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        for a, b in g.seams:
            ra, rb = find(int(g.panel_id[a])), find(int(g.panel_id[b]))
            if ra != rb:
                parent[ra] = rb
        roots = np.array([find(i) for i in range(npan)])
        if len(set(roots.tolist())) < 2:
            return None
        return roots[g.panel_id]

    @staticmethod
    def _pack_body(body):
        """Arguments for the jitted collision: analytic SDF or mesh grid."""
        if getattr(body, "kind", "analytic") == "mesh":
            dummy_t = np.array([[100.0, 0.1, 0.1, 0.0], [100.1, 0.1, 0.1, 0.0]])
            return (dummy_t, np.zeros((0, 7)), 0.01, np.zeros((0, EXTRA_COLS)), np.zeros((0, 6)))
        return (body.torso, body.caps, body.blend, body.extras, body.groups)

    def set_posed(self, posed):
        """Collide with a posed body (pose.PosedCollider); call
        posed.advance(t) before each step to move it."""
        self._posed = posed
        self.set_grid(posed.grid, posed.origin, posed.h)   # the labels are on this grid

    def set_grid(self, grid, origin, h):
        """Collide against this signed-distance grid instead of the body's own
        (a moving body: the pose test blends grids frame by frame)."""
        self._grid_override = (grid, np.ascontiguousarray(origin, dtype=np.float64), float(h))

    def _grid_args(self):
        b = self.body
        ov = getattr(self, "_grid_override", None)
        if ov is not None:
            return (True,) + ov
        if getattr(b, "kind", "analytic") == "mesh":
            return True, b.grid, b.origin, b.h
        return False, np.zeros((2, 2, 2)), np.zeros(3), 1.0

    def _set_hinges(self, tris, edges, erest):
        n = int(max(tris.max(), edges.max())) + 1 if len(tris) else 1
        code = np.sort(edges, axis=1)
        code = code[:, 0] * n + code[:, 1]
        o = np.argsort(code); code, rest = code[o], erest[o]

        def edge_len(i, j):
            a, b = np.minimum(i, j), np.maximum(i, j)
            idx = np.searchsorted(code, a * n + b)
            return rest[np.minimum(idx, len(rest) - 1)]
        self._hinges, self._hK, self._hs = hinge_setup(tris, edge_len)

    def _posed_args(self):
        P = getattr(self, "_posed", None)
        if P is None:
            z3 = np.zeros((1, 3)); z33 = np.zeros((1, 3, 3))
            return (False, np.zeros((1, 1, 1), np.int16), np.zeros((1, 1), np.bool_), z33, z3, z33, z3, z3,
                    np.zeros((1, 1, 3)), 0.0)
        return (True, P.label, P.adj, P.R0, P.P0, P.R1, P.P1, P.H, P.J, P.jr)

    def _compliances(self):
        """Per-edge / per-bend compliance: the mean of the two end vertices'
        fabrics (a seam between two fabrics is in between)."""
        e, b = self.g.edges, self._hinges
        ec = 0.5 * (self._vstretch[e[:, 0]] + self._vstretch[e[:, 1]]) * self._aniso()
        bc = 0.5 * (self._vbend[b[:, 0]] + self._vbend[b[:, 1]]) if len(b) else np.zeros(0)
        return ec, bc

    def body_distance(self, x=None):
        """Signed distance to the body as it is now (posed or not)."""
        x = self.x if x is None else x
        P = getattr(self, "_posed", None)
        if P is not None:
            return posed_distance(x, P.grid, P.origin, P.h, P.label, P.adj, P.R1, P.P1, P.H, P.J, P.jr)
        return self.body.sdf(x)

    def _untangle_step(self, depth=0.002, grow=0.18, hold=0.25, back=0.4, over=0.30):
        """Cloth caught inside a body part (a sleeve pulled through the arm):
        give the cloth around it slack (rest lengths up by `grow`) so it can
        balloon off the body and the collision push it out on the right side,
        then take the slack back in over `back` seconds."""
        if not hasattr(self.body, "sdf") or self.time < self.last_weld_time():
            return
        e = self.g.edges
        if self._relax is None or len(self._relax) != len(e):
            self._relax = np.ones(len(e))
            self._relax_t = np.full(len(e), -1e9)
        d = self.body_distance()
        bad = d < -depth
        # cloth caught the wrong side of a limb shows up as over-stretch too
        L = np.linalg.norm(self.x[e[:, 0]] - self.x[e[:, 1]], axis=1)
        st = (L - self.g.edge_rest) / self.g.edge_rest
        lock = self._edge_lock()
        hot = st > np.maximum(over, 3 * np.minimum(lock, 1.0))
        bad[e[hot].ravel()] = True
        if bad.any():
            self.untangle_events += 1
            # the cloth around: two rings of neighbours
            near = bad.copy()
            for _ in range(2):
                hit = near[e[:, 0]] | near[e[:, 1]]
                near[e[hit].ravel()] = True
            hit = near[e[:, 0]] | near[e[:, 1]]
            self._relax[hit] = 1.0 + grow
            self._relax_t[hit] = self.time
        age = self.time - self._relax_t
        easing = (age > hold) & (self._relax > 1.0)
        if easing.any():
            f = np.clip((age[easing] - hold) / back, 0, 1)
            self._relax[easing] = 1.0 + grow * (1 - f)
        done = age > hold + back
        self._relax[done] = 1.0

    def _aniso(self):
        """Per-edge compliance factor from its direction on the flat pattern:
        1 along the grain (v, lengthwise), weft_ratio across it, bias_ratio at
        45 degrees (the diagonal edges carry the shear). Edges that cross a seam
        (no single flat chart) get the plain average."""
        e = self.g.edges
        cache = getattr(self, "_aniso_cache", None)
        if cache is not None and cache[0] is e:
            return cache[1]
        d = self.g.uv[e[:, 1]] - self.g.uv[e[:, 0]]
        L = np.linalg.norm(d, axis=1)
        c2 = np.where(L > 1e-12, (d[:, 1] / np.maximum(L, 1e-12)) ** 2, 0.5)
        s2 = 1.0 - c2
        weft = 0.5 * (self._vweft[e[:, 0]] + self._vweft[e[:, 1]])
        bias = 0.5 * (self._vbias[e[:, 0]] + self._vbias[e[:, 1]])
        f = c2 + s2 * weft + (bias - 0.5 * (1.0 + weft)) * 4.0 * c2 * s2
        f = np.maximum(f, np.minimum(1.0, weft))
        rest = self.g.edge_rest
        ok = (L > 0.5 * rest) & (L < 2.0 * rest)
        f = np.where(ok, f, 0.5 * (1.0 + weft))
        self._aniso_cache = (e, f)
        return f

    def _edge_lock(self):
        e = self.g.edges
        return 0.5 * (self._vlock[e[:, 0]] + self._vlock[e[:, 1]])

    def pin(self, idx):
        self._pins = np.r_[self._pins, np.atleast_1d(idx)].astype(np.int64)
        idx = self.vmap[np.atleast_1d(idx)]
        self.w[idx] = 0.0

    # ----------------------------------------------------------- weld ----
    def weld(self, mask=None):
        """Merge seam pairs into one vertex -> one continuous mesh. mask: which of
        the current seams (None = all); the others stay seams, renumbered."""
        g, n = self.g, len(self.x)
        parent = np.arange(n)
        if mask is None:
            mask = np.ones(len(g.seams), bool)
        mask = np.asarray(mask, bool)

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        for a, b in g.seams[mask]:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
        root = np.array([find(i) for i in range(n)])
        reps, new_id = np.unique(root, return_inverse=True)
        m = len(reps)

        mass = np.bincount(new_id, weights=g.mass, minlength=m)
        winv = np.where(self.w == 0, 0, 1)  # pinned groups stay pinned
        pinned = np.bincount(new_id, weights=1 - winv, minlength=m) > 0
        x = np.stack([np.bincount(new_id, weights=self.x[:, a] * g.mass, minlength=m) for a in range(3)], 1) / mass[:, None]
        v = np.stack([np.bincount(new_id, weights=self.v[:, a] * g.mass, minlength=m) for a in range(3)], 1) / mass[:, None]
        if not mask.all():                  # a stage's weld: points not merged keep their exact place
            alone = np.bincount(new_id, minlength=m)[new_id] == 1      # (x*m/m can round by 1e-16; a piece
            x[new_id[alone]] = self.x[alone]                            #  waiting to be sewn must not move)
            v[new_id[alone]] = self.v[alone]

        tris = new_id[g.tris]
        ok = (tris[:, 0] != tris[:, 1]) & (tris[:, 1] != tris[:, 2]) & (tris[:, 0] != tris[:, 2])
        tris = tris[ok]

        # edge rest lengths: from the original flat triangles, averaged where
        # two panels' seam edges collapse onto one welded edge
        old_e = g.edges
        ne = np.sort(new_id[old_e], axis=1)
        keep = ne[:, 0] != ne[:, 1]
        ne, rest = ne[keep], g.edge_rest[keep]
        code = ne[:, 0] * m + ne[:, 1]
        ucode, inv = np.unique(code, return_inverse=True)
        erest = np.bincount(inv, weights=rest) / np.bincount(inv)
        self._elastic_e = np.bincount(inv, weights=self._elastic_e[keep].astype(float)) > 0
        edges = np.stack([ucode // m, ucode % m], 1)

        def edge_len(i, j):
            a, b = np.minimum(i, j), np.maximum(i, j)
            idx = np.searchsorted(ucode, a * m + b)
            assert np.all(ucode[idx] == a * m + b), "bend edge missing from edge set"
            return erest[idx]
        bends, brest = unfolded_bend_rest(tris, edge_len)

        cnt = np.bincount(new_id, minlength=m)
        self._vstretch = np.bincount(new_id, weights=self._vstretch, minlength=m) / cnt
        self._vbend = np.bincount(new_id, weights=self._vbend, minlength=m) / cnt
        self._vweft = np.bincount(new_id, weights=self._vweft, minlength=m) / cnt
        self._vbias = np.bincount(new_id, weights=self._vbias, minlength=m) / cnt
        self._vlock = np.bincount(new_id, weights=self._vlock, minlength=m) / cnt
        self._att = [new_id[self._att[0]], new_id[self._att[1]], self._att[2]]
        # the seams not welded now (later stages): renumbered; one whose ends are now
        # the same vertex (it ended on a welded seam's vertex) counts as sewn
        rest_s = new_id[g.seams[~mask]] if len(g.seams) else np.zeros((0, 2), np.int64)
        alive = rest_s[:, 0] != rest_s[:, 1]
        seams_left = rest_s[alive].astype(np.int64).reshape(-1, 2)
        self.seam_rest0 = self.seam_rest0[~mask][alive] if len(self.seam_rest0) else np.zeros(0)
        self.seam_stage = self.seam_stage[~mask][alive]
        vst = np.full(m, 1 << 30, np.int64)
        np.minimum.at(vst, new_id, self._vstage)
        self._vstage = vst
        self._frozen = np.bincount(new_id, weights=self._frozen, minlength=m) > 0
        self._frozen_gar = np.bincount(new_id, weights=self._frozen_gar, minlength=m) > 0
        vg = np.zeros(m, np.int64)
        np.maximum.at(vg, new_id, self._vgar)               # seams never join two garments: one value per point
        self._vgar = vg
        self.g = replace(g, x=x, tris=tris, panel_id=g.panel_id[reps], edges=edges, edge_rest=erest,
                         bends=bends, bend_rest=brest, seams=seams_left, mass=mass,
                         uv=g.uv[reps])
        self.x, self.v = x, v
        self.w = np.where(pinned | self._frozen | self._frozen_gar, 0.0, 1.0 / mass)
        self.vmap = new_id[self.vmap]
        self._last_new_id = new_id
        self._nbrs = _neighbors_csr(m, edges)
        self._set_hinges(tris, edges, erest)
        self.welded = len(seams_left) == 0
        if self.welded:
            self.weld_stage = self.n_stages

    # ----------------------------------------------------------- step ----
    def _self_candidates(self, do_self, pre):
        """Self-collision candidates (vertex, triangle) for this frame; pre: before
        the weld, only between different garments and a pocket bag and its host."""
        cell = 0.02
        size = 1 << 16
        # hash margin = contact thickness + how far anything can move this frame
        # p99 speed, not max: a few jittering vertices must not blow up the margin
        vmax = float(np.percentile(np.sqrt((self.v ** 2).sum(1)), 99)) if len(self.v) else 0.0
        margin = min(max(self.fabric.self_thickness + 2.0 * vmax / self.fps, self.fabric.self_thickness + 0.001), SELF_MARGIN_MAX)
        if self._fast_sewing():
            margin = SELF_MARGIN_MAX
        if do_self:
            start, entries = _build_tri_hash(self.x, self.g.tris, cell, margin, size)
            cand_v, cand_t = _find_candidates(self.x, self.g.tris, start, entries, cell, size,
                                              margin, self._nbrs[0], self._nbrs[1])
            if pre:   # before welding: only between different garments...
                keep = (self._group[cand_v] != self._group[self.g.tris[cand_t, 0]]) if self._group is not None \
                    else np.zeros(len(cand_v), bool)
                if self._layer_pairs is not None:   # ...and between a pocket bag and the piece over it
                    pv, pt = self.g.panel_id[cand_v], self.g.panel_id[self.g.tris[cand_t, 0]]
                    tv = self.g.tris[cand_t]
                    # not where the two are sewn to each other (the seam pulls them together)
                    lay = self._layer_pairs[pv, pt] & ~self._seamv[cand_v, pt] & ~self._seamv[tv, pv[:, None]].any(1)
                    keep |= lay
                cand_v, cand_t = cand_v[keep], cand_t[keep]
        else:
            cand_v = cand_t = np.zeros(0, np.int64)
        if self._frozen_gar.any() and len(cand_v):     # frozen garments are in the grid: the grid does their contact
            keep = ~self._frozen_gar[cand_v] & ~self._frozen_gar[self.g.tris[cand_t]].any(1)
            cand_v, cand_t = cand_v[keep], cand_t[keep]
        return cand_v, cand_t

    def _prepare(self):
        """Everything a frame needs before the substeps (springs.py runs them): the weld, how far the sewing has got,
        self-collision candidates, eased rest lengths. Returns a dict."""
        t = self.time
        if self.n_stages > 1 or self._force_staged:   # (forced: a test checks one stage matches)
            return self._prepare_staged(t)
        if self.do_weld and not self.welded and t >= self.sew_time:
            self.weld()
        tight = min(t / self.sew_time, 1.0) if self.sew_time > 0 else 1.0
        srest = self.seam_rest0 * (1.0 - tight)
        gscale = min(max((t - self.sew_time) / self.gravity_ramp, 0.0), 1.0) if self.gravity_ramp > 0 else 1.0

        # self-collision only once panels are one mesh (seam partners would fight it)
        pre = self.self_collision and self.do_weld and not self.welded and (
            self._group is not None or self._layer_pairs is not None)
        do_self = self.self_collision and (self.welded or not self.do_weld or pre)
        x0 = self.x.copy()
        cand_v, cand_t = self._self_candidates(do_self, pre)
        self.n_candidates = len(cand_v)

        erest = self.g.edge_rest
        if not self.welded and self.sew_time > 0 and t < self.sew_time:
            # ease into the rest lengths while the seams pull in: elastic
            # edges (rest much shorter than where they start) would otherwise
            # snap inward in one frame and tunnel through other layers
            if not hasattr(self, "_erest_start"):
                # only edges made shorter than the flat pattern (elastic casings):
                # every other edge pulls to its rest length right away, so a piece
                # that starts stretched or squashed (trouser legs) unfolds before welding
                e = self.g.edges
                flat = np.linalg.norm(self.g.uv[e[:, 0]] - self.g.uv[e[:, 1]], axis=1)
                shrunk = self.g.edge_rest < 0.97 * flat
                now = np.linalg.norm(self.x[e[:, 0]] - self.x[e[:, 1]], axis=1)
                self._erest_start = np.where(shrunk, now, self.g.edge_rest)
            erest = self.g.edge_rest + (self._erest_start - self.g.edge_rest) * (1.0 - tight)
        arest = np.maximum(self._att_rest0 * (1.0 - tight), self.fabric.self_thickness + 0.0005)
        if self._relax is not None and len(self._relax) == len(erest):
            erest = erest * self._relax
        sewing = t < self.sew_time
        # while sewing: soft springs across every fold too, so pieces that start
        # crumpled (trouser legs wrapped round a knee) open out before the weld
        unfold = bool(not self.welded and self.do_weld and len(self.g.seams) and sewing and len(self.g.bends))
        return dict(t=t, tight=tight, srest=srest, gscale=gscale, do_self=do_self, x0=x0,
                    cand_v=cand_v, cand_t=cand_t, erest=erest, arest=arest, sewing=sewing, unfold=unfold)

    def _prepare_staged(self, t):
        """_prepare for staged sewing (STAGED_SEWING_SPEC): only the seams of the stages
        reached so far, each eased over its own stage; pieces not sewn on yet frozen
        (no mass, out of self-collision); the sewn side heavy for a later stage's seams."""
        self._stage_events(t)
        g, k = self.g, self.cur_stage
        T = self.timeline()
        s0, d = T[k - 1]
        sewing = t < s0 + d
        tk = np.array([0.0] + [min(max((t - a) / b, 0.0), 1.0) if b > 0 else 1.0 for a, b in T])  # by stage
        gscale = min(max((t - self.sew_time) / self.gravity_ramp, 0.0), 1.0) if self.gravity_ramp > 0 else 1.0
        act = self.seam_stage <= k          # (earlier stages' seams are welded already)
        seams = np.ascontiguousarray(g.seams[act])
        srest = self.seam_rest0[act] * (1.0 - tk[self.seam_stage[act]])
        ws = self.w
        if k > 1 and sewing and len(seams):
            # the attachment does the moving: the already-sewn side of this stage's seams
            # is heavy for the seams only (stretch, bending and collisions use real masses)
            ws = self.w.copy()
            ws[self._vstage < k] *= ANCHOR_W
        if self.weld_stage == 0:            # nothing welded yet: as before (other garments, pocket bags)
            pre = self.self_collision and (self._group is not None or self._layer_pairs is not None)
            do_self = pre
        else:
            pre, do_self = False, self.self_collision
        x0 = self.x.copy()
        cand_v, cand_t = self._self_candidates(do_self, pre)
        if len(cand_v):
            bad = self._frozen.copy()       # pieces not sewn on yet aren't there
            if self.weld_stage > 0 and len(g.seams):
                # near a seam still to weld, the partners would fight it (2 rings)
                near = np.zeros(len(self.x), bool)
                near[g.seams.ravel()] = True
                e = g.edges
                for _ in range(2):
                    hit = near[e[:, 0]] | near[e[:, 1]]
                    near[e[hit].ravel()] = True
                bad |= near
            keep = ~bad[cand_v] & ~bad[g.tris[cand_t]].any(1)
            cand_v, cand_t = cand_v[keep], cand_t[keep]
        self.n_candidates = len(cand_v)

        erest = g.edge_rest
        if sewing and d > 0:                # elastic edges of this stage's pieces ease in (as _prepare)
            key = (len(g.edges), self.weld_stage, k)
            if getattr(self, "_erest_key", None) != key:
                e = g.edges
                flat = np.linalg.norm(g.uv[e[:, 0]] - g.uv[e[:, 1]], axis=1)
                shrunk = g.edge_rest < 0.97 * flat
                now = np.linalg.norm(self.x[e[:, 0]] - self.x[e[:, 1]], axis=1)
                self._erest_start = np.where(shrunk, now, g.edge_rest)
                self._erest_key = key
            e = g.edges
            est = np.maximum(self._vstage[e[:, 0]], self._vstage[e[:, 1]])
            erest = g.edge_rest + (self._erest_start - g.edge_rest) * np.where(est == k, 1.0 - tk[k], 0.0)
        av, abc, bary = self._att
        if len(av):                         # topstitching / linings: from their piece's stage
            ast = self._vstage[av]
            on = ast <= k
            att = [av[on], abc[on], bary[on]]
            arest = np.maximum(self._att_rest0[on] * (1.0 - tk[ast[on]]), self.fabric.self_thickness + 0.0005)
        else:
            att, arest = self._att, np.zeros(0)
        if self._relax is not None and len(self._relax) == len(erest):
            erest = erest * self._relax
        bends, brest = g.bends, g.bend_rest
        unfold = bool(sewing and len(seams) and len(bends))
        if unfold:                          # fold springs on this stage's pieces only (the rest has settled)
            bm = (self._vstage[bends[:, 0]] == k) & (self._vstage[bends[:, 1]] == k)
            bends, brest = bends[bm], brest[bm]
            unfold = bool(bm.any())
        return dict(t=t, tight=float(tk[k]), srest=srest, gscale=gscale, do_self=do_self, x0=x0,
                    cand_v=cand_v, cand_t=cand_t, erest=erest, arest=arest, sewing=sewing, unfold=unfold,
                    seams=seams, ws=ws, att=att, bends=np.ascontiguousarray(bends), bend_rest=brest)

    def _fast_sewing(self):
        """Several garments, a stage sewing: plan for pieces moving at the speed cap (start_speed)."""
        return self.start_speed > 0 and self.phase()[1] == "sew"

    def _plan_speed(self, base, do_self, cap=NSUB_CAP):
        """Substeps for this frame: at least base, and enough that no two layers can
        pass through each other between self-collision checks (only matters while
        self-collision runs). Returns (nsub, self_every, speed cap)."""
        nsub, se, vlim = base, self.self_every, self.max_speed
        mv = self.w > 0
        self.v_max = float(np.sqrt((self.v[mv] ** 2).sum(1).max())) if mv.any() else 0.0
        self.speed_limited = False
        if do_self and self.speed_substeps:
            nsub, se, vc, self.speed_limited = plan_substeps(
                self.v_max * SPEED_HEADROOM, self.fps, base, self.self_every, self.fabric.self_thickness,
                max(cap, base), self.nsub_frame if self.nsub_frame > base else None)
            vlim = min(self.max_speed, vc)
        if do_self and self._fast_sewing():   # nothing outruns this frame's contact list
            vlim = min(vlim, (SELF_MARGIN_MAX - self.fabric.self_thickness) * self.fps)
        self.nsub_frame = nsub
        self.substeps_max = max(self.substeps_max, nsub)
        self.speed_limited_frames += int(self.speed_limited)
        return nsub, se, vlim

    def step(self):
        raise NotImplementedError("ClothSim is the base: use springs.SpringSimulator")

    # ------------------------------------------------------------ export --
    def original_positions(self) -> np.ndarray:
        """Current positions mapped back onto the original per-panel vertices."""
        return self.x[self.vmap]

    # ----------------------------------------------------------- metrics --
    def metrics(self) -> dict:
        x, g = self.x, self.g
        L = np.linalg.norm(x[g.edges[:, 0]] - x[g.edges[:, 1]], axis=1)
        strain = (L - g.edge_rest) / g.edge_rest
        xo = self.original_positions()
        s0 = self.g0.seams
        seam_gap = np.linalg.norm(xo[s0[:, 0]] - xo[s0[:, 1]], axis=1) if len(s0) else np.zeros(1)
        d = self.body_distance(x)
        ke = 0.5 * float((g.mass[:, None] * self.v**2).sum())
        return {
            "t": round(self.time, 3),
            "welded": self.welded,
            "stage": int(self.cur_stage), "n_stages": int(self.n_stages), "weld_stage": int(self.weld_stage),
            "finite": bool(np.isfinite(x).all()),
            "strain_mean_pct": float(np.abs(strain).mean() * 100),
            "strain_p99_pct": float(np.percentile(np.abs(strain), 99) * 100),
            "strain_max_pct": float(np.abs(strain).max() * 100),
            "seam_gap_max_mm": float(seam_gap.max() * 1000),
            "min_skin_dist_mm": float(d.min() * 1000),
            "penetrating_verts": int((d < 0).sum()),
            "self_contacts_last_frame": int(self.self_hits),
            "kinetic_energy_uJ": ke * 1e6,
            "max_speed_mm_s": float(np.linalg.norm(self.v, axis=1).max() * 1000),
            "substeps": int(self.nsub_frame),
            "substeps_max": int(self.substeps_max),
            "v_max_mm_s": float(self.v_max * 1000),
            "speed_limited": bool(self.speed_limited),
            "speed_limited_frames": int(self.speed_limited_frames),
        }
