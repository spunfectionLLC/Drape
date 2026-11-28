"""Sewing checks, run on the flat pattern before simulating ("walking the
seams", as a patternmaker does with a tape or a seam-walking wheel):

1. Length match: the two sides of each seam must be equal, or differ by the
   ease the seam is meant to have (e.g. a sleeve cap eased into an armhole).
2. Direction: a seam traversed the wrong way (reverse flag wrong) sews the
   ends crossed. Detected from the 3D placement: if pairing the points the
   other way round is much shorter, the seam is probably twisted.
3. Truing: where a seam meets a cut edge (hem, neckline, armhole, cuff), the
   two pieces' corner angles must add to ~180 degrees, or the sewn edge gets a
   point or a notch at the seam. Example: two 90-degree hem corners at a side
   seam give a straight hem; 100 + 100 gives a dip.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .pattern import Panel, Seam, polyline_length


@dataclass
class Tolerances:
    length_mm: float = 1.5      # absolute length mismatch allowed
    length_pct: float = 0.5     # or relative, whichever is larger
    truing_warn_deg: float = 5.0
    truing_fail_deg: float = 15.0
    twist_ratio: float = 0.7    # reversed pairing < 70% of given pairing -> twisted


def _edge_info(panel: Panel, name: str):
    names = [n for n, _ in panel.edges]
    i = names.index(name)
    prev_name = names[i - 1]
    next_name = names[(i + 1) % len(names)]
    return panel.edge(name), prev_name, next_name


def _unit(v):
    return v / (np.linalg.norm(v) + 1e-15)


def _end_tangent(p: np.ndarray, h: float = 0.003) -> np.ndarray:
    """Tangent at p[0]: least-squares quadratic fit of x(s), y(s) over the
    first few millimetres of arc length s (at least 3 points), slope at s=0.

    History (each tested): first chord -> ~2 deg error on sampled curves;
    -3p0+4p1-p2 on vertices -> exact on evenly sampled curves but garbage on
    unevenly spaced DXF points (0.5 mm then 7 mm gave a 277 deg corner);
    fixed 1.5 mm arc-length window -> falls inside the first chord of coarse
    curves. A quadratic in arc length is exact for all three cases."""
    keep = np.r_[True, np.linalg.norm(np.diff(p, axis=0), axis=1) > 1e-12]
    p = p[keep]
    if len(p) < 3:
        return p[1] - p[0] if len(p) == 2 else np.array([1.0, 0.0])
    s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))])
    n = max(3, int(np.count_nonzero(s <= h)))
    n = min(n, len(p), 6)
    S = s[:n]
    bx = np.polyfit(S, p[:n, 0], 2)[1]
    by = np.polyfit(S, p[:n, 1], 2)[1]
    return np.array([bx, by])


def _corner_angle(incoming: np.ndarray, outgoing: np.ndarray) -> float:
    """Interior angle (deg) at the corner where polyline `incoming` ends and
    `outgoing` starts, for a counter-clockwise outline."""
    a = _unit(_end_tangent(incoming[::-1]) * -1)  # direction arriving
    b = _unit(_end_tangent(outgoing))             # direction leaving
    turn = np.degrees(np.arctan2(a[0] * b[1] - a[1] * b[0], a @ b))  # left turn > 0
    return 180.0 - turn


def check_seams(panels: list[Panel], seams: list[Seam], tol: Tolerances | None = None) -> dict:
    tol = tol or Tolerances()
    pmap = {p.name: p for p in panels}
    lengths, truing, problems = [], [], []

    for s in seams:
        A, B = pmap[s.panel_a], pmap[s.panel_b]
        ea, a_prev, a_next = _edge_info(A, s.edge_a)
        eb, b_prev, b_next = _edge_info(B, s.edge_b)
        la, lb = polyline_length(ea), polyline_length(eb)

        # ---- 1. length
        diff = la - lb
        want = s.ease * lb
        err = diff - want
        allow = max(tol.length_mm / 1000, tol.length_pct / 100 * lb)
        status = "OK" if abs(err) <= allow else "MISMATCH"
        if status == "OK" and s.ease:
            status = "OK (eased)"
        row = {"seam": s.name, "a_mm": la * 1000, "b_mm": lb * 1000, "diff_mm": diff * 1000,
               "diff_pct": diff / lb * 100, "intended_ease_pct": s.ease * 100,
               "error_mm": err * 1000, "status": status}

        # ---- 2. direction (needs 3D placement)
        n = 32
        from .pattern import resample
        pa = A.place(resample(ea, n)); pb = B.place(resample(eb, n))
        if s.reverse:
            pb = pb[::-1]
        given = np.linalg.norm(pa - pb, axis=1).mean()
        swapped = np.linalg.norm(pa - pb[::-1], axis=1).mean()
        row["twisted"] = bool(swapped < tol.twist_ratio * given)
        if row["twisted"]:
            row["status"] = "TWISTED?" if status.startswith("OK") else status + ", TWISTED?"
        lengths.append(row)
        if not row["status"].startswith("OK"):
            problems.append(f"{s.name}: {row['status']} (A {la*1000:.1f} mm vs B {lb*1000:.1f} mm"
                            + (f", intended ease {s.ease*100:.1f}%" if s.ease else "") + ")")

    truing = check_junctions(panels, seams, tol)
    for j in truing:
        if j["status"] != "OK":
            problems.append(f"junction {j['corners']}: angles sum to {j['sum_deg']:.0f} deg, expected "
                            f"{j['expected_deg']:.0f} ({j['deviation_deg']:+.0f}) -> {j['shape']}")
    return {"lengths": lengths, "truing": truing, "problems": problems, "ok": not problems}


def check_junctions(panels: list[Panel], seams: list[Seam], tol: Tolerances) -> list[dict]:
    """Group pattern corners that get sewn to each other into junctions.
    - Junction on the garment's edge (some incident edge unsewn, e.g. a hem or
      neckline): the corner angles must sum to 180 deg for a smooth edge.
    - Junction inside the garment (every incident edge sewn, e.g. where a
      sleeve crown meets the shoulder seam): angles must sum to 360 deg, or the
      fabric is forced into a cone (deficit) or a ripple (excess)."""
    pmap = {p.name: p for p in panels}
    parent: dict = {}

    def find(k):
        parent.setdefault(k, k)
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def union(a, b):
        parent[find(a)] = find(b)

    sewn = set()
    for sm in seams:
        na = [n for n, _ in pmap[sm.panel_a].edges]; nb = [n for n, _ in pmap[sm.panel_b].edges]
        ia, ib = na.index(sm.edge_a), nb.index(sm.edge_b)
        a0, a1 = (sm.panel_a, ia), (sm.panel_a, (ia + 1) % len(na))   # corners at edge start/end
        b0, b1 = (sm.panel_b, ib), (sm.panel_b, (ib + 1) % len(nb))
        if sm.reverse:
            union(a0, b1); union(a1, b0)
        else:
            union(a0, b0); union(a1, b1)
        sewn.add((sm.panel_a, sm.edge_a)); sewn.add((sm.panel_b, sm.edge_b))

    groups: dict = {}
    for k in list(parent):
        groups.setdefault(find(k), []).append(k)

    out = []
    for corners in groups.values():
        if len(corners) < 2:
            continue
        total, free, labels = 0.0, [], []
        for pname, k in sorted(corners):
            E = pmap[pname].edges
            (n_in, e_in), (n_out, e_out) = E[k - 1], E[k]
            total += _corner_angle(e_in, e_out)
            labels.append(f"{pname}[{n_in}|{n_out}]")
            free += [f"{pname}.{n}" for n in (n_in, n_out) if (pname, n) not in sewn]
        expected = 180.0 if free else 360.0
        dev = total - expected
        if abs(dev) <= tol.truing_warn_deg:
            st, shape = "OK", "smooth" if free else "flat"
        else:
            st = "CHECK" if abs(dev) <= tol.truing_fail_deg else "RE-TRUE"
            if free:
                shape = "point in the sewn edge" if dev > 0 else "dip/notch in the sewn edge"
            else:
                shape = "excess fabric (ripple)" if dev > 0 else "cone (fabric forced to dome)"
        out.append({"corners": " + ".join(labels), "kind": "edge" if free else "inside",
                    "free_edges": free, "sum_deg": total, "expected_deg": expected,
                    "deviation_deg": dev, "shape": shape, "status": st})
    out.sort(key=lambda r: r["corners"])
    return out


def format_report(rep: dict) -> str:
    L = ["SEAM LENGTHS"]
    L.append(f"{'seam':44s} {'A mm':>8s} {'B mm':>8s} {'diff':>8s} {'ease':>6s}  status")
    for r in rep["lengths"]:
        L.append(f"{r['seam']:44s} {r['a_mm']:8.1f} {r['b_mm']:8.1f} {r['diff_mm']:+8.1f} "
                 f"{r['intended_ease_pct']:5.1f}%  {r['status']}")
    L.append("")
    L.append("TRUING (corner angles at each sewn junction: 180 on an edge, 360 inside)")
    L.append(f"{'junction':72s} {'kind':>6s} {'sum':>6s} {'want':>5s}  status")
    for r in rep["truing"]:
        L.append(f"{r['corners']:72s} {r['kind']:>6s} {r['sum_deg']:6.1f} {r['expected_deg']:5.0f}  "
                 f"{r['status']}{'' if r['status']=='OK' else ' (' + r['shape'] + ')'}")
    L.append("")
    L.append("RESULT: " + ("all seams OK" if rep["ok"] else f"{len(rep['problems'])} problem(s)"))
    L += ["  - " + p for p in rep["problems"]]
    return "\n".join(L)
