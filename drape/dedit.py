"""Editing a design (the studio's editor format, cm) from Python: the moves
that are fiddly by hand and that the starter templates are built from.

    split_from_top(d, "front", "side_r", [18, 34])   # also splits the edge it's sewn to
    open_down_middle(d, "front", "buttons")          # two fronts, sewn with a closure
    add_band(d, "neckband", ["front.neck", "back.neck"])
    add_inseam_pocket(d, "front.side_r")             # bags hidden inside the side seam
    add_hip_pocket(d, "front_r", "waist", "outseam") # jeans-style front pocket

A design: {"pieces": [{name, verts, edges: [{name, c1, c2, pts?, elastic}], place, shape, at, ...}],
"seams": [{a: "piece.edge", b, ease, reverse?, closure?}]}. Edge i runs verts[i] -> verts[i+1].
"""
from __future__ import annotations

import copy

import numpy as np

KAPPA = 0.5523


# ------------------------------------------------------------ geometry --
def piece(d, name):
    for p in d["pieces"]:
        if p["name"] == name:
            return p
    raise KeyError(f"no piece {name!r}")


def eidx(pc, en):
    for i, e in enumerate(pc["edges"]):
        if e["name"] == en:
            return i
    raise KeyError(f"{pc['name']} has no edge {en!r}")


