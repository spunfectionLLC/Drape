"""Example garments built from the pattern primitives. Units: meters, flat
pattern space: u = horizontal from the piece's center line, v = up from hem."""
from __future__ import annotations

import numpy as np

from .pattern import (Panel, Seam, axis_wrap, bezier, build_garment, cylinder_wrap, line,
                      polyline_length)


def _mirror_join(right: np.ndarray) -> np.ndarray:
    """Right half of a symmetric curve (u=+N .. u=0) -> full curve +N .. -N."""
    left = right[::-1].copy()
    left[:, 0] *= -1
    return np.concatenate([right, left[1:]])


def _bodice(name, W, armhole_v, shoulder_u, shoulder_v, neck_u, neck_v, neck_drop, place):
    """Front/back body piece: hem, side seams, armholes, shoulders, neckline."""
    nv = neck_v - neck_drop
    S, N = np.array([shoulder_u, shoulder_v]), np.array([neck_u, neck_v])
    sdir = (N - S) / np.linalg.norm(N - S)
    perp = np.array([-sdir[1], sdir[0]])  # perpendicular to the shoulder line, pointing down
    # Trued: armhole arrives and neckline leaves at 90 deg to the shoulder seam,
    # and both start square to the side seam / centre line, so every sewn edge
    # runs smoothly across its seams (checked by seamcheck).
    arm_r = bezier((W, armhole_v), (shoulder_u + 0.02, armhole_v),
                   S + perp * 0.5 * (shoulder_v - armhole_v), S)
    neck_half = bezier(N, N + perp * 0.6 * neck_drop, (neck_u * 0.45, nv), (0.0, nv))
    arm_l = arm_r[::-1].copy(); arm_l[:, 0] *= -1
    return Panel(name, [
        ("hem", line((-W, 0.0), (W, 0.0))),
        ("side_r", line((W, 0.0), (W, armhole_v))),
        ("arm_r", arm_r),
        ("shoulder_r", line((shoulder_u, shoulder_v), (neck_u, neck_v))),
        ("neck", _mirror_join(neck_half)),
        ("shoulder_l", line((-neck_u, neck_v), (-shoulder_u, shoulder_v))),
        ("arm_l", arm_l),
        ("side_l", line((-W, armhole_v), (-W, 0.0))),
    ], place)


# Back panels are mirrored in x by the wrap (+u points to -x), so front-right
# meets back-left and vice versa, each traversed in opposite directions.
_BODY_SEAMS = [
    Seam("front", "side_r", "back", "side_l", reverse=True),
    Seam("front", "side_l", "back", "side_r", reverse=True),
    Seam("front", "shoulder_r", "back", "shoulder_l", reverse=True),
    Seam("front", "shoulder_l", "back", "shoulder_r", reverse=True),
]


def tank_top(half_width=0.25, armhole_v=0.36, shoulder_u=0.17, shoulder_v=0.54,
             neck_u=0.075, neck_v=0.58, front_neck_drop=0.11, back_neck_drop=0.025,
             hem_y=0.92, wrap_radius=0.20, spacing=0.015, density=0.15, body=None):
    """Two-panel sleeveless top."""
    if body is not None:
        hem_y, wrap_radius = _placement_for(body, neck_v)
    args = (half_width, armhole_v, shoulder_u, shoulder_v, neck_u, neck_v)
    front = _bodice("front", *args, front_neck_drop, cylinder_wrap(wrap_radius, 0.0, hem_y))
    back = _bodice("back", *args, back_neck_drop, cylinder_wrap(wrap_radius, np.pi, hem_y))
    g = build_garment([front, back], _BODY_SEAMS, spacing=spacing, density=density)
    g.meta.update(hem_y=hem_y, torso_panels=["front", "back"], sleeve_panels=[],
                  girths=_straight_body_girths(half_width, neck_u, front_neck_drop, back_neck_drop))
    return g


def _straight_body_girths(half_width, neck_u, front_neck_drop, back_neck_drop):
    """The girths a straight-cut body (two pieces, each 2 x half_width wide from the hem to
    the armhole) is drafted to, for the ease report (fitcheck)."""
    from .fitcheck import neck_opening
    w = 4 * half_width
    return {"chest": w, "waist": w, "hip": w,
            "neckline": neck_opening(neck_u, front_neck_drop, back_neck_drop)}


def sleeve_cap(half_width, cap_base, cap_height, k=64, start_dir=(-1.0, 0.0)):
    """Right half of a bell-shaped sleeve cap, underarm (u=+W) -> crown (u=0).
    Leaves the underarm square to the underarm seam (start_dir) and is flat at
    the crown, so the cap is smooth across both."""
    W, vb, ch = half_width, cap_base, cap_height
    d = np.asarray(start_dir, float); d = d / np.linalg.norm(d)
    return bezier((W, vb), np.array([W, vb]) + d * 0.45 * W, (0.35 * W, vb + ch), (0.0, vb + ch), k)


