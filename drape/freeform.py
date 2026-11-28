"""Design from scratch: your own pieces, placed anywhere on the body.

A design is plain JSON (what the studio sends and saves):

    {"pieces": [{"name": "front",
                 "edges": [{"name": "bottom", "pts": [[-25, 0], [25, 0]]}, ...],   # cm, closed outline
                 "place": {"anchor": [x, y, z],        # a point on the skin (m), or
                           "landmark": "chest_front",  # a named spot (see LANDMARKS)
                           "mode": "wrap" | "flat",
                           "rotate": 0,                # degrees, turns the piece on the body
                           "offset_cm": 1.5,           # gap between skin and fabric to start
                           "layer": 0}}],              # 1 = worn over layer-0 pieces, 2 = over those
     "seams": [{"a": "front.left", "b": "back.right", "ease": 0, "reverse": null}]}

Placement. The piece's centre goes on the anchor, seen from outside: the
drawing's right is your right as you look at the avatar, its top points up
the body (or toward the shoulder/hip on a limb).

  wrap  curls the piece around the body part under the anchor (torso, neck,
        head, upper/lower arm, thigh/shin), like a sheet wrapped round a
        cylinder: lengths are kept exactly.
  flat  lays it on the tangent plane at the anchor (pockets, patches, hoods
        to start with). Gravity and seams do the rest.

Either way, any point that would start inside the body is pushed out to
offset_cm, so a drape never starts tangled.

Seams. `reverse` = None works out which way round the two edges go from where
the pieces sit on the body (ends that are closer together get sewn together),
so a beginner never has to think about edge direction.
"""
from __future__ import annotations

import numpy as np

from .pattern import Panel, Seam, build_garment, polyline_length

cm = 0.01

# named spots: (region, height reference, direction in the horizontal plane or along the limb)
LANDMARKS = {
    "chest_front": "Chest, front", "chest_back": "Chest, back",
    "waist_front": "Waist, front", "waist_back": "Waist, back",
    "hip_front": "Hips, front", "hip_back": "Hips, back",
    "hip_right": "Right hip", "hip_left": "Left hip",
    "upper_arm_right": "Right upper arm", "upper_arm_left": "Left upper arm",
    "forearm_right": "Right forearm", "forearm_left": "Left forearm",
    "thigh_right": "Right thigh", "thigh_left": "Left thigh",
    "neck_front": "Neck, front", "neck_back": "Neck, back", "head_back": "Back of the head",
}


# ------------------------------------------------------------ body helpers --
class _Surf:
    """Nearest-vertex surface queries (no SDF grid needed, so placement is
    instant even before the collision grid is built)."""

    def __init__(self, body):
        from scipy.spatial import cKDTree
        self.body = body
        V, F = body.mesh()
        V = np.asarray(V, float); F = np.asarray(F)
        N = np.zeros_like(V)
        fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
        for k in range(3):
            np.add.at(N, F[:, k], fn)
        N /= np.linalg.norm(N, axis=1, keepdims=True) + 1e-12
        if ((V - V.mean(0)) * N).sum() < 0:    # make them point out
            N = -N
        self.V, self.N, self.tree = V, N, cKDTree(V)
        h = getattr(body, "human", None)
        self.regions = h.regions if h is not None else None

    def dist(self, P):
        """Signed distance (approx.): + outside. Also the outward normal."""
        _, i = self.tree.query(P)
        n = self.N[i]
        return ((P - self.V[i]) * n).sum(1), n, i

    def push_out(self, P, clearance, iters=6):
        P = P.copy()
        for _ in range(iters):
            d, n, _ = self.dist(P)
            bad = d < clearance
            if not bad.any():
                break
            P[bad] += (clearance - d[bad])[:, None] * n[bad]
        return P

    def region(self, p):
        _, i = self.tree.query(p)
        if self.regions is None:
            return "torso"
        w = {k: float(v[i]) for k, v in self.regions.items()}
        return max(w, key=w.get)


def _surf(body):
    s = getattr(body, "_freeform_surf", None)
    if s is None:
        s = _Surf(body)
        try:
            body._freeform_surf = s
        except AttributeError:
            pass
    return s


def _joint(body, name):
    return np.asarray(body.human.joint(name), float)


def _limb(body, p, kind):
    """(origin, direction toward the body) of the limb segment nearest p."""
    side = "l" if np.sign(_joint(body, "l-shoulder")[0]) == np.sign(p[0]) else "r"
    chain = ([f"{side}-shoulder", f"{side}-elbow", f"{side}-hand"] if kind == "arm"
             else [f"{side}-upper-leg", f"{side}-knee", f"{side}-ankle"])
    J = [_joint(body, n) for n in chain]
    best = None
    for a, b in zip(J, J[1:]):
        d = b - a
        t = np.clip((p - a) @ d / (d @ d), 0, 1)
        dist = np.linalg.norm(a + t * d - p)
        if best is None or dist < best[0]:
            best = (dist, a, b)
    _, a, b = best
    return a, (a - b) / np.linalg.norm(a - b)        # points from the far end toward the body


def body_axis(body, p):
    """The axis the body part under p wraps around: (origin, unit direction 'up')."""
    if getattr(body, "kind", "") != "mesh":
        return np.array([0.0, p[1], 0.0]), np.array([0.0, 1.0, 0.0])
    reg = _surf(body).region(p)
    if reg in ("arm", "hand"):
        return _limb(body, p, "arm")
    if reg in ("leg", "foot"):
        return _limb(body, p, "leg")
    if reg == "head":
        h = _joint(body, "head")
        return np.array([h[0], p[1], h[2]]), np.array([0.0, 1.0, 0.0])
    return np.array([0.0, p[1], _torso_center_z(body, p[1])]), np.array([0.0, 1.0, 0.0])


def _torso_center_z(body, y):
    """Middle of the torso front-to-back at height y (extent, not vertex
    median: the mesh is denser at the front)."""
    S = _surf(body)
    if S.regions is None:
        return 0.0
    V = S.V
    sel = (S.regions["torso"] > 0.5) & (np.abs(V[:, 1] - y) < 0.02)
    if sel.sum() < 6:
        sel = (S.regions["torso"] > 0.5)
    z = V[sel, 2]
    return float(0.5 * (z.min() + z.max()))


def landmark(body, name):
    """A named spot on the skin: (point, outward normal)."""
    L = body.lines
    side = {"right": -1, "left": +1}          # the avatar's right is -x (it faces +z)
    if name.startswith(("chest", "waist", "hip")):
        part, where = name.split("_")
        y = {"chest": L["chest"], "waist": L["waist"], "hip": L["hip"]}[part]
        d = {"front": (0, 1), "back": (0, -1), "right": (-1, 0), "left": (1, 0)}[where]
        return _march(body, np.array([0.0, y, _torso_center_z(body, y)]), np.array([d[0], 0.0, d[1]]))
    if name.startswith(("upper_arm", "forearm", "thigh")):
        s = side[name.rsplit("_", 1)[1]]
        sd = "l" if np.sign(_joint(body, "l-shoulder")[0]) == s else "r"
        a, b, f = {"upper_arm": ("shoulder", "elbow", 0.45), "forearm": ("elbow", "hand", 0.4),
                   "thigh": ("upper-leg", "knee", 0.35)}[name.rsplit("_", 1)[0]]
        A, B = _joint(body, f"{sd}-{a}"), _joint(body, f"{sd}-{b}")
        o = A + f * (B - A)
        d = np.array([0.0, 0.0, 1.0])                # front of the limb
        d -= (d @ (B - A)) / ((B - A) @ (B - A)) * (B - A)
        return _march(body, o, d)
    if name in ("neck_front", "neck_back"):
        y = body.shoulder_top_y() + 0.04
        return _march(body, np.array([0.0, y, _torso_center_z(body, y)]),
                      np.array([0.0, 0.0, 1.0 if name == "neck_front" else -1.0]))
    if name == "head_back":
        h = _joint(body, "head")
        return _march(body, h + [0, 0.04, 0], np.array([0.0, 0.0, -1.0]))
    raise KeyError(f"unknown landmark {name!r}; known: {', '.join(LANDMARKS)}")


