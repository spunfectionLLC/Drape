"""Frozen garments as colliders (multi-garment spec, phase 4: freeze-and-collide).

A frozen garment stops moving and the next garment drapes over it. The new cloth collides with it the
way it collides with the avatar: through the body's signed distance grid. The garment's surface goes into
that grid (the nearer of the two at each grid point), offset by a collision thickness (1.5 mm by
default) so the outer cloth rests just over it instead of in it. Nothing else changes: the CPU solver,
the GPU (live_springs.js) and the website all read body.grid / origin / h.

Design-around rules (docs/specs/MULTI_GARMENT_SPEC.md):
- Layering is by simulation: the new cloth is pushed by the contact impulses, the frozen garment's mesh
  is never moved, inflated or offset to make room, and the new garment is placed where it always was
  (its placement sees the plain body).
- Which garment is inside which is the user's layer order: this only receives the garments the page
  says are frozen; it never sorts them.

The garment's surface is open, so its "inside" is the body's side: each triangle's normal is turned to
point the way the body's distance grows. A point counts as inside only near the surface (BAND) and not
past the garment's edges, so the air beside a hem or under a loose skirt isn't read as inside it.
"""
from __future__ import annotations

import base64
import hashlib

import numpy as np

THICKNESS = 0.0015      # m: the collision thickness of a frozen garment (spec: ~1.5 mm)
BAND = 0.03             # m: how far under a frozen garment a point still counts as inside it
CLAMP = 0.06            # m: the body grid's clamp (meshbody.build_grid)
GROW = 0.40             # m: how far past the body's own grid a frozen garment can extend it
_CACHE: dict = {}


def decode(c) -> tuple[np.ndarray, np.ndarray]:
    """A garment's draped mesh as the studio sends it: {v: int16 mm, f: uint32}, base64."""
    damaged = ValueError("A frozen garment's draped shape is damaged (in the project file): unfreeze it, drape it "
                         "and freeze it again.")
    try:
        bv, bf = base64.b64decode(c["v"]), base64.b64decode(c["f"])
    except Exception:
        raise damaged from None
    if not bv or not bf or len(bv) % 6 or len(bf) % 12:
        raise damaged
    V = np.frombuffer(bv, np.int16).reshape(-1, 3).astype(np.float64) / 1000.0
    F = np.frombuffer(bf, np.uint32).reshape(-1, 3).astype(np.int64)
    if F.max() >= len(V):
        raise damaged
    return V, F


def _samples(V, F, body, spacing):
    """Points over the surface (about `spacing` apart), each with its triangle's normal turned away from
    the body, and whether it lies on a triangle at the garment's edge."""
    from .meshbody import grid_sdf_batch
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    n = np.cross(b - a, c - a)
    area2 = np.linalg.norm(n, axis=1)
    n = n / np.maximum(area2, 1e-12)[:, None]
    cen = (a + b + c) / 3
    e = 0.004                                       # the body's outward direction at each triangle
    gp = grid_sdf_batch(np.ascontiguousarray(cen + e * n), body.grid, body.origin, body.h)
    gm = grid_sdf_batch(np.ascontiguousarray(cen - e * n), body.grid, body.origin, body.h)
    n[gp < gm] *= -1
    # edge triangles: an edge used by one triangle only is the garment's border
    E = np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), axis=1)
    _, inv, cnt = np.unique(E, axis=0, return_inverse=True, return_counts=True)
    border = (cnt[inv.ravel()] == 1).reshape(3, -1).any(0)
    # barycentric samples: k per side so the spacing holds on big triangles
    side = np.maximum(np.linalg.norm(b - a, axis=1), np.linalg.norm(c - a, axis=1))
    k = np.clip(np.ceil(side / spacing).astype(int), 1, 12)
    P, N, B = [cen], [n], [border]
    for kk in np.unique(k[k > 1]):
        sel = np.flatnonzero(k == kk)
        for i in range(kk + 1):
            for j in range(kk + 1 - i):
                u, v = i / kk, j / kk
                P.append(a[sel] + u * (b[sel] - a[sel]) + v * (c[sel] - a[sel])); N.append(n[sel]); B.append(border[sel])
    P.append(V)                                     # the vertices themselves
    vn = np.zeros_like(V); np.add.at(vn, F.ravel(), np.repeat(n, 3, axis=0))
    N.append(vn / np.maximum(np.linalg.norm(vn, axis=1), 1e-12)[:, None])
    vb = np.zeros(len(V), bool); vb[F[border].ravel()] = True
    B.append(vb)
    return np.concatenate(P), np.concatenate(N), np.concatenate(B)


