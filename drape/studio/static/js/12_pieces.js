// drape studio: design tools: finishing bands, the piece inspector, piece and edge operations
// (classic script: shares one global scope with the others, loaded in order by index.html)
async function finishBand() {
  const kind = DS.loopKind, B = BANDS[kind], loop = [...DS.loop];
  DS.tool = "select"; DS.loop = []; $$("#tool button").forEach(b => b.classList.toggle("on", b.dataset.t === "select"));
  if (!loop.length) { toolHint(); drawDesign(); return }
  if (!B.hood && !feature("OPENING_BANDS")) { toast(B.label + ": not available in this build"); toolHint(); drawDesign(); return }
  toolHint();
  // the server puts the edges in order round the opening as they sit on the body (a hood starts
  // and ends at the centre front), whatever order they were tapped in
  if (!ST.avatar) return bandHere(kind, loop);
  if (await serverEdit("band", {kind, loop, avatar: ST.avatar.id})) {
    const pc = D().pieces[D().pieces.length - 1], L = pc.edges.reduce((s, e, i) => s + (e.name.startsWith("join_") ? plen(edgePts(pc, i)) : 0), 0);
    DS.sel = pc.name; renderInspector(); drawDesign();
    toast(`${B.label}: ${fmtLen(L)} long, starting ${B.hood ? "at the centre front" : "at " + pc.place.loop[0]}` + (B.ratio < 1 ? ` (${Math.round(B.ratio * 100)}% of the opening, so it stretches to fit)` : ""), 4500);
  }
}
function bandHere(kind, loop) {   // no avatar to place the edges on: the band follows the tapped order
  const B = BANDS[kind];
  if (!B.hood && !feature("OPENING_BANDS")) { toast(B.label + ": not available in this build"); return }
  if (B.hood) {   // the hood opens at the centre front: split the front neckline there and start the loop from it
    const [pn, en] = loop[0].split("."), pc = pieceBy(pn), i = pc.edges.findIndex(e => e.name === en), pts = edgePts(pc, i);
    if (pts[0][0] * pts[pts.length - 1][0] < 0) {
      const f = arcFrac(pts); let t = .5; for (let k = 1; k < pts.length; k++) if (pts[k - 1][0] * pts[k][0] <= 0) { const u = pts[k - 1][0] / ((pts[k - 1][0] - pts[k][0]) || 1); t = f[k - 1] + (f[k] - f[k - 1]) * u; break }
      splitEdge(pc, i, t);
      const e1 = pc.edges[i].name, e2 = pc.edges[i + 1].name;
      loop = [`${pn}.${e2}`, ...loop.slice(1), `${pn}.${e1}`];
    }
  }
  const lens = loop.map(r => { const [pn, en] = r.split("."), pc = pieceBy(pn); return plen(edgePts(pc, pc.edges.findIndex(e => e.name === en))) * B.ratio });
  const L = lens.reduce((a, b) => a + b, 0), h = B.h, names = D().pieces.map(p => p.name);
  const name = uniqueName(kind, names);
  const verts = [], edges = [];
  let x = -L / 2;
  lens.forEach((l, k) => { verts.push([x, 0]); edges.push({name: `join_${k + 1}`, c1: null, c2: null, elastic: false}); x += l });
  verts.push([L / 2, 0]); edges.push({name: "end_r", c1: null, c2: null, elastic: false});
  if (B.hood) {
    verts.push([L / 2, h]); edges.push({name: "top_r", c1: null, c2: null, elastic: false});
    verts.push([0, h * 1.12]); edges.push({name: "top_l", c1: null, c2: null, elastic: false});
  } else { verts.push([L / 2, h]); edges.push({name: "top", c1: null, c2: null, elastic: false}) }
  verts.push([-L / 2, h]); edges.push({name: "end_l", c1: null, c2: null, elastic: false});
  const pc = {name, verts, edges, shape: {type: "custom"}, at: [0, 0], fabric: B.fabric, interfacing: B.interfacing,
    place: {loop, dir: B.dir, offset_cm: 0.5, rotate: 0, layer: 0}};
  D().pieces.push(pc);
  // a band cut shorter than its opening stretches onto it: say so in the seam (that's the ease)
  const ease = B.ratio < 1 ? +(1 / B.ratio - 1).toFixed(4) : 0;
  loop.forEach((r, k) => { D().seams = D().seams.filter(s => s.a !== r && s.b !== r); D().seams.push({a: `${name}.join_${k + 1}`, b: r, ease}) });
  if (B.hood) D().seams.push({a: `${name}.top_r`, b: `${name}.top_l`, ease: 0, reverse: true});
  else D().seams.push({a: `${name}.end_r`, b: `${name}.end_l`, ease: 0});   // the band closes into a ring
  DS.sel = name; tidy(); dsChanged(true, true);
  toast(`${B.label}: ${fmtLen(L)} long` + (B.ratio < 1 ? ` (${Math.round(B.ratio * 100)}% of the opening, so it stretches to fit)` : ""), 4500);
}
function renderShapes() {
  $("#shapes").innerHTML = Object.entries(SHAPES).map(([k, v]) => `<button class="tb" data-s="${k}" title="Add a ${v.label.toLowerCase()}">${tbInner(k, v.short || v.label)}</button>`).join("");
  $$("#shapes .tb").forEach(c => c.onclick = () => {
    const names = D().pieces.map(p => p.name), pc = makePiece(c.dataset.s, null, uniqueName("piece", names).replace("piece_", "piece "));
    pc.name = uniqueName(pc.name.replace(/ /g, "_"), names);
    // put it to the right of what's there
    const xs = D().pieces.map(p => p.at[0] + Math.max(...p.verts.map(v => v[0])));
    pc.at = [xs.length ? Math.max(...xs) + 10 - Math.min(...pc.verts.map(v => v[0])) : 0, 0];
    D().pieces.push(pc); DS.sel = pc.name; dsChanged(true, true);
  });
}
$("#dsExample").onclick = () => { ST.design = exampleToClient(ST.init.example_design); DS.sel = ST.design.pieces[0].name; DS.view = null; dsChanged(true, true) };
$("#dsClear").onclick = () => { if (D().pieces.length && !confirm("Start over with an empty board?")) return; ST.design = {pieces: [], seams: []}; DS.sel = null; DS.view = null; dsChanged(true) };
function exampleToClient(ex) {   // server example (polylines) -> editable pieces
  return {seams: JSON.parse(JSON.stringify(ex.seams)), pieces: ex.pieces.map((p, k) => {
    const verts = p.edges.map(e => e.pts[0]);
    const xs = verts.map(v => v[0]), w = Math.max(...xs) - Math.min(...xs), h = Math.max(...verts.map(v => v[1]));
    return {name: p.name, verts, at: [k * (w + 10), 0], shape: {type: "rect", w, h},
      edges: p.edges.map(e => ({name: e.name, c1: null, c2: null, elastic: !!e.elastic})), place: {...p.place}};
  })};
}
$("#tool").onclick = e => { const b = e.target.closest("[data-t]"), t = b && b.dataset.t; if (!t) return; DS.tool = t; DS.sewA = null; $$("#tool button").forEach(b => b.classList.toggle("on", b.dataset.t === t)); toolHint(); drawDesign() };
function toolExit() {   // back to the shape tool, whatever was going on
  DS.tool = "select"; DS.sewA = null; DS.loop = []; DS.cut = []; DS.edgeTool = null; DS.edgeHover = null;
  $$("#tool button").forEach(b => b.classList.toggle("on", b.dataset.t === "select")); toolHint(); drawDesign();
}
function toolHint() {
  $$("#bands .tb").forEach(b => b.classList.toggle("on", DS.tool === "loop" && b.dataset.b === DS.loopKind));   // the opening being finished
  $$("#edgetools .tb").forEach(b => b.classList.toggle("on", DS.tool === "edge" && b.dataset.et === DS.edgeTool));
  const busy = DS.tool === "cut" || DS.tool === "loop" || DS.tool === "sew" || DS.tool === "edge";
  $("#toolhint").textContent = busy ? "Follow the box on the pattern (Esc cancels)."
    : "Drag a piece to move it · drag a corner to reshape · drag the dot on an edge to curve it · double-click an edge to split it.";
  const imgs = DS.tool === "select" ? symImages(DS.sel && pieceBy(DS.sel)) : [];
  if (imgs.length) $("#toolhint").innerHTML += `<br><b style="color:var(--accent)">⇋ Mirrored:</b> ${imgs.map(i => i.P === pieceBy(DS.sel) ? "both halves of " + DS.sel : i.P.name).join(", ")}`;
  renderToolPop();
}
function renderToolPop() {   // the active tool's instructions and its Done / Cancel, on the board where you work
  const box = $("#toolpop"); if (!box) return;
  let title = "", text = "", btns = [], extra = "", bind = null;
  if (DS.tool === "edge" && EDGE_TOOLS[DS.edgeTool]) {
    const k = DS.edgeTool, T = EDGE_TOOLS[k], O = DS.edgeOpts[k], u = ST.units, dec = u === "in" ? 2 : 1;
    title = T.label === "Seam allow." ? "Seam allowance" : T.label;
    text = `${T.help} <b>Click ${T.at ? "the spot on an edge" : "an edge"}</b>${DS.sym ? "; its mirror image gets the same (Symmetric is on)" : ""}.`;
    if (k === "sleeve") {
      text = `${T.help} <b>${DS.sewA ? `Now click the back armhole edge (${plainRef(DS.sewA)} is the front)` : "Click the front armhole edge"}</b>${DS.sym ? "; the other arm gets one too (Symmetric is on)" : ""}.`;
      extra = Object.entries(SLEEVE_OPTS).map(([key, opts]) => `<div class="chips">${opts.map(([v, l]) => `<button class="chip ${O[key] === v ? "on" : ""}" data-sl="${key}:${v}">${l}</button>`).join("")}</div>`).join("");
    } else if (k === "hem") {
      if (O.depth == null) Object.assign(O, hemDefaults(O.style));
      const H = ST.init.hem_styles;
      extra = `<div class="chips">${Object.entries(H).map(([s, x]) => `<button class="chip ${s === O.style ? "on" : ""}" data-hs="${s}">${x.label}</button>`).join("")}</div>
        <div class="grid2"><label class="f">Finished depth (${u})<input type="text" inputmode="decimal" data-eo="depth" value="${toUnit(O.depth).toFixed(dec)}"></label>
        <label class="f">Turned under first (${u})<input type="text" inputmode="decimal" data-eo="turn" value="${toUnit(O.turn).toFixed(dec)}"></label></div>`;
    } else if (T.opts) {
      extra = `<div class="grid2">${T.opts.map(([o, lab, , pct]) => `<label class="f">${lab}${pct ? "" : ` (${u})`}<input type="text" inputmode="decimal" data-eo="${o}" ${o === "sa" ? `placeholder="default ${toUnit(ST.sa).toFixed(dec)}"` : ""} value="${O[o] == null ? "" : pct ? O[o] : toUnit(O[o]).toFixed(dec)}"></label>`).join("")}</div>`;
    }
    bind = () => {
      $$("#toolpop [data-hs]").forEach(b => b.onclick = () => { Object.assign(O, hemDefaults(b.dataset.hs)); renderToolPop() });
      $$("#toolpop [data-sl]").forEach(b => b.onclick = () => { const [key, v] = b.dataset.sl.split(":"); O[key] = v; renderToolPop() });
      $$("#toolpop [data-eo]").forEach(inp => inp.oninput = () => {
        const o = inp.dataset.eo, v = parseFloat(inp.value), pct = (T.opts || []).some(x => x[0] === o && x[3]);
        if (o === "sa" && inp.value.trim() === "") { O.sa = null; return }
        O[o] = !isFinite(v) ? NaN : pct ? v : o === "sa" ? Math.min(10, Math.max(0, fromUnit(v))) : fromUnit(v);   // checked when the edge is clicked
      });
    };
    btns = [["Done", "primary", toolExit]];
  } else if (DS.tool === "loop") {
    const B = BANDS[DS.loopKind] || {label: "Band"};
    title = "+ " + B.label;
    text = `Tap the edges round the opening (${DS.loop.length} picked${DS.loopKind === "hood" ? "; any order: the hood opens at the centre front" : ", in any order"}).`;
    btns = [["Done", "primary", finishBand, !DS.loop.length], ["Cancel", "", toolExit]];
  } else if (DS.tool === "cut") {
    title = "✂ Cut a piece";
    const pc = pieceBy(DS.sel), ok = cutReady();
    let len = "";
    if (ok) { const [A, B] = DS.cut.map(h => outlinePoint(pc, h)); len = ` The cut is ${fmtLen(Math.hypot(A[0] - B[0], A[1] - B[1]))} long.` }
    text = `Drag the two dots along the edge of <b>${DS.sel}</b> (or tap the edge to move the nearer one): it's cut in two along the line between them.${len}`;
    btns = [["✂ Cut here", "primary", doCut, !ok], ["Cancel", "", toolExit]];
  } else if (DS.tool === "sew") {
    title = "🧵 Sew";
    text = DS.sewA ? `Now tap the edge that <b>${DS.sewA}</b> sews to.` : "Tap an edge, then the edge it sews to. Same color = sewn together.";
    btns = [["Done", "primary", toolExit]];
    if (DS.sewA) btns.push(["Pick another edge", "", () => { DS.sewA = null; toolHint(); drawDesign() }]);
  } else if (DS.shape && pieceBy(DS.shape.target)) {
    title = `◐ Shape '${DS.shape.target}'`;
    text = "Drag the dashed shape where it goes. Change its shape and size under Tools.";
    btns = [["✂ Cut it away", "primary", () => applyShape("cut")], ["＋ Join it on", "primary", () => applyShape("join")],
            ["◧ Keep the overlap", "", () => applyShape("keep")], ["⫽ Split along it", "", () => applyShape("split")],
            ["Cancel", "", () => { DS.shape = null; renderShapePanel(); drawDesign() }]];
  }
  if (!title || !ST.scratch || ST.step !== "fit") { box.style.display = "none"; box.innerHTML = ""; return }
  box.style.display = "flex";
  box.innerHTML = `<div class="tp-title">${title}</div><div>${text}</div>${extra}
    <div class="row" style="flex-wrap:wrap;gap:6px">${btns.map(([l, c, , off], k) => `<button class="btn small ${c}" data-tp="${k}" ${off ? "disabled" : ""}>${l}</button>`).join("")}</div>
    <div class="tp-keys">${btns.length > 1 ? "Enter: " + btns[0][0].replace(/^\W+\s*/, "") + " · " : ""}Esc: cancel</div>`;
  $$("#toolpop [data-tp]").forEach(b => b.onclick = () => btns[+b.dataset.tp][2]());
  if (bind) bind();
}
addEventListener("keydown", e => {   // picked corners: arrow keys nudge them (0.5 cm, 5 with Shift), Esc lets go
  if (document.body.dataset.step !== "design" || DS.tool !== "select" || /INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return;
  const st = (e.shiftKey ? 5 : 0.5) * (ST.units === "in" ? 1.27 : 1), k = {ArrowLeft: [-st, 0], ArrowRight: [st, 0], ArrowUp: [0, st], ArrowDown: [0, -st]}[e.key];
  if (k && nudgeCorners(...k)) { e.preventDefault(); return }
  if (e.key === "Escape" && DS.vsel && DS.vsel.ids.length) { DS.vsel = null; drawDesign() }
});
addEventListener("keydown", e => {   // Esc cancels the active tool, Enter finishes it
  if (!ST.scratch || ST.step !== "fit" || /INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return;
  if (e.key === "Escape" && (DS.tool !== "select" || DS.shape)) {
    e.preventDefault();
    if (DS.shape) { DS.shape = null; renderShapePanel(); drawDesign() } else toolExit();
  } else if (e.key === "Enter" && $("#toolpop") && $("#toolpop").style.display !== "none") {
    const b = $("#toolpop [data-tp='0']"); if (b && !b.disabled) { e.preventDefault(); b.click() }
  }
});
const LANDMARK_OPTS = pl => (pl && pl.loop ? `<option value="__loop">round the opening it finishes</option>` : "") + (pl && pl.template ? `<option value="__template">where the pattern puts it</option>` : "") + (pl && pl.arm ? `<option value="__arm">round the ${pl.arm > 0 ? "right" : "left"} arm (a drafted sleeve)</option>` : "") + `<option value="">— pick a spot —</option>` + `<option value="__on">sewn onto another piece (pocket, patch)</option>` + Object.entries(ST.init.landmarks).map(([k, v]) => `<option value="${k}">${v}</option>`).join("") + `<option value="__tap">Tap the avatar…</option>`;
function pieceStageLine(pc) {   // staged sewing: when this piece is sewn on (from its role and place)
  const st = DS.resp && DS.resp.stages && DS.resp.stages.piece, k = st && st[pc.name];
  if (!k) return "";
  const many = Object.values(st).some(v => v > 1);
  return many ? `<p class="lead stage-line" style="font-size:12px;margin:2px 0 0">Sews in stage ${k}${k === 1 ? " (with the body)" : ", after the body has settled"}</p>` : "";
}
const PIECE_ROLES = [["", "not set (from where it sits)"], ["body", "body"], ["sleeve", "sleeve"], ["hood", "hood"], ["collar", "collar / neckband"],
  ["cuff", "cuff"], ["waistband", "waistband / hem band"], ["pocket", "pocket"], ["other", "other"]];
function sewOrderRow(pc) {   // Advanced: the piece's sewing order (1 / 2 / 3 / auto) and its role
  const st = DS.resp && DS.resp.stages, now = st && st.piece && st.piece[pc.name];
  const chip = (v, l, t) => `<span class="tag ${(pc.stage || "auto") === v ? "on" : ""}" data-pstage="${v}" title="${t}">${l}</span>`;
  return `<div class="adv stagerow" id="psew"><small>Sewing order</small> ${[1, 2, 3].map(v => chip(v, v, `Sew it in stage ${v}`)).join("")}
      ${chip("auto", `auto${!pc.stage && now ? ` <i class="stage-auto">(${now})</i>` : ""}`, "From its role and where it sits: body pieces first, then hoods, collars, cuffs and waistbands, then pockets")}</div>
    <label class="f adv">Role<select id="prole">${PIECE_ROLES.map(([k, l]) => `<option value="${k}" ${(pc.role || "") === k ? "selected" : ""}>${l}</option>`).join("")}</select></label>`;
}
// ---- a tool's preview before you press its button (pockets): the server works the edit out without
// keeping it; the pieces it would add or change are drawn dashed on the board (DS.ghost)
let previewSeq = 0;
async function previewEdit(op, args) {
  const seq = ++previewSeq, msg = () => $("#pvmsg");
  try {
    const r = await api("/api/edit", {design: D(), op, args, avatar: ST.avatar ? ST.avatar.id : undefined});
    if (seq !== previewSeq) return;            // a newer preview (or Add/Cancel) since
    // new pieces in full; of the pieces it changes, only the edges that move (an edge split at the
    // same place, like the side seam over a pocket opening, isn't a change you'd see)
    const cur = new Map(D().pieces.map(p => [p.name, p]));
    DS.ghost = []; DS.ghostEdges = [];
    for (const p of r.design.pieces) {
      const c = cur.get(p.name);
      if (!c) { DS.ghost.push(p); continue }
      // compared where they land on the board (a mirrored piece can come back in other coordinates)
      const segs = c.edges.flatMap((e, i) => { const P = edgePts(c, i).map(q => boardXY(c, q)); return P.slice(1).map((q, k) => [P[k], q]) });
      const off = q => Math.min(...segs.map(([a, b]) => { const dx = b[0] - a[0], dy = b[1] - a[1], L = dx * dx + dy * dy || 1e-9,
        t = Math.max(0, Math.min(1, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / L)); return Math.hypot(q[0] - a[0] - t * dx, q[1] - a[1] - t * dy) }));
      p.edges.forEach((e, i) => { const P = edgePts(p, i); if (P.some(q => off(boardXY(p, q)) > 0.1)) DS.ghostEdges.push([p, P]) });
    }
    if (msg()) msg().textContent = `Preview: dashed on the pattern. Change the numbers to adjust it.`;
  } catch (e) {
    if (seq !== previewSeq) return;
    DS.ghost = []; DS.ghostEdges = []; if (msg()) msg().textContent = "Can't preview: " + e.message;
  }
  drawDesign();
}
function clearPreview() {
  previewSeq++;
  if ((DS.ghost && DS.ghost.length) || (DS.ghostEdges && DS.ghostEdges.length)) { DS.ghost = []; DS.ghostEdges = []; drawDesign() }
}
function livePreview(op, args, inputs) {   // preview now, and again (after a pause) whenever an input changes
  let t = null;
  const again = () => { clearTimeout(t); t = setTimeout(() => previewEdit(op, args()), 350) };
  inputs.forEach(s => { const el = $(s); if (el) { el.oninput = again; el.onchange = again } });
  previewEdit(op, args());
}
function renderInspector() {
  clearPreview();                              // the form goes with it
  const pc = DS.sel && pieceBy(DS.sel);
  if (!pc) { $("#inspector").innerHTML = D().pieces.length ? `<p class="lead">Tap a piece to edit it.</p>` : ""; return }
  const pl = pc.place, sh = pc.shape, u = ST.units;
  const dimF = sh.type !== "custom" ? SHAPES[sh.type].dims.map(([k, l]) => `<label class="f">${l} (${u})<input type="text" inputmode="decimal" data-dim="${k}" value="${(+toUnit(sh[k])).toFixed(u === "in" ? 2 : 1)}"></label>`).join("")
    : `<label class="f">Width (${u})<input type="text" inputmode="decimal" data-scale="0" value="${toUnit(bboxV(pc)[2] - bboxV(pc)[0]).toFixed(1)}"></label><label class="f">Height (${u})<input type="text" inputmode="decimal" data-scale="1" value="${toUnit(bboxV(pc)[3] - bboxV(pc)[1]).toFixed(1)}"></label>`;
  const where = pl.loop ? "__loop" : pl.on ? "__on" : pl.template ? "__template" : pl.arm ? "__arm" : pl.anchor ? "__tap" : (pl.landmark || "");
  const hosts = D().pieces.filter(p => p !== pc && !onHost(p) && !(p.place && p.place.on));
  const free = pl.on || pl.template || pl.loop || pl.arm;
  const idx = D().pieces.indexOf(pc);
  const joinable = D().seams.map((s, k) => { const mine = s.a.startsWith(pc.name + ".") ? s.a : s.b.startsWith(pc.name + ".") ? s.b : null, theirs = mine === s.a ? s.b : s.a;
    return [s, k, mine, theirs] }).filter(([s, , mine, theirs]) => mine && theirs.split(".")[0] !== pc.name && !(s.ease > 0) && !onHost(pieceBy(theirs.split(".")[0])));
  $("#inspector").innerHTML = `<div class="ins">
    <div class="row" style="justify-content:space-between"><b style="display:flex;gap:8px;align-items:center"><i style="width:12px;height:12px;border-radius:3px;background:${pieceColor(idx)};display:inline-block"></i>
      <span class="begi">${friendlyPiece(pc)}</span><input class="advi" type="text" id="pname" value="${pc.name}" style="width:150px"></b>
      <span class="row"><button class="btn small advi" id="pdup" title="Duplicate">⧉</button><button class="btn small advi" id="pmir" title="Mirror copy (left/right pair)">⇋</button><button class="btn small" id="pdel" title="Delete">🗑</button></span></div>
    <div class="grid2">${dimF}</div>
    <div class="adv">
    ${pieceStageLine(pc)}
    ${sewOrderRow(pc)}
    <h3>Shape it</h3>
    <div class="row" style="flex-wrap:wrap;gap:6px"><button class="btn small" id="pshape" title="Lay a shape over this piece, then cut it away, join it on or keep the overlap">◐ Cut, join or trim with a shape…</button>${splitJobs(pc).length ? `<button class="btn small" id="psplit" title="Use this piece's outline to split every piece under it, keeping all the parts, sewn back together (a contrast midsection); this piece goes">⫽ Split the pieces under it…</button>` : ""}</div>
    ${joinable.length ? `<div class="row" style="flex-wrap:wrap;gap:4px">${joinable.map(([s, k, mine, theirs]) => `<span class="tag" data-join="${k}" title="Make '${theirs.split(".")[0]}' part of this piece: they're laid flat along this seam, which disappears">⊕ join with ${theirs.split(".")[0]} along ${mine.split(".")[1]}</span>`).join("")}</div>` : ""}
    <h3>On the body</h3>
    <label class="f">Where<select id="pwhere">${LANDMARK_OPTS(pl)}</select></label>
    ${pl.loop ? `<p class="lead" style="font-size:12px;margin:0">Goes round ${pl.loop.join(" + ")}, ${pl.dir === "down" ? "hanging down" : "standing up"} from it.</p>` : ""}
    ${pl.loop && pl.dir === "down" && pc.edges.some(e => e.name === "end_r") ? `<div class="slider"><label>Flare<small>fluffy: its open edge is longer than the seam</small></label><span class="val" id="pflarev">${Math.round((pl.flare || 0) * 100)}%</span><input type="range" id="pflare" min="0" max="150" step="5" value="${Math.round((pl.flare || 0) * 100)}"></div>` : ""}
    ${pl.on ? `<label class="f">Sewn onto<select id="phost">${hosts.map(h => `<option ${h.name === pl.on ? "selected" : ""}>${h.name}</option>`).join("")}</select></label>
      <p class="lead" style="font-size:12px;margin:0">Drag it on the board to move it on '${pl.on}'. Tap <b>sewn</b>/<b>open</b> on each edge below: open edges are the pocket's opening.</p>` : ""}
    ${pl.arm ? `<p class="lead" style="font-size:12px;margin:0">Wrapped round the arm, its crown on top of the shoulder. Reshape it freely: it stays on the arm. Pick a spot above to place it yourself instead.</p>` : ""}
    ${pl.template ? `<p class="lead" style="font-size:12px;margin:0">Hangs where the ${pl.template.block.replace(/_/g, " ")} pattern puts it. Reshape it freely: it stays in place. Pick a spot above to place it yourself instead.</p>` : ""}
    <div class="grid2" style="${free ? "display:none" : ""}">
      <label class="f">Which part goes there<select id="pat">${["center", "top", "bottom", "left", "right"].map(o => `<option value="${o}">${{center: "its middle", top: "its top edge", bottom: "its bottom edge", left: "its left edge", right: "its right edge"}[o]}</option>`).join("")}</select></label>
      <label class="f">How<select id="pmode"><option value="wrap">wrap around the body</option><option value="flat">lie flat</option></select></label>
    </div>
    <label class="f">Layer<select id="player"><option value="0">next to the skin</option><option value="1">over other pieces</option><option value="2">outermost</option></select></label>
    <div class="slider" style="${pl.template ? "display:none" : ""}"><label>Turn it</label><span class="val" id="protv">${pl.rotate}°</span><input type="range" id="prot" min="-180" max="180" step="5" value="${pl.rotate}"></div>
    <div class="slider"><label>Start this far from the skin</label><span class="val" id="poffv">${fmtLen(pl.offset_cm)}</span><input type="range" id="poff" min="0.5" max="8" step="0.5" value="${pl.offset_cm}"></div>
    <div class="row" style="${free ? "display:none" : ""}"><button class="btn small" id="ptube" title="Set the width to go once round the body here, plus ease, and sew its sides">Make it a tube that fits here</button></div>
    <h3>Fabric &amp; layers</h3>
    <div class="grid2">
      <label class="f">Fabric<select id="pfab"><option value="">same as the garment</option>${ST.init.fabrics.map(f => `<option value="${f.key}">${f.name}</option>`).join("")}</select></label>
      <label class="f">Interfacing<select id="pint"><option value="">none</option>${ST.init.interfacings.map(f => `<option value="${f.key}">${f.name}</option>`).join("")}</select></label>
      <label class="f">Lining<select id="plin"><option value="">not lined</option>${["lining", "silk", "poplin", "jersey", "flannel"].map(k => `<option value="${k}">${ST.init.fabrics.find(f => f.key === k).name}</option>`).join("")}</select></label>
    </div>
    <h3>Look <small style="text-transform:none;letter-spacing:0;font-weight:400">(how it shows in 3D)</small></h3>
    <div class="chips" id="plook">${[["", "Same as the garment"], ...PRINTS.map(([k, l]) => [k, k === "none" ? "Solid colour" : l])].map(([k, l]) => `<button class="chip ${(pc.look ? pc.look.print : "") === k ? "on" : ""}" data-look="${k}">${l}</button>`).join("")}</div>
    ${pc.look ? `<div class="grid2"><label class="f">${pc.look.print === "none" ? "Colour" : "Background"}<input type="color" id="plookc" value="${pc.look.color || (pc.look.print === "none" ? "#222222" : "#f3efe6")}"></label>
      ${pc.look.print !== "none" ? `<div class="slider"><label>Repeat size</label><span class="val" id="plookcmv">${fmtLen(pc.look.cm || ST.printCm)}</span><input type="range" id="plookcm" min="1" max="40" step="0.5" value="${pc.look.cm || ST.printCm}"></div>` : ""}</div>` : ""}
    <div class="row" style="flex-wrap:wrap;gap:6px"><button class="btn small" id="playercopy" title="A copy on the layer over this piece: an overlay, like tulle over a skirt">⧉ Copy onto the layer over it…</button></div>
    ${pl.layer_of ? `<p class="lead" style="font-size:12px;margin:0">A copy of <b>${pl.layer_of}</b>, one layer out. It's held to ${pl.layer_of} along the edges marked <b>held</b> below (caught in the same seam): tap to change.</p>` : ""}
    ${pl.on ? `<label class="row" style="gap:6px;font-size:13px"><input type="checkbox" id="pinside" ${pl.inside ? "checked" : ""}> On the inside (facing the body), like a jacket's inner pocket</label>` : ""}
    </div>
    <div class="adv">
    <h3>Pockets &amp; openings</h3>
    <div class="row" style="flex-wrap:wrap;gap:6px">
      <button class="btn small" id="ppocket" title="A pocket sewn onto the outside of this piece">+ Patch pocket</button>
      <button class="btn small" id="pinseam" title="Pocket bags hidden inside one of this piece's seams (skirts, dresses, trousers)">+ Pocket in a seam</button>
      <button class="btn small" id="phip" title="A curved front pocket like jeans and chinos, with a yoke behind the opening">+ Front hip pocket</button>
      <button class="btn small" id="popen" title="Cut this piece down its middle and close it with buttons, a zipper or snaps">Open down the middle…</button>
    </div>
    </div>
    <div id="pform"></div>
    <div class="adv">
    ${pc.lining ? `<p class="lead" style="font-size:12px;margin:0">The lining is joined to every edge except the ones marked <b>lining open</b> below (usually the hem).</p>` : ""}
    <h3>Edges</h3>
    <p class="lead" style="font-size:12px;margin:0 0 4px">Darts, pleats, hems, elastic: pick a tool under <b>Edges</b> at the top, then click the edge.</p>
    ${pc.edges.map((e, i) => { const sid = seamIndexOf(pc.name, e.name);
      return `<div class="edgerow"><i style="background:${sid == null ? "var(--line)" : seamColor(sid)}"></i><span>${e.name} <small style="color:var(--muted)">${fmtLen(plen(edgePts(pc, i)))}</small></span>
        <span class="row" style="gap:4px">${pl.layer_of ? `<span class="tag ${(pl.held || []).includes(e.name) ? "on" : ""}" data-held="${i}" title="Held to '${pl.layer_of}' along this edge">held</span>` : ""}${pl.on ? `<span class="tag ${(pl.sewn || []).includes(e.name) ? "on" : ""}" data-sewn="${i}" title="Topstitched onto '${pl.on}' (or left open)">${(pl.sewn || []).includes(e.name) ? "sewn" : "open"}</span>` : ""}${pc.lining ? `<span class="tag ${(pc.lining.open || []).includes(e.name) ? "on" : ""}" data-lopen="${i}" title="Leave the lining loose along this edge">lining open</span>` : ""}${e.elastic ? `<span class="tag on" data-el="${i}" title="Gathered with elastic: click to take it off">elastic ✕</span>` : ""}${e.sa != null && !e.hem ? `<span class="tag on" data-sa="${i}" title="This edge's own seam allowance: click to change it">SA ${toUnit(e.sa).toFixed(ST.units === "in" ? 2 : 1)}</span>` : ""}${e.hem ? `<span class="tag on" data-hem="${i}" title="Hemmed: click to change or remove the hem">hem ${fmtLen(e.hem.depth_cm)}</span>` : ""}</span></div>
        <div class="dartform" id="df${i}" style="display:none"></div>` }).join("")}
    </div>
  </div>`;
  $("#pfab").value = pc.fabric || ""; $("#pint").value = pc.interfacing || ""; $("#plin").value = pc.lining ? pc.lining.fabric : "";
  $("#pfab").onchange = e => { pc.fabric = e.target.value || undefined; for (const img of symImages(pc)) if (img.P !== pc) img.P.fabric = pc.fabric; dsChanged(true) };
  const setLook = f => {          // the look on this piece and its mirror images (Symmetric)
    f(pc); for (const img of symImages(pc)) if (img.P !== pc) { img.P.look = pc.look ? JSON.parse(JSON.stringify(pc.look)) : undefined; if (!pc.look) delete img.P.look }
    dsChanged(true); renderInspector(); if (ST.drape && typeof applyPrint === "function") applyPrint();
  };
  $$("#plook [data-look]").forEach(b => b.onclick = () => {
    const k = b.dataset.look;
    if (k === "upload") {
      const inp = document.createElement("input"); inp.type = "file"; inp.accept = "image/*";
      inp.onchange = () => { const f = inp.files[0]; if (!f) return; const im = new Image(); im.onload = () => {
        const c = document.createElement("canvas"); c.width = c.height = 256; c.getContext("2d").drawImage(im, 0, 0, 256, 256);
        setLook(p => p.look = {...(p.look || {}), print: "upload", src: c.toDataURL("image/jpeg", 0.85)}) }; im.src = URL.createObjectURL(f) };
      inp.click(); return;
    }
    setLook(p => { if (!k) delete p.look; else { p.look = {...(p.look || {}), print: k}; delete p.look.src } });
  });
  if ($("#plookc")) $("#plookc").oninput = e => setLook(p => p.look.color = e.target.value);
  if ($("#plookcm")) $("#plookcm").oninput = e => { $("#plookcmv").textContent = fmtLen(+e.target.value); setLook(p => p.look.cm = +e.target.value) };
  if ($("#pflare")) $("#pflare").oninput = e => { const f = +e.target.value / 100; $("#pflarev").textContent = Math.round(f * 100) + "%";
    flareBand(pc, f); for (const img of symImages(pc)) if (img.P !== pc) flareBand(img.P, f); drawDesign(); dsSoon() };
  $("#pint").onchange = e => { pc.interfacing = e.target.value || undefined; dsChanged(true) };
  $("#plin").onchange = e => {
    const v = e.target.value;
    if (!v) delete pc.lining;
    else pc.lining = {fabric: v, open: pc.lining ? pc.lining.open : pc.edges.filter(x => seamIndexOf(pc.name, x.name) == null && /hem|bottom/.test(x.name)).map(x => x.name)};
    dsChanged(true);
  };
  // sewing order and role: take effect at the next drape
  $$("#inspector [data-pstage]").forEach(t => t.onclick = () => { const v = t.dataset.pstage; if (v === "auto") delete pc.stage; else pc.stage = +v; dsChanged(true) });
  $("#prole").onchange = e => { if (e.target.value) pc.role = e.target.value; else delete pc.role; dsChanged(true) };
  $("#ppocket").onclick = () => addPocket(pc);
  $("#pshape").onclick = () => startShape(pc);
  if ($("#psplit")) $("#psplit").onclick = () => splitForm(pc);
  $$("#inspector [data-join]").forEach(t => t.onclick = () => {
    const [, , mine, theirs] = joinable.find(j => j[1] === +t.dataset.join), pairs = [[mine, theirs]];
    if (DS.sym) {   // the mirror-image pair too (front_r + yoke_r, then front_l + yoke_l)
      const key = r => sideKey(r.split(".")[0]) + "." + r.split(".")[1];
      for (const s of D().seams) {
        const m = key(s.a) === key(mine) && key(s.b) === key(theirs) ? [s.a, s.b] : key(s.b) === key(mine) && key(s.a) === key(theirs) ? [s.b, s.a] : null;
        if (m && m[0] !== mine) { pairs.push(m); break }
      }
    }
    serverEdit("join_seam", {seams: pairs});
  });
  $("#playercopy").onclick = () => {
    const grp = layerGroup(pc), one = [pc.name, ...(DS.sym ? symImages(pc).filter(i => i.P !== pc).map(i => i.P.name) : [])];
    form(`<b style="font-size:13px">Copy onto the layer over it</b>
      <p class="lead" style="font-size:12px;margin:4px 0">For an overlay: tulle over a skirt, a sheer layer over a bodice. The copy hangs just outside the original. Where the original is sewn to other pieces (a waistband) or gathered with elastic, the copy is held to it, caught in the same seam.</p>
      <label class="row" style="gap:6px;font-size:13px"><input type="radio" name="lcwho" value="one" checked> ${one.join(" + ")}</label>
      ${grp.length > one.length ? `<label class="row" style="gap:6px;font-size:13px"><input type="radio" name="lcwho" value="all"> ${grp.join(" + ")} (everything sewn to it)</label>` : ""}
      <label class="f">Fabric of the copy<select id="lcfab"><option value="">same as the original</option>${ST.init.fabrics.map(f => `<option value="${f.key}">${f.name}</option>`).join("")}</select></label>
      <div class="row" style="margin-top:6px"><button class="btn small primary" id="lcok">Make the copy</button></div>`);
    $("#lcok").onclick = () => serverEdit("layer_copy", {pieces: ($("[name=lcwho]:checked") || {}).value === "all" ? grp : one, fabric: $("#lcfab").value || undefined});
  };
  $$("#inspector [data-held]").forEach(t => t.onclick = () => { const n = pc.edges[+t.dataset.held].name, h = pl.held || []; pl.held = h.includes(n) ? h.filter(x => x !== n) : [...h, n]; dsChanged(true) });
  if ($("#pinside")) $("#pinside").onchange = e => { if (e.target.checked) pl.inside = true; else delete pl.inside; dsChanged(true) };
  const sewnEdges = pc.edges.filter(e => seamIndexOf(pc.name, e.name) != null && !/^(join|end|top|cap|cf|neck|shoulder)/.test(e.name));
  const form = html => { $("#pform").innerHTML = `<div class="ins" style="margin-top:8px">${html}</div>` };
  $("#pinseam").onclick = () => {
    if (!sewnEdges.length) { toast("Sew this piece to another one first: the pocket goes in that seam"); return }
    const guess = sewnEdges.find(e => /side|outseam/.test(e.name)) || sewnEdges[0];
    form(`<b style="font-size:13px">Pocket hidden in a seam</b><div class="grid2">
      <label class="f">Which seam<select id="isref">${sewnEdges.map(e => `<option ${e === guess ? "selected" : ""}>${e.name}</option>`).join("")}</select></label>
      <label class="f">Opening starts below the waist (${ST.units})<input type="text" id="istop" value="${toUnit(3).toFixed(1)}"></label>
      <label class="f">Opening (${ST.units})<input type="text" id="islen" value="${toUnit(16).toFixed(1)}"></label>
      <label class="f">Bag depth below it (${ST.units})<input type="text" id="isdep" value="${toUnit(12).toFixed(1)}"></label></div>
      <small style="color:var(--muted)">Any seam, straight, slanted or curved. The seam is left open over the opening; a bag on each side is sewn to it and to the other, and hangs straight down inside this piece. Do both sides for a pair.</small>
      <small class="pvmsg" id="pvmsg">Working out the preview…</small>
      <div class="row" style="margin-top:6px"><button class="btn small primary" id="isok">Add the pocket</button><button class="btn small" id="iscancel">Cancel</button></div>`);
    const args = () => ({ref: `${pc.name}.${$("#isref").value}`, below_waist_cm: fromUnit(parseFloat($("#istop").value)),
      opening_cm: fromUnit(parseFloat($("#islen").value)), depth_cm: fromUnit(parseFloat($("#isdep").value))});
    livePreview("inseam_pocket", args, ["#isref", "#istop", "#islen", "#isdep"]);
    $("#isok").onclick = () => { clearPreview(); serverEdit("inseam_pocket", args()) };
    $("#iscancel").onclick = () => { clearPreview(); $("#pform").innerHTML = "" };
  };
  $("#phip").onclick = () => {
    const names = pc.edges.map(e => e.name), w = names.find(n => /waist/.test(n)) || names[0], sd = names.find(n => /outseam|side/.test(n)) || names[1];
    form(`<b style="font-size:13px">Front hip pocket</b><div class="grid2">
      <label class="f">Waist edge<select id="hpw">${names.map(n => `<option ${n === w ? "selected" : ""}>${n}</option>`).join("")}</select></label>
      <label class="f">Side seam edge<select id="hps">${names.map(n => `<option ${n === sd ? "selected" : ""}>${n}</option>`).join("")}</select></label>
      <label class="f">Along the waist (${ST.units})<input type="text" id="hpa" value="${toUnit(10).toFixed(1)}"></label>
      <label class="f">Down the side (${ST.units})<input type="text" id="hpd" value="${toUnit(16).toFixed(1)}"></label></div>
      <small style="color:var(--muted)">Cuts a curved opening from the corner where the two edges meet. A pocket yoke behind it shows through the opening and goes into the side seam. Add it before the waistband.</small>
      <small class="pvmsg" id="pvmsg">Working out the preview…</small>
      <div class="row" style="margin-top:6px"><button class="btn small primary" id="hpok">Add the pocket</button><button class="btn small" id="hpcancel">Cancel</button></div>`);
    const args = () => ({piece: pc.name, waist: $("#hpw").value, side: $("#hps").value,
      across_cm: fromUnit(parseFloat($("#hpa").value)), down_cm: fromUnit(parseFloat($("#hpd").value))});
    livePreview("hip_pocket", args, ["#hpw", "#hps", "#hpa", "#hpd"]);
    $("#hpok").onclick = () => { clearPreview(); serverEdit("hip_pocket", args()) };
    $("#hpcancel").onclick = () => { clearPreview(); $("#pform").innerHTML = "" };
  };
  $("#popen").onclick = () => {
    form(`<b style="font-size:13px">Open '${pc.name}' down the middle</b>
      <p class="lead" style="font-size:12px;margin:4px 0">Cuts it along its centre line into a right and a left half, joined by the closure you pick. The cut pieces get a button stand and facing automatically.</p>
      <div class="row" style="flex-wrap:wrap;gap:6px">${Object.entries(ST.init.closures).map(([k, l]) => `<button class="chip" data-ok="${k}">${l}</button>`).join("")}</div>
      <label class="row" style="gap:6px;font-size:12px;margin-top:6px">Buttonholes on the wearer's <select id="pholes"><option value="right">right (women's)</option><option value="left">left (men's)</option></select></label>`);
    $("#pholes").value = ST.meas && ST.meas.sex === "male" ? "left" : "right";
    $$("#pform [data-ok]").forEach(b => b.onclick = () => serverEdit("open_middle", {piece: pc.name, kind: b.dataset.ok, holes: $("#pholes").value}));
  };
  if ($("#phost")) $("#phost").onchange = e => { pl.on = e.target.value; dsChanged(true, true) };
  $$("#inspector [data-sewn]").forEach(t => t.onclick = () => { const n = pc.edges[+t.dataset.sewn].name; pl.sewn = (pl.sewn || []).includes(n) ? pl.sewn.filter(x => x !== n) : [...(pl.sewn || []), n]; dsChanged(true) });
  $$("#inspector [data-lopen]").forEach(t => t.onclick = () => { const n = pc.edges[+t.dataset.lopen].name, o = pc.lining.open || []; pc.lining.open = o.includes(n) ? o.filter(x => x !== n) : [...o, n]; dsChanged(true) });
  $("#pwhere").value = where; $("#pat").value = pl.at || "center"; $("#pmode").value = pl.mode || "wrap"; $("#player").value = String(pl.layer || 0);
  $("#player").onchange = e => { pl.layer = +e.target.value; dsChanged(true) };
  $("#pname").onchange = e => renamePiece(pc, e.target.value);
  $$("#inspector [data-dim]").forEach(inp => inp.onchange = () => { const v = parseFloat(inp.value); if (!(v > 0)) return; pc.shape[inp.dataset.dim] = fromUnit(v); reshape(pc); dsChanged(true) });
  $$("#inspector [data-scale]").forEach(inp => inp.onchange = () => { const v = fromUnit(parseFloat(inp.value)), ax = +inp.dataset.scale, bb = bboxV(pc), cur = bb[ax + 2] - bb[ax]; if (!(v > 0) || !cur) return; scalePiece(pc, ax, v / cur); dsChanged(true) });
  $("#pwhere").onchange = e => { const v = e.target.value; if (v === "__template" || v === "__loop" || v === "__arm") return;
    if (pl.arm) { delete pl.arm; delete pl.top_cm; delete pl.wrist }
    if (pl.loop) { delete pl.loop; delete pl.dir }
    if (v === "__on") {
      if (!hosts.length) { toast("Add the piece it sews onto first"); renderInspector(); return }
      sewOnto(pc, hosts[0]); return;
    }
    if (pl.on) { delete pl.on; delete pl.pos; delete pl.sewn; const b = bboxV(pc); pc.at = [0, 0]; tidy() }
    if (pl.template) { DS.tplBackup = {...DS.tplBackup, [pc.name]: pl.template}; delete pl.template; if (pl.mode === "template") pl.mode = "wrap"; pl.offset_cm = 1.5 }
    if (v === "__tap") { startPlacing(); return } delete pl.anchor; if (v) pl.landmark = v; else delete pl.landmark; dsChanged(true) };
  $("#pat").onchange = e => { pl.at = e.target.value; dsChanged(true) };
  $("#pmode").onchange = e => { pl.mode = e.target.value; dsChanged(true) };
  $("#prot").oninput = e => { pl.rotate = +e.target.value; $("#protv").textContent = pl.rotate + "°"; dsSoon() };
  $("#poff").oninput = e => { pl.offset_cm = +e.target.value; $("#poffv").textContent = fmtLen(pl.offset_cm); dsSoon() };
  $("#pdup").onclick = () => { const c = JSON.parse(JSON.stringify(pc)); c.name = uniqueName(pc.name, D().pieces.map(p => p.name)); c.at = [pc.at[0] + 8, pc.at[1] - 8]; D().pieces.push(c); DS.sel = c.name; dsChanged(true) };
  $("#pmir").onclick = () => mirrorCopy(pc);
  $("#pdel").onclick = () => {
    const riders = D().pieces.filter(p => p.place && p.place.on === pc.name);
    if (riders.length && !confirm(`Also delete ${riders.map(r => r.name).join(", ")} (sewn onto it)?`)) return;
    D().pieces.forEach(p => { if (p.place && p.place.layer_of === pc.name) { delete p.place.layer_of; delete p.place.held } });
    D().pieces = D().pieces.filter(p => p !== pc && !riders.includes(p)); D().seams = D().seams.filter(s => !s.a.startsWith(pc.name + ".") && !s.b.startsWith(pc.name + ".")); DS.sel = null; dsChanged(true) };
  $("#ptube").onclick = () => makeTube(pc);
  $$("#inspector [data-el]").forEach(t => t.onclick = () => { const e = pc.edges[+t.dataset.el]; e.elastic = !e.elastic; dsChanged(true) });
  $$("#inspector [data-sa]").forEach(t => t.onclick = () => { const e = pc.edges[+t.dataset.sa];
    const v = prompt(`Seam allowance on '${e.name}' (${ST.units}). Leave empty for the default (${toUnit(ST.sa).toFixed(2)}).`, e.sa != null ? toUnit(e.sa).toFixed(2) : "");
    if (v === null) return; if (v.trim() === "") delete e.sa; else e.sa = Math.min(10, Math.max(0, fromUnit(parseFloat(v)) || 0)); dsChanged(true) });
  const hemForm = i => {
    const f = $("#df" + i), e = pc.edges[i], H = ST.init.hem_styles, u = ST.units;
    let style = e.hem ? e.hem.style : "double";
    const draw = () => {
      const st = H[style], mine = e.hem && e.hem.style === style;
      const dep = mine ? e.hem.depth_cm : st.depth, turn = mine ? e.hem.turn_cm : st.turn;
      f.style.display = "block"; f.className = "ins";
      f.innerHTML = `<b style="font-size:13px">Hem ${e.name}</b>
        <div class="chips">${Object.entries(H).map(([k, x]) => `<button class="chip ${k === style ? "on" : ""}" data-hs="${k}">${x.label}</button>`).join("")}</div>
        <div class="grid2"><label class="f">Finished depth (${u})<input type="text" inputmode="decimal" id="hdep" value="${toUnit(dep).toFixed(u === "in" ? 2 : 1)}"></label>
        <label class="f">Turned under first (${u})<input type="text" inputmode="decimal" id="hturn" value="${toUnit(turn).toFixed(u === "in" ? 2 : 1)}"></label></div>
        <small style="color:var(--muted)">${st.how} The ${fmtLen(dep + turn)} turn-up is cut on beyond the edge, its corners shaped to match the seams when it's folded up.</small>
        <div class="row" style="margin-top:6px"><button class="btn small primary" id="hok">${e.hem ? "Update hem" : "Hem it"}</button>${e.hem ? `<button class="btn small" id="hdel">Remove hem</button>` : ""}</div>`;
      $$(`#df${i} [data-hs]`).forEach(b => b.onclick = () => { style = b.dataset.hs; draw() });
      $("#hok").onclick = () => setHem(pc, i, {style, depth_cm: fromUnit(parseFloat($("#hdep").value)), turn_cm: fromUnit(parseFloat($("#hturn").value)) || 0});
      if ($("#hdel")) $("#hdel").onclick = () => setHem(pc, i, null);
    };
    draw();
  };
  $$("#inspector [data-hem]").forEach(t => t.onclick = () => hemForm(+t.dataset.hem));
}
function insertDart(pc, i, t, w, depth, kind, quiet = false) {
  // replace edge i by: start part, leg a (to the tip), leg b (back), end part; sew a<->b. quiet: the caller
  // redraws once (a dart and its mirror image). Returns whether it was added.
  if (!(w > 0 && depth > 0)) return false;
  const e = pc.edges[i], pts = edgePts(pc, i, 80), f = arcFrac(pts), L = plen(pts);
  let t1 = t - w / 2 / L, t2 = t + w / 2 / L;
  if (t1 < .02 || t2 > .98) { toast("Too close to the end of the edge: click nearer its middle, or make it narrower"); return false }
  const P1 = pointAtFrac(pts, f, t1), P2 = pointAtFrac(pts, f, t2);
  const k1 = f.findIndex(v => v >= t1), k2 = f.findIndex(v => v > t2);
  const a = pointAtFrac(pts, f, Math.max(0, t - .02)), b = pointAtFrac(pts, f, Math.min(1, t + .02));
  let nx = -(b[1] - a[1]), ny = b[0] - a[0]; const nl = Math.hypot(nx, ny) || 1; nx /= nl; ny /= nl;   // into the piece
  const M = pointAtFrac(pts, f, t);
  const tip = [M[0] + nx * depth, M[1] + ny * depth];
  const left = [...pts.slice(0, k1), P1], right = [P2, ...pts.slice(k2)];
  const legA = [P1, tip], legB = [tip, P2];
  custom(pc);
  const taken = pc.edges.map(x => x.name), base = e.name;
  const nA = uniqueName(`${base}_${kind}_a`, taken), nB = uniqueName(`${base}_${kind}_b`, taken);
  const n1 = uniqueName(base + "_1", taken), n2 = uniqueName(base + "_2", taken);
  const mk = (name, pp) => pp.length > 2 ? {name, c1: null, c2: null, pts: pp, elastic: e.elastic} : {name, c1: null, c2: null, elastic: e.elastic};
  pc.verts.splice(i + 1, 0, P1, legA[1], legB[1]);
  pc.edges.splice(i, 1, mk(n1, left), mk(nA, legA), mk(nB, legB), mk(n2, right));
  const k = pc.name + "." + e.name;
  edgeSplitRefs(pc, e.name, [n1, n2]);
  if (D().seams.some(s => s.a === k || s.b === k)) { D().seams = D().seams.filter(s => s.a !== k && s.b !== k); toast(`${k} was sewn: sew ${n1} and ${n2} again`, 4500) }
  D().seams.push({a: `${pc.name}.${nA}`, b: `${pc.name}.${nB}`, ease: 0, reverse: true});
  if (quiet) return true;
  dsChanged(true); if (kind === "dart") toast(`Dart added: ${pc.name}.${nA} is sewn to ${nB}`);
  return true;
}
function gatherEdge(pc, i, more = 0.5, quiet = false) {   // lengthen an edge (spread from the far corner) and gather it into its seam
  const e = pc.edges[i], k = seamIndexOf(pc.name, e.name);
  if (k == null) { toast("Sew this edge to something first: the gathers are what makes it fit"); return false }
  const L = plen(edgePts(pc, i)); extendEdge(pc, i, L * (1 + more));
  const s = D().seams[k]; s.ease = +more.toFixed(4);
  if (!quiet) { toast(`Edge made ${Math.round(more * 100)}% longer and gathered into its seam (change it in Seams)`, 4500); dsChanged(true) }
  return true;
}

// ------------------------------------------------- split with a shape (2026-11-25): a piece as the cutter
function boardBox(pc) { let a = [1e9, 1e9, -1e9, -1e9]; pc.edges.forEach((e, i) => edgePts(pc, i).forEach(q => { const [x, y] = boardXY(pc, q); a = [Math.min(a[0], x), Math.min(a[1], y), Math.max(a[2], x), Math.max(a[3], y)] })); return a }
function splitJobs(S) {   // the pieces under piece S on the board, each with S's outline in its own coords
  if (!S || onHost(S)) return [];
  const sb = boardBox(S), jobs = [];
  for (const P of D().pieces) {
    if (P === S || onHost(P) || (P.place && P.place.loop)) continue;
    const pb = boardBox(P);
    if (pb[0] >= sb[2] || pb[2] <= sb[0] || pb[1] >= sb[3] || pb[3] <= sb[1]) continue;
    jobs.push({piece: P.name, tools: [S.edges.map((e, i) => ({name: e.name, pts: edgePts(S, i).map(q => boardInv(P, boardXY(S, q)).map(v => +v.toFixed(3)))}))]});
  }
  return jobs;
}
function splitForm(S) {
  const jobs = splitJobs(S), f = $("#pform"); if (!jobs.length) { toast("Drag this piece over the pieces to split first"); return }
  f.className = "ins"; f.style.display = "block";
  f.innerHTML = `<b style="font-size:13px">Split ${jobs.map(j => j.piece).join(", ")} with '${S.name}'</b>
    <p class="lead" style="font-size:12px;margin:2px 0 6px">Every piece under it is cut along its outline and sewn back together: all the parts are kept,
      seams it crosses are sewn part to part, and '${S.name}' goes. The parts inside it can be another fabric.</p>
    <label class="f">Inside it<select id="spfab"><option value="">the same fabric</option>${ST.init.fabrics.map(x => `<option value="${x.key}">${x.name}</option>`).join("")}</select></label>
    <div class="row" style="margin-top:8px;gap:6px"><button class="btn small primary" id="spok">⫽ Split</button><button class="btn small" id="spno">Cancel</button></div>`;
  $("#spno").onclick = () => { f.innerHTML = ""; f.style.display = "none" };
  $("#spok").onclick = async () => {
    const fabric = $("#spfab").value || undefined;
    if (await serverEdit("split", {jobs, remove: S.name, fabric})) { f.innerHTML = ""; f.style.display = "none" }
  };
  f.scrollIntoView({behavior: "smooth", block: "nearest"});
}

// ------------------------------------------------- edge tools (2026-11-25): pick one, click the spot on an edge
// at: the tool works at the spot clicked (a dart there), else on the whole edge. Options in cm, shown in the
// user's units; pct and the hem's style as they are.
const EDGE_TOOLS = {
  dart: {label: "Dart", at: true, help: "A wedge sewn closed to shape the fabric (bust, waist, seat). The edge gets shorter by its width.",
    opts: [["w", "Width at the edge", 3], ["d", "Length to the point", 10]]},
  pleat: {label: "Pleat", at: true, help: "Extra fabric folded and stitched down at the edge (a tuck). The edge gets shorter by the fold.",
    opts: [["w", "Fabric folded in", 5], ["d", "Stitched down", 3]]},
  gathers: {label: "Gathers", help: "Makes a sewn edge longer than the edge it joins, and gathers it in.", opts: [["pct", "Longer by (%)", 50, "%"]]},
  hem: {label: "Hem", help: "The turn-up is cut on beyond an edge that isn't sewn to anything. Click a hemmed edge to take the hem off."},
  elastic: {label: "Elastic", help: "Gathers the edge with elastic to fit the body. Click it again to take the elastic off."},
  sa: {label: "Seam allow.", help: "This edge's own seam allowance (a deeper hem, a narrow neckline). Empty: the default.", opts: [["sa", "Seam allowance", null]]},
  split: {label: "Split", at: true, help: "Splits the edge in two where you click (a new corner to drag)."},
  sleeve: {label: "Sleeve", pair: true, help: "A set-in sleeve drafted to fit the armhole: its cap as long as the armhole plus a little ease, its width from the upper arm."},
};
const SLEEVE_OPTS = {length: [["short", "Short"], ["elbow", "Elbow"], ["three_quarter", "¾"], ["long", "Long"]],
  fit: [["fitted", "Fitted"], ["regular", "Regular"], ["loose", "Loose"]], cap: [["smooth", "Smooth cap"], ["puff", "Puff"]]};
DS.edgeTool = null; DS.edgeHover = null;
DS.edgeOpts = Object.fromEntries(Object.entries(EDGE_TOOLS).map(([k, T]) => [k, Object.fromEntries((T.opts || []).map(([o, , v]) => [o, v]))]));
DS.edgeOpts.hem = {style: "double"};
DS.edgeOpts.sleeve = {length: "short", fit: "regular", cap: "smooth"};
function renderEdgeTools() {
  $("#edgetools").innerHTML = Object.entries(EDGE_TOOLS).map(([k, T]) => `<button class="tb" data-et="${k}" title="${T.label}: ${T.help}">${tbInner(k, T.label)}</button>`).join("");
  $$("#edgetools .tb").forEach(b => b.onclick = () => {
    if (DS.tool === "edge" && DS.edgeTool === b.dataset.et) { toolExit(); return }       // clicked again: off
    DS.tool = "edge"; DS.edgeTool = b.dataset.et; DS.sewA = null; DS.loop = []; DS.edgeHover = null;
    $$("#tool button").forEach(x => x.classList.remove("on")); toolHint(); drawDesign();
  });
}
renderEdgeTools();
function edgeTargets(pc, i, t) {   // the edge clicked and, with Symmetric on, its mirror images: [piece, edge, t along it]
  const out = [[pc, i, t]];
  for (const img of symImages(pc)) {
    const [k, rev] = symEdge(img, pc, i), tt = rev ? 1 - t : t;
    if (k < 0) continue;
    if (img.P === pc && k === i) { if (EDGE_TOOLS[DS.edgeTool]?.at && Math.abs(tt - t) > .05) out.push([pc, i, tt]); continue }   // across the centre line: its twin on the same edge
    out.push([img.P, k, tt]);
  }
  return out;
}
function hemDefaults(style) { const H = ST.init.hem_styles[style] || {}; return {style, depth: H.depth, turn: H.turn} }
function applyEdgeTool(pc, i, t) {
  const k = DS.edgeTool, O = DS.edgeOpts[k] || {}, e = pc.edges[i], tg = edgeTargets(pc, i, t), both = tg.length > 1 ? " (and its mirror image)" : "";
  if (k === "split") { splitEdge(pc, i, Math.min(.95, Math.max(.05, t))); return }
  if (k === "sleeve") {            // two clicks: the front armhole edge, then the back one
    const ref = pc.name + "." + e.name;
    if (!DS.sewA) { DS.sewA = ref; DS.sleeveA = [pc, i]; toolHint(); drawDesign(); return }
    if (DS.sewA === ref) { DS.sewA = null; toolHint(); drawDesign(); return }
    const [fp, fi] = DS.sleeveA, sides = [{front: DS.sewA, back: ref}];
    const fT = edgeTargets(fp, fi, .5), bT = edgeTargets(pc, i, .5);       // Symmetric: the other arm's armhole too
    for (let q = 1; q < Math.min(fT.length, bT.length); q++) {
      const f2 = fT[q][0].name + "." + fT[q][0].edges[fT[q][1]].name, b2 = bT[q][0].name + "." + bT[q][0].edges[bT[q][1]].name;
      if (f2 !== sides[0].front && b2 !== sides[0].back) sides.push({front: f2, back: b2});
    }
    DS.sewA = null; DS.sleeveA = null;
    serverEdit("sleeve", {sides, ...O, avatar: ST.avatar && ST.avatar.id}).then(() => { toolHint(); drawDesign() });
    return;
  }
  if (k === "hem") {
    if (!e.hem && seamIndexOf(pc.name, e.name) != null) { toast("A hem goes on an edge that isn't sewn to anything", 4000); return }
    const H = O.depth == null ? hemDefaults(O.style) : O;
    setHem(pc, i, e.hem ? null : {style: H.style, depth_cm: H.depth, turn_cm: H.turn}); return;
  }
  if (k === "elastic") { const on = !e.elastic; tg.forEach(([P, j]) => P.edges[j].elastic = on); dsChanged(true); toast(on ? `Elastic on ${e.name}${both}` : `Elastic taken off ${e.name}${both}`); return }
  if (k === "sa") {
    tg.forEach(([P, j]) => { if (O.sa == null) delete P.edges[j].sa; else P.edges[j].sa = O.sa }); dsChanged(true);
    toast(O.sa == null ? `${e.name}: the default seam allowance${both}` : `${e.name}: ${fmtLen(O.sa)} seam allowance${both}`); return;
  }
  if (k === "gathers") {
    if (!(O.pct > 0)) { toast("Longer by: a number above 0 (%)"); return }
    let n = 0; for (const [P, j] of tg) n += gatherEdge(P, j, O.pct / 100, true) ? 1 : 0;
    if (n) { dsChanged(true); toast(`${e.name} made ${O.pct}% longer and gathered into its seam${both}`, 4500) } return;
  }
  if (k === "dart" || k === "pleat") {
    if (!(O.w > 0 && O.d > 0)) { toast(`${k === "dart" ? "Width and length" : "Fold and stitched length"}: numbers above 0`); return }
    // on one piece the later edge first, and on one edge the later spot first: inserting moves what comes after it
    const L = plen(edgePts(pc, i)), order = [...tg].sort((a, b) => a[0] !== b[0] ? (a[0].name < b[0].name ? -1 : 1) : b[1] - a[1] || b[2] - a[2]);
    let n = 0, prev = null;
    for (const [P, j, tt] of order) {
      let u = Math.min(.9, Math.max(.1, tt));
      if (prev && prev[0] === P && prev[1] === j) u = u / (prev[2] - O.w / 2 / L);    // the first part of the edge the last one split
      if (insertDart(P, j, u, O.w, O.d, k, true)) { n++; prev = [P, j, Math.min(.9, Math.max(.1, tt))] }
    }
    if (n) { dsChanged(true); toast(`${EDGE_TOOLS[k].label} added on ${e.name}${n > 1 ? ` and its mirror image` : ""}`) }
  }
}
// a band hanging from its opening (a cuff, a hem band) reshaped to flare: its open edge (1 + f) times the seam's
// length. Laid flat that's part of a ring (a cone opened out): the seam on the inner circle, radius r = height / f.
function flareBand(pc, f) {
  const er = pc.edges.findIndex(e => e.name === "end_r"); if (er < 0) return;
  const old = Object.fromEntries(pc.edges.map(e => [e.name, e]));
  const joins = pc.edges.map((e, i) => [e, i]).filter(([e]) => e.name.startsWith("join_"));
  const lens = joins.map(([e, i]) => pc.place.flare ? e._len || plen(edgePts(pc, i)) : plen(edgePts(pc, i)));
  const h = pc.place.flare_h || plen(edgePts(pc, er)), L = lens.reduce((a, b) => a + b, 0);
  f = Math.max(0, Math.min(f, 1.9 * Math.PI * h / L));        // one piece: no more than 95% of a full circle
  const r = f > 1e-3 ? h / f : 0, P = (s, v) => r ? [(r + v) * Math.sin(s / r), (r + v) * Math.cos(s / r) - r] : [s, v];
  const arc = (s0, s1, v) => Array.from({length: 25}, (_, k) => P(s0 + (s1 - s0) * k / 24, v)).map(q => q.map(z => +z.toFixed(3)));
  const keep = (nm, extra) => ({...(old[nm] || {name: nm, elastic: false}), c1: null, c2: null, ...extra});
  const verts = [], edges = []; let x = -L / 2;
  lens.forEach((l, k) => { verts.push(P(x, 0)); edges.push(keep(`join_${k + 1}`, r ? {pts: arc(x, x + l, 0), _len: l} : {pts: undefined, _len: l})); x += l });
  verts.push(P(L / 2, 0)); edges.push(keep("end_r", {pts: undefined}));
  verts.push(P(L / 2, h)); edges.push(keep("top", r ? {pts: arc(L / 2, -L / 2, h)} : {pts: undefined}));
  verts.push(P(-L / 2, h)); edges.push(keep("end_l", {pts: undefined}));
  edges.forEach(e => { if (!e.pts) delete e.pts });
  pc.verts = verts.map(q => q.map(z => +z.toFixed(3))); pc.edges = edges; custom(pc);
  if (r) { pc.place.flare = +f.toFixed(3); pc.place.flare_r = +r.toFixed(3); pc.place.flare_h = +h.toFixed(3) }
  else { delete pc.place.flare; delete pc.place.flare_r; delete pc.place.flare_h }
}
function sewOnto(pc, host) {   // centre the piece on its host, topstitch all but the top edge
  const pl = pc.place; delete pl.landmark; delete pl.anchor; delete pl.template; delete pl.arm;
  pl.on = host.name; pl.rotate = 0;
  const hb = bboxV(host), b = bboxV(pc);
  pl.pos = [(hb[0] + hb[2]) / 2 - (b[0] + b[2]) / 2, (hb[1] + hb[3]) / 2 - (b[1] + b[3]) / 2];
  const top = pc.edges.reduce((best, e, i) => { const m = edgePts(pc, i).reduce((s, q) => s + q[1], 0) / edgePts(pc, i).length; return m > best[1] ? [e.name, m] : best }, ["", -1e9])[0];
  pl.sewn = pc.edges.map(e => e.name).filter(n => n !== top);
  D().seams = D().seams.filter(s => !s.a.startsWith(pc.name + ".") && !s.b.startsWith(pc.name + "."));
  dsChanged(true, true); toast(`'${pc.name}' is sewn onto '${host.name}': drag it where you want it`);
}
function addPocket(host) {
  const pc = makePiece("rect", {w: 16, h: 18}, uniqueName("pocket", D().pieces.map(p => p.name)));
  D().pieces.push(pc); DS.sel = pc.name; sewOnto(pc, host);
}
function setHem(pc, i, hem) {   // on this edge, and its mirror image when Symmetric is on
  if (hem && !(hem.depth_cm > 0)) { toast("Give the hem a depth"); return }
  if (hem && hem.turn_cm < 0) hem.turn_cm = 0;
  const targets = [[pc, i], ...symImages(pc).map(img => [img.P, symEdge(img, pc, i)[0]]).filter(([P, k]) => k >= 0 && !(P === pc && k === i))];
  for (const [P, k] of targets) { if (hem) P.edges[k].hem = {...hem}; else delete P.edges[k].hem }
  dsChanged(true);
  toast(hem ? `Hemmed: a ${fmtLen(hem.depth_cm + hem.turn_cm)} turn-up is cut on beyond the edge${targets.length > 1 ? " (both sides)" : ""}` : "Hem removed", 4000);
}
function layerGroup(pc) {   // the piece and every piece sewn to it, through seams (not bands or pockets: the copy is held to those)
  const out = [pc.name], skip = p => !p || (p.place && (p.place.loop || p.place.on));
  for (let i = 0; i < out.length; i++) for (const s of D().seams) {
    const a = s.a.split(".")[0], b = s.b.split(".")[0];
    for (const [x, y] of [[a, b], [b, a]]) if (x === out[i] && !out.includes(y) && !skip(pieceBy(y))) out.push(y);
  }
  return out;
}
function bboxV(pc) { let a = [1e9, 1e9, -1e9, -1e9]; pc.edges.forEach((e, i) => edgePts(pc, i).forEach(([x, y]) => { a[0] = Math.min(a[0], x); a[1] = Math.min(a[1], y); a[2] = Math.max(a[2], x); a[3] = Math.max(a[3], y) })); return a }
function seamIndexOf(pn, en) { const k = pn + "." + en; const i = D().seams.findIndex(s => s.a === k || s.b === k); return i < 0 ? null : i }
function custom(pc) { if (pc.shape.type !== "custom") pc.shape = {type: "custom"} }
function scalePiece(pc, ax, f) { custom(pc); const sc = p => p && (p[ax] *= f); pc.verts.forEach(sc); pc.edges.forEach(e => { sc(e.c1); sc(e.c2); if (e.pts) e.pts.forEach(sc) }) }
function renamePiece(pc, nm) {
  // no . or spaces (seam refs are piece.edge), and none of HTML's characters (names go into the page; files are cleaned the same way)
  nm = (nm || "").trim().replace(/[.\s]+/g, "_").replace(/[<>"`&]/g, ""); if (!nm || nm === pc.name) return renderInspector();
  if (pieceBy(nm)) { toast("There's already a piece called " + nm); return renderInspector() }
  const old = pc.name; pc.name = nm;
  D().seams.forEach(s => { for (const k of ["a", "b"]) if (s[k].startsWith(old + ".")) s[k] = nm + s[k].slice(old.length) });
  D().pieces.forEach(p => { if (p.place && p.place.on === old) p.place.on = nm; if (p.place && p.place.layer_of === old) p.place.layer_of = nm });
  DS.sel = nm; dsChanged(true);
}
function mirrorCopy(pc) {
  const n = pc.verts.length, M = p => p && [-p[0], p[1]];
  const verts = [], edges = [];
  for (let j = 0; j < n; j++) verts.push(M(pc.verts[(n - 1 - j) % n]));
  for (let j = 0; j < n; j++) { const e = pc.edges[((n - 2 - j) % n + n) % n]; const ne = {name: e.name, c1: M(e.c2), c2: M(e.c1), elastic: e.elastic}; if (e.hem) ne.hem = {...e.hem}; if (e.sa != null) ne.sa = e.sa; if (e.pts) ne.pts = e.pts.map(M).reverse(); edges.push(ne) }
  const swap = s => s.replace(/_r$/, "_L").replace(/_l$/, "_r").replace(/_L$/, "_l").replace(/right/, "LEFT").replace(/left/, "right").replace(/LEFT/, "left");
  const names = D().pieces.map(p => p.name);
  let nm = swap(pc.name); if (nm === pc.name) nm = pc.name + "_mirror"; nm = uniqueName(nm, names);
  const place = JSON.parse(JSON.stringify(pc.place));
  if (place.anchor) place.anchor[0] = -place.anchor[0];
  if (place.template) place.template.mirror = !place.template.mirror;
  if (place.arm) place.arm = -place.arm;
  if (place.landmark) place.landmark = swap(place.landmark);
  if (place.rotate) place.rotate = -place.rotate;
  if (place.at === "left") place.at = "right"; else if (place.at === "right") place.at = "left";
  const bb = bboxV(pc), c = {name: nm, verts, edges, shape: {type: "custom"}, place, at: [pc.at[0] + (bb[2] - bb[0]) + 10, pc.at[1]]};
  if (pc.shape.type !== "custom") c.shape = {...pc.shape};
  D().pieces.push(c); DS.sel = nm; dsChanged(true); toast("Mirror copy: placed on the other side of the body");
}
function splitEdgeRaw(pc, i, t) {   // returns the new corner (array)
  const e = pc.edges[i], a = pc.verts[i], b = pc.verts[(i + 1) % pc.verts.length];
  let mid, e1, e2;
  if (e.pts) {
    const f = arcFrac(e.pts); mid = pointAtFrac(e.pts, f, t);
    const k = f.findIndex(v => v >= t);
    e1 = {c1: null, c2: null, pts: [...e.pts.slice(0, k), mid]}; e2 = {c1: null, c2: null, pts: [mid, ...e.pts.slice(k)]};
    if (e1.pts.length < 3) delete e1.pts; if (e2.pts.length < 3) delete e2.pts;
  } else if (!e.c1) { mid = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]; e1 = {c1: null, c2: null}; e2 = {c1: null, c2: null} }
  else {   // de Casteljau
    const L = (p, q) => [p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t];
    const p01 = L(a, e.c1), p12 = L(e.c1, e.c2), p23 = L(e.c2, b), p012 = L(p01, p12), p123 = L(p12, p23); mid = L(p012, p123);
    e1 = {c1: p01, c2: p012}; e2 = {c1: p123, c2: p23};
  }
  custom(pc);
  const taken = pc.edges.map(x => x.name);
  const n1 = uniqueName(e.name + "_1", taken), n2 = uniqueName(e.name + "_2", taken);
  pc.verts.splice(i + 1, 0, mid);
  const keep = {...(e.hem ? {hem: {...e.hem}} : {}), ...(e.sa != null ? {sa: e.sa} : {})};
  pc.edges.splice(i, 1, {name: n1, ...e1, elastic: e.elastic, ...keep}, {name: n2, ...e2, elastic: e.elastic, ...keep});
  const k = pc.name + "." + e.name, before = D().seams.length;
  D().seams = D().seams.filter(s => s.a !== k && s.b !== k);
  if (D().seams.length < before) toast("That edge was sewn: sew its two halves again");
  edgeSplitRefs(pc, e.name, [n1, n2]);
  return mid;
}
function splitEdge(pc, i, t) {
  const twins = symImages(pc).map(img => [img, ...symEdge(img, pc, i)]).filter(([img, k]) => k >= 0 && !(img.P === pc && k === i));
  // split the images first (on this piece the mirror edge's index moves if it comes after i)
  twins.sort((a, b) => (b[0].P === pc ? b[1] : -1) - (a[0].P === pc ? a[1] : -1));
  // a mirrored edge runs the other way: swap the halves' names so _1 / _2 sit at the same end on both sides
  const twin = (P, k, rev) => { splitEdgeRaw(P, k, rev ? 1 - t : t); if (rev) { const a = P.edges[k], b = P.edges[k + 1]; [a.name, b.name] = [b.name, a.name] } };
  for (const [img, k, rev] of twins) if (img.P !== pc || k > i) twin(img.P, k, rev);
  splitEdgeRaw(pc, i, t);
  for (const [img, k, rev] of twins) if (img.P === pc && k < i) twin(pc, k, rev);
  dsChanged(true);
}
function edgeSplitRefs(pc, old, parts) {   // an edge became several: lining-open and pocket-sewn lists follow
  if (pc.lining && (pc.lining.open || []).includes(old)) pc.lining.open = [...pc.lining.open.filter(x => x !== old), ...parts];
  if (pc.place && (pc.place.sewn || []).includes(old)) pc.place.sewn = [...pc.place.sewn.filter(x => x !== old), ...parts];
  if (pc.place && (pc.place.held || []).includes(old)) pc.place.held = [...pc.place.held.filter(x => x !== old), ...parts];
}
async function makeTube(pc) {
  const pl = pc.place;
  if (!pl.anchor && !pl.landmark) { toast("Put it on the body first (pick a spot or tap the avatar)"); return }
  try {
    const r = await api("/api/girth", {avatar: ST.avatar.id, point: pl.anchor, landmark: pl.anchor ? undefined : pl.landmark});
    if (!r.girth_cm) { toast("Couldn't measure the body there"); return }
    const w = r.girth_cm + 6;   // 6 cm of ease
    const side = n => pc.edges.find(e => e.name === n);
    if (pc.shape.type === "rect" || pc.shape.type === "trap") {
      if (pc.shape.type === "rect") pc.shape.w = w; else { const f = w / pc.shape.wb; pc.shape.wb = w; pc.shape.wt *= f }
      reshape(pc);
    } else { const bb = bboxV(pc); scalePiece(pc, 0, w / (bb[2] - bb[0])) }
    const L = side("left"), R = side("right");
    if (L && R && seamIndexOf(pc.name, "left") == null && seamIndexOf(pc.name, "right") == null) D().seams.push({a: pc.name + ".right", b: pc.name + ".left", ease: 0});
    toast(`Body there: ${fmtLen(r.girth_cm)}. Width set to ${fmtLen(w)} (6 cm ease)` + (L && R ? ", sides sewn" : ""), 4000);
    dsChanged(true);
  } catch (e) { toast(e.message) }
}
function startPlacing() {
  if (!DS.sel) return; DS.placing = true; $("#glcard").classList.add("placing");
  $("#placeBanner").textContent = `Tap the avatar where ${ {center: "the middle", top: "the top edge", bottom: "the bottom edge", left: "the left edge", right: "the right edge"}[pieceBy(DS.sel).place.at || "center"]} of '${DS.sel}' goes`;
  if (innerWidth < 980) $("#glcard").scrollIntoView({behavior: "smooth"});
}
GL.onClick(h => {
  if (!DS.placing || !DS.sel) return;
  const pc = pieceBy(DS.sel); delete pc.place.landmark; delete pc.place.center_cm; delete pc.place.span_cm;   // its own middle goes there now
   if (pc.place.template) { delete pc.place.template; pc.place.mode = "wrap"; pc.place.offset_cm = 1.5 } pc.place.anchor = h.map(v => +v.toFixed(4));
  DS.placing = false; $("#glcard").classList.remove("placing"); dsChanged(true); toast(`Placed '${pc.name}'`);
});

