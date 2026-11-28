"""drape studio: local web app (python -m drape.studio).

Everything runs on this computer: a small HTTP server (standard library only)
serves one page (static/index.html) and a JSON API. Drapes run in a separate
process so the UI stays responsive.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import multiprocessing as mp
import queue
import tempfile
import threading
import time
import traceback
import uuid
from dataclasses import asdict, fields
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

from ..blocks import BLOCKS, EASE_PARAM, PRESETS, body_measures, draft_block, preset_values
from ..fabrics import FABRICS, INTERFACINGS
from .. import brand as _brand
from .. import features as _features
from ..features import FeatureOff
from ..measurements import Measurements

STATIC = Path(__file__).parent / "static"
ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "measurements"
if not EXAMPLES.exists():            # installed app: the measurements ship inside the package
    EXAMPLES = Path(__file__).resolve().parents[1] / "measurements"


def _static_file(url_path):
    """A stylesheet or script of the studio page (top level, css/ or js/), or None.
    Never anything outside the studio's static folder."""
    name = url_path.lstrip("/").split("?")[0]
    if not name.endswith((".js", ".css")):
        return None
    try:
        f = (STATIC / name).resolve()
        f.relative_to(STATIC.resolve())
    except (ValueError, OSError):
        return None
    if f.parent not in (STATIC.resolve(), (STATIC / "css").resolve(), (STATIC / "js").resolve()):
        return None
    return f if f.is_file() else None


def studio_source() -> str:
    """The studio page's whole source: the HTML plus every stylesheet and script it
    loads (for tests and for checking what ships)."""
    import re
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    parts = [html]
    for ref in re.findall(r'(?:href|src)="([^"]+\.(?:css|js))"', html):     # in the order the page loads them
        f = _static_file("/" + ref)
        if f is not None:
            parts.append(f.read_text(encoding="utf-8"))
    return "\n".join(parts)


# ------------------------------------------------------------------ state --
class Missing(KeyError):
    """An avatar or drape id the server doesn't have (it restarted while the page stayed open): a sentence, not
    the bare id KeyError gives."""
    def __str__(self):
        return self.args[0]


class _Store(dict):
    """Avatars or drape jobs by id, the `keep` most recently used (a long session builds many: on the website
    they are all in the browser's memory, about 20 MB an avatar with its body grid). A running job is never let
    go; `drop` frees what an entry leaves behind (a job's folder)."""
    def __init__(self, what, keep=None, drop=None):
        super().__init__()
        self.what, self.keep, self.drop = what, keep, drop

    def __missing__(self, key):
        raise Missing(self.what)

    def __getitem__(self, key):
        v = super().__getitem__(key)
        if self.keep and key in self:                     # used: newest again
            super().__delitem__(key)
            super().__setitem__(key, v)
        return v

    def __setitem__(self, key, v):
        super().__setitem__(key, v)
        if self.keep:
            for k in [k for k in self if k != key][:max(0, len(self) - self.keep)]:
                old = dict.get(self, k)
                if isinstance(old, dict) and old.get("state") == "running":
                    continue
                super().__delitem__(k)
                if self.drop:
                    self.drop(old)


def _drop_job(j):
    import shutil
    if isinstance(j, dict) and j.get("outdir"):
        shutil.rmtree(j["outdir"], ignore_errors=True)


AVATARS_KEPT, JOBS_KEPT = 8, 24


class State:
    def __init__(self):
        self.avatars = _Store("Your avatar isn't on the studio's server any more (it restarted, or it keeps only the "
                              f"latest {AVATARS_KEPT}). Go to Body: the avatar rebuilds from your measurements.",
                              keep=AVATARS_KEPT)                  # id -> dict(meas, shape, body, rows)
        self.jobs = _Store("That drape isn't on the studio's server any more (it restarted, or it keeps only the "
                           f"latest {JOBS_KEPT}). Press Drape it again.", keep=JOBS_KEPT, drop=_drop_job)
        self.lock = threading.Lock()


S = State()


def _b64(a):
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def _mesh_payload(V, F):
    return {"v": _b64(np.round(np.asarray(V) * 1000).astype(np.int16)),
            "f": _b64(np.asarray(F, np.uint32)), "nv": int(len(V)), "nf": int(len(F))}


def _req_params(req) -> dict:
    """A request's pattern parameters (a project file's): numbers only; draft_block keeps them within sanity limits."""
    p = req.get("params") or {}
    return {k: float(v) for k, v in (p.items() if isinstance(p, dict) else ())
            if isinstance(v, (int, float)) and not isinstance(v, bool)}


def _meas_from(d: dict) -> Measurements:
    known = {f.name for f in fields(Measurements)}
    clean = {}
    for k, v in d.items():
        if k not in known or v in ("", None):
            continue
        if k == "sex":
            clean[k] = v
            continue
        # a number that can't be a measurement is a typo: say which, about the number (CLAUDE.md, "Bodies");
        # building from it crashed deep in the fit ("arange: cannot compute length") or ran for a minute
        label = k.replace("_", " ").capitalize()
        try:
            x = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{label} \"{v}\": type a number.") from None
        if not np.isfinite(x):
            raise ValueError(f"{label}: type a number.")
        if k != "muscle" and x <= 0:
            raise ValueError(f"{label} {x:g} cm: a measurement can't be zero or less. Check that number and type it again.")
        clean[k] = x
    return Measurements(**clean)


# ----------------------------------------------------------------- avatar --
def api_avatar(req):
    from ..human import fit_human
    from ..meshbody import MeshBody
    m = _meas_from(req["measurements"])
    warnings = m.validate()
    key = hashlib.sha1(json.dumps(asdict(m), sort_keys=True).encode()).hexdigest()[:12]
    with S.lock:
        have = S.avatars[key] if key in S.avatars else None       # [] marks it used (only the latest few are kept)
    if have is None:
        t = time.time()
        try:
            h, rows = fit_human(m)
            body = MeshBody(h, measurements=m)
            body.mesh()
        except Exception as e:
            # numbers the avatar can't be built from: when there's a typo message (inches in cm fields, …) it
            # says why, so the page shows that instead of the fit's own error
            if warnings:
                raise ValueError(" ".join(warnings)) from e
            raise
        have = dict(meas=m, shape=h.shape, body=body, rows=rows, fit_s=time.time() - t)
        with S.lock:
            S.avatars[key] = have
    body = have["body"]
    V, F = body.mesh()
    return {"id": key, "rows": have["rows"], "warnings": warnings, "fit_seconds": round(have["fit_s"], 1),
            "mesh": _mesh_payload(V, F), "lines": body.lines,
            "measures": {k: (round(v, 1) if isinstance(v, float) else v) for k, v in body_measures(body, m).items()}}


