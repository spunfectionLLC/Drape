"""Drafting tools: build pattern pieces from geometry, the way a patternmaker
works on paper. Everything is a polyline (k,2) in metres, pattern space (u
across, v up), compatible with Panel edges, the seam check and DXF export.

Curves      line, bezier, arc, arc_through, circle, ellipse_arc, spline, hermite
Builder     Path(start).line_to / curve_to / smooth_to / arc_to / spline_to / close
Measure     length, point_at, tangent_at, normal_at, closest, intersections
Edit        split_at, join, reverse, offset, mirror, rotate, translate
Pattern     cut_on_fold, add_dart, round_corner, notch, grade, piece

Example (a half front bodice cut on the fold):
    p = (Path((0, 0), "start")
         .line_to((0.25, 0), "hem")
         .line_to((0.25, 0.36), "side")
         .curve_to((0.20, 0.36), (0.17, 0.46), (0.18, 0.54), "armhole")
         .line_to((0.08, 0.58), "shoulder")
         .smooth_to((0, 0.48), "neck", end_tangent=(-1, 0))
         .close("cf"))
    edges = cut_on_fold(p.edges, fold="cf")
"""
from __future__ import annotations

import numpy as np

from .pattern import Panel, polyline_length

TWO_PI = 2 * np.pi


def _a(p):
    return np.asarray(p, dtype=float)


def _unit(v):
    v = _a(v)
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


# =============================================================== curves ===
def line(a, b):
    return np.array([_a(a), _a(b)])


def bezier(p0, p1, p2, p3, k=64):
    t = np.linspace(0, 1, k)[:, None]
    p0, p1, p2, p3 = map(_a, (p0, p1, p2, p3))
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3


def arc(center, radius, a0, a1, k=None):
    """Circular arc from angle a0 to a1 (radians, counter-clockwise if a1 > a0)."""
    c = _a(center)
    k = k or max(8, int(abs(a1 - a0) / (np.pi / 64)) + 1)
    t = np.linspace(a0, a1, k)
    return np.stack([c[0] + radius * np.cos(t), c[1] + radius * np.sin(t)], 1)


def arc_through(p0, p1, p2, k=None):
    """The circular arc from p0 through p1 to p2."""
    p0, p1, p2 = map(_a, (p0, p1, p2))
    ax, ay = p0; bx, by = p1; cx, cy = p2
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-15:
        return np.array([p0, p2])  # collinear: a straight line
    ux = ((ax**2 + ay**2) * (by - cy) + (bx**2 + by**2) * (cy - ay) + (cx**2 + cy**2) * (ay - by)) / d
    uy = ((ax**2 + ay**2) * (cx - bx) + (bx**2 + by**2) * (ax - cx) + (cx**2 + cy**2) * (bx - ax)) / d
    c = np.array([ux, uy]); r = np.linalg.norm(p0 - c)
    ang = lambda p: np.arctan2(p[1] - c[1], p[0] - c[0])
    a0, am, a2 = ang(p0), ang(p1), ang(p2)
    # go the way that passes through p1
    ccw = (a2 - a0) % TWO_PI
    if (am - a0) % TWO_PI <= ccw:
        return arc(c, r, a0, a0 + ccw, k)
    return arc(c, r, a0, a0 - ((a0 - a2) % TWO_PI), k)


def circle(center, radius, k=128):
    """Closed: last point == first (an outline edge that ends where it starts)."""
    c = arc(center, radius, 0, TWO_PI, k)
    c[-1] = c[0]
    return c


def ellipse_arc(center, rx, ry, a0, a1, k=64):
    c = _a(center)
    t = np.linspace(a0, a1, k)
    return np.stack([c[0] + rx * np.cos(t), c[1] + ry * np.sin(t)], 1)