def edge_pts(pc, i, n=24) -> np.ndarray:
    V = pc["verts"]
    a, b = np.asarray(V[i], float), np.asarray(V[(i + 1) % len(V)], float)
    e = pc["edges"][i]
    if e.get("pts"):
        return np.asarray(e["pts"], float)
    if not e.get("c1"):
        return np.stack([a, b])
    t = np.linspace(0, 1, n + 1)[:, None]
    c1, c2 = np.asarray(e["c1"], float), np.asarray(e["c2"], float)
    return (1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * c1 + 3 * (1 - t) * t ** 2 * c2 + t ** 3 * b


def epts(d, ref) -> np.ndarray:
    pn, en = ref.split(".", 1)
    pc = piece(d, pn)
    return edge_pts(pc, eidx(pc, en))


def plen(P) -> float:
    return float(np.linalg.norm(np.diff(P, axis=0), axis=1).sum())


def _cum(P):
    return np.r_[0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]


def at_len(P, s):
    c = _cum(P)
    return np.array([np.interp(s, c, P[:, 0]), np.interp(s, c, P[:, 1])])


def cut_poly(P, s0, s1):
    """The part of polyline P between arc lengths s0 < s1."""
    c = _cum(P)
    inside = P[(c > s0) & (c < s1)]
    return np.vstack([at_len(P, s0), inside, at_len(P, s1)])


def outline(pc):
    """[(edge dict, pts)] round the piece."""
    return [(e, edge_pts(pc, i)) for i, e in enumerate(pc["edges"])]


def set_outline(pc, parts):
    """Rebuild verts/edges from [(edge dict, pts)] (each edge keeps its own points).
    Turns the outline counter-clockwise if it isn't."""
    ring = np.vstack([np.asarray(P, float)[:-1] for _, P in parts])
    area = 0.5 * np.sum(ring[:, 0] * np.roll(ring[:, 1], -1) - np.roll(ring[:, 0], -1) * ring[:, 1])
    if area < 0:
        parts = [(e, np.asarray(P, float)[::-1]) for e, P in parts[::-1]]
    verts, edges = [], []
    for e, P in parts:
        P = np.asarray(P, float)
        verts.append([round(float(P[0, 0]), 3), round(float(P[0, 1]), 3)])
        ne = {k: v for k, v in e.items() if k not in ("pts", "c1", "c2")}
        ne.update(c1=None, c2=None)
        if len(P) > 2:
            ne["pts"] = np.round(P, 3).tolist()
        edges.append(ne)
    pc["verts"], pc["edges"] = verts, edges
    pc["shape"] = {"type": "custom"}


def unique(base, taken):
    if base not in taken:
        return base
    k = 2
    while f"{base}_{k}" in taken:
        k += 1
    return f"{base}_{k}"


def seam_of(d, ref):
    for s in d["seams"]:
        if s["a"] == ref:
            return s, "b"
        if s["b"] == ref:
            return s, "a"
    return None, None


def _rename_refs(d, old, parts):
    """An edge became several: loops, lining-open and pocket-sewn lists follow."""
    pn, en = old.split(".", 1)
    for p in d["pieces"]:
        pl = p.get("place") or {}
        if old in (pl.get("loop") or []):
            k = pl["loop"].index(old)
            pl["loop"] = pl["loop"][:k] + [f"{pn}.{x}" for x in parts] + pl["loop"][k + 1:]
    pc = piece(d, pn)
    if pc.get("lining") and en in (pc["lining"].get("open") or []):
        pc["lining"]["open"] = [x for x in pc["lining"]["open"] if x != en] + parts
    if en in ((pc.get("place") or {}).get("sewn") or []):
        pc["place"]["sewn"] = [x for x in pc["place"]["sewn"] if x != en] + parts
    if en in ((pc.get("place") or {}).get("held") or []):
        pc["place"]["held"] = [x for x in pc["place"]["held"] if x != en] + parts


# --------------------------------------------------------- split edges --
def split_edge_at(d, pn, en, lengths, names=None):
    """Split one edge at arc lengths (cm from its first point). Returns the
    new edge names in order. Doesn't touch seams (see split_from_top)."""
    pc = piece(d, pn)
    i = eidx(pc, en)
    P = edge_pts(pc, i)
    L = plen(P)
    cuts = [0.0] + sorted(float(s) for s in lengths if 0.05 < s < L - 0.05) + [L]
    taken = [e["name"] for e in pc["edges"] if e["name"] != en]
    names = list(names) if names else [f"{en}_{k + 1}" for k in range(len(cuts) - 1)]
    names = [unique(n, taken + names[:k]) for k, n in enumerate(names[:len(cuts) - 1])]
    parts = outline(pc)
    e = parts[i][0]
    new = [({**e, "name": nm}, cut_poly(P, cuts[k], cuts[k + 1])) for k, nm in enumerate(names)]
    set_outline(pc, parts[:i] + new + parts[i + 1:])
    _rename_refs(d, f"{pn}.{en}", names)
    return names


def _top_first(P):
    return P[0, 1] >= P[-1, 1]


def split_from_top(d, ref, from_top_cm, suffixes=None):
    """Split an edge at distances measured down from its top end, and the edge
    it is sewn to at the same distances from its top; the parts are sewn in
    pairs. Returns (parts of ref, parts of the partner or None), top first."""
    pn, en = ref.split(".", 1)
    s, other = seam_of(d, ref)
    out = []
    for r in [ref] + ([s[other]] if s else []):
        qn, qe = r.split(".", 1)
        P = epts(d, r)
        L = plen(P)
        tf = _top_first(P)
        at = [c if tf else L - c for c in from_top_cm]
        nm = [qe + (f"_{k + 1}" if suffixes is None else suffixes[k]) for k in range(len(from_top_cm) + 1)]
        parts = split_edge_at(d, qn, qe, at, nm if tf else nm[::-1])
        out.append((qn, parts if tf else parts[::-1], tf))
    if s:
        d["seams"].remove(s)
        (an, ap, atf), (bn, bp, btf) = out
        for x, y in zip(ap, bp):
            d["seams"].append({"a": f"{an}.{x}", "b": f"{bn}.{y}", "ease": s.get("ease", 0),
                               "reverse": bool(atf != btf)})
    return out[0][1], (out[1][1] if s else None)


# ---------------------------------------------------------- cut pieces --
def cut_vertical(d, pn, x0=0.0, names=None, cut_name="cf"):
    """Split a piece along the line x = x0 into two pieces joined by nothing:
    returns (name of the -x part, name of the +x part). Everything that
    referred to the piece follows its edges to the right half."""
    pc = piece(d, pn)
    parts = outline(pc)
    pts, lab = [], []
    for k, (e, P) in enumerate(parts):
        for q in P[:-1]:
            pts.append(q); lab.append(k)
    pts = np.array(pts); n = len(pts)
    # crossings of x = x0 along the closed outline
    seq = []                       # (point, edge index, is_crossing)
    xs = []
    for j in range(n):
        a, b = pts[j], pts[(j + 1) % n]
        seq.append((a, lab[j], False))
        da, db = a[0] - x0, b[0] - x0
        if da * db < 0 or (db == 0 and da != 0):
            t = da / (da - db)
            seq.append((a + t * (b - a), lab[j], True))
            xs.append(len(seq) - 1)
    if len(xs) != 2:
        raise ValueError(f"'{pn}' crosses the middle line {len(xs)} times; can only cut a piece crossing it twice")
    taken = [p["name"] for p in d["pieces"] if p["name"] != pn]
    lo_name, hi_name = names or (unique(pn + "_r", taken), unique(pn + "_l", taken))

    def chain(i0, i1):
        """Outline from crossing i0 round to crossing i1, regrouped by edge."""
        m = len(seq)
        groups = []          # [edge idx, [points]]
        k = i0
        cur = None
        while True:
            p, ei, cross = seq[k]
            if cur is None or (cur[0] != ei and not cross):
                if cur is not None:
                    cur[1].append(p)
                cur = [ei, [p]]; groups.append(cur)
            else:
                cur[1].append(p)
            if k == i1:
                break
            k = (k + 1) % m
        # drop degenerate groups
        return [(parts[ei][0], np.array(P)) for ei, P in groups if len(P) >= 2 and plen(np.array(P)) > 1e-6]

    A = chain(xs[0], xs[1]) + [({"name": cut_name, "elastic": False}, None)]
    B = chain(xs[1], xs[0]) + [({"name": cut_name, "elastic": False}, None)]
    for ch in (A, B):    # close with the straight cut
        ch[-1] = (ch[-1][0], np.stack([ch[-2][1][-1], ch[0][1][0]]))
    sideA = np.mean(np.vstack([P for _, P in A[:-1]])[:, 0]) - x0
    lo, hi = (A, B) if sideA < 0 else (B, A)
    halves = []
    for nm, ch in ((lo_name, lo), (hi_name, hi)):
        # an edge that was cut in two keeps its name on both halves
        np_ = copy.deepcopy({k: v for k, v in pc.items() if k not in ("verts", "edges", "name")})
        q = {"name": nm, **np_}
        seen = {}
        fixed = []
        for e, P in ch:
            e = dict(e)
            if e["name"] in seen:
                e["name"] = unique(e["name"], list(seen))
            seen[e["name"]] = 1
            fixed.append((e, P))
        set_outline(q, fixed)
        halves.append(q)
    k = d["pieces"].index(pc)
    d["pieces"][k:k + 1] = halves
    names_lo = {e["name"] for e in halves[0]["edges"]}
    names_hi = {e["name"] for e in halves[1]["edges"]}
    for s in d["seams"]:
        for key in ("a", "b"):
            qn, qe = s[key].split(".", 1)
            if qn == pn:
                if qe in names_lo and qe in names_hi:
                    raise ValueError(f"{s[key]} is sewn and would be cut in two")
                s[key] = f"{lo_name if qe in names_lo else hi_name}.{qe}"
    for p in d["pieces"]:
        pl = p.get("place") or {}
        if pl.get("on") == pn:
            pl["on"] = hi_name
        if pl.get("loop"):
            new = []
            for r in pl["loop"]:
                qn, qe = r.split(".", 1)
                if qn != pn:
                    new.append(r); continue
                hit = [h["name"] for h in halves if any(e["name"] == qe for e in h["edges"])]
                new += [f"{h}.{qe}" for h in hit]
            pl["loop"] = new
    return lo_name, hi_name


# ------------------------------------------------------------- closures --
CLOSURES = {
    "buttons": {"label": "Buttons", "size_mm": 15, "stand": True},
    "snaps": {"label": "Snaps", "size_mm": 12, "stand": True},
    "zipper": {"label": "Zipper", "size_mm": 0, "stand": False},
    "hook_loop": {"label": "Hook & loop tape", "size_mm": 20, "stand": True},
}


def closure_seam(d, a, b, kind="buttons", count=None, size_mm=None, open_frac=0.0):
    """Sew a and b with a closure (replacing any seam they had)."""
    d["seams"] = [s for s in d["seams"] if s["a"] not in (a, b) and s["b"] not in (a, b)]
    C = CLOSURES[kind]
    L = plen(epts(d, a))
    if count is None:
        count = max(2, int(round(L / 9.0))) if kind in ("buttons", "snaps") else 1
    s = {"a": a, "b": b, "ease": 0, "closure": {"type": kind, "count": int(count),
                                                 "size_mm": float(size_mm if size_mm is not None else C["size_mm"]),
                                                 "open": float(open_frac)}}
    d["seams"].append(s)
    return s


def open_down_middle(d, pn, kind="buttons", holes="right", **kw):
    """Cut a piece down its centre line and close it with buttons/snaps/a zipper.
    holes: which front gets the buttonholes, on the wearer: "right" (women's
    wear: right over left) or "left" (men's)."""
    lo, hi = cut_vertical(d, pn, 0.0)          # lo = -x = the wearer's right
    a, b = (lo, hi) if holes == "right" else (hi, lo)
    closure_seam(d, f"{a}.cf", f"{b}.cf", kind, **kw)
    return lo, hi


def partial_closure(d, ref, length_cm, kind="zipper", open_frac=0.0, **kw):
    """A closure in the top part of a seam (a skirt's zipper, a fly, a henley
    placket): the rest stays sewn. Returns the closure seam."""
    P = epts(d, ref)
    s, o = seam_of(d, ref)
    if s is None:
        raise ValueError(f"{ref} isn't sewn to anything: sew it first")
    pn = ref.split(".")[0]
    if length_cm < plen(P) - 1.0:
        top, _ = split_from_top(d, ref, [length_cm], suffixes=["_" + ("zip" if kind == "zipper" else "open"), ""])
        a = f"{pn}.{top[0]}"
        s, o = seam_of(d, a)
    keep = {k: v for k, v in s.items() if k not in ("closure", "ease", "reverse")}
    d["seams"].remove(s)
    new = closure_seam(d, keep["a"], keep["b"], kind, open_frac=open_frac, **kw)
    if s.get("reverse") is not None:
        new["reverse"] = s["reverse"]
    return new


def add_zipper(d, ref, length_cm, open_frac=0.0):
    """A zipper in the top part of a seam (a skirt's back, a fly): the rest stays sewn."""
    return partial_closure(d, ref, length_cm, "zipper", open_frac)


# --------------------------------------------------------------- bands --
# Bands round an opening. Creating one is behind features.OPENING_BANDS; the hood is not
# a band (add_hood) and is always available.
BANDS = {
    "neckband": dict(h=3, ratio=0.85, dir="up", fabric="rib"),
    "collar": dict(h=4, ratio=1.0, dir="up", interfacing="light"),
    "waistband": dict(h=4, ratio=1.0, dir="up", interfacing="medium"),
    "cuff": dict(h=7, ratio=0.9, dir="down", fabric="rib"),
    "hemband": dict(h=6, ratio=0.9, dir="down", fabric="rib"),
}
HOOD = dict(h=34, ratio=1.0, dir="up")


BAND_ROLE = {"neckband": "collar", "collar": "collar", "waistband": "waistband", "cuff": "cuff",
             "hemband": "waistband"}     # (a hem band is a band round the bottom opening)


def add_band(d, kind, loop, h=None, ratio=None, name=None, fabric=None, interfacing=None, elastic=False,
             ordered=False):
    """A band sewn round an opening (the edges in `loop`, in order round it). `ordered`
    is accepted for the callers' sake (a band's loop is used as given). kind "hood"
    is passed on to add_hood."""
    if kind == "hood":
        return add_hood(d, loop, h=h, name=name, ordered=ordered)
    B = dict(BANDS[kind])
    h = B["h"] if h is None else h
    ratio = B["ratio"] if ratio is None else ratio
    return _sewn_round(d, kind, list(loop), h, ratio, name or kind, BAND_ROLE[kind], B["dir"],
                       fabric or B.get("fabric"), interfacing or B.get("interfacing"), elastic, hood=False)


def add_hood(d, loop, h=None, name=None, ordered=False):
    """A hood sewn round the neckline (the edges in `loop`, in order round it), open at
    the centre front. ordered: the loop already starts where it should
    (freeform.order_loop): don't split its first edge at x = 0."""
    h = HOOD["h"] if h is None else h
    loop = list(loop)
    if not ordered:     # open at centre front: split the front neckline there
        pn, en = loop[0].split(".", 1)
        P = epts(d, loop[0])
        if P[0, 0] * P[-1, 0] < 0:
            c = _cum(P)
            k = int(np.nonzero(P[:-1, 0] * P[1:, 0] <= 0)[0][0])
            u = P[k, 0] / ((P[k, 0] - P[k + 1, 0]) or 1)
            e1, e2 = split_edge_at(d, pn, en, [c[k] + u * (c[k + 1] - c[k])])
            loop = [f"{pn}.{e2}"] + loop[1:] + [f"{pn}.{e1}"]
    return _sewn_round(d, "hood", loop, h, HOOD["ratio"], name or "hood", "hood", HOOD["dir"],
                       None, None, False, hood=True)


def _sewn_round(d, kind, loop, h, ratio, name, role, direction, fabric, interfacing, elastic, hood):
    """The piece for a band or a hood: as long as the opening (times ratio), its
    edges join_1 .. join_k sewn to the loop's edges in order."""
    lens = [plen(epts(d, r)) * ratio for r in loop]
    L = sum(lens)
    name = unique(name, [p["name"] for p in d["pieces"]])
    verts, edges = [], []
    x = -L / 2
    for k, l in enumerate(lens):
        verts.append([x, 0]); edges.append({"name": f"join_{k + 1}", "c1": None, "c2": None, "elastic": False})
        x += l
    verts.append([L / 2, 0]); edges.append({"name": "end_r", "c1": None, "c2": None, "elastic": False})
    if hood:
        verts.append([L / 2, h]); edges.append({"name": "top_r", "c1": None, "c2": None, "elastic": False})
        verts.append([0, h * 1.12]); edges.append({"name": "top_l", "c1": None, "c2": None, "elastic": False})
    else:
        verts.append([L / 2, h]); edges.append({"name": "top", "c1": None, "c2": None, "elastic": bool(elastic)})
    verts.append([-L / 2, h]); edges.append({"name": "end_l", "c1": None, "c2": None, "elastic": False})
    pc = {"name": name, "verts": verts, "edges": edges, "shape": {"type": "custom"}, "at": [0, 0],
          "role": role,
          "place": {"loop": loop, "dir": direction, "offset_cm": 0.5, "rotate": 0, "layer": 0}}
    if fabric:
        pc["fabric"] = fabric
    if interfacing:
        pc["interfacing"] = interfacing
    d["pieces"].append(pc)
    ease = round(1 / ratio - 1, 4) if ratio < 1 else 0
    for k, r in enumerate(loop):
        d["seams"] = [s for s in d["seams"] if s["a"] != r and s["b"] != r]
        d["seams"].append({"a": f"{name}.join_{k + 1}", "b": r, "ease": ease})
    if hood:
        d["seams"].append({"a": f"{name}.top_r", "b": f"{name}.top_l", "ease": 0, "reverse": True})
    else:
        d["seams"].append({"a": f"{name}.end_r", "b": f"{name}.end_l", "ease": 0})
    return name


# ------------------------------------------------------------- pockets --
def rect(name, w, h, x0=None, y0=0.0):
    x0 = -w / 2 if x0 is None else x0
    x1 = x0 + w
    return {"name": name, "verts": [[x0, y0], [x1, y0], [x1, y0 + h], [x0, y0 + h]], "at": [0, 0],
            "edges": [{"name": n, "c1": None, "c2": None, "elastic": False} for n in ("bottom", "right", "top", "left")],
            "shape": {"type": "rect", "w": w, "h": h}, "place": {"mode": "wrap", "rotate": 0, "offset_cm": 1.5, "at": "center"}}


def add_patch_pocket(d, host, w=16, h=18, centre=None, name="pocket", inside=False, rounded=False, sewn=None):
    """A patch pocket topstitched onto a piece (inside=True: on the inside face,
    like a jacket's inner pocket). centre: (x, y) on the host in cm."""
    hp = piece(d, host)
    V = np.vstack([P for _, P in outline(hp)])
    if centre is None:
        centre = ((V[:, 0].min() + V[:, 0].max()) / 2, (V[:, 1].min() + V[:, 1].max()) / 2)
    nm = unique(name, [p["name"] for p in d["pieces"]])
    pc = rect(nm, w, h, -w / 2, -h / 2)
    if rounded:     # rounded bottom corners
        r = min(3.0, w / 4)
        k = KAPPA * r
        x0, x1, y0, y1 = -w / 2, w / 2, -h / 2, h / 2
        pc["verts"] = [[x0 + r, y0], [x1 - r, y0], [x1, y0 + r], [x1, y1], [x0, y1], [x0, y0 + r]]
        pc["edges"] = [{"name": "bottom", "c1": None, "c2": None},
                       {"name": "corner_r", "c1": [x1 - r + k, y0], "c2": [x1, y0 + r - k]},
                       {"name": "right", "c1": None, "c2": None},
                       {"name": "top", "c1": None, "c2": None},
                       {"name": "left", "c1": None, "c2": None},
                       {"name": "corner_l", "c1": [x0, y0 + r - k], "c2": [x0 + r - k, y0]}]
        for e in pc["edges"]:
            e["elastic"] = False
        pc["shape"] = {"type": "custom"}
    # keep it on the piece (1 cm in from the edge): slide toward the middle, then shrink
    from shapely.geometry import Polygon
    from shapely import affinity
    hpoly = Polygon(V).buffer(0).buffer(-1.0)
    own = Polygon(np.vstack([P for _, P in outline(pc)]))
    mid = np.array(hpoly.representative_point().coords[0]) if not hpoly.is_empty else np.asarray(centre, float)
    c = np.asarray(centre, float)
    for k in range(40):
        if hpoly.is_empty or hpoly.contains(affinity.translate(own, *c)):
            break
        if k < 25:
            c = c + (mid - c) * 0.12
        else:
            own = affinity.scale(own, 0.93, 0.93, origin=(0, 0))
            scale_piece(pc, 0.93)
    centre = c
    pc["place"] = {"on": host, "pos": [float(centre[0]), float(centre[1])], "rotate": 0,
                   "sewn": sewn or [e["name"] for e in pc["edges"] if e["name"] != "top"], "layer": 0}
    if inside:
        pc["place"]["inside"] = True
    # role (sewing order, stages.py): a patch pocket goes on last; one inside goes with its piece
    pc["role"] = "other" if inside else "pocket"
    d["pieces"].append(pc)
    return nm


def scale_piece(pc, f):
    """Scale a piece about its own origin."""
    set_outline(pc, [(e, P * f) for e, P in outline(pc)])


def _bag(opening_len, width, depth, up):
    """Pocket bag in its own frame: the opening along x = 0 from (0, L) down to
    (0, 0), the bag out to +x and down, its top `up` above the opening (up to
    the waist, where it is caught). Returns [(name, polyline)] counter-clockwise."""
    L, w, dd = opening_len, width, depth
    a = np.linspace(np.pi, 2 * np.pi, 15)
    bottom = np.stack([w / 2 + w / 2 * np.cos(a), -dd * 0.5 + dd * 0.5 * np.sin(a)], 1)   # (0,-dd/2) .. (w,-dd/2)
    T = L + max(up, 1.0)
    return [("opening", np.array([[0.0, L], [0.0, 0.0]])),
            ("bag", np.vstack([[[0.0, 0.0]], bottom, [[w, T]]])),
            ("top", np.array([[w, T], [0.0, T]])),
            ("upper", np.array([[0.0, T], [0.0, L]]))]


def _frame(P_top, P_bot, inward_sign):
    """Rigid map from the bag frame to host coords (+ mirror so +x points inward)."""
    v = P_top - P_bot
    L = np.linalg.norm(v)
    up = v / L
    side = np.array([up[1], -up[0]])          # +90 deg clockwise from up
    if side[0] * inward_sign < 0:
        side = -side
    return lambda q: P_bot + np.outer(q[:, 0], side) + np.outer(q[:, 1], up), L


def body_height_offsets(d, body):
    """{piece: offset (cm)}: on the avatar, a point's height is its pattern y + the offset
    (pieces hang upright: exact for the blocks, measured 0.0 mm off). One build of the design."""
    from .freeform import build_design, editor_to_design
    g = build_design(editor_to_design(d), body)
    return {nm: float(np.median(g.x[g.panel_id == k, 1] - g.uv[g.panel_id == k, 1]) * 100)
            for k, nm in enumerate(g.panel_names)}


def _arclen_at_y(P, y):
    """Distance along a top-first polyline to where it first comes down to height y (None: never)."""
    s = 0.0
    for a, b in zip(P[:-1], P[1:]):
        L = float(np.linalg.norm(b - a))
        if (a[1] - y) * (b[1] - y) <= 0 and a[1] != b[1]:
            return s + L * (a[1] - y) / (a[1] - b[1])
        s += L
    return None


def _top_first_pts(d, ref):
    P = epts(d, ref)
    return P if _top_first(P) else P[::-1]


def _edge_at_height(d, ref, y):
    """ref, or the sewn edge of the same piece and kind (side_1_r / side_2_r, outseam_1 ...)
    that reaches height y: a dress's side seam is cut by the bust dart, and the pocket goes in
    the part at the hips."""
    import re
    pn, en = ref.split(".", 1)
    P = epts(d, ref)
    if P[:, 1].min() <= y <= P[:, 1].max():
        return ref
    stem = re.sub(r"_?[0-9]+", "", en)
    for e in piece(d, pn)["edges"]:
        n = e["name"]
        if n == en or re.sub(r"_?[0-9]+", "", n) != stem or seam_of(d, f"{pn}.{n}")[0] is None:
            continue
        Q = epts(d, f"{pn}.{n}")
        if Q[:, 1].min() <= y <= Q[:, 1].max():
            return f"{pn}.{n}"
    return ref


def _hanging_bag(P_open, P_below, inward, width, depth, top_y, P_above=None):
    """A pocket bag that hangs straight down (pattern y is the body's up: pieces hang upright),
    whatever the seam's angle or curve. The opening follows the seam; the bag's outer side runs
    straight down from the opening's bottom, or along the seam 5 mm in where the seam narrows (so
    it stays inside the piece); a rounded bottom `depth` below the opening; the inner side straight
    up to `top_y`; above the opening the bag's side follows the seam (P_above, top first) up to
    `top_y` (a skirt's side seam curves in toward the waist). Host coordinates (cm). Returns
    [(name, polyline)] as _bag does."""
    s = inward
    top, bot = P_open[0], P_open[-1]
    y_round = bot[1] - 0.45 * depth            # where the bottom starts to round
    y_low = bot[1] - depth                     # the bag's lowest point
    x_in = (P_open[:, 0].max() if s > 0 else P_open[:, 0].min()) + s * width

    def seam_x(y):                             # the seam's x under the opening, at height y
        if P_below is None or len(P_below) < 2 or y > P_below[0, 1] or y < P_below[-1, 1]:
            return None
        Q = P_below[::-1]                      # increasing y, for interp
        return float(np.interp(y, Q[:, 1], Q[:, 0]))

    def outer_x(y):
        sx = seam_x(y)
        if sx is None:
            return float(bot[0])
        return max(bot[0], sx + 0.5) if s > 0 else min(bot[0], sx - 0.5)
    ys = np.linspace(bot[1], y_round, 6)
    outer = np.array([[outer_x(y), y] for y in ys])
    outer[0] = bot                             # starts exactly at the opening's bottom (on the seam)
    xo = outer[-1, 0]
    a = np.linspace(0.0, np.pi, 15)            # the rounded bottom, from the outer side to the inner
    cx, rx, ry = (xo + x_in) / 2, (x_in - xo) / 2, y_round - y_low
    bottom = np.stack([cx - rx * np.cos(a), y_round - ry * np.sin(a)], 1)
    bag = np.vstack([outer, bottom[1:], [[x_in, top_y]]])
    # above the opening: along the seam (from top_y down to the opening's top), not straight up
    upper = np.array([[top[0], top_y], top])
    if P_above is not None and len(P_above) >= 2 and P_above[0, 1] >= top_y > top[1]:
        Q = P_above[::-1]                      # increasing y
        x_top = float(np.interp(top_y, Q[:, 1], Q[:, 0]))
        mid = P_above[(P_above[:, 1] < top_y) & (P_above[:, 1] > top[1])]
        upper = np.vstack([[[x_top, top_y]], mid, [top]])
    return [("opening", P_open),
            ("bag", bag),
            ("top", np.array([[x_in, top_y], upper[0]])),
            ("upper", upper)]


def add_inseam_pocket(d, ref, from_top_cm=None, opening_cm=16.0, depth_cm=12.0, width_cm=16.0, name="pocket",
                      body=None, below_waist_cm=None):
    """Pockets hidden in a seam (skirts, dresses, trousers), on a seam of any angle or curve:
    the seam is left open over the opening, a bag inside each side is sewn to it, the two bags
    are sewn together round their edges, and both hang straight down inside the front.

    Where the opening goes: `from_top_cm` down the edge from its top end; or, with `body`,
    `below_waist_cm` under the avatar's waist (3 cm if not given), on whichever part of the seam
    is at that height (a dress's side seam below the bust dart). The bag's top reaches up into a
    waist seam when there is one within 8 cm above the opening (caught in it); otherwise it stops
    3 cm above the opening (tacked to the front)."""
    if from_top_cm is None and body is not None:
        below = 3.0 if below_waist_cm is None else float(below_waist_cm)
        pn = ref.split(".", 1)[0]
        top_y = body.section_y("waist") * 100 - body_height_offsets(d, body)[pn] - below
        ref = _edge_at_height(d, ref, top_y)
        P = _top_first_pts(d, ref)
        s0 = _arclen_at_y(P, top_y)
        L = plen(P)
        from_top_cm = 1.0 if s0 is None else s0
        if from_top_cm + opening_cm > L - 1.0:     # a short edge: the opening fits on it
            from_top_cm = max(1.0, L - 1.0 - opening_cm)
            opening_cm = min(opening_cm, L - 1.0 - from_top_cm)
    elif from_top_cm is None:
        from_top_cm = 5.0
    s, other = seam_of(d, ref)
    if s is None:
        raise ValueError(f"{ref} isn't sewn to anything: an in-seam pocket goes in a seam")
    edge_top_y = float(_top_first_pts(d, ref)[0, 1])
    parts_a, parts_b = split_from_top(d, ref, [from_top_cm, from_top_cm + opening_cm])
    pa, pb = ref.split(".")[0], s[other].split(".")[0]
    oa, ob = f"{pa}.{parts_a[1]}", f"{pb}.{parts_b[1]}"
    d["seams"] = [x for x in d["seams"] if not ({x["a"], x["b"]} == {oa, ob})]
    names = [p["name"] for p in d["pieces"]]
    bags = []
    # both bags lie against the front (pa): the back's bag folds over to it, as sewn
    hp = piece(d, pa)
    V = np.vstack([P for _, P in outline(hp)])
    P_open = _top_first_pts(d, oa)
    P_below = _top_first_pts(d, f"{pa}.{parts_a[2]}") if len(parts_a) > 2 else None
    top = P_open[0]
    inward = float(np.sign(V[:, 0].mean() - P_open[:, 0].mean())) or 1.0
    # a waist seam just above the opening catches the bag's top; otherwise it ends 3 cm above
    top_y = edge_top_y - 0.5 if edge_top_y - top[1] <= 8.0 else float(top[1]) + 3.0
    # and under the piece's top all the way across the bag (a skirt's waist curves down to the
    # centre front): the lowest of the piece's edge above the bag's span, less 5 mm
    from shapely.geometry import LineString, Polygon
    poly = Polygon(V).buffer(0)
    x_in = (P_open[:, 0].max() if inward > 0 else P_open[:, 0].min()) + inward * width_cm
    for x in np.linspace(min(top[0], x_in), max(top[0], x_in), 12):
        cut = poly.intersection(LineString([(x, top[1] - 1e3), (x, top[1] + 1e3)]))
        for seg in getattr(cut, "geoms", [cut]):
            ys = [q[1] for q in getattr(seg, "coords", [])]
            if ys and min(ys) - 0.01 <= top[1] <= max(ys) + 0.01:     # the part of the piece at the opening
                top_y = min(top_y, max(ys) - 0.5)
    top_y = max(top_y, float(top[1]) + 1.0)
    P_above = _top_first_pts(d, f"{pa}.{parts_a[0]}") if from_top_cm > 0 else None
    for depth, oref in ((1, oa), (2, ob)):
        nm = unique(f"{name}_bag", names + bags)
        parts = [({"name": n, "elastic": False}, Q) for n, Q in
                 _hanging_bag(P_open, P_below, inward, width_cm, depth_cm, top_y, P_above)]
        # the bag's top is caught in the waist seam (or tacked); the pair is held to the front
        # round its edge (a stay stitch), so it can't fall out through the opening
        pc = {"name": nm, "at": [0, 0], "fabric": "lining", "role": "other",   # sewn with its piece
              "place": {"on": pa, "pos": [0, 0], "rotate": 0, "sewn": ["top", "bag"] if depth == 1 else ["top"],
                        "inside": depth, "layer": 0}}
        set_outline(pc, parts)
        d["pieces"].append(pc)
        bags.append(nm)
        d["seams"].append({"a": f"{nm}.opening", "b": oref, "ease": 0})
    d["seams"].append({"a": f"{bags[0]}.bag", "b": f"{bags[1]}.bag", "ease": 0})
    d["seams"].append({"a": f"{bags[0]}.upper", "b": f"{bags[1]}.upper", "ease": 0})
    return bags


def add_hip_pocket(d, pn, waist="waist", side="outseam", across_cm=11.0, down_cm=16.0, name=None):
    """Front hip pocket (jeans, chinos): a curved opening cut from the corner
    where the waist meets the side seam, and a pocket yoke behind it (seen
    through the opening, sewn into the side seam and the waist)."""
    pc = piece(d, pn)
    for p in d["pieces"]:
        if f"{pn}.{waist}" in ((p.get("place") or {}).get("loop") or []):
            raise ValueError(f"take the {p['name']} off first (add the pocket, then the band)")
    iw, iside = eidx(pc, waist), eidx(pc, side)
    n = len(pc["edges"])
    W, S = edge_pts(pc, iw), edge_pts(pc, iside)
    # the corner C: shared end of the two edges
    if (iside + 1) % n == iw:            # side runs into the corner, waist runs away from it
        C = S[-1]; side_first = True
    elif (iw + 1) % n == iside:
        C = W[-1]; side_first = False
    else:
        raise ValueError(f"{waist} and {side} don't meet at a corner")
    Lw, Ls = plen(W), plen(S)
    if across_cm > Lw - 3 or down_cm > Ls - 5:
        raise ValueError("pocket is too big for this piece")
    # points
    if side_first:   # waist goes C -> away: A at across from start; side goes ... -> C: B at Ls-down
        A = at_len(W, across_cm); A2 = at_len(W, across_cm + 4)
        B = at_len(S, Ls - down_cm)
    else:            # waist goes ... -> C ; side goes C -> away
        A = at_len(W, Lw - across_cm); A2 = at_len(W, Lw - across_cm - 4)
        B = at_len(S, down_cm)
    # opening curve A -> B, bowing toward the corner? (jeans: a scoop away from it)
    mid = (A + B) / 2
    away = mid - C
    away /= np.linalg.norm(away) + 1e-9
    ctrl = mid + away * 0.18 * np.linalg.norm(A - B)
    t = np.linspace(0, 1, 17)[:, None]
    curve = (1 - t) ** 2 * A + 2 * (1 - t) * t * ctrl + t ** 2 * B          # A -> B
    # --- the front loses the corner
    parts = outline(pc)
    new = []
    for k, (e, P) in enumerate(parts):
        if k == iw:
            if side_first:
                new.append((e, cut_poly(P, across_cm, Lw)))
            else:
                new.append((e, cut_poly(P, 0, Lw - across_cm)))
                new.append(({"name": "pocket_edge", "elastic": False}, curve))                       # A -> B
        elif k == iside:
            if side_first:
                new.append((e, cut_poly(P, 0, Ls - down_cm)))
                new.append(({"name": "pocket_edge", "elastic": False}, curve[::-1]))                 # B -> A
            else:
                new.append((e, cut_poly(P, down_cm, Ls)))
        else:
            new.append((e, P))
    set_outline(pc, new)
    # --- the side seam: the back's side splits where the opening ends
    sref = f"{pn}.{side}"
    s, other = seam_of(d, sref)
    yoke = unique(name or f"{pn}_yoke", [p["name"] for p in d["pieces"]])
    # yoke outline: C -> along waist to A (waist), A -> A2 (waist_under), A2 -> B (under), B -> C (side)
    # the yoke reaches under the front: the opening curve slid along the waist
    # (toward the centre), tapering to nothing where the opening meets the side
    under = curve + np.outer(1 - t[:, 0], A2 - A)
    if side_first:
        wpart = cut_poly(W, 0, across_cm); wunder = cut_poly(W, across_cm, across_cm + 4)
        spart = cut_poly(S, Ls - down_cm, Ls)                     # B -> C
        yparts = [({"name": "waist", "elastic": False}, wpart), ({"name": "waist_under", "elastic": False}, wunder),
                  ({"name": "under", "elastic": False}, under), ({"name": "side", "elastic": False}, spart)]
    else:
        wpart = cut_poly(W, Lw - across_cm, Lw); wunder = cut_poly(W, Lw - across_cm - 4, Lw - across_cm)
        spart = cut_poly(S, 0, down_cm)                           # C -> B
        yparts = [({"name": "side", "elastic": False}, spart), ({"name": "under", "elastic": False}, under[::-1]),
                  ({"name": "waist_under", "elastic": False}, wunder), ({"name": "waist", "elastic": False}, wpart)]
    yp = {"name": yoke, "at": [0, 0], "role": "other",
          "place": {"on": pn, "pos": [0, 0], "rotate": 0, "sewn": ["under", "waist_under"], "inside": True,
                    "yoke": True, "layer": 0}}
    if pc.get("fabric"):
        yp["fabric"] = pc["fabric"]
    set_outline(yp, yparts)
    d["pieces"].append(yp)
    if s is not None:
        oref = s[other]
        qn, qe = oref.split(".", 1)
        Q = epts(d, oref)
        tf = _top_first(Q)
        LQ = plen(Q)
        cut_at = down_cm if tf else LQ - down_cm
        qparts = split_edge_at(d, qn, qe, [cut_at], [qe + "_top", qe] if tf else [qe, qe + "_top"])
        d["seams"].remove(s)
        sd = {k: v for k, v in s.items() if k not in ("a", "b")}
        d["seams"].append({**sd, "a": sref, "b": f"{qn}.{qe}", "reverse": None})
        d["seams"].append({"a": f"{yoke}.side", "b": f"{qn}.{qe}_top", "ease": 0, "reverse": None})
    return yoke


def mirror_x(pc):
    """Mirror a piece left-right in place (outline stays CCW)."""
    parts = outline(pc)
    M = np.array([-1.0, 1.0])
    set_outline(pc, [(e, (P * M)[::-1]) for e, P in parts[::-1]])


# ------------------------------------------------- shaping with a shape --
# Cut a shape away, join it on, or keep only where they overlap, without losing
# the piece's sewing: an edge the shape doesn't touch keeps its name, curve and
# seam; an edge it shortens keeps its name and seam (the checks then flag the
# length); an edge it cuts in two becomes <name>_1, <name>_2, unsewn. The shape's
# own edges come in as new edges ('cut', 'added', 'trim').
SHAPE_OPS = {"cut": "cut", "join": "added", "keep": "trim"}     # what the new edges are called


def _ccw(parts):
    ring = np.vstack([np.asarray(P, float)[:-1] for _, P in parts])
    area = 0.5 * np.sum(ring[:, 0] * np.roll(ring[:, 1], -1) - np.roll(ring[:, 0], -1) * ring[:, 1])
    return parts if area >= 0 else [(e, np.asarray(P, float)[::-1]) for e, P in parts[::-1]]


def _polygon(parts, what):
    from shapely.geometry import Polygon
    poly = Polygon(np.vstack([np.asarray(P, float)[:-1] for _, P in parts]))
    if not poly.is_valid or poly.area < 1e-6:
        raise ValueError(f"{what}: the outline crosses itself")
    return poly


def _turn(P, Q):
    """Angle (degrees) between the end of polyline P and the start of polyline Q."""
    u, v = P[-1] - P[-2], Q[1] - Q[0]
    c = float(np.dot(u, v) / ((np.linalg.norm(u) * np.linalg.norm(v)) or 1))
    return float(np.degrees(np.arccos(np.clip(c, -1, 1))))


def _bare(e):
    return {k: v for k, v in e.items() if k not in ("pts", "c1", "c2")}


def _rename_piece_refs(d, old_piece, new_piece, edge_names):
    """Seams and band loops on these edges of old_piece now point at new_piece."""
    keys = {f"{old_piece}.{n}": f"{new_piece}.{n}" for n in edge_names}
    for s in d["seams"]:
        for k in ("a", "b"):
            if s[k] in keys:
                s[k] = keys[s[k]]
    for p in d["pieces"]:
        pl = p.get("place") or {}
        if pl.get("loop"):
            pl["loop"] = [keys.get(r, r) for r in pl["loop"]]


def shape_with(d, pn, tools, op="cut", src=None):
    """Change piece pn with a shape: op 'cut' (cut it away), 'join' (join it on)
    or 'keep' (keep only the overlap). tools: one or more outlines in pn's own
    coordinates (cm), each a list of edges {name, pts}; several are used as one
    (a shape and its mirror image). src: the piece the shape was taken from; on
    'join' it becomes part of pn (its edges, seams and all) and is removed.
    Returns (names of the pieces made, notes for the user)."""
    from collections import Counter
    from shapely.geometry import LineString, Point
    from shapely.ops import unary_union
    if op not in SHAPE_OPS:
        raise ValueError(f"unknown shape operation {op!r}")
    pc = piece(d, pn)
    A_parts = [(e, edge_pts(pc, i, 48)) for i, e in enumerate(pc["edges"])]
    A = _polygon(A_parts, f"'{pn}'")
    T_parts, polys = [], []
    for t in tools:
        tp = [({**_bare(e), "name": e.get("name") or "shape"}, np.asarray(e["pts"], float)) for e in t]
        polys.append(_polygon(tp, "The shape"))
        T_parts += tp
    T = unary_union(polys)
    if not T.intersects(A) or (op != "join" and T.intersection(A).area < 1e-3):
        raise ValueError("The shape doesn't overlap the piece: drag it onto the part you want to change")
    R = {"cut": A.difference, "join": A.union, "keep": A.intersection}[op](T)
    geoms = [g for g in getattr(R, "geoms", [R]) if g.geom_type == "Polygon" and g.area > 0.5]
    if not geoms:
        raise ValueError("The shape covers the whole piece: nothing would be left" if op == "cut"
                         else "Nothing would be left: the shape and the piece hardly overlap")
    if op == "join" and len(geoms) > 1:
        raise ValueError("The shape has to overlap the piece to join on: drag it so they overlap")
    if any(len(g.interiors) for g in geoms):
        raise ValueError("That would leave a hole in the middle of the piece, and holes aren't supported yet: "
                         "move the shape so it crosses the edge")
    if op == "cut" and len(geoms) == 1 and abs(geoms[0].area - A.area) < 1e-3:
        raise ValueError("The shape doesn't overlap the piece: drag it onto the part you want to change")

    lines_A = [LineString(P) for _, P in A_parts]
    lines_T = [LineString(P) for _, P in T_parts]
    a_names = [e["name"] for e, _ in A_parts]

    def tag(p, q):     # which edge a stretch of the new outline lies on (the piece's own first)
        m = Point((p + q) / 2)
        da = [L.distance(m) for L in lines_A]
        dt = [L.distance(m) for L in lines_T]
        i, j = int(np.argmin(da)), int(np.argmin(dt))
        return ("A", i) if da[i] < 1e-4 or da[i] <= dt[j] else ("T", j)

    results = []                     # per new piece: [(key, pts)] round the outline
    for g in sorted(geoms, key=lambda g: -g.area):
        C = np.asarray(g.exterior.coords, float)[:-1]
        m = len(C)
        keys = [tag(C[k], C[(k + 1) % m]) for k in range(m)]
        start = next((k for k in range(m) if keys[k] != keys[k - 1]), 0)
        runs = []
        for jj in range(m):
            k = (start + jj) % m
            if runs and runs[-1][0] == keys[k]:
                runs[-1][1].append(k)
            else:
                runs.append([keys[k], [k]])
        out = [(key, np.vstack([C[ks], C[(ks[-1] + 1) % m][None]])) for key, ks in runs]
        if not src:                  # a drawn shape: smooth stretches of it become one edge (a circle's quarters)
            merged = []
            for key, P in out:
                if merged and key[0] == "T" and merged[-1][0][0] == "T" and _turn(merged[-1][1], P) < 20:
                    merged[-1] = (merged[-1][0], np.vstack([merged[-1][1], P[1:]]))
                else:
                    merged.append((key, P))
            if len(merged) > 1 and merged[0][0][0] == "T" and merged[-1][0][0] == "T" \
                    and _turn(merged[-1][1], merged[0][1]) < 20:
                merged[0] = (merged[0][0], np.vstack([merged[-1][1], merged[0][1][1:]]))
                merged.pop()
            out = merged
        results.append(out)

    count = Counter(key for out in results for key, _ in out)
    notes, made = [], []
    taken_pieces = [p["name"] for p in d["pieces"]]
    split_parts = {}                 # piece edge name -> the names its pieces got
    moved = []                       # (new piece, edge names that went to it)
    src_names = {}                   # src edge name -> its name on the joined piece
    serial = Counter()
    for gi, out in enumerate(results):
        target = pc if gi == 0 else copy.deepcopy(pc)
        if gi:
            target["name"] = unique(f"{pn}_{chr(ord('a') + gi)}", taken_pieces)
            taken_pieces.append(target["name"])
        taken, parts = [], []
        for key, P in out:
            if key[0] == "A":
                e = A_parts[key[1]][0]
                if count[key] == 1:
                    nm = unique(e["name"], taken)
                else:
                    serial[key] += 1
                    nm = unique(f"{e['name']}_{serial[key]}", taken + a_names)
                    split_parts.setdefault(e["name"], []).append(nm)
                ne = {**_bare(e), "name": nm}
            elif src:
                e = T_parts[key[1]][0]
                nm = e["name"] if e["name"] not in taken + a_names else unique(f"{src}_{e['name']}", taken + a_names)
                if count[key] == 1:
                    src_names[e["name"]] = nm
                ne = {**_bare(e), "name": nm}
            else:
                nm = unique(SHAPE_OPS[op], taken + a_names)
                ne = {"name": nm, "elastic": False}
            taken.append(nm)
            parts.append((ne, P))
        set_outline(target, parts)
        if gi:
            d["pieces"].insert(d["pieces"].index(pc) + gi, target)
            moved.append((target["name"], [e["name"] for e, _ in parts]))
        made.append(target["name"])

    # the sewing follows the edges
    for en, parts in split_parts.items():
        s, _ = seam_of(d, f"{pn}.{en}")
        if s is not None:
            d["seams"].remove(s)
            notes.append(f"{pn}.{en} was sewn: it's in {len(parts)} parts now ({', '.join(parts)}), sew them again")
        _rename_refs(d, f"{pn}.{en}", parts)
    for i, en in enumerate(a_names):
        if not count[("A", i)]:
            s, _ = seam_of(d, f"{pn}.{en}")
            if s is not None:
                d["seams"].remove(s)
                notes.append(f"{pn}.{en} was cut away, and its seam with it")
    for nm, names in moved:
        _rename_piece_refs(d, pn, nm, names)
    if src and op == "join":
        sp = piece(d, src)
        for s in list(d["seams"]):
            for k in ("a", "b"):
                p_, e_ = s[k].split(".", 1)
                if p_ != src:
                    continue
                if e_ in src_names:
                    s[k] = f"{pn}.{src_names[e_]}"
                else:
                    d["seams"].remove(s)
                    notes.append(f"{src}.{e_} is inside the joined piece now, so its seam is gone")
                    break
        for p in d["pieces"]:
            pl = p.get("place") or {}
            if pl.get("on") == src:
                pl["on"] = pn
            if pl.get("layer_of") == src:
                pl.pop("layer_of", None)
                pl.pop("held", None)
        d["pieces"].remove(sp)
    if len(made) > 1:
        notes.insert(0, f"The cut went right through: '{pn}' is now {len(made)} pieces ({', '.join(made)})")
    return made, notes


# ---------------------------------------------------------- split with a shape (2026-11-25) --
def _place_center_cm(pc):
    """The point of a piece that sits at its spot on the body (freeform._piece_place), in cm."""
    P = np.vstack([edge_pts(pc, i, 24) for i in range(len(pc["edges"]))])
    lo, hi = P.min(0), P.max(0)
    cx, cy = 0.5 * (lo + hi)
    at = (pc.get("place") or {}).get("at", "center")
    return {"top": [cx, hi[1]], "bottom": [cx, lo[1]], "left": [lo[0], cy], "right": [hi[0], cy]}.get(at, [cx, cy])


def _fragments(pieces, P):
    """The edges of `pieces` lying along polyline P: [(piece, edge, s0, s1)], s along P from 0 to 1."""
    from shapely.geometry import LineString, Point
    L = LineString(P)
    tot = L.length or 1.0
    out = []
    for q in pieces:
        for i, e in enumerate(q["edges"]):
            Q = edge_pts(q, i, 24)
            m = Q[len(Q) // 2] if len(Q) > 2 else 0.5 * (Q[0] + Q[-1])
            if L.distance(Point(m)) > 1e-3 or L.distance(Point(Q[0])) > 1e-3 or L.distance(Point(Q[-1])) > 1e-3:
                continue
            a, b = L.project(Point(Q[0])) / tot, L.project(Point(Q[-1])) / tot
            out.append((q["name"], e["name"], min(a, b), max(a, b)))
    return sorted(out, key=lambda f: f[2])


SPLIT_SNAP = 0.015          # cuts this close together (share of the seam) are one cut


def _resew(d, rec, frags, notes):
    """Sew a seam again whose edges were cut into parts: part to part along it (ends matched by height on the
    pattern, as a side seam goes top to top), cutting an unsplit side where its partner was cut."""
    sa, sb = rec["seam"]["a"], rec["seam"]["b"]
    fa = frags.get(sa) or [tuple(sa.split(".", 1)) + (0.0, 1.0)]
    fb = frags.get(sb) or [tuple(sb.split(".", 1)) + (0.0, 1.0)]
    rev = rec["seam"].get("reverse")
    if isinstance(rev, bool):
        flip = rev
    else:
        Pa, Pb = rec["pts"][sa], rec["pts"][sb]
        dya, dyb = Pa[-1, 1] - Pa[0, 1], Pb[-1, 1] - Pb[0, 1]
        if abs(dya) > 1 and abs(dyb) > 1:
            flip = (dya > 0) != (dyb > 0)
        else:   # across the body (a waist seam): the parts whose lengths match best
            la = [f[3] - f[2] for f in fa]
            lb = [f[3] - f[2] for f in fb]
            if len(la) == len(lb):
                flip = sum(abs(x - y) for x, y in zip(la, lb[::-1])) < sum(abs(x - y) for x, y in zip(la, lb))
            else:
                flip = True
    # every cut, in a's terms
    def cuts(fr, flipped):
        c = [f[3] for f in fr[:-1]]
        return [1 - x for x in c] if flipped else c
    ca, cb = cuts(fa, False), cuts(fb, flip)
    allc = sorted(ca + cb)
    merged = []
    for x in allc:
        if not merged or x - merged[-1] > SPLIT_SNAP:
            merged.append(x)

    def refine(fr, mine, flipped):
        """Split this side's parts at the cuts it doesn't have yet."""
        out = []
        for pn, en, s0, s1 in fr:
            inner = [c for c in merged if s0 + SPLIT_SNAP < (1 - c if flipped else c) < s1 - SPLIT_SNAP]
            inner = sorted((1 - c if flipped else c) for c in inner)
            if not inner:
                out.append((pn, en, s0, s1))
                continue
            pc = piece(d, pn)
            Lf = plen(edge_pts(pc, eidx(pc, en)))
            # the part runs the way its edge did (shape_with keeps each outline's direction)
            names = split_edge_at(d, pn, en, [(c - s0) / (s1 - s0) * Lf for c in inner])
            bounds = [s0] + inner + [s1]
            out += [(pn, nm, bounds[k], bounds[k + 1]) for k, nm in enumerate(names)]
        return out
    fa = refine(fa, ca, False)
    fb = refine(fb, cb, flip)
    if len(fa) != len(fb):
        notes.append(f"{sa} and {sb} were cut in different places: sew their parts in Sew")
        return
    pairs = zip(fa, fb[::-1] if flip else fb)
    base = {k: v for k, v in rec["seam"].items() if k not in ("a", "b", "closure")}
    for x, y in pairs:
        d["seams"].append({**base, "a": f"{x[0]}.{x[1]}", "b": f"{y[0]}.{y[1]}"})
    if rec["seam"].get("closure"):
        notes.append(f"The {rec['seam']['closure'].get('type', 'closure')} on {sa} was cut across: set it again on the part it goes on")


def split_with(d, jobs, fabric=None):
    """Split every piece in jobs [{piece, tools}] by a shape, keeping every part: the parts outside it and the
    parts inside it, sewn back together along the shape's line. Seams the cut went across are sewn again part
    to part. fabric: for the parts inside the shape (a contrast midsection). Returns (inside parts, all parts
    made, notes for the user). Parts stay where their piece was on the body (place center_cm)."""
    from shapely.geometry import Point
    from shapely.geometry import Polygon as SPoly
    jobs = [j for j in jobs if j.get("tools")]
    if not jobs:
        raise ValueError("The shape doesn't overlap any piece: drag it across the pieces to split")
    names = [j["piece"] for j in jobs]
    # the seams of every piece being split, set aside with their edges' shapes; sewn again at the end
    recs, pts_of = [], {}
    for s in list(d["seams"]):
        refs = [s["a"], s["b"]]
        if any(r.split(".", 1)[0] in names for r in refs):
            pts = {}
            for r in refs:
                pn, en = r.split(".", 1)
                pc = piece(d, pn)
                pts[r] = edge_pts(pc, eidx(pc, en), 48)
            recs.append({"seam": copy.deepcopy(s), "pts": pts})
            d["seams"].remove(s)
    edge_shapes = {}                  # "piece.edge" before the split -> its polyline
    for pn in names:
        pc = piece(d, pn)
        for i, e in enumerate(pc["edges"]):
            edge_shapes[f"{pn}.{e['name']}"] = edge_pts(pc, i, 48)
    inside_all, made_all, notes, frags, cutlines = [], [], [], {}, []
    for job in jobs:
        pn = job["piece"]
        pc = piece(d, pn)
        pl = pc.setdefault("place", {})
        if not (pl.get("template") or pl.get("glove") or pl.get("on") or pl.get("loop") or pl.get("arm")) and pl.get("center_cm") is None:
            pl["center_cm"] = [round(float(v), 4) for v in _place_center_cm(pc)]     # the parts stay where the piece was
            # and wrap round the body over the whole piece's height (the body's outline there), not each part's own
            c = np.asarray(pl["center_cm"], float)
            th = np.radians(float(pl.get("rotate", 0.0)))
            P = np.vstack([edge_pts(pc, i, 24) for i in range(len(pc["edges"]))]) - c
            qy = P[:, 0] * np.sin(th) + P[:, 1] * np.cos(th)
            pl["span_cm"] = [round(float(qy.min()), 4), round(float(qy.max()), 4)]
        orig = copy.deepcopy(pc)
        clone = copy.deepcopy(pc)
        clone["name"] = unique(f"{pn}_mid", [p["name"] for p in d["pieces"]])
        d["pieces"].insert(d["pieces"].index(pc) + 1, clone)
        try:
            inside, n_in = shape_with(d, clone["name"], job["tools"], "keep")
        except ValueError as e:
            d["pieces"].remove(clone)
            if "doesn't overlap" in str(e) or "hardly overlap" in str(e):
                continue
            raise
        try:
            outside, n_out = shape_with(d, pn, job["tools"], "cut")
        except ValueError as e:
            if "covers the whole piece" in str(e):        # all of it is inside: it just gets the fabric
                for nm in inside:
                    d["pieces"].remove(piece(d, nm))
                d["pieces"][d["pieces"].index(pc)] = orig
                if fabric:
                    orig["fabric"] = fabric
                inside_all.append(pn)
                made_all.append(pn)
                continue
            raise
        notes += [x for x in n_in + n_out if not any(w in x for w in ("was sewn", "cut away", "went right through"))]
        parts = [piece(d, nm) for nm in outside + inside]
        for nm in inside:
            if fabric:
                piece(d, nm)["fabric"] = fabric
        # which part each old edge went to (whole or in parts)
        for i, e in enumerate(orig["edges"]):
            ref = f"{pn}.{e['name']}"
            fr = _fragments(parts, edge_shapes[ref])
            if fr:
                frags[ref] = fr
        # the shape's line: each outside part's new edge is sewn to the inside part's matching one
        for o in outside:
            for e in [x for x in piece(d, o)["edges"] if x["name"].startswith("cut")]:
                cutlines.append((o, e["name"], [nm for nm in inside]))
        # pockets on the piece go with the part they sit on
        polys = {q["name"]: SPoly(np.vstack([edge_pts(q, i, 24) for i in range(len(q["edges"]))])) for q in parts}
        for p in d["pieces"]:
            ppl = p.get("place") or {}
            if ppl.get("on") in [x["name"] for x in parts] or ppl.get("on") == pn:
                P = np.vstack([edge_pts(p, i, 12) for i in range(len(p["edges"]))])
                c = 0.5 * (P.min(0) + P.max(0)) + np.asarray(ppl.get("pos") or [0, 0], float)
                hit = next((nm for nm, poly in polys.items() if poly.buffer(0.5).contains(Point(c))), None)
                if hit and hit != ppl.get("on"):
                    ppl["on"] = hit
        inside_all += inside
        made_all += outside + inside
    if not made_all:
        for r in recs:
            d["seams"].append(r["seam"])
        raise ValueError("The shape doesn't overlap any piece: drag it across the pieces to split")
    # sew along the shape's line
    for o, en, ins in cutlines:
        po = piece(d, o)
        Q = edge_pts(po, eidx(po, en), 24)
        best = None
        for nm in ins:
            q = piece(d, nm)
            for i, e in enumerate(q["edges"]):
                if not e["name"].startswith("trim"):
                    continue
                R = edge_pts(q, i, 24)
                dd = min(np.linalg.norm(R[0] - Q[-1]) + np.linalg.norm(R[-1] - Q[0]), np.linalg.norm(R[0] - Q[0]) + np.linalg.norm(R[-1] - Q[-1]))
                if best is None or dd < best[0]:
                    best = (dd, nm, e["name"])
        if best and best[0] < 0.5 and not any(f"{best[1]}.{best[2]}" in (s["a"], s["b"]) for s in d["seams"]):
            d["seams"].append({"a": f"{o}.{en}", "b": f"{best[1]}.{best[2]}", "ease": 0})
        else:
            notes.append(f"{o}.{en} (along the shape) has no matching edge: sew it in Sew")
    # the old seams, part to part
    for r in recs:
        _resew(d, r, frags, notes)
    return inside_all, made_all, notes


def join_along_seam(d, ref_a, ref_b):
    """Two pieces sewn together become one: B is laid flat against A along their
    seam (they have to be the same length and shape there), the seam disappears,
    and B's other edges, seams and pockets come over to A. Returns a note."""
    from shapely.geometry import LineString
    pa, ea = ref_a.split(".", 1)
    pb, eb = ref_b.split(".", 1)
    if pa == pb:
        raise ValueError("Both edges are on the same piece")
    s, other = seam_of(d, ref_a)
    if s is None or s[other] != ref_b:
        raise ValueError(f"{ref_a} isn't sewn to {ref_b}")
    if float(s.get("ease") or 0) > 0:
        raise ValueError("That seam is gathered, so the two pieces can't lie flat as one: take the gathers out first")
    A, B = piece(d, pa), piece(d, pb)
    Ap, Bp = _ccw(outline(A)), _ccw(outline(B))
    ia = [e["name"] for e, _ in Ap].index(ea)
    ib = [e["name"] for e, _ in Bp].index(eb)
    PA, PB = Ap[ia][1], Bp[ib][1]
    la, lb = plen(PA), plen(PB)
    if abs(la - lb) > max(0.3, 0.01 * max(la, lb)):
        raise ValueError(f"The edges are {la:.1f} and {lb:.1f} cm long: make them match first (Seams: Make them match)")
    a0, a1, b0, b1 = PA[0], PA[-1], PB[0], PB[-1]
    va, vb = a0 - a1, b1 - b0                       # B's edge, turned round, lies along A's
    ang = np.arctan2(va[1], va[0]) - np.arctan2(vb[1], vb[0])
    Rm = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]])
    t = (a0 + a1) / 2 - Rm @ ((b0 + b1) / 2)

    def M(P):
        return np.asarray(P, float) @ Rm.T + t
    dev = LineString(PA).hausdorff_distance(LineString(M(PB)))
    if dev > 0.5:
        raise ValueError(f"The two edges are shaped differently (up to {dev:.1f} cm apart), so the pieces can't lie "
                         "flat as one: make the curves match first")
    n, m = len(Ap), len(Bp)
    partsA = [Ap[(ia + 1 + k) % n] for k in range(n - 1)]
    taken = [e["name"] for e, _ in partsA]
    renamed, partsB = {}, []
    for k in range(m - 1):
        e, P = Bp[(ib + 1 + k) % m]
        nm = e["name"] if e["name"] not in taken else unique(f"{pb}_{e['name']}", taken)
        taken.append(nm)
        renamed[e["name"]] = nm
        partsB.append(({**_bare(e), "name": nm}, M(P)))
    partsB[0][1][0] = a0                            # close the joins exactly
    partsB[-1][1][-1] = a1
    _polygon(partsA + partsB, f"'{pa}' joined with '{pb}' would overlap itself")
    set_outline(A, partsA + partsB)
    d["seams"].remove(s)
    for x in d["seams"]:
        for k in ("a", "b"):
            p_, e_ = x[k].split(".", 1)
            if p_ == pb:
                x[k] = f"{pa}.{renamed[e_]}"
    for p in d["pieces"]:
        pl = p.get("place") or {}
        if pl.get("loop"):
            pl["loop"] = [f"{pa}.{renamed[r.split('.', 1)[1]]}" if r.split(".", 1)[0] == pb else r for r in pl["loop"]]
        if pl.get("on") == pb:                       # pockets come along
            pl["on"] = pa
            pl["pos"] = (Rm @ np.asarray(pl.get("pos") or [0, 0], float) + t).round(3).tolist()
            pl["rotate"] = float(pl.get("rotate", 0)) + float(np.degrees(ang))
        if pl.get("layer_of") == pb:
            pl.pop("layer_of", None)
            pl.pop("held", None)
    d["pieces"].remove(B)
    note = f"'{pb}' is part of '{pa}' now: the {ref_a} ↔ {ref_b} seam is gone"
    if (B.get("fabric") or None) != (A.get("fabric") or None):
        note += f" ('{pb}' was in a different fabric: the joined piece uses the fabric of '{pa}')"
    return note


