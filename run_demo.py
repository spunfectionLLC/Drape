"""Sew + drape a garment on the default mannequin.

    python run_demo.py --garment tee      # or: tank
    python run_demo.py --garment tee --bend 1e7 --seconds 4

Outputs (in out/<garment>/):
  drape.gif         sewing + settling animation
  views.png         front / 3-4 / side / back
  fitmap.png        strain map (where the pattern is tight on this body)
  <garment>.obj     draped mesh with per-panel UVs (opens in Blender)
  <garment>_pattern.dxf   flat pattern pieces in mm, seam allowance included
  metrics.json
  viewer.html       interactive 3D view (orbit, zoom, fit map) - open in any browser
  measurement_guide.png   where each measurement is taken on this avatar (realistic avatar only)
"""
import argparse
import json
import time
from pathlib import Path

import imageio.v2 as iio
import numpy as np

from drape import Body, Fabric, Simulator
from drape.export_dxf import export_pattern_dxf
from drape.fitcheck import ease_report, format_ease
from drape.garments import a_line_skirt_for, tank_top, tshirt, tshirt_for
from drape.measurements import Measurements, body_from_measurements, body_report
from drape.render import Renderer, garment_colors, legend_bar, strain_colors, write_obj
from drape.seamcheck import check_seams, format_report

GARMENTS = {"tank": lambda body: tank_top(body=body), "tee": lambda body: tshirt(body=body),
            "skirt": lambda body: a_line_skirt_for(getattr(body, "measurements", None) or Measurements(), body=body)}


