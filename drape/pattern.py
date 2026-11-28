"""2D sewing patterns -> triangulated, seam-matched 3D garment mesh.

Units: meters. Panels are drawn flat in (u, v) pattern space, then placed in 3D
by an isometric mapping (e.g. wrapped onto a cylinder around the avatar), so
the flat pattern is always the rest state of the cloth.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .mesh2d import triangulate_piece

INTERIOR_SPACING = 0.88   # interior grid spacing / outline spacing
# the most cloth points one garment may mesh to: the largest design that ships (opera gloves) is about 10,000;
# a piece typed ten times too big (6 m across) took minutes on every edit, and on the website froze the page
MAX_POINTS = 100_000


# ---------------------------------------------------------------- curves ----
def bezier(p0, p1, p2, p3, k: int = 48) -> np.ndarray:
    """Cubic Bezier as a dense polyline (k points, endpoints included)."""
    t = np.linspace(0.0, 1.0, k)[:, None]
    p0, p1, p2, p3 = map(np.asarray, (p0, p1, p2, p3))
    return ((1 - t) ** 3) * p0 + 3 * ((1 - t) ** 2) * t * p1 + 3 * (1 - t) * t**2 * p2 + t**3 * p3


def line(p0, p1) -> np.ndarray:
    return np.array([p0, p1], dtype=float)


def polyline_length(pts: np.ndarray) -> float:
    return float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())


def resample(pts: np.ndarray, n_seg: int) -> np.ndarray:
    """Resample a polyline to n_seg equal-arc-length segments (n_seg+1 points)."""
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    t = np.linspace(0.0, s[-1], n_seg + 1)
    return np.stack([np.interp(t, s, pts[:, 0]), np.interp(t, s, pts[:, 1])], axis=1)


# --------------------------------------------------------------- pattern ----
@dataclass
class Panel:
    """A pattern piece. `edges` are listed counter-clockwise; each edge's last
    point must equal the next edge's first point (closed outline)."""

    name: str
    edges: list[tuple[str, np.ndarray]]
    place: Callable[[np.ndarray], np.ndarray]  # (n,2) uv -> (n,3) xyz
    extend: dict = field(default_factory=dict)   # edge -> extra width (m) cut beyond it (button stand + facing)
    marks: list = field(default_factory=list)     # [{kind, pts (m)}]: buttonholes, buttons, fold lines, zip stops
    sa_edges: dict = field(default_factory=dict)  # edge -> seam allowance (cm) where it differs from the default
    hems: dict = field(default_factory=dict)      # edge -> {style, depth_cm, turn_cm}: turn-up cut on beyond it (hems.py)

    def edge(self, name: str) -> np.ndarray:
        for n, p in self.edges:
            if n == name:
                return p
        raise KeyError(f"{self.name} has no edge {name!r}")

    def validate(self, tol: float = 1e-9) -> None:
        for (_, a), (_, b) in zip(self.edges, self.edges[1:] + self.edges[:1]):
            if np.linalg.norm(a[-1] - b[0]) > tol:
                raise ValueError(f"panel {self.name}: outline is not closed/continuous")


@dataclass
class Seam:
    """Sew panel_a.edge_a to panel_b.edge_b. If reverse, edge_b is traversed
    end->start so point i on A meets point n-i on B. `ease` is intended extra
    length of A relative to B (0.03 = A is 3% longer, eased in, e.g. a sleeve cap)."""

    panel_a: str
    edge_a: str
    panel_b: str
    edge_b: str
    reverse: bool = False
    ease: float = 0.0

    @property
    def name(self) -> str:
        return f"{self.panel_a}.{self.edge_a} <-> {self.panel_b}.{self.edge_b}"


