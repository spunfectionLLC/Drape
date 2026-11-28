"""Tech pack PDF: what a factory or a sewing contractor needs to make the
garment without you in the room.

  1  Cover: style, size, fabric, front/side/back views of the drape
  2  Measurement spec: points of measure on the finished garment (measured on
     the draped mesh), the body they were made for, ease and tolerances
  3  Bill of materials and cut list (fabrics, interfacing, notions, thread)
  4  Pattern pieces with their seam allowances
  5+ Construction steps
"""
from __future__ import annotations

import datetime
import textwrap

import numpy as np


def _hull_perimeter(P2):
    from scipy.spatial import ConvexHull
    if len(P2) < 4:
        return 0.0
    h = ConvexHull(P2)
    Q = P2[h.vertices]
    return float(np.linalg.norm(np.diff(np.vstack([Q, Q[:1]]), axis=0), axis=1).sum())


def girth_at(x, y, panel_id=None, keep=None, band=0.012):
    """Finished girth of the cloth round the body at height y (m): convex hull of the
    cloth points in a thin slice, torso only (arms/sleeves left out)."""
    sel = np.abs(x[:, 1] - y) < band
    if keep is not None:
        sel &= keep
    P = x[sel][:, [0, 2]]
    if len(P) < 8:
        return None
    # drop the arms: points far out to the sides of the torso
    med = np.median(np.abs(P[:, 0]))
    P = P[np.abs(P[:, 0]) < max(med * 2.2, 0.05)]
    return _hull_perimeter(P)


def points_of_measure(x, panel_id, panel_names, body, m):
    """POMs on the draped garment (cm): (name, garment, body, ease)."""
    L = body.lines
    names = list(panel_names)
    sleeve = np.isin(panel_id, [i for i, n in enumerate(names) if "sleeve" in n or "cuff" in n])
    torso = ~sleeve
    out = []
    ytop, ybot = x[torso, 1].max(), x[torso, 1].min()
    for key, label, bm in (("chest", "Chest / bust (1 in below armhole)", m.chest), ("waist", "Waist", m.waist),
                           ("hip", "Hip", m.hip)):
        y = L["armpit"] - 0.025 if key == "chest" else L[key]
        if not (ybot + 0.01 < y < ytop - 0.01):
            continue
        g = girth_at(x, y, keep=torso)
        if g:
            out.append((label, g * 100, bm, g * 100 - bm))
    hem = girth_at(x, ybot + 0.012, keep=torso)
    if hem:
        out.append(("Hem sweep", hem * 100, None, None))
    out.append(("Length (highest point to hem)", (ytop - ybot) * 100, None, None))
    # trousers and shorts: inseam, from the garment's crotch point down to the hem
    # (only near the body's crotch: knees can come close to the centre line too)
    mid = torso & (np.abs(x[:, 0]) < 0.015) & (x[:, 1] > L["crotch"] - 0.08)
    if mid.any():
        cy = float(x[mid, 1].min())
        legs = torso & (x[:, 1] < cy - 0.05) & (np.abs(x[:, 0]) > 0.03)
        if legs.sum() > 50 and (x[legs, 0] < 0).any() and (x[legs, 0] > 0).any():
            body_ins = getattr(m, "inseam", None) or float(body.lines["crotch"]) * 100
            out.append(("Inseam (crotch to hem)", (cy - x[legs, 1].min()) * 100, body_ins, None))
    if sleeve.any():
        S = x[sleeve]
        # sleeve length: furthest sleeve point from the shoulder line, per side
        for side, sgn in (("right", -1), ("left", 1)):
            Ss = S[np.sign(S[:, 0]) == sgn]
            if len(Ss) > 10:
                lo, hi = Ss[np.argmin(np.abs(Ss[:, 0]))], Ss[np.argmax(np.abs(Ss[:, 0]))]
                out.append((f"Sleeve length ({side}, shoulder to hem)", float(np.linalg.norm(hi - lo)) * 100,
                            m.arm_length if side == "right" else None, None))
                break
    return out


def _draw_table(ax, rows, cols, widths, top=0.95, fs=8.5, row_h=0.034):
    x = 0.0
    xs = []
    for w in widths:
        xs.append(x); x += w
    for c, xx in zip(cols, xs):
        ax.text(xx + 0.005, top, c, fontsize=fs, weight="bold", va="top", transform=ax.transAxes)
    ax.plot([0, 1], [top - row_h * 0.75] * 2, color="black", lw=0.8, transform=ax.transAxes)
    y = top - row_h
    for r in rows:
        for v, xx in zip(r, xs):
            ax.text(xx + 0.005, y, "" if v is None else str(v), fontsize=fs, va="top", transform=ax.transAxes)
        y -= row_h
        ax.plot([0, 1], [y + row_h * 0.25] * 2, color="#ccc", lw=0.4, transform=ax.transAxes)
    return y


