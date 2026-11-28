"""Cutting layout and fabric yardage.

Pieces (with seam allowance) are placed on the fabric with the grain line
running along the length of the fabric (pattern v axis = lengthwise grain).
Pieces may be turned 180 deg (still on grain) but never sideways. Packing is
a skyline heuristic on the pieces' outlines rasterised at 5 mm, which nests
curved pieces much tighter than bounding boxes do.

    lay = layout_pieces(panels, fabric_width_cm=150, seam_allowance_cm=1.5)
    lay["length_cm"], lay["yards"], lay["placements"]
"""
from __future__ import annotations

import numpy as np
from shapely.affinity import rotate as srotate, translate as stranslate
from shapely.geometry import Polygon

YARD_CM = 91.44


def _outline(panel, sa):
    from .closures import cut_polygon
    return cut_polygon(panel, sa)


def _raster(poly, res):
    minx, miny, maxx, maxy = poly.bounds
    w, h = int(np.ceil((maxx - minx) / res)) + 1, int(np.ceil((maxy - miny) / res)) + 1
    from matplotlib.path import Path as MPath
    xs = minx + (np.arange(w) + 0.5) * res
    ys = miny + (np.arange(h) + 0.5) * res
    X, Y = np.meshgrid(xs, ys)
    path = MPath(np.asarray(poly.exterior.coords))
    inside = path.contains_points(np.stack([X.ravel(), Y.ravel()], 1), radius=res * 0.75).reshape(h, w)
    # grow by one cell so neighbours never touch
    g = inside.copy()
    g[1:] |= inside[:-1]; g[:-1] |= inside[1:]; g[:, 1:] |= inside[:, :-1]; g[:, :-1] |= inside[:, 1:]
    return g, (minx, miny)


def layout_pieces(panels, fabric_width_cm=150.0, seam_allowance_cm=1.5, res=1.0, fold=False,
                  copies=None, tries=("area", "height", "width", "perimeter")):
    """Greedy placement is order-sensitive, so several piece orders are tried
    and the shortest layout kept (each try is ~0.05 s)."""
    best = None
    for order in tries:
        lay = _layout_once(panels, fabric_width_cm, seam_allowance_cm, res, fold, copies, order)
        if best is None or lay["length_cm"] < best["length_cm"] - 1e-9:
            best = lay
    return best


