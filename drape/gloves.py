"""Gloves and mittens, drafted from the avatar's hand.

Two-layer construction (the way knit, fleece and stretch gloves are made):
a back piece and a palm piece of the same outline, sewn all the way round
except the cuff (and, for fingerless gloves, the finger ends). Fingers are
fanned out on the pattern so the finger tubes don't overlap on the cloth;
each tube is half the finger's girth plus ease, so the two layers close
round the finger.

Sizes come from the measurements (hand breadth, hand length, wrist) when
given, and otherwise from the avatar's hand: finger lengths from the
skeleton, finger girths in proportion to the hand breadth.

    from drape.gloves import glove_design
    d = glove_design(body, m, style="gloves")      # editor-format design (cm)
"""
from __future__ import annotations

import numpy as np

# finger girth / hand breadth (index, middle, ring, little, thumb): adult hand surveys
GIRTH_RATIO = {2: 0.72, 3: 0.72, 4: 0.68, 5: 0.60, 1: 0.78}
PALM_MID = 0.6       # where up the palm (fraction of knuckle height) the mid-palm girth is read
THUMB_ROOT = 1.4      # thumb tube width at its root / at the thumb itself
NAMES = {1: "thumb", 2: "index", 3: "middle", 4: "ring", 5: "little"}
STYLES = {
    "gloves": dict(cuff=5.0, fingers="full", label="Gloves"),
    "mittens": dict(cuff=6.0, fingers="mitten", label="Mittens"),
    "fingerless": dict(cuff=4.0, fingers="open", label="Fingerless gloves"),
    "long_gloves": dict(cuff=20.0, fingers="full", label="Long gloves"),
}


def _u(v):
    v = np.asarray(v, float)
    return v / (np.linalg.norm(v) + 1e-12)


def _joint(body, name):
    return np.asarray(body.human.joint(name), float)


def hand_frame(body, side="r"):
    """The hand's own axes (m): wrist o, d toward the fingers, f across toward
    the index finger, n_back out of the back of the hand, fa along the forearm
    (toward the hand)."""
    J = lambda n: _joint(body, f"{side}-{n}")
    o = J("hand")
    mcp = np.array([J(f"finger-{k}-1") for k in (2, 3, 4, 5)])
    d = _u(mcp.mean(0) - o)
    f = mcp[0] - mcp[3]
    f = _u(f - (f @ d) * d)
    n = np.cross(f, d)
    if (J("finger-1-4") - o) @ n > 0:      # the thumb curls toward the palm
        n = -n
    fa = _u(o - J("elbow"))
    return o, d, f, n, fa


def _hand_verts(body, side):
    from .freeform import _surf
    S = _surf(body)
    if S.regions is None:
        raise ValueError("gloves need a mesh avatar (with hands)")
    x0 = _joint(body, f"{side}-hand")[0]
    return S.V[(S.regions["hand"] > 0.5) & (np.sign(S.V[:, 0]) == np.sign(x0))]


def _forearm_girth(body, side, at_cm):
    """Girth (cm) of the forearm at_cm from the wrist, from the avatar's mesh."""
    from scipy.spatial import ConvexHull
    from .freeform import _surf
    S = _surf(body)
    o, _, f, _, fa = hand_frame(body, side)
    p = o - fa * at_cm / 100
    x0 = o[0]
    sel = ((S.regions["arm"] + S.regions["hand"]) > 0.5) & (np.sign(S.V[:, 0]) == np.sign(x0))
    D = S.V[sel] - p
    s = D @ fa
    Q = D - np.outer(s, fa)
    ok = (np.abs(s) < 0.006) & (np.linalg.norm(Q, axis=1) < 0.08)
    if ok.sum() < 8:
        return None
    e1 = _u(f - (f @ fa) * fa)
    e2 = np.cross(fa, e1)
    return float(ConvexHull(np.c_[Q[ok] @ e1, Q[ok] @ e2]).area * 100)


