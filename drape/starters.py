"""Starter designs: ready-to-wear garments built from the pattern library and
finished the way real ones are (bands, collars, pockets, buttons, zippers),
sized from the avatar. Each opens as an editable from-scratch design.

    from drape.starters import STARTERS, starter
    d = starter("jeans", body, m)          # editor-format design (cm)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from . import dedit as E
from .blocks import body_measures, preset_values
from . import features


def _band(d, kind, loop, **kw):
    """A band round an opening, if this build has them (features.OPENING_BANDS). Off, the
    opening is left as cut, except that an elastic waistband becomes elastic in the
    edges themselves (a casing), so the garment still stays up."""
    if features.on("OPENING_BANDS"):
        return E.add_band(d, kind, loop, **kw)
    if kw.get("elastic"):
        for ref in loop:
            pn, en = ref.split(".", 1)
            pc = E.piece(d, pn)
            pc["edges"][E.eidx(pc, en)]["elastic"] = True
    return None


@dataclass
class Starter:
    key: str
    label: str
    category: str
    build: Callable
    blurb: str
    fabric: str = "poplin"
    icon: str = "tee"
    level: str = "Beginner"


def _T(block, body, m, bm, _set=None, **choices):
    """A block drafted with plain-language choices; _set: drafting values on top (cm, or a function of bm)."""
    from .freeform import template_design
    v = preset_values(block, choices, bm)
    v.update({k: round(float(x(bm) if callable(x) else x), 1) for k, x in (_set or {}).items()})
    return template_design(block, body, m, v)


def _box(d, pn):
    V = np.vstack([P for _, P in E.outline(E.piece(d, pn))])
    return V.min(0), V.max(0)


def _holes(bm):
    return "left" if bm.get("sex") == "male" else "right"


def _mid_y(d, ref):
    P = E.epts(d, ref)
    return float(P[:, 1].mean()), float(P[:, 0].mean())


# ------------------------------------------------------------------ tops --
def _tee(body, m, bm, **ch):
    d = _T("tee", body, m, bm, **ch)
    _band(d, "neckband", ["front.neck", "back.neck"])
    return d


def classic_tee(body, m, bm):
    return _tee(body, m, bm)


def crop_tee(body, m, bm):
    return _tee(body, m, bm, Fit="Relaxed", Length="Cropped")


def oversized_tee(body, m, bm):
    return _tee(body, m, bm, Fit="Oversized", Length="Long", Sleeves="Elbow")


def pocket_tee(body, m, bm):
    d = _tee(body, m, bm, Fit="Relaxed")
    lo, hi = _box(d, "front")
    E.add_patch_pocket(d, "front", 11, 12, (lo[0] + 0.68 * (hi[0] - lo[0]), hi[1] - 22), name="chest_pocket")
    return d


def sleeveless_tee(body, m, bm):
    d = _tee(body, m, bm, Fit="Relaxed", Sleeves="Cap")
    d["pieces"] = [p for p in d["pieces"] if not p["name"].startswith("sleeve")]
    d["seams"] = [s for s in d["seams"] if "sleeve" not in s["a"] and "sleeve" not in s["b"]]
    return d


def long_sleeve_tee(body, m, bm):
    d = _T("long_sleeve", body, m, bm, Fit="Regular", Cuffs="Fitted")
    _band(d, "neckband", ["front.neck", "back.neck"])
    for s in ("sleeve_r", "sleeve_l"):
        _band(d, "cuff", [f"{s}.hem"], h=6, name="cuff")
    return d


def henley(body, m, bm):
    d = _T("long_sleeve", body, m, bm, Fit="Regular", Cuffs="Fitted")
    lo, hi = E.cut_vertical(d, "front")
    d["seams"].append({"a": f"{lo}.cf", "b": f"{hi}.cf", "ease": 0})
    E.partial_closure(d, f"{lo}.cf", 15, "buttons", count=3, size_mm=11)
    _band(d, "neckband", [f"{lo}.neck", "back.neck", f"{hi}.neck"])
    return d


def hoodie(body, m, bm, zip_front=False):
    d = _T("long_sleeve", body, m, bm, Fit="Relaxed", Length="Hip", Cuffs="Regular")   # was Fitted: caught on the hand
    if zip_front:
        lo, hi = E.cut_vertical(d, "front")
        E.closure_seam(d, f"{lo}.cf", f"{hi}.cf", "zipper")
        E.add_hood(d, [f"{lo}.neck", "back.neck", f"{hi}.neck"])
        for k, h in ((lo, -1), (hi, 1)):
            b0, b1 = _box(d, k)
            E.add_patch_pocket(d, k, 17, 19, ((b0[0] + b1[0]) / 2 + h * 2, b0[1] + 14), name="pocket",
                               sewn=["bottom", "top", "left" if h > 0 else "right"])
        hem = [f"{lo}.hem", "back.hem", f"{hi}.hem"]
    else:
        E.add_hood(d, ["front.neck", "back.neck"])
        b0, b1 = _box(d, "front")
        E.add_patch_pocket(d, "front", 36, 20, ((b0[0] + b1[0]) / 2, b0[1] + 15), name="kangaroo",
                           sewn=["bottom", "top"])
        hem = ["front.hem", "back.hem"]
    for s in ("sleeve_r", "sleeve_l"):
        _band(d, "cuff", [f"{s}.hem"], name="cuff")
    _band(d, "hemband", hem, h=7)
    if zip_front:   # the hem band opens with the zipper
        d["seams"] = [s for s in d["seams"] if {s["a"], s["b"]} != {"hemband.end_r", "hemband.end_l"}]
    return d


def zip_hoodie(body, m, bm):
    return hoodie(body, m, bm, zip_front=True)


def scrub_top(body, m, bm):
    d = _T("tee", body, m, bm, Fit="Relaxed", Length="Long", Neckline="Deep scoop")
    b0, b1 = _box(d, "front")
    w = b1[0] - b0[0]
    for x, nm in ((-0.25, "pocket"), (0.25, "pocket")):
        E.add_patch_pocket(d, "front", 16, 17, ((b0[0] + b1[0]) / 2 + x * w, b0[1] + 15), name=nm)
    E.add_patch_pocket(d, "front", 10, 12, (b0[0] + 0.7 * w, b1[1] - 24), name="pen_pocket")
    return d


# ------------------------------------------------------- shirts & jackets --
def _shirt(body, m, bm, block="long_sleeve", fabric_cuffs=True, collar_h=4, **ch):
    d = _T(block, body, m, bm, **ch)
    lo, hi = E.open_down_middle(d, "front", "buttons", holes=_holes(bm))
    _band(d, "collar", [f"{lo}.neck", "back.neck", f"{hi}.neck"], h=collar_h)
    # the collar opens at the front too: one button at its ends
    for s in d["seams"]:
        if {s["a"], s["b"]} == {"collar.end_r", "collar.end_l"}:
            s["closure"] = {"type": "buttons", "count": 1, "size_mm": 10, "open": 1.0}
    return d, lo, hi


def button_up(body, m, bm):
    d, lo, hi = _shirt(body, m, bm, Fit="Regular", Length="Long", Cuffs="Regular")
    b0, b1 = _box(d, hi if _holes(bm) == "right" else lo)
    E.add_patch_pocket(d, hi, 11, 13, ((b0[0] + b1[0]) / 2, b1[1] - 27), name="chest_pocket", rounded=True)
    for s in ("sleeve_r", "sleeve_l"):
        _band(d, "cuff", [f"{s}.hem"], h=6, ratio=1.0, name="cuff", fabric="poplin", interfacing="light")
    return d


def camp_shirt(body, m, bm):
    d, lo, hi = _shirt(body, m, bm, block="tee", Fit="Relaxed", Length="Hip", Sleeves="Short")
    b0, b1 = _box(d, hi)
    E.add_patch_pocket(d, hi, 11, 12, ((b0[0] + b1[0]) / 2, b1[1] - 27), name="chest_pocket")
    return d


def sleep_shirt(body, m, bm):
    d, lo, hi = _shirt(body, m, bm, block="tee", Fit="Relaxed", Length="Tunic", Sleeves="Short")
    return d


def chore_jacket(body, m, bm):
    d, lo, hi = _shirt(body, m, bm, Fit="Relaxed", Length="Long", Cuffs="Loose", collar_h=6)
    for k in (lo, hi):
        b0, b1 = _box(d, k)
        E.add_patch_pocket(d, k, 17, 18, ((b0[0] + b1[0]) / 2, b0[1] + 16), name="pocket")
    b0, b1 = _box(d, hi)
    E.add_patch_pocket(d, hi, 12, 13, ((b0[0] + b1[0]) / 2, b1[1] - 27), name="chest_pocket")
    for p in d["pieces"]:          # a jacket goes over a top
        (p.get("place") or {})["layer"] = 1
    return d


def cardigan(body, m, bm):
    d = _T("long_sleeve", body, m, bm, Fit="Relaxed", Length="Long", Cuffs="Fitted")
    lo, hi = E.open_down_middle(d, "front", "buttons", holes=_holes(bm), size_mm=18)
    for s in ("sleeve_r", "sleeve_l"):
        _band(d, "cuff", [f"{s}.hem"], name="cuff")
    _band(d, "hemband", [f"{lo}.hem", "back.hem", f"{hi}.hem"], h=6)
    d["seams"] = [s for s in d["seams"] if {s["a"], s["b"]} != {"hemband.end_r", "hemband.end_l"}]
    for k in (lo, hi):
        b0, b1 = _box(d, k)
        E.add_patch_pocket(d, k, 15, 15, ((b0[0] + b1[0]) / 2, b0[1] + 14), name="pocket")
    for p in d["pieces"]:
        (p.get("place") or {})["layer"] = 1
    return d


def zip_jacket(body, m, bm):
    d = _T("long_sleeve", body, m, bm, Fit="Relaxed", Length="Hip", Cuffs="Fitted")
    lo, hi = E.cut_vertical(d, "front")
    E.closure_seam(d, f"{lo}.cf", f"{hi}.cf", "zipper")
    _band(d, "collar", [f"{lo}.neck", "back.neck", f"{hi}.neck"], h=7, fabric="rib")
    d["seams"] = [s for s in d["seams"] if {s["a"], s["b"]} != {"collar.end_r", "collar.end_l"}]
    for s in ("sleeve_r", "sleeve_l"):
        _band(d, "cuff", [f"{s}.hem"], name="cuff")
    _band(d, "hemband", [f"{lo}.hem", "back.hem", f"{hi}.hem"], h=7)
    d["seams"] = [s for s in d["seams"] if {s["a"], s["b"]} != {"hemband.end_r", "hemband.end_l"}]
    for p in d["pieces"]:
        (p.get("place") or {})["layer"] = 1
    return d


# --------------------------------------------------------------- bottoms --
def _waistband(d, loop, button=True, elastic=False, h=4):
    _band(d, "waistband", loop, h=h, elastic=elastic)
    if button:
        for s in d["seams"]:
            if {s["a"], s["b"]} == {"waistband.end_r", "waistband.end_l"}:
                s["closure"] = {"type": "buttons", "count": 1, "size_mm": 17, "open": 0.0}


def _back_pockets(d, w=14, h=15):
    for k in ("back_r", "back_l"):
        y, x = _mid_y(d, f"{k}.waist")
        E.add_patch_pocket(d, k, w, h, (x, y - 8 - h / 2), name="back_pocket")


def jeans(body, m, bm):
    d = _T("trousers", body, m, bm, Fit="Slim", Length="Full", Rise="Mid")
    E.add_hip_pocket(d, "front_r", across_cm=10, down_cm=15)
    E.add_hip_pocket(d, "front_l", across_cm=10, down_cm=15)
    E.add_zipper(d, "front_r.centre", 18)
    _back_pockets(d)
    _waistband(d, ["front_l.waist", "front_l_yoke.waist", "back_l.waist", "back_r.waist",
                   "front_r_yoke.waist", "front_r.waist"])
    return d


def chinos(body, m, bm):
    d = _T("trousers", body, m, bm, Fit="Regular", Length="Full", Rise="Mid")
    E.add_hip_pocket(d, "front_r", across_cm=8, down_cm=17)
    E.add_hip_pocket(d, "front_l", across_cm=8, down_cm=17)
    E.add_zipper(d, "front_r.centre", 18)
    _waistband(d, ["front_l.waist", "front_l_yoke.waist", "back_l.waist", "back_r.waist",
                   "front_r_yoke.waist", "front_r.waist"])
    return d


def _elastic_pants(d, pockets=True, cuffs=False):
    if pockets:
        for k in ("front_r", "front_l"):
            E.add_inseam_pocket(d, f"{k}.outseam", from_top_cm=7, opening_cm=15)
    _band(d, "waistband", ["front_l.waist", "back_l.waist", "back_r.waist", "front_r.waist"],
               h=5, elastic=True)
    if cuffs:
        for k in ("r", "l"):
            _band(d, "cuff", [f"front_{k}.hem", f"back_{k}.hem"], h=8, name="cuff")
    return d


def joggers(body, m, bm):
    d = _T("trousers", body, m, bm, Fit="Regular", Length="Ankle", Rise="Mid")
    return _elastic_pants(d, cuffs=True)


def pajama_pants(body, m, bm):
    d = _T("trousers", body, m, bm, Fit="Wide leg", Length="Full", Rise="High")
    return _elastic_pants(d, pockets=False)


def shorts(body, m, bm):
    d = _T("trousers", body, m, bm, Fit="Regular", Length="Shorts", Rise="Mid")
    return _elastic_pants(d)


def scrub_pants(body, m, bm):
    d = _T("trousers", body, m, bm, Fit="Regular", Length="Full", Rise="Mid")
    _elastic_pants(d)
    b0, b1 = _box(d, "front_r")
    E.add_patch_pocket(d, "front_r", 15, 17, (b0[0] + 9, (b0[1] + b1[1]) * 0.55), name="cargo_pocket")
    _back_pockets(d, 13, 14)
    return d


# ---------------------------------------------------------------- skirts --
def a_line_pockets(body, m, bm):
    d = _T("a_line_skirt", body, m, bm, Fit="Regular", Length="Knee")
    E.add_inseam_pocket(d, "front.side_r", from_top_cm=7)
    E.add_inseam_pocket(d, "front.side_l", from_top_cm=7)
    lo, hi = E.cut_vertical(d, "back")
    d["seams"].append({"a": f"{lo}.cf", "b": f"{hi}.cf", "ease": 0})
    E.add_zipper(d, f"{lo}.cf", 18)
    _waistband(d, [f"{lo}.waist", "front.waist", f"{hi}.waist"], button=False)
    _fix_waistband_ring_to_back(d)
    return d


def _fix_waistband_ring_to_back(d):
    """A skirt's waistband opens over the back zipper: hook & eye there."""
    for s in d["seams"]:
        if {s["a"], s["b"]} == {"waistband.end_r", "waistband.end_l"}:
            s["closure"] = {"type": "snaps", "count": 1, "size_mm": 10, "open": 0.0}


