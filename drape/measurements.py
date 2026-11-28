"""Build the avatar from a person's tape measurements, then verify it by
measuring the generated SDF body back with a virtual tape.

All inputs in centimeters (what a tape measure gives you). Girths are taken
the way a tailor takes them: a tape around the body, which bridges hollows,
so the virtual tape is the perimeter of the convex hull of the body's
cross-section at that height.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import numpy as np
from scipy.spatial import ConvexHull
from skimage.measure import find_contours

from .body import Body


@dataclass
class Measurements:
    sex: str = "male"              # "female" or "male": picks the body model
    height: float = 175.0          # floor to top of head
    chest: float = 96.0            # fullest part of chest/bust, arms down
    waist: float = 82.0            # natural waist
    hip: float = 98.0              # fullest part of seat
    shoulder_width: float = 45.0   # shoulder point to shoulder point, straight across the back
    neck: float = 38.0             # base of neck
    upper_arm: float = 30.0        # fullest part of bicep, relaxed
    arm_length: float = 60.0       # shoulder point to wrist bone, arm straight
    thigh: float | None = None     # default: 0.6 x hip
    inseam: float | None = None    # inside leg: crotch to floor, barefoot (default: the avatar's own)
    underbust: float | None = None # default: between waist and chest
    hand_length: float | None = None   # wrist crease to tip of middle finger (default 0.108 x height)
    hand_breadth: float | None = None  # across the knuckles, thumb excluded (default 0.0485 x height)
    hand_girth: float | None = None    # around the knuckles, thumb not included (glove size; default: the avatar's)
    foot_length: float | None = None   # heel to longest toe, standing (default 0.152 x height)
    foot_breadth: float | None = None  # widest part, across the ball (default 0.0565 x height)
    wrist: float | None = None         # wrist girth (default 0.095 x height)
    ankle: float | None = None         # ankle girth above the bone (default 0.13 x height)
    muscle: float | None = None        # optional build, 0 (slight) .. 0.5 (average) .. 1 (very muscular)
    cup: float | None = None           # optional breast size slider for female avatars, 0..1 (0.5 average)
    arm_angle_deg: float = 37.0    # A-pose: arm angle from vertical (not a body measurement)

    @classmethod
    def load(cls, path) -> "Measurements":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        known = {f.name for f in fields(cls)}
        if "sex" in data and str(data["sex"]).lower() not in ("female", "male", "f", "m"):
            raise ValueError("sex must be 'female' or 'male'")
        unknown = set(data) - known - {"name", "units", "notes"}
        if unknown:
            raise ValueError(f"unknown measurement(s): {sorted(unknown)}; expected {sorted(known)}")
        if data.get("units", "cm") != "cm":
            raise ValueError("measurements must be in cm")
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path):
        Path(path).write_text(json.dumps({"units": "cm", **asdict(self)}, indent=2))

    def validate(self) -> list[str]:
        """Typo checks only: a number that looks like inches typed into a cm field, or a tape
        taken the wrong way. Never a judgement of a body's shape or proportions: every body is
        valid, so there's no upper limit on any girth and no ratio between two girths
        (CLAUDE.md, "Bodies"). Each message is about the number, not the person."""
        w = []
        if self.muscle is not None and not 0 <= self.muscle <= 1:
            w.append("muscle must be between 0 and 1")
        inch = "if you measured in inches, switch the units to inches (⚙) and type it again"
        if self.height < 100:
            w.append(f"Height {self.height:g} cm: {inch}.")
        # inches typed as cm give a number 2.54 times smaller: flag only a value far below any adult's
        for name, lo, how in (("chest", 0.3, ""), ("waist", 0.25, ""), ("hip", 0.3, ""),
                              ("hand_girth", 0.065, " (around the knuckles, thumb out)"),
                              ("inseam", 0.3, " (crotch to floor, barefoot)"),
                              ("wrist", 0.055, ""), ("ankle", 0.075, "")):
            v = getattr(self, name)
            if v is not None and self.height >= 100 and v / self.height < lo:
                w.append(f"{name.replace('_', ' ').capitalize()} {v:g} cm{how}: {inch}.")
        if self.shoulder_width > 0.6 * self.chest:    # a measuring tip: the tape went round, not across
            w.append("Shoulder width is measured across the back, from one shoulder tip to the other "
                     "(not around): check it if you measured around.")
        return w


# ----------------------------------------------------------- geometry ----
def ellipse_perimeter(a, b):
    """Ramanujan's second approximation (error < 1e-5 relative for body shapes)."""
    h = ((a - b) / (a + b)) ** 2
    return np.pi * (a + b) * (1 + 3 * h / (10 + np.sqrt(4 - 3 * h)))


