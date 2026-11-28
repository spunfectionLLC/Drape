// drape studio: step 3: fit choices, checks, the drafted 2D pattern
// (classic script: shares one global scope with the others, loaded in order by index.html)
// ======================================================== 3. fit
const blockInfo = () => ST.init.blocks.find(b => b.key === ST.block);
let draftSeq = 0;
// g: the garment to draft (default the active one). The draft belongs to the garment that asked for it:
// switching garments while it's on its way must not hand it to the other garment (or show it in its panel)
async function redraft(g = activeGarment()) {
  if (g.scratch) return g === activeGarment() ? dsRefresh() : undefined;
  if (!ST.avatar || !g.block) return;
  const seq = ++draftSeq, key = JSON.stringify([g.block, g.choices, g.params]);
  // a new pattern (no draft yet, or another garment type): the controls say they're on their way;
  // a change to one already shown: it stays, dimmed, with a spinner by the title
  if (g === activeGarment()) draftLoading(!g.draft || g.draft.block !== g.block);
  try {
    const d = await api("/api/draft", {avatar: ST.avatar.id, block: g.block, choices: g.choices, params: g.params});
    if (key === JSON.stringify([g.block, g.choices, g.params]) && g.block && !g.scratch) g.draft = d;
    if (seq !== draftSeq || g !== activeGarment()) return;
    renderDraft(); $("#patov").style.display = "none"; liveRefresh();
  } catch (e) { if (g === activeGarment()) { $("#checks").innerHTML = `<div class="err">${e.message}</div>`; $("#checksBox").open = true;
    if (!g.draft || g.draft.block !== g.block) $("#choices").innerHTML = `<div class="err">Couldn't draft it: ${e.message}</div>` } }
  if (seq === draftSeq) draftLoading(null);
}
// the loading state of the Fit controls and the pattern box: true = a new pattern on its way (placeholders and
// an overlay), false = an update (dimmed, spinner in the title), null = done
function draftLoading(fresh) {
  const pane = $('.pane[data-pane="fit"]');
  pane.classList.toggle("busy", fresh === false); $("#pattern").classList.toggle("busy", fresh === false);
  $("#pathint").innerHTML = fresh === null ? "" : `<span class="spin"></span> ${fresh ? "drafting…" : "updating…"}`;
  if (!fresh) { if (fresh === null) $("#patload")?.remove(); return }
  const b = blockInfo(), what = b ? b.label.toLowerCase() : "pattern";
  if (b) $("#fitTitle").textContent = b.label;
  $("#choices").innerHTML = `<div class="loading" role="status"><span class="spin"></span> Drafting the ${what} to your measurements…</div>`
    + `<div class="skel"></div><div class="skel"></div><div class="skel short"></div>`;
  $("#sliders").innerHTML = `<div class="skel"></div><div class="skel"></div>`;
  $("#checks").innerHTML = ""; $("#checksSum").innerHTML = `<span class="spin"></span> Checks`;
  patternLoading(`Drafting the ${what}…`);
}
function patternLoading(text) {           // over the pattern box until the pattern is drawn (text null: remove)
  $("#patload")?.remove(); if (text == null) return;
  $("#patov").style.display = "none";
  $("#patcard").insertAdjacentHTML("beforeend", `<div class="overlay" id="patload" role="status"><div class="box"><span class="spin big"></span><b>${text}</b></div></div>`);
}
// a choice or slider change: drafted 250 ms after the last one, for the garment it was made on (each garment
// has its own timer, so a switch neither drafts the wrong garment nor drops the change)
const redraftTimers = {};
const redraftSoon = () => { const g = activeGarment();
  (redraftTimers[g.id] = redraftTimers[g.id] || debounce(async () => { await redraft(g); pushHist(g) }, 250))() };