def spline(points, k_per_seg=24, alpha=0.5):
    """Smooth curve through all points (centripetal Catmull-Rom: no loops or
    overshoot at uneven spacing)."""
    P = _a(points)
    if len(P) < 3:
        return P.copy()
    ext = np.vstack([2 * P[0] - P[1], P, 2 * P[-1] - P[-2]])
    out = [P[:1]]
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        t0 = 0.0
        t1 = t0 + max(np.linalg.norm(p1 - p0), 1e-12) ** alpha
        t2 = t1 + max(np.linalg.norm(p2 - p1), 1e-12) ** alpha
        t3 = t2 + max(np.linalg.norm(p3 - p2), 1e-12) ** alpha
        t = np.linspace(t1, t2, k_per_seg + 1)[1:, None]
        A1 = (t1 - t) / (t1 - t0) * p0 + (t - t0) / (t1 - t0) * p1
        A2 = (t2 - t) / (t2 - t1) * p1 + (t - t1) / (t2 - t1) * p2
        A3 = (t3 - t) / (t3 - t2) * p2 + (t - t2) / (t3 - t2) * p3
        B1 = (t2 - t) / (t2 - t0) * A1 + (t - t0) / (t2 - t0) * A2
        B2 = (t3 - t) / (t3 - t1) * A2 + (t - t1) / (t3 - t1) * A3
        out.append((t2 - t) / (t2 - t1) * B1 + (t - t1) / (t2 - t1) * B2)
    return np.vstack(out)


def hermite(p0, d0, p1, d1, k=64, tension=0.4):
    """Curve from p0 leaving in direction d0 to p1 arriving in direction d1
    (directions are normalised; tension scales handle length by the chord).
    The patternmaker's 'square off at both ends' curve."""
    p0, p1 = _a(p0), _a(p1)
    L = np.linalg.norm(p1 - p0) * tension
    return bezier(p0, p0 + _unit(d0) * L, p1 - _unit(d1) * L, p1, k)


# ============================================================== measure ===
def length(c):
    return polyline_length(_a(c))


def _cum(c):
    c = _a(c)
    return np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(c, axis=0), axis=1))])


def point_at(c, s=None, frac=None):
    """Point at arc length s (m) or fraction frac along the curve."""
    c = _a(c); S = _cum(c)
    t = S[-1] * frac if frac is not None else s
    t = float(np.clip(t if t >= 0 else S[-1] + t, 0, S[-1]))
    return np.array([np.interp(t, S, c[:, 0]), np.interp(t, S, c[:, 1])])


def tangent_at(c, s=None, frac=None, h=0.002):
    c = _a(c); S = _cum(c)
    t = S[-1] * frac if frac is not None else s
    a, b = point_at(c, s=max(t - h, 0)), point_at(c, s=min(t + h, S[-1]))
    return _unit(b - a)


def normal_at(c, s=None, frac=None):
    """Left-hand normal (points inside a counter-clockwise outline)."""
    t = tangent_at(c, s, frac)
    return np.array([-t[1], t[0]])


def closest(c, p):
    """(arc length, point, distance) of the curve point nearest to p."""
    c, p = _a(c), _a(p)
    S = _cum(c)
    best = (0.0, c[0], np.inf)
    for i in range(len(c) - 1):
        a, b = c[i], c[i + 1]
        ab = b - a; L2 = ab @ ab
        t = 0.0 if L2 == 0 else np.clip((p - a) @ ab / L2, 0, 1)
        q = a + t * ab; d = np.linalg.norm(p - q)
        if d < best[2]:
            best = (S[i] + t * np.sqrt(L2), q, d)
    return best


def intersections(c1, c2):
    """All crossing points of two polylines."""
    c1, c2 = _a(c1), _a(c2)
    out = []
    for i in range(len(c1) - 1):
        p, r = c1[i], c1[i + 1] - c1[i]
        for j in range(len(c2) - 1):
            q, s_ = c2[j], c2[j + 1] - c2[j]
            den = r[0] * s_[1] - r[1] * s_[0]
            if abs(den) < 1e-18:
                continue
            t = ((q - p)[0] * s_[1] - (q - p)[1] * s_[0]) / den
            u = ((q - p)[0] * r[1] - (q - p)[1] * r[0]) / den
            if -1e-12 <= t <= 1 + 1e-12 and -1e-12 <= u <= 1 + 1e-12:
                pt = p + t * r
                if not any(np.linalg.norm(pt - o) < 1e-9 for o in out):
                    out.append(pt)
    return out


# ================================================================= edit ===
def split_at(c, s=None, frac=None, point=None):
    """Split a curve at arc length s, a fraction, or the point nearest `point`."""
    c = _a(c); S = _cum(c)
    if point is not None:
        s = closest(c, point)[0]
    t = S[-1] * frac if frac is not None else s
    q = point_at(c, s=t)
    a = np.vstack([c[S < t - 1e-12], q])
    b = np.vstack([q, c[S > t + 1e-12]])
    return a, b


