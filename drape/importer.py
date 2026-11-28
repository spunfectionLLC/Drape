"""Import sewing patterns from DXF (our own export, Seamly2D/Valentina,
Inkscape, CAD) and turn them into drape Panels and Seams.

Pipeline
  1. read closed outlines (closed polylines, or chains of LINE/ARC/SPLINE/open
     polylines joined end to end) and TEXT labels
  2. pick the stitch outlines: layer "SEW" if present, else every closed outline
     with outlines nested inside another dropped (cut line around sew line);
     optional seam-allowance inset if the file only has cut lines
  3. name each piece from the text inside it ("FRONT cut 1" -> "front")
  4. split each outline into edges at corners (turn > corner_deg), numbered
     e0, e1, ... counter-clockwise from the bottom-left corner; optional
     extra splits at fractions of an edge (e.g. a sleeve cap at its crown)
  5. place each piece around the body (front / back / arm_r / arm_l / flat)
  6. seams from a spec, or suggested automatically: edges of equal length
     (within the allowed ease) that sit close together once placed

A spec is a small JSON file, e.g.:
{
  "layer": "SEW",
  "corner_deg": 30,
  "split": {"sleeve_r.e2": [0.5], "sleeve_l.e2": [0.5]},
  "pieces": {"front": "front", "back": "back", "sleeve_r": "arm_r", "sleeve_l": "arm_l"},
  "seams": "auto"            # or a list: [{"a": "front.e1", "b": "back.e7", "reverse": true}, ...]
}
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf
import numpy as np
from ezdxf import path as dxfpath
from shapely.geometry import Point, Polygon

from .pattern import Panel, Seam, build_garment, cylinder_wrap, polyline_length, resample

UNITS_TO_M = {0: 0.001, 1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0}  # 0 = unitless: assume mm


@dataclass
class Outline:
    pts: np.ndarray        # (n,2) meters, closed implicitly
    layer: str
    name: str = ""
    edges: list = field(default_factory=list)   # [(name, (k,2) polyline)]
    offset: np.ndarray = field(default_factory=lambda: np.zeros(2))


# ------------------------------------------------------------- reading ----
def _flatten(e, tol):
    try:
        p = dxfpath.make_path(e)
    except (TypeError, ValueError):
        return None
    pts = np.array([(v.x, v.y) for v in p.flattening(distance=tol)])
    return pts if len(pts) >= 2 else None


def _chain(segments, tol):
    """Join open polylines end-to-end into closed loops."""
    segs = [s for s in segments if len(s) >= 2]
    loops = []
    while segs:
        cur = segs.pop(0)
        changed = True
        while changed:
            changed = False
            if np.linalg.norm(cur[0] - cur[-1]) < tol and len(cur) > 3:
                break
            for i, s in enumerate(segs):
                if np.linalg.norm(cur[-1] - s[0]) < tol:
                    cur = np.vstack([cur, s[1:]])
                elif np.linalg.norm(cur[-1] - s[-1]) < tol:
                    cur = np.vstack([cur, s[::-1][1:]])
                elif np.linalg.norm(cur[0] - s[-1]) < tol:
                    cur = np.vstack([s, cur[1:]])
                elif np.linalg.norm(cur[0] - s[0]) < tol:
                    cur = np.vstack([s[::-1], cur[1:]])
                else:
                    continue
                segs.pop(i)
                changed = True
                break
        if np.linalg.norm(cur[0] - cur[-1]) < tol and len(cur) > 3:
            loops.append(cur[:-1])
    return loops


def read_dxf(path, flatten_mm=0.2) -> tuple[list[Outline], list[tuple[str, np.ndarray]], float]:
    doc = ezdxf.readfile(str(path))
    scale = UNITS_TO_M.get(int(doc.header.get("$INSUNITS", 0)), 0.001)
    tol = flatten_mm / 1000 / scale
    closed, open_by_layer, texts = [], {}, []
    for e in doc.modelspace():
        t = e.dxftype()
        layer = (getattr(e.dxf, "layer", "") or "").upper()
        if layer == "SEAMNO":                      # drape's seam numbers: not piece names
            continue
        if layer == "NOTCH" and t == "CIRCLE":     # match dots: not pieces
            continue
        if t in ("TEXT", "MTEXT"):
            txt = e.dxf.text if t == "TEXT" else e.plain_text()
            ins = e.dxf.insert
            texts.append((txt, np.array([ins.x, ins.y]) * scale))
            continue
        if t in ("INSERT", "POINT", "DIMENSION", "HATCH"):
            continue
        pts = _flatten(e, tol)
        if pts is None:
            continue
        is_closed = (getattr(e, "closed", False) or getattr(e.dxf, "flags", 0) & 1
                     or t == "CIRCLE" or np.linalg.norm(pts[0] - pts[-1]) < tol)
        if is_closed:
            if np.linalg.norm(pts[0] - pts[-1]) < tol:
                pts = pts[:-1]
            closed.append(Outline(pts * scale, e.dxf.layer))
        else:
            open_by_layer.setdefault(e.dxf.layer, []).append(pts)
    for layer, segs in open_by_layer.items():
        for loop in _chain(segs, 50 * tol):
            closed.append(Outline(loop * scale, layer))
    return closed, texts, scale


# ----------------------------------------------------------- selecting ----
def select_pieces(outlines, texts, layer=None, seam_allowance=0.0, min_area_cm2=4.0):
    layers = {o.layer.upper() for o in outlines}
    if layer is None and "SEW" in layers:
        layer = "SEW"
    cand = [o for o in outlines if layer is None or o.layer.upper() == layer.upper()]
    cand = [o for o in cand if Polygon(o.pts).area * 1e4 >= min_area_cm2]
    # drop outlines that sit inside another one (keep the innermost = stitch line)
    polys = [Polygon(o.pts).buffer(0) for o in cand]
    keep = []
    for i, o in enumerate(cand):
        inner_exists = any(j != i and polys[i].contains(polys[j].representative_point()) and
                           polys[j].area < polys[i].area for j in range(len(cand)))
        if not inner_exists:
            keep.append(o)
    pieces = []
    for o in keep:
        poly = Polygon(o.pts).buffer(0)
        if seam_allowance > 0:  # file has cut lines only: inset to the stitch line
            poly = poly.buffer(-seam_allowance, join_style="mitre", mitre_limit=2.5)
        # counter-clockwise
        pts = np.asarray(poly.exterior.coords)[:-1]
        area = 0.5 * np.sum(pts[:, 0] * np.roll(pts[:, 1], -1) - np.roll(pts[:, 0], -1) * pts[:, 1])
        if area < 0:
            pts = pts[::-1]
        o.pts = pts
        inside = [t for t, p in texts if poly.buffer(0.01).contains(Point(p))]
        o.name = _piece_name(inside[0]) if inside else ""
        pieces.append(o)
    # unique names, left-to-right order for the unnamed
    pieces.sort(key=lambda o: o.pts[:, 0].min())
    seen = {}
    for i, o in enumerate(pieces):
        n = o.name or f"piece{i}"
        if n in seen:
            seen[n] += 1
            n = f"{n}_{seen[n]}"
        else:
            seen[n] = 0
        o.name = n
    return pieces


def _piece_name(text):
    first = text.strip().split()[0] if text.strip() else ""
    return re.sub(r"[^a-z0-9_]", "", first.lower())


# ------------------------------------------------------------ splitting ----
def split_edges(o: Outline, corner_deg=30.0, window_mm=4.0):
    """Split a closed outline into edges at corners; returns [(name, polyline)]."""
    per = polyline_length(np.vstack([o.pts, o.pts[:1]]))
    n = max(int(per / 0.001), 64)                     # ~1 mm sampling
    P = resample(np.vstack([o.pts, o.pts[:1]]), n)[:-1]
    w = max(1, int(window_mm / 1000 / (per / n)))
    a = P - np.roll(P, w, axis=0); b = np.roll(P, -w, axis=0) - P
    turn = np.degrees(np.arctan2(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0], (a * b).sum(1)))
    big = np.abs(turn) > corner_deg
    # one corner per run of "big" samples: the local max of |turn|
    corners = []
    i = 0
    idx = np.where(big)[0]
    if len(idx):
        runs, cur = [], [idx[0]]
        for k in idx[1:]:
            if k == cur[-1] + 1:
                cur.append(k)
            else:
                runs.append(cur); cur = [k]
        runs.append(cur)
        if len(runs) > 1 and runs[0][0] == 0 and runs[-1][-1] == n - 1:   # wraps around
            runs[0] = runs[-1] + runs[0]; runs.pop()
        corners = [r[int(np.argmax(np.abs(turn[r])))] for r in runs]
    # snap corners to the original vertices (exact corner points)
    snapped = []
    for c in corners:
        j = int(np.argmin(np.linalg.norm(o.pts - P[c], axis=1)))
        if np.linalg.norm(o.pts[j] - P[c]) < 0.003:
            snapped.append(("v", j))
        else:
            snapped.append(("p", c))
    # walk the original outline, cutting at corners
    if not corners:  # a smooth closed shape (e.g. a circle): one edge
        o.edges = [("e0", np.vstack([o.pts, o.pts[:1]]))]
        return o.edges
    # densify outline with corner points inserted
    pts = [tuple(p) for p in o.pts]
    cut_pts = [o.pts[j] if kind == "v" else P[j] for kind, j in snapped]
    ring = list(o.pts)
    for cp in cut_pts:
        if not any(np.allclose(cp, q, atol=1e-9) for q in ring):
            # insert on the nearest segment
            best, bi = 1e9, 0
            for k in range(len(ring)):
                a_, b_ = ring[k], ring[(k + 1) % len(ring)]
                t = np.clip(np.dot(cp - a_, b_ - a_) / max(np.dot(b_ - a_, b_ - a_), 1e-18), 0, 1)
                dd = np.linalg.norm(a_ + t * (b_ - a_) - cp)
                if dd < best:
                    best, bi = dd, k
            ring.insert(bi + 1, np.array(cp))
    ring = np.array(ring)
    cut_idx = sorted({int(np.argmin(np.linalg.norm(ring - cp, axis=1))) for cp in cut_pts})
    # start at the corner nearest the bottom-left of the piece
    mn = ring.min(0)
    start = min(cut_idx, key=lambda k: (np.linalg.norm(ring[k] - mn)))
    order = cut_idx[cut_idx.index(start):] + cut_idx[:cut_idx.index(start)]
    m = len(ring)
    edges = []
    for e, (k0, k1) in enumerate(zip(order, order[1:] + order[:1])):
        span = [(k0 + t) % m for t in range(((k1 - k0) % m) + 1 if k1 != k0 else m + 1)]
        edges.append((f"e{e}", _dedupe(ring[span])))
    o.edges = edges
    return edges


def split_edge_at(o: Outline, edge_name: str, fractions):
    """Split one edge at arc-length fractions: e2 -> e2a, e2b, ..."""
    new = []
    for n, pl in o.edges:
        if n != edge_name:
            new.append((n, pl)); continue
        seg = np.linalg.norm(np.diff(pl, axis=0), axis=1)
        s = np.concatenate([[0], np.cumsum(seg)])
        cuts = [0.0] + sorted(fractions) + [1.0]
        for i, (f0, f1) in enumerate(zip(cuts, cuts[1:])):
            t0, t1 = f0 * s[-1], f1 * s[-1]
            inner = pl[(s > t0) & (s < t1)]
            p0 = np.array([np.interp(t0, s, pl[:, 0]), np.interp(t0, s, pl[:, 1])])
            p1 = np.array([np.interp(t1, s, pl[:, 0]), np.interp(t1, s, pl[:, 1])])
            new.append((f"{n}{'abcdefgh'[i]}", _dedupe(np.vstack([p0, inner, p1]))))
    o.edges = new


def _dedupe(pl, eps=1e-9):
    """Drop consecutive duplicate points (zero-length steps break tangents)."""
    keep = np.r_[True, np.linalg.norm(np.diff(pl, axis=0), axis=1) > eps]
    return pl[keep]


# ------------------------------------------------------------ placement ----
def _normalize(o: Outline):
    """Pattern space: u centred on the piece, v = 0 at its lowest point."""
    mn, mx = o.pts.min(0), o.pts.max(0)
    off = np.array([(mn[0] + mx[0]) / 2, mn[1]])
    o.offset = off
    o.pts = o.pts - off
    o.edges = [(n, pl - off) for n, pl in o.edges]


def guess_placement(name: str) -> str:
    n = name.lower()
    if "sleeve" in n or "arm" in n:
        return "arm_l" if re.search(r"(_l|left|_2)$", n) else "arm_r"
    if any(w in n for w in ("skirt", "pant", "trouser", "short")):
        return "lower_back" if "back" in n else "lower_front"
    if "back" in n:
        return "back"
    if "front" in n:
        return "front"
    return "front"


def _resolve_placements(pieces, places):
    """Fill in guesses for pieces the spec doesn't place, without stacking two
    pieces in one spot: a second 'front' becomes 'back', a second 'arm_r'
    becomes 'arm_l' (bug fixed: two unlabeled pieces were both put in front)."""
    taken = list(places.values())
    other = {"front": "back", "back": "front", "arm_r": "arm_l", "arm_l": "arm_r",
             "lower_front": "lower_back", "lower_back": "lower_front"}
    for o in sorted(pieces, key=lambda q: -Polygon(q.pts).area):
        if o.name in places:
            continue
        k = guess_placement(o.name)
        if k in taken and other.get(k) not in taken:
            k = other[k]
        places[o.name] = k
        taken.append(k)


def placement_fn(kind: str, outline: Outline, body):
    from .garments import _placement_for, arm_wrap
    top = float(outline.pts[:, 1].max())
    if kind in ("front", "back"):
        hem_y, wrap = _placement_for(body, top) if body is not None else (0.92, 0.20)
        return cylinder_wrap(wrap, 0.0 if kind == "front" else np.pi, hem_y)
    if kind in ("lower_front", "lower_back"):   # skirts, trousers: top edge at the waist
        from .garments import waist_placement
        hem_y, wrap = waist_placement(body, top)
        return cylinder_wrap(wrap, 0.0 if kind == "lower_front" else np.pi, hem_y)
    if kind in ("arm_r", "arm_l"):
        if body is not None:
            sj, el, r = body.arm_axis(+1)
        else:
            sj, el, r = np.array([0.18, 1.42, 0]), np.array([0.36, 1.18, 0]), 0.045
        return arm_wrap(sj, el, max(0.075, r + 0.03), top, mirror=(kind == "arm_l"))
    if kind == "flat":
        return lambda uv: np.stack([uv[:, 0], uv[:, 1] + 1.0, np.full(len(uv), 0.4)], 1)
    raise ValueError(f"unknown placement {kind!r} (front, back, lower_front, lower_back, arm_r, arm_l, flat)")


# ---------------------------------------------------------------- seams ----
def suggest_seams(panels: list[Panel], max_ease=0.06, max_gap=0.45, length_tol_mm=2.0):
    """Suggest seams: pairs of edges with the same length (or within max_ease,
    e.g. a sleeve cap) that sit near each other once placed.

    Candidates are accepted greedily, nearest first (ranking exact length
    matches first was tested and sews front armhole to back armhole before
    the sleeve caps get a chance). A candidate is REJECTED if it makes any
    fully-sewn junction impossible (corner angles far from 360 deg, see
    seamcheck). A piece is only sewn to itself as a tube: both edges must
    border the piece's lowest edge (sleeve underarm, trouser inseam), never
    e.g. a front's two shoulders across the neckline. A piece's bottom edge
    is treated as a hem and never sewn. Review the result: it is a
    suggestion, written out so you can edit it."""
    from .seamcheck import Tolerances, check_junctions
    tol = Tolerances()
    edges = []
    for p in panels:
        names = [n for n, _ in p.edges]
        lowest = min(p.edges, key=lambda e: e[1][:, 1].mean())
        is_hem = lambda n, pl: (n == lowest[0] and np.ptp(pl[:, 1]) < 0.15 * max(np.ptp(pl[:, 0]), 1e-9))
        for i, (n, pl) in enumerate(p.edges):
            if is_hem(n, pl):
                continue
            edges.append((p, n, polyline_length(pl), p.place(resample(pl, 24)), i, len(names)))
    cands = []
    for i in range(len(edges)):
        for j in range(i + 1, len(edges)):
            pa, na, la, A, ia, ka = edges[i]
            pb, nb, lb, B, ib, kb = edges[j]
            if pa is pb:
                low = min(range(ka), key=lambda k: pa.edges[k][1][:, 1].mean())
                nb_a = {(ia - 1) % ka, (ia + 1) % ka}
                nb_b = {(ib - 1) % ka, (ib + 1) % ka}
                if (ia - ib) % ka in (1, ka - 1) or low not in (nb_a & nb_b):
                    continue  # not a tube seam
            diff = abs(la - lb)
            exact = diff <= length_tol_mm / 1000
            if not exact and diff > max_ease * min(la, lb):
                continue
            fwd = np.linalg.norm(A - B, axis=1).mean()
            rev = np.linalg.norm(A - B[::-1], axis=1).mean()
            gap, reverse = (rev, True) if rev < fwd else (fwd, False)
            if gap > max_gap:
                continue
            cands.append((gap, 0 if exact else 1, i, j, reverse))
    cands.sort()
    used, seams, rejected = set(), [], []
    for gap, cls, i, j, reverse in cands:
        if i in used or j in used:
            continue
        pa, na, la, *_ = edges[i]; pb, nb, lb, *_ = edges[j]
        if la < lb:  # A = longer side; ease = how much longer it is
            pa, na, la, pb, nb, lb = pb, nb, lb, pa, na, la
        ease = la / lb - 1
        cand = Seam(pa.name, na, pb.name, nb, reverse=reverse, ease=ease if ease > 0.005 else 0.0)
        bad = [jn for jn in check_junctions(panels, [s for s, _ in seams] + [cand], tol)
               if jn["kind"] == "inside" and jn["status"] == "RE-TRUE"]
        if bad:
            rejected.append((cand, gap, bad[0]["corners"]))
            continue
        used |= {i, j}
        seams.append((cand, gap))
    suggest_seams.last_rejected = rejected
    return seams


# ---------------------------------------------------------------- main ----
def import_pattern(dxf_path, spec: dict | str | None = None, body=None, spacing=0.015, density=0.15):
    """DXF (+ spec) -> Garment ready to simulate. Returns (garment, info)."""
    if isinstance(spec, (str, Path)):
        spec = json.loads(Path(spec).read_text(encoding="utf-8"))
    spec = spec or {}
    outlines, texts, scale = read_dxf(dxf_path)
    pieces = select_pieces(outlines, texts, spec.get("layer"), spec.get("seam_allowance_mm", 0) / 1000)
    if not pieces:
        raise ValueError(f"no closed outlines found in {dxf_path}")
    for o in pieces:
        split_edges(o, spec.get("corner_deg", 30.0))
    for key, fr in spec.get("split", {}).items():
        pn, en = key.split(".")
        o = next((q for q in pieces if q.name == pn), None)
        if o is None:
            raise ValueError(f"split: no piece {pn!r}; pieces are {[q.name for q in pieces]}")
        split_edge_at(o, en, fr)
    for o in pieces:
        _normalize(o)
    places = dict(spec.get("pieces", {}))
    _resolve_placements(pieces, places)
    panels = []
    for o in pieces:
        kind = places[o.name]
        panels.append(Panel(o.name, [(n, pl) for n, pl in o.edges], placement_fn(kind, o, body)))
    seam_spec = spec.get("seams", "auto")
    suggested = None
    if seam_spec == "auto":
        suggested = suggest_seams(panels)
        seams = [s for s, _ in suggested]
    else:
        seams = [Seam(*s["a"].split("."), *s["b"].split("."), reverse=s.get("reverse", False),
                      ease=s.get("ease", 0.0)) for s in seam_spec]
    g = build_garment(panels, seams, spacing=spacing, density=density)
    g.meta.update(torso_panels=[p.name for p in panels if places[p.name] in ("front", "back", "lower_front", "lower_back")],
                  sleeve_panels=[], imported_from=str(dxf_path))
    front = [p for p in panels if places[p.name] in ("front", "back")]
    lower = [p for p in panels if places[p.name] in ("lower_front", "lower_back")]
    if front and body is not None:
        g.meta["hem_y"] = _placement_for_meta(body, front[0])
    elif lower and body is not None:
        from .garments import waist_placement
        g.meta["hem_y"] = waist_placement(body, max(pl[:, 1].max() for _, pl in lower[0].edges))[0]
    info = {"pieces": [(o.name, places[o.name], [(n, polyline_length(pl)) for n, pl in o.edges])
                       for o in pieces], "suggested": suggested, "units_scale": scale}
    return g, info


def _placement_for_meta(body, panel):
    from .garments import _placement_for
    top = max(pl[:, 1].max() for _, pl in panel.edges)
    return _placement_for(body, top)[0]


def preview(panels_or_garment, path, seams=None, title=""):
    """Drawing of the pieces with edge names and lengths, seams colour-coded."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    g = panels_or_garment
    panels = g.meta["panels"] if hasattr(g, "meta") else g
    seams = seams if seams is not None else (g.meta.get("seam_defs") if hasattr(g, "meta") else [])
    color = {}
    cmap = plt.get_cmap("tab10")
    palette = [cmap(i) for i in range(10) if i != 7]  # no grey: grey = unsewn edge
    for i, s in enumerate(seams):
        c = palette[i % len(palette)]
        color[(s.panel_a, s.edge_a)] = (c, i)
        color[(s.panel_b, s.edge_b)] = (c, i)
    fig, axes = plt.subplots(1, len(panels), figsize=(4.2 * len(panels), 5.2))
    axes = np.atleast_1d(axes)
    for ax, p in zip(axes, panels):
        for n, pl in p.edges:
            c, si = color.get((p.name, n), ((0.55, 0.55, 0.55, 1), None))
            ax.plot(pl[:, 0] * 100, pl[:, 1] * 100, color=c, lw=3 if si is not None else 1.5)
            mid = pl[len(pl) // 2] * 100
            lbl = f"{n}\n{polyline_length(pl) * 1000:.0f}mm" + (f"\nseam {si}" if si is not None else "")
            ax.annotate(lbl, mid, fontsize=7, ha="center", va="center",
                        bbox=dict(boxstyle="round,pad=0.15", fc="white", ec=c, alpha=0.85))
            ax.plot(*(pl[0] * 100), "k.", ms=4)
        ax.set_title(p.name); ax.set_aspect("equal"); ax.set_xlabel("cm")
    fig.suptitle(title or "pattern pieces: edge names, lengths, seams (same colour/number = sewn together)")
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)
