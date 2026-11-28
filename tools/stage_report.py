"""Staged sewing report (STAGED_SEWING_SPEC section 9): a tee alone, the tee with a
hood sewn in stages (body first), and the same with every seam sewn at once (as
before staging). Prints the neckline rise, armhole offsets and hem rise against the
tee alone, and writes out/stages/{front,side,fit}.png (tee | staged | at once).

    python tools/stage_report.py [--seconds 3.5] [--hood-cm 41]
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def avatar():
    from drape.studio import server as S
    init = S.api_init()
    a = S.api_avatar({"measurements": init["examples"]["female_M"]})
    body = S.S.avatars[a["id"]]["body"]
    body.grid
    return S, a["id"], body


def hooded_tee(S, av, hood_cm=41.0):
    """The tee block as a design, and the same with a hood: hood_cm tall (16" = 41 cm),
    round the neckline (22"-ish across), its crown edges curved like a real hood."""
    from drape import dedit as E
    tee = S.api_to_scratch({"avatar": av, "block": "tee"})["design"]
    d = copy.deepcopy(tee)
    r = S.api_edit({"design": d, "op": "band", "args": {"kind": "hood", "loop": ["front.neck", "back.neck"], "avatar": av}})
    d = r["design"]
    hood = E.piece(d, d["pieces"][-1]["name"])
    if hood_cm:
        V = hood["verts"]
        h0 = max(v[1] for v in V)
        for v in V:                       # stretch it to hood_cm at the crown
            if v[1] > 0:
                v[1] = v[1] * hood_cm / (h0 / 1.12)
        names = [e["name"] for e in hood["edges"]]
        for en in ("top_r", "top_l"):     # the crown bulges out (a cubic, a fifth of the way out)
            i = names.index(en)
            a, b = np.asarray(V[i], float), np.asarray(V[(i + 1) % len(V)], float)
            t = b - a
            nrm = np.array([t[1], -t[0]]) / max(np.linalg.norm(t), 1e-9)
            if nrm[1] < 0:
                nrm = -nrm
            off = 0.2 * np.linalg.norm(t)
            hood["edges"][i]["c1"] = (a + t / 3 + nrm * off).round(3).tolist()
            hood["edges"][i]["c2"] = (a + 2 * t / 3 + nrm * off).round(3).tolist()
    return tee, d


def all_at_once(d):
    d = copy.deepcopy(d)
    for pc in d["pieces"]:              # every piece's sewing order set to 1: today's behaviour
        pc["stage"] = 1
    return d


def drape(d, body, seconds=3.5, fabric="jersey", watch=None):
    from drape.fabrics import get, panel_fabrics
    from drape.freeform import build_design, editor_to_design
    from drape.springs import SpringSimulator
    g = build_design(editor_to_design(d), body)
    fab = get(fabric)
    sim = SpringSimulator(panel_fabrics(g, fab), body, fab, substeps=40)
    n = int((seconds + sim.extra_time) * sim.fps)
    t0 = time.time()
    for _ in range(n):
        if watch:
            watch(sim)
        sim.step()
    sim.wall_s = time.time() - t0
    return g, sim


def measures(g, sim):
    """Neckline / hem heights, armhole centres (original vertex ids, cm-free: m)."""
    X = sim.original_positions()
    ei = g.meta["edge_index"]
    names = {p.name: [e for e, _ in p.edges] for p in g.meta["panels"]}

    def verts(piece, pref):
        return np.concatenate([ei[(piece, e)] for e in names[piece] if e.startswith(pref)])
    neck = np.concatenate([verts("front", "neck"), verts("back", "neck")])
    hem = np.concatenate([verts("front", "hem"), verts("back", "hem")])
    arm = {sd: X[verts(f"sleeve_{sd}", "cap")].mean(0) for sd in ("r", "l")}
    m = sim.metrics()
    return {"neck_y": float(X[neck, 1].mean()), "hem_y": float(X[hem, 1].mean()), "arm": arm,
            "penetrating_verts": m["penetrating_verts"], "strain_max_pct": m["strain_max_pct"],
            "strain_p99_pct": m["strain_p99_pct"], "seam_gap_max_mm": m["seam_gap_max_mm"],
            "sim_s": sim.time, "wall_s": sim.wall_s, "n_stages": sim.n_stages}


def compare(ref, r):
    return {"neck_rise_cm": (r["neck_y"] - ref["neck_y"]) * 100, "hem_rise_cm": (r["hem_y"] - ref["hem_y"]) * 100,
            "armhole_r_cm": float(np.linalg.norm(r["arm"]["r"] - ref["arm"]["r"]) * 100),
            "armhole_l_cm": float(np.linalg.norm(r["arm"]["l"] - ref["arm"]["l"]) * 100),
            "extra_sim_s": r["sim_s"] - ref["sim_s"], "extra_wall_s": r["wall_s"] - ref["wall_s"]}


def render(body, sims, path, yaw, fit=False):
    import imageio.v2 as iio
    from drape.render import Renderer, garment_colors, strain_colors
    x = np.vstack([s.x for s in sims])
    lo, hi = x.min(0), x.max(0)
    span = max(hi[1] - lo[1], hi[0] - lo[0]) + 0.25
    R = Renderer(body, width=420, height=560, scale=560 / span * 0.9,
                 center=(float((lo[0] + hi[0]) / 2), float((lo[1] + hi[1]) / 2)))
    imgs = []
    for s in sims:
        if fit:
            from drape.studio.server import _fit_edges
            col, _ = strain_colors(s.x, *_fit_edges(s))
        else:
            col = garment_colors(s.g.panel_id)
        imgs.append(R.render(s.x, s.g.tris, col, yaw=yaw))
    iio.imwrite(path, np.concatenate(imgs, 1))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seconds", type=float, default=3.5)
    ap.add_argument("--hood-cm", type=float, default=41.0)
    ap.add_argument("--no-render", action="store_true")
    a = ap.parse_args()
    S, av, body = avatar()
    tee, hooded = hooded_tee(S, av, a.hood_cm)
    runs = {}
    for label, d in (("tee", tee), ("staged", hooded), ("at_once", all_at_once(hooded))):
        print(f"{label}…", flush=True)
        g, sim = drape(d, body, a.seconds)
        runs[label] = (g, sim, measures(g, sim))
    ref = runs["tee"][2]
    out = {}
    for label in ("staged", "at_once"):
        c = compare(ref, runs[label][2])
        r = runs[label][2]
        out[label] = {**c, **{k: r[k] for k in ("penetrating_verts", "strain_max_pct", "strain_p99_pct", "seam_gap_max_mm", "n_stages")}}
        print(f"{label:8s} neckline {c['neck_rise_cm']:+.2f} cm · armholes R {c['armhole_r_cm']:.2f} / L {c['armhole_l_cm']:.2f} cm · "
              f"hem {c['hem_rise_cm']:+.2f} cm · stretch max {r['strain_max_pct']:.0f}% p99 {r['strain_p99_pct']:.1f}% · "
              f"inside body {r['penetrating_verts']} · +{c['extra_sim_s']:.1f} s simulated, +{c['extra_wall_s']:.0f} s wall")
    dst = ROOT / "out" / "stages"
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "stages.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    if not a.no_render:
        sims = [runs[k][1] for k in ("tee", "staged", "at_once")]
        render(body, sims, dst / "front.png", yaw=0)
        render(body, sims, dst / "side.png", yaw=90)
        render(body, sims, dst / "fit.png", yaw=0, fit=True)
        print("pictures (tee | staged | at once):", dst)


if __name__ == "__main__":
    main()