def pencil_zip(body, m, bm):
    # 2 cm more at the hip and 1 cm at the waist than Regular: in denim (no stretch) Regular pulled
    d = _T("pencil_skirt", body, m, bm, Fit="Regular", Length="Knee", Shape="Pencil", _set={"hip_ease": 6, "waist_ease": 3})
    lo, hi = E.cut_vertical(d, "back")
    d["seams"].append({"a": f"{lo}.cf", "b": f"{hi}.cf", "ease": 0})
    E.add_zipper(d, f"{lo}.cf", 18)
    return d


def button_skirt(body, m, bm):
    d = _T("a_line_skirt", body, m, bm, Fit="Regular", Length="Midi")
    lo, hi = E.open_down_middle(d, "front", "buttons", holes=_holes(bm), size_mm=18)
    _waistband(d, [f"{hi}.waist", "back.waist", f"{lo}.waist"])
    for k in (lo, hi):
        b0, b1 = _box(d, k)
        E.add_patch_pocket(d, k, 13, 14, ((b0[0] + b1[0]) / 2, b1[1] - 22), name="pocket")
    return d


def gathered_skirt(body, m, bm):
    L = round(0.36 * bm["height"])
    W = round(bm["hip"] * 0.85)
    d = {"pieces": [], "seams": []}
    for nm, lm in (("front", "waist_front"), ("back", "waist_back")):
        pc = E.rect(nm, W, L)
        pc["edges"][0]["name"], pc["edges"][1]["name"], pc["edges"][2]["name"], pc["edges"][3]["name"] = \
            "hem", "side_r", "waist", "side_l"
        pc["edges"][2]["elastic"] = True
        pc["place"] = {"landmark": lm, "at": "top", "mode": "wrap", "rotate": 0, "offset_cm": 2}
        pc["role"] = "body"
        d["pieces"].append(pc)
    d["seams"] = [{"a": "front.side_r", "b": "back.side_l", "ease": 0}, {"a": "front.side_l", "b": "back.side_r", "ease": 0}]
    E.add_inseam_pocket(d, "front.side_r", from_top_cm=6)
    E.add_inseam_pocket(d, "front.side_l", from_top_cm=6)
    return d