# --------------------------------------------------- copy onto a layer --
def layer_copy(d, names, fabric=None):
    """Copy pieces onto the layer over them (an overlay: tulle over a skirt, a
    sheer over a bodice). The copies are sewn to each other like the originals;
    an edge the original has sewn to anything else (a waistband) or gathered
    with elastic can't be sewn twice, so the copy is held to the original there
    instead (caught in the same seam). Returns the copies' names."""
    group = list(dict.fromkeys(names))
    taken = [p["name"] for p in d["pieces"]]
    out = {}
    for n in group:
        pc = piece(d, n)
        pl = pc.get("place") or {}
        lv = int(pl.get("layer", 0))
        if lv >= 2:
            raise ValueError(f"'{n}' is already on the outermost layer")
        nm = unique(f"{n}_over", taken)
        taken.append(nm)
        c = copy.deepcopy(pc)
        c["name"] = nm
        c.pop("lining", None)
        c["place"] = {**copy.deepcopy(pl), "layer": lv + 1, "layer_of": n, "held": []}
        if fabric:
            c["fabric"] = fabric
        out[n] = c
    for s in list(d["seams"]):
        pa, ea = s["a"].split(".", 1)
        pb, eb = s["b"].split(".", 1)
        if pa in out and pb in out:
            d["seams"].append({**copy.deepcopy(s), "a": f"{out[pa]['name']}.{ea}", "b": f"{out[pb]['name']}.{eb}"})
        elif pa in out:
            out[pa]["place"]["held"].append(ea)
        elif pb in out:
            out[pb]["place"]["held"].append(eb)
    for c in out.values():
        for e in c["edges"]:
            if e.get("elastic") and e["name"] not in c["place"]["held"]:
                c["place"]["held"].append(e["name"])
    for n in group:
        d["pieces"].insert(d["pieces"].index(piece(d, n)) + 1, out[n])
    return [out[n]["name"] for n in group]


