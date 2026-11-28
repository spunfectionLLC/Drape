"""Closures: buttons, snaps, zippers, hook & loop tape.

A closure lives on a seam of the design: {"a", "b", "closure": {"type",
"count", "size_mm", "open"}}. In the simulation it is a seam (done up) except
the top `open` fraction, which is left apart (unbuttoned / unzipped). On the
cut pieces it adds what the real thing needs: a button stand and a grown-on
facing beyond the centre line, buttonhole and button marks, a fold line, the
zipper stop.

Side "a" of the seam overlaps (buttonholes); side "b" is the underlap (buttons).
"""
from __future__ import annotations

import numpy as np

FACING = 0.04          # grown-on facing beyond the stand (m)
KINDS = {"buttons": "Buttons", "snaps": "Snaps", "zipper": "Zipper", "hook_loop": "Hook & loop tape"}


def _cum(P):
    return np.r_[0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]


def _at(P, s):
    c = _cum(P)
    return np.array([np.interp(s, c, P[:, 0]), np.interp(s, c, P[:, 1])])


def _normals(P):
    """Outward normal at every point of an edge of a CCW outline."""
    d = np.gradient(P, axis=0)
    d /= np.linalg.norm(d, axis=1, keepdims=True) + 1e-12
    return np.stack([d[:, 1], -d[:, 0]], 1)


def _offset(P, w):
    return P + _normals(P) * w


def stand_width(cl) -> float:
    """How far past the centre line the closure needs fabric (m), facing excluded."""
    t, s = cl["type"], float(cl.get("size_mm") or 0) / 1000
    if t == "buttons":
        return max(s, 0.015)
    if t == "snaps":
        return max(s, 0.015)
    if t == "hook_loop":
        return s + 0.005
    return 0.0


def positions(L, cl):
    """Arc lengths from the top (m) of the buttons/snaps along an edge L long."""
    n = max(1, int(cl.get("count") or 1))
    s = float(cl.get("size_mm") or 15) / 1000
    top = 0.01 + s
    bot = max(0.02, min(0.12 * L, 0.12))
    if n == 1 or L - top - bot < 0.02:
        return np.array([min(top, L / 2)])
    return np.linspace(top, L - bot, n)


def _top_first(P):
    return P[0, 1] >= P[-1, 1]


def _num(v, lo, hi, default):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return min(hi, max(lo, x)) if np.isfinite(x) else default


def sane(cl: dict) -> dict:
    """A closure's numbers within what can be sewn (a project file, or a number typed in the seam list, may hold
    a million buttons or a negative size): 1-200 buttons or snaps, sizes up to 100 mm, open 0-1."""
    out = dict(cl)
    out["count"] = int(_num(cl.get("count") or 1, 1, 200, 1))
    if cl.get("size_mm") not in (None, ""):
        out["size_mm"] = _num(cl.get("size_mm"), 0, 100, 0)
    out["open"] = _num(cl.get("open") or 0, 0, 1, 0)
    return out


def layout(panels: dict, design_seams: list):
    """Set panel.extend and panel.marks for every closure. panels: name -> Panel
    (edges in m). Returns a list of closure summaries."""
    out = []
    for p in panels.values():
        p.extend, p.marks = {}, []
    for sd in design_seams:
        cl = sd.get("closure")
        if not cl:
            continue
        cl = sane(cl)
        pa, ea = sd["a"].split(".", 1)
        pb, eb = sd["b"].split(".", 1)
        if pa not in panels or pb not in panels:
            continue
        A, B = panels[pa].edge(ea), panels[pb].edge(eb)
        t = cl["type"]
        La = float(_cum(A)[-1])
        info = {"seam": [sd["a"], sd["b"]], "type": t, "label": KINDS.get(t, t), "count": int(cl.get("count") or 1),
                "size_mm": float(cl.get("size_mm") or 0), "length_cm": round(La * 100, 1),
                "open": float(cl.get("open") or 0)}
        if t == "zipper":
            for P, pn, en in ((A, pa, ea), (B, pb, eb)):
                q = P[-1] if _top_first(P) else P[0]
                n = _normals(P)[-1 if _top_first(P) else 0]
                panels[pn].marks.append({"kind": "zip_stop", "pts": np.stack([q, q + n * 0.012])})
            info["zip_cm"] = int(np.ceil(La * 100 / 2.5) * 2.5)       # zippers come in 2.5 cm steps
            out.append(info)
            continue
        st = stand_width(cl)
        size = float(cl.get("size_mm") or 15) / 1000
        pos = positions(La, cl)
        info["positions_cm"] = [round(float(x) * 100, 1) for x in pos]
        for side, (P, pn, en) in enumerate(((A, pa, ea), (B, pb, eb))):
            panels[pn].extend[en] = st + FACING
            panels[pn].marks.append({"kind": "fold", "pts": _offset(P, st)})
            L = float(_cum(P)[-1])
            tf = _top_first(P)
            N = _normals(P)
            c = _cum(P)
            for s in pos:
                s2 = s if tf else L - s
                q = _at(P, s2)
                k = min(int(np.searchsorted(c, s2)), len(P) - 1)
                n = N[k]
                if t == "buttons" and side == 0:      # horizontal buttonhole, 3 mm past the centre line
                    panels[pn].marks.append({"kind": "buttonhole",
                                             "pts": np.stack([q + n * 0.003, q - n * size])})
                elif t == "buttons":
                    a = np.linspace(0, 2 * np.pi, 13)
                    r = 0.003
                    panels[pn].marks.append({"kind": "button", "pts": q + r * np.stack([np.cos(a), np.sin(a)], 1)})
                elif t == "snaps":
                    a = np.linspace(0, 2 * np.pi, 13)
                    r = size / 2
                    ctr = q + n * (st / 2)
                    panels[pn].marks.append({"kind": "snap", "pts": ctr + r * np.stack([np.cos(a), np.sin(a)], 1)})
            if t == "hook_loop":
                w = size
                inner, outer = _offset(P, 0.0025), _offset(P, 0.0025 + w)
                panels[pn].marks.append({"kind": "tape", "pts": np.vstack([inner, outer[::-1], inner[:1]])})
        out.append(info)
    return out