def api_guide(avatar_id):
    from ..render import measurement_guide
    import imageio.v2 as iio
    a = S.avatars[avatar_id]
    tg = {k: v for k, v in asdict(a["meas"]).items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    img = measurement_guide(a["body"], tg)
    buf = io.BytesIO(); iio.imwrite(buf, img, format="png")
    return buf.getvalue()


# ------------------------------------------------------------------ draft --
def _explain_problem(p: str) -> dict:
    if "MISMATCH" in p:
        return {"text": p, "plain": "Two edges that are sewn together aren't the same length, so the longer one "
                                    "will pucker. If that's on purpose (gathering, easing), it's fine."}
    if "TWISTED" in p:
        return {"text": p, "plain": "These two edges look like they'd be sewn end-to-end the wrong way round."}
    if "point" in p:
        return {"text": p, "plain": "Where these pieces meet, the finished edge will have a small point instead "
                                    "of a smooth line. Smoothing the curve near the seam fixes it."}
    if "dip" in p or "notch" in p:
        return {"text": p, "plain": "Where these pieces meet, the finished edge will dip in a little 'V'."}
    if "cone" in p or "ripple" in p:
        return {"text": p, "plain": "The pieces meeting at this point don't add up to a flat surface: the fabric "
                                    "will bunch or pull there."}
    return {"text": p, "plain": p}


def _pieces_payload(g):
    from ..seammarks import seam_marks
    seams = g.meta["seam_defs"]
    SM = seam_marks(g.meta["panels"], seams)
    sid = {}
    for i, s in enumerate(seams):
        sid[(s.panel_a, s.edge_a)] = i
        sid[(s.panel_b, s.edge_b)] = i
    r2 = lambda v: [round(float(x), 2) for x in v]
    out = []
    for p in g.meta["panels"]:
        edges = []
        for n, e in p.edges:
            pts = np.round(np.asarray(e) * 100, 2)
            mk = SM[p.name]["edges"].get(n)
            edges.append({"name": n, "pts": pts.tolist(), "seam": sid.get((p.name, n)),
                          "length_cm": round(float(np.linalg.norm(np.diff(e, axis=0), axis=1).sum()) * 100, 1),
                          **({"num": mk["num"], "partner": mk["partner"], "tag": r2(mk["tag"]),
                              "notches": [r2(list(q) + list(d)) for q, d in mk["notches"]]} if mk else {})})
        out.append({"name": p.name, "edges": edges, "dots": [r2(d["point"]) for d in SM[p.name]["dots"]]})
    return out


def api_draft(req):
    from ..fitcheck import ease_report
    from ..seamcheck import check_seams
    from ..instructions import instructions
    a = S.avatars[req["avatar"]]
    key = req["block"]
    bm = body_measures(a["body"], a["meas"])
    over = preset_values(key, req.get("choices") or {}, bm)
    over.update(_req_params(req))
    g, info = draft_block(key, a["body"], a["meas"], over)
    rep = check_seams(g.meta["panels"], g.meta["seam_defs"])
    ease = []
    if g.meta.get("hem_y") is not None and (g.meta.get("torso_panels") or g.meta.get("lower")):
        for r in ease_report(g, a["body"]):
            row = dict(r)
            if "ease_cm" in r:
                e = r["ease_cm"]
                row["plain"] = (f"{abs(e):.1f} cm too tight: the fabric would have to stretch" if e < 0 else
                                f"{e:.1f} cm of room")
                p = EASE_PARAM.get(r["line"])
                if p not in info["params"] and r["line"] in ("hip", "waist") and "chest_ease" in info["params"]:
                    p = "chest_ease"      # straight tops: chest ease widens the whole body piece
                if "TIGHT" in r["status"] and p in info["params"]:
                    need = (-e + 2) if r["line"] != "neckline" else 10
                    if r["line"] == "thigh":   # hip ease adds half as much round one leg
                        need *= 2
                    row["fix"] = {"param": p, "value": round(info["params"][p] + need, 1),
                                  "label": f"Make it {need:.0f}{'%' if r['line'] == 'neckline' else ' cm'} roomier"}
            ease.append(row)
    b = BLOCKS[key]
    # which plain-language option each control is showing (the closest one
    # when the values were set by hand or left at the defaults)
    shown = {}
    for control, opts in PRESETS.get(key, {}).items():
        best, bd = None, 1e9
        for o in opts:
            vals = preset_values(key, {control: o}, bm)
            d = sum(abs(info["params"].get(k, v) - v) for k, v in vals.items())
            if d < bd:
                best, bd = o, d
        shown[control] = {"option": best, "exact": bd < 0.6}
    seams = [{"a": f"{s.panel_a}.{s.edge_a}", "b": f"{s.panel_b}.{s.edge_b}", "ease_pct": round(s.ease * 100, 1),
              "name": s.name} for s in g.meta["seam_defs"]]
    return {"block": key, "params": info["params"], "choices": shown, "defaults": b.defaults(bm),
            "pieces": _pieces_payload(g), "seams": seams,
            "check": {"ok": rep["ok"], "problems": [_explain_problem(p) for p in rep["problems"]],
                      "n_seams": len(seams)},
            "ease": ease, "instructions": instructions(g),
            "yardage": _yardage(g)}


def _yardage(g):
    from ..layout import buy_amount, layout_pieces
    out = {}
    for w in (112, 150):
        try:
            lay = layout_pieces(g.meta["panels"], w, 1.5)
            b = buy_amount(lay["length_cm"])
            out[str(w)] = {"length_cm": round(lay["length_cm"], 1), "yards": float(b["yards"]), "metres": float(b["metres"]),
                           "efficiency": round(lay["efficiency"] * 100)}
        except ValueError as e:
            out[str(w)] = {"error": str(e)}
    return out


# ---------------------------------------------------------- from scratch --
def _garment(req, body, meas, spacing=None):
    """Either a pattern-library block or a hand-made design. Returns (g, params).
    spacing: mesh size (a coarser mesh for quick previews)."""
    if req.get("design"):
        from ..freeform import build_design
        return build_design(req["design"], body, **({"spacing": spacing} if spacing else {})), {}
    if spacing:   # blocks build at their own spacing: go through the editable form
        from ..freeform import build_design, editor_to_design, template_design
        bm = body_measures(body, meas)
        params = preset_values(req["block"], req.get("choices") or {}, bm)
        params.update(_req_params(req))
        d = template_design(req["block"], body, meas, params)
        g = build_design(editor_to_design(d), body, spacing=spacing)
        return g, d["pieces"][0]["place"]["template"]["params"]
    bm = body_measures(body, meas)
    params = preset_values(req["block"], req.get("choices") or {}, bm)
    params.update(_req_params(req))
    g, info = draft_block(req["block"], body, meas, params)
    return g, info["params"]


GARMENTS_MAX = 8
GSEP = "~"          # a merged piece's name: <garment number>~<its own name>


def _garment_design(req, body, meas):
    """One garment of a project as a design (the plain format build_design takes): a hand-made design as it is,
    a pattern-library block through its editable form."""
    if req.get("design"):
        return req["design"]
    from ..freeform import editor_to_design, template_design
    bm = body_measures(body, meas)
    params = preset_values(req["block"], req.get("choices") or {}, bm)
    params.update(_req_params(req))
    return editor_to_design(template_design(req["block"], body, meas, params))


def _merged_design(garments, body, meas):
    """Several garments as one design, inner layer first (the order the user set in Garments: drape never
    reorders layers). Each piece's name gets its garment's number; its fabric is its own or its garment's;
    its garment number (`_garment`) puts its stages after the garments under it (stages.assign). Placement is
    each garment's own, against the plain body: layering is by simulation (MULTI_GARMENT_SPEC constraint 2:
    no garment is pushed outward to make room). The inner garments freeze into the collision grid when the
    next one starts (cloth.ClothSim garment_freeze). Returns (design, {merged piece name: (garment, own name)})."""
    import copy
    if not isinstance(garments, list) or not garments:
        raise ValueError("no garments to simulate")
    if len(garments) > GARMENTS_MAX:
        raise ValueError(f"at most {GARMENTS_MAX} garments move at once: freeze the inner ones")
    out = {"pieces": [], "seams": []}
    names = {}
    for k, gr in enumerate(garments):
        d = copy.deepcopy(_garment_design(gr, body, meas))
        fab = gr.get("fabric") or None
        P = lambda n: f"{k}{GSEP}{n}"                                # noqa: E731
        R = lambda r: P(r.split(".", 1)[0]) + "." + r.split(".", 1)[1]   # noqa: E731
        for pc in d["pieces"]:
            pl = pc.setdefault("place", {})
            for key in ("on", "layer_of", "_lining_of"):
                if pl.get(key):
                    pl[key] = P(pl[key])
            if pl.get("loop"):
                pl["loop"] = [R(r) for r in pl["loop"]]
            if fab and not pc.get("fabric"):
                pc["fabric"] = fab
            pc["_garment"] = k                    # its stages come after the garments under it (stages.assign)
            if gr.get("name"):
                pc["_garment_name"] = str(gr["name"])[:60]
            names[P(pc["name"])] = (k, pc["name"])
            pc["name"] = P(pc["name"])
            out["pieces"].append(pc)
        for s in d["seams"]:
            out["seams"].append({**s, "a": R(s["a"]), "b": R(s["b"])})
        for key in ("spacing_cm", "fine_sdf", "body_offset"):      # gloves' finer settings: the finest asked for
            if d.get(key) is not None:
                out[key] = d[key] if out.get(key) is None else (min(out[key], d[key]) if key != "fine_sdf" else (out[key] or d[key]))
    if len(garments) > 1:
        out["garments_merged"] = True
    return out, names


def api_scratch(req):
    """Build a hand-made design on the avatar (no simulation): where each piece
    starts, the seam checks, steps and yardage. Fast enough to call on every edit."""
    from ..freeform import design_check
    from ..instructions import instructions
    a = S.avatars[req["avatar"]]
    out = {"pieces": [p["name"] for p in req["design"]["pieces"]]}
    try:
        g, _ = _garment(req, a["body"], a["meas"])
    except Exception as e:     # a half-drawn design: say what's wrong, keep editing
        out.update(error=str(e), check=[{"ok": False, "text": "Can't build this yet", "plain": str(e)}])
        return out
    out["preview"] = {**_mesh_payload(g.x, g.tris), "piece": _b64(g.panel_id.astype(np.uint8))}
    out["check"] = design_check(g)
    out["seams"] = g.meta["seam_info"]
    out["elastic"] = g.meta.get("elastic", [])
    # staged sewing: each piece's stage (role / place / the user's choice), each seam's (its later piece)
    out["stages"] = {"seam": [int(k) for k in g.meta.get("design_seam_stage", [])],
                     "piece": dict(zip(g.panel_names, [int(k) for k in g.meta.get("piece_stage", [])])),
                     "piece_auto": dict(zip(g.panel_names, [bool(k) for k in g.meta.get("piece_stage_auto", [])]))}
    if req.get("full"):        # the slower bits only when the Make-it step needs them
        out["instructions"] = instructions(g)
        out["yardage"] = _yardage(g) if g.meta["panels"] else {}
    out["area_m2"] = round(g.meta["fabric_area_m2"], 3)
    return out


def api_to_scratch(req):
    """Turn a pattern-library garment (with the current choices) into an editable design."""
    from ..freeform import template_design
    a = S.avatars[req["avatar"]]
    bm = body_measures(a["body"], a["meas"])
    params = preset_values(req["block"], req.get("choices") or {}, bm)
    params.update(_req_params(req))
    return {"design": template_design(req["block"], a["body"], a["meas"], params)}


def _fit_edges(sim):
    """Edges that measure fit: along and across the grain. The diagonal edges carry
    shear, which a woven gives freely on the bias: that's drape, not tightness."""
    e = sim.g.edges
    try:
        f = sim._aniso()
        weft = 0.5 * (sim._vweft[e[:, 0]] + sim._vweft[e[:, 1]])
        keep = f <= np.maximum(1.0, weft) * 1.05
        if keep.sum() > 0.3 * len(e):
            return e[keep], sim.g.edge_rest[keep]
    except Exception:
        pass
    return e, sim.g.edge_rest


def api_live(req):
    """Everything the in-browser GPU solver needs for this garment."""
    from ..live import live_setup
    a = S.avatars[req["avatar"]]
    spacing = 0.025 if req.get("quality") == "quick" else 0.02
    if req.get("garments"):        # every visible, unfrozen garment at once, in their layer order
        from ..freeform import build_design
        d, _ = _merged_design(req["garments"], a["body"], a["meas"])
        if d.get("spacing_cm") is not None:
            spacing = min(spacing, float(d["spacing_cm"]) / 100)
        g = build_design(d, a["body"], spacing=spacing)
    else:
        g, _ = _garment(req, a["body"], a["meas"], spacing)
    from ..colliders import layered_body       # frozen garments collide like the body (multi-garment, phase 4)
    return live_setup(g, layered_body(a["body"], req.get("colliders"), req.get("collider_mm")), req.get("fabric") or "jersey")


def api_starter(req):
    """A ready-made design (bands, pockets, closures) sized for this avatar."""
    from ..starters import starter
    a = S.avatars[req["avatar"]]
    return {"design": starter(req["key"], a["body"], a["meas"])}


def _version():
    """pyproject.toml's version (a checkout), drape/VERSION (the website's bundle, written by build_site),
    else the installed package's (which can lag behind an editable install)."""
    import re
    here = Path(__file__).resolve().parents[1]
    for f, pat in ((here.parent / "pyproject.toml", r'(?m)^version\s*=\s*"([^"]+)"'), (here / "VERSION", r"(\S+)")):
        try:
            m = re.search(pat, f.read_text(encoding="utf-8"))
            if m:
                return m.group(1)
        except OSError:
            pass
    try:
        from importlib.metadata import version
        return version("drape")
    except Exception:
        return "dev"


def api_edit(req):
    """The design edits that are fiddly by hand, done on the server: open a
    piece down the middle with a closure, a closure on a seam, a zipper or
    placket in part of a seam, in-seam pockets, front hip pockets."""
    import copy
    from .. import dedit as E
    d = copy.deepcopy(req["design"])
    a = req.get("args") or {}
    op = req["op"]
    msg = ""
    cm = lambda k, what, default, hi=300.0: _number(a, k, what, "cm", hi=hi, default=default)   # noqa: E731
    if op == "open_middle":
        lo, hi = E.open_down_middle(d, a["piece"], a.get("kind", "buttons"), holes=a.get("holes", "right"))
        msg = f"Cut '{a['piece']}' into {lo} and {hi}, closed with {E.CLOSURES[a.get('kind', 'buttons')]['label'].lower()}"
    elif op == "closure":         # set / change / remove the closure on a seam
        s = next((x for x in d["seams"] if x["a"] == a["a"] and x["b"] == a["b"]), None)
        if s is None:
            raise ValueError(f"{a['a']} ↔ {a['b']} isn't a seam in this design any more: pick the seam again")
        if not a.get("kind"):
            s.pop("closure", None); msg = "Sewn shut"
        else:
            old = s.get("closure") or {}
            C = E.CLOSURES[a["kind"]]
            L = E.plen(E.epts(d, s["a"]))
            cnt = a.get("count") or (old.get("count") if old.get("type") == a["kind"] else None) \
                or (max(2, int(round(L / 9.0))) if a["kind"] in ("buttons", "snaps") else 1)
            cnt = int(_number({"n": cnt}, "n", "How many", "", lo=1, low_ok=True, hi=200))
            size = float(a.get("size_mm") or (old.get("size_mm") if old.get("type") == a["kind"] else 0) or C["size_mm"])
            size = _number({"s": size}, "s", "Size", "mm", hi=100)
            s["closure"] = {"type": a["kind"], "count": cnt, "size_mm": size,
                            "open": min(1.0, max(0.0, float(a.get("open", old.get("open", 0.0)) or 0.0)))}
            msg = f"{C['label']} on {s['a']} ↔ {s['b']}"
    elif op == "partial_closure":
        a = {**a, "length_cm": cm("length_cm", "Length", None)}
        E.partial_closure(d, a["ref"], a["length_cm"], a.get("kind", "zipper"))
        msg = f"{E.CLOSURES[a.get('kind', 'zipper')]['label']} in the top {a['length_cm']:g} cm of {a['ref']}"
    elif op == "inseam_pocket":
        # placed by the avatar's waist when the studio sends the avatar (any side seam, a dress's
        # too); "from_top_cm" (down the edge from its top) when asked for, or with no avatar
        av = S.avatars.get(req.get("avatar")) if req.get("avatar") else None
        ft = a.get("from_top_cm")
        if ft is None and av is None:
            ft = 6
        ft = None if ft is None else _number({"f": ft}, "f", "Down from the top", "cm", low_ok=True, hi=300)
        bags = E.add_inseam_pocket(d, a["ref"], from_top_cm=ft,
                                   opening_cm=cm("opening_cm", "Opening", 16.0, 100), depth_cm=cm("depth_cm", "Depth", 12.0, 100),
                                   body=av["body"] if av else None, below_waist_cm=a.get("below_waist_cm"))
        msg = f"Pocket bags {', '.join(bags)} hidden in the seam at {a['ref']}"
    elif op == "hip_pocket":
        y = E.add_hip_pocket(d, a["piece"], a.get("waist", "waist"), a.get("side", "outseam"),
                             cm("across_cm", "Across", 10.0, 100), cm("down_cm", "Down", 16.0, 100))
        msg = f"Front hip pocket: '{a['piece']}' has a curved opening, '{y}' sits behind it"
    elif op == "shape":           # cut a shape away / join it on / keep the overlap (one job per piece)
        how = a.get("how", "cut")
        made, notes = [], []
        for job in a["jobs"]:
            m_, n_ = E.shape_with(d, job["piece"], job["tools"], how, src=a.get("src"))
            made += m_
            notes += n_
        done = {"cut": "Cut the shape away from", "join": "Joined the shape onto", "keep": "Trimmed to the shape:"}[how]
        msg = f"{done} {', '.join(dict.fromkeys(j['piece'] for j in a['jobs']))}" + "".join(". " + x for x in notes)
    elif op == "split":           # split pieces by a shape, keeping every part, sewn back together (a contrast midsection)
        jobs = a.get("jobs") or []
        if not isinstance(jobs, list) or len(jobs) > 60:
            raise ValueError("Split: at most 60 pieces at once")
        fab = a.get("fabric") or None
        if fab is not None:
            from ..fabrics import get as get_fabric
            get_fabric(fab)              # an unknown fabric: a message, not a broken design
        if a.get("remove"):           # the piece used as the shape: it goes, its seams with it
            rm = a["remove"]
            E.piece(d, rm)
            d["pieces"] = [p for p in d["pieces"] if p["name"] != rm]
            d["seams"] = [x for x in d["seams"] if x["a"].split(".", 1)[0] != rm and x["b"].split(".", 1)[0] != rm]
            jobs = [j for j in jobs if j.get("piece") != rm]
        inside, made, notes = E.split_with(d, jobs, fabric=fab)
        msg = (f"Split into {len(made)} parts, sewn back together; inside the shape: {', '.join(inside)}"
               + ("" if fab else " (give it its own fabric in its piece panel)") + "".join(". " + x for x in notes))
    elif op == "sleeve":          # a set-in sleeve drafted to fit the armhole edges clicked (both arms with Symmetric)
        from ..freeform import _piece_place, editor_to_design
        av = S.avatars[a.get("avatar") or req.get("avatar")]
        d2 = {p["name"]: p for p in editor_to_design(d)["pieces"]}
        sides = []
        for sd in (a.get("sides") or [])[:2]:
            fref, bref = sd["front"], sd["back"]
            for ref in (fref, bref):
                pn, en = ref.split(".", 1)
                if pn not in d2 or not any(e["name"] == en for e in d2[pn]["edges"]):
                    raise ValueError(f"there is no edge {ref}: pick the armhole edges again")
            X = {}
            for ref in (fref, bref):     # each armhole edge on the body: its side, and which end is the underarm
                pn, en = ref.split(".", 1)
                P = np.asarray(next(e["pts"] for e in d2[pn]["edges"] if e["name"] == en), float) * 0.01
                X[ref] = _piece_place(d2[pn], av["body"])[1](P)
            if X[fref][:, 2].mean() < X[bref][:, 2].mean():      # clicked back first: the front is the one in front
                fref, bref = bref, fref
            # the cap's front half runs underarm -> crown, its back half crown -> underarm
            sides.append((1 if float(X[fref].mean(0)[0]) > 0 else -1, fref, bref,
                          bool(X[fref][0, 1] > X[fref][-1, 1]), bool(X[bref][0, 1] < X[bref][-1, 1])))
        if not sides:
            raise ValueError("Sleeve: click the front armhole edge, then the back one")
        made, notes = E.add_sleeve(d, body_measures(av["body"], av["meas"]), sides, a.get("length", "short"),
                                   a.get("fit", "regular"), a.get("cap", "smooth"))
        msg = f"Sleeve{'s' if len(made) > 1 else ''} {', '.join(made)} drafted to fit the armhole and sewn in" + "".join(". " + x for x in notes)
    elif op == "band":            # a band / collar / hood round an opening, its edges put in order on the body
        from ..freeform import order_loop
        if a["kind"] != "hood":   # a hood isn't a band: always available
            _features.require("OPENING_BANDS")
        loop, split = order_loop(d, S.avatars[a["avatar"]]["body"], a["loop"], hood=a["kind"] == "hood")
        if split:                 # the centre front is inside an edge: cut it there, the hood starts and ends at it
            ref, s_cm, rev = split
            pn, en = ref.split(".", 1)
            d["seams"] = [x for x in d["seams"] if ref not in (x["a"], x["b"])]
            e1, e2 = E.split_edge_at(d, pn, en, [s_cm])
            first, last = (e1, e2) if rev else (e2, e1)
            loop = [f"{pn}.{first}"] + loop[1:] + [f"{pn}.{last}"]
        name = E.add_hood(d, loop, ordered=True) if a["kind"] == "hood" else E.add_band(d, a["kind"], loop)
        msg = f"'{name}' goes round {' → '.join(loop)}"
    elif op == "join_seam":       # two sewn pieces become one
        msg = ". ".join(E.join_along_seam(d, ra, rb) for ra, rb in a["seams"])
    elif op == "layer_copy":      # copies on the layer over the originals
        made = E.layer_copy(d, a["pieces"], a.get("fabric") or None)
        held = sorted({f"{p['name']}.{e}" for p in d["pieces"] if p["name"] in made for e in p["place"]["held"]})
        msg = f"Copied onto the layer over: {', '.join(made)}" + (f". Held to the original along {', '.join(held)}" if held else "")
    else:
        raise ValueError(f"unknown edit {op}")
    return {"design": d, "message": msg}


NEST_MAX = 10      # laser nesting, garments in one file: 1 in 1.9 s, 10 in 27 s, 25 in 413 s (desktop, 2026-11-25)


def _number(req, k, what, unit, lo=0.0, hi=None, low_ok=False, default=None):
    """A number typed into a form, or a message about that number (a typo shouldn't save a fabric the simulator
    can't use, a 0 g square has no mass; or put a million buttons on a seam)."""
    import math
    v = req.get(k)
    if v is None or v == "":
        if default is not None:
            return default
        raise ValueError(f"{what}: fill it in")
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what} {v!r}: that isn't a number") from None
    if not math.isfinite(x) or x < lo or (x == lo and not low_ok) or (hi is not None and x > hi):
        u = f" {unit}" if unit else ""
        if not math.isfinite(x):
            raise ValueError(f"{what}: that isn't a number")
        rng = f"at most {hi:g}" if hi is not None and x > hi else (f"at least {lo:g}" if low_ok else f"more than {lo:g}")
        raise ValueError(f"{what} {x:g}{u}: it needs to be {rng}{u}")
    return x