def solve_cap_height(half_width, cap_base, target_len, lo=0.01, hi=0.3, start_dir=(-1.0, 0.0)):
    """Bisection: cap height so each half of the cap is target_len long."""
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if polyline_length(sleeve_cap(half_width, cap_base, mid, 400, start_dir)) < target_len:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def tshirt(half_width=0.25, armhole_v=0.35, shoulder_u=0.20, shoulder_v=0.54,
           neck_u=0.08, neck_v=0.58, front_neck_drop=0.075, back_neck_drop=0.02,
           sleeve_half_width=0.18, sleeve_underarm=0.12, cap_ease=0.03, sleeve_hem_half_width=None,
           hem_y=0.92, wrap_radius=0.20, sleeve_radius=0.075, spacing=0.015, density=0.15,
           body=None):
    """Four-piece T-shirt: front, back, two set-in sleeves. The sleeve cap
    height is solved so each half of the cap equals the armhole length plus
    `cap_ease` (fractional), as a patternmaker would. With `body`, the pieces
    are placed around that body (and sleeves on its arms)."""
    if body is not None:
        hem_y, wrap_radius = _placement_for(body, neck_v)
        sleeve_radius = max(sleeve_radius, body.arm_axis(+1)[2] + 0.03)
    args = (half_width, armhole_v, shoulder_u, shoulder_v, neck_u, neck_v)
    front = _bodice("front", *args, front_neck_drop, cylinder_wrap(wrap_radius, 0.0, hem_y))
    back = _bodice("back", *args, back_neck_drop, cylinder_wrap(wrap_radius, np.pi, hem_y))

    armhole_len = polyline_length(front.edge("arm_r"))
    W, vb = sleeve_half_width, sleeve_underarm
    Wh = W if sleeve_hem_half_width is None else sleeve_hem_half_width   # tapered sleeves
    ua = np.array([W - Wh, vb]); ua /= np.linalg.norm(ua)                 # underarm seam direction (up)
    cap_dir = (-ua[1], ua[0])                                             # square to it
    ch = solve_cap_height(W, vb, armhole_len * (1 + cap_ease), start_dir=cap_dir)
    top = vb + ch
    cap_r = sleeve_cap(W, vb, ch, start_dir=cap_dir)
    cap_l = cap_r[::-1].copy(); cap_l[:, 0] *= -1

    # Arm axes (shoulder joint -> elbow) from the default mannequin's A-pose.
    shoulder_joint = np.array([0.18, 1.42, 0.0]); elbow = np.array([0.36, 1.18, 0.0])
    if body is not None:  # take them from the actual body
        shoulder_joint, elbow, _r = body.arm_axis(+1)
        shoulder_joint, elbow = np.array(shoulder_joint, float), np.array(elbow, float)

    wrist = None
    if body is not None and getattr(body, "kind", "") == "mesh" and vb > 0.25:
        wrist = body.human.joint(f"{body.side}-hand")       # long sleeve: follow the forearm
    if abs(Wh - W) > 1e-9:
        # tapered: the hem arches so it meets both underarm seams at 90 deg
        hem = bezier((-Wh, 0.0), (-Wh + ua[1] * 0.3 * Wh, ua[0] * 0.3 * Wh),
                     (Wh - ua[1] * 0.3 * Wh, ua[0] * 0.3 * Wh), (Wh, 0.0), 48)
    else:
        hem = line((-Wh, 0.0), (Wh, 0.0))

    def sleeve(name, mirror):
        place = arm_wrap(shoulder_joint, elbow, sleeve_radius, top, mirror, wrist=wrist)
        return Panel(name, [
            ("hem", hem),
            ("underarm_r", line((Wh, 0.0), (W, vb))),
            ("cap_r", cap_r),                              # +u side -> front
            ("cap_l", cap_l),                              # -u side -> back
            ("underarm_l", line((-W, vb), (-Wh, 0.0))),
        ], place)

    sr, sl = sleeve("sleeve_r", False), sleeve("sleeve_l", True)
    seams = _BODY_SEAMS + [
        Seam("sleeve_r", "underarm_r", "sleeve_r", "underarm_l", reverse=True),
        Seam("sleeve_l", "underarm_r", "sleeve_l", "underarm_l", reverse=True),
        # right arm (+x): front.arm_r and back.arm_l both run along the cap halves
        # (cap is longer by cap_ease on purpose: declared so the seam check knows)
        Seam("sleeve_r", "cap_r", "front", "arm_r", reverse=False, ease=cap_ease),
        Seam("sleeve_r", "cap_l", "back", "arm_l", reverse=False, ease=cap_ease),
        # left arm (-x): opposite traversal
        Seam("sleeve_l", "cap_r", "front", "arm_l", reverse=True, ease=cap_ease),
        Seam("sleeve_l", "cap_l", "back", "arm_r", reverse=True, ease=cap_ease),
    ]
    g = build_garment([front, back, sr, sl], seams, spacing=spacing, density=density)
    g.meta.update(armhole_len=armhole_len, cap_height=ch, cap_half_len=polyline_length(cap_r),
                  hem_y=hem_y, torso_panels=["front", "back"], sleeve_panels=["sleeve_r", "sleeve_l"],
                  sleeve_circumference=2 * W,
                  girths={**_straight_body_girths(half_width, neck_u, front_neck_drop, back_neck_drop),
                          "upper arm": 2 * W})
    return g


