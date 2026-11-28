// drape studio: symmetric editing
// (classic script: shares one global scope with the others, loaded in order by index.html)
// ------------------------------------------------------------ symmetry
// Left/right pieces (front_r / front_l) are kept mirror images of each other, and a
// piece that is symmetric about its own centre (a tee front) stays symmetric: an
// edit on one side is repeated on the other. Found from the shapes themselves.
DS.sym = LS.get("sym", true);
function renderSymBtn() { const b = $("#symBtn"); b.classList.toggle("on", DS.sym); b.setAttribute("aria-pressed", DS.sym);
  b.title = `Symmetric is ${DS.sym ? "on" : "off"}: a change on one side of a piece is mirrored on the other, and left/right pieces stay mirror images` }
$("#symBtn").onclick = () => { DS.sym = !DS.sym; LS.set("sym", DS.sym); renderSymBtn(); toolHint(); drawDesign() };
const sideKey = n => n.replace(/(^|_)(r|l|right|left)(?=_|$)/g, "$1#");
function symImages(pc) {
  if (!DS.sym || !pc || onHost(pc)) return [];
  const bb = bboxV(pc), size = Math.max(bb[2] - bb[0], bb[3] - bb[1]), tol = Math.max(0.3, 0.012 * size), cx = (bb[0] + bb[2]) / 2;
  const fits = (P, s, o, oy) => P.verts.length === pc.verts.length && pc.verts.every(v => P.verts.some(w => Math.hypot(s * v[0] + o - w[0], v[1] + oy - w[1]) < tol));
  const out = [];
  if (pc.verts.some(v => Math.abs(v[0] - cx) > tol) && fits(pc, -1, 2 * cx, 0)) out.push({P: pc, s: -1, o: 2 * cx, oy: 0});
  const key = sideKey(pc.name);
  if (key !== pc.name) for (const P of D().pieces) {
    if (P === pc || onHost(P) || sideKey(P.name) !== key) continue;
    const b2 = bboxV(P), cx2 = (b2[0] + b2[2]) / 2, oy = b2[1] - bb[1];
    for (const sg of [-1, 1]) if (fits(P, sg, cx2 - sg * cx, oy)) { out.push({P, s: sg, o: cx2 - sg * cx, oy}); break }
  }
  return out;
}
const symMap = (img, p) => [img.s * p[0] + img.o, p[1] + img.oy];
function symVert(img, pc, i) {
  const q = symMap(img, pc.verts[i]); let best = -1, bd = 1e9;
  img.P.verts.forEach((w, j) => { const d = Math.hypot(w[0] - q[0], w[1] - q[1]); if (d < bd) { bd = d; best = j } });
  return best;
}
function symEdge(img, pc, i) {   // the edge on the image that matches edge i: [index, reversed]
  const n = pc.verts.length, ja = symVert(img, pc, i), jb = symVert(img, pc, (i + 1) % n), m = img.P.verts.length;
  if ((ja + 1) % m === jb) return [ja, false];
  if ((jb + 1) % m === ja) return [jb, true];
  return [-1, false];
}
function moveVertexSym(pc, i, dx, dy) {
  const imgs = symImages(pc), plan = imgs.map(img => [img, symVert(img, pc, i)]);
  if (plan.some(([img, j]) => img.P === pc && j === i)) dx = 0;     // on the centre line: it stays there
  moveVertex(pc, i, dx, dy);
  for (const [img, j] of plan) if (!(img.P === pc && j === i)) moveVertex(img.P, j, img.s * dx, dy);
}
function mirrorCurve(pc, i, imgs) {   // after edge i of pc was re-curved: copy the curve to its images
  const e = pc.edges[i];
  for (const img of imgs) {
    const [k, rev] = symEdge(img, pc, i); if (k < 0) continue;
    const t = img.P.edges[k], M = p => p && symMap(img, p);
    if (img.P === pc && k === i) {    // the edge crosses the centre line: keep the curve itself symmetric
      if (e.pts) { const n = e.pts.length; e.pts = e.pts.map((p, q) => { const r = M(e.pts[n - 1 - q]); return [(p[0] + r[0]) / 2, (p[1] + r[1]) / 2] }) }
      else if (e.c1) { const c = [(e.c1[0] + M(e.c2)[0]) / 2, (e.c1[1] + M(e.c2)[1]) / 2]; e.c1 = c; e.c2 = M(c) }
      continue;
    }
    if (e.pts) { const P = e.pts.map(M); t.pts = rev ? P.reverse() : P }
    else { t.c1 = rev ? M(e.c2) : M(e.c1); t.c2 = rev ? M(e.c1) : M(e.c2); delete t.pts }
    custom(img.P);
  }
}
