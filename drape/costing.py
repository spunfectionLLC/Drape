"""Cut list, materials and cost of making a garment, and an Etsy price.

Materials come from the pattern itself: fabric per fabric type (laid out
on the chosen width), interfacing area, elastic length, thread (seam
lengths x thread used per cm of stitching). Sewing time is a rough
home-sewist estimate (cutting per piece, minutes per metre of seam and
of hem). Etsy fees (US, 2026): $0.20 listing, 6.5% transaction on the
order total, 3% + $0.25 payment processing; Offsite Ads 12-15% on the
sales they bring in.
"""
from __future__ import annotations

import numpy as np

from .layout import YARD_CM, buy_amount, layout_pieces
from .pattern import polyline_length

ETSY = {"listing": 0.20, "transaction": 0.065, "processing_pct": 0.03, "processing_fixed": 0.25}


def materials(g, fabric_width_cm=150.0, sa_cm=1.5, main_fabric="main"):
    P = g.meta["panels"]
    keys = g.meta.get("panel_fabric_keys") or [(None, None)] * len(P)
    groups = {}
    for p, (f, i) in zip(P, keys):
        groups.setdefault(f or main_fabric, []).append(p)
    fabrics = []
    for f, ps in groups.items():
        lay = layout_pieces(ps, fabric_width_cm, sa_cm)
        b = buy_amount(lay["length_cm"])
        fabrics.append({"fabric": f, "pieces": [p.name for p in ps], "length_cm": round(lay["length_cm"], 1),
                        "yards": float(b["yards"]), "metres": float(b["metres"])})
    inter = {}
    for p, (f, i) in zip(P, keys):
        if i:
            from shapely.geometry import Polygon
            from .closures import cut_polygon
            a = cut_polygon(p, sa_cm).area
            inter[i] = inter.get(i, 0.0) + a
    seams = g.meta["seam_defs"]
    pmap = {p.name: p for p in P}
    seam_len = sum(polyline_length(pmap[s.panel_a].edge(s.edge_a)) for s in seams) * 100
    seamed = {(s.panel_a, s.edge_a) for s in seams} | {(s.panel_b, s.edge_b) for s in seams}
    free_len = sum(polyline_length(e) for p in P for n, e in p.edges if (p.name, n) not in seamed) * 100
    elastic = sum(e["elastic_cm"] + 2 for e in g.meta.get("elastic", []))
    top = sum(1 for t in g.meta.get("topstitched", []))
    thread_m = (seam_len * 2.5 + free_len * 2.5 + 200) / 100      # lockstitch ~2.5x, plus waste
    # a home sewist: cutting, then per seam, per metre of seam and of hem, pockets, pressing
    minutes = 2 * len(P) + 2 * len(seams) + 6 * seam_len / 100 + 8 * free_len / 100 + 4 * top + 10
    cut_list = [{"piece": p.name, "fabric": (f or main_fabric), "interfacing": i, "cut": 1}
                for p, (f, i) in zip(P, keys)]
    from .closures import notions as _notions
    notions = _notions(g)
    for n in notions:   # buttonholes and buttons, zippers take time too
        minutes += {"buttons": 4 * n["qty"], "snaps": 3 * n["qty"], "zipper": 20, "hook_loop": 8}.get(n["type"], 0)
    return {"fabrics": fabrics, "interfacing_cm2": {k: round(v) for k, v in inter.items()},
            "elastic_cm": round(elastic, 1), "thread_m": round(thread_m), "seam_cm": round(seam_len),
            "hem_cm": round(free_len), "pieces": len(P), "seams": len(seams), "minutes": round(minutes),
            "cut_list": cut_list, "notions": notions}


def price(cost, profit=0.0, offsite_ads=0.0, shipping_charged=0.0):
    """Etsy price so that after fees you keep cost + profit."""
    pct = ETSY["transaction"] + ETSY["processing_pct"] + offsite_ads
    fixed = ETSY["listing"] + ETSY["processing_fixed"]
    p = (cost + profit + fixed) / (1 - pct) - shipping_charged * 1.0
    fees = (p + shipping_charged) * pct + fixed
    return {"price": round(p, 2), "fees": round(fees, 2)}