def techpack_pdf(path, g, body, m, title="My design", fabric_label="", size="custom", sa_cm=1.5,
                 draped=None, notes="", fabric_key=None, units="cm"):
    """draped: (x, tris, panel_id) of the welded draped mesh, or None (views from the start shape)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from .costing import materials
    from .instructions import instructions
    from .printpdf import _draw_pieces, _piece_geoms
    from .render import Renderer, garment_colors

    u = 1.0 if units == "cm" else 1 / 2.54
    U = units
    x, tris, pid = draped if draped is not None else (g.x, g.tris, g.panel_id)
    today = datetime.date.today().isoformat()
    M = materials(g, sa_cm=sa_cm)
    from . import brand
    foot = lambda fig: brand.pdf_footer(fig, brand.COPYRIGHT)
    with PdfPages(str(path), metadata=brand.pdf_metadata()) as pdf:
        # ---------------------------------------------------------- cover --
        fig = plt.figure(figsize=(11, 8.5))
        fig.text(0.04, 0.94, title, fontsize=24, weight="bold")
        fig.text(0.04, 0.905, f"Tech pack  ·  size {size}  ·  {fabric_label}  ·  {today}", fontsize=11, color="#555")
        try:
            R = Renderer(body, width=420, height=620, scale=330, center=(0.0, float(x[:, 1].mean())))
            cols = np.tile(np.array([[0.36, 0.48, 0.66]]), (len(x), 1))      # one fabric colour, like a flat sketch
            for k, (yaw, lab) in enumerate(((0, "Front"), (90, "Side"), (180, "Back"))):
                ax = fig.add_axes([0.03 + k * 0.32, 0.12, 0.30, 0.74])
                ax.imshow(R.render(x, tris, cols, yaw=yaw)); ax.axis("off"); ax.set_title(lab, fontsize=11)
        except Exception as e:     # views are a nicety: the rest of the pack doesn't depend on them
            fig.text(0.04, 0.5, f"(views unavailable: {e})")
        info = [f"Pieces: {len(g.meta['panels'])}", f"Seams: {len(g.meta.get('seam_defs', []))}",
                f"Seam allowance: {sa_cm * u:.2g} {U} unless noted", f"Sewing time: ~{M['minutes']} min"]
        if g.meta.get("closures"):
            info.append("Closures: " + ", ".join(f"{c['label'].lower()}" for c in g.meta["closures"]))
        fig.text(0.04, 0.06, "   ·   ".join(info), fontsize=9)
        if notes:
            fig.text(0.04, 0.03, notes, fontsize=9, color="#444")
        foot(fig); pdf.savefig(fig); plt.close(fig)

        # ------------------------------------------------ measurement spec --
        fig = plt.figure(figsize=(11, 8.5))
        fig.text(0.04, 0.94, "Measurement spec (finished garment)", fontsize=16, weight="bold")
        fig.text(0.04, 0.91, f"Measured on the draped garment, size {size}. Body = the avatar it was fitted to. "
                             f"Tolerances: ±1 {U} on girths, ±0.6 {U} on lengths.", fontsize=9, color="#555")
        ax = fig.add_axes([0.04, 0.08, 0.92, 0.8]); ax.axis("off")
        rows = []
        for i, (name, gv, bv, ease) in enumerate(points_of_measure(x, pid, g.panel_names, body, m)):
            tol = "±1" if "sweep" in name or "Chest" in name or "Waist" in name or "Hip" in name else "±0.6"
            rows.append((chr(65 + i), name, f"{gv * u:.1f}", "" if bv is None else f"{bv * u:.1f}",
                         "" if ease is None else f"{ease * u:+.1f}", tol))
        _draw_table(ax, rows, ["POM", "Point of measure", f"Garment ({U})", f"Body ({U})", "Ease", "Tol."],
                    [0.06, 0.44, 0.13, 0.13, 0.12, 0.12])
        foot(fig); pdf.savefig(fig); plt.close(fig)

        # ------------------------------------------------- BOM + cut list --
        fig = plt.figure(figsize=(11, 8.5))
        fig.text(0.04, 0.94, "Bill of materials", fontsize=16, weight="bold")
        ax = fig.add_axes([0.04, 0.52, 0.92, 0.38]); ax.axis("off")
        rows = []
        for f in M["fabrics"]:
            lab = fabric_label if f["fabric"] == "main" and fabric_label else f["fabric"]
            rows.append(("Fabric", lab, f"{f['metres']:.2f} m / {f['yards']:.2f} yd", "150 cm wide",
                         f"{len(f['pieces'])} pcs"))
        for k, a in (M.get("interfacing_cm2") or {}).items():
            rows.append(("Interfacing", f"{k} fusible", f"{a / 1e4 * 1.15:.2f} m²", "", ""))
        if M.get("elastic_cm"):
            rows.append(("Elastic", "", f"{M['elastic_cm']:.0f} cm", "", ""))
        for n in M.get("notions", []):
            rows.append(("Notion", n["label"], str(n["qty"]), "", ""))
        rows.append(("Thread", "all-purpose polyester", f"{M.get('thread_m', 0):.0f} m", "", ""))
        _draw_table(ax, rows, ["Type", "Description", "Quantity", "Spec", "Pieces"], [0.14, 0.38, 0.2, 0.14, 0.14],
                    fs=9, row_h=0.085)
        fig.text(0.04, 0.46, "Cut list", fontsize=16, weight="bold")
        ax = fig.add_axes([0.04, 0.04, 0.92, 0.4]); ax.axis("off")
        per = {}
        for p in g.meta["panels"]:
            per[p.name] = ", ".join(f"{e} {v * u:g}" for e, v in (getattr(p, "sa_edges", None) or {}).items())
        rows = [(c["piece"], c["fabric"], c.get("interfacing") or "", str(c["cut"]),
                 per.get(c["piece"]) or f"{sa_cm * u:g} all round") for c in M["cut_list"]]
        _draw_table(ax, rows, ["Piece", "Fabric", "Interfacing", "Cut", f"Seam allowance ({U})"],
                    [0.22, 0.18, 0.15, 0.08, 0.37], fs=8, row_h=0.05 if len(rows) < 14 else 0.035)
        foot(fig); pdf.savefig(fig); plt.close(fig)

        # ------------------------------------------------- pattern pieces --
        fig = plt.figure(figsize=(11, 8.5))
        fig.text(0.04, 0.94, "Pattern pieces", fontsize=16, weight="bold")
        fig.text(0.04, 0.91, "Not to scale: print the pattern PDF or cut from the DXF. Solid = cut, dashed = stitch.",
                 fontsize=9, color="#555")
        ax = fig.add_axes([0.03, 0.03, 0.94, 0.86]); ax.set_aspect("equal"); ax.axis("off")
        geoms = _piece_geoms(g.meta["panels"], g.meta.get("seam_defs"), sa_cm)
        placed, xo, yo, rowh = [], 0.0, 0.0, 0.0
        widest = 0.0
        for gm in geoms:
            c = np.asarray(gm["cut"]); lo, hi = c.min(0), c.max(0)
            w, h = hi - lo
            if xo + w > 150:
                xo = 0.0; yo -= rowh + 6; rowh = 0.0
            d = np.array([xo, yo]) - lo
            T = lambda P, d=d: np.asarray(P) + d
            placed.append(dict(name=gm["name"], stitch=T(gm["stitch"]), cut=T(gm["cut"]),
                               notches=[(T(a), T(b)) for a, b in gm["notches"]],
                               marks=[{"kind": mk["kind"], "pts": T(mk["pts"])} for mk in gm.get("marks", [])],
                               grain=(T(gm["grain"][0]), T(gm["grain"][1])), label=T(gm["label"]), rot=0))
            xo += w + 6; rowh = max(rowh, h); widest = max(widest, xo)
        _draw_pieces(ax, placed, title, lw=0.6)
        ax.autoscale()
        foot(fig); pdf.savefig(fig); plt.close(fig)

        # ----------------------------------------------------- steps --
        steps = instructions(g, sa_cm=sa_cm)
        per_page = 7
        for k in range(0, len(steps), per_page):
            fig = plt.figure(figsize=(8.5, 11))
            fig.text(0.06, 0.95, "Construction" + (" (cont.)" if k else ""), fontsize=16, weight="bold")
            y = 0.91
            for i, s in enumerate(steps[k:k + per_page], start=k + 1):
                fig.text(0.06, y, f"{i}. {s['title']}", fontsize=11, weight="bold", va="top")
                body_txt = textwrap.fill(s.get("text", ""), 95)
                fig.text(0.08, y - 0.025, body_txt, fontsize=8.5, va="top", color="#222")
                y -= 0.04 + 0.0135 * (body_txt.count("\n") + 1)
            foot(fig); pdf.savefig(fig); plt.close(fig)
    return path
