"""Mass-spring cloth (Provot 1995): forces from springs and from the isometric
bending energy (Bergou 2006), integrated with linearised backward Euler (Baraff and
Witkin 1998, conjugate gradients, matrix-free), Provot's strain limit and the
contacts applied as velocity impulses (Bridson, Fedkiw and Anderson 2002).
`implicit=False` keeps the older explicit symplectic Euler, with substeps chosen
every frame from the stability limit (it needs 200-700 per frame and lets jersey
stretch to its lock on a tight glove; implicit uses IMPLICIT_SUBSTEPS).

Velocity level (SPRING_VELOCITY_LEVEL_SPEC, a design rule):
positions change ONLY by x += h v (plus a rare deep-penetration fix that never
feeds back into velocity). Nothing sets a velocity from a position difference;
predicted positions x + h v are read-only temporaries for the tests in the
impulse steps, never stored or corrected. The implicit solve only produces a
velocity change. tests/test_v19_velocity.py checks both.

Changes from the spec, measured (docs/specs/SPRING_VELOCITY_LEVEL_SPEC.md, notes):
- cloth layers already overlapping are eased apart over SELF_TAU, not one substep
  (one substep leaves them flying apart and they bounce on each other forever);
- the speed cap lets the body's outward push go first and trims the sliding part; the push
  itself is capped too (a limb moving into the cloth made one-substep pushes of overlap / h).

drape's cloth solver. It replaced XPBD (removed by design), and
nothing here is an XPBD code path: no Lagrange multipliers, no compliance-based
constraint projection. Shared code is in cloth.py (ClothSim): the per-frame setup (ClothSim._prepare:
weld, sewing, the self-collision candidates), the body's distance field, the speed cap, untangling.
The strain limit is on its own in _strain_impulses so it can be reviewed by itself.

Explicit stability: symplectic Euler is stable while h * omega_max < 2. omega_max^2
is bounded by Gershgorin: the largest row sum of M^-1 K (see SpringSimulator._omega).
Springs are never stiffened past the lock strain (that would void the bound):
the strain limit does that job.
"""
from __future__ import annotations

import numpy as np

from ._jit import njit
from .body import sdf, sdf_grad
from .meshbody import grid_sdf, grid_sdf_grad
from .cloth import ANCHOR_W, NSUB_CAP, UNFOLD_COMPLIANCE, ClothSim, _label_at, spring_k

SEAM_K = 2.0            # seams and topstitching: this times the stiffest spring at their vertex
SAFETY = 0.7            # h = SAFETY * 2 / omega_max
MAX_SUBSTEPS = 1500     # CPU; past it the cloth is softened instead (kscale < 1)
REF_SUBSTEPS = 40       # the count the per-substep damping constants were tuned at
LIMIT_ITERS = 2         # strain-limit passes per substep
DEEP_PEN = 0.002        # m: deeper in the body than this after a substep: the safety net puts it back
UNFOLD_K = 1.0 / UNFOLD_COMPLIANCE   # 100 N/m: the springs across folds while sewing
ELASTIC_K = 1000.0      # N/m per edge in an elastic casing (freeform._shrink_band): 25 mm knit
                        # elastic pulls ~3 N at 10%; the casing's ~3 rows of ~9 mm edges give that.
                        # With jersey's own springs (75 N/m across the grain) a skirt slid 7 cm.
IMPLICIT_SUBSTEPS = 40  # implicit: substeps per frame (more if the speed plan asks)
SELF_TAU = 0.005        # s: cloth layers already overlapping are eased apart over this
CG_MAX_ITER = 200
CG_TOL = 1e-4          # relative residual


@njit(cache=True)
def _spring_forces(x, F, springs, srest, sk, hinges, hK, hs, hk, av, abc, bary, arest, ak):
    """F = all spring, bending and topstitch forces at positions x."""
    F[:] = 0.0
    for e in range(springs.shape[0]):           # f_i = -k (L - r) d / L
        i, j = springs[e, 0], springs[e, 1]
        d0 = x[i, 0] - x[j, 0]; d1 = x[i, 1] - x[j, 1]; d2 = x[i, 2] - x[j, 2]
        L = np.sqrt(d0 * d0 + d1 * d1 + d2 * d2)
        if L < 1e-12:
            continue
        c = -sk[e] * (L - srest[e]) / L
        F[i, 0] += c * d0; F[i, 1] += c * d1; F[i, 2] += c * d2
        F[j, 0] -= c * d0; F[j, 1] -= c * d1; F[j, 2] -= c * d2
    for hh in range(hinges.shape[0]):           # energy 1/2 k_b s^2 |H|^2, H = sum K_q x_q
        H0 = 0.0; H1 = 0.0; H2 = 0.0
        for q in range(4):
            v = hinges[hh, q]
            H0 += hK[hh, q] * x[v, 0]; H1 += hK[hh, q] * x[v, 1]; H2 += hK[hh, q] * x[v, 2]
        c = -hk[hh] * hs[hh] * hs[hh]
        for q in range(4):
            v = hinges[hh, q]
            f = c * hK[hh, q]
            F[v, 0] += f * H0; F[v, 1] += f * H1; F[v, 2] += f * H2
    for a in range(av.shape[0]):                # topstitching: one-sided, only when pulled away
        p0 = 0.0; p1 = 0.0; p2 = 0.0
        for r in range(3):
            v = abc[a, r]
            p0 += bary[a, r] * x[v, 0]; p1 += bary[a, r] * x[v, 1]; p2 += bary[a, r] * x[v, 2]
        i = av[a]
        D0 = x[i, 0] - p0; D1 = x[i, 1] - p1; D2 = x[i, 2] - p2
        L = np.sqrt(D0 * D0 + D1 * D1 + D2 * D2)
        if L < 1e-12:
            continue
        C = L - arest[a]
        if C <= 0.0:
            continue
        c = ak[a] * C / L
        F[i, 0] -= c * D0; F[i, 1] -= c * D1; F[i, 2] -= c * D2
        for r in range(3):
            v = abc[a, r]
            F[v, 0] += c * bary[a, r] * D0; F[v, 1] += c * bary[a, r] * D1; F[v, 2] += c * bary[a, r] * D2