def _fabric_name(req):
    import re
    return re.sub(r'[<>"`&]', "", (req.get("name") or "My fabric")).strip()[:40] or "My fabric"


def _fabric_tests(req):
    """The kitchen-table tests' numbers (cm, g), checked."""
    sq = _number(req, "square_g", "Weight of the 10 x 10 cm square", "g", hi=200)
    over = _number(req, "overhang_cm", "Sticking out", "cm", hi=100, default=10.0)
    droop = _number(req, "droop_cm", "Tip hangs down", "cm", low_ok=True, hi=over)
    return sq, droop, over


def api_fabric(req):
    """Measure-your-fabric: calibrate, save, add to the list."""
    import re
    from ..calibrate import calibrate, save_user_fabric
    name = _fabric_name(req)
    key = "my_" + (re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "fabric")
    sq, droop, over = _fabric_tests(req)
    load = stretched = None
    if req.get("load_g") not in (None, "") or req.get("stretched_cm") not in (None, ""):
        load = _number(req, "load_g", "Weight hung", "g", hi=1e5)
        stretched = _number(req, "stretched_cm", "Marks now", "cm", hi=1000)
    fab, check = calibrate(name, sq, droop, over, load, stretched, req.get("friction", "normal"))
    save_user_fabric(key, fab)
    FABRICS[key] = fab
    return {"key": key, "fabric": {"name": fab.name, "gsm": round(fab.density * 1000), "bend": fab.bend_compliance,
                                   "stretch": fab.stretch_compliance}, "check": check}