def garment_field(V, F, body, xs, ys, zs, thickness=THICKNESS):
    """Signed distance (m) on the grid xs × ys × zs to a frozen garment's surface, offset by `thickness`:
    negative under it (the body's side, within BAND, not past its edges), positive outside."""
    from scipy.spatial import cKDTree
    h = xs[1] - xs[0]
    P, N, B = _samples(V, F, body, spacing=min(h / 2, 0.004))
    lo, hi = P.min(0) - CLAMP, P.max(0) + CLAMP     # beyond this, the clamp
    out = np.full((len(xs), len(ys), len(zs)), CLAMP)
    ix = np.flatnonzero((xs >= lo[0]) & (xs <= hi[0]))
    iy = np.flatnonzero((ys >= lo[1]) & (ys <= hi[1]))
    iz = np.flatnonzero((zs >= lo[2]) & (zs <= hi[2]))
    if not (len(ix) and len(iy) and len(iz)):
        return out
    G = np.stack(np.meshgrid(xs[ix], ys[iy], zs[iz], indexing="ij"), -1).reshape(-1, 3)
    d, j = cKDTree(P).query(G, distance_upper_bound=CLAMP)
    s = np.full(len(G), CLAMP)
    hit = np.isfinite(d)
    side = np.einsum("ij,ij->i", G[hit] - P[j[hit]], N[j[hit]])
    under = (side < 0) & (d[hit] < BAND) & ~B[j[hit]]
    s[hit] = np.where(under, -d[hit], d[hit]) - thickness
    out[np.ix_(ix, iy, iz)] = np.clip(s, -CLAMP, CLAMP).reshape(len(ix), len(iy), len(iz))
    return out


class LayeredBody:
    """The avatar's body with frozen garments in its collision grid. Everything else (the mesh, the tape,
    the body lines) is the body's own."""
    kind = "mesh"

    def __init__(self, body, grid, origin, h):
        self._body = body
        self._g = (grid, origin, h)

    def __getattr__(self, k):
        return getattr(self._body, k)

    @property
    def grid(self):
        return self._g[0]

    @property
    def origin(self):
        return self._g[1]

    @property
    def h(self):
        return self._g[2]

    def _ensure_grid(self):
        return self._g

    def sdf(self, p):
        from .meshbody import grid_sdf_batch
        return grid_sdf_batch(np.ascontiguousarray(np.atleast_2d(p), dtype=np.float64), *self._g)


def layered_body(body, colliders, thickness_mm=None):
    """body with the frozen garments `colliders` ([{v, f}] as the studio sends them) in its collision grid.
    The grid grows to cover them (the body's own values are kept; outside its old box: the clamp)."""
    if not colliders:
        return body
    t = THICKNESS if thickness_mm is None else float(thickness_mm) / 1000.0
    key = hashlib.sha1(b"".join(c["v"].encode() + c["f"].encode() for c in colliders) + repr((t, id(body))).encode()).hexdigest()
    if key in _CACHE:
        return _CACHE[key]
    grid, lo, h = layered_grid(body, [decode(c) for c in colliders], t)
    out = LayeredBody(body, grid, lo, h)
    if len(_CACHE) > 4:
        _CACHE.clear()
    _CACHE[key] = out
    return out


def layered_grid(body, meshes, thickness=THICKNESS):
    """The body's collision grid with garment surfaces `meshes` ([(V, F)], m) in it: (grid, origin, h).
    Frozen garments from the page (layered_body) and the inner garments of a multi-garment drape when the next one
    starts (cloth.ClothSim garment_freeze) both come here. The meshes are never moved: only the grid changes."""
    from .meshbody import grid_sdf_batch
    t = float(thickness)
    G0, O0, h = body.grid, body.origin, body.h
    top = O0 + (np.array(G0.shape) - 1) * h
    lo = np.minimum(O0, np.min([V.min(0) for V, _ in meshes], axis=0) - 0.05)
    hi = np.maximum(top, np.max([V.max(0) for V, _ in meshes], axis=0) + 0.05)
    # a frozen mesh comes from a project file: a stray point metres away must not grow the grid to billions of
    # cells (out of memory). Clothes stay near the body: the grid grows at most GROW past the body's box
    lo, hi = np.maximum(lo, O0 - GROW), np.minimum(hi, top + GROW)
    # keep the body's grid points where they were: the new box starts a whole number of cells from the old one
    lo = O0 - np.ceil((O0 - lo) / h) * h
    xs, ys, zs = (np.arange(lo[i], hi[i] + h * 0.5, h) for i in range(3))
    if lo.tolist() == O0.tolist() and (len(xs), len(ys), len(zs)) == G0.shape:
        grid = G0.copy()
    else:
        P = np.stack(np.meshgrid(xs, ys, zs, indexing="ij"), -1).reshape(-1, 3)
        grid = np.minimum(grid_sdf_batch(np.ascontiguousarray(P), G0, O0, h), CLAMP).reshape(len(xs), len(ys), len(zs))
    for V, F in meshes:
        grid = np.minimum(grid, garment_field(V, F, body, xs, ys, zs, t))
    return np.ascontiguousarray(grid, dtype=np.float64), np.ascontiguousarray(lo, dtype=np.float64), float(h)