def _radii_for_girth(girth_m, depth_ratio):
    """Semi-axes (rx, rz) of an ellipse with the given perimeter and rz/rx."""
    rx = girth_m / ellipse_perimeter(1.0, depth_ratio)
    return rx, rx * depth_ratio


# Torso sections as fractions of height, with depth/breadth ratios and
# front-back centre offsets. Ratios follow adult anthropometry (ANSUR II-style
# depth/breadth: chest ~0.76, waist ~0.75, buttock ~0.72). A flatter ellipse
# makes the upper torso too wide and buries the armpit (see tests).
#         name         y/H     rz/rx   cz (m)
_SECTIONS = [
    ("crotch",      0.470, 0.70, -0.005),
    ("seat",        0.505, 0.72, -0.005),
    ("high_hip",    0.547, 0.73,  0.000),
    ("waist",       0.604, 0.75,  0.000),
    ("underbust",   0.684, 0.76,  0.010),
    ("chest",       0.741, 0.76,  0.015),
    ("upper_chest", 0.798, 0.66,  0.000),
    ("yoke",        0.832, 0.58, -0.005),
]


def _section_girths(m: Measurements) -> dict[str, float]:
    under = m.underbust if m.underbust else max(m.waist, m.waist + 0.55 * (m.chest - m.waist))
    return {
        "crotch": 0.90 * m.hip,
        "seat": m.hip,
        "high_hip": m.waist + 0.7 * (m.hip - m.waist),
        "waist": m.waist,
        "underbust": under,
        "chest": m.chest,
        "upper_chest": 0.90 * m.chest,   # across the armpits, above the bust
        # yoke: just below the neck, between the shoulders
        "yoke": None,
    }