@njit(cache=True)
def _seam_forces_one_sided(x, F, seams, srest, sk, fi, fj):
    """Seams of a later stage while they sew: the same springs, but each end gets its
    own share of the force (fi, fj: 1 on the piece being sewn on, ANCHOR_W on the
    already-sewn side). This breaks Newton's third law on purpose, and only for
    unwelded seams of the stage being sewn: the garment already on the body barely
    moves, the attachment comes to it (as a person sews a hood onto a shirt)."""
    for e in range(seams.shape[0]):
        i, j = seams[e, 0], seams[e, 1]
        d0 = x[i, 0] - x[j, 0]; d1 = x[i, 1] - x[j, 1]; d2 = x[i, 2] - x[j, 2]
        L = np.sqrt(d0 * d0 + d1 * d1 + d2 * d2)
        if L < 1e-12:
            continue
        c = -sk[e] * (L - srest[e]) / L
        F[i, 0] += fi[e] * c * d0; F[i, 1] += fi[e] * c * d1; F[i, 2] += fi[e] * c * d2
        F[j, 0] -= fj[e] * c * d0; F[j, 1] -= fj[e] * c * d1; F[j, 2] -= fj[e] * c * d2


@njit(cache=True)
def _strain_impulses(x, v, w, edges, rest, lock, iters, h):
    """Provot's (1995) strain limit, applied as velocity impulses (Bridson, Fedkiw and
    Anderson 2002): an edge that would end the substep stretched past (1 + lock) times
    its rest length has the stretching part of its ends' relative velocity taken away,
    split by inverse mass. The predicted length is a read-only temporary; positions
    are never touched here. Only stretching velocity is removed (never more than the
    edge's own stretching speed), so this can't add energy. Kept on its own so it
    can be reviewed by itself (SPRING_VELOCITY_LEVEL_SPEC section 0)."""
    for _ in range(iters):
        for e in range(edges.shape[0]):
            i, j = edges[e, 0], edges[e, 1]
            ws = w[i] + w[j]
            if ws == 0.0:
                continue
            d0 = (x[i, 0] + h * v[i, 0]) - (x[j, 0] + h * v[j, 0])
            d1 = (x[i, 1] + h * v[i, 1]) - (x[j, 1] + h * v[j, 1])
            d2 = (x[i, 2] + h * v[i, 2]) - (x[j, 2] + h * v[j, 2])
            L = np.sqrt(d0 * d0 + d1 * d1 + d2 * d2)
            Lmax = (1.0 + lock[e]) * rest[e]
            if L <= Lmax or L < 1e-12:
                continue
            n0 = d0 / L; n1 = d1 / L; n2 = d2 / L
            u = (v[i, 0] - v[j, 0]) * n0 + (v[i, 1] - v[j, 1]) * n1 + (v[i, 2] - v[j, 2]) * n2
            if u <= 0.0:
                continue                         # already shortening: the springs pull it back
            dv = min((L - Lmax) / h, u)
            ci = w[i] / ws * dv; cj = w[j] / ws * dv
            v[i, 0] -= ci * n0; v[i, 1] -= ci * n1; v[i, 2] -= ci * n2
            v[j, 0] += cj * n0; v[j, 1] += cj * n1; v[j, 2] += cj * n2


@njit(cache=True)
def _posed_sd(px, py, pz, grid, origin, gh, lab, adj, Rg, Pg, Hg, J, jr):
    """Signed distance to the posed body and its outward normal (world), the same
    bone-frame lookup as solver._collide_posed. (d, nx, ny, nz); d = 1e9 if no bone."""
    G = Rg.shape[0]
    best = 1e9; bg = -1; bq0 = 0.0; bq1 = 0.0; bq2 = 0.0
    for g in range(G):
        dx = px - Pg[g, 0]; dy = py - Pg[g, 1]; dz = pz - Pg[g, 2]
        q0 = Rg[g, 0, 0] * dx + Rg[g, 1, 0] * dy + Rg[g, 2, 0] * dz + Hg[g, 0]
        q1 = Rg[g, 0, 1] * dx + Rg[g, 1, 1] * dy + Rg[g, 2, 1] * dz + Hg[g, 1]
        q2 = Rg[g, 0, 2] * dx + Rg[g, 1, 2] * dy + Rg[g, 2, 2] * dz + Hg[g, 2]
        lb = _label_at(q0, q1, q2, lab, origin, gh)
        if not adj[g, lb]:
            continue
        if lb != g:
            ex = q0 - J[g, lb, 0]; ey = q1 - J[g, lb, 1]; ez = q2 - J[g, lb, 2]
            if ex * ex + ey * ey + ez * ez > jr * jr:
                continue
        d = grid_sdf(q0, q1, q2, grid, origin, gh)
        if d < best:
            best = d; bg = g; bq0 = q0; bq1 = q1; bq2 = q2
    if bg < 0:
        return 1e9, 0.0, 0.0, 0.0
    gx, gy, gz = grid_sdf_grad(bq0, bq1, bq2, grid, origin, gh)
    nx = Rg[bg, 0, 0] * gx + Rg[bg, 0, 1] * gy + Rg[bg, 0, 2] * gz
    ny = Rg[bg, 1, 0] * gx + Rg[bg, 1, 1] * gy + Rg[bg, 1, 2] * gz
    nz = Rg[bg, 2, 0] * gx + Rg[bg, 2, 1] * gy + Rg[bg, 2, 2] * gz
    return best, nx, ny, nz


