"""Tiny z-buffered software rasterizer (orthographic, smooth Lambert shading)
plus OBJ export. No GPU or display needed."""
from __future__ import annotations

import numpy as np
from ._jit import njit
from skimage.measure import marching_cubes

from .body import Body


def body_mesh(body: Body, res: float = 0.008, bounds=None, fine: float = 0.003):
    if bounds is None:  # fit the box to this body, hands and feet included
        c = body.caps
        top = float(max(c[:, 1].max(), c[:, 4].max()) + c[:, 6].max()) + 0.03
        xr = float(np.abs(np.r_[c[:, 0], c[:, 3]]).max() + c[:, 6].max()) + 0.03
        zr = float(max(np.abs(body.torso[:, 3]).max() + body.torso[:, 2].max(),
                       np.abs(np.r_[c[:, 2], c[:, 5]]).max() + c[:, 6].max())) + 0.03
        for g in body.groups:  # extremity bounding spheres
            xr = max(xr, abs(g[0]) + g[3]); zr = max(zr, abs(g[2]) + g[3])
        bounds = ((-xr, xr), (-0.02, top), (-zr, zr))
    patches = [v for k, v in getattr(body, "landmarks", {}).items() if k.endswith("_patch_r") or k.endswith("_patch_l")]
    xs, ys, zs = (np.arange(a, b, res) for a, b in bounds)
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    P = np.stack([X.ravel(), Y.ravel(), Z.ravel()], 1)
    d = body.sdf(P)
    # hands/feet get their own fine patches: cut them out of the coarse mesh
    for c, r in patches:
        d = np.maximum(d, -(np.linalg.norm(P - c, axis=1) - r))
    verts, faces = [], []
    v, f, _, _ = marching_cubes(d.reshape(X.shape), 0.0, spacing=(res, res, res))
    verts.append(v + np.array([xs[0], ys[0], zs[0]])); faces.append(f[:, [0, 2, 1]])
    for c, r in patches:
        r2 = r + 2 * res
        xs, ys, zs = (np.arange(c[i] - r2, c[i] + r2, fine) for i in range(3))
        X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
        P = np.stack([X.ravel(), Y.ravel(), Z.ravel()], 1)
        dd = body.sdf(P).reshape(X.shape)
        if dd.min() > 0 or dd.max() < 0:
            continue
        v, f, _, _ = marching_cubes(dd, 0.0, spacing=(fine, fine, fine))
        off = sum(len(q) for q in verts)
        verts.append(v + np.array([xs[0], ys[0], zs[0]])); faces.append(f[:, [0, 2, 1]] + off)
    return np.concatenate(verts), np.concatenate(faces)


def vertex_normals(v, f):
    fn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    n = np.zeros_like(v)
    for k in range(3):
        np.add.at(n, f[:, k], fn)
    return n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-12)


@njit(cache=True)
def _raster(img, zbuf, sx, sy, sz, nrm, col, f, light, two_sided):
    H, W = zbuf.shape
    for t in range(f.shape[0]):
        a, b, c = f[t, 0], f[t, 1], f[t, 2]
        x0, y0, x1, y1, x2, y2 = sx[a], sy[a], sx[b], sy[b], sx[c], sy[c]
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(area) < 1e-12:
            continue
        minx = max(int(min(x0, x1, x2)), 0); maxx = min(int(max(x0, x1, x2)) + 1, W - 1)
        miny = max(int(min(y0, y1, y2)), 0); maxy = min(int(max(y0, y1, y2)) + 1, H - 1)
        for py in range(miny, maxy + 1):
            for px in range(minx, maxx + 1):
                qx, qy = px + 0.5, py + 0.5
                w0 = ((x1 - qx) * (y2 - qy) - (x2 - qx) * (y1 - qy)) / area
                w1 = ((x2 - qx) * (y0 - qy) - (x0 - qx) * (y2 - qy)) / area
                w2 = 1.0 - w0 - w1
                if w0 < 0 or w1 < 0 or w2 < 0:
                    continue
                z = w0 * sz[a] + w1 * sz[b] + w2 * sz[c]
                if z >= zbuf[py, px]:
                    continue
                zbuf[py, px] = z
                nx = w0 * nrm[a, 0] + w1 * nrm[b, 0] + w2 * nrm[c, 0]
                ny = w0 * nrm[a, 1] + w1 * nrm[b, 1] + w2 * nrm[c, 1]
                nz = w0 * nrm[a, 2] + w1 * nrm[b, 2] + w2 * nrm[c, 2]
                nl = np.sqrt(nx * nx + ny * ny + nz * nz) + 1e-12
                d = (nx * light[0] + ny * light[1] + nz * light[2]) / nl
                if two_sided:
                    d = abs(d)
                s = 0.25 + 0.75 * max(d, 0.0)
                for ch in range(3):
                    img[py, px, ch] = min(col[a, ch] * s, 1.0)