@dataclass
class Garment:
    x: np.ndarray            # (n,3) initial 3D positions
    uv: np.ndarray           # (n,2) flat pattern positions (rest state)
    tris: np.ndarray         # (m,3)
    panel_id: np.ndarray     # (n,)
    panel_names: list[str]
    edges: np.ndarray        # (e,2) unique mesh edges
    edge_rest: np.ndarray    # (e,)
    bends: np.ndarray        # (b,2) opposite-vertex pairs across interior edges
    bend_rest: np.ndarray    # (b,)
    seams: np.ndarray        # (s,2) vertex pairs to sew together
    mass: np.ndarray         # (n,)
    meta: dict = field(default_factory=dict)


def _edge_sample_counts(panels: dict[str, Panel], seams: list[Seam], spacing: float):
    counts: dict[tuple[str, str], int] = {}
    for p in panels.values():
        for en, pts in p.edges:
            counts[(p.name, en)] = max(1, int(np.ceil(polyline_length(pts) / spacing)))
    for s in seams:  # seamed edges must have identical vertex counts
        ka, kb = (s.panel_a, s.edge_a), (s.panel_b, s.edge_b)
        n = max(counts[ka], counts[kb])
        counts[ka] = counts[kb] = n
    return counts


def _check_size(panels, spacing):
    """Refuse, before meshing, a garment that would mesh to more than MAX_POINTS (a message about the size)."""
    h = spacing * INTERIOR_SPACING
    area, big = 0.0, None
    for p in panels:
        P = np.concatenate([np.asarray(pts, float) for _, pts in p.edges])
        a = 0.5 * abs(float(np.dot(P[:, 0], np.roll(P[:, 1], -1)) - np.dot(P[:, 1], np.roll(P[:, 0], -1))))
        area += a
        if big is None or a > big[0]:
            big = (a, p.name, np.ptp(P[:, 0]) * 100, np.ptp(P[:, 1]) * 100)
    est = area * 1.155 / (h * h)              # points on a triangle grid of spacing h
    if est > MAX_POINTS:
        _, name, w, ht = big
        fine = f" at this design's fine mesh ({spacing * 1000:.0f} mm)" if spacing < 0.0149 else ""
        raise ValueError(f"'{name}' is {w:.0f} x {ht:.0f} cm: about {area:.1f} m2 of fabric in all, more than the studio "
                         f"can work with at once{fine} (about {MAX_POINTS * h * h / 1.155:.1f} m2). If a size was typed too big, "
                         "fix it; otherwise make the garment from smaller pieces.")


