"""Avatar as a signed distance field (SDF), built from elliptical torso
sections + capsules joined with a smooth minimum. Everything is numba-jitted
so the solver can query it per particle per substep.

Body arrays:
  torso: (k,4) rows of [y, rx, rz, cz] -- elliptical cross-sections along the
         spine, linearly interpolated between rows (y ascending).
  caps:  (c,7) rows of [ax, ay, az, bx, by, bz, r] capsules (arms, neck, legs, head).
"""
from __future__ import annotations

import numpy as np
from ._jit import njit


@njit(cache=True)
def _smin(a, b, k):
    h = max(k - abs(a - b), 0.0) / k
    return min(a, b) - h * h * k * 0.25


@njit(cache=True)
def _capsule(px, py, pz, c):
    ax, ay, az, bx, by, bz, r = c[0], c[1], c[2], c[3], c[4], c[5], c[6]
    pax, pay, paz = px - ax, py - ay, pz - az
    bax, bay, baz = bx - ax, by - ay, bz - az
    bb = bax * bax + bay * bay + baz * baz
    t = (pax * bax + pay * bay + paz * baz) / bb if bb > 0.0 else 0.0  # a == b -> sphere
    t = min(max(t, 0.0), 1.0)
    dx, dy, dz = pax - bax * t, pay - bay * t, paz - baz * t
    return np.sqrt(dx * dx + dy * dy + dz * dz) - r


@njit(cache=True)
def _cr(p0, p1, p2, p3, t):
    t2 = t * t; t3 = t2 * t
    return 0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3)


@njit(cache=True)
def _torso(px, py, pz, torso):
    n = torso.shape[0]
    y0, y1 = torso[0, 0], torso[n - 1, 0]
    yc = min(max(py, y0), y1)
    # find the section interval containing yc
    i = 0
    while i < n - 2 and torso[i + 1, 0] < yc:
        i += 1
    t = (yc - torso[i, 0]) / (torso[i + 1, 0] - torso[i, 0])
    # Catmull-Rom through the sections: smooth (C1) torso, no shading bands
    i0 = max(i - 1, 0); i3 = min(i + 2, n - 1)
    rx = _cr(torso[i0, 1], torso[i, 1], torso[i + 1, 1], torso[i3, 1], t)
    rz = _cr(torso[i0, 2], torso[i, 2], torso[i + 1, 2], torso[i3, 2], t)
    cz = _cr(torso[i0, 3], torso[i, 3], torso[i + 1, 3], torso[i3, 3], t)
    # approximate distance to the ellipse in this horizontal slice
    ex, ez = px / rx, (pz - cz) / rz
    q = np.sqrt(ex * ex + ez * ez)
    dr = (q - 1.0) * min(rx, rz) if q < 1.0 else (q - 1.0) / np.sqrt((ex / rx) ** 2 + (ez / rz) ** 2) * q
    dy = py - yc  # beyond the end caps
    if dy == 0.0:
        return dr
    if dr < 0.0:
        return abs(dy) if abs(dy) > -dr else dr
    return np.sqrt(dr * dr + dy * dy)


# ---------------------------------------------------------- extremities ----
# Extra primitives (hands, feet) with their own blend radius, so fingers stay
# fingers instead of melting into a mitten. Row layout (EXTRA_COLS floats):
#   [type, k, ...16 params]
#   type 0 capsule:     a(3) b(3) r
#   type 1 rounded box: centre(3) axes as rows u(3) v(3) w(3) half-extents(3) rounding r
#   type 2 round cone:  a(3) b(3) r_a r_b   (tapered capsule: forearm->wrist, shin->ankle)
#   type 3 flat cone:   a(3) b(3) r_a r_b sy  (round cone squashed vertically: feet)
# Groups (one per hand/foot) carry a bounding sphere so far-away points skip
# all of a group's primitives with one distance test.
#   group row: [cx, cy, cz, radius, first_row, end_row]
EXTRA_COLS = 18


@njit(cache=True)
def _rbox(px, py, pz, e):
    dx, dy, dz = px - e[2], py - e[3], pz - e[4]
    qu = abs(dx * e[5] + dy * e[6] + dz * e[7]) - (e[14] - e[17])
    qv = abs(dx * e[8] + dy * e[9] + dz * e[10]) - (e[15] - e[17])
    qw = abs(dx * e[11] + dy * e[12] + dz * e[13]) - (e[16] - e[17])
    ou, ov, ow = max(qu, 0.0), max(qv, 0.0), max(qw, 0.0)
    return np.sqrt(ou * ou + ov * ov + ow * ow) + min(max(qu, max(qv, qw)), 0.0) - e[17]