class Renderer:
    def __init__(self, body: Body, width=420, height=620, scale=330.0, center=(0.0, 1.05)):
        self.bv, self.bf = body.mesh() if hasattr(body, "mesh") else body_mesh(body)
        if getattr(body, "kind", "") == "mesh":
            # real mesh: smooth vertex normals from its own faces (a 6 mm SDF
            # grid would blur fingers), oriented outward by the SDF
            n = vertex_normals(self.bv, self.bf)
            probe = body.sdf(self.bv + 0.004 * n) - body.sdf(self.bv - 0.004 * n)
            self.bn = n if np.median(probe) > 0 else -n
        else:
            # normals from the SDF gradient: exact direction, no winding ambiguity
            e = 1e-4
            g = np.stack([body.sdf(self.bv + d) - body.sdf(self.bv - d) for d in np.eye(3) * e], 1)
            self.bn = g / (np.linalg.norm(g, axis=1, keepdims=True) + 1e-12)
        self.W, self.H, self.scale, self.center = width, height, scale, center

    def _view(self, yaw_deg):
        a = np.radians(yaw_deg)
        right = np.array([np.cos(a), 0.0, -np.sin(a)])
        fwd = np.array([-np.sin(a), 0.0, -np.cos(a)])  # camera looks along fwd
        return right, np.array([0.0, 1.0, 0.0]), fwd

    def render(self, cloth_x, cloth_f, cloth_colors, yaw=0.0):
        right, up, fwd = self._view(yaw)
        light = -fwd * 0.6 + up * 0.5 + right * 0.4
        light /= np.linalg.norm(light)
        img = np.ones((self.H, self.W, 3)) * np.array([0.96, 0.96, 0.94])
        zbuf = np.full((self.H, self.W), np.inf)

        def proj(v):
            sx = (v @ right - self.center[0]) * self.scale + self.W / 2
            sy = self.H / 2 - (v @ up - self.center[1]) * self.scale
            return sx, sy, v @ fwd

        sx, sy, sz = proj(self.bv)
        bcol = np.tile([0.78, 0.74, 0.70], (len(self.bv), 1))
        _raster(img, zbuf, sx, sy, sz, self.bn, bcol, self.bf, light, False)
        cn = vertex_normals(cloth_x, cloth_f)
        sx, sy, sz = proj(cloth_x)
        _raster(img, zbuf, sx, sy, sz - 1e-4, cn, cloth_colors, cloth_f, light, True)
        return (img * 255).astype(np.uint8)


PANEL_COLORS = np.array([[0.20, 0.42, 0.75], [0.16, 0.55, 0.50], [0.80, 0.45, 0.20], [0.6, 0.3, 0.6]])


def garment_colors(panel_id):
    return PANEL_COLORS[panel_id % len(PANEL_COLORS)]


def write_obj(path, x, tris, uv=None):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# drape garment export\n")
        for p in x:
            fh.write(f"v {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n")
        if uv is not None:
            for t in uv:
                fh.write(f"vt {t[0]:.6f} {t[1]:.6f}\n")
        for a, b, c in tris + 1:
            if uv is not None:
                fh.write(f"f {a}/{a} {b}/{b} {c}/{c}\n")
            else:
                fh.write(f"f {a} {b} {c}\n")