def join(*curves, tol=1e-6):
    """Join curves end to start into one."""
    out = _a(curves[0])
    for c in curves[1:]:
        c = _a(c)
        if np.linalg.norm(out[-1] - c[0]) > tol:
            raise ValueError("curves don't meet end to start; reverse one?")
        out = np.vstack([out, c[1:]])
    return out


def reverse(c):
    return _a(c)[::-1].copy()


def translate(c, d):
    return _a(c) + _a(d)


def rotate(c, angle, about=(0, 0)):
    c, o = _a(c), _a(about)
    R = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    return (c - o) @ R.T + o


def mirror(c, a=(0, 0), b=(0, 1)):
    """Reflect across the line through a and b (default: the v axis, u -> -u)."""
    c, a, b = _a(c), _a(a), _a(b)
    d = _unit(b - a)
    v = c - a
    return a + 2 * np.outer(v @ d, d) - v


def offset(c, d):
    """Parallel curve at distance d (to the left of the direction of travel)."""
    c = _a(c)
    n = np.zeros_like(c)
    seg = np.diff(c, axis=0)
    segn = np.stack([-seg[:, 1], seg[:, 0]], 1) / np.maximum(np.linalg.norm(seg, axis=1, keepdims=True), 1e-18)
    n[0], n[-1] = segn[0], segn[-1]
    if len(c) > 2:
        m = segn[:-1] + segn[1:]
        m /= np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-18)
        cos_half = np.maximum((m * segn[1:]).sum(1, keepdims=True), 0.25)   # mitre, limited
        n[1:-1] = m / cos_half
    return c + d * n


# ================================================================ builder ===
class Path:
    """Draw an outline edge by edge, counter-clockwise, naming each edge."""

    def __init__(self, start, name=None):
        self.points = {name or "start": _a(start)}
        self.edges: list[tuple[str, np.ndarray]] = []
        self.cur = _a(start)

    def _add(self, name, poly, end_name=None):
        poly = _a(poly)
        poly[0] = self.cur
        self.edges.append((name or f"e{len(self.edges)}", poly))
        self.cur = poly[-1].copy()
        if end_name:
            self.points[end_name] = self.cur.copy()
        return self

    def end_tangent(self):
        if not self.edges:
            raise ValueError("no previous edge to continue from")
        return tangent_at(self.edges[-1][1], frac=1.0)

    def line_to(self, p, name=None, point=None):
        return self._add(name, line(self.cur, p), point)

    def curve_to(self, c1, c2, p, name=None, point=None):
        return self._add(name, bezier(self.cur, c1, c2, p), point)

    def smooth_to(self, p, name=None, end_tangent=None, tension=0.4, point=None):
        """Curve that continues the previous edge's direction (no kink), and
        optionally arrives along end_tangent (e.g. square to a fold line)."""
        t0 = self.end_tangent()
        t1 = _unit(end_tangent) if end_tangent is not None else _unit(_a(p) - self.cur)
        return self._add(name, hermite(self.cur, t0, p, t1, tension=tension), point)

    def square_to(self, p, start_dir, end_dir, name=None, tension=0.4, point=None):
        """Curve leaving along start_dir and arriving along end_dir."""
        return self._add(name, hermite(self.cur, start_dir, p, end_dir, tension=tension), point)

    def arc_to(self, through, p, name=None, point=None):
        return self._add(name, arc_through(self.cur, through, p), point)

    def spline_to(self, via, p, name=None, point=None):
        return self._add(name, spline([self.cur, *via, p]), point)

    def close(self, name=None):
        start = next(iter(self.points.values()))
        if np.linalg.norm(self.cur - start) > 1e-9:
            self._add(name, line(self.cur, start))
        return self

    def piece(self, name, place, **kw):
        return piece(name, self.edges, place, **kw)


def piece(name, edges, place, validate=True):
    """Make a Panel, checking the outline closes and runs counter-clockwise."""
    edges = [(n, _a(e).copy()) for n, e in edges]
    ring = np.vstack([e[:-1] for _, e in edges])
    area = 0.5 * np.sum(ring[:, 0] * np.roll(ring[:, 1], -1) - np.roll(ring[:, 0], -1) * ring[:, 1])
    if area < 0:  # clockwise: reverse the whole outline
        edges = [(n, e[::-1].copy()) for n, e in edges[::-1]]
    p = Panel(name, edges, place)
    if validate:
        p.validate(tol=1e-7)
    return p