def arm_wrap(shoulder_joint, elbow, radius, v_top, mirror=False, crown_offset=0.05, wrist=None):
    """Placement for a sleeve-like piece: wrapped around the arm axis, crown
    (v = v_top, u = 0) on top of the arm, +u toward the front. With `wrist`,
    the axis bends at the elbow (long sleeves follow the forearm instead of
    running straight into it)."""
    sj, el = np.array(shoulder_joint, float), np.array(elbow, float)
    wr = None if wrist is None else np.array(wrist, float)
    if mirror:
        sj[0] *= -1; el[0] *= -1
        if wr is not None:
            wr[0] *= -1
    down = (el - sj) / np.linalg.norm(el - sj)              # shoulder -> elbow
    up = np.array([-down[1], down[0], 0.0])                 # perpendicular, in the xy plane
    if up[1] < 0:
        up = -up                                            # crown sits on top of the arm
    origin = sj + down * crown_offset
    if wr is None:
        return axis_wrap(radius, origin, -down, up, (0, 0, 1), v_ref=v_top)
    # bent axis: origin -> elbow -> wrist (and beyond along the forearm)
    pts = np.array([origin, el, wr + (wr - el) / np.linalg.norm(wr - el) * 0.3])
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    S = np.concatenate([[0], np.cumsum(seg)])

    def place(uv):
        d = v_top - uv[:, 1]                                 # distance down the arm from the crown
        out = np.empty((len(uv), 3))
        for i, (u, s) in enumerate(zip(uv[:, 0], d)):
            k = int(np.clip(np.searchsorted(S, s) - 1, 0, len(seg) - 1))
            t = (s - S[k]) / seg[k]
            c = pts[k] + (pts[k + 1] - pts[k]) * t
            a = (pts[k + 1] - pts[k]) / seg[k]
            upk = up - a * (up @ a); upk /= np.linalg.norm(upk)
            side = np.cross(a, upk)
            if side[2] < 0:
                side = -side                                 # +u toward the front
            th = u / radius
            out[i] = c + radius * (np.cos(th) * upk + np.sin(th) * side)
        return out
    return place


def _placement_for(body, neck_v):
    """Hang the bodice so its neck point sits just above the body's shoulder
    line, wrapped on a cylinder clear of the torso."""
    hem_y = body.shoulder_top_y() + 0.025 - neck_v
    return hem_y, max(body.torso_wrap_radius(), 0.18)


def waist_y(body) -> float:
    """Natural waist: the narrowest torso section between the hip and the chest."""
    return body.section_y("waist")


def waist_placement(body, top_v):
    """Hang a lower-body piece with its top edge just above the natural waist."""
    if body is None:
        return 1.06 + 0.01 - top_v, 0.20
    return waist_y(body) + 0.01 - top_v, max(body.torso_wrap_radius(), 0.18)