def body_from_measurements(m: Measurements, calibrate: bool = True) -> Body:
    """Mannequin from tape measurements. With calibrate=True the torso is
    iteratively rescaled until the virtual tape reads the target girths
    (the smooth blend with arms/legs and the ellipse SDF otherwise bias them)."""
    H = m.height / 100.0
    s = H / 1.755  # length scale relative to the reference mannequin
    girth = _section_girths(m)
    sw = m.shoulder_width / 100.0

    torso = []
    for name, yf, ratio, cz in _SECTIONS:
        if name == "yoke":
            rx = 0.27 * sw  # yoke width scales with shoulder breadth
            rz = ratio * rx
        else:
            rx, rz = _radii_for_girth(girth[name] / 100.0, ratio)
        torso.append([yf * H, rx, rz, cz * s])
    torso = np.array(torso)

    # shoulders + arms (A-pose)
    bar_r = 0.055 * s
    sh_y = 0.815 * H
    tip = sw / 2
    bar_half = tip - bar_r
    joint = np.array([tip - 0.045 * s, sh_y - 0.01 * s, 0.0])
    ang = np.radians(m.arm_angle_deg)
    down = np.array([np.sin(ang), -np.cos(ang), 0.0])
    arm_len = m.arm_length / 100.0 - (tip - joint[0])  # joint is inset from the shoulder point
    upper_len, fore_len = 0.55 * arm_len, 0.45 * arm_len
    elbow = joint + down * upper_len
    fore_dir = np.array([np.sin(ang + 0.15), -np.cos(ang + 0.15), 0.0])
    fore_dir = fore_dir + np.array([0, 0, 0.05])            # slight forward bend
    fore_dir /= np.linalg.norm(fore_dir)
    wrist = elbow + fore_dir * fore_len
    r_up = m.upper_arm / 100.0 / (2 * np.pi)
    r_fore = 0.80 * r_up

    neck_r = m.neck / 100.0 / (2 * np.pi)
    head_r = 0.054 * H
    thigh = (m.thigh if m.thigh else 0.6 * m.hip) / 100.0
    thigh_r = thigh / (2 * np.pi)
    crotch = 0.460 * H                 # thigh capsules start below the seat line
    knee, ankle = 0.275 * H, 0.045 * H
    leg_x = 0.50 * torso[1, 1]

    def mirror(c):
        c = c.copy(); c[0] *= -1; c[3] *= -1
        return c

    arm_u = np.r_[joint, elbow, r_up]
    arm_f = np.r_[elbow, wrist, r_fore]
    caps = np.array([
        [-bar_half, sh_y, 0.0, bar_half, sh_y, 0.0, bar_r],    # 0 shoulder bar
        arm_u, mirror(arm_u),                                  # 1, 2 upper arms (R, L)
        arm_f, mirror(arm_f),                                  # 3, 4 forearms
        [0.0, 0.820 * H, -0.01 * s, 0.0, 0.900 * H, 0.0, neck_r],   # 5 neck
        [0.0, H - head_r, 0.01 * s, 0.0, H - head_r, 0.01 * s, head_r],  # 6 head
        [leg_x, crotch, 0.0, leg_x * 1.1, knee, 0.0, thigh_r],  # 7, 8 thighs
        [-leg_x, crotch, 0.0, -leg_x * 1.1, knee, 0.0, thigh_r],
        [leg_x * 1.1, knee, 0.0, leg_x * 1.1, ankle, -0.01 * s, 0.62 * thigh_r],  # 9, 10 lower legs
        [-leg_x * 1.1, knee, 0.0, -leg_x * 1.1, ankle, -0.01 * s, 0.62 * thigh_r],
    ])
    # The torso may not reach past the arm joint minus most of the arm's radius
    # (otherwise the armpit is filled and no armhole fits). Where it would,
    # trade breadth for depth at the same girth.
    def max_rx_at(y):
        # arm axis x at height y (A-pose: it moves outward as it goes down)
        drop = max(joint[1] - y, 0.0)
        return joint[0] + drop * np.tan(ang) - 0.6 * r_up

    for i, (name, *_r) in enumerate(_SECTIONS):
        max_rx = max_rx_at(torso[i, 0])
        if torso[i, 0] > 0.7 * H and torso[i, 1] > max_rx and girth.get(name):
            target = girth[name] / 100.0
            rx = max_rx
            lo, hi = rx * 0.3, rx * 2.0           # solve rz for the girth
            for _ in range(60):
                mid = 0.5 * (lo + hi)
                lo, hi = (mid, hi) if ellipse_perimeter(rx, mid) < target else (lo, mid)
            torso[i, 1], torso[i, 2] = rx, 0.5 * (lo + hi)
    body = Body(torso, caps, blend=0.035 * s)
    body.section_names = [n for n, *_ in _SECTIONS]
    from .extremities import attach_extremities
    cm = lambda v: None if v is None else v / 100.0
    attach_extremities(body, H, cm(m.hand_length), cm(m.hand_breadth), cm(m.foot_length),
                       cm(m.foot_breadth), cm(m.wrist), cm(m.ankle))
    body.max_torso_rx = np.array([max_rx_at(y) for y in torso[:, 0]])
    body.measurements = m

    if calibrate:
        tape = body.torso_only()  # shares the torso array
        targets = {name: girth[name] for name, *_ in _SECTIONS if girth[name] is not None}
        for _ in range(6):
            got = {n: girth_at(tape, torso[i, 0]) * 100 for i, (n, *_) in enumerate(_SECTIONS) if n in targets}
            err = max(abs(got[n] / targets[n] - 1) for n in targets)
            if err < 1e-3:
                break
            for i, (n, *_) in enumerate(_SECTIONS):
                if n in targets:
                    f = targets[n] / got[n]
                    if body.torso[i, 1] * f > body.max_torso_rx[i] and body.torso[i, 0] > 0.7 * H:
                        body.torso[i, 2] *= f * f  # clamped breadth: take it all in depth
                    else:
                        body.torso[i, 1:3] *= f
    return body