def hand_sizes(body, m=None, side="r"):
    """Everything a glove pattern needs, in cm (and the hand frame)."""
    o, d, f, n, fa = hand_frame(body, side)
    J = lambda nm: _joint(body, f"{side}-{nm}")
    V = _hand_verts(body, side)
    rel = V - o
    v = rel @ d
    mcp_v = {k: float((J(f"finger-{k}-1") - o) @ d) * 100 for k in (2, 3, 4, 5)}
    palm = ((v > 0.005) & (v < min(mcp_v.values()) / 100) & (np.abs(rel @ n) < 0.03)
            & ~(((rel @ f) > 0.03) & ((rel @ n) < -0.01)))                  # the thumb's root left out
    across = rel[palm] @ f
    breadth_mesh = float(np.ptp(across)) * 100 if palm.sum() > 10 else 8.0
    H = float(getattr(m, "height", None) or body.height * 100) if m is not None else body.height * 100
    # across the knuckles, thumb excluded (the mesh reading includes the thumb's base)
    girth_m = getattr(m, "hand_girth", None)
    breadth = float(getattr(m, "hand_breadth", None) or (girth_m / 2.35 if girth_m else min(breadth_mesh, 0.0485 * H)))
    thick_back = float(np.percentile(rel[palm] @ n, 98)) * 100 if palm.sum() > 10 else 1.3
    thick_palm = float(np.percentile(-(rel[palm] @ n), 98)) * 100 if palm.sum() > 10 else 1.3
    wrist = float(getattr(m, "wrist", None) or 0.095 * H)
    length = {}
    for k in (1, 2, 3, 4, 5):
        P = [J(f"finger-{k}-{i}") for i in (1, 2, 3, 4)]
        segs = [float(np.linalg.norm(P[i + 1] - P[i])) * 100 for i in range(3)]
        length[k] = segs
    # scale finger lengths to a measured hand length (wrist crease to middle fingertip)
    hl_mesh = mcp_v[3] + sum(length[3]) + 0.3
    if m is not None and getattr(m, "hand_length", None):
        sc = float(m.hand_length) / hl_mesh
        length = {k: [s * sc for s in v_] for k, v_ in length.items()}
        mcp_v = {k: v_ * sc for k, v_ in mcp_v.items()}
    girth = {k: GIRTH_RATIO[k] * breadth for k in GIRTH_RATIO}
    tip_u = {k: float((J(f"finger-{k}-4") - o) @ f) * 100 for k in (2, 3, 4, 5)}
    # how far the thumb's root (the ball of the thumb) stands out on the palm side
    vt_ = float((J("finger-1-2") - o) @ d)
    root = (v > 0.005) & (v < vt_ + 0.015) & ((rel @ f) > 0.0)
    thenar = float(np.percentile(-(rel[root] @ n), 98)) * 100 if root.sum() > 10 else 2.5
    finger_n = float(np.mean([(J(f"finger-{k}-1") - o) @ n for k in (2, 3, 4, 5)])) * 100
    # the palm's girth part-way up, over the ball of the thumb (wider than a straight
    # line from wrist to knuckles); thumb itself left out
    palm_mid = None
    vm = min(mcp_v.values()) / 100 * PALM_MID
    sl = (np.abs(v - vm) < 0.0025) & ~(((rel @ f) > 0.03) & ((rel @ n) < -0.01)) & (np.linalg.norm(rel - np.outer(v, d), axis=1) < 0.07)
    if sl.sum() > 8:
        from scipy.spatial import ConvexHull
        palm_mid = float(ConvexHull(np.c_[rel[sl] @ f, rel[sl] @ n]).area * 100)
    return dict(frame=(o, d, f, n, fa), tip_u=tip_u, palm_mid=palm_mid, thenar=thenar, finger_n=finger_n, breadth=breadth, hand_girth=float(girth_m) if girth_m else 2.35 * breadth, wrist=wrist,
                mcp_v=mcp_v, length=length, girth=girth, thick_back=thick_back, thick_palm=thick_palm,
                thumb_v=float((J("finger-1-2") - o) @ d) * 100,
                thumb_dir=_thumb_angle(body, side, o, d, f))


