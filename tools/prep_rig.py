"""One-time: pack MakeHuman's 'game engine' skeleton (CC0, from MPFB2) into
drape/data/rig.npz for posing the avatar (sit / walk / reach tests).

    python tools/prep_rig.py /path/to/mpfb2/src/mpfb/data
"""
import json, sys
from pathlib import Path
import numpy as np

src = Path(sys.argv[1]) / "rigs/standard"
out = Path(__file__).resolve().parents[1] / "drape" / "data" / "rig.npz"
rig = json.load(open(src / "rig.game_engine.json"))
W = json.load(open(src / "weights.game_engine.json"))["weights"]
nb = 13380   # body vertices (helper geometry after this)
# fingers and toes ride with the hand / foot: fewer bones, same look
merge = lambda b: ("hand_" + b[-1]) if any(k in b for k in ("thumb", "index", "middle", "ring", "pinky")) else \
                  ("foot_" + b[-1]) if b.startswith("ball") else b
bones = [b for b in rig if merge(b) == b]
order, seen = [], set()
def visit(b):
    if b in seen: return
    p = rig[b].get("parent")
    if p and p in bones: visit(p)
    seen.add(b); order.append(b)
for b in bones: visit(b)
idx = {b: i for i, b in enumerate(order)}
parent = np.array([idx.get(rig[b].get("parent"), -1) for b in order])
def jname(h):
    if h["strategy"] == "CUBE": return h["cube_name"][len("joint-"):]
    return "mean:" + ",".join(map(str, h["vertex_indices"]))
heads = [jname(rig[b]["head"]) for b in order]
tails = [jname(rig[b]["tail"]) for b in order]
rows = {}
for b, lst in W.items():
    bi = idx[merge(b)] if merge(b) in idx else None
    if bi is None: continue
    for v, w in lst:
        if v < nb:
            rows[(v, bi)] = rows.get((v, bi), 0.0) + w
v = np.array([k[0] for k in rows], np.int32); bi = np.array([k[1] for k in rows], np.int16)
w = np.array(list(rows.values()), np.float32)
tot = np.bincount(v, weights=w, minlength=nb)
w = w / tot[v]
np.savez_compressed(out, bones=np.array(order), parent=parent, heads=np.array(heads), tails=np.array(tails), v=v, b=bi, w=w)
print(len(order), "bones;", len(w), "weights; unweighted verts:", int((tot == 0).sum()), "->", out)