# ------------------------------------------------------- virtual tape ----
def _slice_contours(body: Body, y, res=0.002, half=0.45):
    xs = np.arange(-half, half, res)
    zs = np.arange(-0.35, 0.35, res)
    X, Z = np.meshgrid(xs, zs, indexing="ij")
    P = np.stack([X.ravel(), np.full(X.size, y), Z.ravel()], 1)
    d = body.sdf(P).reshape(X.shape)
    out = []
    for c in find_contours(d, 0.0):
        out.append(np.stack([xs[0] + c[:, 0] * res, zs[0] + c[:, 1] * res], 1))
    return out


def girth_at(body: Body, y: float, center_x: float = 0.0) -> float:
    """Tape-measure girth (m) of the body part enclosing x=center_x at height y."""
    best = None
    for c in _slice_contours(body, y):
        if len(c) < 8:
            continue
        # contour that brackets the centre line (the torso, not an arm)
        if c[:, 0].min() < center_x < c[:, 0].max():
            hull = ConvexHull(c)
            per = hull.area  # in 2D, ConvexHull.area is the perimeter
            if best is None or per > best:
                best = per
    if best is None:
        raise ValueError(f"no body cross-section at y={y:.3f}")
    return float(best)


def measure_body(body: Body) -> dict:
    """Read the avatar back like a tailor would. Returns cm. Girths go around
    the torso only (arms down, tape under the arms), as a tailor measures."""
    H = float(max(c[1] + c[6] for c in body.caps))
    tape = body.torso_only()
    res = {"height": H * 100}
    for key in ("seat", "waist", "chest"):
        res[{"seat": "hip"}.get(key, key)] = girth_at(tape, body.section_y(key)) * 100
    bar, arm = body.caps[0], body.caps[1]
    res["shoulder_width"] = (bar[3] - bar[0] + 2 * bar[6]) * 100
    res["neck"] = 2 * np.pi * body.caps[5][6] * 100
    res["upper_arm"] = 2 * np.pi * arm[6] * 100
    fore = body.caps[3]
    shoulder_tip_x = bar[3] + bar[6]
    wrist = body.landmarks["wrist_r"] if hasattr(body, "landmarks") else fore[3:6]
    res["arm_length"] = ((shoulder_tip_x - arm[0]) + np.linalg.norm(arm[3:6] - arm[:3])
                         + np.linalg.norm(wrist - fore[:3])) * 100
    if hasattr(body, "landmarks"):
        from .extremities import measure_extremities
        ex = measure_extremities(body)
        for k in ("hand_length", "hand_breadth", "foot_length", "foot_breadth"):
            res[k] = ex[k]
        res["wrist"] = body.extremity_sizes["wrist"] * 100
        res["ankle"] = body.extremity_sizes["ankle"] * 100
    return res


def body_report(body: Body, m: Measurements) -> list[dict]:
    got = measure_body(body)
    rows = []
    for k, v in got.items():
        want = getattr(m, k)
        if want is None:  # optional measurement not given: compare with the default used
            want = body.extremity_sizes[k] * 100
        v = float(v)
        rows.append({"measurement": k, "target_cm": float(want), "avatar_cm": round(v, 2),
                     "error_cm": round(v - want, 2), "error_pct": round((v / want - 1) * 100, 2)})
    return rows


def armpit_depth(body: Body) -> float:
    """Vertical distance (m) from the top of the shoulder to the armpit: the
    highest point where the inner side of the upper arm leaves the torso."""
    tape = body.torso_only()
    a = body.caps[1]
    j, e, r = a[:3], a[3:6], a[6]
    d = (e - j) / np.linalg.norm(e - j)
    inward = np.array([-d[1], d[0], 0.0])
    if inward[0] * j[0] > 0:
        inward = -inward          # toward the body's centre line
    top = body.caps[0][1] + body.caps[0][6]
    for t in np.linspace(0.0, np.linalg.norm(e - j), 800):
        p = j + d * t + inward * r
        if tape.sdf(p[None])[0] > 0.005:
            return float(top - p[1])
    raise ValueError("arm never separates from the torso")