def api_tester_fit(req):
    """Fabric tester readings -> a fabric (saved like My fabric)."""
    import re
    from ..calibrate import save_user_fabric
    from ..tester import fabric_from_tests, parse_csv
    tests = []
    for t in req["tests"]:
        smp = t.get("samples")
        if smp is None and t.get("csv"):
            smp = parse_csv(t["csv"]).tolist()
        tests.append({**t, "samples": smp, "gauge_mm": _number(t, "gauge_mm", "Between the jaws", "mm", hi=1000, default=100.0),
                      "width_mm": _number(t, "width_mm", "Strip width", "mm", hi=1000, default=50.0)})
    name = _fabric_name(req)
    key = "my_" + (re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "fabric")
    sq, droop, over = _fabric_tests(req)
    fab, rep = fabric_from_tests(name, tests, sq, droop, over, req.get("friction", "normal"))
    save_user_fabric(key, fab)
    FABRICS[key] = fab
    return {"key": key, "fabric": {"name": fab.name, "gsm": round(fab.density * 1000)}, "report": rep}


def api_explain(req):
    """'What's wrong here?': the cloth around a tapped point, in plain words."""
    from ..explain import explain
    j = S.jobs[req["job"]]
    z = np.load(Path(j["outdir"]) / "result.npz")
    a = S.avatars[j["avatar"]]
    posed = bool(req.get("posed")) and "pose_frames" in z.files
    X = z["pose_frames"][-1].astype(float) if posed else z["x"]
    return explain(a["body"], X, z["stand"], z["edges"], z["edge_rest"], z["uvw"], z["panel_id"],
                   int(req["vertex"]), json.loads(str(z["params"])), str(z["block"]) or None,
                   pose_label=(req.get("pose_label") if posed else None))


def api_costing(req):
    from ..costing import materials
    a = S.avatars[req["avatar"]]
    g, _ = _garment(req, a["body"], a["meas"])
    return materials(g, _number(req, "fabric_width_cm", "Fabric width", "cm", hi=1000, default=150.0),
                     _number(req, "seam_allowance_cm", "Seam allowance", "cm", low_ok=True, hi=20, default=1.5))


def api_trace(req):
    from ..trace import trace
    from PIL import UnidentifiedImageError
    if req.get("p1") == req.get("p2"):
        raise ValueError("The two points of the known length are the same point: click both ends of it")
    try:
        return trace(req["image"], req["p1"], req["p2"], _number(req, "length_cm", "Known length", "cm", hi=1000),
                     invert=bool(req.get("invert")))
    except (UnidentifiedImageError, ValueError) as e:
        if isinstance(e, UnidentifiedImageError) or "base64" in str(e).lower() or "padding" in str(e).lower():
            raise ValueError("That file isn't a picture this can read: use a PNG or JPEG photo") from None
        raise


def api_pick_girth(req):
    """Girth of the body part at a clicked point (to size a tube or band)."""
    from ..freeform import girth_at
    a = S.avatars[req["avatar"]]
    if req.get("landmark"):
        from ..freeform import landmark
        pt = landmark(a["body"], req["landmark"])[0]
    else:
        pt = np.asarray(req["point"], float)
    gt = girth_at(a["body"], pt)
    return {"girth_cm": None if gt is None else round(gt * 100, 1)}


# ------------------------------------------------------------------ drape --
def _frame_colors(panel, frozen=None):
    """Piece colours for a frame of a drape in progress; pieces not sewn on yet
    (staged sewing) faded toward grey."""
    c = _panel_colors(panel)
    if frozen:
        f = np.isin(panel, frozen)
        c[f] = 0.3 * c[f] + 0.7 * 0.82
    return c


def _drape_worker(q, shape, meas, req, fabric_key, seconds, outdir):
    """Runs in a separate process. Streams in-progress cloth frames, then the
    result; with req["pose"], moves the avatar into that pose afterwards."""
    job = _drape_job(q, shape, meas, req, fabric_key, seconds, outdir)
    if next(job, None) is not None:
        next(job, None)                 # the cloth on the CPU here, then the result


