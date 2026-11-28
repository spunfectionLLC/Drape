"""DXF-AAMA / ASTM D6673 pattern export: the format factories, marker makers,
cutting rooms and most pattern CAD programs read.

Each piece is a BLOCK inserted once, in millimetres (or inches), with the
AAMA layer numbers:
    1  boundary (cut line)           8  internal lines (fold lines, marks)
    14 sew line                      4  turn points / notches
    7  grain line                    13 drill holes (button marks)
and TEXT inside each block: Piece Name, Size, Quantity, Category, Annotation.
"""
from __future__ import annotations

import datetime

import numpy as np

LAYER_CUT, LAYER_NOTCH, LAYER_GRAIN, LAYER_INTERNAL, LAYER_DRILL, LAYER_SEW = "1", "4", "7", "8", "13", "14"


def export_aama(path, panels, seams=None, sa_cm=1.5, size="M", style="drape", units="mm",
                quantities=None, category="SHELL", sample_size=None):
    """Write a DXF-AAMA file. quantities: {piece: how many to cut} (default 1)."""
    import ezdxf
    from shapely.geometry import Polygon
    from .closures import cut_polygon, marks_cm
    from .printpdf import _piece_geoms

    k = 10.0 if units == "mm" else 1 / 2.54           # cm -> output units
    doc = ezdxf.new("R12")
    doc.header["$MEASUREMENT"] = 1 if units == "mm" else 0
    for name, color in ((LAYER_CUT, 7), (LAYER_NOTCH, 3), (LAYER_GRAIN, 5), (LAYER_INTERNAL, 6),
                        (LAYER_DRILL, 4), (LAYER_SEW, 1)):
        doc.layers.add(name, color=color)
    msp = doc.modelspace()
    geoms = {g["name"]: g for g in _piece_geoms(panels, seams, sa_cm)}
    x_cursor = 0.0
    for p in panels:
        g = geoms[p.name]
        cut = np.asarray(cut_polygon(p, sa_cm).exterior.coords)
        lo = cut.min(0)
        T = lambda P: [(float(x), float(y)) for x, y in (np.asarray(P, float) - lo) * k]
        bname = f"{p.name}"
        blk = doc.blocks.new(name=bname)
        blk.add_polyline2d(T(cut), close=True, dxfattribs={"layer": LAYER_CUT})
        stitch = np.asarray(g["stitch"])
        blk.add_polyline2d(T(stitch), close=True, dxfattribs={"layer": LAYER_SEW})
        for a, b in g["notches"]:
            blk.add_line(*T([a, b]), dxfattribs={"layer": LAYER_NOTCH})
        (x0, y0), (x1, y1) = g["grain"]
        blk.add_line(*T([(x0, y0), (x1, y1)]), dxfattribs={"layer": LAYER_GRAIN})
        for mk in marks_cm(p):
            P = mk["pts"]
            if mk["kind"] in ("button", "snap"):
                c = P.mean(0)
                blk.add_point(T([c])[0], dxfattribs={"layer": LAYER_DRILL})
            else:
                blk.add_polyline2d(T(P), dxfattribs={"layer": LAYER_INTERNAL})
        cx, cy = (np.asarray(g["label"]) - lo) * k
        h = 4.0 * (k / 10)
        q = (quantities or {}).get(p.name, 1)
        for i, t in enumerate([f"Piece Name: {p.name}", f"Size: {size}", f"Quantity: {q}",
                               f"Category: {category}", f"Annotation: {style}",
                               f"Rule Table: none" ]):
            blk.add_text(t, dxfattribs={"layer": LAYER_INTERNAL, "height": h, "insert": (cx, cy - i * h * 1.6)})
        msp.add_blockref(bname, (x_cursor, 0))
        x_cursor += (cut[:, 0].max() - lo[0]) * k + 20 * (k / 10)
    # file-level annotation (AAMA readers show it as style info)
    msp.add_text(f"Style Name: {style}", dxfattribs={"height": 5 * (k / 10), "insert": (0, -20 * (k / 10)), "layer": "0"})
    msp.add_text(f"Creation Date: {datetime.date.today().isoformat()}", dxfattribs={"height": 5 * (k / 10),
                                                                                    "insert": (0, -30 * (k / 10)), "layer": "0"})
    msp.add_text("Author: Spunfection Studio (AAMA export)", dxfattribs={"height": 5 * (k / 10), "insert": (0, -40 * (k / 10)), "layer": "0"})
    msp.add_text(f"Sample Size: {sample_size or size}", dxfattribs={"height": 5 * (k / 10), "insert": (0, -50 * (k / 10)), "layer": "0"})
    msp.add_text(f"Units: {'METRIC' if units == 'mm' else 'ENGLISH'}", dxfattribs={"height": 5 * (k / 10),
                                                                                    "insert": (0, -60 * (k / 10)), "layer": "0"})
    doc.saveas(str(path))
    return {"pieces": len(panels), "units": units}
