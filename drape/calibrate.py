"""Measure your own fabric: three kitchen-table tests -> a fabric preset.

1. Weight: cut a 10 x 10 cm square and weigh it (a kitchen scale in grams).
2. Droop: a strip 5 cm wide lying on a table, pushed 15 cm out over the edge.
   Measure how far its tip hangs below the table top.
3. Stretch: hang a strip 5 cm wide, mark 20 cm on it, hang a weight from the
   bottom (a water bottle in a bag), measure the marks again.

The same tests are run in the simulator; the bending and stretch
compliances are searched (bisection on a log scale) until the simulated
droop and stretch match yours. Everything is at the garment mesh size
(15 mm), so the numbers mean the same as the built-in presets.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .pattern import Panel, build_garment, line
from .cloth import Fabric
from .springs import SpringSimulator

USER_FILE = Path.home() / ".drape" / "fabrics.json"
SPACING = 0.015


class _NoBody:
    """Nothing to collide with (the test strip hangs in the air)."""
    kind = "analytic"

    def __init__(self):
        from .body import Body
        b = Body.default()
        self.torso, self.caps, self.blend, self.extras, self.groups = b.torso, b.caps, b.blend, b.extras, b.groups

    def sdf(self, p):
        return np.full(len(np.atleast_2d(p)), 1.0)


def _strip(w, L, place):
    p = Panel("strip", [("a", line((0, 0), (L, 0))), ("b", line((L, 0), (L, w))),
                        ("c", line((L, w), (0, w))), ("d", line((0, w), (0, 0)))], place)
    return build_garment([p], [], spacing=SPACING)


def droop_sim(bend, density, overhang=0.15, held=0.05, width=0.05, seconds=2.5):
    """Tip drop (m) of a strip pushed `overhang` out over a table edge."""
    return _droop(bend, density, overhang, held, width, seconds)[0]


def _droop(bend, density, overhang=0.15, held=0.05, width=0.05, seconds=2.5):
    """(tip drop, tip's horizontal reach past the table edge), m."""
    far = np.array([5.0, 1.0, 0.0])
    g = _strip(width, overhang + held, lambda uv: far + np.c_[uv[:, 0] - held, np.zeros(len(uv)), uv[:, 1]])
    f = Fabric("t", density, 1e-8, bend, 0.004, 0.003, 0.0, 0.05)
    sim = SpringSimulator(g, _NoBody(), f, self_collision=False, weld=False)
    sim.sew_time = 0.0; sim.gravity_ramp = 0.2
    sim.pin(np.nonzero(g.uv[:, 0] <= held + 1e-9)[0])
    for _ in range(int(seconds * sim.fps)):
        sim.step()
    tip = g.uv[:, 0] > overhang + held - 1e-6
    return float(far[1] - sim.x[tip, 1].mean()), float(sim.x[tip, 0].mean() - far[0])


def stretch_sim(stretch, density, load_kg, length=0.20, width=0.05, seconds=2.5):
    """Extension (m) of a `length` strip hanging with load_kg on its bottom edge."""
    far = np.array([5.0, 1.0, 0.0])
    g = _strip(width, length, lambda uv: far + np.c_[uv[:, 1], -uv[:, 0], np.zeros(len(uv))])
    bottom = np.nonzero(g.uv[:, 0] >= length - 1e-9)[0]
    from dataclasses import replace
    mass = g.mass.copy(); mass[bottom] += load_kg / len(bottom)
    g = replace(g, mass=mass, meta={**g.meta, "density": density})
    f = Fabric("t", density, stretch, 1e-2, 0.004, 0.003, 0.0, 0.08)
    sim = SpringSimulator(g, _NoBody(), f, self_collision=False, weld=False)
    sim.sew_time = 0.0; sim.gravity_ramp = 0.3
    sim.pin(np.nonzero(g.uv[:, 0] <= 1e-9)[0])
    for _ in range(int(seconds * sim.fps)):
        sim.step()
    return float(-(sim.x[bottom, 1].mean() - far[1]) - length)


def _fit(fn, target, lo, hi, iters=12, increasing=True):
    """Bisection on log10(compliance) for fn(c) == target."""
    a, b = np.log10(lo), np.log10(hi)
    for _ in range(iters):
        m = 0.5 * (a + b)
        v = fn(10 ** m)
        if (v < target) == increasing:
            a = m
        else:
            b = m
    return 10 ** (0.5 * (a + b))


D1388_SLOPE = float(np.tan(np.radians(41.5)))     # 0.885: drop / horizontal reach of the tip


def bend_for_bending_length(c_cm, density):
    """Bending compliance for a bending length c (the standard cantilever
    test, ASTM D1388): sticking out 2c, the strip's tip reaches the line 41.5 deg
    below the table edge, i.e. its drop is 0.885 x its *horizontal* reach (not x the
    overhang: the strip curls in, so that would be a much floppier fabric; the heavy
    elastica gives drop = 0.646 x overhang there, Peirce's B = w c^3)."""
    L = 2 * c_cm / 100.0

    def slope(k):
        dy, dx = _droop(k, density, overhang=L)
        return dy / max(dx, 1e-6)
    return _fit(slope, D1388_SLOPE, 1.0, 1e8)


def calibrate(name, square_g, droop_cm, overhang_cm=10.0, load_g=None, stretched_cm=None, friction="normal"):
    """Your measurements -> a Fabric (and how well the simulation matches)."""
    density = square_g / 1000.0 / 0.01                      # 10 x 10 cm = 0.01 m^2
    L = float(overhang_cm) / 100.0
    droop = max(0.002, min(0.97 * L, float(droop_cm) / 100.0))
    bend = _fit(lambda c: droop_sim(c, density, overhang=L), droop, 1.0, 1e8)
    out = {"droop_cm": round(droop_sim(bend, density, overhang=L) * 100, 2),
           "bending_length_cm": None}
    if float(droop_cm) >= 0.95 * float(overhang_cm):
        out["note"] = "It hangs almost straight down at that overhang: measure again with a shorter overhang (5 cm) for a sharper number."
    stretch = 1e-7
    if load_g and stretched_cm:
        ext = max(0.0, float(stretched_cm) - 20.0) / 100.0
        load = float(load_g) / 1000.0
        if ext < 0.0005:
            stretch = 1e-9
        else:
            stretch = _fit(lambda c: stretch_sim(c, density, load), ext, 1e-7, 1e-1, iters=10)
        out["stretched_cm"] = round(20 + stretch_sim(stretch, density, load) * 100, 2)
    mu = {"slippery": 0.15, "normal": 0.4, "grippy": 0.6}.get(friction, 0.4)
    thick = 0.003 + min(0.004, density / 100)
    fab = Fabric(name, density, stretch, bend, thick, thick - 0.001, mu, 0.02)
    return fab, out


# ------------------------------------------------------------ your fabrics --
def _usable(f: Fabric):
    """A saved fabric the simulator can use: positive, finite numbers (an old file may hold a 0 g square)."""
    import math
    return all(math.isfinite(v) and v > 0 for v in (f.density, f.bend_compliance, f.stretch_compliance, f.thickness))


def load_user_fabrics():
    """Your fabrics, one by one: an entry this copy can't read (a newer version's, a damaged one) is skipped,
    not the whole file. Names are kept plain text (they go into the page)."""
    import re
    from dataclasses import fields
    if not USER_FILE.exists():
        return {}
    try:
        raw = json.loads(USER_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    known = {f.name for f in fields(Fabric)}
    out = {}
    for k, v in (raw.items() if isinstance(raw, dict) else ()):
        try:
            f = Fabric(**{a: b for a, b in v.items() if a in known})
            f.name = re.sub(r'[<>"`&]', "", str(f.name))[:40] or "My fabric"
            if _usable(f):
                out[k] = f
        except Exception:
            continue
    return out


def save_user_fabric(key, fab: Fabric):
    """Add or replace one fabric. Written atomically; a file that can't be read is kept as fabrics.json.bad
    (never overwritten with just the new fabric)."""
    import os
    d = {}
    if USER_FILE.exists():
        try:
            d = json.loads(USER_FILE.read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                raise ValueError("not a list of fabrics")
        except Exception:
            os.replace(USER_FILE, USER_FILE.with_suffix(".json.bad"))
            d = {}
    d[key] = asdict(fab)
    USER_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = USER_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    os.replace(tmp, USER_FILE)