# ------------------------------------------------------------ sleeves (2026-11-26) --
SLEEVE_LENGTHS = {"short": None, "elbow": 0.55, "three_quarter": 0.78, "long": 1.0}   # of the arm's length (shoulder to wrist)
SLEEVE_FIT = {"fitted": 4.0, "regular": 8.0, "loose": 13.0}       # cm round the upper arm
SLEEVE_CAP = {"smooth": 0.03, "puff": 0.25}                       # the cap longer than the armhole: eased / gathered in
SLEEVE_SHORT_UNDERARM = 12.0                                      # cm under the arm for a short sleeve (the tee's)


def _cap_halves(W, vb, Lf, Lb, start_dir):
    """The sleeve cap as two halves sharing its height: the front half (underarm (W, vb) -> crown) Lf long, the back
    half (crown -> underarm (-W, vb)) Lb long. A front armhole is usually shorter than the back one, so the crown
    sits off the middle (towards the front) rather than the two halves being made equal (that gathers one seam and
    stretches the other). Bisection on the cap height (for the halves' total) and the crown's offset (their split)."""
    from .garments import polyline_length, sleeve_cap

    def halves(c, ch):
        f = sleeve_cap(W - c, vb, ch, 200, start_dir); f[:, 0] += c
        b = sleeve_cap(W + c, vb, ch, 200, start_dir)[::-1].copy(); b[:, 0] = c - b[:, 0]
        return f, b

    def height(c):
        lo, hi = 0.005, 0.4
        for _ in range(40):
            mid = 0.5 * (lo + hi); f, b = halves(c, mid)
            lo, hi = (mid, hi) if polyline_length(f) + polyline_length(b) < Lf + Lb else (lo, mid)
        return 0.5 * (lo + hi)

    lo, hi = -0.6 * W, 0.6 * W              # c > 0: the front half narrower (shorter)
    for _ in range(30):
        c = 0.5 * (lo + hi); f, b = halves(c, height(c))
        lo, hi = (c, hi) if polyline_length(f) / max(polyline_length(b), 1e-9) > Lf / Lb else (lo, c)
    c = 0.5 * (lo + hi)
    return halves(c, height(c))


