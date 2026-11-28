"""Ease report: how much bigger the garment is than the body at each
girth line (positive = room, negative = the fabric has to stretch).

Where the garment's girth comes from (a design rule): never from adding up 2D pattern
lengths across pieces.
  - before a drape: the girths the drafting formulas made (`meta["girths"]`, set by the
    drafting code: body measurement + its ease parameter, a sleeve's drafted width, the
    neckline from its drafted width and depths), see `ease_report`;
  - after a drape: a tape round the draped 3D mesh, the perimeter of the convex hull of
    its cross-section at the girth line, the way the body itself is measured
    (meshmeasure), see `drape_ease`.
The body's girth is always the tape on the 3D body.
"""
from __future__ import annotations

import numpy as np

from .body import Body
from .pattern import Garment

LINES = (("chest", "chest"), ("waist", "waist"), ("seat", "hip"))


# ------------------------------------------------------------- drafting --
def _quarter_ellipse(a, b):
    """A quarter of an ellipse's perimeter (Ramanujan), semi-axes a, b."""
    if a <= 0 or b <= 0:
        return max(a, b, 0.0)
    h = ((a - b) / (a + b)) ** 2
    return float(np.pi * (a + b) * (1 + 3 * h / (10 + np.sqrt(4 - 3 * h))) / 4)


def neck_opening(neck_u, front_drop, back_drop):
    """The neckline's length (m) from its drafting parameters: half-width neck_u and the
    depth below the neck point at the front and the back. Each quarter of the opening
    is taken as a quarter ellipse (the drafted curve leaves the shoulder square and
    arrives square to the centre line)."""
    return 2 * (_quarter_ellipse(neck_u, front_drop) + _quarter_ellipse(neck_u, back_drop))


def _row(line, body_g, gar_g, tight=0.0, close=6.0, source="drafted"):
    e = (gar_g - body_g) * 100
    return {"line": line, "body_cm": body_g * 100, "garment_cm": gar_g * 100, "ease_cm": e,
            "status": _verdict(e, tight=tight, close=close), "source": source}


def ease_report(g: Garment, body: Body) -> list[dict]:
    """Ease at each girth line from the girths the drafting made (`g.meta["girths"]`, m).
    The garment's height on the body (hem to top) only says which lines it covers."""
    G = g.meta.get("girths") or {}
    rows = []
    if g.meta.get("lower") == "trousers" or (g.meta.get("lower") and not g.meta.get("torso_panels")):
        if "waist" in G:
            rows.append(_row("waist", body.girth_at_y(body.section_y("waist")), G["waist"], tight=0, close=4))
        if "hip" in G:
            rows.append(_row("hip", body.tape_girth("seat"), G["hip"]))
        T = getattr(body, "tape", None)
        if T is not None and "thigh" in G:
            rows.append(_row("thigh", T.thigh(), G["thigh"], tight=1, close=4))
        return rows
    pmap = {p.name: p for p in g.meta["panels"]}
    top_v = max(pl[:, 1].max() for n in g.meta["torso_panels"] for _, pl in pmap[n].edges)
    for line, label in LINES:
        y = body.section_y(line)
        v = y - g.meta["hem_y"]
        if v < 0:
            rows.append({"line": label, "status": "garment ends above this line"})
        elif line == "waist" and abs(v - top_v) < 0.06 and "waist" in G:
            # a lower-body garment hung at the waist: its drafted waist
            rows.append(_row("waist", body.girth_at_y(y), G["waist"], tight=0, close=4))
        elif v > top_v:
            rows.append({"line": label, "status": "garment starts below this line"})
        elif label in G:
            # near the garment's top the tape is taken level (the body's girth at that height)
            rows.append(_row(label, body.girth_at_y(y) if v > top_v - 0.06 else body.tape_girth(line), G[label]))
    if "neckline" in G:
        rows.append(_row("neckline", body.neck_girth(), G["neckline"], tight=3, close=6))
    if "upper arm" in G:
        rows.append(_row("upper arm", body.upper_arm_girth(), G["upper arm"], tight=2, close=5))
    return rows


