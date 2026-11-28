"""Pattern library: ready-made blocks drafted from the avatar's own
measurements, each with editable parameters (the studio shows these as
sliders). Every block is trued by construction (seam check passes) so it's a
clean baseline to work from.

    from drape.blocks import BLOCKS, draft_block
    g, info = draft_block("trousers", body, measurements, {"hip_ease": 8})

Blocks: tee, long_sleeve, a_line_skirt, pencil_skirt, shift_dress, trousers
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from . import draft as D
from .garments import _placement_for, a_line_skirt_for, tshirt_for, waist_placement
from .pattern import Panel, Seam, build_garment, cylinder_wrap


# ------------------------------------------------------------ parameters --
@dataclass
class Param:
    name: str
    label: str
    default: Callable[[dict], float] | float
    lo: float
    hi: float
    step: float = 0.5
    unit: str = "cm"
    group: str = "Fit"
    help: str = ""

    def value_for(self, bm):
        return float(self.default(bm) if callable(self.default) else self.default)


@dataclass
class Block:
    key: str
    label: str
    category: str
    params: list
    draft: Callable
    description: str = ""
    sexes: tuple = ("female", "male")

    def defaults(self, bm):
        return {p.name: round(p.value_for(bm), 1) for p in self.params}


# ---------------------------------------------------- avatar measurements --
def body_measures(body, m=None) -> dict:
    """Everything the blocks need, in cm, read from the avatar when it is a
    realistic mesh body (so patterns fit the body you see), otherwise from
    the measurements with standard proportions."""
    if getattr(body, "kind", "") == "mesh":
        # the tapes depend only on the mesh: measured once per avatar, not on every draft
        tapes = body.__dict__.get("_tapes")
        if tapes is None:
            tapes = body.__dict__["_tapes"] = _mesh_tapes(body)
        return dict(tapes, sex=getattr(m, "sex", "female") if m is not None else "female")
    H = m.height
    return dict(height=H, chest=m.chest, underbust=m.underbust or m.chest * 0.85, waist=m.waist, hip=m.hip,
                neck=m.neck, upper_arm=m.upper_arm, shoulder_width=m.shoulder_width, arm_length=m.arm_length,
                thigh=m.thigh or 0.6 * m.hip, knee=0.21 * H, ankle=0.13 * H, wrist=0.095 * H,
                crotch_height=0.47 * H, waist_height=0.604 * H, hip_height=0.505 * H, chest_height=0.741 * H,
                sex=m.sex)


def _mesh_tapes(body):
    T = body.tape
    L = T.lines()
    H = body.height()
    return dict(
        height=H * 100, chest=T.chest() * 100, underbust=T.underbust() * 100, waist=T.waist() * 100,
        hip=T.hip() * 100, neck=T.neck() * 100, upper_arm=T.upper_arm() * 100,
        shoulder_width=T.shoulder_width() * 100, arm_length=T.arm_length() * 100,
        thigh=T.thigh() * 100, knee=T.knee() * 100, ankle=T.ankle() * 100,
        wrist=0.095 * H * 100, crotch_height=T.crotch_height() * 100,
        waist_height=L["waist"] * 100, hip_height=L["hip"] * 100, chest_height=L["chest"] * 100)


cm = 0.01


# ================================================================== tops ===
def _tee_draft(v, bm, body, m, long=False):
    kw = dict(neck_u=bm["neck"] * cm / (2 * np.pi) * v["neck_width"] / 100 * 1.45,
              front_neck_drop=v["front_neck_drop"] * cm,
              sleeve_underarm=v["sleeve_length"] * cm)
    if long or v.get("cuff_ease") is not None and "cuff_ease" in v:
        kw["sleeve_hem_half_width"] = (bm["wrist"] + v["cuff_ease"]) / 2 * cm
    return tshirt_for(m, chest_ease_cm=v["chest_ease"], sleeve_ease_cm=v["sleeve_ease"],
                      length_cm=v["length"], body=body, armhole_clearance_cm=v["armhole_clearance"], **kw)


TOP_PARAMS = [
    Param("chest_ease", "Chest ease", 12, 0, 40, 0.5, help="garment chest minus body chest"),
    Param("length", "Length (neck point to hem)", lambda b: 0.38 * b["height"], 40, 110, 1, group="Lengths"),
    Param("sleeve_ease", "Sleeve ease (upper arm)", 8, 2, 25, 0.5),
    Param("armhole_clearance", "Armhole depth below armpit", 6, 2, 12, 0.5, group="Armhole & neck"),
    Param("neck_width", "Neck width", 100, 80, 140, 1, unit="%", group="Armhole & neck"),
    Param("front_neck_drop", "Front neck depth", lambda b: 7.5 * b["height"] / 175, 2, 25, 0.5,
          group="Armhole & neck"),
]

TEE = Block("tee", "T-shirt", "Shirts",
            TOP_PARAMS + [Param("sleeve_length", "Sleeve length (underarm seam)", lambda b: 12 * b["height"] / 175,
                                3, 30, 0.5, group="Lengths")],
            lambda v, bm, body, m: _tee_draft(v, bm, body, m),
            "Set-in sleeve tee: front, back, two sleeves.")

LONG_SLEEVE = Block("long_sleeve", "Long-sleeve shirt", "Shirts",
                    TOP_PARAMS + [
                        Param("sleeve_length", "Sleeve length (underarm seam)", lambda b: b["arm_length"] - 11, 30, 75, 0.5,
                              group="Lengths"),
                        Param("cuff_ease", "Cuff ease (over wrist)", 7, 2, 20, 0.5)],
                    lambda v, bm, body, m: _tee_draft(v, bm, body, m, long=True),
                    "Tee block with full-length tapered sleeves.")


# ================================================================ skirts ===
A_LINE = Block("a_line_skirt", "A-line skirt", "Skirts", [
    Param("waist_ease", "Waist ease", 2, 0, 10, 0.5),
    Param("hip_ease", "Hip ease", 5, 1, 20, 0.5),
    Param("length", "Length (waist to hem)", lambda b: 0.33 * b["height"], 30, 110, 1, group="Lengths"),
], lambda v, bm, body, m: a_line_skirt_for(
    _with(m, waist=bm["waist"], hip=bm["hip"]), body=body, waist_ease_cm=v["waist_ease"],
    hip_ease_cm=v["hip_ease"], length_cm=v["length"]),
    "Two-piece flared skirt, waist and hem arcs: trued by construction.")


def _with(m, **kw):
    from dataclasses import replace
    return replace(m, **kw)


def _trued_dart(edges, edge, at, width, depth, name):
    """add_dart, then re-curve the edge on each side of the dart so it meets
    the legs at 90 deg (the folded dart then makes a straight edge: the
    junction sums to 180)."""
    edges, (la, lb) = D.add_dart(edges, edge, at=at, width=width, depth=depth, name=name)
    d = dict(edges)
    names = [n for n, _ in edges]
    da = D.tangent_at(d[la], frac=0.0)               # opening -> apex
    db = D.tangent_at(d[lb], frac=1.0)               # apex -> opening
    rot = lambda v, s: np.array([-v[1], v[0]]) * s   # +90 (s=1) or -90 (s=-1)
    e1, e2 = d[f"{edge}_1"], d[f"{edge}_2"]
    blend = min(0.025, 0.4 * D.length(e1), 0.4 * D.length(e2))
    a1, _ = D.split_at(e1, s=D.length(e1) - blend)
    e1n = D.join(a1, D.hermite(a1[-1], D.tangent_at(e1, s=D.length(e1) - blend), e1[-1], rot(da, -1), tension=0.35))
    _, b2 = D.split_at(e2, s=blend)
    e2n = D.join(D.hermite(e2[0], rot(db, 1), b2[0], D.tangent_at(e2, s=blend), tension=0.35), b2)
    out = [(n, e1n if n == f"{edge}_1" else e2n if n == f"{edge}_2" else e) for n, e in edges]
    return out, (la, lb)


def _pencil(v, bm, body, m):
    Ww = (bm["waist"] + v["waist_ease"]) / 4 * cm      # quarter (half piece) at the waist
    Hw = (bm["hip"] + v["hip_ease"]) / 4 * cm
    L = v["length"] * cm
    hip_depth = (bm["waist_height"] - bm["hip_height"]) * cm
    top, v_hip = L, L - hip_depth
    hem_half = Hw - v["hem_taper"] * cm / 2
    suppression = Hw - Ww                                # total to remove per quarter
    side_take = suppression * v["side_share"] / 100

    def half(dart_depth):
        side_dir = D._unit(np.array([Hw - hem_half, v_hip]))
        p = (D.Path((0, 0))
             .square_to((hem_half, 0), (1, 0), np.array([side_dir[1], -side_dir[0]]), "hem")
             .line_to((Hw, v_hip), "side_low")
             .square_to((Hw - side_take, top), side_dir, (0, 1), "side_high")
             .line_to((0, top), "waist")
             .close("cf"))
        edges = p.edges
        dart_w = suppression - side_take
        edges, legs = _trued_dart(edges, "waist", at=(Hw - side_take) * 0.45, width=dart_w,
                                  depth=dart_depth * cm, name="dart")
        # side seam as one edge (join the two side parts)
        e = dict(edges)
        side = D.join(e["side_low"], e["side_high"])
        out = []
        for n, pl in edges:
            if n == "side_low":
                out.append(("side", side))
            elif n == "side_high":
                continue
            else:
                out.append((n, pl))
        return D.cut_on_fold(out, fold="cf")

    if body is not None:
        hem_y, wrap = waist_placement(body, top)
    else:
        hem_y, wrap = 1.07 - top, 0.20
    front = Panel("front", half(v["dart_depth_front"]), cylinder_wrap(wrap, 0.0, hem_y))
    back = Panel("back", half(v["dart_depth_back"]), cylinder_wrap(wrap, np.pi, hem_y))
    seams = [Seam("front", "side_r", "back", "side_l", reverse=True),
             Seam("front", "side_l", "back", "side_r", reverse=True)]
    for p in ("front", "back"):
        seams += [Seam(p, "dart_a_r", p, "dart_b_r", reverse=True), Seam(p, "dart_a_l", p, "dart_b_l", reverse=True)]
    g = build_garment([front, back], seams)
    g.meta.update(hem_y=hem_y, torso_panels=["front", "back"], sleeve_panels=[],
                  girths={"waist": 4 * Ww, "hip": 4 * Hw})     # as drafted (the ease report, fitcheck)
    return g


PENCIL = Block("pencil_skirt", "Pencil skirt", "Skirts", [
    Param("waist_ease", "Waist ease", 2, 0, 8, 0.5),
    Param("hip_ease", "Hip ease", 4, 1, 15, 0.5),
    Param("length", "Length (waist to hem)", lambda b: 0.34 * b["height"], 35, 100, 1, group="Lengths"),
    Param("hem_taper", "Hem narrower than hip (total)", 4, 0, 20, 0.5),
    Param("side_share", "Waist shaping in side seams", 45, 0, 100, 5, unit="%", group="Darts"),
    Param("dart_depth_front", "Front dart length", lambda b: 9 * b["height"] / 166, 5, 15, 0.5, group="Darts"),
    Param("dart_depth_back", "Back dart length", lambda b: 13 * b["height"] / 166, 6, 18, 0.5, group="Darts"),
], _pencil, "Straight fitted skirt: waist darts front and back, curved side seams.")


# ================================================================= dress ===
def _dress(v, bm, body, m):
    H = bm["height"]
    Cw = (bm["chest"] + v["chest_ease"]) / 4 * cm
    Ww = (bm["waist"] + v["waist_ease"]) / 4 * cm
    Hw = (bm["hip"] + v["hip_ease"]) / 4 * cm
    L = v["length"] * cm
    neck_v = L
    shoulder_v = neck_v - 0.04 * H / 175
    shoulder_top_y = body.shoulder_top_y() if body is not None else bm["height"] * cm * 0.84
    hem_y = shoulder_top_y + 0.025 - neck_v
    # heights of the girth lines in pattern space
    v_waist = bm["waist_height"] * cm - hem_y
    v_hip = bm["hip_height"] * cm - hem_y
    armpit_depth = body.armpit_depth() if body is not None else 0.13 * H / 175
    v_ua = shoulder_v - (armpit_depth + v["armhole_clearance"] * cm)
    hem_half = Hw + v["flare"] * cm
    sh_u = 0.45 * bm["shoulder_width"] * cm
    neck_u = bm["neck"] * cm / (2 * np.pi) * 1.45
    S, N = np.array([sh_u, shoulder_v]), np.array([neck_u, neck_v])
    sdir = D._unit(N - S)
    perp = np.array([-sdir[1], sdir[0]])

    def half(neck_drop, bust_dart, extend=0.0):
        # a front with a bust dart has a longer side seam: the dart takes the
        # extra length up when sewn (extend = how much the underarm is raised)
        side_pts = [(hem_half, 0), (Hw, v_hip), (Ww, v_waist), (Cw, v_ua + extend)]
        side = D.spline(side_pts)
        # square the side seam's ends: vertical at the underarm, hem square to it
        side = D.join(*[s for s in (side,)])
        hem_end_dir = D.tangent_at(side, frac=0.0)
        p = (D.Path((0, 0))
             .square_to((hem_half, 0), (1, 0), np.array([hem_end_dir[1], -hem_end_dir[0]]), "hem"))
        p._add("side", side)
        sd = D.tangent_at(side, frac=1.0)
        p.square_to(S, np.array([-sd[1], sd[0]]), -perp, "armhole")
        p.line_to(N, "shoulder")
        p.square_to((0, neck_v - neck_drop), perp, (-1, 0), "neck")
        p.close("cf")
        edges = p.edges
        legs = None
        if bust_dart > 0:
            apex = np.array([0.1 * bm["chest"] * cm, bm["chest_height"] * cm - hem_y])
            at = D.length(side) - (v_ua - (bm["chest_height"] * cm - hem_y - 0.03)) * 0.8
            at = float(np.clip(at, 0.2 * D.length(side), 0.92 * D.length(side)))
            pt = D.point_at(side, s=at)
            direction = D._unit(apex - pt)
            depth = max(np.linalg.norm(apex - pt) - 0.025, 0.04)
            edges, legs = _trued_dart(edges, "side", at=at, width=bust_dart * cm, depth=depth, name="bust")
        return D.cut_on_fold(edges, fold="cf"), legs

    bd = v["bust_dart"] if bm.get("sex", "female") == "female" else 0.0
    be, _ = half(0.02 * H / 175, 0.0)
    back_side = D.length(dict(be)["side_r"])
    ext = bd * cm
    for _ in range(6):   # solve the front extension so sewn side seams match exactly
        fe, flegs = half(v["front_neck_drop"] * cm, bd, ext)
        if not flegs:
            break
        fd = dict(fe)
        err = D.length(fd["side_1_r"]) + D.length(fd["side_2_r"]) - back_side
        if abs(err) < 1e-5:
            break
        ext -= err
    wrap = body.torso_wrap_radius() if body is not None else 0.2
    front = Panel("front", fe, cylinder_wrap(wrap, 0.0, hem_y))
    back = Panel("back", be, cylinder_wrap(wrap, np.pi, hem_y))
    if flegs:
        # the back side seam is split where the front's dart opens, so the
        # pieces sew side_1 to side_1 and side_2 to side_2
        fd = dict(fe)
        L1 = D.length(fd["side_1_r"])
        bd_ = dict(be)
        for s in ("r", "l"):
            a, b = D.split_at(bd_[f"side_{s}"], s=L1 if s == "r" else D.length(bd_[f"side_{s}"]) - L1)
            names = [n for n, _ in back.edges]
            i = names.index(f"side_{s}")
            back.edges[i:i + 1] = [(f"side_{1 if s == 'r' else 2}_{s}", a), (f"side_{2 if s == 'r' else 1}_{s}", b)]
        seams = [Seam("front", "side_1_r", "back", "side_1_l", reverse=True),
                 Seam("front", "side_2_r", "back", "side_2_l", reverse=True),
                 Seam("front", "side_1_l", "back", "side_1_r", reverse=True),
                 Seam("front", "side_2_l", "back", "side_2_r", reverse=True),
                 Seam("front", "bust_a_r", "front", "bust_b_r", reverse=True),
                 Seam("front", "bust_a_l", "front", "bust_b_l", reverse=True)]
    else:
        seams = [Seam("front", "side_r", "back", "side_l", reverse=True),
                 Seam("front", "side_l", "back", "side_r", reverse=True)]
    seams += [Seam("front", "shoulder_r", "back", "shoulder_l", reverse=True),
              Seam("front", "shoulder_l", "back", "shoulder_r", reverse=True)]
    g = build_garment([front, back], seams)
    from .fitcheck import neck_opening
    g.meta.update(hem_y=hem_y, torso_panels=["front", "back"], sleeve_panels=[],
                  girths={"chest": 4 * Cw, "waist": 4 * Ww, "hip": 4 * Hw,
                          "neckline": neck_opening(neck_u, v["front_neck_drop"] * cm, 0.02 * H / 175)})
    return g


DRESS = Block("shift_dress", "Shift dress", "Dresses", [
    Param("chest_ease", "Bust / chest ease", 8, 2, 25, 0.5),
    Param("waist_ease", "Waist ease", 12, 2, 40, 0.5),
    Param("hip_ease", "Hip ease", 6, 2, 25, 0.5),
    Param("length", "Length (neck point to hem)", lambda b: 0.55 * b["height"], 60, 140, 1, group="Lengths"),
    Param("flare", "Hem flare (per side)", 3, 0, 20, 0.5, group="Lengths"),
    Param("armhole_clearance", "Armhole depth below armpit", 6, 1, 10, 0.5, group="Armhole & neck",
          help="tested: 3 cm gave 14% strain at the bust/armhole, 6 cm 9.7%"),
    Param("front_neck_drop", "Front neck depth", lambda b: 8 * b["height"] / 166, 2, 25, 0.5, group="Armhole & neck"),
    Param("bust_dart", "Bust dart width (female)", lambda b: max(0.0, min(5.0, (b["chest"] - b["underbust"]) * 0.18)),
          0, 8, 0.25, group="Darts"),
], _dress, "Sleeveless shift: shaped side seams through bust, waist and hip; side bust dart on female bodies.")


# =============================================================== trousers ===
def _trousers(v, bm, body, m):
    """Four pieces (front/back x right/left). Crease line at u = 0, u > 0
    toward the outseam, v up from the hem."""
    H = bm["height"] * cm
    Hq = (bm["hip"] + v["hip_ease"]) / 4 * cm
    Wq = (bm["waist"] + v["waist_ease"]) / 4 * cm
    knee_h = (bm["knee"] + v["knee_ease"]) / 4 * cm
    hem_off = v["hem_above_floor"] * cm
    v_crotch = bm["crotch_height"] * cm - v["crotch_drop"] * cm - hem_off   # leg length to fork
    # the leg opening can never be smaller than the leg where the hem falls
    # (shorts and capris hem on the thigh or calf, not the ankle)
    knee_y = 0.285 * bm["height"]
    leg_at = np.interp(v["hem_above_floor"], [0.04 * bm["height"], knee_y, bm["crotch_height"] - 4],
                       [bm["ankle"], bm["knee"], bm["thigh"]])
    hem_c = max(v["hem_width"], leg_at + 6 + 0.25 * v["knee_ease"])
    hem_h = hem_c / 4 * cm                        # half of each piece at the hem (2 pieces round the leg)
    # a knee shaping point only when the hem is below the knee
    v_knee = 0.53 * v_crotch if v["hem_above_floor"] < knee_y - 6 else None
    rise = (bm["waist_height"] - bm["crotch_height"]) * cm + v["crotch_drop"] * cm + v["rise_ease"] * cm
    v_waist = v_crotch + rise
    v_hip = v_waist - (bm["waist_height"] - bm["hip_height"]) * cm

    def piece(back: bool, fork_lift=0.0, side_adj=0.0):
        fork = (bm["hip"] * cm / 16) * (2.0 if back else 1.0) * v["fork"] / 100
        inner_hip = Hq / 2 + (0.01 if back else 0.0)
        outer_hip = Hq / 2 - (0.01 if back else 0.0)
        top_extra = v["back_rise"] * cm if back else 0.0
        cb_tilt = 0.035 if back else 0.008          # centre seam leans in toward the waist
        waist_in = -(inner_hip - cb_tilt)
        waist_out = Wq - (inner_hip - cb_tilt)
        # outseam first (to know the leg-line directions at the hem)
        knee_pt = [(knee_h, v_knee)] if v_knee is not None else []
        out = D.spline([(hem_h, 0), *knee_pt, (outer_hip * 0.98, v_crotch), (outer_hip, v_hip),
                        (waist_out, v_waist + side_adj)])
        fork_pt = np.array([-(inner_hip + fork), v_crotch + fork_lift])
        # inseam leaves the fork straight down (the four fork corners then make
        # 360 deg), curves into the knee line, straight to the hem
        if v_knee is not None:
            ins = D.join(D.hermite(fork_pt, (0, -1), (-knee_h, v_knee),
                                   D._unit(np.array([-hem_h + knee_h, -v_knee])), tension=0.35),
                         D.line((-knee_h, v_knee), (-hem_h, 0)))
        else:   # shorts: one smooth curve from the fork to the hem
            ins = D.hermite(fork_pt, (0, -1), (-hem_h, 0),
                            D._unit(np.array([-hem_h - fork_pt[0], -fork_pt[1]]) + [0, -1.0]), tension=0.35)
        d_out0 = D.tangent_at(out, frac=0.0)                 # outseam leaving the hem (up)
        d_in1 = D.tangent_at(ins, frac=1.0)                  # inseam arriving at the hem (down)
        hem = D.hermite((-hem_h, 0), (-d_in1[1], d_in1[0]), (hem_h, 0), (d_out0[1], -d_out0[0]), tension=0.3)
        centre = D.line((waist_in, v_waist + top_extra), (-inner_hip, v_hip))
        cdir = D.tangent_at(centre, frac=1.0)
        # crotch continues the centre seam's direction (no kink at the hip),
        # arriving horizontal at the fork
        crotch = D.hermite((-inner_hip, v_hip), cdir, fork_pt, (-1, 0), tension=0.45)
        # waistline square to the outseam and to the centre seam at its ends,
        # so it runs smoothly round the body when sewn
        d_out1 = D.tangent_at(out, frac=1.0)
        waist = D.hermite(out[-1], (-d_out1[1], d_out1[0]), (waist_in, v_waist + top_extra),
                          (cdir[1], -cdir[0]), tension=0.3)
        return [("hem", hem), ("outseam", out), ("waist", waist),
                ("centre", centre), ("crotch", crotch), ("inseam", ins)]

    fe = piece(False)
    fd = dict(fe)
    # balance the legs (as a patternmaker does): lower the back fork until the
    # back inseam equals the front's, and set the back side-waist height so
    # the outseams match. Both are monotonic: bisection.
    def solve(f, target, lo, hi):
        for _ in range(50):
            mid = 0.5 * (lo + hi)
            lo, hi = (mid, hi) if f(mid) < target else (lo, mid)
        return 0.5 * (lo + hi)
    lift = solve(lambda x: D.length(dict(piece(True, fork_lift=x))["inseam"]),
                 D.length(fd["inseam"]), -min(0.08, 0.6 * v_crotch), 0.08)
    side = solve(lambda x: D.length(dict(piece(True, lift, x))["outseam"]),
                 D.length(fd["outseam"]), -0.08, 0.08)
    be = piece(True, lift, side)
    mir = lambda edges: [(n, D.reverse(D.mirror(e))) for n, e in edges[::-1]]

    def legs_place(back, side):
        """Below the crotch: wrapped around the leg; above the hip: around
        the torso; blended in between (initial shape only: the sewing phase
        settles everything)."""
        if body is not None and getattr(body, "kind", "") == "mesh":
            lx = abs(body.human.joint(f"{body.side}-upper-leg")[0])
        else:
            lx = 0.09
        leg_r = max(bm["thigh"] * cm / (2 * np.pi) + 0.045, 0.10)
        tor_r = (body.torso_wrap_radius() if body is not None else 0.2) + 0.01
        ang0 = np.pi if back else 0.0
        sgn = side
        hem_y = (0.0 + hem_off)

        def place(uv):
            # +u points toward +x on all four pieces: on the right leg that's
            # the outseam, and the left pieces are mirror images (their +u is
            # the inseam side, which is also toward +x). Front pieces wrap
            # from +z, back pieces from -z. (Bug fixed: the left pieces were
            # flipped twice and the left front ended up across the crotch.)
            u, vv = uv[:, 0], uv[:, 1]
            t = np.clip((vv - (v_crotch - 0.05)) / max(v_hip - v_crotch + 0.05, 1e-3), 0, 1)
            t = t * t * (3 - 2 * t)
            R = leg_r * (1 - t) + tor_r * t
            cx = sgn * lx * (1 - t)
            th = np.arcsin(np.clip(sgn * lx / tor_r, -1, 1)) * t + u / R
            # legs: elliptical tube, slim side-to-side so it doesn't reach into
            # the other leg; torso: round
            rx = np.minimum(R, lx * 0.98) * (1 - t) + R * t
            x = cx + rx * np.sin(th)
            z = (-1 if back else 1) * R * np.cos(th)
            return np.stack([x, hem_y + vv, z], 1)
        return place

    # right leg pieces: u > 0 (outseam) toward +x for the leg at +x
    P = [Panel("front_r", fe, legs_place(False, +1)), Panel("back_r", be, legs_place(True, +1)),
         Panel("front_l", mir(fe), legs_place(False, -1)), Panel("back_l", mir(be), legs_place(True, -1))]
    seams = []
    for s in ("r", "l"):
        # front and back legs are drafted the same way round: outseams both run
        # hem -> waist, inseams fork -> hem (so not reversed)
        seams += [Seam(f"front_{s}", "outseam", f"back_{s}", "outseam", reverse=False),
                  Seam(f"front_{s}", "inseam", f"back_{s}", "inseam", reverse=False)]
    seams += [Seam("front_r", "centre", "front_l", "centre", reverse=True),
              Seam("front_r", "crotch", "front_l", "crotch", reverse=True),
              Seam("back_r", "centre", "back_l", "centre", reverse=True),
              Seam("back_r", "crotch", "back_l", "crotch", reverse=True)]
    g = build_garment(P, seams)
    fork = lambda back: (bm["hip"] * cm / 16) * (2.0 if back else 1.0) * v["fork"] / 100
    leg = sum(0.98 * (Hq / 2 - d) + (Hq / 2 + d) + fork(back) for back, d in ((False, 0.0), (True, 0.01)))
    g.meta.update(hem_y=hem_off, torso_panels=[], sleeve_panels=[], lower=True,
                  girths={"waist": 4 * Wq, "hip": 4 * Hq, "thigh": leg})
    return g


TROUSERS = Block("trousers", "Trousers", "Pants", [
    Param("waist_ease", "Waist ease", 2, 0, 12, 0.5),
    Param("hip_ease", "Hip ease", 6, 2, 25, 0.5),
    Param("knee_ease", "Knee ease", 16, 4, 40, 0.5),
    Param("hem_width", "Leg opening (circumference)", lambda b: max(36.0, b["ankle"] + 14), 24, 70, 0.5),
    Param("hem_above_floor", "Hem above floor", 3, 0, 75, 0.5, group="Lengths"),   # Shorts: ~67 cm on a 2 m body
    Param("crotch_drop", "Crotch drop below body", 2, 0, 8, 0.25, group="Rise"),
    Param("rise_ease", "Extra rise at waist", 1, -5, 8, 0.5, group="Rise"),
    Param("back_rise", "Back rise (raised centre back)", 3, 0, 8, 0.25, group="Rise"),
    Param("fork", "Fork (crotch extension)", 100, 70, 140, 1, unit="%", group="Rise",
          help="100% = hip/16 front, hip/8 back"),
], _trousers, "Four-piece straight trousers: front and back crotch curves, outseam and inseam per leg.")


BLOCKS = {b.key: b for b in (TEE, LONG_SLEEVE, A_LINE, PENCIL, DRESS, TROUSERS)}


def draft_block(key, body, m, overrides=None):
    """Draft a block for this avatar. Returns (garment, info) where info has
    the parameter values used and the avatar measurements they came from."""
    b = BLOCKS[key]
    bm = body_measures(body, m)
    vals = b.defaults(bm)
    # values from a request (a project file's params): a known parameter, a number, and within sanity limits
    # (twice the slider's span past either end), so a stray 1e6 can't draft a pattern too big to mesh
    P = {p.name: p for p in b.params}
    for k, v in (overrides or {}).items():
        if k not in vals:
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(x):
            continue
        if k in P:
            span = P[k].hi - P[k].lo
            x = min(max(x, P[k].lo - 2 * span), P[k].hi + 2 * span)
        vals[k] = x
    g = b.draft(vals, bm, body, m)
    g.meta["block"] = key
    g.meta["params"] = vals
    return g, {"params": vals, "measures": {k: (round(v, 1) if isinstance(v, float) else v) for k, v in bm.items()}}


# ============================================ beginner controls (presets) ===
# Plain-language choices that set real parameters. Values can depend on the
# avatar (lengths scale with height). The studio shows these in beginner mode;
# advanced mode shows every Param.
def _h(f):
    return lambda b: f * b["height"]


PRESETS = {
    "tee": {
        "Fit": {"Snug": {"chest_ease": 4, "sleeve_ease": 5}, "Regular": {"chest_ease": 12, "sleeve_ease": 8},
                "Relaxed": {"chest_ease": 22, "sleeve_ease": 12}, "Oversized": {"chest_ease": 36, "sleeve_ease": 16}},
        "Length": {"Cropped": {"length": _h(0.31)}, "Hip": {"length": _h(0.38)}, "Long": {"length": _h(0.44)},
                   "Tunic": {"length": _h(0.50)}},
        "Neckline": {"Crew": {"front_neck_drop": _h(0.043)}, "Scoop": {"front_neck_drop": _h(0.075)},
                     "Deep scoop": {"front_neck_drop": _h(0.10)}},
        "Sleeves": {"Cap": {"sleeve_length": _h(0.03)}, "Short": {"sleeve_length": _h(0.069)},
                    "Elbow": {"sleeve_length": lambda b: b["arm_length"] * 0.42 - 6}},
    },
    "long_sleeve": {
        "Fit": {"Snug": {"chest_ease": 6, "sleeve_ease": 5}, "Regular": {"chest_ease": 14, "sleeve_ease": 9},
                "Relaxed": {"chest_ease": 24, "sleeve_ease": 13}},
        "Length": {"Hip": {"length": _h(0.38)}, "Long": {"length": _h(0.44)}, "Tunic": {"length": _h(0.50)}},
        "Neckline": {"Crew": {"front_neck_drop": _h(0.043)}, "Scoop": {"front_neck_drop": _h(0.075)}},
        "Cuffs": {"Fitted": {"cuff_ease": 4}, "Regular": {"cuff_ease": 7}, "Loose": {"cuff_ease": 13}},
    },
    "a_line_skirt": {
        "Fit": {"Fitted hips": {"hip_ease": 3}, "Regular": {"hip_ease": 5}, "Full": {"hip_ease": 10}},
        "Length": {"Mini": {"length": _h(0.24)}, "Knee": {"length": _h(0.33)}, "Midi": {"length": _h(0.42)},
                   "Maxi": {"length": _h(0.55)}},
    },
    "pencil_skirt": {
        "Fit": {"Snug": {"hip_ease": 2}, "Regular": {"hip_ease": 4}, "Easy": {"hip_ease": 7}},
        "Length": {"Above knee": {"length": _h(0.30)}, "Knee": {"length": _h(0.34)}, "Midi": {"length": _h(0.42)}},
        "Shape": {"Straight": {"hem_taper": 0}, "Pencil": {"hem_taper": 4}, "Wiggle": {"hem_taper": 9}},
    },
    "shift_dress": {
        "Fit": {"Fitted": {"chest_ease": 5, "waist_ease": 6, "hip_ease": 4},
                "Regular": {"chest_ease": 8, "waist_ease": 12, "hip_ease": 6},
                "Relaxed": {"chest_ease": 14, "waist_ease": 22, "hip_ease": 12}},
        "Length": {"Mini": {"length": _h(0.48)}, "Knee": {"length": _h(0.55)}, "Midi": {"length": _h(0.65)}},
        "Shape": {"Straight": {"flare": 0}, "A-line": {"flare": 5}, "Swing": {"flare": 12}},
        "Neckline": {"High": {"front_neck_drop": _h(0.03)}, "Scoop": {"front_neck_drop": _h(0.05)},
                     "Deep": {"front_neck_drop": _h(0.09)}},
    },
    "trousers": {
        "Fit": {"Slim": {"hip_ease": 4, "knee_ease": 9, "hem_width": lambda b: b["ankle"] + 9},
                "Regular": {"hip_ease": 6, "knee_ease": 16, "hem_width": lambda b: max(36.0, b["ankle"] + 14)},
                "Wide leg": {"hip_ease": 9, "knee_ease": 34, "hem_width": lambda b: b["ankle"] + 38}},
        "Length": {"Full": {"hem_above_floor": 3}, "Ankle": {"hem_above_floor": 8},
                   "Cropped": {"hem_above_floor": 18}, "Capri": {"hem_above_floor": lambda b: 0.18 * b["height"]},
                   "Shorts": {"hem_above_floor": lambda b: b["crotch_height"] - 0.14 * b["height"]}},
        "Rise": {"Low": {"rise_ease": -4}, "Mid": {"rise_ease": 1}, "High": {"rise_ease": 4}},
    },
}

DEFAULT_CHOICE = {"Fit": "Regular", "Length": None, "Neckline": None, "Sleeves": "Short", "Cuffs": "Regular",
                  "Shape": None, "Rise": "Mid"}


def preset_values(key, choices: dict, bm) -> dict:
    """Parameter overrides for a set of plain-language choices."""
    out = {}
    for control, option in choices.items():
        opts = PRESETS.get(key, {}).get(control, {})
        for k, v in opts.get(option, {}).items():
            out[k] = round(float(v(bm) if callable(v) else v), 1)
    return out


# ease-table line -> the parameter that adds room there (for "make it roomier" fixes)
EASE_PARAM = {"chest": "chest_ease", "waist": "waist_ease", "hip": "hip_ease", "upper arm": "sleeve_ease",
              "neckline": "neck_width", "thigh": "hip_ease"}
