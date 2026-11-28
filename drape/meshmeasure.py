"""Tailor's measurements taken on a triangle mesh (a Human).

A tape measure bridges hollows, so every girth is the perimeter of the convex
hull of the mesh's cross-section. Skin-weight regions keep the arms out of
torso girths (as when a tailor measures with the arms down).
"""
from __future__ import annotations

import numpy as np
from scipy.spatial import ConvexHull


def _slice(V, tris, p0, n):
    """Points where the plane (p0, n) cuts the triangles' edges."""
    d = (V - p0) @ n
    dt = d[tris]                                   # (m,3)
    pts = []
    for a, b in ((0, 1), (1, 2), (2, 0)):
        da, db = dt[:, a], dt[:, b]
        cross = (da * db) < 0
        if not cross.any():
            continue
        t = (da[cross] / (da[cross] - db[cross]))[:, None]
        A, B = V[tris[cross, a]], V[tris[cross, b]]
        pts.append(A + t * (B - A))
    return np.concatenate(pts) if pts else np.zeros((0, 3))


def _slice_segments(V, tris, y):
    """Horizontal cut at height y as 2-D segments (x, z), one per crossed triangle."""
    dt = V[tris][:, :, 1] - y
    segs = []
    for a, b, c in ((0, 1, 2), (1, 2, 0), (2, 0, 1)):
        # triangles where vertex a is alone on its side: the cut runs a-b to a-c
        alone = (np.sign(dt[:, a]) != np.sign(dt[:, b])) & (np.sign(dt[:, a]) != np.sign(dt[:, c]))
        if not alone.any():
            continue
        T = tris[alone]
        A, B, C = V[T[:, a]], V[T[:, b]], V[T[:, c]]
        da, db, dc = dt[alone, a][:, None], dt[alone, b][:, None], dt[alone, c][:, None]
        P = A + (da / (da - db)) * (B - A)
        Q = A + (da / (da - dc)) * (C - A)
        segs.append(np.stack([P[:, [0, 2]], Q[:, [0, 2]]], 1))
    return np.concatenate(segs) if segs else np.zeros((0, 2, 2))


def _inside_along_x(segs, xs, z):
    """Inside/outside of the cut polygon along the line z = const (ray cast in +z)."""
    p, q = segs[:, 0], segs[:, 1]
    inside = np.zeros(len(xs), bool)
    for i, x in enumerate(xs):
        straddle = (p[:, 0] > x) != (q[:, 0] > x)
        if not straddle.any():
            continue
        t = (x - p[straddle, 0]) / (q[straddle, 0] - p[straddle, 0])
        zc = p[straddle, 1] + t * (q[straddle, 1] - p[straddle, 1])
        inside[i] = (zc > z).sum() % 2 == 1
    return inside


def _hull_perimeter(P2):
    if len(P2) < 4:
        return 0.0
    try:
        return float(ConvexHull(P2).area)          # 2-D hull: .area is the perimeter
    except Exception:
        return 0.0


def horizontal_girth(V, tris, y, near=None, radius=None):
    pts = _slice(V, tris, np.array([0, y, 0.0]), np.array([0, 1.0, 0]))
    if near is not None:
        pts = pts[np.linalg.norm(pts[:, [0, 2]] - near, axis=1) < radius]
    return _hull_perimeter(pts[:, [0, 2]])


def limb_girth(V, tris, a, b, frac, radius):
    """Girth of a limb cut perpendicular to the bone a->b at fraction frac."""
    n = (b - a) / np.linalg.norm(b - a)
    c = a + (b - a) * frac
    pts = _slice(V, tris, c, n)
    pts = pts[np.linalg.norm(pts - c, axis=1) < radius]
    if len(pts) < 4:
        return 0.0
    u = np.cross(n, [0, 0, 1.0]);
    if np.linalg.norm(u) < 1e-6:
        u = np.cross(n, [1.0, 0, 0])
    u /= np.linalg.norm(u); v = np.cross(n, u)
    return _hull_perimeter(np.stack([(pts - c) @ u, (pts - c) @ v], 1))


