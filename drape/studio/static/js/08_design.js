// drape studio: the design editor: pieces, shapes, bands
// (classic script: shares one global scope with the others, loaded in order by index.html)
// ======================================================== design from scratch
// A piece: {name, at:[x,y] (where it sits on the drawing board, cm), verts:[[x,y]] (cm, local),
//   edges:[{name, c1, c2, elastic}] (edge i runs verts[i] -> verts[i+1]; c1/c2 = cubic controls or null),
//   shape:{type, ...dims} (type "custom" once hand-edited), place:{landmark|anchor, at, mode, rotate, offset_cm}}
const PIECE_COLORS = ["#2f6fbf", "#d0742c", "#2f9a7a", "#9a4fb0", "#c4485a", "#7a8a2a", "#3b8fd0", "#b08a2a"];
const pieceColor = i => PIECE_COLORS[i % PIECE_COLORS.length];
const DS = {tool: "select", sewA: null, placing: false, resp: null, drag: null};
// the selected piece and the board's view belong to the garment (switching garments keeps each one's own)
for (const k of ["sel", "view"])
  Object.defineProperty(DS, k, {get() { return activeGarment().ui[k] }, set(v) { activeGarment().ui[k] = v }, enumerable: true});
const KAPPA = 0.5523;
const SHAPES = {
  rect: {label: "Rectangle", dims: [["w", "Width", 50], ["h", "Height", 60]],
    make: d => ({verts: [[-d.w / 2, 0], [d.w / 2, 0], [d.w / 2, d.h], [-d.w / 2, d.h]], names: ["bottom", "right", "top", "left"]})},
  trap: {label: "Trapezoid", dims: [["wb", "Bottom width", 60], ["wt", "Top width", 40], ["h", "Height", 55]],
    make: d => ({verts: [[-d.wb / 2, 0], [d.wb / 2, 0], [d.wt / 2, d.h], [-d.wt / 2, d.h]], names: ["bottom", "right", "top", "left"]})},
  tri: {label: "Triangle", dims: [["w", "Base", 40], ["h", "Height", 35]],
    make: d => ({verts: [[-d.w / 2, 0], [d.w / 2, 0], [0, d.h]], names: ["bottom", "right", "left"]})},
  circle: {label: "Circle", dims: [["d", "Diameter", 40]], make: d => ellipse(d.d, d.d)},
  oval: {label: "Oval", dims: [["w", "Width", 50], ["h", "Height", 30]], make: d => ellipse(d.w, d.h)},
  half: {label: "Half circle", short: "Half", dims: [["d", "Diameter", 60]], make: d => {
    const r = d.d / 2, k = KAPPA * r;
    return {verts: [[-r, 0], [r, 0], [0, r]], names: ["straight", "curve_r", "curve_l"],
      ctrl: [null, [[r, k], [k, r]], [[-k, r], [-r, k]]]};
  }},
};
function ellipse(w, h) {
  const a = w / 2, b = h / 2, ka = KAPPA * a, kb = KAPPA * b;
  return {verts: [[0, 0], [a, b], [0, h], [-a, b]], names: ["q1", "q2", "q3", "q4"],
    ctrl: [[[ka, 0], [a, b - kb]], [[a, b + kb], [ka, h]], [[-ka, h], [-a, b + kb]], [[-a, b - kb], [-ka, 0]]]};
}
function makePiece(type, dims, name) {
  const sh = SHAPES[type], d = {}; for (const [k, , v] of sh.dims) d[k] = dims && dims[k] != null ? dims[k] : v;
  const g = sh.make(d);
  return {name, shape: {type, ...d}, verts: g.verts, at: [0, 0],
    edges: g.names.map((n, i) => ({name: n, c1: g.ctrl && g.ctrl[i] ? g.ctrl[i][0] : null, c2: g.ctrl && g.ctrl[i] ? g.ctrl[i][1] : null, elastic: false})),
    place: {mode: "wrap", rotate: 0, offset_cm: 1.5, at: "center"}};
}
function reshape(pc) {   // dims changed: rebuild, keeping edge names (and so the seams)
  const g = SHAPES[pc.shape.type].make(pc.shape), old = pc.edges;
  pc.verts = g.verts;
  pc.edges = g.names.map((n, i) => ({name: old[i] ? old[i].name : n, c1: g.ctrl && g.ctrl[i] ? g.ctrl[i][0] : null, c2: g.ctrl && g.ctrl[i] ? g.ctrl[i][1] : null, elastic: old[i] ? old[i].elastic : false}));
}
const D = () => ST.design;
const pieceBy = n => D().pieces.find(p => p.name === n);
function edgePts(pc, i, n = 24) {
  const a = pc.verts[i], b = pc.verts[(i + 1) % pc.verts.length], e = pc.edges[i];
  if (e.pts) return e.pts;          // a fixed curve (e.g. from a template): its own points
  if (!e.c1) return [a, b];
  const out = [];
  for (let k = 0; k <= n; k++) {
    const t = k / n, u = 1 - t;
    out.push([u * u * u * a[0] + 3 * u * u * t * e.c1[0] + 3 * u * t * t * e.c2[0] + t * t * t * b[0],
              u * u * u * a[1] + 3 * u * u * t * e.c1[1] + 3 * u * t * t * e.c2[1] + t * t * t * b[1]]);
  }
  return out;
}
function arcFrac(pts) {   // 0..1 along a polyline, per point
  const c = [0]; for (let k = 1; k < pts.length; k++) c.push(c[k - 1] + Math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1]));
  const L = c[c.length - 1] || 1; return c.map(v => v / L);
}
const plen = pts => pts.reduce((s, p, i) => i ? s + Math.hypot(p[0] - pts[i - 1][0], p[1] - pts[i - 1][1]) : 0, 0);
function uniqueName(base, taken) { if (!taken.includes(base)) return base; let i = 2; while (taken.includes(base + "_" + i)) i++; return base + "_" + i }
function serverDesign() {
  return {pieces: D().pieces.map(pc => ({name: pc.name, place: pc.place, role: pc.role, stage: pc.stage, fabric: pc.fabric, interfacing: pc.interfacing, lining: pc.lining,
    edges: pc.edges.map((e, i) => ({name: e.name, pts: edgePts(pc, i).map(p => [+p[0].toFixed(3), +p[1].toFixed(3)]), elastic: e.elastic || undefined, sa: e.sa != null ? e.sa : undefined, hem: e.hem || undefined}))})),
    seams: D().seams,
    // per-design settings (gloves: a fine mesh, a fine body grid, a thin air gap to the skin)
    ...Object.fromEntries(["spacing_cm", "fine_sdf", "body_offset"].filter(k => D()[k] != null).map(k => [k, D()[k]]))};
}