def tshirt_for(m, chest_ease_cm=12.0, sleeve_ease_cm=8.0, scye_extra_cm=1.5, length_cm=None,
               body=None, armhole_clearance_cm=6.0, draft_body=None, **kw):
    """Draft a T-shirt to a person's measurements (Measurements, cm). `body`
    is the avatar it is placed on; `draft_body` (default: body) is the avatar
    of the person it is drafted for. Uses
    standard drafting relations:
      body width      = (chest + ease) / 4 per quarter
      shoulder point  = 0.45 x shoulder width from centre (wider tested worse:
                        p99 strain 6.5% -> 8.8% at sw/2 + 1 cm)
      neck width      = neck girth / 2pi x 1.45 (opening ~ neck + 6-8 cm ease)
      armhole depth   = with a body: the avatar's armpit depth + armhole_clearance_cm
                        (6 cm). Without one: chest / 8 + 6.5 cm + scye_extra_cm.
                        chest/8 + 6.5 is the fitted-bodice scye; knit tees are cut
                        deeper. Measured on the default avatar in A-pose: +0 cm ->
                        p99 strain 6.6%, +1.5 cm -> 3.5%; a shallower armhole is
                        the main cause of shoulder/underarm strain.
      sleeve width    = upper arm + ease
      length          = 0.38 x height (neck point to hem) unless given
    """
    cm = 0.01
    H = m.height * cm
    neck_v = (length_cm * cm) if length_cm else 0.38 * H
    shoulder_v = neck_v - 0.04 * H / 1.755
    draft_body = draft_body if draft_body is not None else body
    if draft_body is not None:
        # Draft from the avatar: armhole base sits armhole_clearance below its
        # armpit. Measured: clearance 6.0 cm -> p99 3.5%; 4.9 cm -> 6.5-7.3%.
        scye = draft_body.armpit_depth() + armhole_clearance_cm * cm
    else:
        scye = (m.chest / 8 + 6.5 + scye_extra_cm) * cm
    params = dict(
        half_width=(m.chest + chest_ease_cm) / 4 * cm,
        shoulder_u=0.45 * m.shoulder_width * cm,
        neck_u=m.neck * cm / (2 * np.pi) * 1.45,
        neck_v=neck_v, shoulder_v=shoulder_v, armhole_v=shoulder_v - scye,
        front_neck_drop=0.075 * H / 1.755, back_neck_drop=0.02 * H / 1.755,
        sleeve_half_width=(m.upper_arm + sleeve_ease_cm) / 2 * cm,
        sleeve_underarm=0.12 * H / 1.755,
    )
    params.update(kw)
    g = tshirt(body=body, **params)
    g.meta.update(drafted_for=m, chest_ease_cm=chest_ease_cm, sleeve_ease_cm=sleeve_ease_cm)
    return g


def a_line_skirt_for(m, body=None, waist_ease_cm=2.0, hip_ease_cm=5.0, length_cm=None,
                     spacing=0.015, density=0.15):
    """Two-piece A-line skirt drafted to measurements (cm).

    Each piece is an annular sector: the side seams are straight lines that
    meet at an apex above the waist, and the waist and hem are arcs centred
    on that apex. So every corner is exactly 90 deg: the pattern is trued by
    construction (compare the straight-hem skirt in examples/, which the
    seam check flags with a 155 deg dip at each side seam).

    The flare is not a free choice: it is the one that makes the piece exactly
    (hip + ease)/2 wide at hip depth while being (waist + ease)/2 at the waist.
      width(r) = 2 r alpha   (arc length at distance r from the apex)
      r1 = d * Ww / (Hw - Ww)  with d = waist-to-hip depth along the side
    """
    cm = 0.01
    H = m.height * cm
    Ww = (m.waist + waist_ease_cm) / 2 * cm          # each piece's waist arc
    Hw = (m.hip + hip_ease_cm) / 2 * cm              # each piece's width at hip depth
    if body is not None:
        d = body.section_y("waist") - body.section_y("seat")
    else:
        d = (0.604 - 0.505) * H
    if Hw <= Ww:
        raise ValueError("hip must be larger than waist for an A-line skirt")
    L = (length_cm * cm) if length_cm else 0.33 * H   # waist to hem, along the side
    r1 = d * Ww / (Hw - Ww)
    r2 = r1 + L
    alpha = Ww / (2 * r1)                            # half angle of the sector
    phi = lambda a, b, k=64: np.linspace(a, b, k)

    def arc(r, a, b):
        f = phi(a, b)
        return np.stack([r * np.sin(f), r2 - r * np.cos(f)], 1)

    def piece(name, angle):
        hem = arc(r2, -alpha, alpha)
        waist = arc(r1, alpha, -alpha)
        edges = [("hem", hem),
                 ("side_r", np.array([hem[-1], waist[0]])),
                 ("waist", waist),
                 ("side_l", np.array([waist[-1], hem[0]]))]
        top = float(waist[:, 1].max())
        if body is not None:
            hem_y, wrap = waist_placement(body, top)
        else:
            hem_y, wrap = 1.07 - top, 0.20
        return Panel(name, edges, cylinder_wrap(wrap, angle, hem_y)), hem_y

    (front, hem_y), (back, _) = piece("front", 0.0), piece("back", np.pi)
    seams = [Seam("front", "side_r", "back", "side_l", reverse=True),
             Seam("front", "side_l", "back", "side_r", reverse=True)]
    g = build_garment([front, back], seams, spacing=spacing, density=density)
    g.meta.update(hem_y=hem_y, torso_panels=["front", "back"], sleeve_panels=[],
                  skirt=dict(r1=r1, r2=r2, alpha_deg=float(np.degrees(alpha)), waist_to_hip=d),
                  girths={"waist": 2 * Ww, "hip": 2 * Hw})
    return g