def _march(body, o, d, step=0.002, far=0.6):
    S = _surf(body)
    d = d / np.linalg.norm(d)
    ts = np.arange(0, far, step)
    P = o + ts[:, None] * d
    dist, n, _ = S.dist(P)
    # first exit from the body along the ray (the start point is inside);
    # require a few outside samples in a row so a crease doesn't count
    out = dist > 0
    run = np.convolve(out.astype(int), np.ones(4, int), mode="full")[3:len(out) + 3] == 4
    k = int(np.argmax(run)) if run.any() else len(ts) - 1
    p = P[k]
    return p, S.dist(p[None])[1][0]


# --------------------------------------------------------------- placement --
_TEMPLATE_CACHE = {}


def _template_place(body, t):
    """The placement a pattern-library block gives one of its pieces (a piece
    converted from a template keeps hanging exactly where the template put it)."""
    import json
    from .blocks import draft_block
    key = (id(body), t["block"], json.dumps(t.get("params") or {}, sort_keys=True))
    if key not in _TEMPLATE_CACHE:
        g, _ = draft_block(t["block"], body, getattr(body, "measurements", None), t.get("params") or {})
        _TEMPLATE_CACHE[key] = {p.name: p.place for p in g.meta["panels"]}
        if len(_TEMPLATE_CACHE) > 32:
            _TEMPLATE_CACHE.pop(next(iter(_TEMPLATE_CACHE)))
    f = _TEMPLATE_CACHE[key][t["piece"]]
    if not t.get("mirror"):
        return f
    M = np.array([-1.0, 1.0])
    return lambda uv: f(uv * M) * np.array([-1.0, 1.0, 1.0])


def template_design(block, body, m, params=None):
    """A pattern-library garment as an editable design (cm, editor format):
    every piece keeps its exact outline, its edge names, its seams (direction
    and ease included) and the template's placement on the body."""
    from .blocks import draft_block
    g, info = draft_block(block, body, m, params or {})
    pieces = []
    for k, p in enumerate(g.meta["panels"]):
        edges, verts = [], []
        for n, e in p.edges:
            pts = np.round(np.asarray(e) * 100, 3)
            verts.append(pts[0].tolist())
            ed = {"name": n, "c1": None, "c2": None, "elastic": False}
            if len(pts) > 2:
                ed["pts"] = pts.tolist()
            edges.append(ed)
        pieces.append({"name": p.name, "verts": verts, "edges": edges, "shape": {"type": "custom"},
                       "role": "sleeve" if p.name.startswith("sleeve") else "body",
                       "place": {"template": {"block": block, "params": info["params"], "piece": p.name},
                                 "mode": "template", "rotate": 0, "offset_cm": 0.3, "at": "center", "layer": 0}})
    seams = [{"a": f"{s.panel_a}.{s.edge_a}", "b": f"{s.panel_b}.{s.edge_b}", "ease": round(float(s.ease), 4),
              "reverse": bool(s.reverse)} for s in g.meta["seam_defs"]]
    return {"pieces": pieces, "seams": seams, "from_block": block}


def editor_to_design(d):
    """The studio's editor format (verts + edges with optional cubic controls
    or a fixed polyline) -> the plain design format build_design reads."""
    out = []
    for pc in d["pieces"]:
        if "verts" not in pc:
            out.append(pc)
            continue
        V, n, edges = pc["verts"], len(pc["verts"]), []
        for i, e in enumerate(pc["edges"]):
            a, b = np.asarray(V[i], float), np.asarray(V[(i + 1) % n], float)
            if e.get("pts"):
                pts = np.asarray(e["pts"], float)
            elif e.get("c1"):
                t = np.linspace(0, 1, 25)[:, None]
                c1, c2 = np.asarray(e["c1"]), np.asarray(e["c2"])
                pts = (1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * c1 + 3 * (1 - t) * t ** 2 * c2 + t ** 3 * b
            else:
                pts = np.stack([a, b])
            edges.append({"name": e["name"], "pts": pts.tolist(), "elastic": e.get("elastic") or None,
                          **({"sa": float(e["sa"])} if e.get("sa") is not None else {}),
                          **({"hem": e["hem"]} if e.get("hem") else {})})
        out.append({"name": pc["name"], "edges": edges, "place": pc.get("place") or {},
                    **{k: pc[k] for k in ("role", "stage") if pc.get(k) not in (None, "")}})   # sewing order
    return {"pieces": out, "seams": d.get("seams", []),
            **{k: d[k] for k in ("spacing_cm", "fine_sdf", "body_offset") if d.get(k)}}


def place_fn(body, place: dict, uv_center):
    """uv (m) -> xyz for one piece."""
    S = _surf(body)
    if place.get("glove"):
        from .gloves import glove_place
        return glove_place(body, place["glove"])
    if place.get("arm"):            # a drafted sleeve (dedit.add_sleeve): round the arm on that side, crown on top
        from .garments import arm_wrap
        s = 1 if float(place["arm"]) > 0 else -1
        sj, el, r = body.arm_axis(s)
        wrist = None
        if place.get("wrist") and getattr(body, "kind", "") == "mesh":
            wrist = body.human.joint(f"{body.side if s > 0 else body.tape.other}-hand")    # long: follow the forearm
        f = arm_wrap(sj, el, max(0.075, r + 0.03), float(place.get("top_cm", 25)) / 100, False, wrist=wrist)
        off = (float(place.get("offset_cm", 0.5)) + 1.5 * int(place.get("layer", 0))) * cm
        return lambda uv: S.push_out(f(uv), off)
    if place.get("template"):
        f = _template_place(body, place["template"])
        off = (float(place.get("offset_cm", 0.3)) + 1.5 * int(place.get("layer", 0))) * cm
        return lambda uv: S.push_out(f(uv), off)
    mode = place.get("mode", "wrap")
    # layers: each layer starts 1.5 cm further out so garments worn over
    # others never start tangled with them
    off = (float(place.get("offset_cm", 1.5)) + 1.5 * int(place.get("layer", 0))) * cm
    th = np.radians(float(place.get("rotate", 0.0)))
    R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    if place.get("anchor") is not None:
        p = np.asarray(place["anchor"], float)
        _, n, _ = S.dist(p[None]); n = n[0]
    elif place.get("landmark"):
        p, n = landmark(body, place["landmark"])
    else:
        p, n = landmark(body, "chest_front")
        p = p + n * 0.25                            # not placed yet: hangs in front of the avatar
    o, up = body_axis(body, p)
    c0 = np.asarray(uv_center, float)

    if mode == "flat":
        t2 = up - (up @ n) * n
        t2 = t2 / (np.linalg.norm(t2) + 1e-12) if np.linalg.norm(t2) > 1e-6 else np.array([0.0, 1.0, 0.0])
        t1 = np.cross(t2, n)
        base = p + n * off

        def place_flat(uv):
            q = (uv - c0) @ R.T
            return base + np.outer(q[:, 0], t1) + np.outer(q[:, 1], t2)
        f = place_flat
    else:
        rel = p - o
        h0 = rel @ up
        radial = rel - h0 * up
        r = np.linalg.norm(radial)
        e1 = radial / (r + 1e-12) if r > 1e-6 else n
        e2 = np.cross(up, e1)
        ring = _cross_section(body, S, p, o, up, e1, e2, place, uv_center, R, h0, off)
        if ring is None:      # nothing of the body there: a plain cylinder
            r = r + off

            def place_wrap(uv):
                q = (uv - c0) @ R.T
                a = q[:, 0] / r
                return (o + np.outer(h0 + q[:, 1], up) + r * (np.outer(np.cos(a), e1) + np.outer(np.sin(a), e2)))
        else:
            ring_pt, s0 = ring

            def place_wrap(uv):
                q = (uv - c0) @ R.T
                ab = ring_pt(s0 + q[:, 0])
                return o + np.outer(h0 + q[:, 1], up) + np.outer(ab[:, 0], e1) + np.outer(ab[:, 1], e2)
        f = place_wrap

    return lambda uv: S.push_out(f(uv), off)


def _cross_section(body, S, p, o, up, e1, e2, place, uv_center, R, h0, off):
    """The outline the piece wraps along: the convex hull of the body part
    under the anchor, over the piece's whole height, grown by the offset.
    Returns (arc length -> (a, b) in the e1/e2 plane, arc length at the anchor)."""
    from scipy.spatial import ConvexHull
    from shapely.geometry import LineString, Polygon
    if S.regions is None:
        return None
    reg = S.region(p)
    Rg = S.regions
    V = S.V
    side = np.sign(p[0]) if abs(p[0]) > 1e-3 else 1.0
    if reg in ("arm", "hand"):
        mask = ((Rg["arm"] + Rg["hand"]) > 0.5) & (np.sign(V[:, 0]) == side)
    elif reg in ("leg", "foot"):
        mask = ((Rg["leg"] + Rg["foot"]) > 0.5) & (np.sign(V[:, 0]) == side)
    elif reg == "head":
        mask = Rg["head"] + Rg["torso"] > 0.5
    else:
        mask = (Rg["torso"] + Rg["leg"] + Rg["head"]) > 0.5
    # the piece's span along the axis
    span = place.get("_span")
    if span is None:
        return None
    lo, hi = h0 + span[0] - 0.02, h0 + span[1] + 0.02
    rel = V[mask] - o
    hh = rel @ up
    sel = (hh >= lo) & (hh <= hi)
    if sel.sum() < 12:
        return None
    ab = np.stack([rel[sel] @ e1, rel[sel] @ e2], 1)
    try:
        hull = ab[ConvexHull(ab).vertices]
    except Exception:
        return None
    ring = Polygon(hull).buffer(off, join_style="round").exterior
    pts = np.asarray(ring.coords)
    x, y = pts[:, 0], pts[:, 1]
    if 0.5 * (x[:-1] @ y[1:] - y[:-1] @ x[1:]) < 0:   # counter-clockwise: from e1 toward e2
        pts = pts[::-1]
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.r_[0, np.cumsum(seg)]
    L = cum[-1]
    # where the ray from the axis through the anchor leaves the outline
    ray = LineString([(0, 0), (10, 0)])
    hit = LineString(pts).intersection(ray)
    hx = max((g.x for g in getattr(hit, "geoms", [hit]) if hasattr(g, "x")), default=None)
    if hx is None:
        return None
    s0 = LineString(pts).project(__import__("shapely.geometry", fromlist=["Point"]).Point(hx, 0.0))

    def ring_pt(sv):
        t = np.mod(sv, L)
        return np.stack([np.interp(t, cum, pts[:, 0]), np.interp(t, cum, pts[:, 1])], 1)
    return ring_pt, s0


# ------------------------------------------------------------------ design --
def _clean_edges(piece):
    edges = []
    for e in piece["edges"]:
        pts = np.asarray(e["pts"], float) * cm
        keep = np.r_[True, np.linalg.norm(np.diff(pts, axis=0), axis=1) > 1e-6]
        pts = pts[keep]
        if len(pts) < 2:
            raise ValueError(f"piece {piece['name']}: edge {e['name']} has no length")
        edges.append([e["name"], pts])
    # close exactly: each edge starts where the previous one ended
    for i in range(len(edges)):
        edges[i][1][0] = edges[i - 1][1][-1]
    outline = np.concatenate([p[:-1] for _, p in edges])
    x, y = outline[:, 0], outline[:, 1]
    area = 0.5 * (x @ np.roll(y, -1) - y @ np.roll(x, -1))
    if area < 0:   # clockwise: turn it round (names stay with their edges)
        edges = [[n, p[::-1].copy()] for n, p in edges[::-1]]
    return [(n, p) for n, p in edges], abs(area)


def _hem_norm(h):
    from .hems import normalise
    return normalise(h)


def _piece_place(pc, body):
    """A piece (plain design format) -> (its cleaned edges in m, where its flat
    coords go on the body, the point of it that sits at its spot). Pieces placed
    on other pieces (pockets, bands, linings) are placed again by build_design."""
    edges, _ = _clean_edges(pc)
    _validate(edges, pc["name"])
    outline = np.concatenate([p for _, p in edges])
    lo, hi = outline.min(0), outline.max(0)
    pl = dict(pc.get("place") or {})
    cx, cy = 0.5 * (lo + hi)
    c = np.array({"top": (cx, hi[1]), "bottom": (cx, lo[1]), "left": (lo[0], cy),
                  "right": (hi[0], cy)}.get(pl.get("at", "center"), (cx, cy)), float)
    if pl.get("center_cm") is not None:      # a part of a split piece: placed where it was on its piece
        c = np.asarray(pl["center_cm"], float) * cm
    th = np.radians(float(pl.get("rotate", 0.0)))
    q = (outline - c) @ np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]]).T
    pl["_span"] = (float(q[:, 1].min()), float(q[:, 1].max()))
    if pl.get("span_cm") is not None:        # ... and wrapped over its whole piece's height, as the piece was
        pl["_span"] = tuple(float(v) * cm for v in pl["span_cm"])
    return edges, place_fn(body, pl, c), c