@njit(cache=True)
def _body_sd(px, py, pz, posed, torso, caps, k, extras, groups, use_grid, grid, gorigin, gh,
             lab, adj, Rg, Pg, Hg, J, jr):
    if posed:
        return _posed_sd(px, py, pz, grid, gorigin, gh, lab, adj, Rg, Pg, Hg, J, jr)
    if use_grid:
        d = grid_sdf(px, py, pz, grid, gorigin, gh)
        nx, ny, nz = grid_sdf_grad(px, py, pz, grid, gorigin, gh)
    else:
        d = sdf(px, py, pz, torso, caps, k, extras, groups)
        nx, ny, nz = sdf_grad(px, py, pz, torso, caps, k, extras, groups)
    return d, nx, ny, nz


@njit(cache=True)
def _body_impulses(x, v, w, h, thick, mu, posed, torso, caps, k, extras, groups, use_grid, grid, gorigin, gh,
                   lab, adj, Rg, Pg, Hg, J, jr, bnorm, bflag):
    """Body contact and Coulomb friction as velocity impulses (Bridson et al. 2002):
    a point that would end the substep closer than `thick` to the skin gets just the
    outward speed to end it at `thick`, and its sliding speed cut by mu times that.
    The body is where it will be at the end of the substep, so a limb moving into the
    cloth pushes harder. p* = x + h v is a read-only temporary. bnorm/bflag: the
    normal of each point pushed, for the speed cap (step 6 lets the outward push go first)."""
    for i in range(x.shape[0]):
        if w[i] == 0.0:
            continue
        px = x[i, 0] + h * v[i, 0]; py = x[i, 1] + h * v[i, 1]; pz = x[i, 2] + h * v[i, 2]
        d, nx, ny, nz = _body_sd(px, py, pz, posed, torso, caps, k, extras, groups, use_grid, grid, gorigin, gh,
                                 lab, adj, Rg, Pg, Hg, J, jr)
        if d >= thick:
            continue
        dvn = (thick - d) / h
        v[i, 0] += dvn * nx; v[i, 1] += dvn * ny; v[i, 2] += dvn * nz
        bnorm[i, 0] = nx; bnorm[i, 1] = ny; bnorm[i, 2] = nz; bflag[i] = 1
        vn = v[i, 0] * nx + v[i, 1] * ny + v[i, 2] * nz
        tx = v[i, 0] - vn * nx; ty = v[i, 1] - vn * ny; tz = v[i, 2] - vn * nz
        tl = np.sqrt(tx * tx + ty * ty + tz * tz)
        if tl < 1e-12:
            continue
        f = max(0.0, tl - mu * dvn) / tl
        v[i, 0] = vn * nx + f * tx; v[i, 1] = vn * ny + f * ty; v[i, 2] = vn * nz + f * tz


@njit(cache=True)
def _sphere_impulses(x, v, w, h, pi, pj, r):
    """The sphere experiment: a sphere of radius r at each point, between different garments only. Two points that
    would end the substep closer than 2r (predicted x + h v, read-only) lose the approaching part of their relative
    velocity, split by inverse mass. Spheres have no inside or outside, so they can't lock in a wrong side, but
    they leave holes between points smaller than about 0.6 of the mesh spacing. Positions are never touched."""
    d2 = 2.0 * r
    for q in range(pi.shape[0]):
        i, j = pi[q], pj[q]
        ws = w[i] + w[j]
        if ws == 0.0:
            continue
        p0 = (x[i, 0] + h * v[i, 0]) - (x[j, 0] + h * v[j, 0])
        p1 = (x[i, 1] + h * v[i, 1]) - (x[j, 1] + h * v[j, 1])
        p2 = (x[i, 2] + h * v[i, 2]) - (x[j, 2] + h * v[j, 2])
        L = np.sqrt(p0 * p0 + p1 * p1 + p2 * p2)
        if L >= d2 or L < 1e-12:
            continue
        n0 = p0 / L; n1 = p1 / L; n2 = p2 / L
        u = (v[i, 0] - v[j, 0]) * n0 + (v[i, 1] - v[j, 1]) * n1 + (v[i, 2] - v[j, 2]) * n2
        if u >= 0.0:
            continue                             # already moving apart
        ci = w[i] / ws * u; cj = w[j] / ws * u
        v[i, 0] -= ci * n0; v[i, 1] -= ci * n1; v[i, 2] -= ci * n2
        v[j, 0] += cj * n0; v[j, 1] += cj * n1; v[j, 2] += cj * n2