class Tape:
    """All measurements of one Human. Heights of the girth lines are found
    from the girth profile, as a tailor would find them by eye."""

    def __init__(self, h, fast=False, armpit_drop=None):
        """fast: take the armpit as `armpit_drop` (m) below the shoulder joint
        instead of the geometric search (inside the fitting loop; saves ~0.4 s
        a call). The fitter measures the real drop once per fit, so fast and
        exact tapes agree."""
        self.h = h
        self.fast = fast
        self.armpit_drop = armpit_drop
        V = h.verts
        self.V = V
        self.torso = h.region_tris("torso")
        self.torso_legs = h.region_tris("torso", "leg")
        self.arms = h.region_tris("arm")
        self.legs = h.region_tris("leg")
        self.tris_all = h.tris
        self.side = "l" if h.joint("l-shoulder")[0] > 0 else "r"     # the +x side
        self.other = "r" if self.side == "l" else "l"

    # ---------------------------------------------------------- landmarks
    def shoulder_point(self, side=None):
        """Shoulder point (acromion tip): top surface of the shoulder, a little
        outside the shoulder-joint centre (the acromion overhangs the humeral
        head by ~1.5 cm)."""
        j = self.h.joint(f"{side or self.side}-shoulder").copy()
        j[0] += np.sign(j[0]) * 0.015 * self.h.height() / 1.7
        V = self.V
        near = np.linalg.norm(V[:, [0, 2]] - j[[0, 2]], axis=1) < 0.015
        return V[near][np.argmax(V[near, 1])]

    def armpit_y(self):
        """Armpit: the highest level at which there is air between the arm and
        the side of the chest. Walk down from the shoulder joint; at each level
        cut the body and look along x (at the joint's depth) for an
        inside -> outside -> inside pattern between the body centre and the
        arm. (Skin-weight boundaries sit up near the joint and gave an armhole
        5 cm too shallow.)"""
        j = self.h.joint(f"{self.side}-shoulder")
        e = self.h.joint(f"{self.side}-elbow")
        sgn = np.sign(j[0])
        for y in np.arange(j[1], j[1] - 0.25, -0.002):
            segs = _slice_segments(self.V, self.tris_all, y)
            if not len(segs):
                continue
            # x from the body centre out to the arm axis at this height
            t = (j[1] - y) / max(j[1] - e[1], 1e-6)
            x_arm = j[0] + t * (e[0] - j[0])
            xs = np.linspace(0.0, x_arm, 160)
            for zoff in (0.0, 0.01, -0.01):
                ins = _inside_along_x(segs, xs, j[2] + zoff)
                # inside at the centre, then a gap, then inside again (the arm)
                k = np.flatnonzero(np.diff(ins.astype(int)) != 0)
                if ins[0] and len(k) >= 2:
                    return float(y)
        return float(j[1] - 0.12)

    def crotch_y(self):
        return float(0.5 * (self.h.joint("l-upper-leg")[1] + self.h.joint("r-upper-leg")[1]) - 0.04 * self.h.height() / 1.7)

    # -------------------------------------------------------------- girths
    def profile(self, y0, y1, step=0.005, tris=None):
        ys = np.arange(y0, y1, step)
        T = self.torso if tris is None else tris
        return ys, np.array([horizontal_girth(self.V, T, y) for y in ys])

    def lines(self):
        """Heights (m) of the waist, chest, hip and underbust lines."""
        if hasattr(self, "_lines"):
            return self._lines
        cy = self.crotch_y()
        if self.fast:
            drop = self.armpit_drop if self.armpit_drop is not None else 0.075 * self.h.height() / 1.75
            ay = self.h.joint(f"{self.side}-shoulder")[1] - drop
        else:
            ay = self.armpit_y()
        ys, g = self.profile(cy + 0.02, ay - 0.005)
        span = ay - cy
        mid = (ys > cy + 0.30 * span) & (ys < cy + 0.80 * span)
        # the natural waist: the narrowest girth, but only near the waist's place on the skeleton (between
        # spine joints 2 and 3; nearer 3 for men). Without that, a body with a belly has no narrow point
        # there and the tape slid up under the bust or down to the hip bones, where the waist doesn't grow.
        wide = bool(getattr(getattr(self.h, "shape", None), "wide_tape", False))
        try:
            if not wide:          # bodies in MakeHuman's range are measured as they always were
                raise KeyError
            s2, s3 = self.h.joint("spine-2")[1], self.h.joint("spine-3")[1]
            sx = float(getattr(self.h.shape, "sex", 0.0))
            anchor = s2 - (0.25 + 0.8 * sx) * (s2 - s3)
            near = mid & (np.abs(ys - anchor) < 0.02 * self.h.height())
            if near.sum() >= 3:
                mid = near
        except (KeyError, AttributeError):
            pass
        waist = ys[mid][np.argmin(g[mid])]
        # a body given a belly (human._widen) is measured round the middle at the belly's level, where
        # someone with a belly puts the tape (there's no narrow point to find there)
        wd = getattr(getattr(self.h, "shape", None), "widen", None)
        if wd and wd.get("belly", 0) > 0 and "waist_y" in wd:
            waist = float(wd["waist_y"] * self.h.height())
        up = ys > waist + 0.04
        # the chest at bust level: near the armpits (within 5% of height), so a belly fuller than the
        # bust isn't read as the chest
        near_bust = up & (ys > ay - 0.05 * self.h.height())
        if wide and near_bust.sum() >= 3:
            up = near_bust
        chest = ys[up][np.argmax(g[up])]
        # hip line: level of the fullest part of the seat = where the buttocks
        # protrude furthest back (a 'max girth' rule picks the crotch, where
        # the hull wraps both thighs)
        ys2 = np.arange(cy + 0.01, waist - 0.03, 0.005)
        back = []
        for y in ys2:
            P = _slice(self.V, self.torso_legs, np.array([0, y, 0.0]), np.array([0, 1.0, 0]))
            back.append(P[:, 2].min() if len(P) else np.inf)
        hip = ys2[int(np.argmin(back))]
        # underbust: the narrowest point between waist and chest, just under the chest
        ub = (ys > chest - 0.12) & (ys < chest - 0.02)
        under = ys[ub][np.argmin(g[ub])] if ub.any() else chest - 0.07
        self._lines = dict(waist=float(waist), chest=float(chest), hip=float(hip), underbust=float(under),
                           armpit=float(ay), crotch=float(cy))
        return self._lines

    def chest(self):
        return horizontal_girth(self.V, self.torso, self.lines()["chest"])

    def underbust(self):
        return horizontal_girth(self.V, self.torso, self.lines()["underbust"])

    def waist(self):
        return horizontal_girth(self.V, self.torso, self.lines()["waist"])

    def hip(self):
        return horizontal_girth(self.V, self.torso_legs, self.lines()["hip"])

    def neck(self):
        nb = self.h.joint("neck")
        y = nb[1] + 0.025 * self.h.height() / 1.7
        T = self.h.region_tris("torso", "head", thresh=0.3)
        return horizontal_girth(self.V, T, y, near=nb[[0, 2]], radius=0.10)

    def upper_arm(self):
        a, b = self.h.joint(f"{self.side}-shoulder"), self.h.joint(f"{self.side}-elbow")
        return max(limb_girth(self.V, self.arms, a, b, f, 0.09) for f in np.linspace(0.3, 0.6, 7))

    def thigh(self):
        a, b = self.h.joint(f"{self.side}-upper-leg"), self.h.joint(f"{self.side}-knee")
        return max(limb_girth(self.V, self.legs, a, b, f, 0.14) for f in np.linspace(0.12, 0.3, 7))

    def knee(self):
        a, b = self.h.joint(f"{self.side}-knee"), self.h.joint(f"{self.side}-ankle")
        return limb_girth(self.V, self.legs, a, b, 0.05, 0.10)

    def ankle(self):
        a, b = self.h.joint(f"{self.side}-knee"), self.h.joint(f"{self.side}-ankle")
        return limb_girth(self.V, self.legs, a, b, 0.88, 0.08)

    def crotch_height(self):
        """Floor to crotch (the inseam of a trouser that reaches the floor):
        lowest point of the torso between the legs."""
        V, w = self.V, self.h.regions["torso"]
        sel = (np.abs(V[:, 0]) < 0.02) & (V[:, 1] < self.h.joint("pelvis")[1])
        return float(V[sel, 1].min()) if sel.any() else self.crotch_y()

    def shoulder_path(self):
        """Shoulder tip to shoulder tip across the back, as a tape lies: along
        the convex hull of the cross-section 1.5 cm below the shoulder points,
        rising 1.5 cm at each end (at the back of each shoulder tip). The
        drawn guide and the measurement are this same polyline."""
        A, B = self.shoulder_point(self.side), self.shoulder_point(self.other)
        top = 0.5 * (A[1] + B[1])
        y = top - 0.015
        P = _slice(self.V, self.tris_all, np.array([0, y, 0.0]), np.array([0, 1.0, 0]))[:, [0, 2]]
        xa, xb = sorted((A[0], B[0]))
        P = P[(P[:, 0] >= xa - 0.02) & (P[:, 0] <= xb + 0.02)]
        hull = P[ConvexHull(P).vertices]
        back = hull[hull[:, 1] <= hull[:, 1].mean()]
        back = back[np.argsort(back[:, 0])]
        za, zb = np.interp(xa, back[:, 0], back[:, 1]), np.interp(xb, back[:, 0], back[:, 1])
        back = back[(back[:, 0] > xa) & (back[:, 0] < xb)]
        mid = np.stack([back[:, 0], np.full(len(back), y), back[:, 1]], 1)
        return np.vstack([[xa, top, za], [xa, y, za], mid, [xb, y, zb], [xb, top, zb]])

    def shoulder_width(self):
        P = self.shoulder_path()
        return float(np.linalg.norm(np.diff(P, axis=0), axis=1).sum())

    def _surface_toward(self, p, d, r):
        near = np.linalg.norm(self.V - p, axis=1) < r
        Q = self.V[near]
        return Q[np.argmax((Q - p) @ d)] if len(Q) else p

    def arm_path(self):
        """Shoulder tip -> outside of the elbow -> outside of the wrist: over
        the skin, as a tape goes (joint centres sit inside the arm and read
        ~2.5 cm short)."""
        sp = self.shoulder_point()
        e, w = self.h.joint(f"{self.side}-elbow"), self.h.joint(f"{self.side}-hand")
        out = np.array([np.sign(e[0]), 0.0, 0.0])
        return np.vstack([sp, self._surface_toward(e, out, 0.045), self._surface_toward(w, out, 0.035)])

    def arm_length(self):
        P = self.arm_path()
        return float(np.linalg.norm(np.diff(P, axis=0), axis=1).sum())

    def hand_length(self):
        w = self.h.joint(f"{self.side}-hand")
        sel = (self.h.regions["hand"] > 0.5) & (np.sign(self.V[:, 0]) == np.sign(w[0]))
        return float(np.linalg.norm(self.V[sel] - w, axis=1).max())

    def _hand_frame(self):
        """Wrist o, d toward the fingers, f across toward the index, n out of the back."""
        h, sd = self.h, self.side
        o = np.asarray(h.joint(f"{sd}-hand"), float)
        mcp = np.array([h.joint(f"{sd}-finger-{k}-1") for k in (2, 3, 4, 5)], float)
        d = mcp.mean(0) - o
        d /= np.linalg.norm(d)
        f = mcp[0] - mcp[3]
        f -= (f @ d) * d
        f /= np.linalg.norm(f)
        n = np.cross(f, d)
        if (np.asarray(h.joint(f"{sd}-finger-1-4")) - o) @ n > 0:
            n = -n
        return o, d, f, n, mcp

    def hand_girth_loop(self):
        """Around the widest part of the hand just below the knuckles, thumb not
        included (how glove sizes are measured): (loop points, girth in m).
        Exact cross-sections of the hand's triangles, not a slab of vertices
        (the hand mesh is coarse along its length)."""
        o, d, f, n, mcp = self._hand_frame()
        tri = self.h.region_tris("hand")
        tri = tri[np.sign(self.V[tri].mean(1)[:, 0]) == np.sign(o[0])]
        vk = float(((mcp - o) @ d).min())
        best = None
        for fr in np.linspace(0.8, 1.0, 9):
            P = _plane_section(self.V, tri, o + fr * vk * d, d) - o
            if len(P) < 6:
                continue
            P = P[~(((P @ f) > 0.03) & ((P @ n) < -0.01))]          # the thumb left out
            P2 = np.c_[P @ f, P @ n]
            hull = ConvexHull(P2)
            if best is None or hull.area > best[1]:
                L2 = P2[hull.vertices]
                best = (o + fr * vk * d + L2[:, :1] * f + L2[:, 1:] * n, float(hull.area))
        return best

    def hand_girth(self):
        return self.hand_girth_loop()[1]

    def foot_path(self):
        """Back of the heel to the tip of the longest toe, along the floor
        (follows the foot's toe-out; the z extent alone read short)."""
        sel = (self.h.regions["foot"] > 0.5) & (self.V[:, 0] > 0)
        F = self.V[sel]
        heel, toe = F[np.argmin(F[:, 2])], F[np.argmax(F[:, 2])]
        return np.array([[heel[0], 0.004, heel[2]], [toe[0], 0.004, toe[2]]])

    def foot_length(self):
        P = self.foot_path()
        return float(np.linalg.norm(P[1] - P[0]))

    def foot_breadth(self):
        sel = (self.h.regions["foot"] > 0.5) & (self.V[:, 0] > 0)
        return float(np.ptp(self.V[sel, 0]))

    def all(self) -> dict:
        """Everything, in cm."""
        out = dict(height=self.h.height(), chest=self.chest(), underbust=self.underbust(), waist=self.waist(),
                   hip=self.hip(), shoulder_width=self.shoulder_width(), neck=self.neck(),
                   upper_arm=self.upper_arm(), arm_length=self.arm_length(), thigh=self.thigh(),
                   hand_length=self.hand_length(), foot_length=self.foot_length(),
                   foot_breadth=self.foot_breadth(), inseam=self.crotch_height(), hand_girth=self.hand_girth())
        return {k: v * 100 for k, v in out.items()}