def _thumb_angle(body, side, o, d, f):
    a = _joint(body, f"{side}-finger-1-4") - _joint(body, f"{side}-finger-1-2")
    ang = np.degrees(np.arctan2(a @ f, a @ d))
    return float(np.clip(ang, 30.0, 55.0))


# --------------------------------------------------------------- the outline --
def glove_outline(hs, style="gloves", ease=1.08, cuff_cm=None, forearm_girth=None):
    """The back piece's outline (cm, wrist at the origin, fingers up, thumb at
    +u) as a shapely polygon, the open edges as chords [(name, p, q)], and the
    lobes (where each finger tube is on the pattern)."""
    from shapely.geometry import LineString, Point, Polygon
    from shapely.ops import unary_union
    st = STYLES[style]
    cuff = float(st["cuff"] if cuff_cm is None else cuff_cm)
    P = hs["hand_girth"] / 4 * ease                 # half-width at the knuckles
    Wr = hs["wrist"] / 4 * ease
    Wc = (forearm_girth or hs["wrist"] * (1 + 0.012 * cuff)) / 4 * ease
    Wc = max(Wc, Wr)
    vi, vp = hs["mcp_v"][2], hs["mcp_v"][5]
    vm = PALM_MID * min(vi, vp)
    Pm = max(Wr + (P - Wr) * PALM_MID, (hs.get("palm_mid") or 0) / 4 * ease)
    body_poly = Polygon([(-Wc, -cuff), (Wc, -cuff), (Wr, 0), (Pm, vm), (P, vi), (-P, vp), (-Pm, vm), (-Wr, 0)])
    shapes, lobes, chords = [body_poly], [], []
    w = {k: hs["girth"][k] / 2 * ease + 0.3 for k in hs["girth"]}
    us = [2 * P * x for x in (0.375, 0.125, -0.125, -0.375)]
    fingers = (2, 3, 4, 5)
    if st["fingers"] == "mitten":
        caps = []
        for k, u in zip(fingers, us):
            L = sum(hs["length"][k]) + 2.0           # room to curl the fingers and cover the tips
            ut = hs["tip_u"][k] * 1.1                # as wide as the fingers are spread
            a = np.array([u, hs["mcp_v"][k] - 1.0])
            b = a + _u([ut - u, L + 1.0 - w[k] / 2]) * (L + 1.0 - w[k] / 2)
            caps.append(LineString([a, b]).buffer(w[k] / 2 + 0.25, quad_segs=8))
        shapes.append(unary_union(caps + [Polygon([(P, vi), (-P, vp), (-P, vp + 1), (P, vi + 1)])]).convex_hull)
    else:
        c = 2.0                                     # the crotch: this far up the fingers
        s0 = abs(us[0] - us[1])
        need = max((w[a] + w[b]) / 2 + 0.15 for a, b in zip(fingers, fingers[1:]))
        dth = max(0.0, np.arctan((need - s0) / c))
        for k, u, j in zip(fingers, us, (1.5, 0.5, -0.5, -1.5)):
            th = dth * j
            dr = np.array([np.sin(th), np.cos(th)])
            base = np.array([u, hs["mcp_v"][k]])
            if st["fingers"] == "open":
                L = hs["length"][k][0] + 0.8
                end = base + dr * L
                shapes.append(LineString([base - dr * 1.5, end]).buffer(w[k] / 2, cap_style=2))
                pr = np.array([dr[1], -dr[0]]) * w[k] / 2
                chords.append((f"end_{NAMES[k]}", end + pr, end - pr))
            else:
                L = sum(hs["length"][k]) + 1.2             # over the fingertip, with room to bend
                shapes.append(LineString([base - dr * 1.5, base + dr * (L - w[k] / 2)]).buffer(w[k] / 2, quad_segs=10))
            lobes.append({"joint": k, "base": base.tolist(), "dir": dr.tolist(), "w": w[k], "s0": 0.0})
    # thumb: from the side seam at the thumb's base, angled out
    vt = max(1.5, hs["thumb_v"] - 0.5)
    ut = float(np.interp(vt, [0, vm, vi], [Wr, Pm, P])) - 0.4
    base = np.array([ut, vt])
    lead = 1.2                                       # webbing between thumb and hand
    others = unary_union(shapes[1:]) if len(shapes) > 1 else None
    # the thumb leans out from the hand; on the pattern it must clear the index finger
    for ang in np.arange(max(hs["thumb_dir"], 45.0), 86.0, 2.5):
        th = np.radians(ang)
        dr = np.array([np.sin(th), np.cos(th)])
        if st["fingers"] == "open":
            L = lead + hs["length"][1][1] + 0.6
            end = base + dr * L
            tshape = LineString([base - dr * 1.0, end]).buffer(w[1] / 2, cap_style=2)
        else:
            L = lead + hs["length"][1][1] + hs["length"][1][2] + 1.8
            tshape = LineString([base - dr * 1.0, base + dr * (L - w[1] / 2)]).buffer(w[1] / 2, quad_segs=10)
        # wider at the root: the thumb's base and the ball of the thumb are much thicker
        # than the thumb itself, and a straight tube pulls tight round them
        root = Point(*(base - dr * 1.0)).buffer(w[1] * THUMB_ROOT / 2, quad_segs=10)
        tshape = unary_union([tshape, unary_union([root, Point(*(base + dr * (lead + 3.0))).buffer(w[1] / 2)]).convex_hull])
        if others is None or tshape.distance(others) > 0.6:
            break
    shapes.append(tshape)
    if st["fingers"] == "open":
        pr = np.array([dr[1], -dr[0]]) * w[1] / 2
        chords.append(("end_thumb", end + pr, end - pr))
    # the web between thumb and hand: a gusset of extra cloth up the side seam
    side_v = min(vt + 3.5, vi - 1.0)
    side_u = float(np.interp(side_v, [0, vm, vi], [Wr, Pm, P]))
    shapes.append(Polygon([tuple(base - dr * 1.0), tuple(base + dr * (lead + 0.8) + np.array([dr[1], -dr[0]]) * w[1] / 2),
                           (side_u, side_v), (side_u - 1.0, side_v), (ut - 1.0, vt)]).convex_hull)
    lobes.append({"joint": 1, "base": base.tolist(), "dir": dr.tolist(), "w": w[1], "s0": lead})
    poly = unary_union(shapes)
    poly = poly.buffer(0.25, quad_segs=6).buffer(-0.25, quad_segs=6)     # round the crotches a little
    if poly.geom_type != "Polygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    from shapely.geometry.polygon import orient
    poly = orient(Polygon(poly.exterior).simplify(0.03), 1.0)
    chords.insert(0, ("cuff", np.array([-Wc, -cuff]), np.array([Wc, -cuff])))
    return poly, chords, lobes, dict(P=P, Pm=Pm, vm=vm, Wr=Wr, Wc=Wc, cuff=cuff)