def order_loop(design, body, loop, hood=False):
    """The edges round an opening in the order they sit on the body, whatever
    order they were tapped in. design: the editor format (cm); loop: ["piece.edge"].
    Returns (refs going round, split): the round starts after the biggest gap
    (a front left open) if there is one; for a hood with no gap it starts at the
    centre front: if that falls inside an edge, split = (ref, cm along that edge
    from its start, whether the round runs along it backwards), else None.
    Edges on pieces that sit on other pieces keep the tapped order."""
    d2 = editor_to_design(design)
    pieces = {p["name"]: p for p in d2["pieces"]}
    curves, flat = {}, {}
    for ref in loop:
        pn, en = ref.split(".", 1)
        pc = pieces.get(pn)
        pl = (pc or {}).get("place") or {}
        if pc is None or pl.get("on") or pl.get("loop") or not (pl.get("landmark") or pl.get("anchor") or pl.get("template") or pl.get("arm")):
            return list(loop), None
        if pn not in flat:
            flat[pn] = _piece_place(pc, body)[1]
        e = next(x for x in pc["edges"] if x["name"] == en)
        P = np.asarray(e["pts"], float)
        seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
        cum = np.r_[0, np.cumsum(seg)]
        t = np.linspace(0, cum[-1], max(int(cum[-1]), 2) + 1)        # a point every cm
        P2 = np.stack([np.interp(t, cum, P[:, 0]), np.interp(t, cum, P[:, 1])], 1)
        curves[ref] = (flat[pn](P2 * cm), t)
    n = len(loop)
    if n == 1 and not hood:
        return list(loop), None
    # Which edges meet: pieces start apart (a front in front of the body, a back behind it) and
    # only meet once sewn, so it's the seams that say so: a corner of a piece, and every corner
    # sewn to it, are one point of the garment. (3D distance only breaks ties.)
    ed = {p["name"]: p for p in design["pieces"]}
    parent = {}

    def find(k):
        while parent.get(k, k) != k:
            k = parent[k]
        return k

    def corners(ref):
        pn, en = ref.split(".", 1)
        pc = ed.get(pn)
        i = next((k for k, e in enumerate(pc["edges"]) if e["name"] == en), None) if pc else None
        return None if i is None else ((pn, i), (pn, (i + 1) % len(pc["verts"])))

    def end3d(ref):
        pn, en = ref.split(".", 1)
        pc = pieces.get(pn)
        pl = (pc or {}).get("place") or {}
        if pc is None or pl.get("on") or pl.get("loop") or not (pl.get("landmark") or pl.get("anchor") or pl.get("template") or pl.get("arm")):
            return None
        if pn not in flat:
            flat[pn] = _piece_place(pc, body)[1]
        P = np.asarray(next(x for x in pc["edges"] if x["name"] == en)["pts"], float)[[0, -1]]
        return flat[pn](P * cm)

    for s in design.get("seams", []):
        A, B = corners(s["a"]), corners(s["b"])
        if not A or not B:
            continue
        rev = s.get("reverse")
        if rev is None:                   # as build_design decides it: the ends that start nearer
            ea, eb = end3d(s["a"]), end3d(s["b"])
            if ea is None or eb is None:
                continue
            rev = np.linalg.norm(ea[0] - eb[1]) + np.linalg.norm(ea[1] - eb[0]) < \
                np.linalg.norm(ea[0] - eb[0]) + np.linalg.norm(ea[1] - eb[1])
        for p, q in (((A[0], B[1]), (A[1], B[0])) if rev else ((A[0], B[0]), (A[1], B[1]))):
            parent[find(p)] = find(q)
    node = {r: tuple(find(c) for c in corners(r)) for r in loop}

    def ends(r, rev):                     # ((corner, 3D) where the round enters it, (corner, 3D) where it leaves)
        a, b = (node[r][0], curves[r][0][0]), (node[r][1], curves[r][0][-1])
        return (b, a) if rev else (a, b)

    def gap(p, q):                        # 0: the same point of the garment; 1+: not joined
        return 0.0 if p[0] == q[0] else 1.0 + float(np.linalg.norm(p[1] - q[1]))
    best = None
    for s0 in loop:                       # chain greedily from every start; keep the tightest round
        for rv in (False, True):
            order, left = [(s0, rv)], [r for r in loop if r != s0]
            while left:
                end = ends(*order[-1])[1]
                r, rev = min(((r, rev) for r in left for rev in (False, True)), key=lambda x: gap(ends(*x)[0], end))
                order.append((r, rev))
                left.remove(r)
            gaps = [gap(ends(*order[k])[1], ends(*order[(k + 1) % n])[0]) for k in range(n)]
            cost = sum(gaps) - max(gaps)  # an opening may have one gap (an open front)
            if best is None or cost < best[0] - 1e-9:
                best = (cost, order, gaps)
    _, order, gaps = best
    k = int(np.argmax(gaps))
    if gaps[k] >= 1:                      # not joined all the way round: the round starts after the gap
        order = order[k + 1:] + order[:k + 1]
        return [r for r, _ in order], None
    if not hood:                          # closed and not a hood: start where the user started
        i = next(j for j, (r, _) in enumerate(order) if r == loop[0])
        return [r for r, _ in order[i:] + order[:i]], None
    # a hood opens at the centre front: the front-most point of the round on the body's middle line
    pts = np.vstack([curves[r][0] for r, _ in order])
    mid = pts.mean(0)
    front = pts[:, 2] > mid[2]
    cand = [(abs(X[0] - mid[0]), j, q) for j, (r, _) in enumerate(order)
            for q, X in enumerate(curves[r][0]) if X[2] > mid[2]] if front.any() else []
    if not cand:
        return [r for r, _ in order], None
    _, j, q = min(cand)
    r, rev = order[j]
    C, t = curves[r]
    s = float(t[q])
    L = float(t[-1])
    if min(s, L - s) < 0.5:               # right at an end of the edge: start the round there
        at_start = (s < 0.5) != rev       # the round reaches this edge's start or end first?
        i = j if at_start else j + 1
        order = order[i % n:] + order[:i % n]
        return [x for x, _ in order], None
    return [x for x, _ in order[j:] + order[:j]], (r, s, rev)


