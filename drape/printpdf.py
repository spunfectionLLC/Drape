"""Print-at-home and projector PDFs, at true 1:1 scale.

tiled_pdf:      the pattern split over Letter / A4 pages. Each page carries
                its row/column label (A1, A2, B1...), triangle marks to line
                pages up, and page 1 has a 5 cm + 2 in test square: measure it
                before printing the rest ("actual size", no "fit to page").
projector_pdf:  one large page at 1:1 with a 10 cm grid for projector
                calibration (projector sewing / cutting mats).
"""
from __future__ import annotations

import numpy as np
from shapely.geometry import Polygon

from .layout import layout_pieces

PAGES = {"letter": (8.5, 11.0), "a4": (8.27, 11.69)}
IN = 2.54


def _piece_geoms(panels, seams, sa_cm):
    """Per piece: stitch outline, cut outline, notch segments, numbered and coloured
    seam edges, match dots, grain line, label (cm)."""
    from .closures import cut_polygon, marks_cm
    from .seammarks import seam_marks
    SM = seam_marks(panels, seams)
    out = []
    for p in panels:
        stitch = np.concatenate([e[:-1] for _, e in p.edges]) * 100
        poly = Polygon(stitch).buffer(0)
        cut = cut_polygon(p, sa_cm)
        sm = SM[p.name]
        notches, seamlines, tags = [], [], []
        for en, mk in sm["edges"].items():
            for q, nrm in mk["notches"]:
                notches.append((q, q + nrm * max(sa_cm, 0.6)))           # from the stitch line out to the cut edge
            seamlines.append(dict(pts=mk["pts"], color=mk["color"]))
            tags.append(dict(at=mk["tag"], num=mk["num"], color=mk["color"], partner=mk["partner"]))
        b = poly.bounds
        cx = poly.representative_point()
        h = (b[3] - b[1]) * 0.6
        grain = ((cx.x, cx.y - h / 2), (cx.x, cx.y + h / 2))
        out.append(dict(name=p.name, stitch=stitch, cut=np.asarray(cut.exterior.coords), notches=notches,
                        seamlines=seamlines, tags=tags, dots=[dict(at=d["point"], between=d["between"]) for d in sm["dots"]],
                        grain=grain, label=(cx.x + 1.0, cx.y), marks=marks_cm(p)))
    return out


def _arrange(panels, seams, sa_cm, width_cm):
    lay = layout_pieces(panels, width_cm, sa_cm, res=1.0)
    geoms = {g["name"]: g for g in _piece_geoms(panels, seams, sa_cm)}
    placed = []
    for name, pl, rot in lay["placements"]:
        g = geoms[name]
        # move this piece's geometry the same way the layout moved its cut outline
        src = Polygon(g["cut"])
        if rot:
            c = np.array(src.centroid.coords[0])
            R = lambda P: 2 * c - np.asarray(P)
        else:
            R = lambda P: np.asarray(P)
        off = np.array(pl.bounds[:2]) - np.asarray(Polygon(R(g["cut"])).bounds[:2])
        T = lambda P: R(P) + off
        placed.append(dict(name=name, stitch=T(g["stitch"]), cut=T(g["cut"]),
                           notches=[(T(a), T(b)) for a, b in g["notches"]],
                           seamlines=[dict(sl, pts=T(sl["pts"])) for sl in g.get("seamlines", [])],
                           tags=[dict(t, at=T(t["at"])) for t in g.get("tags", [])],
                           dots=[dict(d, at=T(d["at"])) for d in g.get("dots", [])],
                           marks=[{"kind": mk["kind"], "pts": T(mk["pts"])} for mk in g.get("marks", [])],
                           grain=(T(g["grain"][0]), T(g["grain"][1])), label=T(g["label"]), rot=rot))
    return placed, lay


MARK_STYLE = {"fold": dict(color="#1f4e8c", ls=(0, (8, 3, 2, 3))), "buttonhole": dict(color="black", lw_k=2.2),
              "button": dict(color="black"), "snap": dict(color="black"), "tape": dict(color="#7a4fb0", ls=(0, (3, 2))),
              "zip_stop": dict(color="black", lw_k=1.6)}


