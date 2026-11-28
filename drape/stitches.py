"""Seam and topstitch lines to draw on the draped garment.

Seam lines follow the sewn edges; topstitching runs 8 mm in from every hem
and opening (the free edges), placed on the flat pattern and carried onto the
drape through the triangle it falls in, so it moves with the cloth. Each line
is a list of points, each point = (3 vertex ids of the welded mesh, barycentric
weights)."""
from __future__ import annotations

import numpy as np


def _locate(P, tris, uv):
    """Triangle and barycentric coordinates of 2D points P in a flat mesh."""
    from scipy.spatial import cKDTree
    cent = uv[tris].mean(1)
    tree = cKDTree(cent)
    out_t, out_b = [], []
    for p in P:
        _, cand = tree.query(p, k=min(12, len(tris)))
        best = None
        for t in np.atleast_1d(cand):
            a, b, c = uv[tris[t]]
            T = np.array([[b[0] - a[0], c[0] - a[0]], [b[1] - a[1], c[1] - a[1]]])
            try:
                l1, l2 = np.linalg.solve(T, p - a)
            except np.linalg.LinAlgError:
                continue
            bc = np.array([1 - l1 - l2, l1, l2])
            err = -min(bc.min(), 0)
            if best is None or err < best[0]:
                best = (err, t, np.clip(bc, 0, 1) / max(np.clip(bc, 0, 1).sum(), 1e-9))
            if err == 0:
                break
        out_t.append(best[1]); out_b.append(best[2])
    return np.array(out_t), np.array(out_b)


def stitch_lines(g, vmap, inset=0.008, step=0.006):
    """Lines for the 3D view: [{"kind": "seam"|"topstitch", "ids": [[a,b,c],...], "bary": [[...]]}].
    g is the garment before welding; vmap maps its vertices to the welded mesh."""
    vmap = np.asarray(vmap)
    seamed = {(s.panel_a, s.edge_a) for s in g.meta["seam_defs"]} | {(s.panel_b, s.edge_b) for s in g.meta["seam_defs"]}
    lines = []
    for s in g.meta["seam_defs"]:
        ia = g.meta["edge_index"][(s.panel_a, s.edge_a)]
        if len(ia) > 1:
            v = vmap[ia]
            lines.append({"kind": "seam", "ids": np.stack([v, v, v], 1).tolist(), "bary": [[1, 0, 0]] * len(v)})
    names = list(g.panel_names)
    for p in g.meta["panels"]:
        k = names.index(p.name)
        tmask = g.panel_id[g.tris[:, 0]] == k
        tris = g.tris[tmask]
        if not len(tris):
            continue
        for en, E in p.edges:
            if (p.name, en) in seamed or len(E) < 2:
                continue
            d = np.gradient(E, axis=0)
            d /= np.linalg.norm(d, axis=1, keepdims=True) + 1e-12
            inward = np.stack([-d[:, 1], d[:, 0]], 1)        # CCW outline: left of the direction is inside
            L = np.r_[0, np.cumsum(np.linalg.norm(np.diff(E, axis=0), axis=1))]
            if L[-1] < 4 * inset:
                continue
            s = np.arange(inset, L[-1] - inset + 1e-9, step)
            P = np.stack([np.interp(s, L, E[:, 0]), np.interp(s, L, E[:, 1])], 1)
            N = np.stack([np.interp(s, L, inward[:, 0]), np.interp(s, L, inward[:, 1])], 1)
            P = P + N * inset
            t, b = _locate(P, tris, g.uv)
            ids = vmap[tris[t]]
            lines.append({"kind": "topstitch", "ids": ids.tolist(), "bary": np.round(b, 4).tolist()})
    return lines