def make_body(meas, mannequin=False):
    """Realistic MakeHuman avatar fitted to the measurements (default), or the
    old capsule mannequin."""
    if mannequin:
        body = body_from_measurements(meas)
        rows = body_report(body, meas)
        title = "MANNEQUIN vs MEASUREMENTS (virtual tape)"
    else:
        from drape.human import fit_human
        from drape.meshbody import MeshBody
        t0 = time.time()
        h, rows = fit_human(meas)
        body = MeshBody(h, measurements=meas)
        title = f"AVATAR ({meas.sex}, fitted in {time.time() - t0:.0f} s) vs MEASUREMENTS (virtual tape)"
    lines = []
    for r in rows:
        if r["target_cm"] is None:
            lines.append(f"  {r['measurement']:15s} {'(not given)':>16s}   avatar {r['avatar_cm']:7.2f} cm")
        else:
            lines.append(f"  {r['measurement']:15s} target {r['target_cm']:7.1f} cm   avatar {r['avatar_cm']:7.2f} cm   ({r['error_cm']:+.2f} cm)")
    body.report_text = title + "\n" + "\n".join(lines)
    return body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--garment", choices=GARMENTS, default="tee")
    ap.add_argument("--seconds", type=float, default=3.5)
    ap.add_argument("--bend", type=float, default=None, help="override bend compliance (bigger = floppier)")
    ap.add_argument("--stretch", type=float, default=None, help="override stretch compliance")
    ap.add_argument("--friction", type=float, default=None, help="override friction")
    ap.add_argument("--measurements", help="JSON file of body measurements in cm (see measurements/)")
    ap.add_argument("--draft", action="store_true", help="draft the tee to the measurements instead of the stock pattern")
    ap.add_argument("--draft-for", help="draft the tee to THIS measurements file (e.g. an M tee on an L body)")
    ap.add_argument("--strict", action="store_true", help="stop if the seam check finds problems")
    ap.add_argument("--mannequin", action="store_true",
                    help="use the old capsule mannequin instead of the realistic MakeHuman avatar")
    ap.add_argument("--pattern", help="DXF pattern to import instead of a built-in garment")
    ap.add_argument("--spec", help="JSON spec for --pattern (see import_pattern.py)")
    ap.add_argument("--fabric", default="jersey", help="fabric preset (see drape/fabrics.py)")
    ap.add_argument("--seam-allowance", type=float, default=10.0, help="mm")
    ap.add_argument("--no-self-collision", action="store_true")
    ap.add_argument("--no-gif", action="store_true")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    tag = (Path(a.pattern).stem if a.pattern else a.garment) + (f"_{Path(a.measurements).stem}" if a.measurements else "")
    if a.draft or a.draft_for:
        tag += "_drafted" + (f"_for_{Path(a.draft_for).stem}" if a.draft_for else "")
    out = Path(a.out) / tag
    out.mkdir(parents=True, exist_ok=True)
    reports = []

    # ---- avatar
    meas = Measurements.load(a.measurements) if a.measurements else Measurements()
    for w in meas.validate():
        print("WARNING:", w)
    body = make_body(meas, a.mannequin)
    reports.append(body.report_text)
    print(body.report_text)

    if getattr(body, "kind", "") == "mesh":
        from dataclasses import asdict
        from drape.render import measurement_guide
        tg = {k: v for k, v in asdict(meas).items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
        iio.imwrite(out / "measurement_guide.png", measurement_guide(body, tg, title=Path(a.measurements).stem if a.measurements else "avatar"))

    # ---- garment
    if a.pattern:
        from drape.importer import import_pattern
        spec = json.loads(Path(a.spec).read_text()) if a.spec else {"seams": "auto"}
        garment, _info = import_pattern(a.pattern, spec, body=body)
    elif a.draft or a.draft_for:
        mg = Measurements.load(a.draft_for) if a.draft_for else meas
        if a.garment == "skirt":
            garment = a_line_skirt_for(mg, body=body)
        elif a.garment == "tee":
            draft_body = make_body(mg, a.mannequin) if a.draft_for else body
            garment = tshirt_for(mg, body=body, draft_body=draft_body)
        else:
            ap.error("--draft is available for the tee and the skirt")
    else:
        garment = GARMENTS[a.garment](body)

    # ---- sewing checks (before simulating)
    rep = check_seams(garment.meta["panels"], garment.meta["seam_defs"])
    txt = format_report(rep); print(txt); reports.append(txt)
    if a.strict and not rep["ok"]:
        (out / "report.txt").write_text("\n\n".join(reports))
        raise SystemExit("seam check failed (--strict)")
    if garment.meta.get("hem_y") is not None:
        txt = "EASE (garment minus body)\n" + format_ease(ease_report(garment, body))
        print(txt); reports.append(txt)
    dxf = export_pattern_dxf(out / f"{a.garment}_pattern.dxf", garment.meta["panels"],
                             garment.meta["seam_defs"], seam_allowance=a.seam_allowance / 1000)
    print("pattern DXF:", {k: f"{v['cut_bbox_mm'][0]:.0f}x{v['cut_bbox_mm'][1]:.0f} mm" for k, v in dxf.items()})

    from dataclasses import replace as _replace
    from drape.fabrics import get as get_fabric
    fabric = get_fabric(a.fabric)
    over = {k: v for k, v in (("bend_compliance", a.bend), ("stretch_compliance", a.stretch),
                              ("friction", a.friction)) if v is not None}
    fabric = _replace(fabric, **over)
    print(f"fabric: {fabric.name} ({fabric.density * 1000:.0f} g/m2)")
    sim = Simulator(garment, body, fabric, self_collision=not a.no_self_collision)
    print(f"mesh: {len(garment.x)} verts, {len(garment.tris)} tris, {len(garment.seams)} seam pairs")

    # frame the garment (whatever it is: top, skirt...) with a little body around it
    y0, y1 = float(garment.x[:, 1].min()), float(garment.x[:, 1].max())
    cy, span = 0.5 * (y0 + y1) - 0.03, (y1 - y0) + 0.35
    small = Renderer(body, width=360, height=440, scale=440 / span * 0.95, center=(0.0, cy))
    frames, t0 = [], time.time()
    for f in range(int(a.seconds * sim.fps)):
        sim.step()
        if not a.no_gif and f % 3 == 0:
            frames.append(small.render(sim.x, sim.g.tris, garment_colors(sim.g.panel_id), yaw=30))
    wall = time.time() - t0
    m = sim.metrics()
    m.update(garment=a.garment, wall_seconds=round(wall, 1), sim_seconds=a.seconds,
             realtime_factor=round(a.seconds / wall, 3), fabric=fabric.name)
    print(json.dumps(m, indent=2))

    big = Renderer(body, width=480, height=560, scale=560 / span * 0.95, center=(0.0, cy))
    col = garment_colors(sim.g.panel_id)
    iio.imwrite(out / "views.png", np.concatenate(
        [big.render(sim.x, sim.g.tris, col, yaw=y) for y in (0, 35, 90, 180)], 1))
    fcol, _ = strain_colors(sim.x, sim.g.edges, sim.g.edge_rest)
    fit = np.concatenate([big.render(sim.x, sim.g.tris, fcol, yaw=y) for y in (0, 90, 180)], 1)
    iio.imwrite(out / "fitmap.png", np.concatenate([fit, legend_bar(fit.shape[0])], 1))
    if frames:
        iio.mimsave(out / "drape.gif", frames, duration=0.05, loop=0)
    from drape.viewer import export_viewer
    export_viewer(out / "viewer.html", body, sim.x, sim.g.tris, sim.g.panel_id, sim.g.edges, sim.g.edge_rest,
                  title=f"drape · {tag}",
                  info={"subtitle": f"{fabric.name}", "stats": {
                      "p99 strain": f"{m['strain_p99_pct']:.1f}%", "in body": f"{m['penetrating_verts']} points",
                      "seams": "closed" if m["seam_gap_max_mm"] < 1 else f"gap {m['seam_gap_max_mm']:.1f} mm"}})
    # export on the original per-panel mesh so every panel keeps its own flat UVs
    write_obj(out / f"{a.garment}.obj", sim.original_positions(), garment.tris, garment.uv)
    (out / "metrics.json").write_text(json.dumps(m, indent=2))
    reports.append("SIMULATION\n" + json.dumps(m, indent=2))
    (out / "report.txt").write_text("\n\n".join(reports))
    print("wrote", out)


if __name__ == "__main__":
    main()
