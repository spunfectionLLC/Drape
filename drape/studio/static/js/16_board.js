// drape studio: server round trip and the drawing board
// (classic script: shares one global scope with the others, loaded in order by index.html)
// ------------------------------------------------------------ server round trip
let dsSeq = 0;
async function dsRefresh() {
  if (!ST.avatar || !ST.scratch) return;
  const seq = ++dsSeq, g = activeGarment();      // an answer for this garment only (a switch mid-request drops it)
  if (!D().pieces.length) { DS.resp = null; GL.setColored(null); renderDsSeams(); renderDsChecks(); return }
  try {
    const r = await api("/api/scratch", {avatar: ST.avatar.id, design: serverDesign()});
    if (seq !== dsSeq || g !== activeGarment()) return; DS.resp = r;
    if (r.preview && !ST.drape) {
      const pid = b64(r.preview.piece, Uint8Array), cols = new Float32Array(pid.length * 3);
      for (let i = 0; i < pid.length; i++) { const h = pieceColor(pid[i]); for (let k = 0; k < 3; k++) cols[i * 3 + k] = parseInt(h.slice(1 + 2 * k, 3 + 2 * k), 16) / 255 * (pieceBy(r.pieces[pid[i]])?.name === DS.sel ? 1 : 0.8) }
      GL.setColored(r.preview, cols); $("#gltitle").textContent = "Where your pieces start (before sewing)";
    }
  } catch (e) { if (g !== activeGarment()) return; DS.resp = {check: [{ok: false, text: "Something went wrong", plain: e.message}]} }
  renderDsSeams(); renderDsChecks();
}
// per garment: a change made just before a switch still gets its own undo step, on its own garment
const dsTimers = {};
function dsSoon() { const g = activeGarment(); (dsTimers[g.id] || (dsTimers[g.id] = debounce(async () => { if (g === activeGarment()) await dsRefresh(); pushHist(g) }, 250)))() }
function overlapping() {
  const B = D().pieces.filter(pc => !onHost(pc)).map(pc => { const b = bboxV(pc); return [b[0] + pc.at[0], b[1] + pc.at[1], b[2] + pc.at[0], b[3] + pc.at[1]] });
  for (let i = 0; i < B.length; i++) for (let j = i + 1; j < B.length; j++)
    if (B[i][0] < B[j][2] && B[j][0] < B[i][2] && B[i][1] < B[j][3] && B[j][1] < B[i][3]) return true;
  return false;
}
function dsChanged(commit, reframe) {
  if (!DS.drag && overlapping()) { tidy(); reframe = true }
  ST.drape = null; ST.sfull = null; renderInspector(); drawDesign(); renderDsSeams();
  if (reframe) { DS.view = null; drawDesign() }
  if (commit) { dsSoon(); liveRefresh() }
}
// live editing: the pattern changed while the cloth is live: rebuild it and carry
// every point over from where it is now (matched by piece and position on the pattern)
let liveRefreshTimer = null;
function liveRefresh() {
  if (!LIVE.sim) return;
  clearTimeout(liveRefreshTimer); liveRefreshTimer = setTimeout(() => startLive(true), 450);
}
$("#dsPreview").onclick = () => go("preview");

