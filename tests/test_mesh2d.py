"""The pattern mesher: free for commercial use (no Triangle), outline points kept
exactly (seams stay matched), the whole piece covered, sensible triangles."""
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from drape.mesh2d import triangulate_piece


def _sample(poly, h):
    R = np.asarray(poly.exterior.coords)[:-1]
    C = np.vstack([R, R[:1]])
    L = np.r_[0, np.cumsum(np.linalg.norm(np.diff(C, axis=0), axis=1))]
    t = np.linspace(0, L[-1], max(8, int(L[-1] / h)), endpoint=False)
    return np.c_[np.interp(t, L, C[:, 0]), np.interp(t, L, C[:, 1])]


SHAPES = {
    "square": box(0, 0, 0.4, 0.5),
    "circle": Point(0, 0).buffer(0.2, quad_segs=32),
    "fingers": unary_union([box(0, 0, 0.09, 0.1)] + [box(0.005 + i * 0.022, 0.1, 0.022 + i * 0.022, 0.18) for i in range(4)]),
    "L": Polygon([(0, 0), (0.5, 0), (0.5, 0.06), (0.06, 0.06), (0.06, 0.5), (0, 0.5)]),
    "thin_strip": box(0, 0, 0.8, 0.03),
    "zigzag": Polygon([(0, 0), (0.3, 0), (0.3, 0.3), (0.2, 0.05), (0.15, 0.3), (0.1, 0.05), (0.0, 0.3)]),
}


@pytest.mark.parametrize("name", list(SHAPES))
@pytest.mark.parametrize("h", [0.005, 0.015])
def test_mesh(name, h):
    poly = SHAPES[name]
    outline = _sample(poly, h)
    V, T = triangulate_piece(outline, h)
    nb = len(outline)
    assert np.array_equal(V[:nb], outline)                       # outline untouched, in order
    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    signed = (b - a)[:, 0] * (c - a)[:, 1] - (b - a)[:, 1] * (c - a)[:, 0]
    assert (signed > 0).all()                                    # counter-clockwise, none flat
    assert abs(signed.sum() / 2 - Polygon(outline).area) < 1e-9  # covers exactly the piece
    E = np.sort(np.vstack([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]]), axis=1)
    edges, count = np.unique(E, axis=0, return_counts=True)
    assert count.max() <= 2                                      # a proper surface
    bnd = {tuple(e) for e in edges[count == 1]}
    want = {tuple(sorted((i, (i + 1) % nb))) for i in range(nb)}
    assert bnd == want                                           # its border is exactly the outline


def test_no_triangle_dependency():
    root = Path(__file__).resolve().parents[1]
    assert '"triangle"' not in (root / "pyproject.toml").read_text(encoding="utf-8")
    for f in (root / "drape").rglob("*.py"):
        src = f.read_text(encoding="utf-8")
        assert "import triangle" not in src and "from triangle" not in src, f
