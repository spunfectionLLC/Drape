"""One-time: pack the MakeHuman / MPFB2 assets drape uses (CC0) into
drape/data/makehuman.npz.

    git clone --depth 1 --filter=blob:none --sparse https://github.com/makehumancommunity/mpfb2
    (sparse-checkout src/mpfb/data/{3dobjs,targets/...,rigs/standard})
    python tools/prep_makehuman.py /path/to/mpfb2/src/mpfb/data

Units: MakeHuman uses decimetres, y up, facing +z. Stored in metres.
"""
import gzip, json, sys
from itertools import product
from pathlib import Path
import numpy as np

src = Path(sys.argv[1])
out = Path(__file__).resolve().parents[1] / "drape" / "data" / "makehuman.npz"

V, groups, grp = [], {}, None
for line in open(src / "3dobjs/base.obj"):
    if line.startswith("v "):
        V.append([float(x) for x in line.split()[1:4]])
    elif line.startswith("g "):
        grp = line.split()[1]
    elif line.startswith("f "):
        groups.setdefault(grp, []).append([int(t.split("/")[0]) - 1 for t in line.split()[1:]])
V = np.array(V) * 0.1
body = np.array(groups["body"])
tris = np.concatenate([body[:, [0, 1, 2]], body[:, [0, 2, 3]]]).astype(np.int32)
joints = {g[len("joint-"):]: np.unique(np.array(f).ravel()).astype(np.int32)
          for g, f in groups.items() if g.startswith("joint-")}

def load_target(path):
    idx, d = [], []
    with gzip.open(path, "rt") as fh:
        for line in fh:
            t = line.split()
            if len(t) == 4 and not line.startswith("#"):
                idx.append(int(t[0])); d.append([float(x) for x in t[1:]])
    return np.array(idx, np.uint16), (np.array(d) * 0.1).astype(np.float16)

T = src / "targets"
names = []
M, W = ("minmuscle", "averagemuscle", "maxmuscle"), ("minweight", "averageweight", "maxweight")
for g, m, w in product(("female", "male"), M, W):
    names.append(f"macrodetails/universal-{g}-young-{m}-{w}")
    for h in ("minheight", "maxheight"):
        names.append(f"macrodetails/height/{g}-young-{m}-{w}-{h}")
for r, g in product(("african", "asian", "caucasian"), ("female", "male")):
    names.append(f"macrodetails/{r}-{g}-young")
for m, w, c, f in product(M, W, ("mincup", "averagecup", "maxcup"), ("minfirmness", "averagefirmness", "maxfirmness")):
    names.append(f"breast/female-young-{m}-{w}-{c}-{f}")
for part, items in {
    "torso": ["measure-bust-circ", "measure-underbust-circ", "measure-waist-circ", "measure-hips-circ",
              "measure-shoulder-dist", "measure-napetowaist-dist", "measure-waisttohip-dist", "measure-frontchest-dist"],
    "neck": ["measure-neck-circ", "measure-neck-height"],
    "arms": ["measure-upperarm-circ", "measure-upperarm-length", "measure-lowerarm-length"],
    "legs": ["measure-thigh-circ", "measure-calf-circ", "measure-upperleg-height", "measure-lowerleg-height"],
    "buttocks": ["buttocks-volume"],
    "breast": ["nipple-point", "nipple-size"],
    "stomach": ["stomach-pregnant"],
}.items():
    for it in items:
        base = it if it.startswith("measure") or it.startswith("buttocks") or it.startswith("stomach") else it
        for s in ("decr", "incr"):
            names.append(f"{part}/{base}-{s}")

arrays = {"V": V.astype(np.float32), "tris": tris}
found = []
for n in names:
    p = T / f"{n}.target.gz"
    if not p.exists():
        continue
    i, d = load_target(p)
    key = n.split("/")[-1]
    arrays[f"t_idx/{key}"], arrays[f"t_d/{key}"] = i, d
    found.append(key)
for k, v in joints.items():
    arrays[f"joint/{k}"] = v

# skin-weight regions (for slicing the torso apart from limbs, and landmarks)
w = json.load(open(src / "rigs/standard/weights.default.json"))["weights"]
region_of = lambda b: ("hand" if any(k in b for k in ("hand", "finger", "wrist", "metacarpal"))
                       else "arm" if any(k in b for k in ("upperarm", "lowerarm"))
                       else "foot" if any(k in b for k in ("foot", "toe"))
                       else "leg" if any(k in b for k in ("upperleg", "lowerleg"))
                       else "head" if any(k in b for k in ("head", "jaw", "eye", "tongue", "ear", "lip", "nose", "brow", "cheek", "temple", "oris", "levator", "risorius", "orbicularis", "mandible"))
                       else "torso")
nb = 13380
acc = {r: np.zeros(nb) for r in ("torso", "arm", "hand", "leg", "foot", "head")}
for b, lst in w.items():
    r = region_of(b)
    for vi, wt in lst:
        if vi < nb:
            acc[r][vi] += wt
for r, a in acc.items():
    arrays[f"region/{r}"] = a.astype(np.float16)
np.savez_compressed(out, **arrays)
print(f"{len(found)} targets of {len(names)} requested; joints {len(joints)}; wrote {out} ({out.stat().st_size/1e6:.1f} MB)")
missing = sorted(set(n.split('/')[-1] for n in names) - set(found))
print("missing:", missing[:10], "..." if len(missing) > 10 else "")