@njit(cache=True)
def _self_impulses(x, v, x0, w, h, tris, cand_v, cand_t, thick, tau, touched):
    """Cloth-on-cloth repulsion impulses (Bridson et al. 2002) on the candidate
    (point, triangle) pairs, tested at the predicted positions (read-only), so a fast
    point is stopped before it crosses. The side a point must stay on comes from the
    frame-start positions x0. Each push is capped at half the thickness per substep
    (in squeezed spots, armpits, the full one overshoots and layers ping-pong).
    A pair approaching gets just the speed to end at `thick`; a pair already closer
    than `thick` is eased apart over `tau` seconds instead of one substep (pushing it
    out in one substep leaves it flying apart at overlap / h, and layers bounce on
    each other forever: the tee never settled)."""
    n_hits = 0
    for q in range(cand_v.shape[0]):
        p, t = cand_v[q], cand_t[q]
        if w[p] == 0.0:
            continue
        a, b, c = tris[t, 0], tris[t, 1], tris[t, 2]
        px = x[p, 0] + h * v[p, 0]; py = x[p, 1] + h * v[p, 1]; pz = x[p, 2] + h * v[p, 2]
        ax = x[a, 0] + h * v[a, 0]; ay = x[a, 1] + h * v[a, 1]; az = x[a, 2] + h * v[a, 2]
        bx = x[b, 0] + h * v[b, 0]; by = x[b, 1] + h * v[b, 1]; bz = x[b, 2] + h * v[b, 2]
        cx = x[c, 0] + h * v[c, 0]; cy = x[c, 1] + h * v[c, 1]; cz = x[c, 2] + h * v[c, 2]
        e1x = bx - ax; e1y = by - ay; e1z = bz - az
        e2x = cx - ax; e2y = cy - ay; e2z = cz - az
        nx = e1y * e2z - e1z * e2y; ny = e1z * e2x - e1x * e2z; nz = e1x * e2y - e1y * e2x
        nl = np.sqrt(nx * nx + ny * ny + nz * nz)
        if nl < 1e-14:
            continue
        nx /= nl; ny /= nl; nz /= nl
        apx = px - ax; apy = py - ay; apz = pz - az
        dist = apx * nx + apy * ny + apz * nz
        if abs(dist) >= thick:
            continue
        d00 = e1x * e1x + e1y * e1y + e1z * e1z
        d01 = e1x * e2x + e1y * e2y + e1z * e2z
        d11 = e2x * e2x + e2y * e2y + e2z * e2z
        d20 = apx * e1x + apy * e1y + apz * e1z
        d21 = apx * e2x + apy * e2y + apz * e2z
        den = d00 * d11 - d01 * d01
        if den < 1e-20:
            continue
        bv = (d11 * d20 - d01 * d21) / den
        bw = (d00 * d21 - d01 * d20) / den
        bu = 1.0 - bv - bw
        if bu < -0.02 or bv < -0.02 or bw < -0.02:
            continue
        f1x = x0[b, 0] - x0[a, 0]; f1y = x0[b, 1] - x0[a, 1]; f1z = x0[b, 2] - x0[a, 2]
        f2x = x0[c, 0] - x0[a, 0]; f2y = x0[c, 1] - x0[a, 1]; f2z = x0[c, 2] - x0[a, 2]
        mx = f1y * f2z - f1z * f2y; my = f1z * f2x - f1x * f2z; mz = f1x * f2y - f1y * f2x
        s0 = (x0[p, 0] - x0[a, 0]) * mx + (x0[p, 1] - x0[a, 1]) * my + (x0[p, 2] - x0[a, 2]) * mz
        side = 1.0 if s0 > 0.0 else -1.0
        if s0 == 0.0:
            side = 1.0 if dist >= 0.0 else -1.0
        gap = side * dist
        if gap >= thick:
            continue
        denom = w[p] + bu * bu * w[a] + bv * bv * w[b] + bw * bw * w[c]
        if denom == 0.0:
            continue
        need = (thick - gap) / h             # approaching: just enough to end at thick
        vrel = side * ((v[p, 0] - bu * v[a, 0] - bv * v[b, 0] - bw * v[c, 0]) * nx
                       + (v[p, 1] - bu * v[a, 1] - bv * v[b, 1] - bw * v[c, 1]) * ny
                       + (v[p, 2] - bu * v[a, 2] - bv * v[b, 2] - bw * v[c, 2]) * nz)
        gap_now = gap - h * vrel             # the gap now, along n
        if gap_now < thick:                  # already overlapping: ease apart over tau
            need = (thick - gap_now) / tau - vrel
            if need <= 0.0:
                continue
        s = min(need, 0.5 * thick / h) / denom * side
        touched[p] = 1; touched[a] = 1; touched[b] = 1; touched[c] = 1
        v[p, 0] += w[p] * s * nx; v[p, 1] += w[p] * s * ny; v[p, 2] += w[p] * s * nz
        v[a, 0] -= w[a] * s * bu * nx; v[a, 1] -= w[a] * s * bu * ny; v[a, 2] -= w[a] * s * bu * nz
        v[b, 0] -= w[b] * s * bv * nx; v[b, 1] -= w[b] * s * bv * ny; v[b, 2] -= w[b] * s * bv * nz
        v[c, 0] -= w[c] * s * bw * nx; v[c, 1] -= w[c] * s * bw * ny; v[c, 2] -= w[c] * s * bw * nz
        n_hits += 1
    return n_hits


@njit(cache=True)
def _kinetic(v, w):
    e = 0.0
    for i in range(v.shape[0]):
        if w[i] > 0.0:
            e += 0.5 / w[i] * (v[i, 0] * v[i, 0] + v[i, 1] * v[i, 1] + v[i, 2] * v[i, 2])
    return e