def add_sleeve(d, bm, sides, length="short", fit="regular", cap="smooth"):
    """A set-in sleeve for each armhole in `sides` [(arm side +1/-1, front armhole ref, back armhole ref)], drafted to
    fit them: each half of the cap is as long as its armhole edge plus the cap ease (its height solved for that, as the
    tee's: garments.solve_cap_height), the width from the upper arm (bm: blocks.body_measures, cm) plus the fit's
    ease, the length from the arm, a long sleeve tapering to the wrist. Sewn to both armhole edges and closed under
    the arm. Each side may carry (.., front reversed, back reversed): the armhole edges' direction against the cap's
    (the front half runs underarm to crown, the back half crown to underarm). Returns (the sleeves' names, notes)."""
    from .garments import bezier, line, polyline_length, sleeve_cap, solve_cap_height
    if length not in SLEEVE_LENGTHS or fit not in SLEEVE_FIT or cap not in SLEEVE_CAP:
        raise ValueError("Sleeve: length short / elbow / three_quarter / long, fit fitted / regular / loose, cap smooth / puff")
    made, notes = [], []
    taken = [p["name"] for p in d["pieces"]]
    right = max((float(np.max(edge_pts(p, i)[:, 0])) + p.get("at", [0, 0])[0]
                 for p in d["pieces"] for i in range(len(p["edges"]))), default=0.0)
    for side, fref, bref, *rev in sides:
        frev, brev = (list(rev) + [False, False])[:2]
        for ref in (fref, bref):
            s, _ = seam_of(d, ref)
            if s is not None:
                other = s["b"] if s["a"] == ref else s["a"]
                raise ValueError(f"{ref} is already sewn to {other}: unpick it first (Seams), then add the sleeve")
        Lf, Lb = plen(epts(d, fref)) / 100, plen(epts(d, bref)) / 100          # m
        e = SLEEVE_CAP[cap]
        W = (float(bm["upper_arm"]) + SLEEVE_FIT[fit]) / 200                   # half width, m
        AL = float(bm["arm_length"]) / 100
        frac = SLEEVE_LENGTHS[length]
        ch = solve_cap_height(W, 0.0, 0.5 * (Lf + Lb) * (1 + e))               # cap height for the mean half
        vb = SLEEVE_SHORT_UNDERARM / 100 if frac is None else max(frac * AL + 0.02 - ch, 0.06)
        if frac is not None and frac >= 0.75:      # tapered to the wrist (with the same ease, at least 3/4 of the top)
            Wh = max((float(bm["wrist"]) + SLEEVE_FIT[fit] + 4.0) / 200, 0.0)
            Wh = W - (W - Wh) * min(1.0, (frac * AL) / max(AL, 1e-6))
            Wh = min(W, max(Wh, 0.6 * W))
        else:
            Wh = W
        ua = np.array([W - Wh, vb]); ua /= np.linalg.norm(ua)
        cap_dir = (-ua[1], ua[0])
        cap_r, cap_l = _cap_halves(W, vb, Lf * (1 + e), Lb * (1 + e), cap_dir)
        if abs(Wh - W) > 1e-9:
            hem = bezier((-Wh, 0.0), (-Wh + ua[1] * 0.3 * Wh, ua[0] * 0.3 * Wh), (Wh - ua[1] * 0.3 * Wh, ua[0] * 0.3 * Wh), (Wh, 0.0), 48)
        else:
            hem = line((-Wh, 0.0), (Wh, 0.0))
        hf, hb = polyline_length(cap_r), polyline_length(cap_l)
        nm = unique("sleeve_r" if side > 0 else "sleeve_l", taken)
        taken.append(nm)
        c = 100.0
        pc = {"name": nm, "at": [right + 15 + W * c, 0.0], "shape": {"type": "custom"}, "role": "sleeve",
              "place": {"arm": int(side), "top_cm": round(float(max(cap_r[:, 1].max(), cap_l[:, 1].max())) * c, 3), "wrist": bool(frac is not None and frac >= 0.75),
                        "offset_cm": 0.5}}
        set_outline(pc, [({"name": "hem", "elastic": False}, np.asarray(hem) * c),
                         ({"name": "underarm_r", "elastic": False}, np.array([[Wh, 0.0], [W, vb]]) * c),
                         ({"name": "cap_r", "elastic": False}, cap_r * c),
                         ({"name": "cap_l", "elastic": False}, cap_l * c),
                         ({"name": "underarm_l", "elastic": False}, np.array([[-W, vb], [-Wh, 0.0]]) * c)])
        right += 2 * W * c + 10
        d["pieces"].append(pc)
        # the cap's +u half faces the front (arm_wrap): sewn to the front armhole; the easing as the seam's ease
        d["seams"] += [{"a": f"{nm}.cap_r", "b": fref, "ease": round(hf / Lf - 1, 4), "reverse": bool(frev)},
                       {"a": f"{nm}.cap_l", "b": bref, "ease": round(hb / Lb - 1, 4), "reverse": bool(brev)},
                       {"a": f"{nm}.underarm_r", "b": f"{nm}.underarm_l", "ease": 0, "reverse": True}]
        made.append(nm)
        if cap == "puff":
            notes.append(f"{nm}: the cap is {round(e * 100)}% longer than the armhole, gathered in")
    return made, notes
