"""Hands and feet for the avatar.

Hands hang relaxed at the end of the forearms, palms facing the thighs, thumbs
forward, fingers slightly curled. Feet stand flat on the floor (y = 0),
toes pointing forward and turned out a little. The forearm and shin are
re-tapered to the wrist and ankle with round cones so there's no ball at the
joint.

Default proportions (fractions of height H, adult averages):
  hand length (wrist crease -> middle fingertip) 0.108 H
  hand breadth (across the knuckles)             0.0485 H
  foot length (heel -> longest toe)              0.152 H
  foot breadth (widest, across the ball)         0.0565 H
  wrist girth 0.095 H,  ankle girth 0.13 H
"""
from __future__ import annotations

import numpy as np

from .body import EXTRA_COLS, Body

# indices into Body.caps (shared by Body.default and body_from_measurements)
FOREARM = {"r": 3, "l": 4}
SHIN = {"r": 9, "l": 10}


def _unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def _row(kind, k, params):
    r = np.zeros(EXTRA_COLS)
    r[0], r[1] = kind, k
    r[2:2 + len(params)] = params
    return r


def capsule(a, b, r, k):
    return _row(0, k, np.r_[a, b, r])


def round_cone(a, b, ra, rb, k):
    return _row(2, k, np.r_[a, b, ra, rb])


def flat_cone(a, b, ra, rb, sy, k):
    return _row(3, k, np.r_[a, b, ra, rb, sy])


def rbox(center, u, v, w, half, rounding, k):
    return _row(1, k, np.r_[center, _unit(u), _unit(v), _unit(w), half, rounding])


def _hand(wrist, d, side, s, L, B, r_wrist, finger_scale=1.0):
    """side = +1 right hand (x > 0), -1 left. d = forearm direction (toward fingers)."""
    f = _unit(np.array([0.0, 0.0, 1.0]) - d[2] * d)            # thumb side: forward
    n = _unit(np.cross(d, f))                                   # palm normal
    if n[0] * side > 0:
        n = -n                                                  # palm faces the thigh
    palm_len = 0.53 * L
    thick = 0.026 * s
    rows = [round_cone(wrist - d * 0.01 * s, wrist + d * 0.02 * s, r_wrist, 0.85 * r_wrist, 0.012 * s),
            rbox(wrist + d * (palm_len / 2), d, f, n,
                 np.array([palm_len / 2, B / 2, thick / 2]), 0.009 * s, 0.012 * s)]
    fr = 0.21 * B / 2                                           # finger radius ~ 9 mm at B = 8.5 cm
    curl = _unit(d + np.tan(np.radians(14)) * n)                # fingers curl toward the palm
    finger_len = (L - palm_len) * finger_scale
    for off, frac in ((0.375, 0.93), (0.125, 1.0), (-0.125, 0.95), (-0.375, 0.79)):  # index..pinky
        base = wrist + d * (palm_len - 0.012 * s) + f * (off * B * 0.92)
        ln = finger_len * frac + 0.012 * s
        rows.append(capsule(base, base + curl * (ln - fr), fr * (1.0 if off > -0.3 else 0.88), 0.004 * s))
    tb = wrist + d * (0.22 * palm_len) + f * (0.40 * B) + n * (0.004 * s)
    td = _unit(0.80 * d + 0.55 * f + 0.20 * n)
    rows.append(capsule(tb, tb + td * (0.36 * L), fr * 1.15, 0.008 * s))
    mid_base = wrist + d * (palm_len - 0.012 * s) + f * (0.125 * B * 0.92)
    mid_end = mid_base + curl * (finger_len + 0.012 * s - fr)   # capsule axis end of middle finger
    return rows, (mid_end, curl)


def _foot(ankle, side, s, L, B, r_ankle, toe_out_deg=7.0, lift=0.0):
    a = np.radians(toe_out_deg) * side
    f = np.array([np.sin(a), 0.0, np.cos(a)])                  # toward the toes
    up = np.array([0.0, 1.0, 0.0])
    sd = np.cross(up, f)
    base = np.array([ankle[0], lift, ankle[2]])                 # ankle projected to the floor
    heel = base - f * (0.24 * L)
    # Foot = two vertically squashed round cones (sole flat on the floor):
    #   heel -> ball: widens from the heel (0.68 B) to the ball (B), height ~6.5 cm at the instep
    #   ball -> toes: tapers to the toe tips, ~2.5 cm thick
    r_heel, r_ball, r_toe = 0.34 * B, 0.50 * B, 0.30 * B
    sy1, sy2 = 0.62, 0.42                       # height/width of each section
    a1 = heel + f * r_heel + up * (r_heel * sy1)
    b1 = heel + f * (0.70 * L) + up * (r_ball * sy1)
    a2 = heel + f * (0.70 * L) + up * (r_ball * sy2)
    b2 = heel + f * (L - r_toe) + up * (r_toe * sy2)
    rows = [
        round_cone(ankle + up * 0.02 * s, ankle - up * 0.01 * s, r_ankle, r_ankle * 1.05, 0.02 * s),
        flat_cone(a1, b1, r_heel, r_ball, sy1, 0.02 * s),
        flat_cone(a2, b2, r_ball, r_toe, sy2, 0.012 * s),
    ]
    return rows, heel, heel + f * L, f