# --------------------------------------------------------------- dresses --
def shift_zip(body, m, bm):
    d = _T("shift_dress", body, m, bm, Fit="Regular", Length="Knee", Shape="A-line", Neckline="Scoop")
    lo, hi = E.cut_vertical(d, "back")
    d["seams"].append({"a": f"{lo}.cf", "b": f"{hi}.cf", "ease": 0})
    E.add_zipper(d, f"{lo}.cf", 45)
    return d


def _low_side(d, pn, side):
    """The lowest sewn side-seam edge of a piece on one side ('r' or 'l')."""
    pc = E.piece(d, pn)
    best = None
    for i, e in enumerate(pc["edges"]):
        n = e["name"]
        if n.startswith("side") and n.endswith("_" + side) and E.seam_of(d, f"{pn}.{n}")[0] is not None:
            y = float(E.edge_pts(pc, i)[:, 1].mean())
            if best is None or y < best[0]:
                best = (y, n)
    if best is None:
        raise ValueError(f"no side seam on {pn}")
    return f"{pn}.{best[1]}"


def shift_pockets(body, m, bm):
    d = _T("shift_dress", body, m, bm, Fit="Relaxed", Length="Midi", Shape="Swing", Neckline="Scoop")
    for side in ("r", "l"):     # 3 cm under the waist, on the part of the side seam at the hips
        E.add_inseam_pocket(d, _low_side(d, "front", side), body=body, below_waist_cm=3)
    return d