# ------------------------------------------------------------ tape paths --
# The exact lines the tape follows, for drawing measurement guides.
def _hull_loop_xz(P, y):
    """Ordered convex-hull loop (closed) of slice points, lifted back to 3-D."""
    if len(P) < 4:
        return np.zeros((0, 3))
    H = ConvexHull(P[:, [0, 2]])
    q = P[H.vertices][:, [0, 2]]
    loop = np.stack([q[:, 0], np.full(len(q), y), q[:, 1]], 1)
    return np.vstack([loop, loop[:1]])


def _limb_loop(V, tris, a, b, frac, radius):
    n = (b - a) / np.linalg.norm(b - a)
    c = a + (b - a) * frac
    pts = _slice(V, tris, c, n)
    pts = pts[np.linalg.norm(pts - c, axis=1) < radius]
    if len(pts) < 4:
        return np.zeros((0, 3)), 0.0
    u = np.cross(n, [0, 0, 1.0]); u /= np.linalg.norm(u); v = np.cross(n, u)
    P2 = np.stack([(pts - c) @ u, (pts - c) @ v], 1)
    H = ConvexHull(P2)
    q = P2[H.vertices]
    loop = c + q[:, :1] * u + q[:, 1:] * v
    return np.vstack([loop, loop[:1]]), float(H.area)