@njit(cache=True)
def _spring_substeps(x, v, w, sub_lo, sub_hi, nsub, h, g, damp, kscale,
                     springs, srest, sk, ledges, lrest, llock, limit_iters,
                     hinges, hK, hs, hk, av, abc, bary, arest, ak,
                     torso, caps, k, extras, groups, thick, mu, use_grid, grid, gorigin, gh,
                     do_self, self_every, tris, x0, cand_v, cand_t, sthick, contact_damp, tau,
                     posed, lab, adj, Rg0, Pg0, Rg1, Pg1, Hg, J, jr, vmax,
                     oseams, osrest, osk, ofi, ofj, deep, pushed, dbg,
                     implicit, cg_max, cg_tol, ws_nd, ws_fac, ws_dv, ws_r, ws_p, ws_Ap, ws_z, ws_diag, ws_bn, ws_bf,
                     sp_i, sp_j, sp_r):
    """Substeps sub_lo .. sub_hi - 1 of nsub. Everything but step 7 works on velocities;
    positions change only by x += h v (and the rare deep-penetration fix, step 8, which
    never sets a velocity from the move). pushed[i] = 1 for points step 8 moved in the
    last substep run. dbg[0] (if dbg has 2 entries): the largest kinetic-energy gain of
    the strain step (J), a check that it never adds energy. -> (self hits, step-8 count)."""
    n = x.shape[0]
    F = np.zeros_like(x)
    touched = np.zeros(n, np.int8)
    hits = 0
    pushes = 0
    cg_iters = 0
    check = dbg.shape[0] >= 2
    Rg = Rg1; Pg = Pg1
    for sub in range(sub_lo, sub_hi):
        if posed:               # the body where it is at the end of this substep
            u = (sub + 1.0) / nsub
            Rg = Rg0 * (1.0 - u) + Rg1 * u
            Pg = Pg0 * (1.0 - u) + Pg1 * u
        # 1-2. forces (they read x only) and gravity -> velocities
        _spring_forces(x, F, springs, srest, sk, hinges, hK, hs, hk, av, abc, bary, arest, ak)
        if oseams.shape[0] > 0:
            _seam_forces_one_sided(x, F, oseams, osrest, osk, ofi, ofj)
        if implicit:            # backward Euler for springs and bending (topstitch, one-sided seams explicit)
            cg_iters += _implicit_dv(x, v, w, h, g, F, springs, srest, sk, hinges, hK, hs, hk,
                                     ws_nd, ws_fac, ws_dv, ws_r, ws_p, ws_Ap, ws_z, ws_diag, cg_max, cg_tol)
            for i in range(n):
                if w[i] > 0.0:
                    v[i, 0] += ws_dv[i, 0]; v[i, 1] += ws_dv[i, 1]; v[i, 2] += ws_dv[i, 2]
        else:
            for i in range(n):
                if w[i] > 0.0:
                    s = h * w[i] * kscale
                    v[i, 0] += s * F[i, 0]; v[i, 1] += s * F[i, 1] + g * h; v[i, 2] += s * F[i, 2]
        # 3. strain limit (velocity impulses)
        if check:
            e0 = _kinetic(v, w)
        _strain_impulses(x, v, w, ledges, lrest, llock, limit_iters, h)
        if check:
            dbg[0] = max(dbg[0], _kinetic(v, w) - e0)
        # 4. the body, 5. cloth on cloth
        _body_impulses(x, v, w, h, thick, mu, posed, torso, caps, k, extras, groups, use_grid, grid, gorigin, gh,
                       lab, adj, Rg, Pg, Hg, J, jr, ws_bn, ws_bf)
        if sp_i.shape[0] > 0:   # the sphere experiment (off: no pairs)
            _sphere_impulses(x, v, w, h, sp_i, sp_j, sp_r)
        if do_self and (sub % self_every == self_every - 1):
            hits += _self_impulses(x, v, x0, w, h, tris, cand_v, cand_t, sthick, tau, touched)
            if posed:
                # a moving body: the skin once more (thickness 0, it only stops points going
                # in), so a cloth push can't press a layer into a limb moving into it (sitting:
                # 3 trouser points inside -> 2). Not for a still body: a sheet on a ball was
                # pushed through the one over it, and the gloves ended with 1-3 points inside.
                _body_impulses(x, v, w, h, 0.0, mu, posed, torso, caps, k, extras, groups, use_grid, grid, gorigin, gh,
                               lab, adj, Rg, Pg, Hg, J, jr, ws_bn, ws_bf)
        # 6. damping, contact damping, speed cap
        for i in range(n):
            dmp = damp + contact_damp * touched[i]
            touched[i] = 0
            v[i, 0] *= 1.0 - dmp; v[i, 1] *= 1.0 - dmp; v[i, 2] *= 1.0 - dmp
            sp = np.sqrt(v[i, 0] * v[i, 0] + v[i, 1] * v[i, 1] + v[i, 2] * v[i, 2])
            if ws_bf[i] == 1:
                # the body pushed it this substep: the outward push goes first (up to vmax),
                # the sliding part gets what's left (scaling the whole velocity left points
                # deep in the body). The push is capped too: a limb moving into the cloth
                # (sitting) made pushes of overlap / h, up to 600 m/s, for one substep.
                ws_bf[i] = 0
                vn = v[i, 0] * ws_bn[i, 0] + v[i, 1] * ws_bn[i, 1] + v[i, 2] * ws_bn[i, 2]
                if vn > 0.0 and sp > vmax:
                    tx = v[i, 0] - vn * ws_bn[i, 0]; ty = v[i, 1] - vn * ws_bn[i, 1]; tz = v[i, 2] - vn * ws_bn[i, 2]
                    tl = np.sqrt(tx * tx + ty * ty + tz * tz)
                    vn = min(vn, vmax)
                    room = np.sqrt(max(vmax * vmax - vn * vn, 0.0))
                    f = room / tl if tl > room else 1.0
                    v[i, 0] = vn * ws_bn[i, 0] + f * tx; v[i, 1] = vn * ws_bn[i, 1] + f * ty; v[i, 2] = vn * ws_bn[i, 2] + f * tz
                    continue
            if sp > vmax:
                f = vmax / sp
                v[i, 0] *= f; v[i, 1] *= f; v[i, 2] *= f
        # 7. advance: the only position update
        for i in range(n):
            x[i, 0] += v[i, 0] * h; x[i, 1] += v[i, 1] * h; x[i, 2] += v[i, 2] * h
        # 8. safety net: a point deep in the body (grid error, a bone popping through)
        # is put back on the surface; only its inward speed is dropped
        for i in range(n):
            pushed[i] = 0
            if w[i] == 0.0:
                continue
            d, nx, ny, nz = _body_sd(x[i, 0], x[i, 1], x[i, 2], posed, torso, caps, k, extras, groups,
                                     use_grid, grid, gorigin, gh, lab, adj, Rg, Pg, Hg, J, jr)
            if d >= -deep:
                continue
            x[i, 0] += (thick - d) * nx; x[i, 1] += (thick - d) * ny; x[i, 2] += (thick - d) * nz
            vn = v[i, 0] * nx + v[i, 1] * ny + v[i, 2] * nz
            if vn < 0.0:
                v[i, 0] -= vn * nx; v[i, 1] -= vn * ny; v[i, 2] -= vn * nz
            pushed[i] = 1
            pushes += 1
    return hits, pushes, cg_iters