def _validate(piece_edges, name):
    from shapely.geometry import Polygon
    poly = Polygon(np.concatenate([p[:-1] for _, p in piece_edges]))
    if not poly.is_valid:
        raise ValueError(f"piece {name}: its outline crosses itself")


LINING_SHORTER_CM = 2.5     # a lining ends this far inside its shell's open edges (a hem), as a real one is cut


def _shorten_open(edges, opened, d):
    """A lining's edges with each open edge (a hem) moved d cm into the piece, its two neighbours trimmed to meet it.
    Returns (edges, the open edges moved). An open edge next to another open one, or whose neighbours are too short to
    trim, stays as it is."""
    E = [dict(e, pts=[[float(q[0]), float(q[1])] for q in e["pts"]]) for e in edges]
    ring = np.concatenate([np.asarray(e["pts"], float)[:-1] for e in E])
    area = 0.5 * float(np.sum(ring[:, 0] * np.roll(ring[:, 1], -1) - np.roll(ring[:, 0], -1) * ring[:, 1]))
    n, moved = len(E), []

    def cut(P, origin, nrm):         # along P (which starts at origin): where it gets d into the piece
        s = (P - origin) @ nrm
        for j in range(1, len(P)):
            if s[j] >= d > s[j - 1]:
                u = (d - s[j - 1]) / (s[j] - s[j - 1])
                return j, P[j - 1] + u * (P[j] - P[j - 1])
        return None
    for k in range(n):
        e, prev, nxt = E[k], E[(k - 1) % n], E[(k + 1) % n]
        if e["name"] not in opened or prev["name"] in opened or nxt["name"] in opened or n < 3:
            continue
        P = np.asarray(e["pts"], float)
        t = P[-1] - P[0]
        if np.linalg.norm(t) < 1e-6:
            continue
        t /= np.linalg.norm(t)
        nrm = np.array([-t[1], t[0]]) * (1.0 if area > 0 else -1.0)           # into the piece
        Qr, R = np.asarray(prev["pts"], float)[::-1], np.asarray(nxt["pts"], float)
        cq, cr = cut(Qr, P[0], nrm), cut(R, P[-1], nrm)
        if cq is None or cr is None:
            continue
        (jq, c1), (jr, c2) = cq, cr
        prev["pts"] = np.vstack([Qr[jq:][::-1], c1]).round(4).tolist()
        nxt["pts"] = np.vstack([c2, R[jr:]]).round(4).tolist()
        e["pts"] = np.vstack([c1, P[1:-1] + d * nrm, c2]).round(4).tolist()
        moved.append(e["name"])
    return E, moved


def _expand_linings(design):
    """Each lined piece gets a twin '<name>_lining' in the lining fabric. Linings
    of neighbouring lined pieces are sewn together like the shell; every other
    edge of a lining is held to the shell's edge (like the seam that catches
    both), except the edges left open (a hem, say). Those are cut LINING_SHORTER_CM
    shorter (`lining.shorter_cm`), so the lining can't show below the shell, and the
    lining is tacked to the shell at each end of them (French tacks at the seams):
    design["_lining_tacks"]."""
    pieces = [dict(p) for p in design["pieces"]]
    seams = [dict(s) for s in design.get("seams", [])]
    lined = {p["name"]: p["lining"] for p in pieces if p.get("lining")}
    joins, tacks = [], []
    if not lined:
        return {**design, "pieces": pieces, "seams": seams}, joins
    for p in list(pieces):
        L = lined.get(p["name"])
        if not L:
            continue
        # elastic edges stay elastic: the lining is caught in the same casing
        opened = set(L.get("open", []))
        d = float(L.get("shorter_cm", LINING_SHORTER_CM))
        ed, moved = _shorten_open(p["edges"], opened, d) if d > 0 and opened else ([dict(e) for e in p["edges"]], [])
        twin = {"name": p["name"] + "_lining", "edges": ed,
                "place": {**(p.get("place") or {}), "_lining_of": p["name"]},
                "fabric": L.get("fabric", "lining"), "_lining": True}
        pieces.append(twin)
        tacks += [(twin["name"], en, p["name"]) for en in moved]
        for e in p["edges"]:
            if e["name"] not in opened:
                joins.append((twin["name"], e["name"], p["name"], e["name"]))
    for sd in list(seams):
        pa, ea = sd["a"].split(".", 1)
        pb, eb = sd["b"].split(".", 1)
        if pa in lined and pb in lined:
            seams.append({**sd, "a": f"{pa}_lining.{ea}", "b": f"{pb}_lining.{eb}"})
            for j in list(joins):     # those lining edges are sewn to each other, not to the shell
                if (j[0], j[1]) in ((pa + "_lining", ea), (pb + "_lining", eb)):
                    joins.remove(j)
    return {**design, "pieces": pieces, "seams": seams, "_lining_tacks": tacks}, joins