def build_garment(panels: list[Panel], seams: list[Seam], spacing: float = 0.015,
                  density: float = 0.15) -> Garment:
    """Mesh every panel and stitch seams. density in kg/m^2 (cotton jersey ~0.15)."""
    pmap = {p.name: p for p in panels}
    for p in panels:
        p.validate()
    _check_size(panels, spacing)
    counts = _edge_sample_counts(pmap, seams, spacing)

    xs, uvs, tris, pids = [], [], [], []
    edge_index: dict[tuple[str, str], np.ndarray] = {}  # global vertex ids along each edge
    offset = 0
    for pid, p in enumerate(panels):
        outline, ranges = [], []
        for en, pts in p.edges:
            r = resample(pts, counts[(p.name, en)])
            start = len(outline)
            outline.extend(r[:-1])
            ranges.append((en, start, len(r) - 1))
        outline = np.array(outline)
        nb = len(outline)
        # no points added on the outline, so seam vertices stay matched
        # the inside a little denser than the outline spacing: the same point density the
        # solver's bending and fit calibration were done at
        V, T = triangulate_piece(outline, spacing * INTERIOR_SPACING)   # same jitter for every piece: identical pieces mesh identically
        assert np.allclose(V[:nb], outline), "the mesher moved outline points"
        # Make triangles CCW in uv so normals are consistent per panel.
        a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
        cross = (b - a)[:, 0] * (c - a)[:, 1] - (b - a)[:, 1] * (c - a)[:, 0]
        T[cross < 0] = T[cross < 0][:, [0, 2, 1]]
        for en, start, n in ranges:
            idx = (start + np.arange(n + 1)) % nb
            edge_index[(p.name, en)] = idx + offset
        xs.append(p.place(V)); uvs.append(V); tris.append(T + offset)
        pids.append(np.full(len(V), pid)); offset += len(V)

    x = np.concatenate(xs); uv = np.concatenate(uvs)
    T = np.concatenate(tris); pid = np.concatenate(pids)

    # Unique edges + bending pairs (opposite vertices of the two triangles sharing an edge).
    e_all = np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
    opp_all = np.concatenate([T[:, 2], T[:, 0], T[:, 1]])
    key = np.sort(e_all, axis=1)
    order = np.lexsort((key[:, 1], key[:, 0]))
    key, opp = key[order], opp_all[order]
    same = np.all(key[1:] == key[:-1], axis=1)
    bends = np.stack([opp[:-1][same], opp[1:][same]], axis=1)
    edges = np.unique(key, axis=0)

    # Seam vertex pairs.
    pairs = []
    for s in seams:
        ia, ib = edge_index[(s.panel_a, s.edge_a)], edge_index[(s.panel_b, s.edge_b)]
        if s.reverse:
            ib = ib[::-1]
        pairs.append(np.stack([ia, ib], axis=1))
    if pairs:
        # which seam each vertex pair came from (the first, where two share a pair)
        seam_pairs, first = np.unique(np.concatenate(pairs), axis=0, return_index=True)
        seam_of_pair = np.concatenate([np.full(len(p), k) for k, p in enumerate(pairs)])[first]
    else:
        seam_pairs, seam_of_pair = np.zeros((0, 2), int), np.zeros(0, int)

    # Lumped mass: a third of each triangle's (flat) area to each corner.
    a, b, c = uv[T[:, 0]], uv[T[:, 1]], uv[T[:, 2]]
    area = 0.5 * np.abs((b - a)[:, 0] * (c - a)[:, 1] - (b - a)[:, 1] * (c - a)[:, 0])
    mass = np.zeros(len(uv))
    for k in range(3):
        np.add.at(mass, T[:, k], area * density / 3.0)

    rest = lambda pr: np.linalg.norm(uv[pr[:, 0]] - uv[pr[:, 1]], axis=1)
    return Garment(x=x, uv=uv, tris=T, panel_id=pid, panel_names=[p.name for p in panels],
                   edges=edges, edge_rest=rest(edges), bends=bends, bend_rest=rest(bends),
                   seams=seam_pairs, mass=mass,
                   meta={"edge_index": edge_index, "fabric_area_m2": float(area.sum()),
                         "panels": panels, "seam_defs": seams, "density": density,
                         "seam_of_pair": seam_of_pair})


# ------------------------------------------------------------- placement ----
def cylinder_wrap(radius: float, center_angle: float, y0: float, cx: float = 0.0, cz: float = 0.0):
    """Isometric wrap of a flat panel onto a vertical cylinder. u -> arc length,
    v -> height. center_angle=0 faces +z (front), pi faces -z (back)."""
    def place(uv: np.ndarray) -> np.ndarray:
        th = center_angle + uv[:, 0] / radius
        return np.stack([cx + radius * np.sin(th), y0 + uv[:, 1], cz + radius * np.cos(th)], axis=1)
    return place


def axis_wrap(radius: float, origin, axis_dir, up_dir, side_dir, v_ref: float):
    """Isometric wrap onto a cylinder around an arbitrary axis (e.g. an arm).
    v runs along axis_dir; the point with v = v_ref sits at `origin` on the
    axis. u = 0 lies toward up_dir; +u turns toward side_dir."""
    o, a, up, sd = (np.asarray(t, float) for t in (origin, axis_dir, up_dir, side_dir))
    a, up, sd = a / np.linalg.norm(a), up / np.linalg.norm(up), sd / np.linalg.norm(sd)

    def place(uv: np.ndarray) -> np.ndarray:
        th = uv[:, 0] / radius
        return (o + np.outer(uv[:, 1] - v_ref, a)
                + radius * (np.outer(np.cos(th), up) + np.outer(np.sin(th), sd)))
    return place
