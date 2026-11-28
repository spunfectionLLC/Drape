"""How well the avatar reaches a range of bodies (CLAUDE.md "Bodies": every body is valid).

For each body: the fitted avatar's tape vs the numbers given (and what it chose for the ones left on
auto), fit time, and front + side renders in out/avatar_range/ to check the shape looks natural.
    python tools/avatar_range.py [WEIGHT_MAX MEASURE_MAX OVER_COST]
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np

from drape import human
from drape.measurements import Measurements

OUT = Path("out/avatar_range")
OUT.mkdir(parents=True, exist_ok=True)
if len(sys.argv) >= 4:
    human.WEIGHT_MAX, human.MEASURE_MAX, human.OVER_COST = map(float, sys.argv[1:4])
    human.WIDEN = len(sys.argv) < 5 or sys.argv[4] != "nowiden"
tag = f"w{human.WEIGHT_MAX:g}_m{human.MEASURE_MAX:g}_c{human.OVER_COST:g}" + ("" if human.WIDEN else "_nowiden")

# only height, chest, waist, hips given (the rest on auto, as the studio sends them)
BODIES = {
    "female_M": dict(sex="female", height=166, chest=92, waist=74, hip=100),
    "female_plus": dict(sex="female", height=165, chest=125, waist=118, hip=135),
    "female_plus2": dict(sex="female", height=165, chest=140, waist=150, hip=160),
    "female_plus3": dict(sex="female", height=160, chest=160, waist=165, hip=180),
    "male_plus": dict(sex="male", height=180, chest=130, waist=130, hip=125),
    "male_plus2": dict(sex="male", height=178, chest=150, waist=160, hip=150),
    "female_slim": dict(sex="female", height=172, chest=80, waist=60, hip=86),
}
AUTO = ("shoulder_width", "neck", "upper_arm", "arm_length", "thigh", "inseam")


def meas(d):
    m = Measurements(**{k: v for k, v in d.items()})
    for k in ("shoulder_width", "neck", "upper_arm", "arm_length"):   # auto: not a target
        setattr(m, k, None)
    return m


def render(h, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    V, T = h.verts, h.tris[(h.tris < len(h.verts)).all(1)]
    fig, ax = plt.subplots(1, 2, figsize=(6, 6))
    for a, (i, j), t in zip(ax, ((0, 1), (2, 1)), ("front", "side")):
        a.tripcolor(V[:, i], V[:, j], T, np.full(len(T), 0.6), cmap="Greys", vmin=0, vmax=1, shading="flat", edgecolors="none")
        a.set_aspect("equal"); a.axis("off"); a.set_title(t)
        a.set_xlim(-0.45, 0.45); a.set_ylim(0, 2.0)
    fig.savefig(path, dpi=80, bbox_inches="tight"); plt.close(fig)


print(f"limits: weight <= {human.WEIGHT_MAX}, measure targets within +-{human.MEASURE_MAX}, cost past the sliders {human.OVER_COST}")
for name, d in BODIES.items():
    t = time.time()
    h, rows = human.fit_human(meas(d))
    R = {r["measurement"]: r for r in rows}
    given = "  ".join(f"{k} {R[k]['avatar_cm']:.0f}/{d[k]}" for k in ("chest", "waist", "hip"))
    auto = "  ".join(f"{k} {R[k]['avatar_cm']:.0f}" for k in AUTO)
    worst = max(abs(R[k]["avatar_cm"] - d[k]) for k in ("chest", "waist", "hip"))
    print(f"{name:13s} worst {worst:5.1f} cm | {given} | auto: {auto} | weight {h.fit['params']['weight']:.2f} | {time.time() - t:.0f} s", flush=True)
    render(h, OUT / f"{name}_{tag}.png")
