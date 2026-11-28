"""Export flat pattern pieces to DXF (millimeters) for printing, plotting,
or laser/knife cutting.

Layers:
  CUT    - cut line (sew line offset outward by the seam allowance)
  SEW    - stitch line (the actual pattern outline), dashed
  NOTCH  - notches 40% along every seamed edge (one = front, two = back) and match dots
  SEAMNO - seam numbers in the seam colour: 3 sews to 3
  GRAIN  - grainline arrow
  TEXT   - piece name, cut count, seam allowance
"""
from __future__ import annotations

import numpy as np
import ezdxf
import ezdxf.colors
import ezdxf.enums
from shapely.geometry import Polygon

from .pattern import Panel, Seam, polyline_length


def _outline(p: Panel) -> np.ndarray:
    pts = [e[:-1] for _, e in p.edges]
    return np.concatenate(pts)


def _point_at(poly: np.ndarray, frac: float):
    """Point and unit tangent at a fraction of a polyline's arc length."""
    seg = np.diff(poly, axis=0)
    L = np.linalg.norm(seg, axis=1)
    s = np.concatenate([[0], np.cumsum(L)])
    t = frac * s[-1]
    i = min(np.searchsorted(s, t) - 1, len(seg) - 1)
    i = max(i, 0)
    u = (t - s[i]) / L[i] if L[i] > 0 else 0.0
    return poly[i] + u * seg[i], seg[i] / (L[i] + 1e-12)