def _loop_place(body, S, pmap, pl, pc):
    """Bottom edge of the band along the opening (the loop of edges it is sewn
    to, in 3D), the rest of it standing up (or hanging down) from there."""
    curves = []
    for ref in pl["loop"]:
        pn, en = ref.split(".", 1)
        if pn not in pmap:
            raise ValueError(f"'{pc['name']}' goes round {ref}, but there is no piece {pn}")
        P = pmap[pn]
        e = P.edge(en)                       # densify: a straight edge is just 2 points
        seg = np.linalg.norm(np.diff(e, axis=0), axis=1)
        cum = np.r_[0, np.cumsum(seg)]
        t = np.linspace(0, cum[-1], max(int(cum[-1] / 0.01), 2) + 1)
        e = np.stack([np.interp(t, cum, e[:, 0]), np.interp(t, cum, e[:, 1])], 1)
        curves.append(P.place(e))
    chain = curves[0]
    if len(curves) > 1:   # orient the first so its end meets the second
        c1 = curves[1]
        if min(np.linalg.norm(chain[0] - c1[0]), np.linalg.norm(chain[0] - c1[-1])) < \
           min(np.linalg.norm(chain[-1] - c1[0]), np.linalg.norm(chain[-1] - c1[-1])):
            chain = chain[::-1]
    for c in curves[1:]:
        if np.linalg.norm(c[-1] - chain[-1]) < np.linalg.norm(c[0] - chain[-1]):
            c = c[::-1]
        chain = np.vstack([chain, c])
    seg = np.linalg.norm(np.diff(chain, axis=0), axis=1)
    cum = np.r_[0, np.cumsum(seg)]
    L3 = cum[-1]
    centre = chain.mean(0)
    _, up = body_axis(body, centre)
    sign = -1.0 if pl.get("dir") == "down" else 1.0
    # the band's +u follows the edges in the order they were picked (a plain
    # band looks the same from either side, so which way round doesn't matter)
    fr = float(pl.get("flare_r") or 0) * cm             # a flared band (the cuff's Flare): part of a flat ring

    def unring(P):
        if not fr:
            return P
        q = P - np.array([0.0, -fr])
        return np.stack([np.arctan2(q[:, 0], q[:, 1]) * fr, np.linalg.norm(q, axis=1) - fr], 1)
    outline = unring(np.concatenate([e[:-1] for e in (np.asarray(x["pts"], float) * cm for x in pc["edges"])]))
    lo, hi = outline.min(0), outline.max(0)
    off = float(pl.get("offset_cm", 0.5)) * cm

    # each join edge of the band goes along its own edge of the opening (the
    # jumps between pieces that aren't sewn yet must not skew where it lands)
    joins = []
    for k in range(len(curves)):
        e = next((x for x in pc["edges"] if x["name"] == f"join_{k + 1}"), None)
        if e is None:
            joins = []
            break
        xs = unring(np.asarray(e["pts"], float) * cm)[:, 0]
        joins.append((xs.min(), xs.max()))
    oriented = [chain[:len(curves[0])]]
    pos = len(curves[0])
    for c in curves[1:]:
        oriented.append(chain[pos:pos + len(c)]); pos += len(c)
    seg_cum = [np.r_[0, np.cumsum(np.linalg.norm(np.diff(c, axis=0), axis=1))] for c in oriented]

    def base_at(u):
        if not joins:
            sv = (u - lo[0]) / max(hi[0] - lo[0], 1e-9) * L3
            return np.stack([np.interp(sv, cum, chain[:, k]) for k in range(3)], 1)
        out = np.empty((len(u), 3))
        edges_x = np.array([j[0] for j in joins] + [joins[-1][1]])
        k = np.clip(np.searchsorted(edges_x, u, side="right") - 1, 0, len(joins) - 1)
        for q in range(len(joins)):
            m = k == q
            if not m.any():
                continue
            a, b = joins[q]
            t = np.clip((u[m] - a) / max(b - a, 1e-9), 0, 1) * seg_cum[q][-1]
            out[m] = np.stack([np.interp(t, seg_cum[q], oriented[q][:, j]) for j in range(3)], 1)
        return out

    spread = float(pl.get("flare") or 0) and (hi[0] - lo[0]) / (2 * np.pi * fr)    # the cone's widening per metre down

    def place(uv):
        uv = unring(uv)
        base = base_at(uv[:, 0])
        out = base - centre
        out -= (out @ up)[:, None] * up
        out /= np.linalg.norm(out, axis=1, keepdims=True) + 1e-12
        h = (uv[:, 1] - lo[1])
        # a hood or tall collar leans out a little as it rises, so it starts clear of the head
        X = base + np.outer(h * sign, up) + out * (off + 0.15 * np.clip(h - 0.08, 0, None) + spread * h)[:, None]
        return S.push_out(X, off)
    return place


def _host_normal(f, uv, h=0.005, body=None):
    """Outward normal of a placed piece at uv (from its placement function). With `body`: turned to point away from
    it. The cross product's side follows the piece's 2D winding, and a mirrored piece (the right sleeve, which is
    the left one flipped) came out pointing into the body: its lining then started outside it (Tyler's dress,
    2026-11-28: 865 of 946 points)."""
    du = f(uv + [h, 0]) - f(uv - [h, 0])
    dv = f(uv + [0, h]) - f(uv - [0, h])
    n = np.cross(du, dv)
    n = n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-12)
    if body is not None and len(n):
        X, e = f(uv), 2e-3
        grad = np.stack([np.ravel(body.sdf(X + e * np.eye(3)[k])) - np.ravel(body.sdf(X - e * np.eye(3)[k])) for k in range(3)], 1)
        if float(np.sum(n * grad)) < 0:          # the piece as a whole: its normal points into the body
            n = -n
    return n


def _on_transform(place):
    """Pocket coords (m) -> host coords: turn, then move to place['pos'] (cm)."""
    th = np.radians(float(place.get("rotate", 0.0)))
    Rm = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    pos = np.asarray(place.get("pos", [0, 0]), float) * cm
    return lambda uv: uv @ Rm.T + pos


def _barycentric_on(g, panel_index, pts2d):
    """For points in a piece's own flat coords: the triangle of that piece
    under each point and the barycentric weights (nearest triangle if outside)."""
    from scipy.spatial import cKDTree
    T = g.tris[g.panel_id[g.tris[:, 0]] == panel_index]
    A, B, C = g.uv[T[:, 0]], g.uv[T[:, 1]], g.uv[T[:, 2]]
    tree = cKDTree((A + B + C) / 3)
    _, cand = tree.query(pts2d, k=min(12, len(T)))
    out_t, out_b = [], []
    for q, cs in zip(pts2d, np.atleast_2d(cand)):
        best, bb, berr = None, None, 1e9
        for t in cs:
            a, b, c = A[t], B[t], C[t]
            m = np.array([b - a, c - a]).T
            try:
                l1, l2 = np.linalg.solve(m, q - a)
            except np.linalg.LinAlgError:
                continue
            bary = np.array([1 - l1 - l2, l1, l2])
            err = -min(bary.min(), 0)
            if err < berr:
                best, bb, berr = t, bary, err
                if err == 0:
                    break
        bb = np.clip(bb, 0, None); bb /= bb.sum()
        out_t.append(T[best]); out_b.append(bb)
    return np.array(out_t), np.array(out_b)


def piece_regions(design, body, centres=None, pmap=None):
    """{piece name: stages.region(...)}: where each piece is placed on the body, from its
    placement alone (its own outline's centre, put where its placement says). Used for
    the sewing order; it must never look at the seams (STAGED_SEWING_SPEC section 0)."""
    from .stages import region
    out = {}
    for pc in design["pieces"]:
        pl = pc.get("place") or {}
        where = None
        if pl.get("template") or pl.get("anchor") is not None or pl.get("landmark") or pl.get("arm"):
            try:
                if pmap is not None and pc["name"] in pmap:
                    f, c = pmap[pc["name"]].place, centres[pc["name"]]
                else:
                    _, f, c = _piece_place(pc, body)
                where = f(np.asarray(c, float)[None])[0]
            except Exception:
                where = None
        out[pc["name"]] = region(pc, where, body)
    return out