def shirt_dress(body, m, bm):
    d = _T("shift_dress", body, m, bm, Fit="Relaxed", Length="Knee", Shape="A-line", Neckline="High")
    lo, hi = E.open_down_middle(d, "front", "buttons", holes=_holes(bm))
    _band(d, "collar", [f"{lo}.neck", "back.neck", f"{hi}.neck"], h=4)
    for s in d["seams"]:
        if {s["a"], s["b"]} == {"collar.end_r", "collar.end_l"}:
            s["closure"] = {"type": "buttons", "count": 1, "size_mm": 10, "open": 1.0}
    for k in (lo, hi):
        sides = [e["name"][-1] for e in E.piece(d, k)["edges"] if e["name"].startswith("side")]
        E.add_inseam_pocket(d, _low_side(d, k, sides[0]), body=body, below_waist_cm=3)
    return d


def tee_dress(body, m, bm):
    return _tee(body, m, bm, Fit="Relaxed", Length="Tunic", Sleeves="Short")


def _glove(style):
    def build(body, m, bm):
        from .gloves import glove_design
        return glove_design(body, m, style)
    return build


STARTERS = {s.key: s for s in [
    Starter("classic_tee", "Classic tee", "Tops", classic_tee, "Crew neck with a rib neckband.", "jersey", "tee"),
    Starter("crop_tee", "Cropped tee", "Tops", crop_tee, "Boxy and short.", "jersey", "tee"),
    Starter("oversized_tee", "Oversized tee", "Tops", oversized_tee, "Dropped, roomy, elbow sleeves.", "jersey", "tee"),
    Starter("pocket_tee", "Pocket tee", "Tops", pocket_tee, "Relaxed tee with a chest pocket.", "jersey", "tee"),
    Starter("sleeveless_tee", "Sleeveless top", "Tops", sleeveless_tee, "A tee with the sleeves left off.", "jersey", "tank"),
    Starter("long_sleeve_tee", "Long-sleeve tee", "Tops", long_sleeve_tee, "Neckband and rib cuffs.", "jersey", "long_sleeve"),
    Starter("henley", "Henley", "Tops", henley, "Three-button placket at the neck.", "jersey", "long_sleeve", "Intermediate"),
    Starter("scrub_top", "Scrub top", "Workwear", scrub_top, "Deep neck, two hip pockets and a pen pocket.", "poplin", "tee"),
    Starter("scrub_pants", "Scrub pants", "Workwear", scrub_pants, "Elastic waist, side pockets, cargo pocket.", "poplin", "trousers"),
    Starter("hoodie", "Hoodie", "Loungewear", hoodie, "Hood, kangaroo pocket, rib cuffs and hem.", "fleece", "hoodie"),
    Starter("zip_hoodie", "Zip hoodie", "Loungewear", zip_hoodie, "Full-length zipper, two pockets.", "fleece", "hoodie", "Intermediate"),
    Starter("joggers", "Joggers", "Loungewear", joggers, "Elastic waistband, side pockets, rib cuffs.", "fleece", "trousers"),
    Starter("pajama_pants", "Pajama pants", "Loungewear", pajama_pants, "Wide legs, elastic waist. The easiest pants.", "flannel", "trousers"),
    Starter("sleep_shirt", "Sleep shirt", "Loungewear", sleep_shirt, "Long button-front sleep shirt.", "flannel", "shirt"),
    Starter("button_up", "Button-up shirt", "Shirts & jackets", button_up, "Collar, button front, cuffs, chest pocket.", "poplin", "shirt", "Intermediate"),
    Starter("camp_shirt", "Camp shirt", "Shirts & jackets", camp_shirt, "Short-sleeve button front with a pocket.", "poplin", "shirt"),
    Starter("chore_jacket", "Chore jacket", "Shirts & jackets", chore_jacket, "Worn over a top: three patch pockets.", "canvas", "shirt", "Intermediate"),
    Starter("cardigan", "Cardigan", "Shirts & jackets", cardigan, "Button front, rib hem and cuffs, pockets.", "jersey", "shirt"),
    Starter("zip_jacket", "Zip jacket", "Shirts & jackets", zip_jacket, "Bomber-style: zip front, rib collar and cuffs.", "poplin", "hoodie", "Intermediate"),
    Starter("jeans", "Jeans", "Pants & shorts", jeans, "Front hip pockets, fly zipper, waistband, back pockets.", "denim", "trousers", "Advanced"),
    Starter("chinos", "Chinos", "Pants & shorts", chinos, "Slant pockets, fly zipper, waistband.", "poplin", "trousers", "Intermediate"),
    Starter("shorts", "Pull-on shorts", "Pants & shorts", shorts, "Elastic waist and in-seam pockets.", "poplin", "shorts"),
    Starter("a_line_pockets", "A-line skirt with pockets", "Skirts", a_line_pockets, "Hidden side pockets, back zipper, waistband.", "poplin", "a_line_skirt", "Intermediate"),
    Starter("pencil_zip", "Pencil skirt", "Skirts", pencil_zip, "Darted, with a back zipper.", "denim", "pencil_skirt", "Intermediate"),
    Starter("button_skirt", "Button-front skirt", "Skirts", button_skirt, "Midi length, buttons down the front, pockets.", "denim", "a_line_skirt"),
    Starter("gathered_skirt", "Gathered skirt", "Skirts", gathered_skirt, "Two rectangles, elastic waist, side pockets.", "poplin", "gathered"),
    Starter("shift_zip", "Shift dress", "Dresses", shift_zip, "Back zipper, scoop neck, A-line.", "poplin", "shift_dress", "Intermediate"),
    Starter("shift_pockets", "Swing dress with pockets", "Dresses", shift_pockets, "Pulls on, swings out, hides pockets.", "jersey", "shift_dress"),
    Starter("shirt_dress", "Shirt dress", "Dresses", shirt_dress, "Collar, buttons all the way, pockets.", "poplin", "shift_dress", "Advanced"),
    Starter("tee_dress", "T-shirt dress", "Dresses", tee_dress, "A long, relaxed tee.", "jersey", "tee"),
    Starter("knit_gloves", "Gloves", "Accessories", _glove("gloves"), "Five fingers, sewn round in two layers. Cut from a stretch knit.", "jersey", "glove", "Intermediate"),
    Starter("mittens", "Mittens", "Accessories", _glove("mittens"), "A thumb and a mitt, with room to curl your fingers.", "fleece", "mitten"),
    Starter("fingerless_gloves", "Fingerless gloves", "Accessories", _glove("fingerless"), "Open finger ends and thumb, for working hands.", "rib", "fingerless", "Intermediate"),
    Starter("opera_gloves", "Long gloves", "Accessories", _glove("long_gloves"), "Evening length, up the forearm.", "jersey", "glove", "Advanced"),
]}


def starter(key, body, m):
    """An editable design for this avatar (studio editor format)."""
    s = STARTERS[key]
    bm = body_measures(body, m)
    d = s.build(body, m, bm)
    d["from_starter"] = key
    d["suggest_fabric"] = s.fabric
    return d