@njit(cache=True)
def _round_cone(px, py, pz, e):
    """Capsule whose radius tapers from r1 at a to r2 at b (Quilez)."""
    ax, ay, az, bx, by, bz, r1, r2 = e[2], e[3], e[4], e[5], e[6], e[7], e[8], e[9]
    bax, bay, baz = bx - ax, by - ay, bz - az
    l2 = bax * bax + bay * bay + baz * baz
    rr = r1 - r2
    a2 = l2 - rr * rr
    il2 = 1.0 / l2
    pax, pay, paz = px - ax, py - ay, pz - az
    y = pax * bax + pay * bay + paz * baz
    z = y - l2
    qx, qy, qz = pax * l2 - bax * y, pay * l2 - bay * y, paz * l2 - baz * y
    x2 = qx * qx + qy * qy + qz * qz
    y2 = y * y * l2
    z2 = z * z * l2
    k = np.sign(rr) * rr * rr * x2
    if np.sign(z) * a2 * z2 > k:
        return np.sqrt(x2 + z2) * il2 - r2
    if np.sign(y) * a2 * y2 < k:
        return np.sqrt(x2 + y2) * il2 - r1
    return (np.sqrt(x2 * a2 * il2) + y * rr) * il2 - r1


@njit(cache=True)
def _flat_cone(px, py, pz, e):
    """Round cone squashed vertically by e[10] (height/width) around a's height:
    a foot-shaped taper. Distances are scaled back conservatively."""
    sy = e[10]
    ay = e[3]
    f = np.empty(EXTRA_COLS)
    f[:] = e[:]
    f[6] = ay + (e[6] - ay) / sy
    return _round_cone(px, ay + (py - ay) / sy, pz, f) * sy


@njit(cache=True)
def _extra(px, py, pz, e):
    if e[0] == 3.0:
        return _flat_cone(px, py, pz, e)
    if e[0] == 0.0:
        return _capsule(px, py, pz, e[2:9])
    if e[0] == 2.0:
        return _round_cone(px, py, pz, e)
    return _rbox(px, py, pz, e)


@njit(cache=True)
def sdf(px, py, pz, torso, caps, k, extras, groups):
    d = _torso(px, py, pz, torso)
    for i in range(caps.shape[0]):
        d = _smin(d, _capsule(px, py, pz, caps[i]), k)
    for g in range(groups.shape[0]):
        dx, dy, dz = px - groups[g, 0], py - groups[g, 1], pz - groups[g, 2]
        lb = np.sqrt(dx * dx + dy * dy + dz * dz) - groups[g, 3]
        if lb > d + k:
            continue  # nothing in this group can be closer than what we have
        for i in range(int(groups[g, 4]), int(groups[g, 5])):
            d = _smin(d, _extra(px, py, pz, extras[i]), extras[i, 1])
    return d


@njit(cache=True)
def sdf_grad(px, py, pz, torso, caps, k, extras, groups):
    e = 1e-4
    gx = sdf(px + e, py, pz, torso, caps, k, extras, groups) - sdf(px - e, py, pz, torso, caps, k, extras, groups)
    gy = sdf(px, py + e, pz, torso, caps, k, extras, groups) - sdf(px, py - e, pz, torso, caps, k, extras, groups)
    gz = sdf(px, py, pz + e, torso, caps, k, extras, groups) - sdf(px, py, pz - e, torso, caps, k, extras, groups)
    n = np.sqrt(gx * gx + gy * gy + gz * gz) + 1e-12
    return gx / n, gy / n, gz / n


@njit(cache=True)
def sdf_batch(p, torso, caps, k, extras, groups):
    out = np.empty(p.shape[0])
    for i in range(p.shape[0]):
        out[i] = sdf(p[i, 0], p[i, 1], p[i, 2], torso, caps, k, extras, groups)
    return out


def _empty_extras():
    return np.zeros((0, EXTRA_COLS)), np.zeros((0, 6))


