"""A realistic body (MakeHuman mesh, see human.py) as a collision body.

Collision uses a signed distance grid computed from the mesh with libigl's
fast winding number (robust to the small openings at the eyes and mouth),
sampled trilinearly in the solver. Grids are cached on disk by mesh hash:
the first build of a new body takes ~20 s at 6 mm, later runs load it.

Exposes the same small interface as the capsule mannequin (body.Body), so
garments, fit checks, importer and renderers work with either:
  shoulder_top_y, arm_axis, armpit_depth, section_y, tape_girth, neck_girth,
  upper_arm_girth, torso_wrap_radius, mesh, sdf
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np
from ._jit import njit

from .human import Human
from .meshmeasure import Tape, horizontal_girth

CACHE = Path(os.environ.get("DRAPE_SDF_CACHE", Path(__file__).resolve().parents[1] / ".sdf_cache"))


@njit(cache=True)
def grid_sdf(px, py, pz, grid, origin, h):
    """Trilinear sample of a signed distance grid; outside the grid, distance
    to the grid box plus the clamped value (always positive there)."""
    nx, ny, nz = grid.shape
    fx = (px - origin[0]) / h; fy = (py - origin[1]) / h; fz = (pz - origin[2]) / h
    cx = min(max(fx, 0.0), nx - 1.000001); cy = min(max(fy, 0.0), ny - 1.000001); cz = min(max(fz, 0.0), nz - 1.000001)
    out = np.sqrt((fx - cx) ** 2 + (fy - cy) ** 2 + (fz - cz) ** 2) * h
    i, j, k = int(cx), int(cy), int(cz)
    tx, ty, tz = cx - i, cy - j, cz - k
    c00 = grid[i, j, k] * (1 - tx) + grid[i + 1, j, k] * tx
    c10 = grid[i, j + 1, k] * (1 - tx) + grid[i + 1, j + 1, k] * tx
    c01 = grid[i, j, k + 1] * (1 - tx) + grid[i + 1, j, k + 1] * tx
    c11 = grid[i, j + 1, k + 1] * (1 - tx) + grid[i + 1, j + 1, k + 1] * tx
    c0 = c00 * (1 - ty) + c10 * ty
    c1 = c01 * (1 - ty) + c11 * ty
    return c0 * (1 - tz) + c1 * tz + out


@njit(cache=True)
def grid_sdf_grad(px, py, pz, grid, origin, h):
    e = 0.5 * h
    gx = grid_sdf(px + e, py, pz, grid, origin, h) - grid_sdf(px - e, py, pz, grid, origin, h)
    gy = grid_sdf(px, py + e, pz, grid, origin, h) - grid_sdf(px, py - e, pz, grid, origin, h)
    gz = grid_sdf(px, py, pz + e, grid, origin, h) - grid_sdf(px, py, pz - e, grid, origin, h)
    n = np.sqrt(gx * gx + gy * gy + gz * gz) + 1e-12
    return gx / n, gy / n, gz / n


@njit(cache=True)
def grid_sdf_batch(P, grid, origin, h):
    out = np.empty(P.shape[0])
    for i in range(P.shape[0]):
        out[i] = grid_sdf(P[i, 0], P[i, 1], P[i, 2], grid, origin, h)
    return out


def build_grid(V, F, h=0.006, margin=0.05, clamp=0.06, box=None):
    """box: (lo, hi) to sample on a fixed box (so grids of several poses line up)."""
    key = hashlib.sha1(np.round(V, 5).tobytes() + F.tobytes() + f"{h},{margin},{clamp},{None if box is None else np.round(np.r_[box[0], box[1]], 4).tolist()}".encode()).hexdigest()[:16]
    path = CACHE / f"{key}.npz"
    if path.exists():
        z = np.load(path)
        return z["grid"], z["origin"], float(z["h"])
    lo = V.min(0) - margin if box is None else np.asarray(box[0], float)
    hi = V.max(0) + margin if box is None else np.asarray(box[1], float)
    xs, ys, zs = (np.arange(lo[i], hi[i] + h, h) for i in range(3))
    try:
        import igl
    except ImportError:      # web browser: numpy + SciPy only (same signs, within 0.2 mm near the skin)
        igl = None
    if igl is not None and not os.environ.get("DRAPE_NO_IGL"):
        P = np.stack(np.meshgrid(xs, ys, zs, indexing="ij"), -1).reshape(-1, 3)
        S = igl.signed_distance(P, V, F.astype(np.int64),
                                sign_type=igl.SIGNED_DISTANCE_TYPE_FAST_WINDING_NUMBER)[0]
        grid = np.clip(S, -clamp, clamp).reshape(len(xs), len(ys), len(zs)).astype(np.float64)
    else:
        from .sdf_numpy import signed_distance_grid
        grid = signed_distance_grid(V, F, xs, ys, zs, clamp=clamp).astype(np.float64)
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        # written under a private name, then renamed: tests run in parallel (pytest -n) and two
        # processes can build the same body's grid at once; a reader never sees half a file
        tmp = path.with_name(f"{path.stem}.{os.getpid()}.tmp.npz")
        np.savez_compressed(tmp, grid=grid.astype(np.float32), origin=lo, h=h)
        os.replace(tmp, path)
    except OSError:          # read-only or no file system: just don't cache
        pass
    return grid, lo, h


class MeshBody:
    kind = "mesh"

    def __init__(self, human: Human, grid_h=None, measurements=None):
        self.human = human
        if grid_h is None:     # 6 mm; the web build sets DRAPE_GRID_H=0.008 (numpy grid: 48 s -> 20 s natively)
            grid_h = float(os.environ.get("DRAPE_GRID_H", "0.006"))
        self.V, self.F = human.verts, human.tris
        self._grid_h = grid_h
        self._grid = None          # built on first use (drafting never needs it)
        self.tape = Tape(human)
        self.lines = self.tape.lines()
        self.measurements = measurements
        self.side = self.tape.side

    # --------------------------------------------------------- distance --
    def _ensure_grid(self):
        if self._grid is None:
            g, o, h = build_grid(self.V, self.F, self._grid_h)
            self._grid = (np.ascontiguousarray(g, dtype=np.float64), np.ascontiguousarray(o, dtype=np.float64), float(h))
        return self._grid

    @property
    def grid(self):
        return self._ensure_grid()[0]

    @property
    def origin(self):
        return self._ensure_grid()[1]

    @property
    def h(self):
        return self._ensure_grid()[2]

    def sdf(self, p):
        p = np.ascontiguousarray(np.atleast_2d(p), dtype=np.float64)
        return grid_sdf_batch(p, self.grid, self.origin, self.h)

    # -------------------------------------------------------- interface --
    def shoulder_top_y(self) -> float:
        return float(self.tape.shoulder_point()[1])

    def arm_axis(self, side=+1):
        """(shoulder joint, elbow, upper-arm radius) for the arm on the +x
        (side=+1) or -x side."""
        s = self.side if side > 0 else self.tape.other
        j, e = self.human.joint(f"{s}-shoulder"), self.human.joint(f"{s}-elbow")
        return j, e, self.upper_arm_girth() / (2 * np.pi)

    def armpit_depth(self) -> float:
        return self.shoulder_top_y() - self.lines["armpit"]

    def section_y(self, name: str) -> float:
        return float(self.lines[{"seat": "hip"}.get(name, name)])

    def tape_girth(self, name: str) -> float:
        name = {"seat": "hip"}.get(name, name)
        return {"chest": self.tape.chest, "waist": self.tape.waist, "hip": self.tape.hip,
                "underbust": self.tape.underbust}[name]()

    def girth_at_y(self, y: float) -> float:
        return horizontal_girth(self.V, self.tape.torso, y)

    def neck_girth(self) -> float:
        return self.tape.neck()

    def upper_arm_girth(self) -> float:
        if not hasattr(self, "_ua"):
            self._ua = self.tape.upper_arm()
        return self._ua

    def torso_wrap_radius(self) -> float:
        V, w = self.V, self.human.regions["torso"]
        sel = (w > 0.5) & (V[:, 1] > self.lines["crotch"]) & (V[:, 1] < self.lines["armpit"])
        r = np.hypot(V[sel, 0], V[sel, 2] - np.median(V[sel, 2])).max()
        return float(r + 0.035)

    def torso_center_z(self) -> float:
        V, w = self.V, self.human.regions["torso"]
        sel = (w > 0.5) & (V[:, 1] > self.lines["waist"]) & (V[:, 1] < self.lines["armpit"])
        return float(np.median(V[sel, 2]))

    def mesh(self, **_):
        return self.V, self.F[:, [0, 2, 1]]

    def height(self) -> float:
        return self.human.height()