def build_design(design: dict, body, spacing=0.015, density=0.15, auto_reverse=True):
    """Design JSON -> Garment (meta has panels, seam_defs, and per-seam info)."""
    if design.get("spacing_cm"):        # small pieces (gloves) need a finer mesh than the default
        spacing = min(5.0, max(0.5, float(design["spacing_cm"]))) / 100   # a file's: 5 mm (the gloves') to 5 cm
    design, lining_joins = _expand_linings(design)
    lining_joins = lining_joins + _layer_joins(design)
    panels, centres, layers = [], {}, []
    names = [p["name"] for p in design["pieces"]]
    # a piece with pocket bags inside it starts a little further out, so they fit under it
    roomy = {(p.get("place") or {}).get("on") for p in design["pieces"]
             if (p.get("place") or {}).get("inside") and not p["place"].get("yoke")}
    if roomy:
        design = {**design, "pieces": [({**p, "place": {**p["place"], "offset_cm": float(p["place"].get("offset_cm", 0.3)) + 1.2}}
                                        if p["name"] in roomy and p.get("place") else p) for p in design["pieces"]]}
    if len(set(names)) != len(names):
        raise ValueError("two pieces have the same name")
    for pc in design["pieces"]:
        edges, place, c = _piece_place(pc, body)
        centres[pc["name"]] = c
        panels.append(Panel(pc["name"], edges, place,
                            sa_edges={e["name"]: float(e["sa"]) for e in pc["edges"] if e.get("sa") is not None},
                            hems={e["name"]: _hem_norm(e["hem"]) for e in pc["edges"] if e.get("hem")}))
        layers.append(int((pc.get("place") or {}).get("layer", 0)))
    pmap = {p.name: p for p in panels}
    S = _surf(body)
    for pc in design["pieces"]:
        pl = pc.get("place") or {}
        if pl.get("_lining_of"):          # just inside its shell
            shell = pmap[pl["_lining_of"]]

            def lining_place(uv, f=shell.place):
                X = f(uv)
                return S.push_out(X - 0.005 * _host_normal(f, uv, body=body), 0.002)
            pmap[pc["name"]].place = lining_place
        elif pl.get("loop"):              # a band round an opening (collar, cuff, waistband, hood)
            pmap[pc["name"]].place = _loop_place(body, S, pmap, pl, pc)
        elif pl.get("on"):                # sewn onto another piece (pocket, patch)
            host = pmap.get(pl["on"])
            if host is None:
                raise ValueError(f"'{pc['name']}' is sewn onto '{pl['on']}', which doesn't exist")
            T = _on_transform(pl)
            if pl.get("inside"):          # on the inside face (pocket bags, inner pockets): under the host
                depth = 0.005 * float(pl["inside"])      # 1, 2: one layer further in

                def on_place(uv, f=host.place, T=T, depth=depth):
                    q = T(uv)
                    return S.push_out(f(q) - depth * _host_normal(f, q, body=body), 0.0015)
            else:
                lift = 0.004 * (1 + int(pl.get("layer", 0)))

                def on_place(uv, f=host.place, T=T, lift=lift):
                    q = T(uv)
                    return f(q) + lift * _host_normal(f, q, body=body)
            pmap[pc["name"]].place = on_place
    # garments worn over others (merged for Live / Drape it): lifted only as far as contact needs (layer_gap_cm);
    # 12 mm stretched a long-sleeve top round a tee by ~7.5 cm and it snapped through it at the start
    _layer_panels(body, panels, layers, **({"gap": float(design["layer_gap_cm"]) / 100} if design.get("layer_gap_cm") else {}))
    seams, info, closure_seams = [], [], []
    used = set()
    for s in design.get("seams", []):
        pa, ea = s["a"].split(".", 1)
        pb, eb = s["b"].split(".", 1)
        for key in ((pa, ea), (pb, eb)):
            if key not in {(p.name, n) for p in panels for n, _ in p.edges}:
                raise ValueError(f"seam {s['a']} <-> {s['b']}: there is no edge {key[0]}.{key[1]}")
            if key in used:
                raise ValueError(f"edge {key[0]}.{key[1]} is in two seams; an edge can only be sewn once "
                                 "(split it first to sew it to two places)")
            used.add(key)
        A, B = pmap[pa].edge(ea), pmap[pb].edge(eb)
        la, lb = polyline_length(A), polyline_length(B)
        ease = float(s.get("ease") or 0.0)
        rev = s.get("reverse")
        if rev is None:
            if auto_reverse:
                a3 = pmap[pa].place(A[[0, -1]])
                b3 = pmap[pb].place(B[[0, -1]])
                same = np.linalg.norm(a3[0] - b3[0]) + np.linalg.norm(a3[1] - b3[1])
                cross = np.linalg.norm(a3[0] - b3[1]) + np.linalg.norm(a3[1] - b3[0])
                rev = bool(cross < same)
            else:
                rev = True
        if lb > la * 1.0005:     # Seam.ease means A is the longer one: put the longer edge first
            seams.append(Seam(pb, eb, pa, ea, reverse=bool(rev), ease=ease))
        else:
            seams.append(Seam(pa, ea, pb, eb, reverse=bool(rev), ease=ease))
        info.append({"a": s["a"], "b": s["b"], "len_a_cm": la * 100, "len_b_cm": lb * 100,
                     "diff_cm": (la - lb) * 100, "reverse": bool(rev), "ease": ease})
        if s.get("closure"):
            from .closures import sane as _sane_closure      # within what can be sewn (1-200 buttons, ...)
            closure_seams.append((_sane_closure(s["closure"]), Seam(pa, ea, pb, eb, reverse=bool(rev))))   # design order: a = overlap
    g = build_garment(panels, seams, spacing=spacing, density=density)
    # closures: buttons/zips are seams that are done up, except the part left open
    from .closures import layout as closure_layout, open_pairs
    drop = set()
    for cl, sm in closure_seams:
        drop |= open_pairs(g, sm, cl)
    if drop:
        keep = np.array([(int(a), int(b)) not in drop for a, b in g.seams], bool)
        g.seams = g.seams[keep]
        g.meta["seam_of_pair"] = g.meta["seam_of_pair"][keep]
    # staged sewing (stages.py): each piece's stage from where it's placed and its role,
    # never from the seams (spec section 0); a seam is sewn with the later of its two pieces
    from .stages import assign as assign_stages, stage_names
    pst, pauto = assign_stages(design["pieces"], piece_regions(design, body, centres, pmap))
    g.meta["piece_stage"] = [int(pst[n]) for n in g.panel_names]
    g.meta["piece_stage_auto"] = [bool(pauto[n]) for n in g.panel_names]
    byname = {pc["name"]: pc for pc in design["pieces"]}       # several garments merged: which one each piece is
    g.meta["piece_garment"] = [int(byname.get(n, {}).get("_garment", 0)) for n in g.panel_names]
    pidx = np.asarray(g.meta["piece_stage"], np.int64)
    g.meta["seam_stage"] = (np.maximum(pidx[g.panel_id[g.seams[:, 0]]], pidx[g.panel_id[g.seams[:, 1]]])
                            if len(g.seams) else np.zeros(0, np.int64))
    g.meta["design_seam_stage"] = [max(int(pst.get(s["a"].split(".", 1)[0], 1)), int(pst.get(s["b"].split(".", 1)[0], 1)))
                                   for s in design.get("seams", [])]
    g.meta["stage_names"] = stage_names(g.panel_names, g.meta["piece_stage"],
                                        {pc["name"]: pc.get("role") for pc in design["pieces"]})
    gname = {pc["name"]: pc.get("_garment_name") for pc in design["pieces"] if pc.get("_garment_name")}
    for k in set(g.meta["piece_stage"]) if gname else ():      # several garments: a garment's stage says its name
        who = {gname.get(n) for n, s in zip(g.panel_names, g.meta["piece_stage"]) if s == k}
        if k > 1 and len(who) == 1 and None not in who:
            g.meta["stage_names"][int(k)] = who.pop()
    g.meta["closure_seams"] = closure_seams
    # pocket bags / yokes and the piece over them, and bags sharing a host: kept apart while sewing
    idx = {n: i for i, n in enumerate(g.panel_names)}
    ins = [(pc["name"], pc["place"]["on"]) for pc in design["pieces"] if (pc.get("place") or {}).get("inside")]
    lp = [(idx[a], idx[b]) for a, b in ins if b in idx]
    lp += [(idx[a], idx[c]) for a, b in ins for c, d in ins if a < c and b == d]
    g.meta["layer_pairs"] = lp
    if design.get("fine_sdf"):
        g.meta["fine_sdf"] = float(design["fine_sdf"])
    if design.get("body_offset"):
        g.meta["body_offset"] = float(design["body_offset"])
    g.meta["closures"] = closure_layout(pmap, design.get("seams", []))
    from .hems import fold_marks
    for p in panels:              # hems: fold lines on the pattern (after the closures reset the marks)
        for en, hm in p.hems.items():
            p.marks += [{"kind": m["kind"], "pts": m["pts"] / 100} for m in fold_marks(p.edge(en) * 100, hm)]
    _apply_elastic(g, design, body)
    _attachments(g, design, lining_joins)
    # pieces meant to be stretched (rib bands) shouldn't count as "pulling"
    g.meta["stretchy_panels"] = [i for i, pc in enumerate(design["pieces"]) if (pc.get("place") or {}).get("loop")]
    g.meta["panel_fabric_keys"] = [((pc.get("fabric") or None), (pc.get("interfacing") or None))
                                   for pc in design["pieces"]]
    g.meta.update(design=True, seam_info=info, hem_y=None, torso_panels=[], sleeve_panels=[],
                  placed={p["name"]: bool((p.get("place") or {}).get("anchor") is not None
                                          or (p.get("place") or {}).get("glove")
                                          or (p.get("place") or {}).get("landmark")
                                          or (p.get("place") or {}).get("template")
                                          or (p.get("place") or {}).get("arm")
                                          or (p.get("place") or {}).get("on")
                                          or (p.get("place") or {}).get("loop")
                                          or (p.get("place") or {}).get("_lining_of"))
                          for p in design["pieces"]})
    return g