// ---------------------------------------------------------- the toolbar's icons (24 x 24, drawn in currentColor)
const TOOL_ICONS = {
  select: '<path d="M12 3v18M3 12h18M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3"/>',
  sew: '<path d="M5 19 19 5"/><circle cx="18" cy="6" r="1.6"/><path d="M3 14h3M8 14h3M13 14h3M18 14h3"/>',
  rect: '<rect x="4" y="6" width="16" height="12" rx="1"/>',
  trap: '<path d="M3 18h18L17 6H7z"/>',
  tri: '<path d="M12 5l9 14H3z"/>',
  circle: '<circle cx="12" cy="12" r="8"/>',
  oval: '<ellipse cx="12" cy="12" rx="9" ry="6"/>',
  half: '<path d="M3 16a9 9 0 0 1 18 0z"/>',
  neckband: '<path d="M4 5c2 7 14 7 16 0"/><path d="M7 5c1.5 4.5 8.5 4.5 10 0"/>',
  collar: '<path d="M5 9c4 3 10 3 14 0V5c-4 3-10 3-14 0z"/><path d="M8 19v-7M16 19v-7"/>',
  waistband: '<rect x="4" y="4" width="16" height="4" rx="1"/><path d="M5 8 3 20h18L19 8"/>',
  cuff: '<path d="M6 3l2 12h8l2-12"/><rect x="7" y="15" width="10" height="5" rx="1"/>',
  hemband: '<path d="M6 3v12h12V3"/><rect x="5" y="15" width="14" height="5" rx="1"/>',
  hood: '<path d="M6 20c-2-6-1-15 6-16 7 1 8 10 6 16"/><path d="M9 20c0-5 1-8 3-9 2 1 3 4 3 9"/>',
  sym: '<path d="M12 3v18" stroke-dasharray="2 2"/><path d="M9 6H4v12h5M15 6h5v12h-5"/>',
  view3d: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M12 12l8-4.5M12 12v9M12 12 4 7.5"/>',
  seams: '<path d="M4 8h16M4 16h16"/><path d="M6 8v8M10 8v8M14 8v8M18 8v8" stroke-dasharray="2 2"/>',
  restart: '<path d="M4 12a8 8 0 1 0 3-6.2"/><path d="M4 4v5h5"/>',
  add: '<path d="M12 5v14M5 12h14"/>',
  dart: '<path d="M3 6h18"/><path d="M8 6l4 13 4-13"/>',
  pleat: '<path d="M3 18 7 6l4 12 4-12 4 12"/>',
  gathers: '<path d="M3 12c1.5-4 3-4 4.5 0s3 4 4.5 0 3-4 4.5 0 3 4 4.5 0"/>',
  hem: '<path d="M4 6h16"/><path d="M4 13h16" stroke-dasharray="2 2"/><path d="M4 18h16"/>',
  elastic: '<path d="M2 12h3l1.5-5 3 10 3-10 3 10 1.5-5H22"/>',
  sa: '<path d="M4 7h16"/><path d="M4 17h16" stroke-dasharray="3 2"/><path d="M12 9v6M10 11l2-2 2 2M10 13l2 2 2-2"/>',
  split: '<path d="M3 12h7M14 12h7"/><path d="M12 5v14" stroke-dasharray="2 2"/>',
  sleeve: '<path d="M4 9c3-5 13-5 16 0l-2 11H6z"/><path d="M6 15h12" stroke-dasharray="2 2"/>',
};
const icon = k => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${TOOL_ICONS[k] || ""}</svg>`;
// a square toolbar button's insides: the icon over a short label (its title says the rest)
const tbInner = (ic, label) => `${icon(ic)}<span class="tl">${label}</span>`;
$$("[data-ic]").forEach(b => b.innerHTML = tbInner(b.dataset.ic, b.innerHTML));

// -------------------------------------------------------------- side pane
// bands round an opening (feature OPENING_BANDS) and the hood, which isn't a band (always on)
const BANDS = {
  neckband: {label: "Neckband", h: 3, ratio: 0.85, dir: "up", fabric: "rib", help: "a stretchy rib band round a T-shirt neckline"},
  collar: {label: "Collar (stand)", short: "Collar", h: 4, ratio: 1, dir: "up", interfacing: "light", help: "a stand-up collar"},
  waistband: {label: "Waistband", short: "Waist", h: 4, ratio: 1, dir: "up", interfacing: "medium", help: "a band round the top of a skirt or trousers"},
  cuff: {label: "Cuff", h: 7, ratio: 0.9, dir: "down", fabric: "rib", help: "a band at the end of a sleeve or leg"},
  hemband: {label: "Hem band", h: 6, ratio: 0.9, dir: "down", fabric: "rib", help: "a band round the bottom of a top"},
  hood: {label: "Hood", h: 34, ratio: 1, dir: "up", hood: true, help: "a hood, open at the centre front"},
};
function renderBands() {
  $("#bands").innerHTML = Object.entries(BANDS).filter(([k, b]) => b.hood || feature("OPENING_BANDS")).map(([k, b]) => `<button class="tb" data-b="${k}" title="${b.label}: ${b.help}">${tbInner(k, b.short || b.label)}</button>`).join("");
  $$("#bands .tb").forEach(c => c.onclick = () => {
    DS.loopKind = c.dataset.b; DS.loop = []; DS.tool = "loop"; DS.sewA = null;
    $$("#tool button").forEach(b => b.classList.remove("on")); $$("#bands .tb").forEach(b => b.classList.toggle("on", b === c)); toolHint(); drawDesign();
  });
  // Simple mode's Add menu: the same finishes (same feature switches), and the pockets
  $("#addBands").innerHTML = Object.entries(BANDS).filter(([k, b]) => b.hood || feature("OPENING_BANDS")).map(([k, b]) => `<button class="chip" data-ab="${k}" title="${b.help}">${b.label}</button>`).join("");
  $$("#addBands .chip").forEach(c => c.onclick = () => { $("#addMenu").hidden = true; $(`#bands [data-b="${c.dataset.ab}"]`).click() });
  $$("#addMenu [data-add]").forEach(b => b.onclick = () => {
    $("#addMenu").hidden = true;
    if (!DS.sel || !pieceBy(DS.sel)) { toast("Tap the piece the pocket goes on first, then Add ▸ Pocket.", 4000); return }
    const btn = $(b.dataset.add === "inseam" ? "#pinseam" : "#ppocket");
    if (btn) { btn.click(); const f = $("#pform"); if (f) f.scrollIntoView({behavior: "smooth", block: "nearest"}) }
  });
}
$("#cutBtn").onclick = () => {
  const pc = DS.sel && pieceBy(DS.sel);
  if (!pc) { toast("Select the piece to cut first"); return }
  // two dots on the outline straight away, left and right half way up: drag them where the cut goes
  const bb = bboxV(pc), my = (bb[1] + bb[3]) / 2;
  DS.cut = [nearestOnOutline(pc, boardXY(pc, [bb[0] - 1, my])), nearestOnOutline(pc, boardXY(pc, [bb[2] + 1, my]))];
  DS.tool = "cut"; $$("#tool button").forEach(b => b.classList.remove("on")); toolHint(); drawDesign();
};
function outlinePoint(pc, hit) {   // (edge index, fraction along it) -> board point
  const raw = edgePts(pc, hit[0], 60);
  return boardXY(pc, pointAtFrac(raw, arcFrac(raw), hit[1]));
}
function cutReady() {   // the two dots far enough apart to cut between
  const pc = DS.sel && pieceBy(DS.sel);
  if (!pc || !DS.cut || DS.cut.length !== 2) return false;
  const [A, B] = DS.cut.map(h => outlinePoint(pc, h));
  return Math.hypot(A[0] - B[0], A[1] - B[1]) > 1 && !(DS.cut[0][0] === DS.cut[1][0] && Math.abs(DS.cut[0][1] - DS.cut[1][1]) < 0.06);
}
function doCut() {
  const pc = DS.sel && pieceBy(DS.sel);
  if (!pc || !cutReady()) { toast("Drag the dots apart: the cut goes between them"); return }
  const [a, b] = DS.cut; DS.tool = "select"; DS.cut = [];
  $$("#tool button").forEach(x => x.classList.toggle("on", x.dataset.t === "select"));
  cutPiece(pc, a, b); toolHint();
}
function nearestOnOutline(pc, w) {   // board point -> (edge index, t along it)
  let best = [0, 0, 1e9];
  pc.edges.forEach((e, i) => { const raw = edgePts(pc, i, 60), rf = arcFrac(raw);
    const pts = Array.from({length: 121}, (_, k) => pointAtFrac(raw, rf, k / 120)), f = pts.map((_, k) => k / 120);
    pts.forEach((p, k) => { const q = boardXY(pc, p), d = Math.hypot(q[0] - w[0], q[1] - w[1]); if (d < best[2]) best = [i, f[k], d] }) });
  return best;
}
function cutPiece(pc, a, b) {
  // split the outline at both points, then make two pieces joined by a straight 'cut' edge, sewn together
  const tA = Math.min(.97, Math.max(.03, a[1]));
  const A = splitEdgeRaw(pc, a[0], tA);
  let ib = b[0], tB = b[1];
  if (ib === a[0]) { if (tB > tA) { ib = a[0] + 1; tB = (tB - tA) / (1 - tA) } else tB = tB / tA }
  else if (ib > a[0]) ib += 1;
  const B = splitEdgeRaw(pc, ib, Math.min(.97, Math.max(.03, tB)));
  const n = pc.verts.length, ia = pc.verts.indexOf(A), jb = pc.verts.indexOf(B);
  const names = D().pieces.map(p => p.name), n1 = uniqueName(pc.name + "_a", names), n2 = uniqueName(pc.name + "_b", [...names, n1]);
  const part = (nm, i0, i1) => {
    const verts = [], edges = [];
    for (let k = i0; ; k = (k + 1) % n) { verts.push([...pc.verts[k]]); if (k === i1) break; edges.push(JSON.parse(JSON.stringify(pc.edges[k]))) }
    edges.push({name: "cut", c1: null, c2: null, elastic: false});
    return {name: nm, shape: {type: "custom"}, at: [...pc.at], place: JSON.parse(JSON.stringify(pc.place)), fabric: pc.fabric, interfacing: pc.interfacing, verts, edges};
  };
  const P1 = part(n1, ia, jb), P2 = part(n2, jb, ia);
  const i = D().pieces.indexOf(pc); D().pieces.splice(i, 1, P1, P2);
  D().seams.forEach(s => { for (const k of ["a", "b"]) if (s[k].startsWith(pc.name + ".")) { const en = s[k].slice(pc.name.length + 1); s[k] = (P1.edges.some(e => e.name === en) ? n1 : n2) + "." + en } });
  D().pieces.forEach(p => { if (p.place && p.place.on === pc.name) p.place.on = n1 });
  D().seams.push({a: `${n1}.cut`, b: `${n2}.cut`, ease: 0});
  DS.sel = n1; tidy(); dsChanged(true, true); toast(`Cut into ${n1} and ${n2}, sewn together along 'cut'. Unsew it if they should stay apart.`, 5000);
}

