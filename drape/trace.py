"""Trace a pattern piece from a photo of a garment (or a paper pattern)
lying flat on a contrasting surface.

The scale comes from two points the user taps on something of known length
in the photo (a ruler, a sheet of letter paper). The garment is whatever
stands out from the background colour (read from the photo's border), the
largest blob wins; its outline is split into edges at the sharp corners so
it arrives as a few named edges, not hundreds of segments.
"""
from __future__ import annotations

import base64
import io

import numpy as np


def _load(data_url: str, max_side=1400):
    from PIL import Image, ImageOps
    raw = base64.b64decode(data_url.split(",", 1)[-1])
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    s = min(1.0, max_side / max(im.size))
    if s < 1:
        im = im.resize((round(im.width * s), round(im.height * s)))
    return np.asarray(im, float) / 255.0, s


def trace(data_url: str, p1, p2, length_cm: float, corner_deg=35.0, simplify_cm=0.4, invert=False):
    """Returns {"verts": [[x,y]...] (cm), "edges": [{"name", "pts"}], "mask": png data url, ...}.
    p1, p2: the two tapped points in ORIGINAL image pixels."""
    from skimage import color, filters, measure, morphology
    from scipy import ndimage
    img, s = _load(data_url)
    lab = color.rgb2lab(img)
    h, w = lab.shape[:2]
    b = max(4, min(h, w) // 40)
    border = np.concatenate([lab[:b].reshape(-1, 3), lab[-b:].reshape(-1, 3), lab[:, :b].reshape(-1, 3), lab[:, -b:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    dist = np.linalg.norm(lab - bg, axis=2)
    dist = filters.gaussian(dist, 2)
    t = filters.threshold_otsu(dist)
    mask = dist > t
    if invert:
        mask = ~mask
    r = max(2, min(h, w) // 150)
    mask = ndimage.binary_opening(mask, morphology.disk(r))
    mask = ndimage.binary_closing(mask, morphology.disk(r * 2))
    mask = ndimage.binary_fill_holes(mask)
    lbl = measure.label(mask)
    if lbl.max() == 0:
        raise ValueError("couldn't find the garment: try a plainer background that contrasts with it")
    sizes = np.bincount(lbl.ravel()); sizes[0] = 0
    keep = lbl == sizes.argmax()
    if keep.mean() > 0.9:
        raise ValueError("the garment seems to fill the whole photo: leave some background around it")
    cs = measure.find_contours(np.pad(keep, 1).astype(float), 0.5)
    c = max(cs, key=len)[:, ::-1] - 1                          # (x, y) pixels
    # scale: cm per pixel of the resized image
    px = np.linalg.norm((np.asarray(p2, float) - np.asarray(p1, float)) * s)
    if px < 5:
        raise ValueError("the two scale points are too close together")
    k = float(length_cm) / px
    P = np.stack([c[:, 0] * k, -c[:, 1] * k], 1)                # cm, y up
    P -= [(P[:, 0].min() + P[:, 0].max()) / 2, P[:, 1].min()]
    P = measure.approximate_polygon(P, simplify_cm)[:-1]
    # counter-clockwise
    x, y = P[:, 0], P[:, 1]
    if 0.5 * (x @ np.roll(y, -1) - y @ np.roll(x, -1)) < 0:
        P = P[::-1]
    # corners: turning angle above corner_deg, judged over ~2 cm each side
    n = len(P)
    seglen = np.linalg.norm(np.roll(P, -1, 0) - P, axis=1)
    cum = np.r_[0, np.cumsum(seglen)]
    L = cum[-1]

    def at(sv):
        sv = np.mod(np.atleast_1d(sv), L)
        return np.stack([np.interp(sv, cum, np.r_[P[:, 0], P[0, 0]]), np.interp(sv, cum, np.r_[P[:, 1], P[0, 1]])], 1)
    ang = np.zeros(n)
    for i in range(n):
        a, o, bb = at(cum[i] - 2.0)[0], P[i], at(cum[i] + 2.0)[0]
        u, v = o - a, bb - o
        ang[i] = np.degrees(np.arctan2(u[0] * v[1] - u[1] * v[0], u @ v))
    corner = np.abs(ang) > corner_deg
    # thin out corners closer than 2 cm (keep the sharpest)
    idx = list(np.nonzero(corner)[0])
    idx.sort(key=lambda i: -abs(ang[i]))
    chosen = []
    for i in idx:
        if all(min(abs(cum[i] - cum[j]), L - abs(cum[i] - cum[j])) > 2.0 for j in chosen):
            chosen.append(i)
    chosen.sort()
    if len(chosen) < 3:   # smooth shape (a circle): cut in four
        chosen = sorted({int(np.argmin(np.abs(cum[:-1] - L * q))) for q in (0, .25, .5, .75)})
    verts, edges = [], []
    for j, i in enumerate(chosen):
        nxt = chosen[(j + 1) % len(chosen)]
        seq = list(range(i, nxt + 1)) if nxt > i else list(range(i, n)) + list(range(0, nxt + 1))
        pts = P[seq]
        verts.append(P[i].round(2).tolist())
        edges.append({"name": f"e{j + 1}", "pts": pts.round(2).tolist() if len(pts) > 2 else None})
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray((keep * 255).astype(np.uint8)).save(buf, "PNG")
    bbox = P.max(0) - P.min(0)
    return {"verts": verts, "edges": edges, "width_cm": round(float(bbox[0]), 1), "height_cm": round(float(bbox[1]), 1),
            "mask": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(),
            "outline_px": (c[::max(1, len(c) // 400)] / s).round(1).tolist()}