function renderDraft() {
  const d = ST.draft, b = blockInfo(); $("#fitTitle").textContent = b.label;
  // plain-language choices
  $("#choices").innerHTML = Object.entries(b.presets).map(([c, opts]) => {
    const shown = d.choices[c] || {};
    return `<div><h3>${c}</h3><div class="chips">${Object.keys(opts).map(o => {
      const on = ST.choices[c] === o || (!ST.choices[c] && shown.option === o && shown.exact);
      const near = !on && shown.option === o;
      return `<button class="chip ${on ? "on" : ""} ${near ? "near" : ""}" data-c="${c}" data-o="${o}" ${near ? 'title="closest to your custom values"' : ""}>${o}</button>`
    }).join("")}</div></div>`
  }).join("");
  $$("#choices .chip").forEach(ch => ch.onclick = () => {
    const c = ch.dataset.c, o = ch.dataset.o; ST.choices[c] = o;
    for (const p of b.presets[c][o]) delete ST.params[p];   // the choice wins over hand edits of the same values
    ST.drape = null; redraftSoon();
    $$(`#choices .chip[data-c="${c}"]`).forEach(x => x.classList.toggle("on", x === ch));
  });
  renderChecks(); renderSliders(); renderSeamTable(); drawPattern();
}
function renderChecks() {
  const d = ST.draft, out = [];
  if (d.check.ok) out.push(`<div class="check ok"><span class="ic">✓</span><div><b>All ${d.check.n_seams} seams line up</b><span class="tech">Every pair of edges that sew together is the same length, and the edges meet smoothly.</span></div></div>`);
  else for (const p of d.check.problems) out.push(`<div class="check bad"><span class="ic">!</span><div><b>${p.plain}</b><span class="tech">${p.text}</span></div></div>`);
  for (const r of d.ease) {
    if (r.ease_cm == null) continue;
    const tight = /TIGHT/.test(r.status);
    const room = r.ease_cm < 0 ? `${fmtLen(-r.ease_cm)} too tight: the fabric has to stretch` : `${fmtLen(r.ease_cm)} of room`;
    const fix = r.fix ? `<div style="margin-top:6px"><button class="btn small primary" data-fp="${r.fix.param}" data-fv="${r.fix.value}">Fix it: ${r.fix.label.replace(/(\d+) cm/, (m, n) => fmtLen(+n, 0))}</button></div>` : "";
    out.push(`<div class="check ${tight ? "bad" : "ok"}"><span class="ic">${tight ? "!" : "✓"}</span><div><b>${cap(r.line)}: ${room}</b><span class="tech">body ${fmtLen(r.body_cm)} · pattern ${fmtLen(r.garment_cm)} · ${r.status.toLowerCase()}</span>${fix}</div></div>`);
  }
  $("#checks").innerHTML = out.join("");
  // one summary line; the list opens by itself when something needs a look
  const bad = out.filter(h => h.includes("check bad")).length;
  $("#checksSum").innerHTML = bad ? `<span class="ic bad">!</span>${bad} of ${out.length} checks need a look` : `<span class="ic ok">✓</span>All ${out.length} checks pass`;
  if (bad) $("#checksBox").open = true;
  $$("#checks [data-fp]").forEach(bt => bt.onclick = () => applyFix(bt.dataset.fp, +bt.dataset.fv));
  renderLog();
}
const cap = s => s[0].toUpperCase() + s.slice(1);
function applyFix(p, v) { ST.params[p] = v; ST.drape = null; toast(`Changed ${p.replace(/_/g, " ")}`); redraftSoon() }
function renderSliders() {
  const b = blockInfo(), d = ST.draft, groups = {};
  for (const p of b.params) (groups[p.group] = groups[p.group] || []).push(p);
  $("#sliders").innerHTML = Object.entries(groups).map(([g, ps]) => `<h3>${g}</h3>` + ps.map(p => {
    const v = d.params[p.name], isLen = p.unit === "cm";
    const show = isLen ? toUnit(v).toFixed(ST.units === "in" ? 2 : 1) + (ST.units === "in" ? '"' : " cm") : v + " " + p.unit;
    const changed = Math.abs(v - d.defaults[p.name]) > 1e-6;
    return `<div class="slider ${changed ? "changed" : ""}"><label>${p.label}${p.help ? `<small>${p.help}</small>` : ""}</label><span class="val">${show}</span>
      <input type="range" min="${p.lo}" max="${p.hi}" step="${p.step}" value="${v}" data-p="${p.name}"></div>`
  }).join("")).join("");
  $$("#sliders input").forEach(s => s.oninput = () => {
    const p = b.params.find(q => q.name === s.dataset.p), v = +s.value; ST.params[p.name] = v; ST.drape = null;
    s.previousElementSibling.textContent = p.unit === "cm" ? fmtLen(v) : v + " " + p.unit; redraftSoon();
  });
}
$("#resetp").onclick = () => { ST.params = {}; ST.drape = null; redraftSoon() };
function renderSeamTable() {
  const d = ST.draft;
  $("#seamtab").innerHTML = `<tr><th>Edge A</th><th>Edge B</th><th class="num">ease</th></tr>` +
    d.seams.map((s, i) => `<tr><td><i style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${seamColor(i)}"></i> ${s.a}</td><td>${s.b}</td><td class="num">${s.ease_pct}%</td></tr>`).join("");
}
$("#toPreview").onclick = () => go("preview");
$("#toScratch").onclick = async () => {
  if (ST.design.pieces.length && !confirm("This replaces your current from-scratch design. Continue?")) return;
  try {
    const r = await api("/api/to_scratch", {avatar: ST.avatar.id, block: ST.block, choices: ST.choices, params: ST.params});
    ST.design = r.design; ST.scratch = true; ST.drape = null; ST.sfull = null;
    tidy(); DS.view = null; DS.sel = r.design.pieces[0].name; $("#pattern").classList.add("design");
    renderGarments(); go("fit"); pushHist();
    toast(`${blockInfo().label} is now yours to edit. Undo goes back to the pattern.`, 4500);
  } catch (e) { toast("Couldn't convert: " + e.message, 5000) }
};
addEventListener("resize", debounce(() => ST.scratch ? (ST.step === "fit" && drawDesign()) : ST.draft && drawPattern(), 200));

