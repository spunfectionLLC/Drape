"""Import a DXF sewing pattern, preview it, and write an editable spec.

    python import_pattern.py my_pattern.dxf                 # preview + spec with suggested seams
    python import_pattern.py my_pattern.dxf --spec my.json  # use/refine an existing spec
    python import_pattern.py pattern.dxf --seam-allowance 10 --layer CUT

Then drape it:
    python run_demo.py --pattern my_pattern.dxf --spec my_pattern.spec.json [--measurements me.json]

Outputs next to the DXF (or in --out):
  <name>.preview.png   pieces with edge names (e0, e1, ...), lengths and seams by colour
  <name>.spec.json     pieces, placements and seams; edit it, then re-run with --spec
"""
import argparse
import json
from pathlib import Path

from drape import Body
from drape.importer import import_pattern, preview, suggest_seams
from drape.seamcheck import check_seams, format_report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dxf")
    ap.add_argument("--spec")
    ap.add_argument("--layer", help="layer holding the stitch lines (default: SEW if present)")
    ap.add_argument("--seam-allowance", type=float, default=None, help="mm to inset if the file has cut lines only")
    ap.add_argument("--corner-deg", type=float, default=None)
    ap.add_argument("--out")
    a = ap.parse_args()
    dxf = Path(a.dxf)
    out = Path(a.out) if a.out else dxf.parent
    out.mkdir(parents=True, exist_ok=True)
    spec = json.loads(Path(a.spec).read_text()) if a.spec else {}
    if a.layer: spec["layer"] = a.layer
    if a.seam_allowance is not None: spec["seam_allowance_mm"] = a.seam_allowance
    if a.corner_deg is not None: spec["corner_deg"] = a.corner_deg
    spec.setdefault("seams", "auto")

    g, info = import_pattern(dxf, spec, body=Body.default())
    print(f"{len(info['pieces'])} piece(s):")
    for name, kind, edges in info["pieces"]:
        print(f"  {name:12s} placed: {kind:6s} edges: " + ", ".join(f"{n}={l*1000:.0f}mm" for n, l in edges))
    if info["suggested"] is not None:
        print("suggested seams (nearest first, checked for impossible junctions):")
        for s, gap in info["suggested"]:
            print(f"  {s.name:36s} reverse={s.reverse!s:5s} ease={s.ease*100:4.1f}%  ({gap*100:.0f} cm apart before sewing)")
        for s, gap, where in getattr(suggest_seams, "last_rejected", []):
            print(f"  rejected {s.name}: would break junction {where}")
    rep = check_seams(g.meta["panels"], g.meta["seam_defs"])
    print(format_report(rep))

    stem = dxf.stem
    preview(g, out / f"{stem}.preview.png")
    spec_out = {k: v for k, v in spec.items() if k != "seams"}
    spec_out["pieces"] = {name: kind for name, kind, _ in info["pieces"]}
    spec_out["seams"] = [{"a": f"{s.panel_a}.{s.edge_a}", "b": f"{s.panel_b}.{s.edge_b}",
                          "reverse": s.reverse, **({"ease": round(s.ease, 4)} if s.ease else {})}
                         for s in g.meta["seam_defs"]]
    path = out / f"{stem}.spec.json"
    if a.spec and Path(a.spec).resolve() == path.resolve():
        path = out / f"{stem}.spec.new.json"
    path.write_text(json.dumps(spec_out, indent=2))
    print(f"wrote {out / (stem + '.preview.png')} and {path}")


if __name__ == "__main__":
    main()