def _layer_joins(design):
    """A copy on the layer over its original (dedit.layer_copy) is held to it
    along its 'held' edges, like a lining to its shell: (copy, edge, original, edge).
    Edges renamed or split since the copy was made are skipped."""
    have = {p["name"]: {e["name"] for e in p["edges"]} for p in design["pieces"]}
    out = []
    for p in design["pieces"]:
        pl = p.get("place") or {}
        o = pl.get("layer_of")
        if o in have:
            out += [(p["name"], en, o, en) for en in pl.get("held") or [] if en in have[p["name"]] and en in have[o]]
    return out


def _piece_cloud(panel, step=0.015):
    """Points covering a placed piece (its outline and a grid inside)."""
    from shapely.geometry import Point, Polygon
    outline = np.concatenate([p[:-1] for _, p in panel.edges])
    poly = Polygon(outline)
    lo, hi = outline.min(0), outline.max(0)
    xs, ys = np.meshgrid(np.arange(lo[0], hi[0], step), np.arange(lo[1], hi[1], step))
    G = np.stack([xs.ravel(), ys.ravel()], 1)
    inside = np.array([poly.contains(Point(*q)) for q in G], bool) if len(G) else np.zeros(0, bool)
    return panel.place(np.vstack([outline, G[inside]]))


def _layer_panels(body, panels, layers, gap=0.012, step=0.01, smooth=0.04):
    """Pieces on a higher layer start outside the cloth of the layers below
    (not just outside the body), so worn-over garments never start tangled.

    The lift is worked out once per piece on a grid over its flat shape and smoothed (amount and direction,
    over `smooth` m), then every point moves straight out from the body by it. Lifting each point on its own
    along the normal of the cloth under it (2026-11-24) pushed neighbours different ways: a long-sleeve top
    over a tee started with its sleeves folded through its bodice (260 crossings within it, 1300+ in Live)."""
    if len(set(layers)) < 2:
        return
    from scipy.interpolate import RegularGridInterpolator
    from scipy.ndimage import gaussian_filter, maximum_filter
    from scipy.spatial import cKDTree
    S = _surf(body)
    order = sorted(set(layers))
    below = []
    sig = smooth / step
    for lv in order:
        if below:
            cloud = np.vstack(below)
            tree = cKDTree(cloud)
            cn = S.dist(cloud)[1]                     # outward direction (from the body under it)
            for i, p in enumerate(panels):
                if layers[i] != lv:
                    continue
                f = p.place
                outline = np.concatenate([q[:-1] for _, q in p.edges])
                lo, hi = outline.min(0) - 2 * step, outline.max(0) + 2 * step
                xs, ys = np.arange(lo[0], hi[0] + step, step), np.arange(lo[1], hi[1] + step, step)
                G = np.stack(np.meshgrid(xs, ys, indexing="ij"), -1).reshape(-1, 2)
                X = f(G)
                N = S.dist(X)[1].reshape(len(xs), len(ys), 3)
                N = np.stack([gaussian_filter(N[..., k], sig, mode="nearest") for k in range(3)], -1).reshape(-1, 3)
                N /= np.linalg.norm(N, axis=1, keepdims=True) + 1e-12
                L = np.zeros(len(G))
                for _ in range(6):
                    Y = X + L[:, None] * N
                    d, j = tree.query(Y)
                    h = ((Y - cloud[j]) * cn[j]).sum(1)
                    need = np.where((d < 0.06) & (h < gap), gap - h, 0.0)
                    if not need.any():
                        break
                    L += need
                L = L.reshape(len(xs), len(ys))
                L = gaussian_filter(maximum_filter(L, size=int(2 * sig) | 1, mode="nearest"), sig, mode="nearest")
                lift = RegularGridInterpolator((xs, ys), L, bounds_error=False, fill_value=None)
                dirs = [RegularGridInterpolator((xs, ys), N[:, k].reshape(len(xs), len(ys)), bounds_error=False, fill_value=None) for k in range(3)]

                def lifted(uv, f=f, lift=lift, dirs=dirs):
                    uv = np.asarray(uv, float)
                    n = np.stack([dk(uv) for dk in dirs], 1)
                    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
                    return f(uv) + np.maximum(lift(uv), 0.0)[:, None] * n
                p.place = lifted
        below += [_piece_cloud(p) for i, p in enumerate(panels) if layers[i] == lv]


def _attachments(g, design, lining_joins):
    """Topstitched edges (pockets onto pieces) and lining edges held to their
    shell: each vertex on such an edge is tied to the point under it."""
    idx = {n: i for i, n in enumerate(g.panel_names)}
    V, ABC, BARY, info = [], [], [], []
    for pc in design["pieces"]:
        pl = pc.get("place") or {}
        if not pl.get("on"):
            continue
        sewn = pl.get("sewn")
        if sewn is None:   # default: every edge but the top one (the pocket opening)
            top = max(pc["edges"], key=lambda e: np.mean(np.asarray(e["pts"], float)[:, 1]))
            sewn = [e["name"] for e in pc["edges"] if e is not top]
        T = _on_transform(pl)
        from shapely.geometry import Polygon
        host_poly = Polygon(np.concatenate([e[:-1] for _, e in g.meta["panels"][idx[pl["on"]]].edges]))
        own = np.concatenate([np.asarray(e["pts"], float) * cm for e in pc["edges"]])
        if not pl.get("inside") and not host_poly.buffer(0.005).contains(Polygon(T(own))):
            g.meta.setdefault("off_host", []).append(pc["name"])
        for en in sewn:
            vid = g.meta["edge_index"][(pc["name"], en)]
            tri, bary = _barycentric_on(g, idx[pl["on"]], T(g.uv[vid]))
            V.append(vid); ABC.append(tri); BARY.append(bary)
        info.append({"piece": pc["name"], "on": pl["on"], "sewn": list(sewn)})
    for lp, le, sp, se in lining_joins:
        vid = g.meta["edge_index"][(lp, le)]
        tri, bary = _barycentric_on(g, idx[sp], g.uv[vid])
        V.append(vid); ABC.append(tri); BARY.append(bary)
    tacked = []
    for lp, le, sp in design.get("_lining_tacks") or []:      # a lining's hem tacked to its shell at each end
        vid = g.meta["edge_index"][(lp, le)]
        ends = np.unique(np.r_[vid[:2], vid[-2:]])
        tri, bary = _barycentric_on(g, idx[sp], g.uv[ends])
        V.append(ends); ABC.append(tri); BARY.append(bary); tacked.append(f"{lp}.{le}")
    if V:
        g.meta["attach"] = {"v": np.concatenate(V), "abc": np.concatenate(ABC), "bary": np.concatenate(BARY)}
    g.meta["topstitched"] = info
    g.meta["lining_joins"] = [f"{a}.{b}" for a, b, _, _ in lining_joins]
    g.meta["lining_tacks"] = tacked


