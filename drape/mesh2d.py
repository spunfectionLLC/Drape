"""Triangulate a flat pattern piece for the cloth solver.

The outline's points are kept exactly as given, in order, with no points added
on the outline (seams depend on both sides having the same points). The inside
is filled with an evenly spaced, slightly jittered triangular grid (the jitter
keeps folds from lining up with the grid), the points are joined by a Delaunay
triangulation, any outline segment the triangulation missed is restored by edge
flips, and the triangles outside the piece are dropped.

Only numpy, scipy (Qhull) and shapely: all free for commercial use.
"""
from __future__ import annotations

import numpy as np
from scipy.spatial import Delaunay


def _orient(a, b, c):
    """Twice the signed area of (a, b, c); > 0 when counter-clockwise. Vectorised over rows."""
    return (b[..., 0] - a[..., 0]) * (c[..., 1] - a[..., 1]) - (b[..., 1] - a[..., 1]) * (c[..., 0] - a[..., 0])


def _interior_points(outline, h, seed):
    import shapely
    from shapely.geometry import LinearRing, Polygon
    poly = Polygon(outline)
    if not poly.is_valid:
        poly = poly.buffer(0)
    x0, y0, x1, y1 = poly.bounds
    dy = h * np.sqrt(3) / 2
    rows = []
    for k, y in enumerate(np.arange(y0 + dy / 2, y1, dy)):
        xs = np.arange(x0 + (h / 2 if k % 2 else 0.0) + h / 4, x1, h)
        rows.append(np.c_[xs, np.full(len(xs), y)])
    if not rows:
        return np.zeros((0, 2))
    P = np.vstack(rows)
    P += np.random.default_rng(seed).uniform(-0.12, 0.12, P.shape) * h
    P = P[shapely.contains_xy(poly, P[:, 0], P[:, 1])]
    if len(P):
        # keep clear of the outline: it is never sampled coarser than h (seams can make it finer)
        d = shapely.distance(LinearRing(outline), shapely.points(P))
        P = P[d > 0.55 * h]
    return P


def _recover(T, V, a, b, max_flips=10000):
    """Edge-flip until segment (a, b) is an edge of the triangulation T (list of [i, j, k], CCW)."""
    pa, pb = V[a], V[b]
    for _ in range(max_flips):
        E = np.sort(np.vstack([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]]), axis=1)
        if ((E[:, 0] == min(a, b)) & (E[:, 1] == max(a, b))).any():
            return T
        # edges properly crossing the open segment
        Eu = np.unique(E, axis=0)
        Eu = Eu[(Eu[:, 0] != a) & (Eu[:, 1] != a) & (Eu[:, 0] != b) & (Eu[:, 1] != b)]
        c, d = V[Eu[:, 0]], V[Eu[:, 1]]
        o1, o2 = _orient(pa, pb, c), _orient(pa, pb, d)
        o3, o4 = _orient(c, d, pa[None]), _orient(c, d, pb[None])
        cross = Eu[(o1 * o2 < 0) & (o3 * o4 < 0)]
        if not len(cross):
            raise ValueError("could not restore an outline segment")
        flipped = False
        for i, j in cross:
            # the two triangles sharing edge (i, j)
            has = ((T == i).any(1)) & ((T == j).any(1))
            ts = np.flatnonzero(has)
            if len(ts) != 2:
                continue
            t1, t2 = T[ts[0]], T[ts[1]]
            p = [v for v in t1 if v != i and v != j][0]
            q = [v for v in t2 if v != i and v != j][0]
            # the quad p-i-q-j must be convex to flip (i, j) into (p, q)
            if _orient(V[p], V[q], V[i]) * _orient(V[p], V[q], V[j]) >= 0:
                continue
            if _orient(V[i], V[j], V[p]) * _orient(V[i], V[j], V[q]) >= 0:
                continue
            n1, n2 = [p, q, i], [q, p, j]
            for n in (n1, n2):
                if _orient(V[n[0]], V[n[1]], V[n[2]]) < 0:
                    n[1], n[2] = n[2], n[1]
            T = T.copy()
            T[ts[0]], T[ts[1]] = n1, n2
            flipped = True
            break
        if not flipped:
            raise ValueError("could not restore an outline segment (no convex flip)")
    raise ValueError("could not restore an outline segment (too many flips)")


def triangulate_piece(outline: np.ndarray, h: float, seed: int = 0):
    """outline: (nb, 2) closed polygon (not repeated), any orientation.
    Returns (V, T): V[:nb] == outline exactly; T counter-clockwise triangles."""
    import shapely
    from shapely.geometry import Polygon
    outline = np.asarray(outline, float)
    nb = len(outline)
    P = _interior_points(outline, h, seed)
    V = np.vstack([outline, P]) if len(P) else outline.copy()
    T = Delaunay(V, qhull_options="Qbb Qc Qz Q12").simplices.astype(np.int64)
    flip = _orient(V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]) < 0
    T[flip] = T[flip][:, [0, 2, 1]]
    # every outline segment must be an edge. Most already are: look them up in one set and only flip for the
    # missing ones (calling _recover for each sorted every edge once per segment: ~40% of a tee's draft)
    def edge_set(T):
        E = np.sort(np.vstack([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]]), axis=1)
        return set(map(tuple, E.tolist()))
    have = edge_set(T)
    for i in range(nb):
        j = (i + 1) % nb
        if (min(i, j), max(i, j)) not in have:
            T = _recover(T, V, i, j)
            have = edge_set(T)
    # with the outline in place every triangle is wholly inside or outside: test its centroid
    poly = Polygon(outline)
    if not poly.is_valid:
        poly = poly.buffer(0)
    cen = V[T].mean(1)
    T = T[shapely.contains_xy(poly, cen[:, 0], cen[:, 1])]
    # drop slivers lying flat along the outline (three outline points in a row)
    area = np.abs(_orient(V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]))
    T = T[area > 1e-12 * max(h * h, 1e-12)]
    used = np.zeros(len(V), bool)
    used[T.ravel()] = True
    if not used[:nb].all():
        raise ValueError("an outline point ended up outside the mesh")
    if not used.all():                     # an interior point cut off by a flip: drop and renumber
        keep = np.flatnonzero(used)
        remap = -np.ones(len(V), np.int64)
        remap[keep] = np.arange(len(keep))
        V, T = V[keep], remap[T]
    return V, T
