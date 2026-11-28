// drape studio: seams list, seam matching, design checks
// (classic script: shares one global scope with the others, loaded in order by index.html)
// ------------------------------------------------------------ seams & checks
async function serverEdit(op, args) {
  try {
    const r = await api("/api/edit", {design: D(), op, args, avatar: ST.avatar ? ST.avatar.id : undefined});
    ST.design = r.design; if (DS.sel && !pieceBy(DS.sel)) DS.sel = ST.design.pieces[0] && ST.design.pieces[0].name;
    tidy(); dsChanged(true, true); toast(r.message, 4500); return true;
  } catch (e) { toast(e.message, 6000); return false }
}
const OPENS = [[0, "done up"], [0.5, "half open"], [1, "open"]];
function closureRow(s, i, r) {
  const c = s.closure, L = r ? Math.min(r.len_a_cm, r.len_b_cm) : 50;
  const kinds = `<select data-clo="${i}" title="How this seam closes"><option value="">sewn shut</option>${Object.entries(ST.init.closures).map(([k, l]) => `<option value="${k}" ${c && c.type === k ? "selected" : ""}>${l}</option>`).join("")}</select>`;
  if (!c) return `<div class="cloopts">${kinds}</div>`;
  const many = c.type === "buttons" || c.type === "snaps";
  return `<div class="cloopts">${kinds}
    ${many ? `<label>× <input data-ccount="${i}" type="number" min="1" max="20" value="${c.count}" style="width:52px"></label>` : ""}
    ${c.type !== "zipper" ? `<label><input data-csize="${i}" type="number" min="6" max="40" value="${c.size_mm}" style="width:52px"> mm</label>` : `<small style="color:var(--muted)">${Math.ceil(L / 2.5) * 2.5} cm zipper</small>`}
    ${OPENS.map(([v, l]) => `<span class="tag ${Math.abs((c.open || 0) - v) < .01 ? "on" : ""}" data-copen="${i}" data-v="${v}">${l}</span>`).join("")}
    ${L > 25 ? `<span class="tag" data-cpart="${i}" title="Only the top part opens; the rest is sewn">top part only…</span>` : ""}</div>`;
}
function bindClosures(info) {
  $$("#dsSeams [data-clo]").forEach(el => el.onchange = () => {
    const s = D().seams[+el.dataset.clo], k = el.value, r = info.find(x => x.a === s.a && x.b === s.b), L = r ? r.len_a_cm : 50;
    if (!k) delete s.closure;
    else s.closure = {type: k, count: (k === "buttons" || k === "snaps") ? Math.max(2, Math.round(L / 9)) : 1,
      size_mm: {buttons: 15, snaps: 12, zipper: 0, hook_loop: 20}[k], open: s.closure ? s.closure.open || 0 : 0};
    dsChanged(true);
  });
  $$("#dsSeams [data-ccount]").forEach(el => el.onchange = () => { D().seams[+el.dataset.ccount].closure.count = Math.min(200, Math.max(1, Math.round(+el.value) || 1)); dsChanged(true) });
  $$("#dsSeams [data-csize]").forEach(el => el.onchange = () => { D().seams[+el.dataset.csize].closure.size_mm = Math.min(100, Math.max(5, +el.value || 15)); dsChanged(true) });
  $$("#dsSeams [data-copen]").forEach(el => el.onclick = () => { D().seams[+el.dataset.copen].closure.open = +el.dataset.v; ST.drape = null; dsChanged(true) });
  $$("#dsSeams [data-cpart]").forEach(el => el.onclick = () => {
    const s = D().seams[+el.dataset.cpart], v = prompt(`How long is the opening, from the top (${ST.units})?`, toUnit(18).toFixed(0)); if (!v) return;
    const kind = s.closure.type, a = s.a, old = s.closure;
    // refused (a blank or odd length): the seam keeps its closure
    delete s.closure; serverEdit("partial_closure", {ref: a, length_cm: fromUnit(parseFloat(v)), kind}).then(ok => { if (!ok) { s.closure = old; renderDsSeams() } });
  });
}
function stageRow(s, i) {   // staged sewing (read-only): a seam is sewn with the later of its two pieces
  const st = (DS.resp && DS.resp.stages) || {}, now = (st.seam || [])[i];
  if (!now || !(st.seam || []).some(v => v > 1)) return "";
  return `<div class="adv stagerow"><small>Sews in stage ${now}</small> <small class="stage-auto">(set a piece's sewing order in its panel)</small></div>`;
}
function renderDsSeams() {
  const info = (DS.resp && DS.resp.seams) || [];
  $("#seamCount").textContent = D().seams.length ? `(${D().seams.length})` : "";   // on the toolbar's Seams button
  $("#dsSeams").innerHTML = D().seams.length ? D().seams.map((s, i) => {
    const r = info.find(x => x.a === s.a && x.b === s.b), d = r ? r.diff_cm : 0, ok = !r || Math.abs(d) <= Math.max(0.3, 0.01 * Math.min(r.len_a_cm, r.len_b_cm)) || s.ease;
    // seam colours identify which edges sew together, never whether they match (a design
    // rule): the row looks the same either way, a mismatch is in words
    return `<div class="check seamrow"><span class="ic" style="background:${seamColor(i)}">${i + 1}</span><div><b>${plainRef(s.a)} ↔ ${plainRef(s.b)}</b><span class="tech adv-inline">${s.a} ↔ ${s.b}</span>
      <span class="tech">${r ? `${fmtLen(r.len_a_cm)} and ${fmtLen(r.len_b_cm)}` : ""}${s.ease ? ` · gathered ${(s.ease * 100).toFixed(0)}%` : ""}${!ok && r ? ` · lengths differ by ${fmtLen(Math.abs(d))}` : ""}</span>
      <div class="row" style="margin-top:5px">${!ok ? `<button class="btn small primary" data-match="${i}" data-keep="a" title="Change ${s.b} to match ${s.a}">Both ${r ? fmtLen(r.len_a_cm) : ""}</button><button class="btn small primary" data-match="${i}" data-keep="b" title="Change ${s.a} to match ${s.b}">Both ${r ? fmtLen(r.len_b_cm) : ""}</button><button class="btn small" data-gather="${i}">Gather the longer one</button>` : ""}
      ${s.ease ? `<button class="btn small" data-ungather="${i}">No gathers</button>` : ""}<button class="btn small" data-flip="${i}" title="If the seam comes out twisted, sew it the other way round">Flip</button><button class="btn small" data-unsew="${i}">Unsew</button></div>${closureRow(s, i, r)}${stageRow(s, i)}</div></div>`
  }).join("") : `<p class="lead" style="font-size:13px">Nothing sewn yet. Switch to 🧵 Sew edges.</p>`;
  bindClosures(info);
  $$("#dsSeams [data-unsew]").forEach(b => b.onclick = () => { D().seams.splice(+b.dataset.unsew, 1); dsChanged(true) });
  $$("#dsSeams [data-flip]").forEach(b => b.onclick = () => { const s = D().seams[+b.dataset.flip], r = info.find(x => x.a === s.a && x.b === s.b); s.reverse = r ? !r.reverse : !s.reverse; dsChanged(true) });
  $$("#dsSeams [data-gather]").forEach(b => b.onclick = () => { const s = D().seams[+b.dataset.gather], r = info.find(x => x.a === s.a && x.b === s.b); s.ease = +(Math.abs(r.diff_cm) / Math.min(r.len_a_cm, r.len_b_cm)).toFixed(4); dsChanged(true) });
  $$("#dsSeams [data-ungather]").forEach(b => b.onclick = () => { D().seams[+b.dataset.ungather].ease = 0; dsChanged(true) });
  $$("#dsSeams [data-match]").forEach(b => b.onclick = () => matchSeam(D().seams[+b.dataset.match], b.dataset.keep));
  renderLog();
}
function matchSeam(s, keep) {   // make the two edges of a seam the same length: keep "a", keep "b", or (none) lengthen the shorter
  const [pa, ea] = s.a.split("."), [pb, eb] = s.b.split("."), A = pieceBy(pa), B = pieceBy(pb);
  const ia = A.edges.findIndex(e => e.name === ea), ib = B.edges.findIndex(e => e.name === eb);
  const la = plen(edgePts(A, ia)), lb = plen(edgePts(B, ib));
  if (!keep) keep = la < lb ? "b" : "a";
  const [P, i, L, f] = keep === "a" ? [B, ib, la, la / lb] : [A, ia, lb, lb / la];
  if (P.shape.type === "custom") { extendEdge(P, i, L); toast(`${P.name}.${P.edges[i].name} is now ${fmtLen(L)}`); dsChanged(true); return }
  // scale the piece along that edge's direction (works for the sides of rectangles and trapezoids)
  const a = P.verts[i], b = P.verts[(i + 1) % P.verts.length], ax = Math.abs(b[0] - a[0]) > Math.abs(b[1] - a[1]) ? 0 : 1;
  if (P.shape.type === "rect") { P.shape[ax ? "h" : "w"] *= f; reshape(P) }
  else if (P.shape.type === "trap" && ax === 1) { P.shape.h *= f; reshape(P) }
  else scalePiece(P, ax, f);
  toast(`Resized '${P.name}' so the seam matches`); dsChanged(true);
}
function extendEdge(P, i, L) {
  // move one end of the edge along its own direction until it is L long: the
  // end next to an unsewn edge (a hem, say), so the rest of the piece stays put
  const n = P.verts.length;
  for (let it = 0; it < 4; it++) {
    const pts = edgePts(P, i), d = L - plen(pts); if (Math.abs(d) < 0.02) break;
    const nextFree = seamIndexOf(P.name, P.edges[(i + 1) % n].name) == null, prevFree = seamIndexOf(P.name, P.edges[(i - 1 + n) % n].name) == null;
    const atEnd = nextFree || !prevFree;
    const [p, q] = atEnd ? [pts[pts.length - 2], pts[pts.length - 1]] : [pts[1], pts[0]];
    const l = Math.hypot(q[0] - p[0], q[1] - p[1]) || 1;
    moveVertexSym(P, atEnd ? (i + 1) % n : i, (q[0] - p[0]) / l * d, (q[1] - p[1]) / l * d);
  }
}
function renderDsChecks() {
  renderLog();
  const c = (DS.resp && DS.resp.check) || [];
  $("#dsChecks").innerHTML = c.map(x => `<div class="check ${x.ok ? "ok" : "bad"}"><span class="ic">${x.ok ? "✓" : "!"}</span><div><b>${x.text}</b><span class="tech">${x.plain || ""}</span></div></div>`).join("")
    + ((DS.resp && DS.resp.elastic || []).map(e => `<div class="check ok"><span class="ic">✓</span><div><b>Elastic: ${fmtLen(e.elastic_cm)}</b><span class="tech">gathers ${e.edges} edge${e.edges > 1 ? "s" : ""} to ${e.gathers_to_pct}% to fit the body</span></div></div>`).join(""));
}


