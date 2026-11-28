"""Move the avatar: sit, walk, reach. For checking that a garment still works
when you move in it (trousers that bind when sitting, sleeves that pull when
reaching).

The avatar is skinned with MakeHuman's game-engine skeleton (CC0, packed by
tools/prep_rig.py). A pose is a few joint rotations; the body is posed by
linear blend skinning. For the cloth, the moving body is a series of
signed-distance grids on one shared box (keyframes along the motion) that
are blended frame by frame.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

RIG = Path(__file__).parent / "data" / "rig.npz"

# rotations (axis in the avatar's world frame at rest, degrees); x = the
# avatar's left, y = up, z = forward. Children inherit their parent's turn.
POSES = {
    "sit": {"label": "Sitting", "help": "hips and knees bent 90°: does it bind at the seat, waist or knees?",
            "rot": {"thigh_l": ([1, 0, 0], -88), "thigh_r": ([1, 0, 0], -88),
                    "calf_l": ([1, 0, 0], 88), "calf_r": ([1, 0, 0], 88)}},
    "walk": {"label": "Walking stride", "help": "a long step: is there room across the thighs and at the hem?",
             "rot": {"thigh_l": ([1, 0, 0], -32), "calf_l": ([1, 0, 0], 20), "thigh_r": ([1, 0, 0], 18),
                     "calf_r": ([1, 0, 0], 22), "upperarm_l": ([1, 0, 0], 18), "upperarm_r": ([1, 0, 0], -18)}},
    "reach_up": {"label": "Arms up", "help": "reaching overhead: does the hem ride up, do the armholes pull?",
                 "rot": {"upperarm_l": ([0, 0, 1], 95), "upperarm_r": ([0, 0, 1], -95)}},
    "reach_forward": {"label": "Reaching forward", "help": "arms out in front: is the back too narrow?",
                      "rot": {"upperarm_l": [([0, 0, 1], 45), ([0, 1, 0], -55)],
                              "upperarm_r": [([0, 0, 1], -45), ([0, 1, 0], 55)],
                              "clavicle_l": ([0, 1, 0], -12), "clavicle_r": ([0, 1, 0], 12)}},
}


def _rig():
    z = np.load(RIG)
    return {k: z[k] for k in z.files}


def _axis_angle(axis, deg):
    a = np.asarray(axis, float); a /= np.linalg.norm(a)
    t = np.radians(deg)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(t) * K + (1 - np.cos(t)) * K @ K


class Skeleton:
    def __init__(self, human):
        self.h = human
        R = _rig()
        self.bones = [str(b) for b in R["bones"]]
        self.parent = R["parent"]
        V = human.verts

        def jpos(name):
            name = str(name)
            if name.startswith("mean:"):
                return np.zeros(3)
            return human.joint(name)
        self.head = np.array([jpos(n) for n in R["heads"]])
        n, nb = len(V), len(self.bones)
        self.W = np.zeros((n, nb))
        self.W[R["v"], R["b"]] = R["w"]
        self.W /= self.W.sum(1, keepdims=True) + 1e-12
        self.V0 = V

    def pose(self, name_or_rot, t=1.0):
        """Posed vertices for a pose name (or {bone: (axis, deg)}) at fraction t."""
        Rw, Pw = self.world(name_or_rot, t)
        rel = self.V0[:, None, :] - self.head[None]               # n, nb, 3
        moved = np.einsum("bij,nbj->nbi", Rw, rel) + Pw[None]
        return (self.W[..., None] * moved).sum(1)

    def world(self, name_or_rot, t=1.0):
        """World rotation and posed head position of every bone."""
        rot = POSES[name_or_rot]["rot"] if isinstance(name_or_rot, str) else name_or_rot
        nb = len(self.bones)
        Rw = np.zeros((nb, 3, 3)); Pw = np.zeros((nb, 3))
        for i, b in enumerate(self.bones):
            Rl = np.eye(3)
            if b in rot:
                spec = rot[b]
                steps = [spec] if np.isscalar(spec[1]) else list(spec)   # one turn, or several in order
                for ax, deg in steps:
                    Rl = _axis_angle(ax, deg * t) @ Rl
            p = self.parent[i]
            if p < 0:
                Rw[i], Pw[i] = Rl, self.head[i]
            else:
                Rw[i] = Rw[p] @ Rl
                Pw[i] = Rw[p] @ (self.head[i] - self.head[p]) + Pw[p]
        return Rw, Pw


class PosedCollider:
    """Collision with the avatar while it moves: the rest-pose distance grid,
    a grid of which bone owns each spot, and per-frame bone transforms (see
    solver._collide_posed). Only bones that move get their own transform;
    everything else shares the identity."""

    def __init__(self, body, pose, h=0.008):
        from scipy.spatial import cKDTree
        from .meshbody import build_grid
        self.sk = sk = Skeleton(body.human)
        self.pose_name = pose
        g, o, hh = build_grid(sk.V0, body.F, h)
        self.grid, self.origin, self.h = np.asarray(g, np.float64), np.asarray(o, np.float64), float(hh)
        # which bones move in this pose (and all their children)
        rot = POSES[pose]["rot"]
        moving = set()
        for i, b in enumerate(sk.bones):
            p = sk.parent[i]
            if b in rot or (p >= 0 and sk.bones[p] in moving):
                moving.add(b)
        self.groups = [None] + [b for b in sk.bones if b in moving]          # group 0 = still
        gid = {b: (self.groups.index(b) if b in moving else 0) for b in sk.bones}
        bone_of_vert = sk.W.argmax(1)
        vert_group = np.array([gid[sk.bones[k]] for k in bone_of_vert])
        nx, ny, nz = self.grid.shape
        xs = [self.origin[a] + np.arange(n) * self.h for a, n in enumerate((nx, ny, nz))]
        Pq = np.stack(np.meshgrid(*xs, indexing="ij"), -1).reshape(-1, 3)
        _, j = cKDTree(sk.V0).query(Pq)
        self.label = vert_group[j].reshape(nx, ny, nz).astype(np.int16)
        G = len(self.groups)
        # a group may claim spots of itself, its parent and its children (joints)
        adj = np.eye(G, dtype=np.bool_)
        J = np.zeros((G, G, 3))          # where two neighbouring groups meet (rest pose)
        for b in moving:
            i = sk.bones.index(b); p = sk.parent[i]
            pg = gid[sk.bones[p]] if p >= 0 else 0
            adj[gid[b], pg] = adj[pg, gid[b]] = True
            J[gid[b], pg] = J[pg, gid[b]] = sk.head[i]
        # neighbours may claim each other's spots only very close to their joint
        # (a crease); further out that would drag a phantom limb along
        self.adj, self.J, self.jr = adj, J, 0.035
        self.H = np.array([np.zeros(3)] + [sk.head[sk.bones.index(b)] for b in self.groups[1:]])
        self._t = 0.0
        self.R1, self.P1 = self._transforms(0.0)
        self.R0, self.P0 = self.R1.copy(), self.P1.copy()

    def _transforms(self, t):
        Rw, Pw = self.sk.world(self.pose_name, t)
        R = np.array([np.eye(3)] + [Rw[self.sk.bones.index(b)] for b in self.groups[1:]])
        P = np.array([np.zeros(3)] + [Pw[self.sk.bones.index(b)] for b in self.groups[1:]])
        return np.ascontiguousarray(R), np.ascontiguousarray(P)

    def advance(self, t):
        """Move to pose fraction t over the next frame."""
        self.R0, self.P0 = self.R1, self.P1
        self.R1, self.P1 = self._transforms(t)


class PoseMotion:
    """Keyframed collision grids from the rest pose to a pose and back."""

    def __init__(self, body, pose, keys=6, h=0.012):
        from .meshbody import build_grid
        self.sk = Skeleton(body.human)
        self.F = body.F
        ts = np.linspace(0, 1, keys)
        Vs = [self.sk.pose(pose, t) for t in ts]
        lo = np.min([V.min(0) for V in Vs], axis=0) - 0.06
        hi = np.max([V.max(0) for V in Vs], axis=0) + 0.06
        self.ts, self.Vs = ts, Vs
        self.grids = []
        for V in Vs:
            g, o, hh = build_grid(V, self.F, h, box=(lo, hi))
            self.grids.append(np.asarray(g, np.float64))
        self.origin, self.h = np.asarray(o, float), hh
        self._buf = np.empty_like(self.grids[0])

    def at(self, t):
        """Blended grid for motion fraction t in [0, 1]."""
        t = float(np.clip(t, 0, 1))
        k = min(int(t * (len(self.ts) - 1)), len(self.ts) - 2)
        u = (t - self.ts[k]) / (self.ts[k + 1] - self.ts[k])
        # between two keyframes the body is (a little more than) both: the
        # union, eased toward the next key. A plain blend of two distance
        # fields opens holes where a limb moves (and cloth falls into them).
        np.minimum(self.grids[k], self.grids[k + 1], out=self._buf)
        return self._buf, self.origin, self.h

    def verts_at(self, t):
        return self.sk.pose_cached(t) if hasattr(self.sk, "pose_cached") else None


def smooth(t):
    return t * t * (3 - 2 * t)