# ------------------------------------------------------------- the drape --
def section_girth(x, tris, y, keep=None):
    """Tape-measure girth (m) of a triangle mesh at height y: the perimeter of the convex
    hull of where its triangles cross the plane (a tape bridges hollows and folds).
    keep: which triangles to use (bool mask), e.g. the torso pieces only. None if the
    mesh doesn't reach that height."""
    from scipy.spatial import ConvexHull
    T = tris if keep is None else tris[keep]
    pts = []
    for a, b in ((0, 1), (1, 2), (2, 0)):
        p, q = x[T[:, a]], x[T[:, b]]
        cross = (p[:, 1] - y) * (q[:, 1] - y) < 0
        if cross.any():
            p, q = p[cross], q[cross]
            t = ((y - p[:, 1]) / (q[:, 1] - p[:, 1]))[:, None]
            pts.append((p + t * (q - p))[:, [0, 2]])
    if not pts or sum(len(p) for p in pts) < 3:
        return None
    return float(ConvexHull(np.concatenate(pts)).area)       # in 2D, ConvexHull.area is the perimeter


def drape_ease(sim, body) -> list[dict]:
    """Ease at each girth line measured on the draped garment: a tape round its 3D
    cross-section (torso pieces only on a top, so sleeves stay out). For garments from
    the pattern library (their meta names the torso pieces and the legs)."""
    meta = sim.g0.meta
    names = [p.name for p in meta["panels"]]
    tris = sim.g.tris
    tri_pid = sim.g.panel_id[tris[:, 0]]
    rows = []
    lower = meta.get("lower") and not meta.get("torso_panels")
    if lower:
        lines = [("waist", "waist", None), ("seat", "hip", None)]
    else:
        torso = np.isin(tri_pid, [names.index(n) for n in meta.get("torso_panels", []) if n in names])
        lines = [(ln, lab, torso) for ln, lab in LINES]
    for line, label, keep in lines:
        y = body.section_y(line)
        if line == "waist":
            # a garment hung at the waist settles a little below the body's waist line:
            # the tape goes just under its top edge then
            P = sim.x[np.unique(tris if keep is None else tris[keep])]
            y = min(y, float(np.percentile(P[:, 1], 99)) - 0.015)
        gg = section_girth(sim.x, tris, y, keep)
        if gg is None:
            continue
        if line == "waist":
            rows.append(_row(label, body.girth_at_y(body.section_y("waist")), gg, tight=0, close=4, source="drape"))
        else:
            rows.append(_row(label, body.tape_girth(line), gg, source="drape"))
    T = getattr(body, "tape", None)
    if lower and T is not None:
        leg = np.isin(tri_pid, [names.index(n) for n in ("front_r", "back_r") if n in names])
        if leg.any():       # one leg just below the fork (6 to 0.5 cm under it), the widest
            fork = T.crotch_height() - 0.02
            gs = [section_girth(sim.x, tris, y, leg) for y in np.linspace(fork - 0.06, fork - 0.005, 8)]
            gs = [x for x in gs if x is not None]
            if gs:
                rows.append(_row("thigh", T.thigh(), max(gs), tight=1, close=4, source="drape"))
    return rows


def _verdict(e, tight=0.0, close=6.0):
    if e < tight:
        return "TOO TIGHT (fabric must stretch)"
    if e < close:
        return "close fit"
    if e < 20:
        return "regular fit"
    return "loose / oversized"


def format_ease(rows) -> str:
    L = [f"{'line':10s} {'body':>8s} {'garment':>8s} {'ease':>8s}  fit"]
    for r in rows:
        if "body_cm" in r:
            L.append(f"{r['line']:10s} {r['body_cm']:7.1f}cm {r['garment_cm']:7.1f}cm {r['ease_cm']:+7.1f}cm  {r['status']}")
        else:
            L.append(f"{r['line']:10s} {'':>8s} {'':>8s} {'':>8s}  {r['status']}")
    return "\n".join(L)
