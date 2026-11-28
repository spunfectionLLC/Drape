// drape studio: the Garments panel (multi-garment spec, 2026-11-24)
// (classic script: shares one global scope with the others, loaded in order by index.html)
// The project's garments, top layer first. Click one to work on it; drag to change the layer order (the
// order is only ever set here, by you: design-around rule, never worked out from the body); the eye hides
// it in 3D; the snowflake freezes it (it stops moving and the next garment drapes over it).
const topLayer = () => Math.max(0, ...PROJECT.garments.map(g => g.layer));
const byLayer = () => [...PROJECT.garments].sort((a, b) => b.layer - a.layer);
const esc = s => String(s).replace(/[&<>"]/g, c => `&#${c.charCodeAt(0)};`);

function renderGarmentList() {
  const act = PROJECT.activeGarmentId;
  $("#glist").innerHTML = byLayer().map(g => `<div class="grow ${g.id === act ? "on" : ""} ${g.visible ? "" : "hiddeng"}" draggable="true" data-id="${g.id}" role="option" aria-selected="${g.id === act}">
      <span class="gsw" style="background:${g.color}"></span>
      <span class="gname" title="Double-click to rename">${esc(g.name)}</span>
      <span class="glayer" title="Layer ${g.layer}: ${g.layer === 1 ? "closest to the body" : "over layer " + (g.layer - 1)}">L${g.layer}</span>
      <button class="gicon geye ${g.visible ? "on" : ""}" data-act="eye" title="${g.visible ? "Hide" : "Show"} it in 3D" aria-pressed="${g.visible}">${g.visible ? "👁" : "◌"}</button>
      <button class="gicon gfreeze ${g.frozen ? "on" : ""}" data-act="freeze" title="${g.frozen ? "Frozen: it holds its draped shape and the next layer drapes over it. Click to unfreeze" : "Freeze it once it's draped: it holds still and the next garment drapes over it"}" aria-pressed="${g.frozen}">❄</button>
    </div>`).join("");
  $("#gselect").innerHTML = byLayer().map(g => `<option value="${g.id}" ${g.id === act ? "selected" : ""}>L${g.layer} · ${esc(g.name)}${g.frozen ? " ❄" : ""}</option>`).join("");
  $$("#glist .grow").forEach(row => {
    const g = garmentBy(row.dataset.id);
    row.onclick = e => {
      const a = e.target.closest("[data-act]");
      if (a && a.dataset.act === "eye") { g.visible = !g.visible; afterPanelChange(g === activeGarment()); return }
      if (a && a.dataset.act === "freeze") { toggleFreeze(g); return }
      setActiveGarment(g.id);
    };
    row.querySelector(".gname").ondblclick = e => { e.stopPropagation(); renameInline(row, g) };
    row.oncontextmenu = e => { e.preventDefault(); garmentMenu(g, e.clientX, e.clientY) };
    row.ondragstart = e => { e.dataTransfer.setData("text/plain", g.id); row.classList.add("dragging") };
    row.ondragend = () => row.classList.remove("dragging");
    row.ondragover = e => { e.preventDefault(); row.classList.add("dropover") };
    row.ondragleave = () => row.classList.remove("dropover");
    row.ondrop = e => { e.preventDefault(); row.classList.remove("dropover"); moveGarment(e.dataTransfer.getData("text/plain"), g.id) };
  });
}
// after a change to the list: redraw it (and the 3D view if what shows changed), keep it in this browser
function afterPanelChange(redraw3d = true) {
  renderGarmentList(); if (redraw3d) { if (ST.drape && ["preview", "export"].includes(ST.step)) showDrape(); else refreshScene() }
  autosave();
}
// drop `id` where `onto` is: the list is top layer first, so layers are renumbered from the bottom up
function moveGarment(id, onto) {
  if (!id || id === onto || !garmentBy(id) || !garmentBy(onto)) return;    // something else dropped on a row (text, a file)
  const ids = byLayer().map(g => g.id), down = ids.indexOf(id) < ids.indexOf(onto);   // dragged down: it goes below
  const order = ids.filter(x => x !== id);
  order.splice(order.indexOf(onto) + (down ? 1 : 0), 0, id);
  order.forEach((x, i) => garmentBy(x).layer = order.length - i);
  afterPanelChange(false);
}
function renameInline(row, g) {
  const span = row.querySelector(".gname"), inp = document.createElement("input");
  inp.className = "gnamein"; inp.value = g.name; span.replaceWith(inp); inp.focus(); inp.select();
  // once: Enter/Escape re-render the list, which removes the input, which fires blur (Escape must not then save)
  let fin = false;
  const done = ok => { if (fin) return; fin = true; if (ok && inp.value.trim()) g.name = inp.value.trim(); afterPanelChange(false) };
  inp.onkeydown = e => { if (e.key === "Enter") done(true); if (e.key === "Escape") done(false) };
  inp.onblur = () => done(true);
  inp.onclick = e => e.stopPropagation();
}
function garmentMenu(g, x, y) {
  $$(".gctx").forEach(m => m.remove());
  const m = document.createElement("div"); m.className = "ddmenu gctx"; m.style.cssText = `position:fixed;left:${x}px;top:${y}px;z-index:50`;
  m.innerHTML = `<button class="btn small" data-m="rename">Rename</button><button class="btn small" data-m="dup">Duplicate</button>
    <button class="btn small" data-m="export">Export garment</button><button class="btn small" data-m="del">Delete…</button>`;
  document.body.appendChild(m);
  m.onclick = e => {
    const k = e.target.dataset.m; m.remove(); if (!k) return;
    if (k === "rename") renameInline($(`#glist .grow[data-id="${g.id}"]`), g);
    if (k === "dup") duplicateGarment(g);
    if (k === "export") exportGarment(g);
    if (k === "del") deleteGarment(g);
  };
  setTimeout(() => document.addEventListener("click", () => m.remove(), {once: true}), 0);
}
// ---- add, duplicate, delete
function addBlankGarment() {
  const g = newGarment(`Garment ${PROJECT.garments.length + 1}`, {layer: topLayer() + 1});
  PROJECT.garments.push(g); setActiveGarment(g.id); go("garment");     // pick what it is
}
function duplicateGarment(src = activeGarment()) {
  const d = JSON.parse(JSON.stringify(garmentData(src)));
  const g = newGarment(src.name + " copy", {...d, id: uid(), layer: topLayer() + 1, frozen: false, frozenMesh: undefined,
    color: GARMENT_COLORS[PROJECT.garments.length % GARMENT_COLORS.length]});
  PROJECT.garments.push(g); setActiveGarment(g.id); pushHist();
  if (!ST.scratch && ST.block) redraft();
}
function deleteGarment(g) {
  if (!confirm(`Delete "${g.name}"? Its pattern and drape go with it. (Export it first if you might want it back.)`)) return;
  PROJECT.garments = PROJECT.garments.filter(x => x.id !== g.id);
  if (!PROJECT.garments.length) PROJECT.garments.push(newGarment("Garment 1"));
  byLayer().reverse().forEach((x, i) => x.layer = i + 1);                 // no gaps
  // its undo steps go; the position moves back by the steps removed at or before it
  H.i -= H.stack.slice(0, H.i + 1).filter(e => e.gid === g.id).length;
  H.stack = H.stack.filter(e => e.gid !== g.id); delete H.last[g.id]; updUndo();
  if (PROJECT.activeGarmentId === g.id) { PROJECT.activeGarmentId = byLayer()[0].id; onGarmentSwitch(false) }
  else afterPanelChange();
}
// ---- freeze: the garment keeps the shape it was draped in, stops moving, and the next one drapes over it
// (all or nothing per garment: design-around rule, no per-area pinning)
function toggleFreeze(g) {
  if (!g.frozen) {
    const c = g.drape && g.drape.cloth;
    if (!c) { toast(`Drape ${g.name} first: it freezes in its draped shape`); return }
    g.frozenMesh = {v: c.v, f: c.f, panel: c.panel, nv: c.nv, nf: c.nf};
  }
  g.frozen = !g.frozen; if (!g.frozen) g.frozenMesh = undefined;
  afterPanelChange(false); syncFrozenNotice();
}
// the dimmed garments around the one you work on: every other visible garment with a draped (or frozen) shape
function refreshScene() {
  if (!GL.setOthers) return;
  const moving = (typeof LIVE !== "undefined" && LIVE.gids) || [];      // in Live with the active one: its cloth shows them
  GL.setOthers(PROJECT.garments.filter(g => g.id !== PROJECT.activeGarmentId && !moving.includes(g.id) && g.visible && ((g.drape && g.drape.cloth) || g.frozenMesh))
    .map(g => ({cloth: (g.drape && g.drape.cloth) || g.frozenMesh, fabric: g.fabric, gid: g.id})));
}
// more than one garment would move in the next drape: they drape together, inner layer first (desktop)
function syncFrozenNotice() {
  const n = PROJECT.garments.filter(g => g.visible && !g.frozen && (g.block || g.scratch)).length;
  const el = $("#layernote"); if (el) el.hidden = n < 2;
}
// ---- the panel's own controls
{
  const set = open => { $("#gpanel").classList.toggle("collapsed", !open); $("#gtoggle").setAttribute("aria-expanded", String(open)); $("#gtoggle").textContent = open ? "▾" : "▸"; LS.set("gpanelOpen", open) };
  $("#gtoggle").onclick = () => set($("#gpanel").classList.contains("collapsed"));
  set(LS.get("gpanelOpen", true));
  $("#addGarmentMenu").addEventListener("click", e => {
    const a = e.target.dataset.ga; if (!a) return; $("#addGarmentMenu").hidden = true;
    if (a === "blank") addBlankGarment();
    if (a === "dup") duplicateGarment();
    if (a === "import") $("#importGarmentFile").click();
  });
  $("#importGarmentFile").onchange = async e => {
    const f = e.target.files[0]; e.target.value = ""; if (!f) return;
    try { await openText(await f.text(), f.name) } catch (err) { toast("Couldn't open that file: " + err.message, 5000) }
  };
  $("#gselect").onchange = e => setActiveGarment(e.target.value);
  $("#exportGarmentBtn").onclick = () => exportGarment();
  $("#saveProjectBtn").onclick = () => saveFile(false);
  $("#changePattern").onclick = e => { e.preventDefault(); go("garment") };   // Design: pick another pattern for this garment
  GL.onGarmentClick && GL.onGarmentClick(id => setActiveGarment(id));
  renderGarmentList();
}
