"""Laser-cutter nesting: pack pattern pieces (several garments at once) onto
your laser bed, sheet after sheet, and write one DXF ready for LightBurn.

Pieces keep their grain line along the bed's long side (they may turn 180
deg, never sideways). Each sheet is drawn next to the previous one with its
bed outline on a separate layer: switch that layer's output off in LightBurn,
cut a sheet, move the job to the next one.

Layers (LightBurn reads them by colour):
  CUT    red     cut through (outline with seam allowance)
  SEW    blue    the stitching line: a light score or mark, or turn it off
  NOTCH  red     4 mm snips into the seam allowance
  TEXT   green   piece names: engrave lightly, or turn it off
  BED    grey    the bed outline of each sheet: don't output
  MARK   magenta buttonholes, buttons, fold lines, zipper stops: score lightly or chalk
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from .printpdf import _arrange


def nest(panels, seams, bed_w_cm, bed_h_cm, sa_cm=1.5, garments=1, gap_cm=0.6):
    """Returns a list of sheets, each a list of placed pieces (cm, from printpdf._arrange)."""
    items, its = [], []
    for k in range(garments):
        tag = f"#{k + 1}" if garments > 1 else ""
        items += [replace(p, name=p.name + tag) for p in panels]
        its += [replace(s, panel_a=s.panel_a + tag, panel_b=s.panel_b + tag) for s in seams]
    remaining = items
    sheets = []
    while remaining:
        try:
            placed, _ = _arrange(remaining, its, sa_cm + gap_cm / 2, width_cm=bed_w_cm)
        except ValueError:
            wide = max(remaining, key=lambda p: np.ptp(np.concatenate([e for _, e in p.edges])[:, 0]))
            raise ValueError(f"'{wide.name}' is wider than the bed ({bed_w_cm:g} cm) even with its seam allowance")
        ymin = min(g["cut"][:, 1].min() for g in placed)
        fit = [g for g in placed if g["cut"][:, 1].max() - ymin <= bed_h_cm]
        if not fit:
            tall = max(placed, key=lambda g: np.ptp(g["cut"][:, 1]))
            raise ValueError(f"'{tall['name']}' is taller than the bed ({bed_h_cm:g} cm): use a bigger bed or cut it from a roll")
        for g in fit:   # shift so the sheet starts at y = 0
            for key in ("cut", "stitch"):
                g[key] = g[key] - [0, ymin]
            g["notches"] = [(a - [0, ymin], b - [0, ymin]) for a, b in g["notches"]]
            g["marks"] = [{"kind": mk["kind"], "pts": mk["pts"] - [0, ymin]} for mk in g.get("marks", [])]
            g["label"] = np.asarray(g["label"]) - [0, ymin]
        sheets.append(fit)
        done = {g["name"] for g in fit}
        remaining = [p for p in remaining if p.name not in done]
    return sheets


def nest_dxf(path, panels, seams, bed_w_cm, bed_h_cm, sa_cm=1.5, garments=1, title=""):
    import ezdxf
    sheets = nest(panels, seams, bed_w_cm, bed_h_cm, sa_cm, garments)
    doc = ezdxf.new("R2010", setup=True)
    from . import brand
    brand.dxf_stamp(doc)
    doc.units = ezdxf.units.MM
    for name, color in (("CUT", 1), ("SEW", 5), ("NOTCH", 1), ("TEXT", 3), ("BED", 8), ("MARK", 6)):
        doc.layers.add(name, color=color)
    msp = doc.modelspace()
    mm = lambda P, dx: [(float(x * 10 + dx), float(y * 10)) for x, y in P]
    used = 0.0
    for k, sheet in enumerate(sheets):
        dx = k * (bed_w_cm + 5) * 10
        msp.add_lwpolyline(mm([(0, 0), (bed_w_cm, 0), (bed_w_cm, bed_h_cm), (0, bed_h_cm)], dx), close=True,
                           dxfattribs={"layer": "BED"})
        msp.add_text(f"sheet {k + 1}/{len(sheets)} {title}", height=8,
                     dxfattribs={"layer": "BED", "insert": (dx, bed_h_cm * 10 + 6)})
        for g in sheet:
            msp.add_lwpolyline(mm(g["cut"], dx), close=True, dxfattribs={"layer": "CUT"})
            msp.add_lwpolyline(mm(g["stitch"], dx), close=True, dxfattribs={"layer": "SEW"})
            for a, b in g["notches"]:
                a, b = np.asarray(a), np.asarray(b)
                d = (b - a) / (np.linalg.norm(b - a) + 1e-12)
                msp.add_line(*mm([b - d * 0.4, b], dx), dxfattribs={"layer": "NOTCH"})
            for mk in g.get("marks", []):
                msp.add_lwpolyline(mm(mk["pts"], dx), dxfattribs={"layer": "MARK"})
            lx, ly = g["label"]
            msp.add_text(g["name"].replace("_", " "), height=6,
                         dxfattribs={"layer": "TEXT", "insert": (float(lx * 10 + dx), float(ly * 10))})
            from shapely.geometry import Polygon
            used += Polygon(g["cut"]).area
    doc.saveas(path)
    return {"sheets": len(sheets), "pieces": sum(len(s) for s in sheets),
            "bed_use_pct": round(100 * used / (len(sheets) * bed_w_cm * bed_h_cm))}