def export_pattern_dxf(path, panels: list[Panel], seams: list[Seam],
                       seam_allowance: float = 0.010, gap: float = 0.04,
                       cut_counts: dict[str, int] | None = None, laser: bool = False) -> dict:
    """Write all panels laid out left to right. Lengths in meters in, mm out.
    Returns a summary dict (areas, bounding boxes) for checking.

    laser=True writes a laser-cutter file (LightBurn, RDWorks, LaserGRBL
    import layers by color): CUT red (ACI 1, cut through), SEW blue (ACI 5,
    a light mark or turn it off), GRAIN/TEXT green (ACI 3, engrave or off).
    Notches become 4 mm snips in from the cut edge, so the laser never cuts
    into the stitch line. No dashed linetypes (lasers ignore them)."""
    mm = 1000.0
    doc = ezdxf.new("R2010", setup=True)
    from . import brand
    brand.dxf_stamp(doc)
    doc.header["$INSUNITS"] = 4       # millimeters
    doc.header["$MEASUREMENT"] = 1    # metric
    layers = (("CUT", 7, "CONTINUOUS"), ("SEW", 1, "DASHED"), ("NOTCH", 3, "CONTINUOUS"),
              ("GRAIN", 5, "CONTINUOUS"), ("TEXT", 8, "CONTINUOUS"), ("MARK", 6, "CONTINUOUS"),
              ("SEAMNO", 4, "CONTINUOUS"))
    if laser:
        layers = (("CUT", 1, "CONTINUOUS"), ("SEW", 5, "CONTINUOUS"), ("NOTCH", 1, "CONTINUOUS"),
                  ("GRAIN", 3, "CONTINUOUS"), ("TEXT", 3, "CONTINUOUS"), ("MARK", 6, "CONTINUOUS"),
                  ("SEAMNO", 4, "CONTINUOUS"))      # seam numbers: engrave lightly or turn off
    for name, color, lt in layers:
        doc.layers.add(name, color=color, linetype=lt)
    msp = doc.modelspace()

    from .seammarks import seam_marks
    SM = seam_marks(panels, seams)
    cut_counts = cut_counts or {}
    x_cursor, summary = 0.0, {}

    for p in panels:
        sew = _outline(p)
        sew_poly = Polygon(sew)
        if not sew_poly.is_valid:
            raise ValueError(f"panel {p.name}: outline self-intersects")
        # mitred corners keep sharp points sharp (with a limit so acute corners don't spike)
        from .closures import cut_polygon
        cut_poly = cut_polygon(p, seam_allowance * 100)
        from shapely.affinity import scale as _sc
        cut_poly = _sc(cut_poly, 0.01, 0.01, origin=(0, 0))
        cut = np.asarray(cut_poly.exterior.coords)

        minx, miny, maxx, maxy = cut_poly.bounds
        off = np.array([x_cursor - minx, -miny])
        to_mm = lambda a: [tuple(v) for v in ((np.asarray(a) + off) * mm)]

        msp.add_lwpolyline(to_mm(cut), close=True, dxfattribs={"layer": "CUT"})
        msp.add_lwpolyline(to_mm(sew), close=True,
                           dxfattribs={"layer": "SEW"} if laser else {"layer": "SEW", "ltscale": 0.5})

        for mk in getattr(p, "marks", None) or []:     # buttonholes, buttons, fold line, zipper stop
            msp.add_lwpolyline(to_mm(mk["pts"]), dxfattribs={"layer": "MARK"})
        # notches (single = front, double = back, 40% along so a piece can't go in end for end),
        # seam numbers on their own layer in the seam's colour (engrave lightly, or hide)
        n_notch = 0
        for en, mk in SM[p.name]["edges"].items():
            for q, nrm in mk["notches"]:
                q, nrm = np.asarray(q) / 100, np.asarray(nrm)
                a, b = q, q + nrm * seam_allowance
                if laser:   # a short snip in from the cut edge only
                    a = q + nrm * max(seam_allowance - 0.004, seam_allowance * 0.5)
                msp.add_line(*to_mm([a, b]), dxfattribs={"layer": "NOTCH"})
                n_notch += 1
            rgb = tuple(int(mk["color"][k:k + 2], 16) for k in (1, 3, 5))
            t = msp.add_text(str(mk["num"]), height=8.0,                       # 8 mm tall
                             dxfattribs={"layer": "SEAMNO", "true_color": ezdxf.colors.rgb2int(rgb)})
            t.set_placement(to_mm([np.asarray(mk["tag"]) / 100])[0], align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
        for d in SM[p.name]["dots"]:
            c = np.asarray(d["point"]) / 100
            msp.add_circle(to_mm([c])[0], radius=2.0, dxfattribs={"layer": "NOTCH"})      # match point, 2 mm

        # grainline: vertical (pattern v axis = lengthwise grain), centered
        c = np.array(sew_poly.centroid.coords[0])
        h = 0.5 * (sew[:, 1].max() - sew[:, 1].min())
        g0, g1 = c - [0, h * 0.6], c + [0, h * 0.6]
        msp.add_line(*to_mm([g0, g1]), dxfattribs={"layer": "GRAIN"})
        for side in (-1, 1):
            msp.add_line(*to_mm([g1, g1 + [side * 0.01, -0.02]]), dxfattribs={"layer": "GRAIN"})
            msp.add_line(*to_mm([g0, g0 + [side * 0.01, 0.02]]), dxfattribs={"layer": "GRAIN"})

        n = cut_counts.get(p.name, 1)
        label = f"{p.name.upper()}  cut {n}"
        sub = f"SA {seam_allowance * mm:g} mm included"
        tp = to_mm([c + [0.02, -h * 0.55], c])  # rotated text grows upward from here
        msp.add_text(label, height=min(12, h * mm * 0.06), dxfattribs={"layer": "TEXT", "rotation": 90}).set_placement(tp[0])
        msp.add_text(sub, height=min(7, h * mm * 0.035), dxfattribs={"layer": "TEXT", "rotation": 90}).set_placement(
            (tp[0][0] + 16, tp[0][1]))

        summary[p.name] = {
            "sew_area_mm2": sew_poly.area * mm * mm,
            "cut_area_mm2": cut_poly.area * mm * mm,
            "cut_bbox_mm": ((maxx - minx) * mm, (maxy - miny) * mm),
            "notches": n_notch,
            "sew_perimeter_mm": polyline_length(np.vstack([sew, sew[:1]])) * mm,
        }
        x_cursor += (maxx - minx) + gap

    doc.saveas(str(path))
    return summary