def attach_extremities(body: Body, height: float, hand_length=None, hand_breadth=None,
                       foot_length=None, foot_breadth=None, wrist=None, ankle=None, calibrate=True):
    """Add hands and feet to `body` in place. Lengths in meters (None -> from height).
    With calibrate, finger and foot lengths are corrected until the virtual
    measurements (measure_extremities) match the targets."""
    caps0 = body.caps.copy()
    finger_scale, foot_scale, lift, breadth_scale = 1.0, 1.0, 0.0, 1.0
    for _ in range(6):
        body.caps = caps0.copy()
        _attach(body, height, hand_length, hand_breadth, foot_length, foot_breadth, wrist, ankle,
                finger_scale, foot_scale, lift, breadth_scale)
        if not calibrate:
            break
        got = measure_extremities(body)
        tgt = body.extremity_sizes
        eh = tgt["hand_length"] * 100 / got["hand_length"]
        ef = tgt["foot_length"] * 100 / got["foot_length"]
        sink = got["below_floor_mm"] / 1000
        eb = tgt["foot_breadth"] * 100 / got["foot_breadth"]
        if abs(eh - 1) < 1e-3 and abs(ef - 1) < 1e-3 and abs(eb - 1) < 2e-3 and sink < 2e-4:
            break
        breadth_scale *= eb
        lift += sink
        palm = 0.53 * tgt["hand_length"]
        # only the finger part (L - palm) is scaled, so convert the length error
        finger_scale *= 1 + (eh - 1) * tgt["hand_length"] / (tgt["hand_length"] - palm)
        foot_scale *= ef
    return body


def _attach(body, height, hand_length, hand_breadth, foot_length, foot_breadth, wrist, ankle,
            finger_scale, foot_scale, lift, breadth_scale=1.0):
    H = height
    s = H / 1.755
    L_h = hand_length or 0.108 * H
    B_h = hand_breadth or 0.0485 * H
    L_f = foot_length or 0.152 * H
    B_f = foot_breadth or 0.0565 * H
    r_w = (wrist or 0.095 * H) / (2 * np.pi)
    r_a = (ankle or 0.13 * H) / (2 * np.pi)

    extras, groups, lm = [], [], {}

    def add_group(rows, center, radius):
        start = len(extras)
        extras.extend(rows)
        groups.append([*center, radius, start, len(extras)])

    for key, side in (("r", 1), ("l", -1)):
        # forearm: stop the constant-radius capsule early, taper to the wrist
        c = body.caps[FOREARM[key]]
        elbow, wrist = c[:3].copy(), c[3:6].copy()
        d = _unit(wrist - elbow)
        r_f = c[6]
        mid = elbow + (wrist - elbow) * 0.45
        body.caps[FOREARM[key], 3:6] = mid
        rows, tip = _hand(wrist, d, side, s, L_h, B_h, r_w, finger_scale)
        rows.insert(0, round_cone(mid, wrist, r_f, r_w, 0.01 * s))
        center = wrist + d * (0.5 * L_h)
        add_group(rows, center, 0.6 * L_h + 0.05 * s + r_f)
        lm[f"wrist_{key}"], lm[f"fingertip_{key}"], lm[f"hand_dir_{key}"] = wrist, tip, d
        lm[f"hand_patch_{key}"] = (wrist + d * (0.5 * L_h), 0.62 * L_h + 0.012 * s)

        # shin: same, taper to the ankle
        c = body.caps[SHIN[key]]
        knee, ank = c[:3].copy(), c[3:6].copy()
        ank[1] = 0.045 * H
        r_s = c[6]
        mid = knee + (ank - knee) * 0.55
        body.caps[SHIN[key], 3:6] = mid
        rows, heel, toe, f = _foot(ank, side, s, L_f * foot_scale, B_f * breadth_scale, r_a, lift=lift)
        rows.insert(0, round_cone(mid, ank, r_s, r_a, 0.015 * s))
        center = 0.5 * (heel + toe) + np.array([0, 0.05 * s, 0])
        add_group(rows, center, 0.62 * L_f + np.linalg.norm(ank - mid) * 0.0 + 0.25 * H * 0.0 + r_s +
                  max(0.0, (ank[1] - mid[1]) * -1.0))
        lm[f"ankle_{key}"], lm[f"heel_{key}"], lm[f"toe_{key}"], lm[f"foot_dir_{key}"] = ank, heel, toe, f
        lm[f"foot_patch_{key}"] = (0.5 * (heel + toe) + np.array([0, 0.03 * s, 0]), 0.58 * L_f * foot_scale)

    body.extras = np.ascontiguousarray(np.array(extras), dtype=np.float64)
    body.groups = np.ascontiguousarray(np.array(groups), dtype=np.float64)
    # bounding spheres must contain every primitive: grow them to fit, exactly
    for g in body.groups:
        c = g[:3]
        reach = 0.0
        for e in body.extras[int(g[4]):int(g[5])]:
            if e[0] in (0.0, 2.0):
                ends = [e[2:5], e[5:8]]
                r = max(e[8], e[9]) if e[0] == 2.0 else e[8]
            else:
                ctr, half = e[2:5], e[14:17]
                ends = [ctr]
                r = np.linalg.norm(half)
            reach = max(reach, max(np.linalg.norm(p - c) for p in ends) + r)
        g[3] = reach + 0.005
    body.landmarks = lm
    body.extremity_sizes = dict(hand_length=L_h, hand_breadth=B_h, foot_length=L_f,
                                foot_breadth=B_f, wrist=2 * np.pi * r_w, ankle=2 * np.pi * r_a)