# ------------------------------------------------------- implicit springs --
# Backward Euler, linearised once per substep (Baraff and Witkin 1998):
#   (M + h^2 K) dv = h (F(x) + M g - h K v)
# K = -dF/dx with the compressed-spring term dropped so it stays positive
# semi-definite. Solved by Jacobi-preconditioned conjugate gradients, matrix-free.
# Only velocities come out of it; positions still change only by x += h v.
@njit(cache=True)
def _spring_frames(x, springs, srest, nd, fac):
    """Per spring: unit direction nd and the transverse factor max(0, 1 - r / L)."""
    for e in range(springs.shape[0]):
        i, j = springs[e, 0], springs[e, 1]
        d0 = x[i, 0] - x[j, 0]; d1 = x[i, 1] - x[j, 1]; d2 = x[i, 2] - x[j, 2]
        L = np.sqrt(d0 * d0 + d1 * d1 + d2 * d2)
        if L < 1e-12:
            nd[e, 0] = 0.0; nd[e, 1] = 0.0; nd[e, 2] = 0.0; fac[e] = 0.0
            continue
        nd[e, 0] = d0 / L; nd[e, 1] = d1 / L; nd[e, 2] = d2 / L
        fac[e] = max(0.0, 1.0 - srest[e] / L)


@njit(cache=True)
def _apply_K(u, out, springs, sk, nd, fac, hinges, hK, hs, hk):
    """out = K u (K = -dF/dx, positive semi-definite)."""
    out[:] = 0.0
    for e in range(springs.shape[0]):
        i, j = springs[e, 0], springs[e, 1]
        k = sk[e]
        a0 = u[i, 0] - u[j, 0]; a1 = u[i, 1] - u[j, 1]; a2 = u[i, 2] - u[j, 2]
        n0 = nd[e, 0]; n1 = nd[e, 1]; n2 = nd[e, 2]
        dn = a0 * n0 + a1 * n1 + a2 * n2
        f = fac[e]
        # k [n n^T + f (I - n n^T)] a = k [(1 - f) (n.a) n + f a]
        c = k * (1.0 - f) * dn
        r0 = c * n0 + k * f * a0; r1 = c * n1 + k * f * a1; r2 = c * n2 + k * f * a2
        out[i, 0] += r0; out[i, 1] += r1; out[i, 2] += r2
        out[j, 0] -= r0; out[j, 1] -= r1; out[j, 2] -= r2
    for hh in range(hinges.shape[0]):           # bending is linear in x: K = k_b s^2 K_v K_r I
        H0 = 0.0; H1 = 0.0; H2 = 0.0
        for q in range(4):
            v = hinges[hh, q]
            H0 += hK[hh, q] * u[v, 0]; H1 += hK[hh, q] * u[v, 1]; H2 += hK[hh, q] * u[v, 2]
        c = hk[hh] * hs[hh] * hs[hh]
        for q in range(4):
            v = hinges[hh, q]
            f = c * hK[hh, q]
            out[v, 0] += f * H0; out[v, 1] += f * H1; out[v, 2] += f * H2


@njit(cache=True)
def _implicit_dv(x, v, w, h, g, F, springs, srest, sk, hinges, hK, hs, hk,
                 nd, fac, dv, r, p, Ap, z, diag, max_iter, tol):
    """Solve (M + h^2 K) dv = h (F + M g - h K v) for dv (pinned points: dv = 0).
    F holds the forces at x. Returns the CG iterations used."""
    n = x.shape[0]
    _spring_frames(x, springs, srest, nd, fac)
    # Jacobi preconditioner: m + h^2 (diagonal of K, averaged over the 3 axes)
    for i in range(n):
        diag[i] = 0.0
    for e in range(springs.shape[0]):
        k = sk[e] * (1.0 + 2.0 * fac[e]) / 3.0
        diag[springs[e, 0]] += k; diag[springs[e, 1]] += k
    for hh in range(hinges.shape[0]):
        c = hk[hh] * hs[hh] * hs[hh]
        for q in range(4):
            diag[hinges[hh, q]] += c * hK[hh, q] * hK[hh, q]
    for i in range(n):
        diag[i] = (1.0 / w[i] + h * h * diag[i]) if w[i] > 0.0 else 1.0
    # right-hand side b = h (F + M g - h K v); r = b - A dv0 with dv0 = 0
    _apply_K(v, Ap, springs, sk, nd, fac, hinges, hK, hs, hk)
    bn = 0.0
    for i in range(n):
        dv[i, 0] = 0.0; dv[i, 1] = 0.0; dv[i, 2] = 0.0
        if w[i] > 0.0:
            m = 1.0 / w[i]
            r[i, 0] = h * (F[i, 0] - h * Ap[i, 0])
            r[i, 1] = h * (F[i, 1] + m * g - h * Ap[i, 1])
            r[i, 2] = h * (F[i, 2] - h * Ap[i, 2])
        else:
            r[i, 0] = 0.0; r[i, 1] = 0.0; r[i, 2] = 0.0
        bn += r[i, 0] * r[i, 0] + r[i, 1] * r[i, 1] + r[i, 2] * r[i, 2]
    if bn == 0.0:
        return 0
    rz = 0.0
    for i in range(n):
        for c in range(3):
            z[i, c] = r[i, c] / diag[i]
            p[i, c] = z[i, c]
            rz += r[i, c] * z[i, c]
    it = 0
    while it < max_iter:
        it += 1
        _apply_K(p, Ap, springs, sk, nd, fac, hinges, hK, hs, hk)
        pAp = 0.0
        for i in range(n):
            if w[i] > 0.0:
                m = 1.0 / w[i]
                for c in range(3):
                    Ap[i, c] = m * p[i, c] + h * h * Ap[i, c]
                    pAp += p[i, c] * Ap[i, c]
            else:
                Ap[i, 0] = 0.0; Ap[i, 1] = 0.0; Ap[i, 2] = 0.0
        if pAp <= 0.0:
            break
        a = rz / pAp
        rn = 0.0
        rz2 = 0.0
        for i in range(n):
            for c in range(3):
                dv[i, c] += a * p[i, c]
                r[i, c] -= a * Ap[i, c]
                rn += r[i, c] * r[i, c]
                z[i, c] = r[i, c] / diag[i]
                rz2 += r[i, c] * z[i, c]
        if rn <= tol * tol * bn:
            break
        beta = rz2 / rz
        rz = rz2
        for i in range(n):
            if w[i] > 0.0:
                for c in range(3):
                    p[i, c] = z[i, c] + beta * p[i, c]
            else:
                p[i, 0] = 0.0; p[i, 1] = 0.0; p[i, 2] = 0.0
    return it