def open_pairs(g, seam, cl):
    """Seam vertex pairs to leave apart: the top `open` fraction of the closure."""
    f = float(cl.get("open") or 0)
    if f <= 0:
        return set()
    ia = g.meta["edge_index"][(seam.panel_a, seam.edge_a)]
    ib = g.meta["edge_index"][(seam.panel_b, seam.edge_b)]
    if seam.reverse:
        ib = ib[::-1]
    P = g.uv[ia]
    c = _cum(P)
    L = c[-1]
    from_top = c if _top_first(P) else L - c
    sel = from_top <= f * L + 1e-6
    if f >= 0.999:
        sel[:] = True
    return {(int(a), int(b)) for a, b in zip(ia[sel], ib[sel])} | {(int(b), int(a)) for a, b in zip(ia[sel], ib[sel])}


def trims(g):
    """What to draw on the cloth in 3D (pre-weld vertex ids): buttons/snaps
    on the underlap, zipper teeth along both edges and the pull."""
    out = []
    for cl, seam in g.meta.get("closure_seams", []):
        ia = g.meta["edge_index"][(seam.panel_a, seam.edge_a)]
        ib = g.meta["edge_index"][(seam.panel_b, seam.edge_b)]
        if seam.reverse:
            ib = ib[::-1]
        Pa = g.uv[ia]
        if not _top_first(Pa):
            ia, ib = ia[::-1], ib[::-1]
        Pa = g.uv[ia]
        c = _cum(Pa)
        if cl["type"] == "zipper":
            k = int(np.searchsorted(c, float(cl.get("open") or 0) * c[-1]))
            out.append({"type": "zip", "a": ia.tolist(), "b": ib.tolist(), "pull": min(k, len(ia) - 1)})
        elif cl["type"] in ("buttons", "snaps"):
            r = float(cl.get("size_mm") or 15) / 2000
            for s in positions(c[-1], cl):
                k = int(np.argmin(np.abs(c - s)))
                out.append({"type": "button" if cl["type"] == "buttons" else "snap", "v": int(ib[k]), "r": r})
        elif cl["type"] == "hook_loop":
            out.append({"type": "tape", "a": ia.tolist(), "b": ib.tolist(), "pull": -1})
    return out


# ------------------------------------------------------- cut outlines --
def _line_x(p0, d0, p1, d1):
    """Intersection of two lines p0 + t d0 and p1 + s d1 (None if parallel)."""
    den = d0[0] * d1[1] - d0[1] * d1[0]
    if abs(den) < 1e-9:
        return None
    t = ((p1[0] - p0[0]) * d1[1] - (p1[1] - p0[1]) * d1[0]) / den
    return p0 + t * d0


