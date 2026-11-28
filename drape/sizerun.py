"""Size runs: one pattern graded across standard sizes, as a sell-ready
print-at-home PDF (all sizes nested on the same pages, a size chart, a test
square) - the kind of PDF pattern people buy on Etsy.

Size tables
  misses  Women, US misses sizes 2-20: ASTM D5585-95 body measurements
          (bust, waist, hip, neck base, upper arm, mid thigh), 5'5" tall.
  mens    Men, chest sizes 34-52 (regular): chest = size; waist = chest - 6"
          (the usual 'drop 6' regular cut); hip = chest + 1"; neck from the
          common shirt-size rule. A rule of thumb, not an ASTM table (the men's
          table isn't freely available).
Pattern-library garments are re-drafted for each size from the size's
measurements (true grading: ease, darts, sleeve caps all recomputed).
From-scratch designs are graded proportionally: widths by the size's girths,
lengths by height, relative to the avatar the design was made on.
"""
from __future__ import annotations

import numpy as np

from .blocks import BLOCKS, EASE_PARAM, body_measures, draft_block, preset_values
from .measurements import Measurements

IN = 2.54

# ASTM D5585-95 (misses), inches
_MISSES = {
    "size": ["2", "4", "6", "8", "10", "12", "14", "16", "18", "20"],
    "bust": [32, 33, 34, 35, 36, 37.5, 39, 40.5, 42.5, 44.5],
    "waist": [24, 25, 26, 27, 28, 29.5, 31, 32.5, 34.5, 36.5],
    "hip": [34.5, 35.5, 36.5, 37.5, 38.5, 40, 41.5, 43, 45, 47],
    "neck": [13.5, 13.75, 14, 14.25, 14.5, 14.875, 15.25, 15.625, 16.125, 16.625],
    "upper_arm": [10, 10.25, 10.5, 10.75, 11, 11.375, 11.75, 12.125, 12.75, 13.375],
    "thigh": [18.25, 18.75, 19.25, 19.75, 20.25, 21, 21.75, 22.5, 23.5, 24.5],
}


def size_table(kind):
    """List of (size label, Measurements) in cm."""
    out = []
    if kind == "misses":
        T = _MISSES
        for i, s in enumerate(T["size"]):
            b = T["bust"][i] * IN
            m = Measurements(sex="female", height=166.0, chest=b, waist=T["waist"][i] * IN, hip=T["hip"][i] * IN,
                             neck=T["neck"][i] * IN, upper_arm=T["upper_arm"][i] * IN, thigh=T["thigh"][i] * IN,
                             shoulder_width=0.40 * b, arm_length=0.34 * 166.0, underbust=b - 12.0)
            out.append((s, m))
    elif kind == "mens":
        for c in range(34, 54, 2):
            ch = c * IN
            m = Measurements(sex="male", height=178.0, chest=ch, waist=(c - 6) * IN, hip=(c + 1) * IN,
                             neck=(0.31 * c + 3.3) * IN, upper_arm=(0.27 * c + 1.2) * IN,
                             thigh=(0.5 * c + 2) * IN, shoulder_width=0.44 * ch, arm_length=0.345 * 178.0)
            out.append((str(c), m))
    else:
        raise ValueError(f"unknown size table {kind!r}: misses or mens")
    return out


def grade_block(block, choices, params, kind, sizes=None):
    """[(size, garment, finished measurements)] for a pattern-library block."""
    out = []
    for label, m in size_table(kind):
        if sizes and label not in sizes:
            continue
        bm = body_measures(None, m)
        over = preset_values(block, choices or {}, bm)
        # user edits that are ease/style (not tied to one body) carry over
        over.update({k: v for k, v in (params or {}).items()})
        g, info = draft_block(block, None, m, over)
        fin = {}
        for line, p in EASE_PARAM.items():
            if p in info["params"] and line in ("chest", "waist", "hip"):
                fin[line] = bm[line] + info["params"][p]
        out.append((label, g, m, fin))
    return out


def grade_design(design, base_meas, kind, body_factory=None, sizes=None):
    """Proportional grading of a from-scratch design (editor format, cm)."""
    import copy
    out = []
    for label, m in size_table(kind):
        if sizes and label not in sizes:
            continue
        fx = 0.5 * (m.chest / base_meas.chest + m.hip / base_meas.hip)
        fy = m.height / base_meas.height
        d = copy.deepcopy(design)
        for pc in d["pieces"]:
            for e in pc["edges"]:
                e["pts"] = [[x * fx, y * fy] for x, y in e["pts"]]
        out.append((label, d, m, {}))
    return out