def gershgorin_omega(w, S, sk, hinges=None, hK=None, hs=None, bc=None, av=None, abc=None, bary=None, ak=None):
    """Upper bound on the highest frequency (rad/s) of the spring system: the largest
    row sum of M^-1 K by Gershgorin. Springs give 2k per end (diagonal k plus the
    off-diagonal k), a hinge k_b s^2 |K_q| sum|K_r|, a topstitch k_a |u_q| sum|u|.
    Returns (omega, the vertex that sets it)."""
    n = len(w)
    row = np.zeros(n)
    np.add.at(row, S[:, 0], 2 * sk)
    np.add.at(row, S[:, 1], 2 * sk)
    if hinges is not None and len(hinges):
        kb = hs ** 2 / bc
        Ka = np.abs(hK)
        tot = Ka.sum(1)
        for q in range(4):
            np.add.at(row, hinges[:, q], kb * Ka[:, q] * tot)
    if av is not None and len(av):
        b = np.abs(bary)
        tot = 1.0 + b.sum(1)
        np.add.at(row, av, ak * tot)
        for r in range(3):
            np.add.at(row, abc[:, r], ak * b[:, r] * tot)
    rw = row * w
    if not len(rw):
        return 0.0, -1
    return float(np.sqrt(rw.max())), int(np.argmax(rw))


def plan_stable(omega, fps, max_substeps=MAX_SUBSTEPS, safety=SAFETY):
    """Substeps that keep h * omega below 2 * safety. Past max_substeps the springs
    are softened by kscale instead (omega ~ sqrt(k): it lands exactly on the cap).
    Returns (nsub, kscale)."""
    need = omega / fps / (2.0 * safety)
    if need > max_substeps:
        return int(max_substeps), (max_substeps / need) ** 2
    return int(min(max(np.ceil(need - 1e-9), 1), max_substeps)), 1.0