// ------------------------------------------------------------ the drawing board
function drawDesign() {
  const host = $("#pattern"); host.classList.add("design"); $("#patov").style.display = "none";
  const P = D().pieces;
  if (!P.length) { host.innerHTML = `<div style="display:grid;place-items:center;height:100%;color:var(--muted);text-align:center;padding:20px">Add a piece on the left<br>(a rectangle is a good start)</div>`; return }
  if (!DS.view) {     // fit the view to the pieces
    let a = [1e9, 1e9, -1e9, -1e9];
    for (const pc of P) pc.edges.forEach((e, i) => edgePts(pc, i).forEach(q => { const [x, y] = boardXY(pc, q); a = [Math.min(a[0], x), Math.min(a[1], y), Math.max(a[2], x), Math.max(a[3], y)] }));
    const pad = Math.max(8, (a[2] - a[0]) * 0.08);
    DS.view = [a[0] - pad, -(a[3] + pad), a[2] - a[0] + 2 * pad, a[3] - a[1] + 2 * pad];
  }
  const [vx, vy, vw, vh] = DS.view, hr = Math.max(vw, vh) / 90;
  let svg = `<svg id="board" viewBox="${vx} ${vy} ${vw} ${vh}" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg">
    <defs><pattern id="grid2" width="10" height="10" patternUnits="userSpaceOnUse"><path d="M10 0H0V10" fill="none" stroke="var(--line)" stroke-width="${hr * .12}"/></pattern></defs>
    <rect x="${vx - vw}" y="${vy - vh}" width="${vw * 3}" height="${vh * 3}" fill="url(#grid2)" data-bg="1"/>`;
  // pieces first, then whatever is sewn on top of them (pockets)
  const order = P.map((pc, k) => [pc, k]).sort((a, b) => !!onHost(a[0]) - !!onHost(b[0]));
  const labels = [];      // label boxes already placed: a label that would overlap one moves down
  order.forEach(([pc, k]) => {
    const T = p => { const [x, y] = boardXY(pc, p); return `${x.toFixed(2)},${(-y).toFixed(2)}` }, sel = pc.name === DS.sel;
    const outline = pc.edges.flatMap((e, i) => edgePts(pc, i).slice(0, -1)).map(T).join(" ");
    svg += `<g data-piece="${pc.name}"><polygon points="${outline}" fill="${pieceColor(k)}" fill-opacity="${sel ? .28 : .14}" stroke="none" data-body="${pc.name}" style="cursor:${DS.tool === "select" ? "move" : "default"}"/>`;
    pc.edges.forEach((e, i) => {
      const sid = seamIndexOf(pc.name, e.name), isA = DS.sewA === pc.name + "." + e.name || (DS.tool === "loop" && DS.loop.includes(pc.name + "." + e.name)), pts = edgePts(pc, i);
      const col = isA ? "var(--accent)" : sid == null ? "var(--ink)" : seamColor(sid);
      svg += `<polyline points="${pts.map(T).join(" ")}" fill="none" stroke="${col}" stroke-width="${hr * (sid == null && !isA ? .35 : .7)}" ${e.elastic ? `stroke-dasharray="${hr} ${hr * .6}"` : ""} stroke-linecap="round"/>`;
      if (e.hem) {   // the turn-up allowance, cut on beyond the edge (outward = right of a counter-clockwise outline)
        const a = e.hem.depth_cm + (e.hem.turn_cm || 0), V = pc.verts;
        const sg = V.reduce((s2, v, k) => s2 + v[0] * V[(k + 1) % V.length][1] - V[(k + 1) % V.length][0] * v[1], 0) >= 0 ? 1 : -1;
        const off = pts.map((q, k) => { const nx = pts[Math.min(k + 1, pts.length - 1)], pv = pts[Math.max(k - 1, 0)], tx = nx[0] - pv[0], ty = nx[1] - pv[1], L = Math.hypot(tx, ty) || 1;
          return [q[0] + sg * ty / L * a, q[1] - sg * tx / L * a] });
        svg += `<polyline points="${off.map(T).join(" ")}" fill="none" stroke="var(--muted)" stroke-width="${hr * .3}" stroke-dasharray="${hr * .8} ${hr * .5}" pointer-events="none"><title>${plainRef(pc.name + "." + e.name)}: ${fmtLen(a)} hem turn-up, cut on</title></polyline>`;
      }
      svg += `<polyline points="${pts.map(T).join(" ")}" fill="none" stroke="transparent" stroke-width="${hr * 2.4}" data-edge="${pc.name}|${i}" style="cursor:${DS.tool === "edge" ? "crosshair" : DS.tool !== "select" ? "pointer" : "copy"}"><title>${plainRef(pc.name + "." + e.name)}: ${fmtLen(plen(pts))}${e.elastic ? " (elastic)" : ""}</title></polyline>`;
    });
    const bb = bboxV(pc), c = T([(bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2]).split(","), full = friendlyPiece(pc);
    // two lines: the name, then the details (a pocket bag's side and half) with the size; the text is
    // sized to fit inside its piece, and moved down if it would land on a label already placed
    const [name, more] = full.includes(" · ") ? full.split(" · ") : [full, ""];
    const fs = Math.min(hr * 2.3, (bb[2] - bb[0]) * 0.9 / Math.max(name.length * 0.58, 1)), fs2 = Math.min(hr * 1.4, fs * 0.7);
    { const w = Math.max(name.length * fs * 0.58, (more.length + 14) * fs2 * 0.55), h = fs + fs2 * 1.6, hit = r => Math.abs(r[0] - +c[0]) < (r[2] + w) / 2 && Math.abs(r[1] - +c[1]) < Math.max(h, r[3]);
      for (let n = 0; n < 12 && labels.some(hit); n++) c[1] = String(+c[1] + h);
      labels.push([+c[0], +c[1], w, h]) }
    svg += `<text x="${c[0]}" y="${c[1]}" text-anchor="middle" font-size="${fs}" font-weight="600" fill="var(--ink)" pointer-events="none" class="plabel">${name}<title>${full}</title></text>`;
    svg += `<text x="${c[0]}" y="${+c[1] + fs2 * 1.5}" text-anchor="middle" font-size="${fs2}" fill="var(--muted)" pointer-events="none">${more ? more + " · " : ""}${fmtLen(bb[2] - bb[0], 0)} × ${fmtLen(bb[3] - bb[1], 0)}${pc.place.anchor || pc.place.landmark || pc.place.template || pc.place.glove || pc.place.loop || pc.place.on || pc.place.layer_of || pc.place.arm ? "" : " · not on the body"}</text>`;
    if (sel && DS.tool === "select") {
      const H = DS.handleEdge && DS.handleEdge.pn === pc.name ? DS.handleEdge.i : -1;
      if (H >= 0 && H < pc.edges.length) {     // the picked edge's handles: direction and strength at each end
        const cc = cubicOf(pc, H), n = pc.verts.length;
        if (cc) [[pc.verts[H], cc[0], 0], [pc.verts[(H + 1) % n], cc[1], 1]].forEach(([end, c, k]) => {
          const a = T(end).split(","), b = T(c).split(",");
          svg += `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="var(--accent)" stroke-width="${hr * .22}" pointer-events="none" class="hndline"/>`;
          svg += `<circle cx="${b[0]}" cy="${b[1]}" r="${hr * .75}" fill="var(--accent)" stroke="var(--panel)" stroke-width="${hr * .2}" data-hnd="${k}" style="cursor:grab"><title>drag: the curve's direction and strength at this end</title></circle>`;
        });
      }
      pc.edges.forEach((e, i) => { const pts = edgePts(pc, i), m = pointAtFrac(pts, arcFrac(pts), .5), t = T(m).split(",");
        svg += `<circle cx="${t[0]}" cy="${t[1]}" r="${hr * .55}" fill="${i === H ? "var(--accent)" : "var(--panel)"}" stroke="var(--accent)" stroke-width="${hr * .25}" data-mid="${i}" style="cursor:grab"><title>drag to curve this edge; click it for handles (direction and strength at each end); right-click: symmetric curve, straighten</title></circle>` });
      const picked = vselOf(pc);
      pc.verts.forEach((v, i) => { const t = T(v).split(","), on = picked.includes(i);
        if (on) svg += `<rect x="${t[0] - hr * 1.15}" y="${t[1] - hr * 1.15}" width="${hr * 2.3}" height="${hr * 2.3}" fill="none" stroke="var(--accent)" stroke-width="${hr * .3}" pointer-events="none" class="vpicked"/>`;
        svg += `<rect x="${t[0] - hr * .7}" y="${t[1] - hr * .7}" width="${hr * 1.4}" height="${hr * 1.4}" fill="${on ? "#fff" : "var(--accent)"}" stroke="var(--accent)" stroke-width="${on ? hr * .3 : 0}" data-vert="${i}" style="cursor:grab"><title>drag to move; shift-click to pick several, or shift-drag a box round them</title></rect>` });
    }
    svg += `</g>`;
  });
  if (DS.drag && DS.drag.kind === "marq") {     // the box picking corners
    const [a, b] = [DS.drag.a, DS.drag.b];
    svg += `<rect x="${Math.min(a[0], b[0])}" y="${-Math.max(a[1], b[1])}" width="${Math.abs(b[0] - a[0])}" height="${Math.abs(b[1] - a[1])}" fill="var(--accent)" fill-opacity=".08" stroke="var(--accent)" stroke-width="${hr * .25}" stroke-dasharray="${hr} ${hr * .6}" pointer-events="none" class="marq"/>`;
  }
  const selP = DS.sel && pieceBy(DS.sel), imgs = DS.tool === "select" ? symImages(selP) : [];
  for (const img of imgs) {
    if (img.P === selP) {   // its own centre line
      const bb = bboxV(selP), cx = img.o / 2, a = boardXY(selP, [cx, bb[1] - 2]), b = boardXY(selP, [cx, bb[3] + 2]);
      svg += `<line x1="${a[0]}" y1="${-a[1]}" x2="${b[0]}" y2="${-b[1]}" stroke="var(--accent)" stroke-width="${hr * .25}" stroke-dasharray="${hr} ${hr * .7}" pointer-events="none"/>`;
    } else {
      const P = img.P, pts = P.edges.flatMap((e, i) => edgePts(P, i).slice(0, -1)).map(q => { const [x, y] = boardXY(P, q); return `${x},${-y}` }).join(" ");
      svg += `<polygon points="${pts}" fill="none" stroke="var(--accent)" stroke-width="${hr * .5}" stroke-dasharray="${hr} ${hr * .7}" pointer-events="none"/>`;
    }
  }
  for (const g of (DS.ghost || [])) {   // a tool's preview (pockets): what pressing its button would add or change
    const pts = g.edges.flatMap((e, i) => edgePts(g, i).slice(0, -1)).map(q => { const [x, y] = boardXY(g, q); return `${x},${-y}` }).join(" ");
    svg += `<polygon points="${pts}" fill="var(--accent)" fill-opacity=".12" stroke="var(--accent)" stroke-width="${hr * .6}" stroke-dasharray="${hr * 1.2} ${hr * .7}" pointer-events="none" class="ghost"/>`;
  }
  for (const [g, P] of (DS.ghostEdges || [])) {   // ... and the edges of existing pieces it would move
    const pts = P.map(q => { const [x, y] = boardXY(g, q); return `${x},${-y}` }).join(" ");
    svg += `<polyline points="${pts}" fill="none" stroke="var(--accent)" stroke-width="${hr * .8}" stroke-dasharray="${hr * 1.2} ${hr * .7}" pointer-events="none" class="ghost"/>`;
  }
  if (DS.tool === "cut" && selP && DS.cut && DS.cut.length === 2) {   // the cut line and its two draggable dots
    const [A, B] = DS.cut.map(h => outlinePoint(selP, h));
    svg += `<line x1="${A[0]}" y1="${-A[1]}" x2="${B[0]}" y2="${-B[1]}" stroke="#d6453d" stroke-width="${hr * .55}" stroke-dasharray="${hr * 1.1} ${hr * .6}" pointer-events="none"/>`;
    [A, B].forEach((P, k) => { svg += `<circle cx="${P[0]}" cy="${-P[1]}" r="${hr * 1.15}" fill="#fff" stroke="#d6453d" stroke-width="${hr * .45}" data-cuth="${k}" style="cursor:grab"><title>drag along the edge</title></circle>` });
  }
  if (DS.tool === "edge" && DS.edgeHover && pieceBy(DS.edgeHover.pn)) {   // the edge tool's marker, and its mirror images
    const H = DS.edgeHover, T = EDGE_TOOLS[DS.edgeTool] || {}, O = DS.edgeOpts[DS.edgeTool] || {}, mk = "#c27a12";
    const W = q => { const [x, y] = q; return `${x.toFixed(2)},${(-y).toFixed(2)}` };
    for (const [P, k, t] of edgeTargets(pieceBy(H.pn), H.i, H.t)) {
      const pts = edgePts(P, k, 80);
      if (!T.at) { svg += `<polyline class="edgemark" points="${pts.map(q => W(boardXY(P, q))).join(" ")}" fill="none" stroke="${mk}" stroke-width="${hr * 1.2}" stroke-linecap="round" opacity=".7" pointer-events="none"/>`; continue }
      const f = arcFrac(pts), L = plen(pts), u = Math.min(.9, Math.max(.1, t)), M = pointAtFrac(pts, f, DS.edgeTool === "split" ? t : u);
      if ((DS.edgeTool === "dart" || DS.edgeTool === "pleat") && O.w > 0 && O.d > 0) {   // the wedge it would sew closed
        const a = pointAtFrac(pts, f, Math.max(0, u - .02)), b = pointAtFrac(pts, f, Math.min(1, u + .02));
        let nx = -(b[1] - a[1]), ny = b[0] - a[0]; const nl = Math.hypot(nx, ny) || 1; nx /= nl; ny /= nl;
        const P1 = pointAtFrac(pts, f, u - O.w / 2 / L), P2 = pointAtFrac(pts, f, u + O.w / 2 / L), tip = [M[0] + nx * O.d, M[1] + ny * O.d];
        svg += `<polygon class="edgemark" points="${[P1, tip, P2].map(q => W(boardXY(P, q))).join(" ")}" fill="${mk}" fill-opacity=".15" stroke="${mk}" stroke-width="${hr * .45}" stroke-dasharray="${hr * .9} ${hr * .5}" pointer-events="none"/>`;
      }
      const c = boardXY(P, M);
      svg += `<circle class="edgemark" cx="${c[0]}" cy="${-c[1]}" r="${hr * 1.1}" fill="#fff" stroke="${mk}" stroke-width="${hr * .5}" pointer-events="none"/>`;
    }
  }
  if (DS.shape && !pieceBy(DS.shape.target)) renderShapePanel();      // its piece went (undo, delete)
  if (DS.shape) shapeJobs().forEach((job, j) => job.tools.forEach((tool, k) => {   // the shape being laid on, and its mirror images
    const P = pieceBy(job.piece), main = !j && !k;
    const pts = tool.flatMap(e => e.pts.slice(0, -1)).map(q => { const [x, y] = boardXY(P, q); return `${x.toFixed(2)},${(-y).toFixed(2)}` }).join(" ");
    svg += `<polygon points="${pts}" fill="var(--accent)" fill-opacity="${main ? .2 : .08}" stroke="var(--accent)" stroke-width="${hr * .45}" stroke-dasharray="${hr * .9} ${hr * .5}" ${main ? `data-shape="1" style="cursor:move"` : `pointer-events="none"`}><title>${main ? "drag the shape where it goes" : "mirror image"}</title></polygon>`;
  }));
  svg += `</svg>`;
  host.innerHTML = svg + `<button class="btn small" id="fitBoard" style="position:absolute;right:14px;bottom:12px" title="Line the pieces up and fit them in view">⤢ Tidy</button>`; bindBoard();
  $("#fitBoard").onclick = () => { tidy(); DS.view = null; drawDesign(); pushHist() };
  drawBadges();
}
function tidy() {   // pieces in rows, bottoms lined up (pockets ride on their piece)
  const P = D().pieces.filter(pc => !onHost(pc)); if (!P.length) return;
  const B = P.map(bboxV), area = B.reduce((a, b) => a + (b[2] - b[0] + 10) * (b[3] - b[1] + 10), 0);
  const rowW = Math.max(Math.sqrt(area) * 1.5, ...B.map(b => b[2] - b[0]));
  let x = 0, y = 0, rowH = 0;
  P.forEach((pc, i) => {
    const b = B[i], w = b[2] - b[0], h = b[3] - b[1];
    if (x > 0 && x + w > rowW) { x = 0; y -= rowH + 10; rowH = 0 }
    pc.at = [x - b[0], y - b[1] - h]; x += w + 10; rowH = Math.max(rowH, h);
  });
}
const onHost = pc => pc.place && pc.place.on ? pieceBy(pc.place.on) : null;
function rotM(deg) { const t = (deg || 0) * Math.PI / 180; return [Math.cos(t), Math.sin(t)] }
// Pieces sewn inside another (pocket bags) are drawn beside it, not over it: a row to its right at
// their own height. Drawing only: where they go on the body (place.pos) doesn't change.
function asideShift(pc) {
  if (!pc.place || !pc.place.inside) return [0, 0];
  const h = onHost(pc); if (!h) return [0, 0];
  // in a row to the right of every piece on the board (beside its host they landed on the next piece)
  const inside = q => q.place && q.place.inside && onHost(q);
  const list = [...D().pieces.filter(inside), ...(DS.ghost || []).filter(q => inside(q) && !pieceBy(q.name))];
  let right = -1e9;
  for (const q of D().pieces) if (!onHost(q)) right = Math.max(right, bboxV(q)[2] + q.at[0]);
  let x = right + 10;
  for (const q of list) {
    const b = bboxV(q), H = onHost(q), base = (q.place.pos || [0, 0])[0] + H.at[0];   // where it would be drawn on its host
    if (q === pc || q.name === pc.name) return [x - (b[0] + base), 0];
    x += b[2] - b[0] + 5;
  }
  return [0, 0];
}
function boardXY(pc, p) {      // a piece's own coords -> drawing-board coords (cm, y up)
  const h = onHost(pc);
  if (!h) return [p[0] + pc.at[0], p[1] + pc.at[1]];
  const [c, s] = rotM(pc.place.rotate), pos = pc.place.pos || [0, 0], a = asideShift(pc);
  return [c * p[0] - s * p[1] + pos[0] + h.at[0] + a[0], s * p[0] + c * p[1] + pos[1] + h.at[1] + a[1]];
}
function boardInv(pc, w) {
  const h = onHost(pc);
  if (!h) return [w[0] - pc.at[0], w[1] - pc.at[1]];
  const [c, s] = rotM(pc.place.rotate), pos = pc.place.pos || [0, 0], a = asideShift(pc);
  const x = w[0] - pos[0] - h.at[0] - a[0], y = w[1] - pos[1] - h.at[1] - a[1];
  return [c * x + s * y, -s * x + c * y];
}
function boardDelta(pc, dx, dy) { if (!onHost(pc)) return [dx, dy]; const [c, s] = rotM(pc.place.rotate); return [c * dx + s * dy, -s * dx + c * dy] }
// ---- several corners at once: DS.vsel = {pn, ids} (corners of the selected piece)
function vselOf(pc) { return pc && DS.vsel && DS.vsel.pn === pc.name ? DS.vsel.ids.filter(i => i < pc.verts.length) : [] }
function moveGroupSym(pc, ids, grab, dx, dy) {
  // with Symmetric on, a picked corner whose own mirror image is picked too follows it mirrored: the one on the side
  // that was grabbed leads (moving both by the same amount would break the symmetry)
  const self = symImages(pc).find(img => img.P === pc), mid = self ? self.o / 2 : 0;
  const side = Math.sign(pc.verts[grab][0] - mid) || 1;
  const lead = ids.filter(i => { if (!self) return true; const j = symVert(self, pc, i);
    return j === i || !ids.includes(j) || (Math.sign(pc.verts[i][0] - mid) || 1) === side });
  for (const i of lead) moveVertexSym(pc, i, dx, dy);
}
function nudgeCorners(dx, dy) {   // the arrow keys: the picked corners move a little
  const pc = DS.sel && pieceBy(DS.sel), ids = vselOf(pc); if (!ids.length) return false;
  const [ddx, ddy] = boardDelta(pc, dx, dy);
  if (ids.length > 1) moveGroupSym(pc, ids, ids[0], ddx, ddy); else moveVertexSym(pc, ids[0], ddx, ddy);
  drawDesign(); dsSoon(); return true;
}
function moveVertex(pc, i, dx, dy) {   // a corner moves; the two edges meeting there follow
  custom(pc); const n = pc.verts.length, v = pc.verts[i];
  v[0] += dx; v[1] += dy; const ein = pc.edges[(i - 1 + n) % n], eout = pc.edges[i];
  if (ein.c2) { ein.c2[0] += dx; ein.c2[1] += dy } if (eout.c1) { eout.c1[0] += dx; eout.c1[1] += dy }
  if (ein.pts) { const f = arcFrac(ein.pts); ein.pts = ein.pts.map((p, k) => [p[0] + dx * f[k], p[1] + dy * f[k]]) }
  if (eout.pts) { const f = arcFrac(eout.pts); eout.pts = eout.pts.map((p, k) => [p[0] + dx * (1 - f[k]), p[1] + dy * (1 - f[k])]) }
}
// ---- Bezier handles: an edge as one cubic (its two controls are the handles at its ends) ----
const bez = (a, c1, c2, b, t) => { const u = 1 - t; return [0, 1].map(j => u * u * u * a[j] + 3 * u * u * t * c1[j] + 3 * u * t * t * c2[j] + t * t * t * b[j]) };
function cubicOf(pc, i) {   // [c1, c2] of edge i: its own, a straight edge's at thirds, or fitted to a drawn curve (null: none fits)
  const n = pc.verts.length, a = pc.verts[i], b = pc.verts[(i + 1) % n], e = pc.edges[i];
  if (e.c1 && e.c2 && !e.pts) return [e.c1, e.c2];
  if (!e.pts) return [[a[0] + (b[0] - a[0]) / 3, a[1] + (b[1] - a[1]) / 3], [a[0] + 2 * (b[0] - a[0]) / 3, a[1] + 2 * (b[1] - a[1]) / 3]];
  const P = e.pts, f = arcFrac(P); let s11 = 0, s12 = 0, s22 = 0; const r1 = [0, 0], r2 = [0, 0];
  P.forEach((p, k) => { const t = f[k], u = 1 - t, B1 = 3 * u * u * t, B2 = 3 * u * t * t;
    s11 += B1 * B1; s12 += B1 * B2; s22 += B2 * B2;
    for (const j of [0, 1]) { const r = p[j] - u * u * u * a[j] - t * t * t * b[j]; r1[j] += B1 * r; r2[j] += B2 * r } });
  const det = s11 * s22 - s12 * s12; if (Math.abs(det) < 1e-12) return null;
  const c1 = [0, 1].map(j => (s22 * r1[j] - s12 * r2[j]) / det), c2 = [0, 1].map(j => (s11 * r2[j] - s12 * r1[j]) / det);
  const Q = Array.from({length: 61}, (_, k) => bez(a, c1, c2, b, k / 60));        // does one cubic follow the curve?
  const err = Math.max(...P.map(p => Math.min(...Q.map(q => Math.hypot(q[0] - p[0], q[1] - p[1]))))), chord = Math.hypot(b[0] - a[0], b[1] - a[1]);
  return err <= Math.max(0.15, 0.02 * chord) ? [c1, c2] : null;
}
function acrossMiddle(a, b, p) {   // p mirrored across the line square to a-b through its middle
  const L = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1, d = [(b[0] - a[0]) / L, (b[1] - a[1]) / L], m = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  const s = (p[0] - m[0]) * d[0] + (p[1] - m[1]) * d[1]; return [p[0] - 2 * s * d[0], p[1] - 2 * s * d[1]];
}
function curveMenu(pc, i, x, y) {
  $$(".gctx").forEach(m => m.remove());
  const e = pc.edges[i], curved = !!(e.c1 || e.pts), m = document.createElement("div");
  m.className = "ddmenu gctx curvemenu"; m.style.cssText = `position:fixed;left:${x}px;top:${y}px;z-index:50`;
  m.innerHTML = `<button class="btn small" data-c="sym">${e.symc ? "✓ " : ""}Symmetric curve</button>
    <button class="btn small" data-c="straight" ${curved ? "" : "disabled"}>Straighten</button>`;
  document.body.appendChild(m);
  m.onclick = ev => {
    const k = ev.target.dataset.c; m.remove(); if (!k) return;
    const sym = symImages(pc), n = pc.verts.length, a = pc.verts[i], b = pc.verts[(i + 1) % n];
    custom(pc);
    if (k === "straight") { e.c1 = null; e.c2 = null; delete e.pts; delete e.symc }
    else if (e.symc) delete e.symc;
    else {                // on: both ends get the same curve (the two handles averaged, mirrored)
      if (!toCubic(pc, i)) { toast("This edge isn't one smooth curve: straighten it first", 4000); return }
      e.symc = true;
      const c2m = acrossMiddle(a, b, e.c2); e.c1 = [(e.c1[0] + c2m[0]) / 2, (e.c1[1] + c2m[1]) / 2]; e.c2 = acrossMiddle(a, b, e.c1);
    }
    mirrorCurve(pc, i, sym);
    for (const img of sym) { const [j] = symEdge(img, pc, i); if (j >= 0) { const t2 = img.P.edges[j]; if (e.symc) t2.symc = true; else delete t2.symc } }
    DS.handleEdge = {pn: pc.name, i}; dsChanged(true);
    toast(k === "straight" ? `${e.name} straightened` : `${e.name}: ${e.symc ? "symmetric curve (both ends alike)" : "each end curves on its own"}`, 2500);
  };
  setTimeout(() => document.addEventListener("click", () => m.remove(), {once: true}), 0);
}
function toCubic(pc, i) {   // make edge i a cubic (handles to drag); false if its drawn curve isn't one smooth curve
  const c = cubicOf(pc, i); if (!c) return false;
  const e = pc.edges[i]; e.c1 = [...c[0]]; e.c2 = [...c[1]]; delete e.pts; return true;
}
function pointAtFrac(pts, f, t) {
  for (let k = 1; k < pts.length; k++) if (f[k] >= t) { const u = (t - f[k - 1]) / ((f[k] - f[k - 1]) || 1); return [pts[k - 1][0] + (pts[k][0] - pts[k - 1][0]) * u, pts[k - 1][1] + (pts[k][1] - pts[k - 1][1]) * u] }
  return pts[pts.length - 1];
}
function svgPt(e) { const sv = $("#board"), p = sv.createSVGPoint(); p.x = e.clientX; p.y = e.clientY; const q = p.matrixTransform(sv.getScreenCTM().inverse()); return [q.x, -q.y] }
function bindBoard() {
  const sv = $("#board");
  sv.addEventListener("pointerdown", e => {
    const t = e.target, w = svgPt(e);
    if (t.dataset.edge && DS.tool === "sew") { sewClick(t.dataset.edge); return }
    if (DS.tool === "edge") {
      if (!t.dataset.edge) return;
      const pc = pieceBy(t.dataset.edge.split("|")[0]), hit = nearestOnOutline(pc, w);
      DS.edgeHover = null; applyEdgeTool(pc, hit[0], hit[1]); return;
    }
    if (t.dataset.shape && DS.shape) { DS.drag = {kind: "shape", last: w}; sv.setPointerCapture(e.pointerId); return }
    if (DS.tool === "cut") {
      const pc = pieceBy(DS.sel); if (!pc) return;
      if (t.dataset.cuth != null) { DS.drag = {kind: "cuth", k: +t.dataset.cuth}; sv.setPointerCapture(e.pointerId); return }
      const hit = nearestOnOutline(pc, w); if (hit[2] > Math.max(DS.view[2], DS.view[3]) / 25) { toast("Drag the dots, or tap the edge of " + pc.name); return }
      const d = DS.cut.map(h => { const P = outlinePoint(pc, h); return Math.hypot(P[0] - w[0], P[1] - w[1]) });
      DS.cut[d[0] <= d[1] ? 0 : 1] = hit; toolHint(); drawDesign();        // the nearer dot jumps there
      return;
    }
    if (t.dataset.edge && DS.tool === "loop") {
      const [pn, i] = t.dataset.edge.split("|"), k = pn + "." + pieceBy(pn).edges[+i].name;
      DS.loop = DS.loop.includes(k) ? DS.loop.filter(x => x !== k) : [...DS.loop, k]; toolHint(); drawDesign(); return;
    }
    if (DS.tool !== "select") return;
    const pc = DS.sel && pieceBy(DS.sel);
    const multi = e.shiftKey || e.ctrlKey || e.metaKey;
    if (t.dataset.vert != null && pc) {
      const i = +t.dataset.vert, cur = vselOf(pc);
      if (multi) { DS.vsel = {pn: pc.name, ids: cur.includes(i) ? cur.filter(x => x !== i) : [...cur, i]}; drawDesign(); return }
      if (!cur.includes(i)) DS.vsel = {pn: pc.name, ids: [i]};
      DS.drag = {kind: "vert", pc, i, last: w};
    }
    else if (multi && pc && t.dataset.hnd == null && t.dataset.mid == null) { DS.drag = {kind: "marq", pc, a: w, b: w, keep: vselOf(pc)} }
    else if (t.dataset.hnd != null && pc && DS.handleEdge && DS.handleEdge.pn === pc.name) {
      const i = DS.handleEdge.i; if (!toCubic(pc, i)) return;
      DS.drag = {kind: "hnd", pc, i, k: +t.dataset.hnd, sym: symImages(pc)};
    }
    else if (t.dataset.mid != null && pc) {
      const i = +t.dataset.mid, e = pc.edges[i]; DS.handleEdge = {pn: pc.name, i};
      const cub = e.pts ? cubicOf(pc, i) : null;           // a drawn curve: reshaped as one smooth curve when it fits one
      DS.drag = {kind: "mid", pc, i, orig: e.pts && !cub ? e.pts.map(p => [...p]) : null, cub: !e.pts || !!cub, sym: symImages(pc), start: w, moved: false};
    }
    else if (t.dataset.body || t.dataset.edge) {
      const name = t.dataset.body || t.dataset.edge.split("|")[0];
      if (DS.sel !== name) { DS.sel = name; renderInspector(); drawDesign(); dsRefresh(); return }
      DS.drag = {kind: "move", pc: pieceBy(name), last: w};
    } else if (t.dataset.bg) { if (DS.sel) { DS.sel = null; renderInspector(); drawDesign() } return }
    if (DS.drag) sv.setPointerCapture(e.pointerId);
  });
  sv.addEventListener("pointermove", e => {
    const d = DS.drag;
    if (!d && DS.tool === "edge") { edgeHover(e); return }
    if (!d) return; const w = svgPt(e);
    if (d.kind === "cuth") {          // a cut dot slides along the outline, following the pointer
      const pc = pieceBy(DS.sel); if (pc) { DS.cut[d.k] = nearestOnOutline(pc, w); renderToolPop() }
    }
    else if (d.kind === "shape") {
      const [dx, dy] = boardDelta(pieceBy(DS.shape.target), w[0] - d.last[0], w[1] - d.last[1]);
      DS.shape.pos = [DS.shape.pos[0] + dx, DS.shape.pos[1] + dy]; d.last = w;
    }
    else if (d.kind === "move") {
      const dx = w[0] - d.last[0], dy = w[1] - d.last[1];
      if (onHost(d.pc)) { const p = d.pc.place.pos || [0, 0]; d.pc.place.pos = [p[0] + dx, p[1] + dy] } else { d.pc.at[0] += dx; d.pc.at[1] += dy }
      d.last = w;
    }
    else if (d.kind === "marq") { d.b = w }
    else if (d.kind === "vert") {
      const [ddx, ddy] = boardDelta(d.pc, w[0] - d.last[0], w[1] - d.last[1]), ids = vselOf(d.pc);
      if (ids.length > 1) moveGroupSym(d.pc, ids, d.i, ddx, ddy); else moveVertexSym(d.pc, d.i, ddx, ddy); d.last = w;
    } else if (d.kind === "hnd") {
      custom(d.pc); const e = d.pc.edges[d.i], p = boardInv(d.pc, w); e[d.k ? "c2" : "c1"] = p;
      if (e.symc) { const n = d.pc.verts.length; e[d.k ? "c1" : "c2"] = acrossMiddle(d.pc.verts[d.i], d.pc.verts[(d.i + 1) % n], p) }
      mirrorCurve(d.pc, d.i, d.sym);
    } else if (d.kind === "mid") {
      if (!d.moved && Math.hypot(w[0] - d.start[0], w[1] - d.start[1]) < DS.view[2] / 300) return;   // a click: just the handles
      custom(d.pc); const n = d.pc.verts.length, a = d.pc.verts[d.i], b = d.pc.verts[(d.i + 1) % n], m = boardInv(d.pc, w);
      if (!d.moved && d.cub) { toCubic(d.pc, d.i); const e = d.pc.edges[d.i]; d.c0 = [[...e.c1], [...e.c2]]; d.mid0 = bez(a, e.c1, e.c2, b, .5) }
      d.moved = true;
      if (d.cub) {    // the curve's middle follows the pointer; both handles move together, so their shape is kept
        const e = d.pc.edges[d.i], k = 4 / 3, dx = (m[0] - d.mid0[0]) * k, dy = (m[1] - d.mid0[1]) * k;
        e.c1 = [d.c0[0][0] + dx, d.c0[0][1] + dy]; e.c2 = [d.c0[1][0] + dx, d.c0[1][1] + dy];
      } else if (d.orig) {   // a fixed curve: push its middle toward the pointer, ends stay put
        const f = arcFrac(d.orig), mid = pointAtFrac(d.orig, f, 0.5), dx = m[0] - mid[0], dy = m[1] - mid[1];
        d.pc.edges[d.i].pts = d.orig.map((p, k) => { const w4 = 4 * f[k] * (1 - f[k]); return [p[0] + dx * w4, p[1] + dy * w4] });
      }
      mirrorCurve(d.pc, d.i, d.sym);
    }
    drawDesign();
  });
  const end = () => { if (!DS.drag) return;
    if (DS.drag.kind === "shape") { DS.drag = null; renderShapePanel(); drawDesign(); return }   // not part of the design yet
    if (DS.drag.kind === "cuth") { DS.drag = null; drawDesign(); renderToolPop(); return }
    if (DS.drag.kind === "marq") {       // every corner of the piece inside the box (added to the ones picked)
      const {pc, a, b, keep} = DS.drag, x0 = Math.min(a[0], b[0]), x1 = Math.max(a[0], b[0]), y0 = Math.min(a[1], b[1]), y1 = Math.max(a[1], b[1]);
      const inside = pc.verts.map((v, i) => [boardXY(pc, v), i]).filter(([q]) => q[0] >= x0 && q[0] <= x1 && q[1] >= y0 && q[1] <= y1).map(([, i]) => i);
      DS.vsel = {pn: pc.name, ids: [...new Set([...keep, ...inside])]}; DS.drag = null; drawDesign();
      if (inside.length) toast(`${DS.vsel.ids.length} corners picked: drag one to move them together (arrow keys nudge, Esc lets go)`, 3000);
      return;
    }
    if (DS.drag.kind === "mid" && !DS.drag.moved) { DS.drag = null; drawDesign(); return }    // clicked: its handles show
    const moved = DS.drag.kind !== "move" || !!onHost(DS.drag.pc);
    if (DS.drag.kind === "move" && onHost(DS.drag.pc)) {   // keep a pocket's middle on its piece
      const pc = DS.drag.pc, h = onHost(pc), hb = bboxV(h), b = bboxV(pc), pos = pc.place.pos;
      const cx = (b[0] + b[2]) / 2, cy = (b[1] + b[3]) / 2;
      pos[0] = Math.min(hb[2] - (b[2] - b[0]) / 2, Math.max(hb[0] + (b[2] - b[0]) / 2, pos[0] + cx)) - cx;
      pos[1] = Math.min(hb[3] - (b[3] - b[1]) / 2, Math.max(hb[1] + (b[3] - b[1]) / 2, pos[1] + cy)) - cy;
    }
    DS.drag = null;
    if (moved) dsChanged(true); else { drawDesign(); pushHist() } };
  sv.addEventListener("pointerup", end); sv.addEventListener("pointercancel", end);
  sv.addEventListener("contextmenu", e => {     // right-click a curve dot: symmetric curve on / off, straighten
    const t = e.target, pc = DS.sel && pieceBy(DS.sel); if (t.dataset.mid == null || !pc || DS.tool !== "select") return;
    e.preventDefault(); curveMenu(pc, +t.dataset.mid, e.clientX, e.clientY);
  });
  sv.addEventListener("dblclick", e => {
    const t = e.target; if (!t.dataset.edge || DS.tool !== "select") return;
    const [pn, i] = t.dataset.edge.split("|"), pc = pieceBy(pn), w = svgPt(e);
    const hit = nearestOnOutline(pc, w);
    splitEdge(pc, hit[0], Math.min(.95, Math.max(.05, hit[1])));
  });
  sv.addEventListener("wheel", e => {
    e.preventDefault(); const f = Math.exp(e.deltaY * .0015), w = svgPt(e), X = w[0], Y = -w[1], v = DS.view;
    const s = Math.max(v[2], v[3]), F = Math.min(Math.max(f, 2 / s), 5000 / s);     // 2 cm to 50 m across
    DS.view = [X + (v[0] - X) * F, Y + (v[1] - Y) * F, v[2] * F, v[3] * F]; drawDesign();
  }, {passive: false});
}
let hoverFrame = 0;
function edgeHover(e) {   // the edge tool: a marker where a click would put it (and on the mirror images)
  const t = e.target, pc = t.dataset && t.dataset.edge && pieceBy(t.dataset.edge.split("|")[0]);
  const H = pc ? (h => ({pn: pc.name, i: h[0], t: h[1]}))(nearestOnOutline(pc, svgPt(e))) : null, o = DS.edgeHover;
  if (!H && !o) return;
  if (H && o && H.pn === o.pn && H.i === o.i && (!EDGE_TOOLS[DS.edgeTool]?.at || Math.abs(H.t - o.t) < .01)) return;
  DS.edgeHover = H; cancelAnimationFrame(hoverFrame); hoverFrame = requestAnimationFrame(drawDesign);
}
function sewClick(key) {
  const [pn, i] = key.split("|"), k = pn + "." + pieceBy(pn).edges[+i].name;
  if (seamIndexOf(pn, pieceBy(pn).edges[+i].name) != null) { toast(`${k} is already sewn. Unsew it from the list first, or split it.`); return }
  if (!DS.sewA) { DS.sewA = k; toolHint(); drawDesign(); return }
  if (DS.sewA === k) { DS.sewA = null; toolHint(); drawDesign(); return }
  D().seams.push({a: DS.sewA, b: k, ease: 0}); toast(`Sewn: ${plainRef(DS.sewA)} ↔ ${plainRef(k)}`); DS.sewA = null; toolHint(); dsChanged(true);
}

GL.onClothClick(explainCb);