class Body:
    def __init__(self, torso: np.ndarray, caps: np.ndarray, blend: float = 0.03,
                 extras: np.ndarray | None = None, groups: np.ndarray | None = None):
        self.torso = np.ascontiguousarray(torso, dtype=np.float64)
        self.caps = np.ascontiguousarray(np.reshape(caps, (-1, 7)), dtype=np.float64)
        self.blend = float(blend)
        e0, g0 = _empty_extras()
        self.extras = np.ascontiguousarray(e0 if extras is None else extras, dtype=np.float64)
        self.groups = np.ascontiguousarray(g0 if groups is None else groups, dtype=np.float64)

    def sdf(self, p: np.ndarray) -> np.ndarray:
        p = np.ascontiguousarray(np.atleast_2d(p), dtype=np.float64)
        return sdf_batch(p, self.torso, self.caps, self.blend, self.extras, self.groups)

    def torso_only(self) -> "Body":
        """The tape-measure body: torso without limbs."""
        return Body(self.torso, np.zeros((0, 7)), self.blend)

    # ---- interface shared with meshbody.MeshBody -----------------------
    kind = "analytic"

    def shoulder_top_y(self) -> float:
        return float(self.caps[0][1] + self.caps[0][6])

    def arm_axis(self, side=+1):
        c = self.caps[1].copy()
        if side < 0:
            c[0] *= -1; c[3] *= -1
        return c[:3], c[3:6], float(c[6])

    def armpit_depth(self) -> float:
        from .measurements import armpit_depth
        return armpit_depth(self)

    def tape_girth(self, name: str) -> float:
        from .measurements import girth_at
        return girth_at(self.torso_only(), self.section_y(name))

    def girth_at_y(self, y: float) -> float:
        from .measurements import girth_at
        return girth_at(self.torso_only(), y)

    def neck_girth(self) -> float:
        return float(2 * np.pi * self.caps[5][6])

    def upper_arm_girth(self) -> float:
        return float(2 * np.pi * self.caps[1][6])

    def torso_wrap_radius(self) -> float:
        t = self.torso
        return float(max(t[:, 1].max(), t[:, 2].max() + np.abs(t[:, 3]).max())) + 0.035

    def mesh(self, **kw):
        from .render import body_mesh
        return body_mesh(self, **kw)

    def section_y(self, name: str) -> float:
        """Height of a named torso section (waist, chest, seat, ...). Each body
        carries its own section list (bug fixed: code assumed the measured
        avatar's layout, which has an extra 'crotch' row, so on the default
        mannequin every lookup was one section off)."""
        names = getattr(self, "section_names", None)
        if names is None or len(names) != len(self.torso):
            raise ValueError("this body has no named torso sections")
        return float(self.torso[names.index(name), 0])

    @staticmethod
    def default(chest_cm: float = 96.0, height_scale: float = 1.0) -> "Body":
        """A simple A-pose mannequin (~175 cm). Chest girth sets torso width."""
        s = chest_cm / 96.0
        torso = np.array([
            # y,    rx,          rz,          cz
            [0.86, 0.165 * s, 0.105 * s, -0.005],   # hip/seat
            [0.96, 0.170 * s, 0.110 * s, 0.000],    # high hip
            [1.06, 0.140 * s, 0.090 * s, 0.000],    # waist
            [1.20, 0.155 * s, 0.100 * s, 0.010],    # underbust
            [1.30, 0.165 * s, 0.110 * s, 0.015],    # chest
            [1.40, 0.160 * s, 0.095 * s, 0.000],    # upper chest
            [1.46, 0.120 * s, 0.070 * s, -0.005],   # shoulder top/yoke
        ])
        torso[:, 0] *= height_scale
        sh = 1.43 * height_scale
        caps = np.array([
            # shoulder bar (rounds the deltoids)
            [-0.17 * s, sh, 0.0, 0.17 * s, sh, 0.0, 0.055],
            # upper arms, A-pose (~40 deg from vertical)
            [0.18 * s, sh - 0.01, 0.0, 0.36 * s, sh - 0.25, 0.0, 0.045],
            [-0.18 * s, sh - 0.01, 0.0, -0.36 * s, sh - 0.25, 0.0, 0.045],
            # forearms
            [0.36 * s, sh - 0.25, 0.0, 0.50 * s, sh - 0.48, 0.03, 0.035],
            [-0.36 * s, sh - 0.25, 0.0, -0.50 * s, sh - 0.48, 0.03, 0.035],
            # neck + head
            [0.0, 1.44 * height_scale, -0.01, 0.0, 1.58 * height_scale, 0.0, 0.055],
            [0.0, 1.64 * height_scale, 0.01, 0.0, 1.66 * height_scale, 0.01, 0.095],
            # legs
            [0.09, 0.86, 0.0, 0.10, 0.48, 0.0, 0.075],
            [-0.09, 0.86, 0.0, -0.10, 0.48, 0.0, 0.075],
            [0.10, 0.48, 0.0, 0.10, 0.08, -0.01, 0.050],
            [-0.10, 0.48, 0.0, -0.10, 0.08, -0.01, 0.050],
        ])
        b = Body(torso, caps, blend=0.035)
        b.section_names = ["seat", "high_hip", "waist", "underbust", "chest", "upper_chest", "yoke"]
        from .extremities import attach_extremities
        attach_extremities(b, height=1.755 * height_scale)
        return b