# ============================================================== pattern ===
def cut_on_fold(edges, fold: str, keep_fold=False):
    """Mirror a half piece across its fold edge (a straight edge, usually the
    centre front/back) into the full piece. Edges are renamed *_r (original
    half) and *_l (mirror half); edges that cross the fold (hem, neck) are
    joined into one."""
    names = [n for n, _ in edges]
    i = names.index(fold)
    fe = _a(edges[i][1])
    a, b = fe[0], fe[-1]
    rest = edges[i + 1:] + edges[:i]          # outline from fold end round to fold start
    mirrored = [(n, reverse(mirror(e, a, b))) for n, e in rest[::-1]]
    orig = [(f"{n}_r", e) for n, e in rest]
    mirr = [(f"{n}_l", e) for n, e in mirrored]
    # first edge of orig starts at fold end b; last edge of mirr ends at mirror(b) == b
    # last edge of orig ends at fold start a; first edge of mirr starts at a
    joined_end = (orig[-1][0][:-2], join(orig[-1][1], mirr[0][1]))      # e.g. neck_r + neck_l -> neck
    joined_start = (orig[0][0][:-2], join(mirr[-1][1], orig[0][1]))     # e.g. hem_l + hem_r -> hem
    edges_out = [joined_start] + orig[1:-1] + [joined_end] + mirr[1:-1]
    if keep_fold:
        return edges_out, (a, b)
    return edges_out


def add_dart(edges, edge: str, at: float, width: float, depth: float, direction=None, name="dart"):
    """Insert a dart into an edge. `at` = distance (m) along the edge to the
    dart centre; `width` = opening on the edge; `depth` = distance to the
    point (apex), measured inward along the edge normal unless `direction`
    is given. Returns (new edges, (leg_a, leg_b)) - sew leg_a to leg_b
    (Seam(piece, leg_a, piece, leg_b, reverse=True)).

    The two legs come out exactly equal in length, so the dart sews flat."""
    names = [n for n, _ in edges]
    k = names.index(edge)
    e = _a(edges[k][1])
    c = point_at(e, s=at)
    d = _unit(direction) if direction is not None else normal_at(e, s=at)
    apex = c + d * depth
    left, rest = split_at(e, s=at - width / 2)
    _, right = split_at(rest, s=width)
    la, lb = f"{name}_a", f"{name}_b"
    new = (edges[:k] + [(f"{edge}_1", left), (la, line(left[-1], apex)), (lb, line(apex, right[0])),
                        (f"{edge}_2", right)] + edges[k + 1:])
    return new, (la, lb)


def round_corner(edges, after: str, radius: float):
    """Round the corner where edge `after` ends and the next edge begins with
    a tangent arc of the given radius (fillet). The arc is added to the end
    of `after`."""
    names = [n for n, _ in edges]
    i = names.index(after)
    j = (i + 1) % len(edges)
    A, B = _a(edges[i][1]), _a(edges[j][1])
    P = A[-1]
    ta, tb = -tangent_at(A, frac=1.0), tangent_at(B, frac=0.0)      # both pointing away from P
    theta = np.arccos(np.clip(ta @ tb, -1, 1))
    if theta < 1e-3 or abs(theta - np.pi) < 1e-3:
        return edges
    d = radius / np.tan(theta / 2)
    if d >= length(A) or d >= length(B):
        raise ValueError("radius too large for these edges")
    A2, _ = split_at(A, s=length(A) - d)
    _, B2 = split_at(B, s=d)
    bis = _unit(ta + tb)
    center = P + bis * (radius / np.sin(theta / 2))
    mid = center - bis * radius
    out = list(edges)
    out[i] = (names[i], join(A2, arc_through(A2[-1], mid, B2[0])))
    out[j] = (names[j], B2)
    return out


def notch(edges, edge: str, at: float, depth=0.006):
    """A notch mark (for matching seams): returns (point, inward direction,
    depth); attach to a Panel's meta for DXF export."""
    e = dict(edges)[edge]
    return point_at(e, s=at), normal_at(e, s=at), depth


def grade(edges, sx=1.0, sy=1.0, anchor=(0, 0)):
    """Proportional grade: scale a piece about an anchor (centre front at the
    hem, typically) by sx across and sy up. Lengths along every edge scale
    consistently, so seams that matched still match."""
    o = _a(anchor)
    S = np.array([sx, sy])
    return [(n, (e - o) * S + o) for n, e in edges]
