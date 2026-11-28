"""'What's wrong here?' - tap the draped garment, get the cause in plain words.

Around the tapped point (3 cm), every mesh edge's strain is split into
along-the-grain (the pattern's vertical) and across-the-grain parts. That
tells apart the classic fitting problems:
  pulled across          -> too tight around here: needs more ease/width
  pulled along the grain -> too short here / hanging from this spot
  pulled on the bias     -> drag lines: something is pulling diagonally
  slack (compressed)     -> extra fabric: rippling or pooling here
and the region (from where the point sits on the standing body) picks the
setting to change.
"""
from __future__ import annotations

import numpy as np

REGION_FIX = {
    # region: (across fix, along fix)
    "neck & shoulders": (("neck_width", 8, "%", "a wider neckline"), ("armhole_clearance", 1.5, "cm", "a deeper armhole")),
    "upper chest / armholes": (("chest_ease", 4, "cm", "more room across the chest"), ("armhole_clearance", 1.5, "cm", "a deeper armhole")),
    "bust / chest": (("chest_ease", 4, "cm", "more room across the bust"), ("bust_dart", 1, "cm", "a bigger bust dart")),
    "waist": (("waist_ease", 4, "cm", "more room at the waist"), ("length", 4, "cm", "more length")),
    "hips": (("hip_ease", 4, "cm", "more room over the hips"), ("crotch_drop", 1.5, "cm", "a longer rise")),
    "legs": (("knee_ease", 6, "cm", "wider legs"), ("hem_above_floor", -3, "cm", "longer legs")),
    "ankles & feet": (("hem_width", 6, "cm", "a wider hem"), ("hem_above_floor", 4, "cm", "shorter legs")),
    "arms": (("sleeve_ease", 3, "cm", "a roomier sleeve"), ("cap_height", 1, "cm", "a taller sleeve cap")),
}


def _region(body, p):
    L = body.lines
    H = body.height()
    from .freeform import _surf
    reg = _surf(body).region(p) if getattr(body, "kind", "") == "mesh" else "torso"
    if reg in ("arm", "hand"):
        return "arms"
    y = p[1]
    if y >= L["armpit"] + 0.04:
        return "neck & shoulders"
    if y >= L["armpit"] - 0.04:
        return "upper chest / armholes"
    if y >= L["underbust"]:
        return "bust / chest"
    if y >= L["waist"] - 0.06:
        return "waist"
    if y >= L["crotch"]:
        return "hips"
    if y >= 0.13 * H / 1.7:
        return "legs"
    return "ankles & feet"


def explain(body, X, stand, edges, rest, uv, panel_id, v, params, block=None, pose_label=None):
    p = X[v]
    d = np.linalg.norm(X - p, axis=1)
    near = d < 0.03
    sel = near[edges[:, 0]] & near[edges[:, 1]]
    if sel.sum() < 3:
        sel = (d[edges[:, 0]] < 0.05)
    E = edges[sel]
    L = np.linalg.norm(X[E[:, 0]] - X[E[:, 1]], axis=1)
    strain = (L - rest[sel]) / rest[sel]
    duv = uv[E[:, 1]] - uv[E[:, 0]]
    duv /= np.linalg.norm(duv, axis=1, keepdims=True) + 1e-12
    along = np.abs(duv[:, 1]); across = np.abs(duv[:, 0])
    w_al, w_ac = along ** 2, across ** 2
    s_al = float((strain * w_al).sum() / (w_al.sum() + 1e-12))
    s_ac = float((strain * w_ac).sum() / (w_ac.sum() + 1e-12))
    diag = np.abs(np.abs(duv[:, 0]) - np.abs(duv[:, 1])) < 0.35
    s_bias = float(strain[diag].mean()) if diag.any() else 0.0
    region = _region(body, stand[v])
    where = f"at the {region}" + (f" ({pose_label.lower()})" if pose_label else "")
    out = {"region": region, "across_pct": round(s_ac * 100, 1), "along_pct": round(s_al * 100, 1),
           "bias_pct": round(s_bias * 100, 1)}
    tight = 0.04
    fixes = []
    if max(s_ac, s_al, s_bias) < tight and min(s_ac, s_al) > -0.02:
        out["title"] = f"Fits fine {where}"
        out["text"] = (f"The fabric here is stretched {max(s_ac, s_al, 0) * 100:.0f}% at most: it is resting, "
                       "not pulling.")
    elif min(s_ac, s_al) < -0.02 and max(s_ac, s_al) < tight:
        out["title"] = f"Extra fabric {where}"
        out["text"] = ("The fabric here is bunched up (shorter than it was cut): it ripples or pools. "
                       "If you don't want that fullness, take some width or length out here.")
    elif s_ac >= s_al and s_ac >= s_bias:
        out["title"] = f"Too tight across {where}"
        out["text"] = (f"Pulled {s_ac * 100:.0f}% across the grain: the body is wider here than the garment. "
                       "You'd see horizontal pull lines.")
        fixes.append(REGION_FIX.get(region, (None, None))[0])
    elif s_al >= s_bias:
        out["title"] = f"Pulled up and down {where}"
        out["text"] = (f"Stretched {s_al * 100:.0f}% along the grain: the garment is too short here, or the weight "
                       "of the fabric below is hanging from this spot.")
        fixes.append(REGION_FIX.get(region, (None, None))[1])
    else:
        out["title"] = f"Diagonal drag lines {where}"
        out["text"] = (f"Pulled {s_bias * 100:.0f}% on the bias: something nearby is too tight or too short and "
                       "pulls the fabric sideways. Fix the tight spot it points to.")
        fixes += [REGION_FIX.get(region, (None, None))[0]]
    out["fixes"] = []
    for f in fixes:
        if f and f[0] in (params or {}):
            out["fixes"].append({"param": f[0], "value": round(params[f[0]] + f[1], 1),
                                 "label": f"Try {f[3]} ({'+' if f[1] > 0 else ''}{f[1]:g} {f[2]})"})
        elif f:
            out["hint"] = f"For your own design: give it {f[3]} here."
    return out