def _layout_once(panels, fabric_width_cm, seam_allowance_cm, res, fold, copies, order):
    """Place every piece. fold=True: fabric folded lengthwise (half width),
    mirror pairs (e.g. sleeve_r/sleeve_l) cut as one through both layers.
    Returns dict with placements [(name, polygon cm, rotated?)], length_cm,
    yards, metres, efficiency."""
    copies = copies or {}
    W = fabric_width_cm / (2 if fold else 1)
    items = []
    names = [p.name for p in panels]
    skip = set()
    for p in panels:
        if p.name in skip:
            continue
        poly = _outline(p, seam_allowance_cm)
        n = 1
        if fold:
            # a mirror twin (name_r / name_l) is cut in the same go through two layers
            for a, b in (("_r", "_l"), ("_l", "_r")):
                if p.name.endswith(a) and p.name[: -len(a)] + b in names:
                    skip.add(p.name[: -len(a)] + b)
        for _ in range(copies.get(p.name, n)):
            items.append((p.name, poly))
    # bottom-left placement on a full occupancy grid (holes
    # left beside earlier pieces get used, unlike a skyline). All candidate
    # offsets are tested at once with an FFT convolution.
    from scipy.signal import fftconvolve
    keyf = {"area": lambda it: -it[1].area,
            "height": lambda it: -(it[1].bounds[3] - it[1].bounds[1]),
            "width": lambda it: -(it[1].bounds[2] - it[1].bounds[0]),
            "perimeter": lambda it: -it[1].length}[order]
    items.sort(key=keyf)
    cols = int(np.floor(W / res))
    rows = int(sum(it[1].bounds[3] - it[1].bounds[1] for it in items) / res) + 10
    occ = np.zeros((rows, cols), np.float32)
    placements = []
    for name, poly in items:
        if poly.bounds[2] - poly.bounds[0] > W + 1e-6:
            raise ValueError(f"piece {name} ({poly.bounds[2] - poly.bounds[0]:.0f} cm wide) "
                             f"doesn't fit a {W:.0f} cm {'folded ' if fold else ''}fabric width")
        best = None
        for rot in (0, 180):
            pp = srotate(poly, rot, origin="centroid") if rot else poly
            mask, (mx, my) = _raster(pp, res)
            h, w = mask.shape
            if w > cols:
                continue
            ov = fftconvolve(occ, mask[::-1, ::-1].astype(np.float32), mode="valid")   # (rows-h+1, cols-w+1)
            free = ov < 0.5
            if not free.any():
                continue
            r_idx, c_idx = np.nonzero(free)
            top = r_idx + h
            k = np.lexsort((c_idx, top))[0]
            cand = (top[k], r_idx[k], c_idx[k], rot, pp, mask, mx, my)
            if best is None or cand[:3] < best[:3]:
                best = cand
        if best is None:   # wider than the fabric once rasterised (rounding at the edge)
            raise ValueError(f"piece {name} doesn't fit a {W:.0f} cm fabric width")
        top, y, c0, rot, pp, mask, mx, my = best
        h, w = mask.shape
        occ[y:y + h, c0:c0 + w] = np.maximum(occ[y:y + h, c0:c0 + w], mask)
        placed = stranslate(pp, c0 * res - mx, y * res - my)
        placements.append((name, placed, rot))
    L = float(max(pl.bounds[3] for _, pl, _ in placements)) if placements else 0.0
    used = sum(pl.area for _, pl, _ in placements)
    return dict(placements=placements, length_cm=L, yards=L / YARD_CM, metres=L / 100,
                width_cm=W, fold=fold, efficiency=used / (L * W) if L else 0.0)


def buy_amount(length_cm, extra_cm=10):
    """Round up the way fabric is sold: to 1/8 yard and 10 cm, plus a margin
    for straightening the cut edge and shrinkage."""
    L = length_cm + extra_cm
    return dict(yards=np.ceil(L / YARD_CM * 8) / 8, metres=np.ceil(L / 10) / 10)


def layout_image(lay, path, title=""):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    W, L = lay["width_cm"], lay["length_cm"]
    fig, ax = plt.subplots(figsize=(min(14, 2 + L / 15), 2 + W / 15))
    ax.add_patch(plt.Rectangle((0, 0), L, W, fc="#f3efe6", ec="#999", lw=1))
    cmap = plt.get_cmap("tab10")
    for i, (name, pl, rot) in enumerate(lay["placements"]):
        xy = np.asarray(pl.exterior.coords)
        ax.fill(xy[:, 1], xy[:, 0], fc=cmap(i % 10), alpha=0.35, ec=cmap(i % 10), lw=1.5)
        c = pl.centroid
        ax.annotate(f"{name}{' (turned)' if rot else ''}", (c.y, c.x), ha="center", va="center", fontsize=8)
        # grain arrow (along the fabric length)
        ax.annotate("", (c.y + 8, c.x - 4), (c.y - 8, c.x - 4), arrowprops=dict(arrowstyle="<->", lw=0.8))
    ax.set_xlim(-5, L + 5); ax.set_ylim(-5, W + 8); ax.set_aspect("equal")
    ax.set_xlabel("fabric length (cm)"); ax.set_ylabel(("folded " if lay["fold"] else "") + "width (cm)")
    b = buy_amount(L)
    ax.set_title(title or f"{L:.0f} cm used ({lay['efficiency'] * 100:.0f}% efficient) - buy {b['yards']:.3g} yd / {b['metres']:.2g} m")
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)