def _start_at(loop, key):
    """Rotate a closed loop so it starts at the point maximising key (where a
    tailor starts the tape: centre front for girths, outside of a limb)."""
    open_ = loop[:-1]
    i = int(np.argmax(key(open_)))
    r = np.vstack([open_[i:], open_[:i]])
    return np.vstack([r, r[:1]])


def _plane_section(V, tris, p0, nrm):
    """Points where the triangles cross the plane through p0 with normal nrm."""
    sd = (V - p0) @ nrm
    out = []
    for a, b in ((0, 1), (1, 2), (2, 0)):
        ia, ib = tris[:, a], tris[:, b]
        da, db = sd[ia], sd[ib]
        x = (da * db) < 0
        t = (da[x] / (da[x] - db[x]))[:, None]
        out.append(V[ia[x]] + t * (V[ib[x]] - V[ia[x]]))
    return np.vstack(out) if out else np.zeros((0, 3))


def tape_paths(T: "Tape") -> list[dict]:
    """Every measurement as a drawable path: name, kind ('loop'/'path'),
    pts (N,3), value_cm, start, end, and where to read it."""
    h, V = T.h, T.V
    out = []
    L = T.lines()

    def girth(name, y, tris, near=None, radius=None, label=None):
        P = _slice(V, tris, np.array([0, y, 0.0]), np.array([0, 1.0, 0]))
        if near is not None:
            P = P[np.linalg.norm(P[:, [0, 2]] - near, axis=1) < radius]
        loop = _start_at(_hull_loop_xz(P, y), lambda q: q[:, 2] - 3 * np.abs(q[:, 0]))
        if len(loop) < 4:
            return
        value = float(np.linalg.norm(np.diff(loop, axis=0), axis=1).sum())
        out.append(dict(name=name, kind="loop", pts=loop, value_cm=value * 100, start=loop[0], end=loop[0],
                        how=label))

    girth("chest", L["chest"], T.torso, label="around the fullest part of the chest, under the arms, level")
    girth("underbust", L["underbust"], T.torso, label="directly under the bust")
    girth("waist", L["waist"], T.torso, label="around the narrowest part of the torso")
    girth("hip", L["hip"], T.torso_legs, label="around the fullest part of the seat, feet together")
    nb = h.joint("neck")
    girth("neck", nb[1] + 0.025 * h.height() / 1.7, h.region_tris("torso", "head", thresh=0.3),
          near=nb[[0, 2]], radius=0.10, label="around the base of the neck")

    # limbs: the fullest cut perpendicular to the bone (same search as the tape)
    for name, a_j, b_j, tris, fr, rad, how in (
            ("upper_arm", "shoulder", "elbow", T.arms, np.linspace(0.3, 0.6, 7), 0.09, "around the fullest part of the upper arm"),
            ("thigh", "upper-leg", "knee", T.legs, np.linspace(0.12, 0.3, 7), 0.14, "around the fullest part of the thigh")):
        a, b = h.joint(f"{T.side}-{a_j}"), h.joint(f"{T.side}-{b_j}")
        best = max((_limb_loop(V, tris, a, b, f, rad) for f in fr), key=lambda t: t[1])
        loop = _start_at(best[0], lambda q: q[:, 0] * np.sign(a[0]))
        if len(loop) >= 4:
            out.append(dict(name=name, kind="loop", pts=loop, value_cm=best[1] * 100,
                            start=loop[0], end=loop[0], how=how))

    path = T.shoulder_path()
    out.append(dict(name="shoulder_width", kind="path", pts=path, value_cm=T.shoulder_width() * 100,
                    start=path[0], end=path[-1], how="shoulder tip to shoulder tip, across the back"))
    arm = T.arm_path()
    out.append(dict(name="arm_length", kind="path", pts=arm, value_cm=T.arm_length() * 100,
                    start=arm[0], end=arm[-1], how="shoulder tip, over the outside of the elbow, to the wrist bone"))
    w = h.joint(f"{T.side}-hand")

    # height: floor to crown, drawn beside the body
    top = V[np.argmax(V[:, 1])]
    xh = V[:, 0].min() - 0.06
    hp = np.array([[xh, 0.0, top[2]], [xh, top[1], top[2]]])
    out.append(dict(name="height", kind="path", pts=hp, value_cm=h.height() * 100, start=hp[0], end=hp[1],
                    how="floor to the top of the head, barefoot", beside=True))

    # inseam: crotch to floor, down the inside of the leg
    cy = T.crotch_height()
    sgn = np.sign(h.joint(f"{T.side}-knee")[0])
    legv = V[(h.regions["leg"] > 0.5) & (np.sign(V[:, 0]) == sgn)]
    ins = [[0.0, cy, float(np.median(legv[np.abs(legv[:, 1] - cy) < 0.03, 2])) if len(legv) else 0.0]]
    for y in np.linspace(cy - 0.03, 0.06, 14):      # down the inside of the leg
        band = legv[np.abs(legv[:, 1] - y) < 0.01]
        if len(band):       # the inner side of the leg, at the leg's middle front-to-back
            ins.append([float(np.percentile(np.abs(band[:, 0]), 3)) * sgn, y, float(np.median(band[:, 2]))])
    ins = np.array(ins)
    if len(ins) > 4:        # smooth out mesh steps
        k = np.ones(3) / 3
        for c in (0, 2):
            ins[1:-1, c] = np.convolve(ins[:, c], k, mode="same")[1:-1]
    ins = np.vstack([ins, [ins[-1, 0], 0.0, ins[-1, 2]]])
    out.append(dict(name="inseam", kind="path", pts=ins, value_cm=cy * 100, start=ins[0], end=ins[1],
                    how="crotch to the floor, down the inside of the leg, barefoot"))

    # hand and foot length
    sel = (h.regions["hand"] > 0.5) & (np.sign(V[:, 0]) == np.sign(w[0]))
    tip = V[sel][np.argmax(np.linalg.norm(V[sel] - w, axis=1))]
    out.append(dict(name="hand_length", kind="path", pts=np.vstack([w, tip]), value_cm=T.hand_length() * 100,
                    start=w, end=tip, how="wrist crease to the tip of the middle finger"))
    hg, hv = T.hand_girth_loop()
    out.append(dict(name="hand_girth", kind="loop", pts=hg, value_cm=hv * 100, start=hg[0], end=hg[0],
                    how="around the knuckles, thumb not included"))
    fp = T.foot_path()
    out.append(dict(name="foot_length", kind="path", pts=fp, value_cm=T.foot_length() * 100,
                    start=fp[0], end=fp[1], how="back of the heel to the longest toe, standing"))
    return out