def _drape_job(q, shape, meas, req, fabric_key, seconds, outdir):
    """The drape job as a generator: prepares the garment and its simulator, yields
    (sim, frames), then finishes (fit, ease, pose, result.npz) when resumed.
    Resumed with next(): it steps the cloth itself (the desktop). Resumed with
    send(True): the cloth has been stepped elsewhere and sim holds the result (the web
    build: the GPU in the page, webapi.py). Errors go to q as ("error", ...)."""
    try:
        from ..human import Human
        from ..meshbody import MeshBody
        from ..springs import SpringSimulator
        from ..fabrics import get as get_fabric, panel_fabrics
        from ..render import strain_colors
        q.put(("stage", "Preparing the avatar for collisions (first time only: ~20 s)"))
        body = MeshBody(Human(shape), measurements=meas)
        body.grid  # build / load the collision grid now
        # a move test needs the full mesh: coarse cloth lets limbs slip between vertices
        quick = req.get("quality") == "quick" and not req.get("pose")
        g, params = _garment(req, body, meas, spacing=0.025 if quick else None)   # placed against the body alone
        block = req.get("block")
        fab = get_fabric(fabric_key)
        # frozen garments (multi-garment, phase 4) collide like the body: in its collision grid (colliders.py)
        from ..colliders import layered_body
        if req.get("colliders"):
            q.put(("stage", "Adding the frozen garments"))
        coll = layered_body(body, req.get("colliders"), req.get("collider_mm"))
        sim = SpringSimulator(panel_fabrics(g, fab), coll, fab, substeps=24 if quick else 40)
        if (req.get("design") or {}).get("garments_merged"):   # several garments (_merged_design): one after another,
            sim.start_speed = sim.max_speed                     # each sewn fast, the inner ones frozen into the grid
            sim.garment_freeze = True
        elif g.meta.get("lining_joins"):    # a lining or a layer copy: its layers fly together as sewing starts; with
            sim.start_speed = sim.max_speed  # contacts planned for that, Tyler's dress kept its lining in (1 s: 475 -> 2)
        # staged sewing (body first, then hood / collar / cuffs / pockets) adds ~1.4 s per extra stage
        n = int((seconds + sim.extra_time) * sim.fps)
        staged = sim.n_stages > 1
        if staged:
            nm = [sim.stage_names.get(k) or "the rest" for k in range(2, sim.n_stages + 1)]
            q.put(("stage", " · ".join(["Sewing body", "Settling"] + [f"Attaching {x}" for x in nm] + ["Draping"])))
        else:
            q.put(("stage", "Sewing and draping"))
        last_tris = None
        last_phase = None
        last_frozen = None

        def stream(frac):
            nonlocal last_tris, last_frozen
            tris = None
            frozen = np.unique(sim.g.panel_id[sim._frozen]).tolist() if staged else []
            if last_tris is not sim.g.tris or frozen != last_frozen:   # new triangles (a weld) / pieces woken
                tris = sim.g.tris; last_tris = tris; last_frozen = frozen
            q.put(("frame", {"x": sim.x.astype(np.float32), "tris": tris, "panel": sim.g.panel_id, "t": frac,
                             "frozen": frozen}))
        stepped_elsewhere = yield sim, n
        for f in range(0 if stepped_elsewhere else n):
            if staged:
                k, _, ph = sim.phase()
                if ph != last_phase:
                    last_phase = ph
                    q.put(("stage", f"{ph} (stage {k} of {sim.n_stages})"))
            sim.step()
            if f % 6 == 0:
                q.put(("progress", (f + 1) / n))
            if f % 12 == 0 or f == n - 1:
                stream((f + 1) / n)
        m = sim.metrics()
        fe, fr = _fit_edges(sim)
        fit, vs = strain_colors(sim.x, fe, fr)
        calm = _calm_mask(g, sim)
        vcomf, vlock = vertex_comfort(sim, fab)
        advice = _advise(body, sim.x, np.where(calm, 0.0, vs), block, params,
                         comfy=vcomf, lock=vlock, inside=int(m.get("penetrating_verts", 0) or 0))
        out = {"metrics": _plain(m), "advice": advice}
        if block and (g.meta.get("torso_panels") or g.meta.get("lower")):
            from ..fitcheck import drape_ease      # the tape round the draped garment (A3)
            out["ease"] = drape_ease(sim, body)
        extra = {}
        pose = req.get("pose")
        if pose:
            from ..pose import POSES, smooth
            q.put(("stage", f"Posing the avatar: {POSES[pose]['label'].lower()}"))
            from ..pose import PosedCollider, Skeleton
            col = PosedCollider(body, pose)
            sim.set_posed(col)
            # slack where it's caught (untangle) cuts the worst stretch when sitting (v1.1 tests)
            sim.untangle = True
            stand = sim.x.copy()
            go, hold = 1.4, 1.0
            nf = int((go + hold) * sim.fps)
            frames, ts = [], []
            q.put(("stage", f"Moving: {POSES[pose]['label'].lower()}"))
            for f in range(nf):
                t = smooth(min((f + 1) / (go * sim.fps), 1.0))
                col.advance(t)
                sim.step()
                if f % 3 == 0:
                    frames.append(sim.x.astype(np.float32).copy()); ts.append(t)
                if f % 6 == 0:
                    q.put(("progress", (f + 1) / nf))
            keys = np.linspace(0, 1, 7)
            body_keys = [col.sk.pose(pose, k) for k in keys]
            pfit, pvs = strain_colors(sim.x, *_fit_edges(sim))
            # where things are judged: by their standing position (regions are standing heights)
            padv = _advise(body, stand, np.where(calm, 0.0, pvs), block, params, comfy=vcomf, lock=vlock)
            for a in padv:
                a["text"] = a["text"].replace("Pulling at", f"{POSES[pose]['label']}: pulling at").replace(
                    "No tight spots", f"{POSES[pose]['label']}: no tight spots")
            out["pose"] = {"name": pose, "label": POSES[pose]["label"], "advice": padv,
                           "strain_p99_pct": float(np.percentile(np.abs((np.linalg.norm(sim.x[sim.g.edges[:, 0]] - sim.x[sim.g.edges[:, 1]], axis=1) - sim.g.edge_rest) / sim.g.edge_rest), 99) * 100)}
            extra = dict(pose_frames=np.array(frames), pose_t=np.array(ts), pose_fit=pfit,
                         pose_body=np.array(body_keys, np.float32), pose_keys=keys)
        # inside pieces (pocket bags, yokes) are drawn under the piece over them,
        # so it always shows on top (render layer priority); the
        # simulation and its numbers are untouched
        dp = {pc["name"]: (pc.get("place") or {}) for pc in (req.get("design") or {}).get("pieces", [])}
        nm = {n: i for i, n in enumerate(g.panel_names)}
        ins = [(nm[n], nm.get(pl.get("on"))) for n, pl in dp.items() if pl.get("inside") and n in nm and pl.get("on") in nm]

        def _tuck(X, pid):
            """Each inside vertex ends up at least 3 mm under the piece over it."""
            if not ins:
                return X
            from scipy.spatial import cKDTree
            from ..freeform import _surf
            S_ = _surf(body)
            X = X.copy()
            for bi, hi in ins:
                mb, mh = pid == bi, pid == hi
                if not mb.any() or not mh.any():
                    continue
                db, nb, _ = S_.dist(X[mb])
                H = X[mh]
                dh = S_.dist(H)[0]
                _, j = cKDTree(H).query(X[mb])
                target = np.maximum(dh[j] - 0.003, 0.0008)
                lift = np.clip(db - target, 0, None)
                X[mb] -= nb * lift[:, None]
            return X
        if ins:
            if pose:
                stand = _tuck(stand, sim.g.panel_id)
                extra["pose_frames"] = np.array([_tuck(f_, sim.g.panel_id) for f_ in extra["pose_frames"]])
            else:
                sim.x[:] = _tuck(sim.x, sim.g.panel_id)
        from ..closures import trims as _trims
        tr = _trims(g)
        vm = np.asarray(sim.vmap)
        for t_ in tr:          # welded ids for the main mesh, raw ids for the per-piece (print) mesh
            for k_ in ("v", "a", "b"):
                if k_ in t_:
                    t_[k_ + "0"] = t_[k_]
                    t_[k_] = (vm[np.asarray(t_[k_])]).tolist() if isinstance(t_[k_], list) else int(vm[t_[k_]])
        try:
            from ..stitches import stitch_lines
            for ln in stitch_lines(g, np.arange(len(g.x))):
                ids0 = np.asarray(ln["ids"])
                tr.append({"type": ln["kind"], "ids": vm[ids0].tolist(), "ids0": ids0.tolist(), "bary": ln["bary"]})
        except Exception:
            pass
        out["trims"] = tr
        np.savez_compressed(Path(outdir) / "result.npz", x=sim.x if not pose else stand, tris=sim.g.tris,
                            panel_id=sim.g.panel_id, fit=fit, x0=sim.original_positions(), tris0=g.tris, uv0=g.uv,
                            panel_id0=g.panel_id, panel_names=np.array(g.panel_names),
                            vmap=sim.vmap, edges=sim.g.edges, edge_rest=sim.g.edge_rest, uvw=sim.g.uv,
                            stand=stand if pose else sim.x, params=json.dumps(params), block=str(block or ""), **extra)
        q.put(("done", out))
    except Exception as e:
        q.put(("error", f"{e}\n{traceback.format_exc()}"))


def _plain(m):
    return {k: (v if isinstance(v, bool) else float(v) if isinstance(v, (int, float, np.floating, np.integer)) else v) for k, v in m.items()}


def _calm_mask(g, sim):
    """Vertices meant to be under tension (elastic edges, rib bands): left out of the advice."""
    ev = list(g.meta.get("elastic_verts") or [])
    for pi in g.meta.get("stretchy_panels") or []:
        ev += np.nonzero(g.panel_id == pi)[0].tolist()
    if not ev:
        return np.zeros(len(sim.x), bool)
    from scipy.spatial import cKDTree
    P = sim.x[np.unique(sim.vmap[np.asarray(ev)])]
    return cKDTree(P).query(sim.x, distance_upper_bound=0.04)[0] < 0.04


# ---- fit messages: what is a note and what is a problem (one place, "less is more" spec 1.3) ----
# A point stretched more than SNUG_STRAIN is a snug spot, in any fabric. An area of snug spots is a
# neutral *fit note* ("Snug across the hips") unless its typical stretch (90th percentile) goes past
# what the fabric gives comfortably: COMFORT_SHARE of its lock strain (where the yarns straighten:
# jersey 30%, rib 60%, poplin 4%), never less than COMFORT_MIN. Past that it's a *problem* (red). Each
# point is judged by its own piece's fabric (rib cuffs on a jersey hoodie get rib's allowance).
# Hands are meant to be snug (knit gloves): a note unless they reach HAND_LOCK_SHARE of the lock strain.
# Cloth pushed into the body is a problem from INSIDE_MIN points (fewer is a few points a millimetre
# under the skin, which doesn't show). Jersey: comfortable to 15%; wovens: anything snug is a problem.
SNUG_STRAIN = 0.07
COMFORT_SHARE = 0.5
COMFORT_MIN = 0.07
HAND_LOCK_SHARE = 0.9
INSIDE_MIN = 10