class SpringSimulator(ClothSim):
    """The mass-spring solver (drape.Simulator)."""
    solver = "springs"

    def __init__(self, garment, body, fabric=None, max_substeps=MAX_SUBSTEPS, implicit=True,
                 k_mult=1.0, **kw):
        super().__init__(garment, body, fabric, **kw)
        pf = (self.g0.meta or {}).get("panel_fabrics")
        if pf:
            fabs = [f or self.fabric for f in pf]
            self._vk = np.array([spring_k(f) for f in fabs])[self.g0.panel_id]
        else:
            self._vk = np.full(len(self.x), spring_k(self.fabric))
        self.implicit = bool(implicit)  # backward Euler (default); False: explicit, stability-limited
        self.k_mult = float(k_mult)
        self._vk = self._vk * self.k_mult
        self.implicit_substeps = IMPLICIT_SUBSTEPS
        self.cg_iters = 0
        self.max_substeps = max_substeps
        self._omega_cache = {}
        self.omega = 0.0
        self.kscale = 1.0
        self.nsub_stable = 1
        self.safety_pushes = 0          # deep-penetration fixes in the last frame (should be 0)
        self.safety_total = 0
        self._pushed = np.zeros(len(self.x), np.int8)
        self.self_tau = SELF_TAU
        self.debug_check = False        # tests: run substeps one by one and check x += h v
        self.debug_residual = 0.0
        self.debug_ke_gain = 0.0

    # ------------------------------------------------------------ stiffness --
    def _edge_k(self):
        e = self.g.edges
        k = 0.5 * (self._vk[e[:, 0]] + self._vk[e[:, 1]]) / self._aniso()
        # an elastic casing pulls with the elastic in it, not the fabric round it
        return np.where(self._elastic_e, np.maximum(k, ELASTIC_K * self.k_mult), k)

    def _springs(self, P):
        """All springs this frame: (pairs, rest, k, topstitch k, one-sided seams). Mesh
        edges (eased rest), seams before the weld (rest shrinking to 0), unfold springs
        while sewing. A later stage's seams while it sews go in the one-sided set
        (seams, rest, k, share at a, share at b), see _seam_forces_one_sided."""
        E, ke = self.g.edges, self._edge_k()
        kv = np.zeros(len(self.x))
        np.maximum.at(kv, E[:, 0], ke)
        np.maximum.at(kv, E[:, 1], ke)
        pairs, rest, k = [E], [P["erest"]], [ke]
        seams = P.get("seams", self.g.seams)
        one = (np.zeros((0, 2), np.int64), np.zeros(0), np.zeros(0), np.zeros(0), np.zeros(0))
        if not self.welded and len(seams):
            sk = SEAM_K * np.maximum(kv[seams[:, 0]], kv[seams[:, 1]])
            if self.cur_stage > 1 and P["sewing"]:
                vs = self._vstage
                fi = np.where(vs[seams[:, 0]] < self.cur_stage, ANCHOR_W, 1.0)
                fj = np.where(vs[seams[:, 1]] < self.cur_stage, ANCHOR_W, 1.0)
                one = (np.ascontiguousarray(seams, np.int64), P["srest"], sk, fi, fj)
            else:
                pairs.append(seams); rest.append(P["srest"]); k.append(sk)
        if P["unfold"]:
            B = P.get("bends", self.g.bends)
            pairs.append(B); rest.append(P.get("bend_rest", self.g.bend_rest)); k.append(np.full(len(B), UNFOLD_K))
        av = P.get("att", self._att)[0]
        ak = SEAM_K * kv[av] if len(av) else np.zeros(0)
        return (np.ascontiguousarray(np.vstack(pairs), np.int64), np.concatenate(rest), np.concatenate(k), ak, one)

    def _omega(self, P, springs=None):
        """Gershgorin bound on the highest frequency, cached until its inputs change
        (at the weld, and when sewing ends and the unfold springs drop out)."""
        key = (self.weld_stage, self.cur_stage, P["sewing"], P["unfold"]) if self.n_stages > 1 \
            else (self.welded, P["unfold"])
        if key in self._omega_cache:
            return self._omega_cache[key]
        S, _, sk, ak, one = springs if springs is not None else self._springs(P)
        if len(one[0]):   # the one-sided seams: bounded as ordinary (full-strength) springs
            S, sk = np.vstack([S, one[0]]), np.concatenate([sk, one[2]])
        bc = self._compliances()[1] if len(self._hinges) else np.zeros(0)
        av, abc, bary = P.get("att", self._att)
        om, self.worst_vertex = gershgorin_omega(self.w, S, sk, self._hinges, self._hK, self._hs, bc,
                                                 av, abc, bary, ak)
        self._omega_cache[key] = om
        return om

    # ----------------------------------------------------------- weld ----
    def weld(self, mask=None):
        super().weld(mask)
        new_id = self._last_new_id
        m = len(self.x)
        self._vk = np.bincount(new_id, weights=self._vk, minlength=m) / np.bincount(new_id, minlength=m)
        self._omega_cache.clear()

    # ----------------------------------------------------------- step ----
    def step(self):
        P = self._prepare()
        springs = self._springs(P)
        if self.implicit:       # no stability limit on the step: a fixed base count
            self.nsub_stable, self.kscale = self.implicit_substeps, 1.0
        else:
            self.omega = self._omega(P, springs)
            self.nsub_stable, self.kscale = plan_stable(self.omega, self.fps, self.max_substeps)
        # and enough that fast cloth can't tunnel (never fewer than the stable count)
        nsub, se, vlim = self._plan_speed(self.nsub_stable, P["do_self"], cap=max(NSUB_CAP, self.nsub_stable))
        h = self.h = 1.0 / (self.fps * nsub)
        # per-substep constants tuned at REF_SUBSTEPS: the same per-frame effect at any count
        damp = 1.0 - (1.0 - self.fabric.damping) ** (1.0 / nsub)
        if P["sewing"]:
            damp = max(damp, 1.0 - 0.99 ** (REF_SUBSTEPS / nsub))
        cdamp = 1.0 - (1.0 - self.contact_damp) ** (REF_SUBSTEPS / nsub)
        S, srest, sk, ak, one = springs
        att = P.get("att", self._att)
        _, bc = self._compliances()
        hk = 1.0 / bc if len(bc) else np.zeros(0)
        if len(self._pushed) != len(self.x):
            self._pushed = np.zeros(len(self.x), np.int8)
        dbg = np.zeros(2 if self.debug_check else 0)
        n, ns = len(self.x), len(S)
        ws = (np.zeros((ns, 3)), np.zeros(ns), np.zeros((n, 3)), np.zeros((n, 3)), np.zeros((n, 3)),
              np.zeros((n, 3)), np.zeros((n, 3)), np.zeros(n))

        sp = self._sphere_pairs()

        def run(lo, hi):
            return _spring_substeps(
                self.x, self.v, self.w, lo, hi, nsub, h, -9.81 * P["gscale"], damp, self.kscale,
                S, srest, sk, self.g.edges, P["erest"], self._edge_lock(), LIMIT_ITERS,
                self._hinges, self._hK, self._hs, hk,
                att[0], att[1], att[2], P["arest"], ak,
                *self._body_args,
                self.fabric.thickness, self.fabric.friction, *self._grid_args(),
                P["do_self"], se, self.g.tris, P["x0"], P["cand_v"], P["cand_t"],
                self.fabric.self_thickness, cdamp, self.self_tau,
                *self._posed_args(), vlim, *one, DEEP_PEN, self._pushed, dbg,
                self.implicit, CG_MAX_ITER, CG_TOL, *ws, np.zeros((n, 3)), np.zeros(n, np.int8), *sp)
        if not self.debug_check:
            self.self_hits, self.safety_pushes, self.cg_iters = run(0, nsub)
        else:   # one substep at a time, checking from outside that x moved by exactly h v
            self.self_hits = self.safety_pushes = self.cg_iters = 0
            for sub in range(nsub):
                x_old = self.x.copy()
                a, b, c = run(sub, sub + 1)
                self.self_hits += a; self.safety_pushes += b; self.cg_iters += c
                ok = self._pushed == 0
                r = np.abs(self.x[ok] - (x_old[ok] + self.v[ok] * h)).max(initial=0.0)
                self.debug_residual = max(self.debug_residual, float(r))
            self.debug_ke_gain = max(self.debug_ke_gain, float(dbg[0]))
        self.safety_total += self.safety_pushes
        self.time += 1.0 / self.fps
        if self.untangle:
            self._untangle_step()

    def _sphere_pairs(self):
        """This frame's point pairs for the sphere experiment: different garments, not frozen, within reach."""
        r = float(getattr(self, "sphere_r", 0.0) or 0.0)
        none = (np.zeros(0, np.int64), np.zeros(0, np.int64), 0.0)
        if r <= 0 or not hasattr(self, "_vgar") or len(np.unique(self._vgar)) < 2:
            return none
        from scipy.spatial import cKDTree
        P = np.asarray(cKDTree(self.x).query_pairs(2 * r + 0.015, output_type="ndarray"), np.int64).reshape(-1, 2)
        keep = (self._vgar[P[:, 0]] != self._vgar[P[:, 1]]) & ((self.w[P[:, 0]] > 0) | (self.w[P[:, 1]] > 0))
        P = P[keep]
        return np.ascontiguousarray(P[:, 0]), np.ascontiguousarray(P[:, 1]), r

    def metrics(self) -> dict:
        m = super().metrics()
        m.update(solver="springs", omega=float(self.omega), substeps_stable=int(self.nsub_stable),
                 stiffness_scale=float(self.kscale), safety_pushes=int(self.safety_pushes),
                 safety_pushes_total=int(self.safety_total), implicit=bool(self.implicit),
                 cg_iters_frame=int(self.cg_iters))
        return m