// ------------------------------------------------------------ shape it (cut away / join on / keep the overlap)
// A dashed shape laid over a piece (not a piece itself: nothing else sees it). Drag it
// into place, then apply it; the server does the maths and keeps the edges' names and
// seams (dedit.shape_with). With Symmetric on, it's mirrored onto the other side too.
const shapeDims = (kind, s) => ({circle: {d: s}, half: {d: s}, oval: {w: s, h: s * .6}, rect: {w: s, h: s * .6},
  tri: {w: s, h: s * .8}, trap: {wb: s, wt: s * .6, h: s * .6}})[kind];
function startShape(pc) {
  const bb = bboxV(pc), s = Math.max(4, Math.round(Math.min(bb[2] - bb[0], bb[3] - bb[1]) * .35));
  DS.shape = {target: pc.name, kind: "circle", dims: shapeDims("circle", s), src: null, pos: [(bb[0] + bb[2]) / 2, bb[3]], rot: 0};
  DS.tool = "select"; $$("#tool button").forEach(b => b.classList.toggle("on", b.dataset.t === "select"));
  toolHint(); renderShapePanel(); drawDesign();
  if (innerWidth < 980) $("#shapepanel").scrollIntoView({behavior: "smooth"});
}
function shapeOutline() {   // the shape's edges in its piece's own coords: [{name, pts}]
  const S = DS.shape; let tmp;
  if (S.src) { tmp = pieceBy(S.src); if (!tmp) return [] }
  else {
    const g = SHAPES[S.kind].make(S.dims);
    tmp = {verts: g.verts, edges: g.names.map((n, i) => ({name: n, c1: g.ctrl && g.ctrl[i] ? g.ctrl[i][0] : null, c2: g.ctrl && g.ctrl[i] ? g.ctrl[i][1] : null}))};
  }
  const bb = bboxV(tmp), cx = (bb[0] + bb[2]) / 2, cy = (bb[1] + bb[3]) / 2, [c, s] = rotM(S.rot);
  return tmp.edges.map((e, i) => ({name: e.name, pts: edgePts(tmp, i, 32).map(([x, y]) => {
    x -= cx; y -= cy; return [+(c * x - s * y + S.pos[0]).toFixed(3), +(s * x + c * y + S.pos[1]).toFixed(3)] })}));
}
function shapeJobs() {      // [{piece, tools}]: the shape, plus its mirror images when Symmetric is on
  const S = DS.shape, pc = S && pieceBy(S.target), tool = pc ? shapeOutline() : []; if (!tool.length) return [];
  const jobs = [{piece: pc.name, tools: [tool]}];
  if (S.src) return jobs;   // a real piece can only go one place
  for (const img of symImages(pc)) {
    const t2 = tool.map(e => ({name: e.name, pts: e.pts.map(p => symMap(img, p))}));
    const j = jobs.find(x => x.piece === img.P.name); if (j) j.tools.push(t2); else jobs.push({piece: img.P.name, tools: [t2]});
  }
  return jobs;
}
function renderShapePanel() {
  const box = $("#shapepanel"), S = DS.shape;
  if (!S || !ST.design || !pieceBy(S.target)) { DS.shape = null; box.style.display = "none"; box.innerHTML = ""; renderToolPop(); return }
  const u = ST.units, others = D().pieces.filter(p => p.name !== S.target && !onHost(p)), jobs = shapeJobs();
  const both = jobs.length > 1 || jobs.some(j => j.tools.length > 1);
  box.style.display = "flex";
  box.innerHTML = `<b>Shape '${S.target}'</b>
    <div class="chips">${Object.entries(SHAPES).map(([k, v]) => `<button class="chip ${!S.src && S.kind === k ? "on" : ""}" data-sk="${k}">${v.label}</button>`).join("")}</div>
    ${others.length ? `<label class="f">…or the shape of a piece<select id="shsrc"><option value="">none</option>${others.map(p => `<option ${p.name === S.src ? "selected" : ""}>${p.name}</option>`).join("")}</select></label>` : ""}
    ${S.src ? "" : `<div class="grid2">${SHAPES[S.kind].dims.map(([k, l]) => `<label class="f">${l} (${u})<input type="text" inputmode="decimal" data-shd="${k}" value="${toUnit(S.dims[k]).toFixed(u === "in" ? 2 : 1)}"></label>`).join("")}</div>`}
    <div class="slider"><label>Turn it</label><span class="val" id="shrotv">${S.rot}°</span><input type="range" id="shrot" min="-180" max="180" step="5" value="${S.rot}"></div>
    <p class="lead" style="font-size:12px;margin:0">Drag the dashed shape on the pattern to where it goes.${both ? ` <b style="color:var(--accent)">⇋ Done on both sides.</b>` : ""}${S.src ? ` <b>Join it on</b> makes '${S.src}' part of '${S.target}'.` : ""}</p>
    <p class="lead" style="font-size:12px;margin:0">Then <b>Cut it away</b>, <b>Join it on</b> or <b>Keep the overlap</b> in the box on the pattern.</p>`;
  const size = () => Math.max(...Object.values(S.dims));
  $$("#shapepanel [data-sk]").forEach(b => b.onclick = () => { S.dims = shapeDims(b.dataset.sk, S.src ? 20 : size()); S.kind = b.dataset.sk; S.src = null; renderShapePanel(); drawDesign() });
  if ($("#shsrc")) $("#shsrc").onchange = e => { S.src = e.target.value || null; renderShapePanel(); drawDesign() };
  $$("#shapepanel [data-shd]").forEach(inp => inp.onchange = () => { const v = fromUnit(parseFloat(inp.value)); if (v > 0) { S.dims[inp.dataset.shd] = v; drawDesign() } });
  $("#shrot").oninput = e => { S.rot = +e.target.value; $("#shrotv").textContent = S.rot + "°"; drawDesign() };
  renderToolPop();
}
async function applyShape(how) {
  const S = DS.shape, jobs = shapeJobs(); if (!jobs.length) return;
  const ok = how === "split" ? await serverEdit("split", {jobs})            // keep every part, sewn back together
    : await serverEdit("shape", {how, jobs, src: how === "join" && S.src ? S.src : undefined});
  if (ok) { DS.shape = null; renderShapePanel(); drawDesign() }
}