def draw_marks(ax, marks, lw=0.8):
    """Closure marks: fold line, buttonholes, buttons/snaps, tape, zipper stop."""
    for mk in marks:
        st = MARK_STYLE.get(mk["kind"], {})
        P = np.asarray(mk["pts"])
        ax.plot(P[:, 0], P[:, 1], color=st.get("color", "black"), lw=lw * st.get("lw_k", 1.0), ls=st.get("ls", "-"))
        if mk["kind"] == "fold":
            q = P[len(P) // 2]
            ax.text(q[0], q[1], " fold", fontsize=6, color=st["color"], rotation=90, va="center")


def _draw_pieces(ax, placed, garment_name, lw=0.8):
    for g in placed:
        ax.plot(*np.vstack([g["cut"], g["cut"][:1]]).T, color="black", lw=lw * 1.4)
        ax.plot(*np.vstack([g["stitch"], g["stitch"][:1]]).T, color="#c0392b", lw=lw * 0.8, ls=(0, (4, 3)))
        for sl in g.get("seamlines", []):          # each seam in its own colour, the same on both pieces
            P = np.asarray(sl["pts"])
            ax.plot(P[:, 0], P[:, 1], color=sl["color"], lw=lw * 2.2, solid_capstyle="round")
        for a, b in g["notches"]:
            ax.plot([a[0], b[0]], [a[1], b[1]], color="black", lw=lw * 1.6)
        for t in g.get("tags", []):                # ③ = sews to the other ③
            # printed at true size: a ~8 mm disc, readable at arm's length
            ax.text(t["at"][0], t["at"][1], str(t["num"]), fontsize=17, fontweight="bold", color="white",
                    ha="center", va="center", zorder=5,
                    bbox=dict(boxstyle="circle,pad=0.3", fc=t["color"], ec="none"))
            ax.text(t["at"][0], t["at"][1] - 1.0, f"to {t['partner']}", fontsize=8, fontweight="bold", color=t["color"],
                    ha="center", va="top", zorder=5)
        for d in g.get("dots", []):                 # e.g. the top of a sleeve cap: to the shoulder seam
            ax.plot(d["at"][0], d["at"][1], "o", color="black", ms=8, zorder=6)
            ax.text(d["at"][0], d["at"][1] + 0.8, f"● match point: between {d['between'][0]} and {d['between'][1]}",
                    fontsize=7, ha="center", va="bottom", zorder=6)
        draw_marks(ax, g.get("marks", []), lw)
        (x0, y0), (x1, y1) = g["grain"]
        ax.annotate("", (x1, y1), (x0, y0), arrowprops=dict(arrowstyle="<->", lw=lw, color="#1f4e8c"))
        ax.text(g["label"][0], g["label"][1], f"{g['name'].upper()}\n{garment_name}\ncut 1\ngrain ↕",
                fontsize=9, color="#1f4e8c", va="center", rotation=90)


def tiled_pdf(panels, seams, path, garment_name="", sa_cm=1.5, paper="letter", margin_in=0.4):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    pw, ph = PAGES[paper]
    tw, th = (pw - 2 * margin_in) * IN, (ph - 2 * margin_in) * IN            # tile size, cm

    def pages_with_ink(placed):
        allpts = np.vstack([g["cut"] for g in placed])
        x0, y0 = allpts.min(0) - 1
        x1, y1 = allpts.max(0) + 1
        ncol, nrow = int(np.ceil((x1 - x0) / tw)), int(np.ceil((y1 - y0) / th))
        polys = [Polygon(g["cut"]) for g in placed]
        ink = set()
        for r in range(nrow):
            for c in range(ncol):
                tx, ty = x0 + c * tw, y1 - (r + 1) * th
                tile = Polygon([(tx, ty), (tx + tw, ty), (tx + tw, ty + th), (tx, ty + th)])
                if any(tile.intersects(pp) for pp in polys):
                    ink.add((r, c))
        return ink, (x0, y0, x1, y1, ncol, nrow)

    # arrangement width: try 2..5 pages across, keep the fewest printed pages
    best = None
    for k in (2, 3, 4, 5, 6):
        try:
            placed_k, _ = _arrange(panels, seams, sa_cm, width_cm=k * tw - 2)
        except ValueError:
            continue          # a piece is wider than k pages: try wider
        ink, geo = pages_with_ink(placed_k)
        if best is None or len(ink) < len(best[1]):
            best = (placed_k, ink, geo)
    placed, ink, (x0, y0, x1, y1, ncol, nrow) = best
    from . import brand
    with PdfPages(path, metadata=brand.pdf_metadata()) as pdf:
        for r in range(nrow):
            for c in range(ncol):
                if (r, c) not in ink and (r, c) != (0, 0):
                    continue          # blank page: don't print it
                fig = plt.figure(figsize=(pw, ph))
                ax = fig.add_axes([margin_in / pw, margin_in / ph, 1 - 2 * margin_in / pw, 1 - 2 * margin_in / ph])
                tx, ty = x0 + c * tw, y1 - (r + 1) * th
                ax.set_xlim(tx, tx + tw); ax.set_ylim(ty, ty + th)
                ax.set_aspect("equal"); ax.axis("off")
                _draw_pieces(ax, placed, garment_name)
                # page frame, label, alignment triangles on the inner edges
                ax.plot([tx, tx + tw, tx + tw, tx, tx], [ty, ty, ty + th, ty + th, ty], color="#999", lw=0.5)
                label = f"{chr(65 + r)}{c + 1}"
                ax.text(tx + tw / 2, ty + th / 2, label, fontsize=60, color="#000", alpha=0.06,
                        ha="center", va="center")
                ax.text(tx + 0.4, ty + th - 0.4, f"{label}   ({r + 1}/{nrow} rows, {c + 1}/{ncol} cols)",
                        fontsize=7, va="top", color="#555")
                for (mx, my) in ((tx + tw / 2, ty), (tx + tw / 2, ty + th), (tx, ty + th / 2), (tx + tw, ty + th / 2)):
                    ax.plot(mx, my, marker="d", ms=6, color="#555")
                if r == 0 and c == 0:
                    # test squares
                    sx, sy = tx + 1.0, ty + 1.0
                    ax.add_patch(plt.Rectangle((sx, sy), 5, 5, fill=False, lw=1.0))
                    ax.text(sx + 2.5, sy + 2.5, "5 cm", ha="center", va="center", fontsize=8)
                    ax.add_patch(plt.Rectangle((sx + 6, sy), 2 * IN, 2 * IN, fill=False, lw=1.0))
                    ax.text(sx + 6 + IN, sy + IN, "2 in", ha="center", va="center", fontsize=8)
                    ax.text(sx, sy + 6, "Print at 100% / 'actual size'.\nCheck these squares with a ruler first.",
                            fontsize=7, va="bottom")
                brand.pdf_footer(fig, f"{garment_name} · page {label}" if garment_name else f"page {label}")
                pdf.savefig(fig); plt.close(fig)
    return dict(pages=len(ink | {(0, 0)}), rows=nrow, cols=ncol, paper=paper)


def projector_pdf(panels, seams, path, garment_name="", sa_cm=1.5, width_cm=140):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    placed, lay = _arrange(panels, seams, sa_cm, width_cm=width_cm)
    allpts = np.vstack([g["cut"] for g in placed])
    x0, y0 = np.floor(allpts.min(0) / 10) * 10 - 10
    x1, y1 = np.ceil(allpts.max(0) / 10) * 10 + 10
    W, H = (x1 - x0) / IN, (y1 - y0) / IN
    fig = plt.figure(figsize=(W, H))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect("equal"); ax.axis("off")
    for gx in np.arange(x0, x1 + 1, 10):
        ax.axvline(gx, color="#ccc", lw=0.4)
    for gy in np.arange(y0, y1 + 1, 10):
        ax.axhline(gy, color="#ccc", lw=0.4)
    _draw_pieces(ax, placed, garment_name, lw=1.2)
    ax.add_patch(plt.Rectangle((x0 + 2, y0 + 2), 10, 10, fill=False, lw=2))
    ax.text(x0 + 7, y0 + 7, "10 cm\ncalibrate", ha="center", va="center", fontsize=10)
    from . import brand
    ax.text(x1 - 2, y0 + 2, brand.MADE_WITH, ha="right", va="bottom", fontsize=10, color="#999")
    fig.savefig(path, metadata=brand.pdf_metadata()); plt.close(fig)
    return dict(width_cm=x1 - x0, height_cm=y1 - y0)
