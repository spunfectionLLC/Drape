"""Hems that are part of the piece: the turn-up allowance is cut on, beyond the
hem line, not sewn on as another piece. Also a fold-over elastic casing.

A hem edge's cut line sits `allowance` (= depth + turn) outside the stitch line,
and its ends are the mirror image of the neighbouring seam's cut line across the
fold. Folded up, the allowance then lies exactly on the piece, side seam
allowances included: a flared skirt's hem doesn't come up too narrow, a tapered
leg's doesn't come up too wide (patternmakers call it folding the hem corner).

A hem on an edge (editor format, cm): edge["hem"] = {"style", "depth_cm", "turn_cm"}.
"""
from __future__ import annotations

import numpy as np

# style: label, finished depth (cm), turned under (cm), how it's sewn
STYLES = {
    "double": dict(label="Double-fold hem", depth=2.5, turn=1.0,
                   how="Fold along the outer line, then along the hem line, so the raw edge is hidden inside; stitch close to the inner fold."),
    "single": dict(label="Single-fold hem (overlocked)", depth=2.5, turn=0.0,
                   how="Overlock or zigzag the raw edge, fold up along the hem line and stitch (knits: twin needle or coverstitch)."),
    "narrow": dict(label="Narrow hem", depth=0.6, turn=0.6,
                   how="Fold 6 mm twice and stitch on the fold: for curved hems, sheers and ruffles."),
    "blind": dict(label="Blind hem", depth=4.0, turn=1.0,
                  how="Fold as a double-fold hem, then blind-stitch by hand or machine so almost nothing shows outside."),
    "casing": dict(label="Elastic casing", depth=3.0, turn=1.0,
                   how="Fold as a double-fold hem and stitch close to the inner fold, leaving 5 cm open; thread the elastic through, overlap its ends 2 cm, zigzag them, close the gap."),
}


def allowance_cm(hem) -> float:
    return float(hem.get("depth_cm", 0)) + float(hem.get("turn_cm", 0))


def normalise(hem):
    """Fill in a hem's defaults from its style."""
    st = STYLES.get(hem.get("style", "double"), STYLES["double"])
    return {"style": hem.get("style", "double"), "depth_cm": float(hem.get("depth_cm", st["depth"])),
            "turn_cm": float(hem.get("turn_cm", st["turn"]))}


def _offset(P, d):
    """Polyline P offset by d to its right (outside, for a counter-clockwise outline)."""
    from .closures import _offset as off
    return off(P, d)


def _unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def _reflect(v, axis):
    a = _unit(axis)
    return 2 * (v @ a) * a - v


def _meet(p, d, q, e):
    """Where the lines p + s d and q + t e cross (None if parallel)."""
    M = np.array([d, -e]).T
    if abs(np.linalg.det(M)) < 1e-12:
        return None
    s, _ = np.linalg.solve(M, q - p)
    return p + s * d


def hem_strip(edges, i, sas, a):
    """The turn-up allowance of edge i (cm): a polygon from the hem line out to
    the raw edge `a` beyond it, its ends the neighbouring cut lines mirrored
    across the fold. edges: [pts (n,2) cm] counter-clockwise; sas: seam allowance
    per edge (cm)."""
    from shapely.geometry import Polygon
    n = len(edges)
    E = np.asarray(edges[i], float)
    if len(E) == 2:
        E = np.stack([np.linspace(E[0, 0], E[1, 0], 8), np.linspace(E[0, 1], E[1, 1], 8)], 1)
    Q = _offset(E, a)
    ends = []
    for at_start in (True, False):
        k = (i - 1) % n if at_start else (i + 1) % n
        N = np.asarray(edges[k], float)
        corner = E[0] if at_start else E[-1]
        tan = _unit(E[1] - E[0]) if at_start else _unit(E[-1] - E[-2])
        # the neighbour's cut line near the corner: its last (first) segment, offset by its allowance
        seg = N[-2:] if at_start else N[:2]
        nd = _unit(seg[1] - seg[0])
        nO = _offset(seg, sas[k])
        # where it crosses the hem line (the fold): the cut corner on the fold
        C = _meet(nO[0], nd, corner, tan)
        if C is None or np.linalg.norm(C - corner) > 4 * max(sas[k], 1.0) + a:
            C = corner + (nO[-1] - seg[-1] if at_start else nO[0] - seg[0])
        # folded over the hem line, the neighbour's cut line runs the mirrored way
        md = _reflect(nd if not at_start else -nd, tan)
        out_pt = Q[0] if at_start else Q[-1]
        P = _meet(C, md, out_pt, tan)
        if P is None or np.linalg.norm(P - out_pt) > 4 * a + 4 * max(sas[k], 1.0):
            P = out_pt + (C - corner)
        ends.append((C, P))
    (CA, PA), (CB, PB) = ends
    ring = np.vstack([CA, PA, Q[1:-1], PB, CB, E[::-1][1:-1]])
    poly = Polygon(ring).buffer(0)
    if poly.geom_type != "Polygon":
        poly = max(poly.geoms, key=lambda q: q.area)
    return poly


def fold_marks(E_cm, hem):
    """Fold lines (cm, like closure marks): the hem line, and for a turned-under
    hem the inner fold `depth` out from it."""
    E = np.asarray(E_cm, float)
    out = [{"kind": "fold", "pts": E.copy()}]
    if hem["turn_cm"] > 0:
        out.append({"kind": "fold", "pts": _offset(E, hem["depth_cm"])})
    return out


def curve_excess(E_cm, a):
    """How much longer (fraction) the raw edge of a hem `a` deep is than where it
    lands when folded up: > 0 on outward-curving (flared) hems."""
    from .closures import _offset as off
    E = np.asarray(E_cm, float)
    if len(E) < 3:
        return 0.0
    L = np.linalg.norm(np.diff(E, axis=0), axis=1).sum()
    Lo = np.linalg.norm(np.diff(off(E, a), axis=0), axis=1).sum()
    return float(Lo / L - 1) if L > 0 else 0.0


def max_flat_depth(E_cm, limit=0.05):
    """The deepest allowance (cm) whose raw edge is at most `limit` longer than
    where it lands (beyond that a curved hem ripples)."""
    lo, hi = 0.0, 10.0
    if curve_excess(E_cm, hi) <= limit:
        return hi
    for _ in range(30):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if curve_excess(E_cm, mid) <= limit else (lo, mid)
    return lo