// ---------------------------------------------------- 2D pattern (SVG)
const seamColor = i => `hsl(${(i * 137.5) % 360} 62% 46%)`;
function packPieces(pieces, rowW, gap) {
  let x = 0, y = 0, rowH = 0, H = 0, W = 0; const placed = [];
  for (const p of pieces) {
    const [x0, y0, x1, y1] = bbox(p), w = x1 - x0, h = y1 - y0;
    if (x > 0 && x + w > rowW + 1e-6) { x = 0; y += rowH + gap; rowH = 0 }
    placed.push({p, dx: x - x0, dy: y + h + y0}); x += w + gap; rowH = Math.max(rowH, h); H = Math.max(H, y + rowH); W = Math.max(W, x - gap);
  }
  return {placed, W, H};
}
function drawPattern() {
  const d = ST.draft, pad = 6, gap = 8, box = $("#pattern").getBoundingClientRect();
  const aspect = box.width > 10 && box.height > 10 ? box.width / box.height : 1;
  // try every number of rows; keep the arrangement that shows the pieces biggest
  const total = d.pieces.reduce((a, p) => { const bb = bbox(p); return a + bb[2] - bb[0] + gap }, 0);
  const widest = Math.max(...d.pieces.map(p => bbox(p)[2] - bbox(p)[0]));
  let best = null;
  for (let r = 1; r <= d.pieces.length; r++) {
    const L = packPieces(d.pieces, Math.max(widest, total / r), gap);
    const sc = Math.min(aspect / (L.W + 2 * pad), 1 / (L.H + 2 * pad + 4));
    if (!best || sc > best.sc) best = {...L, sc};
  }
  const {placed, H} = best;
  const W = Math.max(...placed.map(q => q.dx + bbox(q.p)[2]));
  const T = q => pt => `${(pt[0] + q.dx).toFixed(2)},${(q.dy - pt[1]).toFixed(2)}`;
  let svg = `<svg viewBox="${-pad} ${-pad} ${W + 2 * pad} ${H + 2 * pad}" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg">
   <defs><pattern id="grid" width="10" height="10" patternUnits="userSpaceOnUse"><path d="M10 0H0V10" fill="none" stroke="var(--line)" stroke-width=".3"/></pattern></defs>
   <rect x="${-pad}" y="${-pad}" width="${W + 2 * pad}" height="${H + 2 * pad}" fill="url(#grid)"/>`;
  for (const q of placed) {
    const t = T(q), poly = q.p.edges.flatMap(e => e.pts.slice(0, -1)).map(t).join(" ");
    svg += `<g><polygon points="${poly}" fill="var(--accent-soft)" fill-opacity=".55" stroke="none"/>`;
    for (const e of q.p.edges) {
      const col = e.seam == null ? "var(--ink)" : seamColor(e.seam), wd = e.seam == null ? .5 : 1.1;
      svg += `<polyline points="${e.pts.map(t).join(" ")}" fill="none" stroke="${col}" stroke-width="${wd}" stroke-linecap="round" class="edge"><title>${q.p.name}.${e.name}: ${fmtLen(e.length_cm)}${e.seam != null ? "  (sews to " + otherEnd(e.seam, q.p.name + "." + e.name) + ")" : ""}</title></polyline>`;
    }
    // the same markings as the printed pattern: notches (one = front, two = back), ③ sews to ③, match dots
    for (const e of q.p.edges) {
      for (const [x, y, nx, ny] of e.notches || []) {
        const a = t([x, y]).split(","), b = t([x + nx * 1.4, y + ny * 1.4]).split(",");
        svg += `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="var(--ink)" stroke-width=".5"/>`;
      }
      if (e.num != null && e.tag) {
        const c = t(e.tag).split(",");
        svg += `<g><title>${q.p.name}.${e.name}: seam ${e.num}, sews to ${e.partner.toLowerCase()}</title><circle cx="${c[0]}" cy="${c[1]}" r="2" fill="${seamColor(e.seam)}"/><text x="${c[0]}" y="${+c[1] + .85}" text-anchor="middle" font-size="2.4" font-weight="700" fill="#fff" font-family="var(--font)">${e.num}</text></g>`;
      }
    }
    for (const d of q.p.dots || []) { const c = t(d).split(","); svg += `<circle cx="${c[0]}" cy="${c[1]}" r=".9" fill="var(--ink)"><title>match point: goes to the seam between the two pieces</title></circle>` }
    // grainline + label
    const [x0, y0, x1, y1] = bbox(q.p), cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, gh = (y1 - y0) * .28;
    const a = t([cx, cy - gh]), b = t([cx, cy + gh]);
    svg += `<line x1="${a.split(",")[0]}" y1="${a.split(",")[1]}" x2="${b.split(",")[0]}" y2="${b.split(",")[1]}" stroke="var(--muted)" stroke-width=".4"/>`;
    const fs = Math.max(2.2, Math.min(4.5, (x1 - x0) / 9)), lp = t([cx, cy - fs * .2]).split(",");   // centre: clear of the seam numbers by the edges
    svg += `<text x="${lp[0]}" y="${lp[1]}" text-anchor="middle" font-size="${fs}" fill="var(--ink)" font-family="var(--font)" font-weight="600">${q.p.name.replace(/_/g, " ")}</text>`;
    svg += `<text x="${lp[0]}" y="${+lp[1] + fs * 1.1}" text-anchor="middle" font-size="${fs * .6}" fill="var(--muted)" font-family="var(--font)">cut 1 · grain ↕</text></g>`;
  }
  // scale bar: 10 cm
  svg += `<g transform="translate(0 ${H + pad * .4})"><line x1="0" x2="10" stroke="var(--ink)" stroke-width=".6"/><text x="11.5" y="1.2" font-size="2.6" fill="var(--muted)">${ST.units === "in" ? "10 cm (3.9\")" : "10 cm"}</text></g></svg>`;
  $("#pattern").innerHTML = svg;
}
function bbox(p) { let a = [1e9, 1e9, -1e9, -1e9]; for (const e of p.edges) for (const [x, y] of e.pts) { a[0] = Math.min(a[0], x); a[1] = Math.min(a[1], y); a[2] = Math.max(a[2], x); a[3] = Math.max(a[3], y) } return a }
function otherEnd(i, me) { const s = ST.draft.seams[i]; return s.a === me ? s.b : s.a }