def _split(poly, chords):
    """The outline as editor edges: open chords become their own edges (named),
    the sewn runs between them are named after the openings either side."""
    R = np.asarray(poly.exterior.coords)[:-1]
    keys = []
    for name, p, q in chords:
        ip = int(np.argmin(np.linalg.norm(R - p, axis=1)))
        iq = int(np.argmin(np.linalg.norm(R - q, axis=1)))
        keys.append((ip, name, "start"))
        keys.append((iq, name, "end"))
    keys.sort()
    # rotate the ring so it starts at the first key
    k0 = keys[0][0]
    R = np.roll(R, -k0, axis=0)
    keys = [((i - k0) % len(R), n, t) for i, n, t in keys]
    keys.sort()
    verts, edges = [], []
    m = len(keys)
    for j in range(m):
        i, name, _ = keys[j]
        i2, name2, _ = keys[(j + 1) % m]
        stop = i2 if j + 1 < m else len(R)
        pts = np.vstack([R[i:stop + 1] if j + 1 < m else np.vstack([R[i:], R[:1]])])
        verts.append(R[i].tolist())
        L_path = float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())
        L_chord = float(np.linalg.norm(pts[-1] - pts[0]))
        if name == name2 and L_path < 1.1 * L_chord + 0.05:      # across an opening
            edges.append({"name": name, "c1": None, "c2": None, "elastic": False})
        else:
            a, b = sorted((name, name2))
            nm = "seam" if a == b else f"seam_{a.replace('end_', '')}_{b.replace('end_', '')}"
            edges.append({"name": nm, "c1": None, "c2": None, "elastic": False,
                          "pts": np.round(pts, 3).tolist(), "sa": 0.5})
    return verts, edges