def _per_edge_outline(edges, sas):
    """Offset every edge of a CCW outline by its own allowance and join the
    offsets at their intersections (mitred corners), cm."""
    from shapely.geometry import Polygon
    offs = []
    for E, a in zip(edges, sas):
        if len(E) == 2:
            E = np.stack([np.linspace(E[0, 0], E[1, 0], 4), np.linspace(E[0, 1], E[1, 1], 4)], 1)
        offs.append(_offset(E, a) if a > 0 else E.copy())
    ring = []
    n = len(offs)
    for i in range(n):
        A, B = offs[i], offs[(i + 1) % n]
        ring.extend(A[1:-1] if i else A[:-1])
        dA = A[-1] - A[-2]; dB = B[1] - B[0]
        dA /= np.linalg.norm(dA) + 1e-12; dB /= np.linalg.norm(dB) + 1e-12
        q = _line_x(A[-1], dA, B[0], dB)
        lim = 3 * max(sas[i], sas[(i + 1) % n], 0.5)
        if q is not None and np.linalg.norm(q - A[-1]) < lim and np.linalg.norm(q - B[0]) < lim:
            ring.append(q)
        else:                       # nearly straight, or a sharp point: bevel
            ring.append(A[-1]); ring.append(B[0])
    poly = Polygon(np.asarray(ring)).buffer(0)
    if poly.geom_type != "Polygon":
        poly = max(poly.geoms, key=lambda q: q.area)
    return poly


def cut_polygon(panel, sa_cm):
    """The cut line of a piece (shapely, cm): stitch outline, plus any closure
    extension, plus the seam allowance (per edge where the piece sets one:
    panel.sa_edges = {edge: cm}, e.g. 2.5 cm for a hem, 0.6 for a neckline)."""
    from shapely.geometry import Polygon
    stitch = np.concatenate([e[:-1] for _, e in panel.edges]) * 100
    poly = Polygon(stitch).buffer(0)
    for en, ext in (getattr(panel, "extend", None) or {}).items():
        E = panel.edge(en) * 100
        if len(E) == 2:     # a straight edge: give the offset some points
            E = np.stack([np.linspace(E[0, 0], E[1, 0], 8), np.linspace(E[0, 1], E[1, 1], 8)], 1)
        Q = _offset(E, ext * 100)
        poly = poly.union(Polygon(np.vstack([E, Q[::-1]])).buffer(0))
    poly = poly.buffer(0)
    if poly.geom_type != "Polygon":
        poly = max(poly.geoms, key=lambda q: q.area)
    per = dict(getattr(panel, "sa_edges", None) or {})
    hems = getattr(panel, "hems", None) or {}
    for en in hems:            # a hemmed edge: its turn-up allowance replaces the seam allowance
        per[en] = 0.0
    if per and any(abs(float(v) - sa_cm) > 1e-6 for v in per.values()):
        sas = [float(per.get(n, sa_cm)) for n, _ in panel.edges]
        cut = _per_edge_outline([e * 100 for _, e in panel.edges], sas)
        if getattr(panel, "extend", None):       # closure stands: add them, with the default allowance
            cut = cut.union(poly.buffer(sa_cm, join_style="mitre", mitre_limit=2.5)).buffer(0)
            if cut.geom_type != "Polygon":
                cut = max(cut.geoms, key=lambda q: q.area)
    else:
        cut = poly.buffer(sa_cm, join_style="mitre", mitre_limit=2.5) if sa_cm > 0 else poly
    if hems:                   # the turn-up allowances, their corners mirrored across the fold
        from .hems import allowance_cm, hem_strip
        names = [n for n, _ in panel.edges]
        edges_cm = [e * 100 for _, e in panel.edges]
        sas = [float(per.get(n, sa_cm)) for n in names]
        for en, hm in hems.items():
            if en in names:
                cut = cut.union(hem_strip(edges_cm, names.index(en), sas, allowance_cm(hm))).buffer(0)
        if cut.geom_type != "Polygon":
            cut = max(cut.geoms, key=lambda q: q.area)
    return cut


def marks_cm(panel):
    return [{"kind": m["kind"], "pts": np.asarray(m["pts"], float) * 100} for m in (getattr(panel, "marks", None) or [])]


def notions(g):
    """Buttons, snaps, zippers, tape this garment needs."""
    out = []
    for c in g.meta.get("closures", []):
        if c["type"] == "zipper":
            out.append({"type": "zipper", "label": f"{c['zip_cm']:g} cm zipper", "qty": 1, "length_cm": c["zip_cm"]})
        elif c["type"] == "hook_loop":
            out.append({"type": "hook_loop", "label": f"{c['size_mm']:g} mm hook & loop tape, {c['length_cm']:.0f} cm",
                        "qty": 1, "length_cm": c["length_cm"]})
        else:
            out.append({"type": c["type"], "label": f"{c['count']} × {c['size_mm']:g} mm {c['type'][:-1]}{'s' if c['count'] > 1 else ''}",
                        "qty": c["count"], "size_mm": c["size_mm"]})
    return out