# ------------------------------------------------------- measure back ----
def _march(body, start, direction, max_len=0.4, step=0.0005):
    """Distance from `start` (inside) along `direction` to where the SDF turns positive."""
    t = 0.0
    while t < max_len:
        if body.sdf((start + direction * t)[None])[0] > 0:
            return t
        t += step
    return np.nan


def measure_extremities(body: Body) -> dict:
    """Read hands and feet back from the SDF (cm)."""
    lm = body.landmarks
    out = {}
    w, (axis_end, curl), d = lm["wrist_r"], lm["fingertip_r"], lm["hand_dir_r"]
    # find the real fingertip: from inside the middle finger, march out along it
    tip = axis_end + curl * _march(body, axis_end, curl, max_len=0.05)
    # hand length = wrist crease to middle fingertip (straight), as with a ruler
    out["hand_length"] = float(np.linalg.norm(tip - w)) * 100
    # breadth across the knuckles: from the knuckle line centre outward both ways
    f = np.array([0, 0, 1.0]) - d[2] * d; f /= np.linalg.norm(f)
    kn = w + d * (0.53 * body.extremity_sizes["hand_length"] - 0.02)
    out["hand_breadth"] = (_march(body, kn, f, 0.15) + _march(body, kn, -f, 0.15)) * 100
    heel, toe, fd = lm["heel_r"], lm["toe_r"], lm["foot_dir_r"]
    mid = 0.5 * (heel + toe) + np.array([0, 0.012, 0])
    out["foot_length"] = (_march(body, mid, fd, 0.3) + _march(body, mid, -fd, 0.3)) * 100
    side = np.cross([0, 1.0, 0], fd)
    # widest part of the foot (a tape across the ball): take the max over the forefoot
    fl = np.linalg.norm(toe - heel)
    widths = []
    for t in np.linspace(0.55, 0.85, 13):
        ball = heel + fd * (t * fl) + np.array([0, 0.012, 0])
        widths.append(_march(body, ball, side, 0.12) + _march(body, ball, -side, 0.12))
    out["foot_breadth"] = max(widths) * 100
    # how far the sole dips below the floor (y = 0): SDF at floor level under the foot
    pts = []
    for t in np.linspace(0.05, 0.95, 19):
        for u in np.linspace(-0.4, 0.4, 5):
            p = heel + (toe - heel) * t + side * u * body.extremity_sizes["foot_breadth"]
            pts.append([p[0], 0.0, p[2]])
    d = body.sdf(np.array(pts))
    out["below_floor_mm"] = float(max(0.0, -d.min()) * 1000)
    return out