def glove_design(body, m=None, style="gloves", ease=1.08, cuff_cm=None):
    """A pair of gloves (or mittens) as an editor-format design (cm)."""
    hs = hand_sizes(body, m, "r")
    st = STYLES[style]
    cuff = float(st["cuff"] if cuff_cm is None else cuff_cm)
    fg = _forearm_girth(body, "r", cuff) if cuff > 6 else None
    poly, chords, lobes, dims = glove_outline(hs, style, ease, cuff, fg)
    verts, edges = _split(poly, chords)
    pieces, seams = [], []
    for hand in ("r", "l"):
        o, d, f, n, fa = hand_frame(body, hand)
        for layer, sgn in (("back", 1), ("palm", -1)):
            nn = sgn * n
            # cut right side up: (u, v, out) must be right-handed, else the piece is mirrored
            mirror = bool(np.cross(f, d) @ nn < 0)
            if mirror:
                from shapely.affinity import scale
                from shapely.geometry.polygon import orient
                mp = orient(scale(poly, xfact=-1, yfact=1, origin=(0, 0)), 1.0)
                mc = [(nm, p * [-1, 1], q * [-1, 1]) for nm, p, q in chords]
                V, E = _split(mp, mc)
            else:
                V, E = [list(p) for p in verts], [dict(e) for e in edges]
            name = f"{layer}_{hand}"
            pieces.append({"name": name, "verts": V, "edges": E, "shape": {"type": "custom"},
                           "role": "body",          # gloves on their own are the garment (stage 1)
                           "place": {"glove": {"hand": hand, "layer": sgn, "mirror": mirror,
                                               "lobes": lobes, "dims": dims,
                                               "mitten": st["fingers"] == "mitten"},
                                     "mode": "glove", "rotate": 0, "offset_cm": 0.3, "at": "center", "layer": 0}})
        for e in edges:
            if e["name"].startswith("seam"):
                seams.append({"a": f"back_{hand}.{e['name']}", "b": f"palm_{hand}.{e['name']}", "ease": 0})
    return {"pieces": pieces, "seams": seams, "spacing_cm": 0.5, "fine_sdf": 0.003, "body_offset": 0.002,
            "style": style}


