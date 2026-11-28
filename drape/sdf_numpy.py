"""Signed distance to a closed triangle mesh on a grid, with numpy and SciPy only
(no libigl), so it also runs in a web browser (Pyodide).

Distance: exact point-to-triangle distance against the nearest triangles (found
with a k-d tree), only for points near the surface; values are clamped anyway.
Sign: parity of a ray along +z: a point is inside if an odd number of the
mesh's triangles lie below it in its grid column. Exact for watertight meshes
(the avatar body is).
"""
from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree


def _closest_dist(P, A, B, C):
    """Distance from points P to triangles (A, B, C), row by row (Ericson, Real-Time
    Collision Detection 5.1.5), vectorised."""
    ab, ac, ap = B - A, C - A, P - A
    d1, d2 = (ab * ap).sum(1), (ac * ap).sum(1)
    bp = P - B
    d3, d4 = (ab * bp).sum(1), (ac * bp).sum(1)
    cp = P - C
    d5, d6 = (ab * cp).sum(1), (ac * cp).sum(1)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    Q = np.empty_like(P)
    done = np.zeros(len(P), bool)

    def put(mask, q):
        m = mask & ~done
        Q[m] = q[m]
        done[m] = True

    put((d1 <= 0) & (d2 <= 0), A)
    put((d3 >= 0) & (d4 <= d3), B)
    put((d6 >= 0) & (d5 <= d6), C)
    with np.errstate(divide="ignore", invalid="ignore"):
        v = d1 / (d1 - d3)
        put((vc <= 0) & (d1 >= 0) & (d3 <= 0), A + v[:, None] * ab)
        w = d2 / (d2 - d6)
        put((vb <= 0) & (d2 >= 0) & (d6 <= 0), A + w[:, None] * ac)
        w2 = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        put((va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0), B + w2[:, None] * (C - B))
        den = 1.0 / (va + vb + vc)
        v3, w3 = (vb * den)[:, None], (vc * den)[:, None]
        put(np.ones(len(P), bool), A + ab * v3 + ac * w3)
    return np.linalg.norm(P - Q, axis=1)


def inside_mask(V, F, xs, ys, zs):
    """Boolean (nx, ny, nz): grid point inside the closed mesh (ray parity along +z)."""
    nx, ny, nz = len(xs), len(ys), len(zs)
    h = xs[1] - xs[0]
    T = V[F]
    x0, y0 = xs[0], ys[0]
    # each triangle against the grid columns its xy shadow covers
    lo = np.floor((T[:, :, :2].min(1) - [x0, y0]) / h).astype(int)
    hi = np.ceil((T[:, :, :2].max(1) - [x0, y0]) / h).astype(int)
    lo = np.clip(lo, 0, [nx - 1, ny - 1])
    hi = np.clip(hi, 0, [nx - 1, ny - 1])
    span = (hi - lo + 1)
    cnt = span[:, 0] * span[:, 1]
    tri = np.repeat(np.arange(len(F)), cnt)
    k = np.arange(cnt.sum()) - np.repeat(np.cumsum(cnt) - cnt, cnt)
    ix = lo[tri, 0] + k // span[tri, 1]
    iy = lo[tri, 1] + k % span[tri, 1]
    px, py = xs[ix], ys[iy]
    a, b, c = T[tri, 0], T[tri, 1], T[tri, 2]
    # barycentric test in xy (half-open rule so a ray through a shared edge counts once)
    def ed(p, q, x, y):
        return (q[:, 0] - p[:, 0]) * (y - p[:, 1]) - (q[:, 1] - p[:, 1]) * (x - p[:, 0])
    w0, w1, w2 = ed(b, c, px, py), ed(c, a, px, py), ed(a, b, px, py)
    area = w0 + w1 + w2
    s = np.sign(area)
    ok = (np.abs(area) > 1e-20) & (w0 * s >= 0) & (w1 * s >= 0) & (w2 * s >= 0)
    ok &= ~((w0 == 0) | (w1 == 0) | (w2 == 0)) | ((w0 * s > 0) & (w1 * s > 0) & (w2 * s > 0))
    tri, ix, iy = tri[ok], ix[ok], iy[ok]
    w0, w1, w2, area = w0[ok], w1[ok], w2[ok], area[ok]
    zh = (w0 * T[tri, 0, 2] + w1 * T[tri, 1, 2] + w2 * T[tri, 2, 2]) / area
    # crossings below each grid point, per column
    col = ix * ny + iy
    order = np.lexsort((zh, col))
    col, zh = col[order], zh[order]
    kz = np.searchsorted(zs, zh, side="right")             # first grid z above the crossing
    hits = np.zeros((nx * ny, nz + 1), np.int32)
    np.add.at(hits, (col, kz), 1)
    parity = np.cumsum(hits[:, :nz], axis=1) & 1
    return parity.reshape(nx, ny, nz).astype(bool)


def signed_distance_grid(V, F, xs, ys, zs, clamp=0.06, k=32, k_far=8, band=0.02):
    """Signed distance (negative inside), clamped to +-clamp, on the grid xs x ys x zs."""
    V = np.asarray(V, float)
    F = np.asarray(F, np.int64)
    inside = inside_mask(V, F, xs, ys, zs)
    G = np.stack(np.meshgrid(xs, ys, zs, indexing="ij"), -1).reshape(-1, 3)
    D = np.full(len(G), clamp)
    # only points within reach of the surface need an exact distance
    cen = V[F].mean(1)
    rad = np.linalg.norm(V[F] - cen[:, None], axis=2).max()
    near_tree = cKDTree(cen)
    d0, _ = near_tree.query(G, k=1, distance_upper_bound=clamp + rad)
    near = np.flatnonzero(np.isfinite(d0))
    for s in range(0, len(near), 200_000):                  # in chunks: bounded memory
        idx = near[s:s + 200_000]
        P = G[idx]
        # close to the skin the nearest centroids can miss the nearest triangle (small,
        # thin triangles): look further there (2.6 mm worst error with 12, 0.18 mm with 32)
        kk = np.where(d0[idx] < band + rad, k, k_far)
        _, nb = near_tree.query(P, k=k)
        best = np.full(len(P), np.inf)
        for j in range(k):
            use = kk > j
            if not use.any():
                break
            t = F[nb[use, j]]
            best[use] = np.minimum(best[use], _closest_dist(P[use], V[t[:, 0]], V[t[:, 1]], V[t[:, 2]]))
        D[idx] = np.minimum(best, clamp)
    S = np.where(inside.reshape(-1), -D, D)
    return S.reshape(len(xs), len(ys), len(zs))
