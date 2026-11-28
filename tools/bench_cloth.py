"""Benchmark the cloth solver (springs.SpringSimulator) on the reference garments,
avatars and fabrics.

    python tools/bench_cloth.py                 # all cases
    python tools/bench_cloth.py --cases tee_jersey gloves

Prints one table and writes out/bench/results.json and a render per case
(out/bench/<case>.png).

The bars (the tests'): 0 penetrations, seam gap < 0.01 mm, strain p99 < 6% on the
tee; gloves p95 < 15%.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from drape.fabrics import get, panel_fabrics            # noqa: E402
from drape.springs import SpringSimulator               # noqa: E402

CASES = {   # name: (garment, fabric, avatar, seconds)
    "tee_jersey": ("tee", "jersey", "male_M", 3.5),
    "tee_poplin": ("tee", "poplin", "male_M", 3.5),
    "skirt_poplin": ("a_line_skirt", "poplin", "female_M", 3.5),
    "gloves": ("gloves", "jersey", "male_L", 2.5),
}
KE_SETTLED_UJ = 20.0
_AVATARS = {}


def avatar(key):
    if key not in _AVATARS:
        from drape.human import fit_human
        from drape.measurements import Measurements
        from drape.meshbody import MeshBody
        m = Measurements.load(ROOT / "measurements" / f"{key}.json")
        h, _ = fit_human(m)
        _AVATARS[key] = (MeshBody(h, measurements=m), m)
    return _AVATARS[key]


def garment(kind, body, m):
    if kind == "gloves":
        from drape.freeform import build_design, editor_to_design
        from drape.gloves import glove_design
        return build_design(editor_to_design(glove_design(body, m, "gloves")), body)
    from drape.blocks import draft_block
    return draft_block(kind, body, m)[0]


def run(cls, g, body, fab, seconds):
    sim = cls(panel_fabrics(g, fab), body, fab)
    frames = int(round(seconds * sim.fps))
    subs, settle, t0 = [], 0.0, time.time()
    for k in range(frames):
        sim.step()
        subs.append(sim.nsub_frame)
        ke = 0.5 * float((sim.g.mass[:, None] * sim.v ** 2).sum()) * 1e6
        if ke >= KE_SETTLED_UJ:
            settle = (k + 1) / sim.fps
    wall = time.time() - t0
    m = sim.metrics()
    x, e = sim.x, sim.g.edges
    strain = np.abs(np.linalg.norm(x[e[:, 0]] - x[e[:, 1]], axis=1) - sim.g.edge_rest) / sim.g.edge_rest
    return sim, {
        "substeps_mean": float(np.mean(subs)), "substeps_max": int(max(subs)),
        "kscale": float(m.get("stiffness_scale", 1.0)),
        "wall_per_sim_s": wall / seconds,
        "strain_p95_pct": float(np.percentile(strain, 95) * 100), "strain_p99_pct": float(np.percentile(strain, 99) * 100),
        "max_penetration_mm": max(0.0, -m["min_skin_dist_mm"]), "penetrating_verts": m["penetrating_verts"],
        "seam_gap_mm": m["seam_gap_max_mm"], "settle_s": settle if settle < seconds else None,
        "finite": m["finite"], "kinetic_energy_uJ": m["kinetic_energy_uJ"],
    }


def render(body, sims, path):
    import imageio.v2 as iio
    from drape.render import Renderer, garment_colors
    x = np.vstack([s.x for s in sims])
    lo, hi = x.min(0), x.max(0)
    span = max(hi[1] - lo[1], hi[0] - lo[0]) + 0.25
    R = Renderer(body, width=420, height=520, scale=520 / span * 0.9, center=(float((lo[0] + hi[0]) / 2), float((lo[1] + hi[1]) / 2)))
    imgs = [R.render(s.x, s.g.tris, garment_colors(s.g.panel_id), yaw=30) for s in sims]
    iio.imwrite(path, np.concatenate(imgs, 1))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cases", nargs="*", default=list(CASES), choices=list(CASES))
    ap.add_argument("--no-render", action="store_true")
    a = ap.parse_args()
    out = ROOT / "out" / "bench"
    out.mkdir(parents=True, exist_ok=True)
    rows, results = [], {}
    for name in a.cases:
        kind, fkey, akey, seconds = CASES[name]
        body, m = avatar(akey)
        g = garment(kind, body, m)
        fab = get(fkey)
        print(f"{name}…", flush=True)
        sim, r = run(SpringSimulator, g, body, fab, seconds)
        results[name] = r
        st = f"{r['settle_s']:.2f}" if r["settle_s"] is not None else f"> {seconds}"
        rows.append(f"| {kind} / {fkey} | {r['substeps_mean']:.0f} (max {r['substeps_max']}) | {r['kscale']:.2f} | "
                    f"{r['wall_per_sim_s']:.1f} | {r['strain_p95_pct']:.1f} / {r['strain_p99_pct']:.1f} | "
                    f"{r['max_penetration_mm']:.1f} | {r['seam_gap_mm']:.3f} | {st} |")
        if not a.no_render:
            render(body, [sim], out / f"{name}.png")
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\n| garment / fabric | substeps/frame | kscale | wall s per sim s | strain p95 / p99 % | "
          "max penetration mm | seam gap mm | settle time s (KE < 20 uJ) |")
    print("|---|---|---|---|---|---|---|---|")
    print("\n".join(rows))


if __name__ == "__main__":
    main()
