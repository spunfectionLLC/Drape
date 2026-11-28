"""Realistic human avatar from the MakeHuman base mesh and shape targets
(CC0, via MPFB2; see data/MAKEHUMAN_LICENSE_CC0.md).

Shape = base mesh + weighted morph targets, combined the way MakeHuman does:
  macros   sex (0 = female .. 1 = male), muscle, weight (0..1, 0.5 = average),
           height (0..1), breast cup size and firmness (female), ethnicity mix
  measure  targets that change one measurement in an anatomically shaped way
           (bust, underbust, waist, hips, shoulders, neck, upper arm, thigh...),
           each in -1..1
These targets were sculpted by artists on real anatomy, so a body that gets
bigger gains it where people do (belly, hips, upper arms, under the chin),
instead of every girth swelling like a tube.

Mesh is in metres, y up, facing +z, standing in the A-pose the base mesh ships
in (arms ~35 deg from vertical).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

DATA = Path(__file__).parent / "data" / "makehuman.npz"
N_BODY = 13380   # the 'body' group; vertices after it are helpers / joint cubes


@lru_cache(maxsize=1)
def _data():
    z = np.load(DATA)
    targets = {}
    for k in z.files:
        if k.startswith("t_idx/"):
            name = k[len("t_idx/"):]
            targets[name] = (z[k].astype(np.int64), z["t_d/" + name].astype(np.float64))
    joints = {k[len("joint/"):]: z[k] for k in z.files if k.startswith("joint/")}
    regions = {k[len("region/"):]: z[k].astype(np.float64) for k in z.files if k.startswith("region/")}
    return z["V"].astype(np.float64), z["tris"], targets, joints, regions


def _three(v):
    """MakeHuman's min/average/max interpolation for a 0..1 slider. Values
    past the ends extrapolate the end target (used sparingly by the fitter
    for bodies beyond MakeHuman's range, e.g. a 100+ cm male waist)."""
    if v < 0.5:
        return {"min": 1 - v / 0.5, "average": v / 0.5, "max": 0.0}
    return {"min": 0.0, "average": 1 - (v - 0.5) / 0.5, "max": (v - 0.5) / 0.5}


MEASURE_TARGETS = ["measure-bust-circ", "measure-underbust-circ", "measure-waist-circ", "measure-hips-circ",
                   "measure-shoulder-dist", "measure-napetowaist-dist", "measure-waisttohip-dist",
                   "measure-frontchest-dist", "measure-neck-circ", "measure-neck-height",
                   "measure-upperarm-circ", "measure-upperarm-length", "measure-lowerarm-length",
                   "measure-thigh-circ", "measure-calf-circ", "measure-upperleg-height",
                   "measure-lowerleg-height", "buttocks-volume", "stomach-pregnant"]


@dataclass
class Shape:
    sex: float = 0.0            # 0 female .. 1 male
    muscle: float = 0.5
    weight: float = 0.5
    height: float = 0.5         # MakeHuman height slider (proportions of tall/short people)
    cup: float = 0.5            # breast size (female)
    firmness: float = 0.5
    ethnicity: tuple = (1 / 3, 1 / 3, 1 / 3)   # african, asian, caucasian
    measure: dict = field(default_factory=dict)  # MEASURE_TARGETS name -> -1..1
    smooth_chest: bool = True   # dress-form style: flatten nipple detail (MakeHuman nipple targets)
    scale: float = 1.0          # uniform scale applied last (exact height)
    hand_scale: float = 1.0
    hand_width: float = 1.0     # across and through the hand (girth), about the hand's own axis
    foot_scale: float = 1.0
    widen: dict | None = None   # girths past MakeHuman's range: see _widen (set by fit_human)
    wide_tape: bool = False     # measured the way bodies past MakeHuman's range are (meshmeasure.Tape.lines)


def build_vertices(s: Shape) -> np.ndarray:
    V0, _, T, _, regions = _data()
    V = V0.copy()

    def add(name, w):
        if abs(w) < 1e-9 or name not in T or len(T[name][0]) == 0:  # neutral targets are empty
            return
        i, d = T[name]
        V[i] += w * d

    sexes = {"female": 1 - s.sex, "male": s.sex}
    mus, wts = _three(s.muscle), _three(s.weight)
    for g, gw in sexes.items():
        if gw <= 0:
            continue
        for m, mw in mus.items():
            for w, ww in wts.items():
                base = gw * mw * ww
                if base <= 0:
                    continue
                add(f"universal-{g}-young-{m}muscle-{w}weight", base)
                if s.height < 0.5:
                    add(f"{g}-young-{m}muscle-{w}weight-minheight", base * (0.5 - s.height) * 2)
                elif s.height > 0.5:
                    add(f"{g}-young-{m}muscle-{w}weight-maxheight", base * (s.height - 0.5) * 2)
                if g == "female":
                    cups, firms = _three(s.cup), _three(s.firmness)
                    for c, cw in cups.items():
                        for f, fw in firms.items():
                            if c == "average" and f == "average":
                                continue
                            add(f"female-young-{m}muscle-{w}weight-{c}cup-{f}firmness", base * cw * fw)
        for race, rw in zip(("african", "asian", "caucasian"), s.ethnicity):
            add(f"{race}-{g}-young", gw * rw)
    if s.smooth_chest:
        add("nipple-point-decr", 1.0)
        add("nipple-size-decr", 1.0)
    for name, v in s.measure.items():
        if v < 0:
            add(f"{name}-decr", -v)
        elif v > 0:
            add(f"{name}-incr", v)

    # hands / feet: scale about wrist / ankle, blended by skin weight
    if abs(s.hand_scale - 1) > 1e-9 or abs(s.foot_scale - 1) > 1e-9 or abs(s.hand_width - 1) > 1e-9:
        V = _scale_extremities(V, s.hand_scale, s.foot_scale, regions, s.hand_width)
    # stand on the floor, centred, then scale to the exact height
    floor = V[:N_BODY, 1].min()
    V[:, 1] -= floor
    V[:, 0] -= V[:N_BODY, 0].mean()
    torso = regions["torso"] > 0.5
    V[:, 2] -= np.median(V[:N_BODY][torso, 2])   # garments wrap around the z = 0 axis
    if s.widen:
        V = _widen(V, s.widen, regions)
    return V * s.scale


# ------------------------------------------------------- past MakeHuman's range --
# MakeHuman's sculpted shapes reach most bodies' chest and hips (with the weight macro a little past
# its slider), but not a waist much larger than the hips: a 150 cm waist reached 110 cm. Every body is
# valid (CLAUDE.md "Bodies"), so what's still missing at the waist is added as a belly: smooth in
# height (centred on the waist line, hanging lower than it reaches up), mostly forward, some to the
# sides, none at the back. Fractions of the unscaled body height.
BELLY_FRONT, BELLY_SIDE, BELLY_BACK = 1.3, 0.8, 0.0   # none at the back: it would read as the seat
BELLY_DOWN, BELLY_DROP = 0.09, 0.0     # reach below the centre; the centre on the waist line


@lru_cache(maxsize=1)
def _helper_owner():
    """Each helper vertex (joint cubes, after N_BODY) follows its nearest body vertex."""
    from scipy.spatial import cKDTree
    V0 = _data()[0]
    return cKDTree(V0[:N_BODY]).query(V0[N_BODY:])[1]


def _widen(V, w, regions):
    """Add a belly of size w["belly"] (0 = none; the waist girth grows by about that share) centred on
    w["waist_y"] (fraction of height)."""
    k = float(w.get("belly", 0.0))
    if k <= 0:
        return V
    V = V.copy()
    B = V[:N_BODY]
    H = B[:, 1].max()
    y = B[:, 1] / H
    core = np.clip(1 - regions["arm"][:N_BODY] - regions["hand"][:N_BODY] - regions["head"][:N_BODY], 0, 1)
    # round, and exactly nothing from the underbust line up (the bust stays the bust)
    c = w["waist_y"] - BELLY_DROP
    up = float(np.clip(w.get("underbust_y", c + 0.06) - c, 0.02, 0.08))
    dy = y - c
    span = np.where(dy > 0, up, BELLY_DOWN)
    g = np.where(np.abs(dy) < span, np.cos(0.5 * np.pi * dy / span) ** 2, 0.0)
    # the torso's centre line (z) at each height, from the core's front and back
    bins = np.round(y * 200).astype(int)
    zc = np.zeros(len(B))
    cm = core > 0.5
    for b in np.unique(bins[g > 0.01]):
        sel = bins == b
        c = sel & cm
        if c.sum() > 4:
            zc[sel] = 0.5 * (B[c, 2].max() + B[c, 2].min())
    dz = B[:, 2] - zc
    dirz = np.where(dz > 0, BELLY_FRONT, BELLY_BACK)
    d = np.zeros_like(B)
    d[:, 0] = k * BELLY_SIDE * g * B[:, 0]
    d[:, 2] = k * dirz * g * dz
    d *= core[:, None]
    B += d
    V[:N_BODY] = B
    V[N_BODY:] += d[_helper_owner()]
    return V


def _scale_extremities(V, hs, fs, regions, hw=1.0):
    V = V.copy()
    j = lambda n: V[_data()[3][n]].mean(0)
    for side in ("l", "r"):
        for reg, joint, sc in (("hand", f"{side}-hand", hs), ("foot", f"{side}-ankle", fs)):
            wide = hw if reg == "hand" else 1.0
            if abs(sc - 1) < 1e-9 and abs(wide - 1) < 1e-9:
                continue
            c = j(joint)
            w = regions[reg].copy()
            # this side only
            sel = np.sign(V[:N_BODY, 0] - V[:N_BODY, 0].mean()) == np.sign(c[0])
            w[~sel] = 0
            Vb = V[:N_BODY]
            if abs(wide - 1) > 1e-9:      # girth: scale across the hand's own axis, length unchanged
                ax = np.mean([j(f"{side}-finger-{k}-1") for k in (2, 3, 4, 5)], axis=0) - c
                ax /= np.linalg.norm(ax)
                r = Vb - c
                perp = r - np.outer(r @ ax, ax)
                Vb += (w[:, None] * (wide - 1)) * perp
            Vb += (w[:, None] * (sc - 1)) * (Vb - c)
    return V


class Human:
    """A shaped, scaled MakeHuman body: mesh + joints + regions."""

    def __init__(self, shape: Shape):
        self.shape = shape
        self.V = build_vertices(shape)
        V0, tris, _, joints, regions = _data()
        self.tris = tris
        self._joints = joints
        self.regions = regions

    @property
    def verts(self):
        return self.V[:N_BODY]

    def joint(self, name: str) -> np.ndarray:
        return self.V[self._joints[name]].mean(0)

    def height(self) -> float:
        return float(self.verts[:, 1].max() - self.verts[:, 1].min())

    def region_tris(self, *names, thresh=0.5):
        w = sum(self.regions[n] for n in names)
        ok = w[self.tris].min(1) > thresh
        return self.tris[ok]


# ----------------------------------------------------------------- fitting --
FIT_MAP = {   # measurement -> MakeHuman measure target that moves it
    "chest": "measure-bust-circ",
    "underbust": "measure-underbust-circ",
    "waist": "measure-waist-circ",
    "hip": "measure-hips-circ",
    "shoulder_width": "measure-shoulder-dist",
    "neck": "measure-neck-circ",
    "upper_arm": "measure-upperarm-circ",
    "thigh": "measure-thigh-circ",
}


def _height_slider(sex, target_h, muscle, weight):
    hs = np.array([0.0, 0.5, 1.0])
    H = [Human(Shape(sex=sex, muscle=muscle, weight=weight, height=v)).height() for v in hs]
    return float(np.clip(np.interp(target_h, H, hs), 0.0, 1.0))


# How far past MakeHuman's own sliders the fitter may go (its 'weight' macro tops out short of many
# real bodies), and what going past costs per unit. Every body is valid (CLAUDE.md "Bodies").
WEIGHT_MAX = 1.6           # MakeHuman's weight macro a little past its slider (natural up to here)
EXTRA_SHAPES = True
WIDEN = True          # widen sections past MakeHuman's range (_widen)
WIDEN_FROM_CM = 1.0   # a belly only when the waist is short by more than this
WIDER_FROM_CM = 2.5   # the wider fit only when a girth is this short in MakeHuman's own range (its fits are within 1.5)
WIDEN_ITERS = 8
MEASURE_MAX = 3.0
OVER_COST = 0.01


def fit_human(m, reg=0.03, verbose=False):
    """Fit a Human to a Measurements (cm). Returns (human, report rows).

    Unknowns: body weight (MakeHuman 'weight' macro: whole-body, anatomically
    distributed) + one measure target per given girth/width + arm length.
    The measure targets carry a small penalty (reg) so the solver explains as
    much as it can with body weight first, the way real bodies differ, and
    uses the local targets for what's left."""
    from scipy.optimize import least_squares
    from .meshmeasure import Tape

    sex = 1.0 if str(getattr(m, "sex", "male")).lower().startswith("m") else 0.0
    muscle = getattr(m, "muscle", None)
    muscle = 0.5 if muscle is None else float(muscle)
    H = m.height / 100.0
    hslider = _height_slider(sex, H, muscle, 0.5)

    wanted = {k: getattr(m, k) for k in ("chest", "waist", "hip", "shoulder_width", "neck", "upper_arm",
                                         "arm_length", "underbust", "thigh", "inseam")
              if getattr(m, k, None) is not None}
    mkeys = [k for k in wanted if k in FIT_MAP]
    # sculpted shapes for the belly and seat: how larger bodies gain at the waist and hips (forward and
    # round, not as a tube). Used with the waist / hip measure targets when those are given.
    extra = [n for n, k in (("stomach-pregnant", "waist"), ("buttocks-volume", "hip")) if EXTRA_SHAPES and k in wanted]
    names = (["weight"] + [FIT_MAP[k] for k in mkeys] + extra + (["arm"] if "arm_length" in wanted else [])
             + (["leg"] if "inseam" in wanted else []))
    i_extra = {n: 1 + len(mkeys) + j for j, n in enumerate(extra)}
    i_arm = 1 + len(mkeys) + len(extra) if "arm_length" in wanted else None
    i_leg = len(names) - 1 if "inseam" in wanted else None

    def shape_from(x):
        meas = {FIT_MAP[k]: x[1 + i] for i, k in enumerate(mkeys)}
        meas.update({n: x[i] for n, i in i_extra.items()})
        if i_arm is not None:
            meas["measure-upperarm-length"] = x[i_arm]
            meas["measure-lowerarm-length"] = x[i_arm]
        if i_leg is not None:       # inseam: thigh and shin lengthen together
            meas["measure-upperleg-height"] = x[i_leg]
            meas["measure-lowerleg-height"] = x[i_leg]
        return Shape(sex=sex, muscle=muscle, weight=x[0], height=hslider, measure=meas,
                     cup=getattr(m, "cup", None) or 0.5, widen=dict(belly) if belly else None,
                     wide_tape=bool(wide))

    belly = {}
    wide = []       # non-empty once the fit goes past MakeHuman's range      # set after the first fit when the waist is past MakeHuman's range (_widen)

    def make(x):
        s = shape_from(x)
        h = Human(s)
        s.scale = H / h.height()
        return Human(s)

    # the armpit's drop below the shoulder joint, measured exactly once (it
    # bounds the chest search; fast and exact tapes must agree)
    h0 = make(np.r_[0.5, np.zeros(len(names) - 1)])
    T0 = Tape(h0)
    drop_rel = (h0.joint(f"{T0.side}-shoulder")[1] - T0.armpit_y()) / h0.height()

    def resid(x):
        hx = make(x)
        T = Tape(hx, fast=True, armpit_drop=drop_rel * hx.height())
        got = {"chest": T.chest, "waist": T.waist, "hip": T.hip, "shoulder_width": T.shoulder_width,
               "neck": T.neck, "upper_arm": T.upper_arm, "arm_length": T.arm_length,
               "underbust": T.underbust, "thigh": T.thigh, "inseam": T.crotch_height}
        r = [(got[k]() * 100 - v) / v for k, v in wanted.items()]
        # beyond MakeHuman's slider range: allowed, but at a steep extra cost
        over = [max(0.0, x[0] - 1.0)] + [max(0.0, abs(v) - 1.0) for v in x[1:]]
        regs = np.full(len(x) - 1, reg)
        if i_leg is not None:      # leg length is a length, not something body weight explains
            regs[i_leg - 1] = reg * 0.15
        cost = OVER_COST if wide else 0.05          # MakeHuman's own fit: 0.05, as always
        return np.array(r + list(regs * x[1:]) + [cost * o for o in over])

    x0 = np.r_[0.5, np.zeros(len(names) - 1)]
    def bounds(wmax, mmax):
        lo = np.r_[0.0, -mmax * np.ones(len(names) - 1)]
        hi = np.r_[wmax, mmax * np.ones(len(names) - 1)]
        for i in (i_arm, i_leg):          # arm and leg *lengths* keep MakeHuman's range (girths go further)
            if i is not None:
                lo[i], hi[i] = -1.5, 1.5
        for i in i_extra.values():        # a belly or seat shape only adds (its negative isn't sculpted)
            lo[i] = 0.0
        return lo, hi

    # first within MakeHuman's own range (the bounds steer the solver's steps, so a body that fits there
    # comes out exactly as it always did); wider only if a girth is still short
    def solve(free, x_start, lo, hi, nfev):
        """least squares over the free unknowns; the others held at x_start"""
        free = list(free)
        full = lambda xf: np.put(xc := x_start.copy(), free, xf) or xc
        # the rows of held unknowns (their penalty and past-the-slider terms) are left out, so the
        # problem is exactly the one without them
        held = [i for i in range(len(names)) if i not in free]
        nw = len(wanted)
        drop = {nw + i - 1 for i in held if i > 0} | {nw + len(names) - 1 + i for i in held}
        rows = [j for j in range(nw + 2 * len(names) - 1) if j not in drop]
        r = least_squares(lambda xf: resid(full(xf))[rows], np.clip(x_start[free], lo[free], hi[free]),
                          bounds=(lo[free], hi[free]), diff_step=0.08, x_scale=1.0, max_nfev=nfev,
                          verbose=2 if verbose else 0)
        return full(r.x), r

    # first the fit MakeHuman always had: its own range, no belly or seat shape (the bounds and the
    # unknowns steer the solver, so a body that fits there comes out exactly as it always did); then,
    # only if a girth is still short, wider and with the belly and seat shapes
    free = [i for i in range(len(names)) if i not in i_extra.values()]
    lo, hi = bounds(1.3, 1.5)
    xs, sol = solve(free, x0, lo, hi, 200)
    short = [wanted[k] * -resid(xs)[i] for i, k in enumerate(wanted) if k in FIT_MAP]
    if max(short, default=0.0) > WIDER_FROM_CM and (WEIGHT_MAX > 1.3 or MEASURE_MAX > 1.5 or i_extra):
        free = list(range(len(names)))
        wide.append(True)
        lo, hi = bounds(WEIGHT_MAX, MEASURE_MAX)
        xs, sol = solve(free, np.clip(xs, lo, hi), lo, hi, 200)
    xs = xs.copy()
    if i_leg is not None:
        # crotch height moves in small steps (it is the lowest mesh point between the
        # legs), which stalls the solver short of the target: finish the leg alone
        want = wanted["inseam"]
        f = lambda xl: Tape(make(np.r_[xs[:i_leg], xl, xs[i_leg + 1:]])).crotch_height() * 100 - want
        a, fa = xs[i_leg], f(xs[i_leg])
        b = float(np.clip(a - np.sign(fa) * 0.3, -1.5, 1.5))
        fb = f(b)
        for _ in range(6):
            if abs(fb) < 0.25 or fb == fa:
                break
            a, fa, b = b, fb, float(np.clip(b - fb * (b - a) / (fb - fa), -1.5, 1.5))
            fb = f(b)
        if abs(fb) < abs(f(xs[i_leg])):
            xs[i_leg] = b
            # the longer/shorter leg changed the overall scale: refit the girths with the leg held
            xs, _ = solve([i for i in free if i != i_leg], xs, lo, hi, 120)
            fb = f(xs[i_leg])                    # one last nudge of the leg
            if abs(fb) > 0.25:
                d = 0.1
                slope = (f(xs[i_leg] + d) - fb) / d
                if abs(slope) > 1e-3:
                    xs[i_leg] = float(np.clip(xs[i_leg] - fb / slope, -1.5, 1.5))
    s = shape_from(xs)
    s.scale = H / Human(s).height()
    h = Human(s)
    # past MakeHuman's range: a waist still short gets a belly
    if WIDEN and wide and getattr(m, "waist", None) and m.waist - Tape(h).waist() * 100 > WIDEN_FROM_CM:
        for _rnd in range(1):
            T = Tape(h)
            belly["waist_y"] = T.lines()["waist"] / h.height()
            belly["underbust_y"] = T.lines()["underbust"] / h.height()
            k = belly.get("belly", 0.0)
            for _ in range(WIDEN_ITERS):
                got = Tape(h).waist() * 100
                if abs(got - m.waist) < 0.5:
                    break
                k = max(0.0, k + (m.waist / got - 1) * 0.9)      # the waist grows a bit less than k
                belly["belly"] = k
                s = shape_from(xs)
                s.scale = H / Human(s).height()
                h = Human(s)
    # hands and feet: scale about wrist / ankle if measured
    T = Tape(h)
    if getattr(m, "hand_length", None):
        s.hand_scale = m.hand_length / (T.hand_length() * 100)
    if getattr(m, "foot_length", None):
        s.foot_scale = m.foot_length / (T.foot_length() * 100)
    if s.hand_scale != 1 or s.foot_scale != 1:
        h = Human(s)
        h_ = h.height()
        s.scale *= H / h_
        h = Human(s)
    if getattr(m, "hand_girth", None):       # around the knuckles: widen/narrow the hand to it
        for _ in range(2):
            s.hand_width *= m.hand_girth / (Tape(h).hand_girth() * 100)
            h = Human(s)
    T = Tape(h)
    got = T.all()
    rows = []
    for k in ("height", "chest", "underbust", "waist", "hip", "shoulder_width", "neck", "upper_arm",
              "arm_length", "thigh", "inseam", "hand_length", "hand_girth", "foot_length"):
        want = getattr(m, k, None)
        rows.append({"measurement": k, "target_cm": want, "avatar_cm": round(got[k], 2),
                     "error_cm": None if want is None else round(got[k] - want, 2)})
    h.fit = dict(params=dict(zip(names, np.round(xs, 3))), height_slider=hslider, sex=sex,
                 cost=float(sol.cost), nfev=int(sol.nfev))
    return h, rows