# ------------------------------------------------------------- placement --
def _ellipse_point(half_len, B, frac):
    """A point on the half-ellipse of semi-axes (A, B) whose half-perimeter is
    half_len, at arc fraction frac (-1 = one side, 0 = top, +1 = other side).
    Returns (lateral, normal) offsets. Vectorised."""
    half_len, B, frac = (np.broadcast_to(np.asarray(a, float), np.shape(frac)) for a in (half_len, B, frac))
    lo, hi = np.full(half_len.shape, 1e-4), np.maximum(half_len, 1e-3)
    for _ in range(40):                       # A from the half-perimeter (Ramanujan)
        A = 0.5 * (lo + hi)
        Bc = np.minimum(B, half_len / 1.6)
        hp = 0.5 * np.pi * (3 * (A + Bc) - np.sqrt((3 * A + Bc) * (A + 3 * Bc)))
        lo, hi = np.where(hp < half_len, A, lo), np.where(hp < half_len, hi, A)
    A = 0.5 * (lo + hi)
    th = np.linspace(-np.pi / 2, np.pi / 2, 65)
    P = np.stack([A[:, None] * np.sin(th), Bc[:, None] * np.cos(th)], -1)        # (n, 65, 2)
    L = np.concatenate([np.zeros((len(A), 1)), np.cumsum(np.linalg.norm(np.diff(P, axis=1), axis=2), 1)], 1)
    target = (np.clip(frac, -1, 1) + 1) / 2 * L[:, -1]
    out = np.empty((len(A), 2))
    for j in range(2):
        out[:, j] = [np.interp(t, Li, Pi[:, j]) for t, Li, Pi in zip(target, L, P)]
    return out[:, 0], out[:, 1]


