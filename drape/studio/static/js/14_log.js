// drape studio: the warnings log and the popups on the pattern
// (classic script: shares one global scope with the others, loaded in order by index.html)
// ------------------------------------------------------------ warnings log + popups on the pattern
const LOG = {items: [], focus: null, seen: new Set(), closed: false, first: true};
function gatherSeam(s) {
  const r = ((DS.resp && DS.resp.seams) || []).find(x => x.a === s.a && x.b === s.b); if (!r) return;
  s.ease = +(Math.abs(r.diff_cm) / Math.min(r.len_a_cm, r.len_b_cm)).toFixed(4); dsChanged(true);
}
function logItems() {
  const out = [];
  if (ST.scratch && ["fit", "design"].includes(ST.step) && DS.resp) {
    for (const c of DS.resp.check || []) {
      if (c.ok) continue;
      if (c.seam) {
        const s = D().seams.find(x => x.a === c.seam[0] && x.b === c.seam[1]); if (!s) continue;
        const r = (DS.resp.seams || []).find(x => x.a === s.a && x.b === s.b) || {};
        const sp = k => k.split(".");
        out.push({id: "seam:" + s.a + "|" + s.b, src: "Seam", text: `${plainRef(s.a)} ↔ ${plainRef(s.b)}: ${fmtLen(Math.abs(r.diff_cm || 0))} different`,
          tech: `${s.a} is ${fmtLen(r.len_a_cm || 0)}, ${s.b} is ${fmtLen(r.len_b_cm || 0)}. Edges that sew together should match, unless one is gathered on purpose.`,
          edges: [sp(s.a), sp(s.b)],
          fixes: [{label: `Both ${fmtLen(r.len_a_cm || 0)}`, title: `Change ${s.b} to match ${s.a}`, run: () => matchSeam(s, "a")},
                  {label: `Both ${fmtLen(r.len_b_cm || 0)}`, title: `Change ${s.a} to match ${s.b}`, run: () => matchSeam(s, "b")},
                  {label: "Gather", title: "Keep both and gather the longer edge into the shorter", run: () => gatherSeam(s)}]});
      } else {
        const m = /'([^']+)'/.exec(c.text), pn = m && pieceBy(m[1]) ? m[1] : null;
        out.push({id: "chk:" + c.text, src: "Design", text: c.text, tech: c.plain || "", piece: pn, edges: [], fixes: []});
      }
    }
  } else if (!ST.scratch && ST.draft && ST.step === "fit") {
    const d = ST.draft;
    if (!d.check.ok) for (const p of d.check.problems) out.push({id: "draft:" + p.text, src: "Pattern", text: p.plain, tech: p.text, edges: [], fixes: []});
    for (const r of d.ease) if (r.ease_cm != null && /TIGHT/.test(r.status))
      out.push({id: "ease:" + r.line, src: "Fit", text: `${cap(r.line)}: ${fmtLen(-r.ease_cm)} too tight`, tech: `body ${fmtLen(r.body_cm)} · pattern ${fmtLen(r.garment_cm)}`, edges: [],
        fixes: r.fix ? [{label: r.fix.label.replace(/(\d+) cm/, (m, n) => fmtLen(+n, 0)), run: () => applyFix(r.fix.param, r.fix.value)}] : []});
  }
  if (ST.drape && ["preview", "export"].includes(ST.step)) {
    const d = ST.drape;
    for (const a of [...(d.advice || []), ...(d.pose ? d.pose.advice : [])]) if (!a.ok && a.level !== "note")   // notes aren't warnings
      out.push({id: "fit:" + a.text, src: "Drape", text: a.text, tech: "", edges: [], fixes: a.fix ? [{label: a.fix.label, run: () => applyFix(a.fix.param, a.fix.value)}] : []});
  }
  return out;
}
function renderLog() {
  const items = logItems(); LOG.items = items;
  const fresh = items.filter(x => !LOG.seen.has(x.id));
  LOG.seen = new Set(items.map(x => x.id));        // a problem that comes back is new again
  if (LOG.focus && !items.some(x => x.id === LOG.focus)) { LOG.focus = null; closePop() }
  $("#logcnt").textContent = items.length; $("#logcnt").classList.toggle("bad", items.length > 0);
  $("#logsum").textContent = items.length ? "" : ST.step === "body" || !(ST.draft || ST.scratch) ? "Pick a garment to check its pattern" : "No problems: every check passes";
  // Simple mode: the bar shows only when there's something to check, as one line
  $("#logcard").classList.toggle("empty", !items.length);
  if (items.length && !document.body.classList.contains("advanced")) $("#logsum").textContent = `${items.length} thing${items.length > 1 ? "s" : ""} to check ▸`;
  $("#logbody").innerHTML = items.map((x, k) => `<div class="lrow ${LOG.focus === x.id ? "focus" : ""}" data-k="${k}"><span class="ic">!</span><span class="src">${x.src}</span>
    <div><b>${x.text}</b>${x.tech ? `<span class="tech">${x.tech}</span>` : ""}</div>
    <div class="fx">${x.fixes.map((f, j) => `<button class="btn small ${j < 2 ? "primary" : ""}" data-f="${j}" title="${f.title || ""}">${f.label}</button>`).join("")}</div></div>`).join("");
  $$("#logbody .lrow").forEach(row => {
    const x = items[+row.dataset.k];
    row.onclick = e => { if (e.target.dataset.f != null) { x.fixes[+e.target.dataset.f].run(); return } focusWarning(x) };
  });
  // something new went wrong on the board: point at it
  const pop = fresh.find(x => x.edges.length);
  if (pop && !LOG.first && ST.step === "fit" && ST.scratch && !DS.drag) focusWarning(pop, true);
  LOG.first = false;
  if (ST.scratch) drawBadges();
}
// the Warnings box is pinned to the bottom of the window: leave room for it (it grows and shrinks with the list)
new ResizeObserver(() => document.documentElement.style.setProperty("--logh", $("#logcard").offsetHeight + "px")).observe($("#logcard"));
$("#loghead").onclick = () => { LOG.closed = !LOG.closed; $("#logcard").classList.toggle("closed", LOG.closed); $("#logtog").textContent = LOG.closed ? "▴" : "▾" };
function focusWarning(x, quiet) {
  LOG.focus = x.id; $$("#logbody .lrow").forEach(r => r.classList.toggle("focus", LOG.items[+r.dataset.k] === x));
  const pn = (x.edges[0] && x.edges[0][0]) || x.piece;
  if (pn && ST.scratch && ST.step === "fit") {
    if (!quiet && DS.sel !== pn) { DS.sel = pn; renderInspector() }
    drawDesign();
  }
  if (!x.edges.length) closePop();
}
function closePop() { const p = $("#warnpop"); if (p) p.remove() }
function edgeMidBoard(pn, en) {
  const pc = pieceBy(pn); if (!pc) return null; const i = pc.edges.findIndex(e => e.name === en); if (i < 0) return null;
  const pts = edgePts(pc, i), f = arcFrac(pts); return boardXY(pc, pointAtFrac(pts, f, 0.5));
}
function boardToCard(w) {   // board point (cm, y up) -> pixels inside the pattern card
  const sv = $("#board"); if (!sv) return null; const p = sv.createSVGPoint(); p.x = w[0]; p.y = -w[1];
  const q = p.matrixTransform(sv.getScreenCTM()), r = $("#patcard").getBoundingClientRect(); return [q.x - r.left, q.y - r.top];
}
function placePop() {   // the popup for the focused warning, pinned under its first edge
  closePop();
  const x = LOG.items.find(i => i.id === LOG.focus); if (!x || !x.edges.length || !ST.scratch || ST.step !== "fit" || DS.drag) return;
  const w = edgeMidBoard(...x.edges[0]); if (!w) return; const at = boardToCard(w); if (!at) return;
  const card = $("#patcard"), div = document.createElement("div"); div.className = "pop"; div.id = "warnpop";
  div.innerHTML = `<button class="x" title="Close">✕</button><b>${x.text}</b><span class="tech">${x.tech}</span><div class="fx">${x.fixes.map((f, j) => `<button class="btn small ${j < 2 ? "primary" : ""}" data-f="${j}" title="${f.title || ""}">${f.label}</button>`).join("")}</div>`;
  card.appendChild(div);
  const W = card.clientWidth, left = Math.max(8, Math.min(W - div.offsetWidth - 8, at[0] - 24));
  div.style.left = left + "px"; div.style.top = Math.min(card.clientHeight - div.offsetHeight - 8, at[1] + 14) + "px";
  div.style.setProperty("--ax", Math.max(10, Math.min(div.offsetWidth - 20, at[0] - left - 6)) + "px");
  div.querySelector(".x").onclick = () => { LOG.focus = null; closePop(); renderLog(); drawDesign() };
  div.querySelectorAll("[data-f]").forEach(b => b.onclick = () => x.fixes[+b.dataset.f].run());
}
function drawBadges() {   // a "!" on every edge with a problem; the focused one drawn bold
  const sv = $("#board"); if (!sv) return; sv.querySelectorAll(".wbadge").forEach(n => n.remove());
  const v = DS.view, hr = Math.max(v[2], v[3]) / 90, NS = "http://www.w3.org/2000/svg";
  for (const x of LOG.items) for (const [pn, en] of x.edges) {
    const pc = pieceBy(pn); if (!pc) continue; const i = pc.edges.findIndex(e => e.name === en); if (i < 0) continue;
    const focus = LOG.focus === x.id, pts = edgePts(pc, i).map(q => boardXY(pc, q));
    if (focus) { const pl = document.createElementNS(NS, "polyline"); pl.setAttribute("points", pts.map(([a, b]) => `${a},${-b}`).join(" "));
      pl.setAttribute("fill", "none"); pl.setAttribute("stroke", "var(--accent)");   // selection colour: never a match colour (A2) pl.setAttribute("stroke-width", hr * 1.1); pl.setAttribute("stroke-linecap", "round");
      pl.setAttribute("class", "wbadge"); pl.setAttribute("pointer-events", "none"); sv.appendChild(pl) }
    // beside the edge, just outside the piece: on the edge it sat on the curve dot, which then couldn't be clicked
    const m0 = edgeMidBoard(pn, en), f = arcFrac(pts), qa = pointAtFrac(pts, f, .45), qb = pointAtFrac(pts, f, .55);
    let nx = -(qb[1] - qa[1]), ny = qb[0] - qa[0]; const nl = Math.hypot(nx, ny) || 1; nx /= nl; ny /= nl;
    const bb = bboxV(pc), c = boardXY(pc, [(bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2]);
    if (nx * (m0[0] - c[0]) + ny * (m0[1] - c[1]) < 0) { nx = -nx; ny = -ny }       // pointing away from the piece
    const m = [m0[0] + nx * hr * 2.6, m0[1] + ny * hr * 2.6], g = document.createElementNS(NS, "g"); g.setAttribute("class", "wbadge"); g.style.cursor = "pointer";
    g.innerHTML = `<circle cx="${m[0]}" cy="${-m[1]}" r="${hr * 1.3}" fill="#e0603f" stroke="var(--panel)" stroke-width="${hr * .3}"/><text x="${m[0]}" y="${-m[1] + hr * .55}" text-anchor="middle" font-size="${hr * 1.6}" font-weight="700" fill="#fff">!</text><title>${x.text}</title>`;
    g.addEventListener("pointerdown", e => { e.stopPropagation(); focusWarning(x) });
    sv.appendChild(g);
  }
  placePop();
}