def girth_at(body, p):
    """Girth of the body part under p (around its own axis), m."""
    from scipy.spatial import ConvexHull
    S = _surf(body)
    o, up = body_axis(body, p)
    rel = p - o
    e1 = rel - (rel @ up) * up
    e1 = e1 / (np.linalg.norm(e1) + 1e-12)
    e2 = np.cross(up, e1)
    h0 = rel @ up
    V = S.V
    reg = S.region(p)
    Rg = S.regions
    side = np.sign(p[0]) if abs(p[0]) > 1e-3 else 1.0
    if reg in ("arm", "hand"):
        mask = ((Rg["arm"] + Rg["hand"]) > 0.5) & (np.sign(V[:, 0]) == side)
    elif reg in ("leg", "foot"):
        mask = ((Rg["leg"] + Rg["foot"]) > 0.5) & (np.sign(V[:, 0]) == side)
    else:
        mask = (Rg["torso"] + Rg["head"]) > 0.5
    r = V[mask] - o
    sel = np.abs(r @ up - h0) < 0.012
    if sel.sum() < 8:
        return None
    ab = np.stack([r[sel] @ e1, r[sel] @ e2], 1)
    hv = ab[ConvexHull(ab).vertices]
    return float(np.linalg.norm(np.diff(np.vstack([hv, hv[:1]]), axis=0), axis=1).sum())


CASING = 0.025    # elastic casing width (m): the band of fabric the elastic pulls in


def _shrink_band(g, vid, frac, band):
    """Shorten, along the edge, every mesh edge within `band` of it: a casing
    with elastic in it (one row alone is too weak to hold a skirt up)."""
    poly = g.uv[vid]
    pid = g.panel_id[vid[0]]
    E = g.edges
    inp = (g.panel_id[E[:, 0]] == pid) & (g.panel_id[E[:, 1]] == pid)
    E_idx = np.nonzero(inp)[0]
    a, b = g.uv[E[E_idx, 0]], g.uv[E[E_idx, 1]]
    mid = 0.5 * (a + b)
    seg0, seg1 = poly[:-1], poly[1:]
    d = seg1 - seg0
    L2 = (d ** 2).sum(1) + 1e-18
    # nearest segment for every edge midpoint
    t = np.clip(((mid[:, None, :] - seg0[None]) * d[None]).sum(2) / L2[None], 0, 1)
    near = seg0[None] + t[..., None] * d[None]
    dist = np.linalg.norm(mid[:, None, :] - near, axis=2)
    k = dist.argmin(1)
    ok = dist[np.arange(len(k)), k] < band
    if not ok.any():
        return
    tang = d[k[ok]] / np.sqrt(L2[k[ok]])[:, None]
    v = (b - a)[ok]
    along = (v * tang).sum(1)
    perp = v - along[:, None] * tang
    g.edge_rest[E_idx[ok]] = np.linalg.norm(perp + (frac * along)[:, None] * tang, axis=1)


def _apply_elastic(g, design, body):
    """Edges marked "elastic": shorten their rest length so the opening
    gathers to fit the body where it sits (or to a given fraction)."""
    groups = {}
    for pc in design["pieces"]:
        for e in pc["edges"]:
            el = e.get("elastic")
            if not el:
                continue
            vid = g.meta["edge_index"][(pc["name"], e["name"])]
            if isinstance(el, (int, float)) and not isinstance(el, bool):
                groups[("fixed", pc["name"], e["name"])] = ([vid], float(el))
                continue
            c = g.x[vid].mean(0)
            reg = _surf(body).region(c) if getattr(body, "kind", "") == "mesh" else "torso"
            key = (reg, round(float(c[1]) / 0.08), int(np.sign(c[0])) if reg != "torso" else 0)
            groups.setdefault(key, ([], None))[0].append(vid)
    info = []
    for key, (vids, frac) in groups.items():
        # length of the elastic edges themselves (boundary rows)
        L = sum(float(np.linalg.norm(np.diff(g.uv[v], axis=0), axis=1).sum()) for v in vids)
        if frac is None:
            pts = np.concatenate([g.x[v] for v in vids])
            if key[0] == "torso" and hasattr(body, "girth_at_y"):
                gt = body.girth_at_y(float(pts[:, 1].mean()))
            else:
                gt = girth_at(body, pts.mean(0))
            if gt is None:
                continue
            # an elastic loop round the body: snug (92% of the body), shared by its edges
            frac = min(1.0, 0.92 * gt / L)
        for v in vids:
            _shrink_band(g, v, frac, band=CASING)
        g.meta.setdefault("elastic_verts", []).extend(int(x) for v in vids for x in v)
        info.append({"edges": len(vids), "gathers_to_pct": round(frac * 100),
                     "elastic_cm": round(L * frac * 100, 1)})
    g.meta["elastic"] = info


def design_check(g) -> list[dict]:
    """Plain-language checks for a hand-made design."""
    out = []
    for name, ok in g.meta["placed"].items():
        if not ok:
            out.append({"ok": False, "text": f"'{name}' isn't on the body yet",
                        "plain": "Select it and tap the avatar where its middle should go (or pick a spot)."})
    for s in g.meta["seam_info"]:
        d = s["diff_cm"]
        base = min(s["len_a_cm"], s["len_b_cm"])
        if abs(d) > max(0.3, 0.01 * base) and not s["ease"]:
            longer = s["a"] if d > 0 else s["b"]
            out.append({"ok": False, "seam": [s["a"], s["b"]],
                        "text": f"{s['a']} ↔ {s['b']}: {abs(d):.1f} cm different",
                        "plain": f"{longer} is longer. Make them the same length, or gather the longer one "
                                 f"({abs(d) / base * 100:.0f}% extra) on purpose.",
                        "gather": round(abs(d) / base, 4)})
    for name in g.meta.get("off_host", []):
        out.append({"ok": False, "text": f"'{name}' hangs off the piece it's sewn onto",
                    "plain": "Drag it so it sits fully on that piece (or make it smaller)."})
    from .hems import allowance_cm, curve_excess, max_flat_depth
    for p in g.meta["panels"]:    # a deep hem on a curved edge has too much fabric at its raw edge: it ripples
        for en, hm in (getattr(p, "hems", None) or {}).items():
            E = p.edge(en) * 100
            ex = curve_excess(E, allowance_cm(hm))
            if ex > 0.05:
                ok = max_flat_depth(E) - hm["turn_cm"]
                out.append({"ok": False, "text": f"{p.name}.{en}: the hem curves too much for {allowance_cm(hm):g} cm",
                            "plain": f"Folded up, its raw edge is {ex * 100:.0f}% longer than where it lands, so it "
                                     f"ripples. Make it {max(ok, 0.5):.1f} cm deep or less, or use a narrow hem."})
    seamed = {(s.panel_a, s.edge_a) for s in g.meta["seam_defs"]} | {(s.panel_b, s.edge_b) for s in g.meta["seam_defs"]}
    for p in g.meta["panels"]:
        for en in (getattr(p, "hems", None) or {}):
            if (p.name, en) in seamed:
                out.append({"ok": False, "text": f"{p.name}.{en} is hemmed and sewn",
                            "plain": "A hem goes on an open edge: unsew it, or take the hem off."})
    for note in []:
        out.append({"ok": False, "text": note[0].upper() + note[1:],
                    "plain": "A seam can't go on before the pieces it joins are sewn: it's sewn in that stage instead."})
    n_free = sum(1 for p in g.meta["panels"] for n, _ in p.edges if (p.name, n) not in seamed)
    if not g.meta["seam_defs"] and len(g.meta["panels"]) > 1:
        out.append({"ok": False, "text": "Nothing is sewn together yet",
                    "plain": "Use Sew: tap an edge, then the edge it joins."})
    if not out:
        out.append({"ok": True, "text": f"All {len(g.meta['seam_defs'])} seams match",
                    "plain": f"{n_free} edges are left open (hems, neckline, openings)."})
    return out


# ---------------------------------------------------------------- example --
def example_design():
    """Two rectangles hung from the waist, sewn at the sides, elastic at the top: a gathered skirt."""
    def rect(name, w, h, lm, elastic=False):
        x0, x1 = -w / 2, w / 2
        return {"name": name, "edges": [{"name": "hem", "pts": [[x0, 0], [x1, 0]]},
                                         {"name": "right", "pts": [[x1, 0], [x1, h]]},
                                         {"name": "waist", "pts": [[x1, h], [x0, h]], "elastic": elastic},
                                         {"name": "left", "pts": [[x0, h], [x0, 0]]}],
                "place": {"landmark": lm, "at": "top", "mode": "wrap", "rotate": 0, "offset_cm": 2}}
    return {"pieces": [rect("front", 60, 55, "waist_front", True), rect("back", 60, 55, "waist_back", True)],
            "seams": [{"a": "front.right", "b": "back.left"}, {"a": "front.left", "b": "back.right"}]}