def comfortable_stretch(fab):
    return max(COMFORT_MIN, COMFORT_SHARE * float(getattr(fab, "lock_strain", 0.0)))


def vertex_comfort(sim, fab):
    """Per point (sim's current vertices): (comfortable stretch, lock strain) of its piece's fabric."""
    pf = (sim.g0.meta or {}).get("panel_fabrics") or []
    fabs = [(pf[p] if p < len(pf) and pf[p] else fab) for p in range(len(sim.g.panel_names))]
    comf = np.array([comfortable_stretch(f) for f in fabs])[sim.g.panel_id]
    lock = np.array([float(getattr(f, "lock_strain", 0.1)) for f in fabs])[sim.g.panel_id]
    return comf, lock


def _advise(body, x, vstrain, block, params, comfy=COMFORT_MIN, inside=0, lock=None):
    """Fit advisor: where is the fabric snug or pulling, and what would fix it. Each message has a
    level: "note" (snug, within what the fabric stretches comfortably) or "problem". comfy and lock:
    per point, or one value for the whole garment."""
    comfy = np.broadcast_to(np.asarray(comfy, float), vstrain.shape)
    lock = np.broadcast_to(np.asarray(0.1 if lock is None else lock, float), vstrain.shape)
    over = vstrain / comfy                     # > 1: past what its fabric gives comfortably
    pushed = [{"text": f"Pushed into the body in {int(inside)} places: give it more room there.",
               "level": "problem"}] if inside >= INSIDE_MIN else []
    hot = vstrain > SNUG_STRAIN
    if hot.sum() < 5:
        return pushed or [{"text": "No tight spots: the fabric hangs freely everywhere.", "ok": True}]
    L = body.lines
    out = []
    total = hot.sum()
    # hands and arms first, by the skin underneath (a glove's hand hangs at hip height)
    try:
        from scipy.spatial import cKDTree
        from ..freeform import _surf
        Sf = _surf(body)
        if Sf.regions is not None:
            near = cKDTree(Sf.V).query(x[hot])[1]
            hi_ = np.flatnonzero(hot)
            for key, name in (("hand", "hands & fingers"), ("arm", "arms")):
                on = Sf.regions[key][near] > 0.5
                share = on.sum() / total
                if share >= 0.15:
                    idx = hi_[on]   # hands are meant to be snug: a problem only near the fabric's limit
                    if key == "hand":
                        lvl = "problem" if np.percentile(vstrain[idx] / lock[idx], 90) > HAND_LOCK_SHARE else "note"
                    else:
                        lvl = "problem" if np.percentile(over[idx], 90) > 1 else "note"
                    glove = key == "hand" and share >= 0.5      # most of the snug cloth is on the hand: a glove
                    out.append({"text": f"Snug on the {name}."
                                + (" Knit gloves are meant to fit like this; in a fabric with little stretch, add ease." if glove else ""),
                                "region": name, "share": float(share), "level": lvl})
                hot = hot.copy(); hot[hi_[on]] = False
            if hot.sum() < 5:
                return pushed + out
    except Exception:
        pass
    regions = [("neck & shoulders", L["armpit"] + 0.04, 9), ("upper chest / armholes", L["armpit"] - 0.04, L["armpit"] + 0.04),
               ("bust / chest", L["underbust"], L["armpit"] - 0.04), ("waist", L["waist"] - 0.06, L["underbust"]),
               ("hips", L["crotch"], L["waist"] - 0.06), ("legs", 0.13 * body.height() / 1.7, L["crotch"]),
               ("ankles & feet", -1, 0.13 * body.height() / 1.7)]
    fixes = {"neck & shoulders": [("neck_width", 8), ("armhole_clearance", 1.5)],
             "upper chest / armholes": [("armhole_clearance", 1.5), ("chest_ease", 4)],
             "bust / chest": [("chest_ease", 4), ("bust_dart", 1)],
             "waist": [("waist_ease", 4)], "hips": [("hip_ease", 4), ("chest_ease", 6)], "legs": [("knee_ease", 6), ("hem_width", 6)],
             "ankles & feet": [("hem_above_floor", 4), ("hem_width", 6)]}
    used = set()     # one button per parameter
    for name, lo, hi in regions:
        sel = hot & (x[:, 1] >= lo) & (x[:, 1] < hi)
        share = sel.sum() / total
        if share < 0.15:
            continue
        sug = [(p, d) for p, d in fixes[name] if p in params and p not in used][:1]
        lvl = "problem" if np.percentile(over[sel], 90) > 1 else "note"
        if name == "ankles & feet":
            item = {"text": "The hem is resting on the feet and bunching. Shorter or wider legs will hang cleanly.",
                    "region": name, "share": float(share), "level": "note"}
        elif lvl == "note":
            item = {"text": f"Snug across the {name}.", "region": name, "share": float(share), "level": "note"}
        else:
            item = {"text": f"Pulling at the {name}: tighter than the fabric stretches comfortably.",
                    "region": name, "share": float(share), "level": "problem"}
        if sug:
            p, d = sug[0]
            used.add(p)
            item["fix"] = {"param": p, "value": round(params[p] + d, 1),
                           "label": f"Add {d:g}{'%' if p == 'neck_width' else ' cm'} ({p.replace('_', ' ')})"}
        out.append(item)
    return (pushed + out) or [{"text": "A few small tight spots, nothing to fix.", "ok": True}]


_CLEANUP = []


def _cleanup_at_exit():
    """Each drape leaves its result in a temp folder (exports read it); remove them when the studio closes."""
    if _CLEANUP:
        return
    import atexit
    import shutil

    def clean():
        for j in list(S.jobs.values()):
            p = j.get("proc")
            if p is not None and p.is_alive():
                p.terminate()
            if j.get("outdir"):
                shutil.rmtree(j["outdir"], ignore_errors=True)
    atexit.register(clean)
    _CLEANUP.append(clean)


def api_drape(req):
    a = S.avatars[req["avatar"]]
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    outdir = tempfile.mkdtemp(prefix="drape_job_")
    sub = {k: req.get(k) for k in ("block", "choices", "params", "design", "pose", "quality", "colliders", "collider_mm")}
    garments = req.get("garments")
    if garments:                 # several garments, one simulation, inner layer first (the order set in Garments)
        if len(garments) < 2:
            raise ValueError("several garments: send two or more")
        sub["design"], _ = _merged_design(garments, a["body"], a["meas"])
        sub["block"] = None
        sub["pose"] = None       # moves wait for the single-garment drape (the posed body and frozen garments)
    p = ctx.Process(target=_drape_worker, args=(q, a["shape"], a["meas"], sub,
                                                req.get("fabric", "jersey"), float(req.get("seconds", 3.5)), outdir),
                    daemon=True)
    p.start()
    _cleanup_at_exit()
    jid = uuid.uuid4().hex[:10]
    S.jobs[jid] = dict(proc=p, q=q, progress=0.0, stage="Starting", state="running", result=None, outdir=outdir,
                       avatar=req["avatar"], block=req.get("block"), garments=garments or None)
    return {"job": jid}


def _split_job(jid):
    """A multi-garment drape that finished: one finished job per garment ("<jid>-<k>"), each with its own
    result.npz (its points, triangles, pieces under their own names, fit colours, trims), so the page, the 3D
    view and every export read it as they read a garment draped on its own."""
    j = S.jobs[jid]
    if j.get("split") is not None:
        return j["split"]
    z = np.load(Path(j["outdir"]) / "result.npz")
    names = [str(n) for n in z["panel_names"]]
    gar = np.array([int(n.split(GSEP, 1)[0]) for n in names])
    res = j.get("result") or {}
    out = []
    for k, gr in enumerate(j["garments"]):
        pk = np.flatnonzero(gar == k)
        pnew = -np.ones(len(names), np.int64)
        pnew[pk] = np.arange(len(pk))
        m = gar[z["panel_id"]] == k                       # welded points of this garment
        idx = -np.ones(len(m), np.int64)
        idx[m] = np.arange(m.sum())
        tris = z["tris"][m[z["tris"]].all(1)]
        edges = z["edges"][m[z["edges"]].all(1)] if len(z["edges"]) else z["edges"]
        erest = z["edge_rest"][m[z["edges"]].all(1)] if len(z["edges"]) else z["edge_rest"]
        m0 = gar[z["panel_id0"]] == k                     # the per-piece (print) mesh
        idx0 = -np.ones(len(m0), np.int64)
        idx0[m0] = np.arange(m0.sum())
        tris0 = z["tris0"][m0[z["tris0"]].all(1)]
        outdir = tempfile.mkdtemp(prefix="drape_job_")
        np.savez_compressed(Path(outdir) / "result.npz", x=z["x"][m], tris=idx[tris], panel_id=pnew[z["panel_id"][m]],
                            fit=z["fit"][m], x0=z["x0"][m0], tris0=idx0[tris0], uv0=z["uv0"][m0],
                            panel_id0=pnew[z["panel_id0"][m0]], panel_names=np.array([names[i].split(GSEP, 1)[1] for i in pk]),
                            vmap=idx[z["vmap"][m0]], edges=idx[edges], edge_rest=erest, uvw=z["uvw"][m], stand=z["stand"][m],
                            params=z["params"], block=str(gr.get("block") or ""))
        trims = []
        for t_ in res.get("trims") or []:                 # the trims (buttons, stitching) on this garment's points
            keys = [kk for kk in ("v", "a", "b", "ids") if kk in t_]

            def mine(ids, mask):            # every point id (any nesting) on this garment
                arr = np.asarray(ids, np.int64).ravel()
                return bool(len(arr)) and bool(((arr >= 0) & (arr < len(mask))).all()) and bool(mask[arr].all())

            def remap(ids, table):
                arr = np.asarray(ids, np.int64)
                return int(table[arr]) if arr.ndim == 0 else table[arr].tolist()
            if not keys or not all(mine(t_[kk], m) for kk in keys):
                continue
            t2 = dict(t_)
            for kk in keys:
                t2[kk] = remap(t_[kk], idx)
                if kk + "0" in t_:
                    t2[kk + "0"] = remap(t_[kk + "0"], idx0)
            trims.append(t2)
        cid = f"{jid}-{k}"
        S.jobs[cid] = dict(proc=None, q=queue.Queue(), progress=1.0, stage="Done", state="done", outdir=outdir,
                           avatar=j["avatar"], block=gr.get("block"),
                           result={"metrics": res.get("metrics", {}), "advice": res.get("advice", []), "trims": trims,
                                   "draped_with": len(j["garments"])})
        out.append(cid)
    j["split"] = out
    return out


