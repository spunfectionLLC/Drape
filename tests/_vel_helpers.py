"""Small scenes for the velocity-level springs tests (test_v19_velocity.py) and the report."""
from dataclasses import replace
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def far_body():
    from drape.measurements import Measurements, body_from_measurements
    return body_from_measurements(Measurements.load(ROOT / "measurements" / "male_M.json"))


def strip(w, h, place):
    """A w x h (m) rectangle; place(uv) -> xyz."""
    from drape.pattern import Panel, build_garment
    c = np.array([[0, 0], [w, 0], [w, h], [0, h]], float)
    edges = [(f"e{k}", np.stack([c[k], c[(k + 1) % 4]])) for k in range(4)]
    return build_garment([Panel("s", edges, place)], [], spacing=0.02 if min(w, h) > 0.1 else 0.01)


def pin_where(sim, mask):
    sim.pin(np.nonzero(mask)[0])


def hanging_load(cls, fabric="poplin", load_kg=0.05, seconds=3.0):
    """A 30 x 30 cm strip, top edge held, a 50 g weight on the middle of its bottom edge."""
    from drape.fabrics import get
    g = strip(0.30, 0.30, lambda uv: np.c_[uv[:, 0] - 0.15, uv[:, 1] + 3.0, np.zeros(len(uv))])
    sim = cls(g, far_body(), get(fabric))
    y = sim.x[:, 1]
    pin_where(sim, y > y.max() - 1e-6)
    bot = np.nonzero(y < y.min() + 1e-6)[0]
    i = bot[np.argmin(np.abs(sim.x[bot, 0]))]
    sim.g.mass[i] += load_kg
    sim.w[i] = 1.0 / sim.g.mass[i]
    worst = []
    for k in range(int(seconds * sim.fps)):
        sim.step()
        if k >= int((seconds - 1.0) * sim.fps):
            worst.append(strain_max(sim))
    return sim, max(worst)


def strain_max(sim):
    x, e = sim.x, sim.g.edges
    return float(((np.linalg.norm(x[e[:, 0]] - x[e[:, 1]], axis=1) - sim.g.edge_rest) / sim.g.edge_rest).max())


def tilted_arm(R=0.045, tilt_deg=30.0, centre=(0.0, 3.0, 0.0), half=0.30, h=0.004):
    """A signed distance grid of a long round 'arm' (radius R) tilted tilt_deg down
    from horizontal along x. -> (grid, origin, h, axis (downhill), centre)."""
    t = np.radians(tilt_deg)
    axis = np.array([np.cos(t), -np.sin(t), 0.0])
    c = np.asarray(centre, float)
    n = int(2 * half / h) + 1
    o = c - half
    ax = o[0] + h * np.arange(n)
    X, Y, Z = np.meshgrid(ax, o[1] + h * np.arange(n), o[2] + h * np.arange(n), indexing="ij")
    P = np.stack([X - c[0], Y - c[1], Z - c[2]], -1)
    along = P @ axis
    radial = np.linalg.norm(P - along[..., None] * axis, axis=-1)
    return (radial - R).astype(np.float64), o, h, axis, c


def sleeve_on_arm(cls, mu, ease=0.03, R=0.045, seconds=1.6, tilt_deg=30.0):
    """A jersey tube (a sleeve), 20 cm long, a little smaller round than the arm, on a
    30-degree tilted arm. -> how far it slid downhill (m) from 0.6 s to 1.6 s."""
    from drape.fabrics import get
    from drape.pattern import Panel, Seam, build_garment
    fab = replace(get("jersey"), friction=mu)
    grid, o, h, axis, c = tilted_arm(R, tilt_deg)
    Rc = R + fab.thickness
    C, H = 2 * np.pi * Rc * (1 - ease), 0.20
    up = np.array([0.0, 1.0, 0.0]); up -= (up @ axis) * axis; up /= np.linalg.norm(up)
    side = np.cross(axis, up)

    def place(uv):
        th = uv[:, 0] / C * 2 * np.pi
        return (c + np.outer(uv[:, 1] - H / 2, axis) + Rc * (np.outer(np.cos(th), up) + np.outer(np.sin(th), side)))
    cc = np.array([[0, 0], [C, 0], [C, H], [0, H]], float)
    edges = [(f"e{k}", np.stack([cc[k], cc[(k + 1) % 4]])) for k in range(4)]
    g = build_garment([Panel("sleeve", edges, place)], [Seam("sleeve", "e1", "sleeve", "e3", reverse=True)], spacing=0.012)
    sim = cls(g, far_body(), fab)
    sim.set_grid(grid, o, h)
    sim.sew_time, sim.gravity_ramp = 0.05, 0.05
    pos = []
    for k in range(int(seconds * sim.fps)):
        sim.step()
        pos.append(float(sim.x.mean(0) @ axis))
    k0 = min(int(0.6 * sim.fps), len(pos))
    return sim, pos[-1] - pos[k0 - 1]


def pendulum(cls, length=0.50, width=0.05, start_deg=20.0, seconds=4.0, fabric="poplin"):
    """A 50 cm strip held along its top edge, let go 20 degrees out: -> period (s)."""
    from drape.fabrics import get
    a = np.radians(start_deg)
    top = np.array([0.0, 3.2, 0.0])

    def place(uv):
        s = length - uv[:, 1]                 # distance down from the top edge
        return np.c_[uv[:, 0] - width / 2 + top[0], top[1] - s * np.cos(a), top[2] + s * np.sin(a)]
    g = strip(width, length, place)
    sim = cls(g, far_body(), get(fabric))
    sim.sew_time, sim.gravity_ramp = 0.0, 0.0
    y = sim.x[:, 1]
    pin_where(sim, y > y.max() - 1e-6)
    bot = y < y.min() + 1e-6
    zs, ts = [], []
    for k in range(int(seconds * sim.fps)):
        sim.step()
        zs.append(float(sim.x[bot, 2].mean())); ts.append(sim.time)
    zs, ts = np.array(zs), np.array(ts)
    cross = [ts[i] - zs[i] * (ts[i + 1] - ts[i]) / (zs[i + 1] - zs[i]) for i in range(len(zs) - 1) if zs[i] * zs[i + 1] < 0]
    if len(cross) < 3:
        return float("nan"), zs
    return float(2 * np.mean(np.diff(cross))), zs
