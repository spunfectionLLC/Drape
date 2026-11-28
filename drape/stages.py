"""Staged sewing: the sewing order of a garment's pieces (STAGED_SEWING_SPEC).

A person sews the body of a garment first (shoulders, sides, sleeves), puts it
on, and only then sews on the hood, collar, cuffs and pockets. Sewing every seam
at once makes a hood and a shirt meet halfway: the neckline gets dragged up to
the hood. So pieces are sewn in stages, a construction order in time:

  1  body pieces: on the torso, arms or legs
  2  hoods, collars, cuffs, waistbands (bands round an opening), pieces on the
     head, neck or hands
  3  pockets topstitched onto a garment

DESIGN RULE (STAGED_SEWING_SPEC section 0): a piece's stage comes ONLY
from (a) where it is placed on the body, (b) its role tag, (c) the user's choice.
Nothing here may look at the seams, the seam graph or which pieces are sewn to
which; tests/test_v18_stages.py checks this file's assignment code for it. A piece
with no region and no role is stage 1 (no fallback that infers anything). Pieces
are placed once, before the simulation; a stage only says *when* a piece is sewn.

A lining, a pocket bag or a layer copy is placed on its piece (a placement key),
so it goes in that piece's stage. Stages are renumbered 1, 2, ... without gaps, so
a garment that's all one kind of piece (gloves alone, a plain tee) is all stage 1.
"""
from __future__ import annotations

import re

import numpy as np

STAGE_MAX = 3
GARMENT_STAGES_MAX = 4    # stages in all, with several garments (live_springs.js has four stage slots)
ROLES = ("body", "sleeve", "hood", "collar", "cuff", "waistband", "pocket", "other")
ROLE_STAGE = {"body": 1, "sleeve": 1, "hood": 2, "collar": 2, "cuff": 2, "waistband": 2, "pocket": 3}
REGION_STAGE = {"body": 1, "head": 2, "neck": 2, "hands": 2, "band": 2, "surface": 3}


def region(pc, where=None, body=None):
    """Where a piece is placed, from its placement keys alone:
    ('on', host): placed on another piece (lining, inside pocket bag, layer copy);
    'surface' (topstitched on a garment), 'band' (round an opening), 'hands', 'head',
    'neck', 'body', or None (not placed). where: the piece's centre on the body (m),
    for pieces placed by a point or a template."""
    pl = pc.get("place") or {}
    if pl.get("_lining_of"):
        return ("on", pl["_lining_of"])
    if pl.get("layer_of"):
        return ("on", pl["layer_of"])
    if pl.get("on"):
        return ("on", pl["on"]) if pl.get("inside") else "surface"
    if pl.get("loop"):
        return "band"
    if pl.get("glove"):
        return "hands"
    lm = pl.get("landmark") or ""
    if lm.startswith("head"):
        return "head"
    if lm.startswith("neck"):
        return "neck"
    if where is not None and body is not None:
        r = _body_region(body, np.asarray(where, float))
        if r:
            return r
    if pl.get("arm"):                 # a drafted sleeve (dedit.add_sleeve): sewn with the body, as the tee's sleeves
        return "body"
    if lm or pl.get("template") or pl.get("anchor") is not None:
        return "body"
    return None


def _body_region(body, p):
    try:
        if p[1] > body.shoulder_top_y() + 0.03:
            return "head"
    except Exception:
        pass
    for j in ("l-hand", "r-hand"):
        try:
            from .freeform import _joint
            if np.linalg.norm(_joint(body, j) - p) < 0.07:
                return "hands"
        except Exception:
            pass
    return None


def _user_stage(pc):
    v = pc.get("stage")
    if v in (None, "", "auto"):
        return None
    return int(min(max(int(v), 1), STAGE_MAX))


def assign(pieces, regions=None):
    """-> ({piece name: stage}, {piece name: True if automatic}).
    pieces: the design's pieces (their role, stage and placement);
    regions: {piece name: region(...)} (from the placement alone if not given)."""
    regions = dict(regions or {})
    by_name = {pc["name"]: pc for pc in pieces}
    for pc in pieces:
        regions.setdefault(pc["name"], region(pc))

    def table(n, seen=()):
        pc = by_name[n]
        u = _user_stage(pc)
        if u is not None:
            return u
        role = pc.get("role")
        if role in ROLE_STAGE:
            return ROLE_STAGE[role]
        r = regions.get(n)
        if isinstance(r, tuple):              # on its piece: in that piece's stage
            return table(r[1], seen + (n,)) if r[1] in by_name and r[1] not in seen else 1
        return REGION_STAGE.get(r, 1)

    raw = {n: table(n) for n in by_name}
    # garments worn over others (merged for Live and Drape it, server._merged_design): a garment's stages come after
    # those of every garment under it, in the layer order the user set in Garments (Tyler, 2026-11-25); within a
    # garment, as above. One garment: as before.
    layer = {n: int(by_name[n].get("_garment", 0)) for n in by_name}
    stage, base = {}, 0
    for k in sorted(set(layer.values())):
        mine = [n for n in by_name if layer[n] == k]
        order = {v: i + 1 for i, v in enumerate(sorted({raw[n] for n in mine}))}   # no empty stages
        for n in mine:
            stage[n] = min(base + order[raw[n]], GARMENT_STAGES_MAX)
        base += len(order)
    auto = {n: _user_stage(by_name[n]) is None for n in by_name}
    return stage, auto


def stage_names(panel_names, piece_stage, roles=None):
    """A word or two for each stage, for the progress text: {2: 'hood, cuffs'}."""
    out = {}
    roles = roles or {}
    for n, k in zip(panel_names, piece_stage):
        if k > 1:
            n = n.split("~", 1)[-1]            # a merged garment's piece: its own name
            r = roles.get(n)
            w = r if r in ROLE_STAGE and r not in ("body", "sleeve") else None
            if not w:
                w = re.sub(r"(_lining)?(_\d+)?$", "", n)
                w = re.sub(r"_(r|l|left|right)$", "", w).replace("_", " ") or n
            out.setdefault(int(k), [])
            if w not in out[int(k)]:
                out[int(k)].append(w)
    return {k: ", ".join(v[:3]) + ("…" if len(v) > 3 else "") for k, v in out.items()}