def api_job(jid):
    j = S.jobs[jid]
    while True:
        try:
            kind, val = j["q"].get_nowait()
        except Exception:
            break
        if kind == "progress":
            j["progress"] = val
        elif kind == "stage":
            j["stage"] = val
        elif kind == "frame":
            j["frame"] = val
            if val["tris"] is not None:
                j["frame_tris"] = val["tris"]; j["frame_panel"] = val["panel"]; j["frame_rev"] = j.get("frame_rev", 0) + 1
                j["frame_frozen"] = val.get("frozen") or []
        elif kind == "done":
            j["state"] = "done"; j["result"] = val
        elif kind == "error":
            j["state"] = "error"; j["error"] = val
    # a worker that died without a word (out of memory, killed, a crash in native code) would leave the job
    # "running" for ever and the page polling it: once it's gone and its queue is empty, it failed
    p = j.get("proc")
    if j["state"] == "running" and p is not None and not p.is_alive():
        j.setdefault("dead_polls", 0)
        j["dead_polls"] += 1
        if j["dead_polls"] >= 3:        # its last messages may still be in the pipe for a moment
            j["state"] = "error"
            j["error"] = (f"The drape stopped unexpectedly (the worker process ended, exit code {p.exitcode}). "
                          "If this keeps happening, try Quick quality or a shorter simulation.")
    out = {"state": j["state"], "progress": j["progress"], "stage": j["stage"]}
    fr = j.get("frame")
    if j["state"] == "running" and fr is not None and fr is not j.get("sent_frame"):
        # the cloth as it is right now (positions every poll, triangles when they change)
        out["frame"] = {"v": _b64(np.round(fr["x"] * 1000).astype(np.int16)), "nv": int(len(fr["x"])), "rev": j["frame_rev"]}
        if j.get("sent_rev") != j["frame_rev"]:
            out["frame"].update(f=_b64(np.asarray(j["frame_tris"], np.uint32)), nf=int(len(j["frame_tris"])),
                                panel=_b64(np.round(_frame_colors(j["frame_panel"], j.get("frame_frozen")) * 255).astype(np.uint8)))
            j["sent_rev"] = j["frame_rev"]
        j["sent_frame"] = fr
    if j["state"] == "error":
        out["error"] = j["error"]
    if j["state"] == "done" and j.get("garments"):     # several garments: each one's own finished job
        out["garment_jobs"] = _split_job(jid)
        return out
    if j["state"] == "done":
        z = np.load(Path(j["outdir"]) / "result.npz")
        out.update(j["result"])
        if "pose_frames" in z.files:
            out["pose_anim"] = {"frames": [_b64(np.round(f * 1000).astype(np.int16)) for f in z["pose_frames"]],
                                "t": z["pose_t"].tolist(), "keys": z["pose_keys"].tolist(),
                                "body": [_b64(np.round(b * 1000).astype(np.int16)) for b in z["pose_body"]],
                                "fit": _b64(np.round(np.clip(z["pose_fit"], 0, 1) * 255).astype(np.uint8))}
        # per-piece (unwelded) mesh with flat pattern coordinates: for prints
        out["cloth_uv"] = {**_mesh_payload(z["x0"], z["tris0"]), "uv": _b64(np.asarray(z["uv0"], np.float32)),
                           "vmap": _b64(np.asarray(z["vmap"], np.uint32)),
                           "pid": _b64(np.asarray(z["panel_id0"], np.uint16)),            # each point's piece (its look)
                           "names": [str(n) for n in z["panel_names"]]}
        out["cloth"] = {**_mesh_payload(z["x"], z["tris"]),
                        "panel": _b64(np.round(_panel_colors(z["panel_id"]) * 255).astype(np.uint8)),
                        "fit": _b64(np.round(np.clip(z["fit"], 0, 1) * 255).astype(np.uint8))}
    return out


def _panel_colors(pid):
    from ..render import garment_colors
    return garment_colors(pid)


# ----------------------------------------------------------------- export --
def _outfit(req):
    """The other garments of a 3D outfit export: req["outfit"] = [{job, fabric, name}], each a finished drape."""
    out = []
    for o in req.get("outfit") or []:
        j = S.jobs.get(o.get("job") or "")
        if j and j.get("state") == "done":
            out.append({"z": np.load(Path(j["outdir"]) / "result.npz"), "fabric": o.get("fabric") or "poplin",
                        "name": str(o.get("name") or "garment"), "trims": (j.get("result") or {}).get("trims")})
    return out


