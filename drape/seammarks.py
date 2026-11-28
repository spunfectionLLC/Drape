"""Seam markings that make pieces go together only one way.

Every seam gets a number and a colour, the same on both of its edges (seam i
is number i + 1, coloured like the studio's pattern view), so ③ sews to ③.
Its notches sit 40% of the way along the seam rather than in the middle, so
an edge turned end for end no longer lines up, and seams that touch a back
piece get double notches (single for front), the usual convention: a sleeve
put in back to front can't be matched. Where two seams meet on a smooth curve
(the top of a sleeve cap), a dot marks the point that goes to the seam
between them (the shoulder seam).

All lengths in cm, in each piece's own flat coordinates.
"""
from __future__ import annotations

import colorsys

import numpy as np

NOTCH_AT = 0.40          # along the seam, from edge A's start
DOUBLE_GAP_CM = 0.6      # between the two notches of a double notch
SMOOTH_DEG = 30.0        # a junction turning less than this is a curve, not a corner


def seam_color(i: int) -> str:
    """Seam i's colour, as in the studio (hsl(i * 137.5, 62%, 46%))."""
    r, g, b = colorsys.hls_to_rgb(((i * 137.5) % 360) / 360, 0.46, 0.62)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def _arc(e):
    s = np.linalg.norm(np.diff(e, axis=0), axis=1)
    return np.concatenate([[0.0], np.cumsum(s)])


def _at(e, frac):
    """Point and unit tangent at a fraction of the edge's length."""
    S = _arc(e)
    t = np.clip(frac, 0, 1) * S[-1]
    i = int(np.clip(np.searchsorted(S, t), 1, len(e) - 1))
    w = (t - S[i - 1]) / max(S[i] - S[i - 1], 1e-12)
    d = e[i] - e[i - 1]
    return e[i - 1] + w * d, d / (np.linalg.norm(d) + 1e-12)


def _is_back(name: str) -> bool:
    return "back" in name.lower()


def _partner_label(name: str) -> str:
    return name.replace("_", " ").upper()


def seam_marks(panels, seams):
    """{piece: {"edges": {edge: mark}, "dots": [mark]}}.
    Edge mark: num, color, seam index, partner, notches [(point, outward unit)],
    tag (a point inside the piece next to the edge's middle), pts (the edge, cm).
    Dot mark: point, between (the two seam numbers it sits between)."""
    from shapely.geometry import Point, Polygon
    by = {p.name: p for p in panels}
    out = {p.name: {"edges": {}, "dots": []} for p in panels}
    orient = {}
    poly = {}
    for p in panels:
        P = np.concatenate([e[:-1] for _, e in p.edges]) * 100
        a = 0.5 * np.sum(P[:, 0] * np.roll(P[:, 1], -1) - np.roll(P[:, 0], -1) * P[:, 1])
        orient[p.name] = 1.0 if a > 0 else -1.0
        poly[p.name] = Polygon(P).buffer(0)

    def edge(pn, en):
        for n, e in by[pn].edges:
            if n == en:
                return np.asarray(e, float) * 100
        return None

    for i, s in enumerate(seams):
        if s.panel_a not in by or s.panel_b not in by:
            continue
        double = _is_back(s.panel_a) or _is_back(s.panel_b)
        for pn, en, other, frac in ((s.panel_a, s.edge_a, s.panel_b, NOTCH_AT),
                                    (s.panel_b, s.edge_b, s.panel_a, 1 - NOTCH_AT if s.reverse else NOTCH_AT)):
            e = edge(pn, en)
            if e is None or len(e) < 2:
                continue
            L = _arc(e)[-1]
            offs = [-DOUBLE_GAP_CM / 2, DOUBLE_GAP_CM / 2] if double else [0.0]
            notches = []
            for o in offs:
                q, d = _at(e, frac + o / max(L, 1e-9))
                notches.append((q, orient[pn] * np.array([d[1], -d[0]])))     # outward
            # the number goes just inside the piece, by the middle of the edge
            m, d = _at(e, 0.5)
            inward = -orient[pn] * np.array([d[1], -d[0]])
            tag = m + inward * 1.2
            for k in (2.4, 1.8, 1.2, 0.8, 0.5):
                c = m + inward * k
                if poly[pn].contains(Point(*c)):
                    tag = c
                    break
            partner = "ITS OTHER SIDE" if other == pn else _partner_label(other)
            out[pn]["edges"][en] = dict(num=i + 1, seam=i, color=seam_color(i), partner=partner,
                                        notches=notches, tag=tag, pts=e)

    # match dots: where two seamed edges meet on a smooth curve and sew to different pieces
    for p in panels:
        names = [n for n, _ in p.edges]
        for k, (n1, e1) in enumerate(p.edges):
            n2, e2 = p.edges[(k + 1) % len(p.edges)]
            m1, m2 = out[p.name]["edges"].get(n1), out[p.name]["edges"].get(n2)
            if not (m1 and m2) or m1["partner"] == m2["partner"]:
                continue
            a = np.asarray(e1, float)[-1] - np.asarray(e1, float)[-2]
            b = np.asarray(e2, float)[1] - np.asarray(e2, float)[0]
            ang = np.degrees(np.arccos(np.clip(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12), -1, 1)))
            if ang < SMOOTH_DEG:
                out[p.name]["dots"].append(dict(point=np.asarray(e2, float)[0] * 100,
                                                between=(m1["num"], m2["num"])))
        del names
    return out
