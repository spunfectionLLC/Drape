"""The drape fabric tester (hardware/fabric_tester): turn its readings into
a fabric.

A strip of fabric (gauge length L0, width W) is clamped in the jig and pulled
by a hand crank; an HX711 load cell reads the force, a slide potentiometer the
extension. Pull three strips: one cut along the grain (warp), one across
(weft), one at 45 degrees (bias). The firmware streams "ms,ext_mm,force_N".

    tests = [{"dir": "warp", "gauge_mm": 100, "width_mm": 50, "samples": [[ext_mm, force_N], ...]}, ...]
    fab, report = fabric_from_tests("Linen", tests, square_g=1.6, droop_cm=6.5)
"""
from __future__ import annotations

import numpy as np

G = 9.81
REF_LOAD_G = 500.0          # the calibration's reference strip: 5 cm x 20 cm with this hanging


def parse_csv(text):
    """Firmware / spreadsheet output -> (ext_mm, force_N) rows; header and comment lines skipped.
    Takes "ms,ext_mm,force_N" (3 columns) or "ext_mm,force_N" (2)."""
    rows = []
    for line in str(text).splitlines():
        line = line.strip()
        if not line or line[0] in "#;" or line[0].isalpha():
            continue
        parts = [p for p in line.replace(";", ",").replace("\t", ",").split(",") if p.strip()]
        try:
            vals = [float(p) for p in parts]
        except ValueError:
            continue
        if len(vals) >= 3:
            rows.append((vals[1], vals[2]))
        elif len(vals) == 2:
            rows.append((vals[0], vals[1]))
    return np.array(rows, float).reshape(-1, 2)


def fit_curve(samples, gauge_mm, width_mm):
    """Tension per width (N/m) against strain: initial stiffness k0 (N/m per unit
    strain), the lock strain where it stiffens (knee of a two-line fit), and the
    stiffness after it."""
    S = np.asarray(samples, float).reshape(-1, 2)
    S = S[np.isfinite(S).all(1)]
    if len(S) < 6:
        raise ValueError("too few readings: pull the strip slowly for a few seconds")
    ext, F = S[:, 0], S[:, 1]
    # loading part only, from where it starts taking load
    k = int(np.argmax(F))
    ext, F = ext[:k + 1], F[:k + 1]
    start = np.nonzero(F > max(0.02, 0.01 * F.max()))[0]
    if not len(start):
        raise ValueError("no force reading: is the load cell connected and tared?")
    ext = ext[start[0]:] - ext[start[0]]
    F = F[start[0]:]
    eps = ext / gauge_mm
    T = F / (width_mm / 1000.0)
    order = np.argsort(eps)
    eps, T = eps[order], T[order]
    if eps[-1] <= 1e-4:
        raise ValueError("the strip didn't stretch: check the extension sensor")

    def line(x, y):
        A = np.c_[x, np.ones_like(x)]
        c, res, *_ = np.linalg.lstsq(A, y, rcond=None)
        r = float(res[0]) if len(res) else float(((A @ c - y) ** 2).sum())
        return c, r

    best = None
    for b in range(3, len(eps) - 3):          # two lines, knee at eps[b]
        c1, r1 = line(eps[:b], T[:b])
        c2, r2 = line(eps[b:], T[b:])
        if c1[0] <= 0:
            continue
        if best is None or r1 + r2 < best[0]:
            best = (r1 + r2, b, c1, c2)
    c0, r0 = line(eps, T)
    k0 = max(float(c0[0]), 1.0)
    out = {"k0_N_per_m": k0, "lock_strain": None, "k_after": None, "max_strain": float(eps[-1]),
           "max_force_N": float(F.max())}
    if best is not None:
        _, b, c1, c2 = best
        if c2[0] > 3.0 * c1[0] and best[0] < 0.7 * r0:
            # where the two lines cross, measured from where the first one starts taking load
            knee = (c2[1] - c1[1]) / (c1[0] - c2[0])
            e0 = -c1[1] / c1[0]
            out.update(k0_N_per_m=float(c1[0]), lock_strain=float(max(knee - e0, 1e-3)), k_after=float(c2[0]))
        else:
            out["k0_N_per_m"] = k0
    return out


def stretched_cm_for(k0, load_g=REF_LOAD_G):
    """What the kitchen-table stretch test (5 cm x 20 cm strip, load_g hanging)
    would read for a fabric of initial stiffness k0 (N/m)."""
    T = load_g / 1000.0 * G / 0.05
    return 20.0 * (1.0 + T / k0)


def fabric_from_tests(name, tests, square_g, droop_cm, overhang_cm=10.0, friction="normal"):
    """Bending from the droop test, stretch from the warp strip (through the
    same simulator calibration as the kitchen-table test), weft and bias as
    ratios of the measured stiffnesses, lock strain from the knee."""
    from dataclasses import replace
    from .calibrate import calibrate
    fits = {}
    for t in tests:
        fits[t.get("dir", "warp")] = fit_curve(t["samples"], float(t.get("gauge_mm", 100)), float(t.get("width_mm", 50)))
    if "warp" not in fits:
        raise ValueError("pull at least one strip cut along the grain (warp)")
    kw = fits["warp"]["k0_N_per_m"]
    fab, check = calibrate(name, square_g, droop_cm, overhang_cm, REF_LOAD_G, stretched_cm_for(kw), friction)
    weft = kw / fits["weft"]["k0_N_per_m"] if "weft" in fits else 1.0
    bias = kw / fits["bias"]["k0_N_per_m"] if "bias" in fits else 1.0
    locks = [f["lock_strain"] for f in fits.values() if f["lock_strain"]]
    lock = float(min(locks)) if locks else 10.0
    fab = replace(fab, weft_ratio=float(np.clip(weft, 0.2, 50)), bias_ratio=float(np.clip(bias, 0.2, 100)),
                  lock_strain=float(np.clip(lock, 0.005, 10.0)))
    report = {"check": check, "fits": fits, "weft_ratio": fab.weft_ratio, "bias_ratio": fab.bias_ratio,
              "lock_strain": fab.lock_strain}
    return fab, report