def strain_colors(x, edges, rest, max_strain=0.08):
    """Fit map: per-vertex mean |strain| of incident edges, mapped
    blue (0%) -> green -> yellow -> red (>= max_strain). Returns (colors, per-vertex strain)."""
    L = np.linalg.norm(x[edges[:, 0]] - x[edges[:, 1]], axis=1)
    s = np.abs(L - rest) / rest
    tot = np.bincount(edges[:, 0], s, len(x)) + np.bincount(edges[:, 1], s, len(x))
    cnt = np.bincount(edges[:, 0], minlength=len(x)) + np.bincount(edges[:, 1], minlength=len(x))
    vs = tot / np.maximum(cnt, 1)
    t = np.clip(vs / max_strain, 0, 1)[:, None]
    stops = np.array([[0.20, 0.35, 0.80], [0.15, 0.70, 0.40], [0.95, 0.85, 0.20], [0.85, 0.15, 0.12]])
    pos = t * (len(stops) - 1)
    i = np.minimum(pos.astype(int)[:, 0], len(stops) - 2)
    f = pos[:, 0] - i
    return stops[i] * (1 - f)[:, None] + stops[i + 1] * f[:, None], vs


def legend_bar(height, max_strain=0.08, width=90):
    """Vertical color bar image for the fit map."""
    from PIL import Image, ImageDraw, ImageFont
    vals = np.linspace(max_strain, 0, height)
    stops = np.array([[0.20, 0.35, 0.80], [0.15, 0.70, 0.40], [0.95, 0.85, 0.20], [0.85, 0.15, 0.12]])
    t = vals / max_strain * (len(stops) - 1)
    i = np.minimum(t.astype(int), len(stops) - 2); f = t - i
    col = stops[i] * (1 - f)[:, None] + stops[i + 1] * f[:, None]
    img = np.ones((height, width, 3)) * 0.96
    img[20:height - 20, 6:26] = col[20:height - 20, None, :]
    im = Image.fromarray((img * 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    font = ImageFont.load_default(size=18)
    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        y = int(20 + (1 - frac) * (height - 41))
        d.text((32, y - 10), f"{frac * max_strain * 100:.0f}%", fill=(40, 40, 40), font=font)
    d.text((4, 0), "strain", fill=(40, 40, 40), font=font)
    return np.asarray(im)


# ------------------------------------------------------ measurement guides --
@njit(cache=True)
def _line3(img, zbuf, x0, y0, z0, x1, y1, z1, col, width, bias, dash_len, t_off):
    """Thick line with depth test: solid where visible, dashed + faint where
    hidden behind the body. Returns the arc length drawn (for dash phase)."""
    H, W = zbuf.shape
    n = int(max(abs(x1 - x0), abs(y1 - y0)) * 2) + 1
    r = width * 0.5
    seg = np.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2)
    for s in range(n + 1):
        t = s / n
        x = x0 + (x1 - x0) * t; y = y0 + (y1 - y0) * t; z = z0 + (z1 - z0) * t
        ix, iy = int(x), int(y)
        if ix < 0 or iy < 0 or ix >= W or iy >= H:
            continue
        visible = z <= zbuf[iy, ix] + bias
        if not visible:
            phase = (t_off + seg * t) % (2 * dash_len)
            if phase > dash_len:
                continue
        a = 1.0 if visible else 0.45
        rr = r if visible else max(r * 0.6, 0.8)
        for dy in range(-int(rr) - 1, int(rr) + 2):
            for dx in range(-int(rr) - 1, int(rr) + 2):
                if dx * dx + dy * dy > rr * rr + 0.25:
                    continue
                px, py = ix + dx, iy + dy
                if 0 <= px < W and 0 <= py < H:
                    for c in range(3):
                        img[py, px, c] = img[py, px, c] * (1 - a) + col[c] * a
    return t_off + seg


GUIDE_COLORS = {
    "chest": (0.85, 0.20, 0.20), "underbust": (0.90, 0.45, 0.65), "waist": (0.15, 0.55, 0.90),
    "hip": (0.20, 0.65, 0.35), "neck": (0.60, 0.35, 0.80), "upper_arm": (0.95, 0.55, 0.10),
    "thigh": (0.45, 0.55, 0.15), "shoulder_width": (0.10, 0.70, 0.70), "arm_length": (0.80, 0.60, 0.05),
    "height": (0.35, 0.35, 0.35), "inseam": (0.55, 0.35, 0.15), "hand_girth": (0.85, 0.25, 0.35), "hand_length": (0.70, 0.30, 0.50), "foot_length": (0.30, 0.40, 0.70),
}

LABELS = {"chest": "Chest / bust", "underbust": "Underbust", "waist": "Waist", "hip": "Hip", "neck": "Neck",
          "upper_arm": "Upper arm", "thigh": "Thigh", "shoulder_width": "Shoulder width",
          "arm_length": "Arm length", "height": "Height", "inseam": "Inseam", "hand_length": "Hand length", "hand_girth": "Hand girth",
          "foot_length": "Foot length"}


def render_guides(renderer, paths, yaw, names=None, targets=None, width=3.0, title=None):
    """Body with the tape paths drawn on it, start/end markers and labels.
    targets: optional {name: cm} to show 'avatar (target)'."""
    from PIL import Image, ImageDraw, ImageFont
    R = renderer
    right, up, fwd = R._view(yaw)
    light = -fwd * 0.6 + up * 0.5 + right * 0.4
    light /= np.linalg.norm(light)
    img = np.ones((R.H, R.W, 3)) * np.array([0.97, 0.97, 0.955])
    zbuf = np.full((R.H, R.W), np.inf)

    def proj(v):
        v = np.atleast_2d(v)
        return ((v @ right - R.center[0]) * R.scale + R.W / 2,
                R.H / 2 - (v @ up - R.center[1]) * R.scale, v @ fwd)

    sx, sy, sz = proj(R.bv)
    _raster(img, zbuf, sx, sy, sz, R.bn, np.tile([0.80, 0.77, 0.73], (len(R.bv), 1)), R.bf, light, False)
    labels = []
    body_left = float(sx.min())
    for p in paths:
        if names and p["name"] not in names:
            continue
        col = np.array(GUIDE_COLORS.get(p["name"], (0.2, 0.2, 0.2)))
        # densify (~5 mm) so visibility and the label anchor are judged along
        # the whole line, not just at its corners (arm length's corners are
        # all on the side of the arm, hidden from the front)
        P = p["pts"]
        seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
        dense = [P[0]]
        for a_, b_, L_ in zip(P[:-1], P[1:], seg):
            n_ = max(1, int(L_ / 0.005))
            dense.extend(a_ + (b_ - a_) * (np.arange(1, n_ + 1)[:, None] / n_))
        X, Y, Z = proj(np.array(dense))
        if p.get("beside"):        # e.g. height: a ruler beside the body in every view
            X = np.full_like(X, body_left - 28.0)
            Z = np.full_like(Z, -1e9)
        off = 0.0
        for i in range(len(X) - 1):
            off = _line3(img, zbuf, X[i], Y[i], Z[i], X[i + 1], Y[i + 1], Z[i + 1], col, width,
                         0.012 if not p.get("beside") else 1.0, 5.0, off)
        # where to hang the label: the visible point furthest to the right
        vis = Z <= zbuf[np.clip(Y.astype(int), 0, R.H - 1), np.clip(X.astype(int), 0, R.W - 1)] + 0.012
        k = int(np.argmax(np.where(vis, X, -1e9))) if vis.any() else int(np.argmax(X))
        labels.append((p, col, X, Y, Z, k, vis))
    I = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))
    d = ImageDraw.Draw(I)
    font = ImageFont.load_default(size=13)
    fontb = ImageFont.load_default(size=14)
    # start / end markers (only where visible)
    for p, col, X, Y, Z, k, vis in labels:
        c255 = tuple(int(255 * v) for v in col)
        ends = [0] if p["kind"] == "loop" else [0, len(X) - 1]
        for j in ends:
            if vis[j] or p.get("beside"):
                d.ellipse([X[j] - 5, Y[j] - 5, X[j] + 5, Y[j] + 5], fill=c255, outline=(255, 255, 255), width=2)
        if p["kind"] == "path" and (vis[-1] or p.get("beside")):
            # arrowhead at the end
            dx, dy = X[-1] - X[-2], Y[-1] - Y[-2]
            n_ = np.hypot(dx, dy) + 1e-9; dx, dy = dx / n_, dy / n_
            tip = (X[-1] + dx * 2, Y[-1] + dy * 2)
            d.polygon([tip, (X[-1] - dx * 9 - dy * 5, Y[-1] - dy * 9 + dx * 5),
                       (X[-1] - dx * 9 + dy * 5, Y[-1] - dy * 9 - dx * 5)], fill=c255)
    # labels in two columns (left / right margin), each beside its own path;
    # leader lines from the label to the anchor point on the path
    cx = 0.5 * (float(sx.min()) + float(sx.max()))
    placed = {"L": [], "R": []}
    for p, col, X, Y, Z, k, vis in sorted(labels, key=lambda t: t[3][t[5]]):
        if not vis.any() and not p.get("beside"):
            continue
        side = "L" if (p.get("beside") or float(X[k]) < cx - 5) else "R"
        if side == "L":   # anchor on the left-most visible point instead
            k = int(np.argmin(np.where(vis, X, 1e9))) if vis.any() else k
        y = float(Y[k]) - 12
        for py in sorted(placed[side]):
            if abs(y - py) < 36:
                y = py + 36
        placed[side].append(y)
        c255 = tuple(int(255 * v) for v in col)
        ax, ay = float(X[k]), float(Y[k])
        lx = 8 if side == "L" else R.W - 152
        d.line([(ax, ay), (lx + (144 if side == "L" else -4), y + 15)], fill=c255, width=1)
        txt = LABELS.get(p["name"], p["name"])
        val = f"{p['value_cm']:.1f} cm"
        if targets and targets.get(p["name"]) is not None:
            val += f"  (target {targets[p['name']]:g})"
        d.rounded_rectangle([lx - 4, y - 3, lx + 140, y + 30], radius=5, fill=(255, 255, 255), outline=c255, width=2)
        d.text((lx + 2, y - 1), txt, fill=c255, font=fontb)
        d.text((lx + 2, y + 15), val, fill=(40, 40, 40), font=font)
    if title:
        d.text((10, 8), title, fill=(30, 30, 30), font=ImageFont.load_default(size=17))
    return np.asarray(I)


def measurement_guide(body, targets=None, title=""):
    """Front / back / side sheet of where every measurement is taken on this
    avatar, with the avatar's values (and targets if given)."""
    from .meshmeasure import tape_paths
    paths = tape_paths(body.tape)
    H = body.height()
    R = Renderer(body, width=900, height=900, scale=840 / (H + 0.12), center=(0, H / 2))
    t = targets or {}
    front = render_guides(R, paths, 0, names=["chest", "underbust", "waist", "hip", "neck", "upper_arm", "thigh",
                                               "height", "arm_length", "inseam", "hand_length", "hand_girth", "foot_length"],
                          targets=t, title=(title + " - front").strip(" -"))
    back = render_guides(R, paths, 180, names=["shoulder_width", "neck", "waist", "hip", "height"], targets=t, title="back")
    side = render_guides(R, paths, 90, names=["chest", "waist", "hip", "neck", "height", "foot_length"], targets=t, title="side")
    return np.concatenate([front, back, side], 1)