def api_export(req):
    """Returns (filename, mime, bytes). The files are made in a temp folder that goes once they're read."""
    import shutil
    tmp = Path(tempfile.mkdtemp(prefix="drape_export_"))
    try:
        return _export(req, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _safe_name(s, default="my_design"):
    """A request's name for a file: letters, digits, _ and - only (it becomes a path in the temp folder and
    a download header: "../../x" or quotes must not)."""
    import re
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", str(s or "")).strip("_")[:60]
    return s or default


def _export(req, tmp):
    from ..export_dxf import export_pattern_dxf
    from ..printpdf import projector_pdf, tiled_pdf
    from ..layout import layout_image, layout_pieces
    a = S.avatars[req["avatar"]]
    g, _ = _garment(req, a["body"], a["meas"])
    kind = req["kind"]
    name = _safe_name(req.get("block"))
    sa = _number(req, "seam_allowance_cm", "Seam allowance", "cm", low_ok=True, hi=10, default=1.5)
    title = BLOCKS[name].label if name in BLOCKS else (req.get("title") or "My design")
    if kind in ("pdf_letter", "pdf_a4"):
        f = tmp / f"{name}_print_{kind[4:]}.pdf"
        tiled_pdf(g.meta["panels"], g.meta["seam_defs"], f, title, sa_cm=sa, paper=kind[4:])
        return f.name, "application/pdf", f.read_bytes()
    if kind == "projector":
        f = tmp / f"{name}_projector.pdf"
        projector_pdf(g.meta["panels"], g.meta["seam_defs"], f, title, sa_cm=sa)
        return f.name, "application/pdf", f.read_bytes()
    if kind in ("dxf", "dxf_laser"):
        f = tmp / f"{name}_{'laser' if kind == 'dxf_laser' else 'pattern'}.dxf"
        export_pattern_dxf(f, g.meta["panels"], g.meta["seam_defs"], seam_allowance=sa / 100, laser=(kind == "dxf_laser"))
        return f.name, "application/dxf", f.read_bytes()
    if kind == "layout":
        f = tmp / f"{name}_layout.png"
        w = _number(req, "fabric_width_cm", "Fabric width", "cm", hi=1000, default=150.0)
        layout_image(layout_pieces(g.meta["panels"], w, sa), f)
        return f.name, "image/png", f.read_bytes()
    if kind == "laser_nest":
        from ..nest import nest_dxf
        bw = _number(req, "bed_w", "Bed width", "cm", hi=1000, default=60.0)
        bh = _number(req, "bed_h", "Bed height", "cm", hi=1000, default=40.0)
        # each sheet packs every piece still to place: the time grows with the square of the count
        many = int(_number(req, "garments", "Garments", "", lo=1, low_ok=True, hi=NEST_MAX, default=1))
        f = tmp / f"{name}_laser_{bw:g}x{bh:g}.dxf"
        info = nest_dxf(f, g.meta["panels"], g.meta["seam_defs"], bw, bh, sa, many, title)
        return f.name, "application/dxf", f.read_bytes()
    if kind.startswith("sizes_"):
        from ..sizerun import grade_block, grade_design, sizerun_pdf
        table = _safe_name(kind.split("_", 1)[1], "us")
        paper = _safe_name(req.get("paper", "letter"), "letter")
        if req.get("design"):
            from ..freeform import build_design
            from ..pattern import Panel
            graded = []
            for label, d, m, fin in grade_design(req["design"], a["meas"], table):
                P = [Panel(pc["name"], [(e["name"], np.asarray(e["pts"], float) / 100) for e in pc["edges"]], lambda uv: uv)
                     for pc in d["pieces"]]
                from ..closures import layout as _cl
                _cl({p.name: p for p in P}, d.get("seams", []))
                graded.append((label, P, m, fin))
            seams = None
        else:
            G = grade_block(req["block"], req.get("choices") or {}, req.get("params") or {}, table)
            graded = [(l, gg.meta["panels"], m, fin) for l, gg, m, fin in G]
            seams = [gg.meta["seam_defs"] for _, gg, _, _ in G]
        f = tmp / f"{name}_sizes_{table}_{paper}.pdf"
        sizerun_pdf(graded, f, title, sa_cm=sa, paper=paper, units=req.get("units", "in"), seams=seams)
        return f.name, "application/pdf", f.read_bytes()
    if kind == "aama":
        from ..export_aama import export_aama
        f = tmp / f"{name}_AAMA.dxf"
        export_aama(f, g.meta["panels"], g.meta["seam_defs"], sa_cm=sa, size=req.get("size", "custom"), style=title,
                    units="mm" if req.get("units", "in") == "cm" else "in")
        return f.name, "application/dxf", f.read_bytes()
    if kind in ("glb", "blender", "techpack"):
        j = S.jobs.get(req.get("job") or "")
        if not j or j.get("state") != "done":
            raise ValueError("Drape it first (Try on), then export")
        z = np.load(Path(j["outdir"]) / "result.npz")
        fab = req.get("fabric") or "poplin"
        if kind == "techpack":
            from ..fabrics import get as _getf
            from ..techpack import techpack_pdf
            f = tmp / f"{name}_techpack.pdf"
            try:
                flabel = _getf(fab).name
            except Exception:
                flabel = fab
            techpack_pdf(f, g, a["body"], a["meas"], title, flabel, req.get("size", "custom"), sa_cm=sa,
                         draped=(z["stand"] if "stand" in z.files else z["x"], z["tris"], z["panel_id"]),
                         units="cm" if req.get("units", "in") == "cm" else "in")
            return f.name, "application/pdf", f.read_bytes()
        from ..export_gltf import blender_bundle, garment_meshes, write_glb
        glb = tmp / "garment.glb"
        meshes = garment_meshes(z, a["body"], color=req.get("color"), fabric=fab, trims=(j.get("result") or {}).get("trims"))
        for o in _outfit(req):          # the whole outfit (multi-garment): the other visible garments' drapes
            for mm in garment_meshes(o["z"], None, fabric=o["fabric"], trims=o["trims"]):
                mm["name"] = f"{o['name']}: {mm['name']}"
                meshes.append(mm)
        write_glb(glb, meshes)
        if kind == "glb":
            return f"{name}.glb", "model/gltf-binary", glb.read_bytes()
        f = tmp / f"{name}_blender.zip"
        blender_bundle(f, glb, fab)
        return f.name, "application/zip", f.read_bytes()
    if kind == "obj":
        j = S.jobs[req["job"]]
        z = np.load(Path(j["outdir"]) / "result.npz")
        from ..render import write_obj
        f = tmp / f"{name}_draped.obj"
        X, T, U = [z["x0"]], [z["tris0"]], [z["uv0"]]
        for o in _outfit(req):          # the whole outfit: one mesh, every garment's triangles
            T.append(o["z"]["tris0"] + sum(len(x) for x in X)); X.append(o["z"]["x0"]); U.append(o["z"]["uv0"])
        write_obj(f, np.concatenate(X), np.concatenate(T), np.concatenate(U))
        return f.name, "model/obj", f.read_bytes()
    raise ValueError(f"unknown export {kind}")


# ------------------------------------------------------------------- init --
def api_init():
    blocks = []
    for b in BLOCKS.values():
        blocks.append({"key": b.key, "label": b.label, "category": b.category, "description": b.description,
                       "params": [{"name": p.name, "label": p.label, "lo": p.lo, "hi": p.hi, "step": p.step,
                                   "unit": p.unit, "group": p.group, "help": p.help} for p in b.params],
                       "presets": {c: {o: list(vals) for o, vals in opts.items()} for c, opts in PRESETS.get(b.key, {}).items()}})
    examples = {}
    for f in sorted(EXAMPLES.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if "sex" in d:
                examples[f.stem] = d
        except Exception:
            pass
    from ..freeform import LANDMARKS, example_design
    from ..starters import STARTERS
    from ..dedit import CLOSURES
    starters = [{"key": k, "label": t.label, "category": t.category, "blurb": t.blurb, "fabric": t.fabric,
                 "icon": t.icon, "level": t.level} for k, t in STARTERS.items()]
    return {"blocks": blocks, "starters": starters, "closures": {k: v["label"] for k, v in CLOSURES.items()}, "version": _version(), "brand": _brand.as_dict(), "hem_styles": __import__("drape.hems", fromlist=["STYLES"]).STYLES, "examples": examples, "landmarks": LANDMARKS, "example_design": example_design(),
            "fabrics": [{"key": k, "name": f.name, "gsm": round(f.density * 1000), "mine": k.startswith("my_")} for k, f in FABRICS.items()],
            "interfacings": [{"key": k, "name": f.name} for k, f in INTERFACINGS.items()],
            "fields": [f.name for f in fields(Measurements)],
            "features": dict(_features.FEATURES)}


# ------------------------------------------------------------------- http --
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype="application/json", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, default=_jsonable).encode())

    def do_GET(self):
        try:
            if self.path in ("/", "/index.html"):
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            page = _brand.placeholder_page(self.path.split("?")[0])
            if page is not None:   # Terms, Privacy, Source code, Report a bug (brand.py)
                return self._send(200, page, "text/html; charset=utf-8")
            if self.path == "/api/init":
                return self._json(api_init())
            if self.path.startswith("/api/job/"):
                return self._json(api_job(self.path.rsplit("/", 1)[1]))
            if self.path.startswith("/api/guide/"):
                return self._send(200, api_guide(self.path.rsplit("/", 1)[1].split(".")[0]), "image/png")
            f = _static_file(self.path)
            if f is not None:
                return self._send(200, f.read_bytes(),
                                  "text/javascript; charset=utf-8" if f.suffix == ".js" else "text/css; charset=utf-8")
            self._send(404, b'{"error":"not found"}')
        except FeatureOff as e:   # a switched-off feature (drape/features.py)
            self._json({"error": str(e)}, 403)
        except Exception as e:
            self._json({"error": str(e), "trace": traceback.format_exc()}, 500)

    def _foreign(self):
        """A request another website made the visitor's browser send here (the studio listens on 127.0.0.1, or the
        home network with --share): a reason to refuse it, or None. The page's own requests are JSON, from its
        own origin, to an IP address or this computer's name."""
        import ipaddress
        import socket
        from urllib.parse import urlsplit
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            return "requests to the studio are JSON"            # a cross-site form or no-preflight fetch can't be
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            names = {"localhost", socket.gethostname().lower(), socket.gethostname().lower() + ".local"}
            if host not in names:                               # DNS rebinding: someone's domain pointed at us
                return "unknown host name"
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc.lower() != (self.headers.get("Host") or "").lower():   # "null": a sandboxed frame
            return "another website's request"
        return None

    def do_POST(self):
        try:
            why = self._foreign()
            if why:
                return self._json({"error": f"Refused: {why}."}, 403)
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/avatar":
                return self._json(api_avatar(req))
            if self.path == "/api/draft":
                return self._json(api_draft(req))
            if self.path == "/api/scratch":
                return self._json(api_scratch(req))
            if self.path == "/api/to_scratch":
                return self._json(api_to_scratch(req))
            if self.path == "/api/tester_fit":
                return self._json(api_tester_fit(req))
            if self.path == "/api/live":
                return self._json(api_live(req))
            if self.path == "/api/starter":
                return self._json(api_starter(req))
            if self.path == "/api/edit":
                return self._json(api_edit(req))
            if self.path == "/api/explain":
                return self._json(api_explain(req))
            if self.path == "/api/costing":
                return self._json(api_costing(req))
            if self.path == "/api/fabric":
                return self._json(api_fabric(req))
            if self.path == "/api/trace":
                return self._json(api_trace(req))
            if self.path == "/api/girth":
                return self._json(api_pick_girth(req))
            if self.path == "/api/drape":
                return self._json(api_drape(req))
            if self.path == "/api/export":
                fname, mime, data = api_export(req)
                return self._send(200, data, mime, {"Content-Disposition": f'attachment; filename="{fname}"'})
            f = _static_file(self.path)
            if f is not None:
                return self._send(200, f.read_bytes(),
                                  "text/javascript; charset=utf-8" if f.suffix == ".js" else "text/css; charset=utf-8")
            self._send(404, b'{"error":"not found"}')
        except FeatureOff as e:   # a switched-off feature (drape/features.py)
            self._json({"error": str(e)}, 403)
        except Exception as e:
            self._json({"error": str(e), "trace": traceback.format_exc()}, 500)


def _jsonable(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def _lan_ip():
    """This computer's address on the local network (no packets are sent)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def serve(port=8765, open_browser=True, host="127.0.0.1", https=False):
    ip = _lan_ip() if host != "127.0.0.1" else None
    if https:
        from .tls import cert_dir, https_server
        srv = https_server(ThreadingHTTPServer, (host, port), Handler, [ip] if ip else [])
    else:
        srv = ThreadingHTTPServer((host, port), Handler)
    scheme = "https" if https else "http"
    url = f"{scheme}://127.0.0.1:{port}/"
    print(f"{_brand.APP} running at {url}  (Ctrl+C to stop)")
    if host != "127.0.0.1":
        where = ip or "<this computer's IP>"
        print(f"shared on your network: open  {scheme}://{where}:{port}/  on another device")
        print("  anyone on this network can use it while it runs")
        if https:
            print("  the first time, the browser warns the connection isn't private (Spunfection Studio made its own")
            print("  certificate): choose Advanced, then Continue/Proceed. After that live mode works there.")
            print(f"  (certificate kept in {cert_dir()})")
    if open_browser:
        import webbrowser
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return srv