def glove_place(body, spec):
    """uv (m, pattern coordinates) -> xyz. Each layer starts as one half of a
    closed glove: the palm, cuff and every finger are wrapped half-way round
    by each layer, so the seams already meet and nothing has to be pulled
    round a finger while sewing."""
    from .freeform import _surf
    S = _surf(body)
    hand, sgn = spec["hand"], float(spec["layer"])
    hs = hand_sizes(body, getattr(body, "measurements", None), hand)
    o, d, f, n, fa = hs["frame"]
    J = lambda nm: _joint(body, f"{hand}-{nm}")
    dims = {k: v / 100 for k, v in spec["dims"].items()}
    vk = min(hs["mcp_v"][k] for k in (2, 5)) / 100
    vi, vp = hs["mcp_v"][2] / 100, hs["mcp_v"][5] / 100
    cn = (hs["thick_back"] - hs["thick_palm"]) / 200                    # middle of the palm along n
    B_palm = (hs["thick_back"] + hs["thick_palm"]) / 200 + 0.005
    B_wrist = hs["wrist"] / (2 * np.pi) * 0.8 / 100 + 0.004
    D_t = (hs["thenar"] + cn * 100) / 100 + 0.006        # palm-side depth needed over the thumb's root
    vt3 = hs["thumb_v"] / 100 + 0.02
    cfing = hs["finger_n"] / 100
    B_fing = max(hs["girth"][3] / (2 * np.pi) / 100 + 0.006, 0.014)
    e1c = _u(f - (f @ fa) * fa)
    nc = _u(n - (n @ fa) * fa - (n @ e1c) * e1c)
    a3 = _u(J("finger-3-4") - J("finger-3-1"))
    mitten = spec.get("mitten")
    mir = -1.0 if spec.get("mirror") else 1.0
    lobes = []
    for lb in spec["lobes"]:
        k = lb["joint"]
        b3 = J("finger-1-2") if k == 1 else J(f"finger-{k}-1")
        a = _u(J(f"finger-{k}-4") - b3)
        if k == 1:      # the thumb: seams along its sides as seen in the hand's plane
            ap = _u(a - (a @ n) * n)
            lat = _u(np.cross(ap, n))
            lat = lat * np.sign(lat @ f + 1e-9)
            lat = _u(lat - (lat @ a) * a)
        else:
            lat = _u(f - (f @ a) * a)
        nf = _u(np.cross(a, lat))
        nf = nf * np.sign(nf @ n + 1e-9)
        lobes.append(dict(b2=np.array(lb["base"]) / 100, d2=np.array(lb["dir"]), w=lb["w"] / 100,
                          s0=lb.get("s0", 0.0) / 100, b3=b3, a=a, lat=lat, nf=nf, k=k))

    def half_width(v):
        """The pattern's half-width (m) at height v, below the fingers."""
        return np.where(v < 0, dims["Wr"] + (dims["Wc"] - dims["Wr"]) * np.clip(-v / max(dims["cuff"], 1e-3), 0, 1),
                        np.interp(v, [0.0, dims.get("vm", vk / 2), vk], [dims["Wr"], dims.get("Pm", (dims["Wr"] + dims["P"]) / 2), dims["P"]]))

    def place(uv):
        uv = np.asarray(uv, float)
        u, v = mir * uv[:, 0], uv[:, 1]
        hw = half_width(v)
        if mitten:
            hw = np.where(v > vk, np.maximum(hw, np.abs(u) + 1e-3), hw)
        frac = np.clip(u / hw, -1, 1)
        Bv = np.interp(v, [-0.01, 0.03], [B_wrist, B_palm])
        cv = np.full(len(v), cn)
        if mitten:            # past the knuckles: round the fingers, which sit higher than the palm's middle
            Bv = np.where(v > vk, np.interp(v, [vk, vk + 0.03], [B_palm, B_fing]), Bv)
            cv = np.interp(v, [vk - 0.01, vk + 0.02], [cn, cfing])
        lat_off, nrm_off = _ellipse_point(2 * hw, Bv, frac)
        nrm_off = sgn * nrm_off
        hand_c = o + np.outer(v, d) + np.outer(cv, n)
        if mitten:            # past the knuckles the mitten follows the fingers' curl
            past = np.clip(v - vk, 0, None)
            hand_c = hand_c + np.outer(past, a3 - d)
        arm_c = o + np.outer(v, fa)
        # beyond the palm's side (the thumb's web): carry on outward, round toward this layer's side
        over = np.clip(np.abs(u) - hw, 0, None)
        sg = np.sign(u)
        cl, cn_ = (0.95, 0.3) if sgn > 0 else (0.3, 0.95)     # the palm layer goes down round the thumb's root
        lat_off = lat_off + over * sg * cl
        nrm_off = nrm_off + sgn * over * cn_
        Xa = arm_c + np.outer(lat_off, e1c) + np.outer(nrm_off, nc)
        Xh = hand_c + np.outer(lat_off, f) + np.outer(nrm_off, n)
        wv = np.clip((v + 0.02) / 0.04, 0, 1)[:, None]          # bend smoothly at the wrist
        wv = wv * wv * (3 - 2 * wv)
        X = (1 - wv) * Xa + wv * Xh
        best = np.full(len(u), np.inf)
        for L in lobes:
            q = np.c_[u, v] - L["b2"]
            s = q @ L["d2"]
            t = q @ np.array([L["d2"][1], -L["d2"][0]])
            # every point past the lobe's base belongs to its nearest tube; cloth wider than
            # the tube (the web, rounded crotches) wraps on round it
            inside = (s > -0.002) & (np.abs(t) <= L["w"] / 2 + (0.03 if L["k"] == 1 else 0.012))
            score = np.abs(t) / L["w"] - 0.5 * (s > 0.01)
            take = inside & (score < best)
            if not take.any():
                continue
            best[take] = score[take]
            sf = s[take] - L["s0"]
            R = L["w"] / np.pi + 0.0005
            th = np.clip(t[take] / R, -0.95 * np.pi, 0.95 * np.pi)       # arc length -> angle
            Rr = R + 0.003 * np.clip(np.abs(th) - np.pi / 2, 0, None)     # past the seam: just outside the other layer
            Y = (L["b3"] + np.outer(sf, L["a"]) + np.outer(Rr * np.sin(th), L["lat"])
                 + np.outer(sgn * Rr * np.cos(th), L["nf"]))
            span = L["s0"] + (0.02 if L["k"] == 1 else 0.012)
            wgt = np.clip(s[take] / span, 0, 1)
            wgt = wgt * wgt * (3 - 2 * wgt)
            X[take] = (1 - wgt)[:, None] * X[take] + wgt[:, None] * Y
        return S.push_out(X, 0.002)
    return place