# ------------------------------------------------------------------ the PDF --
def sizerun_pdf(graded, path, title="", sa_cm=1.5, paper="letter", margin_in=0.4, units="in", seams=None):
    """graded: [(size, panels, measurements, finished)] (panels: drape.pattern.Panel
    with metres). Pieces of all sizes are nested, lined up at the top centre."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from shapely.geometry import Polygon
    from .printpdf import PAGES, _piece_geoms
    pw, ph = PAGES[paper]
    tw, th = (pw - 2 * margin_in) * IN, (ph - 2 * margin_in) * IN
    n = len(graded)
    cmap = plt.get_cmap("tab10" if n <= 10 else "tab20")
    styles = [(0, ()), (0, (6, 2)), (0, (2, 2)), (0, (8, 2, 2, 2))]
    # per piece: outlines of every size, aligned at the top centre of the stitch line
    names = [p.name for p in graded[0][1]]
    pieces = []
    for name in names:
        rows = []
        for k, (label, panels, m, fin) in enumerate(graded):
            P = next(p for p in panels if p.name == name)
            g = _piece_geoms([P], seams[k] if seams else [], sa_cm)[0]
            st = g["stitch"]
            ref = np.array([0.5 * (st[:, 0].min() + st[:, 0].max()), st[:, 1].max()])
            rows.append(dict(size=label, cut=g["cut"] - ref, stitch=st - ref,
                             notches=[(a - ref, b - ref) for a, b in g["notches"]], k=k))
        allp = np.vstack([r["cut"] for r in rows])
        lo, hi = allp.min(0), allp.max(0)
        pieces.append(dict(name=name, rows=rows, w=hi[0] - lo[0], h=hi[1] - lo[1], lo=lo))
    # shelf-pack the pieces into a strip a few pages wide (fewest pages wins)
    def pack(W):
        offs, x, y, rowh = {}, 0.0, 0.0, 0.0
        for p in sorted(range(len(pieces)), key=lambda i: -pieces[i]["h"]):
            P = pieces[p]
            if x > 0 and x + P["w"] > W:
                x, y, rowh = 0.0, y + rowh + 2, 0.0
            offs[p] = np.array([x - P["lo"][0], -y - (P["lo"][1] + P["h"])])
            x += P["w"] + 2; rowh = max(rowh, P["h"])
        return offs, y + rowh
    best = None
    for cols in (2, 3, 4, 5, 6):
        W = cols * tw - 2
        if any(P["w"] > W for P in pieces):
            continue
        offs, tot = pack(W)
        pages = cols * int(np.ceil((tot + 1) / th))
        if best is None or pages < best[0]:
            best = (pages, cols, offs, tot)
    _, cols, offs, tot = best
    y, rowh = tot, 0.0
    nrow = int(np.ceil((y + rowh + 1) / th))
    x0, ytop = -1.0, 1.0

    def draw(ax):
        for p, P in enumerate(pieces):
            o = offs[p]
            for r in P["rows"]:
                col = cmap(r["k"] % 10)
                ax.plot(*(np.vstack([r["cut"], r["cut"][:1]]) + o).T, color=col, lw=1.0, ls=styles[(r["k"] // 10) % 4])
            base = P["rows"][len(P["rows"]) // 2]
            for a, b in base["notches"]:
                ax.plot([a[0] + o[0], b[0] + o[0]], [a[1] + o[1], b[1] + o[1]], color="black", lw=1.2)
            lo = P["lo"] + o
            cx = lo[0] + P["w"] / 2
            ax.annotate("", (cx, lo[1] + P["h"] * 0.75), (cx, lo[1] + P["h"] * 0.2),
                        arrowprops=dict(arrowstyle="<->", lw=0.8, color="#1f4e8c"))
            ax.text(cx + 1, lo[1] + P["h"] * 0.5, f"{P['name'].replace('_', ' ').upper()}\n{title}\nsizes {graded[0][0]}–{graded[-1][0]}\ngrain ↕",
                    fontsize=8, color="#1f4e8c", va="center", rotation=90)
            for r in P["rows"]:   # size labels along the bottom of each outline
                c = r["cut"] + o
                i = int(np.argmin(c[:, 1] - 0.02 * c[:, 0]))
                ax.text(c[i, 0], c[i, 1] - 0.3, r["size"], fontsize=6, color=cmap(r["k"] % 10), ha="center", va="top")

    from . import brand
    with PdfPages(path, metadata=brand.pdf_metadata()) as pdf:
        # cover: size chart, legend, how to print
        fig = plt.figure(figsize=(pw, ph))
        fig.text(0.08, 0.93, title or "Pattern", fontsize=22, weight="bold")
        fig.text(0.08, 0.90, f"Sizes {graded[0][0]}–{graded[-1][0]} · seam allowance {sa_cm:g} cm ({sa_cm / IN:.2g} in) included",
                 fontsize=10, color="#444")
        u = (lambda v: f"{v / IN:.1f}") if units == "in" else (lambda v: f"{v:.0f}")
        rows = [["Size", "Bust/chest", "Waist", "Hip", "Finished chest", "Finished hip"]]
        for label, _, m, fin in graded:
            rows.append([label, u(m.chest), u(m.waist), u(m.hip), u(fin["chest"]) if "chest" in fin else "–",
                         u(fin["hip"]) if "hip" in fin else "–"])
        ax = fig.add_axes([0.08, 0.40, 0.84, 0.45]); ax.axis("off")
        tb = ax.table(cellText=rows[1:], colLabels=rows[0], loc="upper left", cellLoc="center")
        tb.auto_set_font_size(False); tb.set_fontsize(9); tb.scale(1, 1.35)
        for k in range(len(graded)):
            tb[k + 1, 0].set_text_props(color=cmap(k % 10), weight="bold")
        fig.text(0.08, 0.37, f"Body measurements in {'inches' if units == 'in' else 'cm'}. Pick your size by bust/chest "
                              "(tops) or hip (skirts, trousers); blend between sizes at the waist if you need to.",
                 fontsize=8.5, wrap=True)
        fig.text(0.08, 0.30, "Printing: print at 100% / 'actual size' (never 'fit to page'). Check the test square "
                             "on page 2 with a ruler.\nTape pages together matching the diamonds; page labels A1, A2... "
                             "are rows and columns.\nCut along your size's colour.", fontsize=8.5, va="top")
        brand.pdf_footer(fig); pdf.savefig(fig); plt.close(fig)
        for r in range(nrow):
            for c in range(cols):
                tx, ty = x0 + c * tw, ytop - (r + 1) * th
                tile = Polygon([(tx, ty), (tx + tw, ty), (tx + tw, ty + th), (tx, ty + th)])
                ink = any(tile.intersects(Polygon(np.vstack([rr["cut"] + offs[p] for rr in P["rows"][-1:]])).convex_hull)
                          for p, P in enumerate(pieces))
                if not ink and (r, c) != (0, 0):
                    continue
                fig = plt.figure(figsize=(pw, ph))
                ax = fig.add_axes([margin_in / pw, margin_in / ph, 1 - 2 * margin_in / pw, 1 - 2 * margin_in / ph])
                ax.set_xlim(tx, tx + tw); ax.set_ylim(ty, ty + th); ax.set_aspect("equal"); ax.axis("off")
                draw(ax)
                ax.plot([tx, tx + tw, tx + tw, tx, tx], [ty, ty, ty + th, ty + th, ty], color="#999", lw=0.5)
                lab = f"{chr(65 + r)}{c + 1}"
                ax.text(tx + tw / 2, ty + th / 2, lab, fontsize=60, color="#000", alpha=0.06, ha="center", va="center")
                ax.text(tx + 0.4, ty + th - 0.4, lab, fontsize=7, va="top", color="#555")
                for (mx, my) in ((tx + tw / 2, ty), (tx + tw / 2, ty + th), (tx, ty + th / 2), (tx + tw, ty + th / 2)):
                    ax.plot(mx, my, marker="d", ms=6, color="#555")
                if (r, c) == (0, 0):
                    sx, sy = tx + 1.0, ty + 1.0
                    ax.add_patch(plt.Rectangle((sx, sy), 5, 5, fill=False, lw=1.0))
                    ax.text(sx + 2.5, sy + 2.5, "5 cm", ha="center", va="center", fontsize=8)
                    ax.add_patch(plt.Rectangle((sx + 6, sy), 2 * IN, 2 * IN, fill=False, lw=1.0))
                    ax.text(sx + 6 + IN, sy + IN, "2 in", ha="center", va="center", fontsize=8)
                    # size legend
                    for k, (label, *_r) in enumerate(graded):
                        ax.plot([sx + 13, sx + 15], [sy + 4.6 - k * 0.5] * 2, color=cmap(k % 10), lw=1.5, ls=styles[(k // 10) % 4])
                        ax.text(sx + 15.4, sy + 4.6 - k * 0.5, label, fontsize=6, va="center")
                brand.pdf_footer(fig); pdf.savefig(fig); plt.close(fig)
    return {"sizes": [g[0] for g in graded], "pieces": len(pieces)}
