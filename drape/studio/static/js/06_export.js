// drape studio: step 5: exports, size runs, nesting, costing, video
// (classic script: shares one global scope with the others, loaded in order by index.html)
// ======================================================== 5. export
$("#sa").oninput = e => { ST.sa = +e.target.value; $("#sav").textContent = fmtLen(ST.sa) };
const EXPORTS = [
  ["pdf_letter", "Print at home (Letter)", "Tiled pages with a 5 cm test square. Tape together along the marks."],
  ["pdf_a4", "Print at home (A4)", "Same, on A4 paper."],
  ["projector", "Projector file", "One big page at true scale with a 10 cm calibration grid."],
  ["layout", "Cutting layout", "Where each piece goes on the fabric (PNG)."],
  ["dxf", "DXF (CAD / plotter)", "Cut and stitch lines, notches, grain, labels. Millimetres."],
  ["dxf_laser", "DXF for laser cutting", "Red = cut, blue = stitch mark, green = engrave. LightBurn-ready."],
  ["aama", "DXF-AAMA (factory / pattern CAD)", "The industry format: most pattern CAD software and marker makers read it. Pieces as blocks with names, sizes, notches, grain."],
  ["techpack", "Tech pack (PDF)", "For a factory or sewing contractor: views, measurement spec with tolerances, materials, cut list, pieces, construction steps.", true],
  ["blender", "Photoreal render kit (Blender)", "The draped garment and avatar (.glb) plus a script that renders a studio photo in free Blender, with fabric sheen and weave.", true],
  ["glb", "3D model (glTF .glb)", "Draped garment and avatar, one object per piece, UVs at true scale. Opens in any 3D app.", true],
  ["obj", "3D model (OBJ)", "The draped garment, for Blender and other 3D apps.", true],
  ["spec", "Project file (JSON)", "Your measurements, garment and every setting. Open it later to pick up where you left off."],
];
// ---- Simple mode's three outputs; everything else is under "More formats" (open in Advanced)
// Letter in the US and Canada, A4 elsewhere (from the browser's language); the card can switch it
function defaultPaper(lang = navigator.language || "") { return /^en-(US|CA)\b/i.test(lang) ? "letter" : "a4" }
function renderSimpleExports() {
  const paper = LS.get("paper", null) || defaultPaper(), pane = $('.pane[data-pane="export"]');
  $("#simpleExports").innerHTML = `<button class="exp primary" data-k="pdf_${paper}" id="printHome"><b>Print at home</b>
      <small>Tiled pages with a 5 cm test square. Tape them together along the marks.</small>
      <span class="seg paper" title="Paper size"><span data-paper="letter" class="${paper === "letter" ? "on" : ""}">Letter</span><span data-paper="a4" class="${paper === "a4" ? "on" : ""}">A4</span></span></button>
    <button class="exp" data-k="layout"><b>Cutting layout</b><small>Where each piece goes on the fabric.</small></button>
    <button class="exp" id="instrCard"><b>Sewing instructions</b><small>Step by step, in the order you sew it.</small></button>`;
  $$("#simpleExports [data-paper]").forEach(s => s.onclick = e => { e.stopPropagation(); LS.set("paper", s.dataset.paper); renderSimpleExports() });
  $$("#simpleExports .exp[data-k]").forEach(b => b.onclick = () => doExport(b.dataset.k));
  $("#instrCard").onclick = () => { pane.classList.add("showsteps"); $("#sewsteps").scrollIntoView({behavior: "smooth", block: "start"}) };
  $("#moreFormats").onclick = () => { const on = pane.classList.toggle("showmore"); $("#moreFormats").textContent = on ? "Fewer formats ◂" : "More formats ▸" };
}
const EXPORT_GROUPS = [["Print it", ["pdf_letter", "pdf_a4", "projector", "layout"]], ["Cut it", ["dxf", "dxf_laser", "aama"]],
  ["3D &amp; photos", ["glb", "obj", "blender"]], ["For a maker", ["techpack"]], ["Project file", ["spec"]]];
$("#srGo").onclick = () => doExport("sizes_" + $("#srTable").value, {paper: $("#srPaper").value, units: ST.units});
$("#bedGo").onclick = () => { LS.set("bed", [$("#bedW").value, $("#bedH").value]);
  doExport("laser_nest", {bed_w: parseFloat($("#bedW").value), bed_h: parseFloat($("#bedH").value), garments: parseInt($("#bedN").value) || 1}) };
{ const b = LS.get("bed", null); if (b) { $("#bedW").value = b[0]; $("#bedH").value = b[1] } }
// ---- cost & price: materials from the server, prices from you (kept in this browser)
const PRICE_DEFAULTS = {fabric: 8, lining: 6, rib: 10, interfacing: 3, elastic: 0.6, thread: 3, hour: 20, profit: 10, ads: 0,
  buttons: 0.3, snaps: 0.4, zipper: 2.5, hook_loop: 3};
async function renderCost() {
  const P = {...PRICE_DEFAULTS, ...LS.get("prices", {})};
  let M;
  try { M = await api("/api/costing", {avatar: ST.avatar.id, ...garmentReq(), seam_allowance_cm: ST.sa}) } catch (e) { $("#costBody").textContent = e.message; return }
  const fabLine = f => { const isL = /lining/.test(f.fabric), isR = /rib/.test(f.fabric); const k = isL ? "lining" : isR ? "rib" : "fabric";
    return {label: `${f.fabric === "main" ? "Main fabric" : f.fabric} (${f.pieces.length} pcs)`, qty: f.yards, unit: "yd", price: P[k], key: k} };
  const lines = [...M.fabrics.map(fabLine),
    ...Object.entries(M.interfacing_cm2).map(([k, a]) => ({label: `Interfacing (${k})`, qty: +(a / (YD2_CM2)).toFixed(2), unit: "yd", price: P.interfacing, key: "interfacing"})),
    ...(M.elastic_cm ? [{label: "Elastic", qty: +(M.elastic_cm / 91.44).toFixed(2), unit: "yd", price: P.elastic, key: "elastic"}] : []),
    ...(M.notions || []).map(n => n.type === "hook_loop" ? {label: n.label, qty: +(n.length_cm / 91.44).toFixed(2), unit: "yd", price: P.hook_loop, key: "hook_loop"}
      : {label: n.label, qty: n.qty, unit: n.type === "zipper" ? "" : "", price: P[n.type], key: n.type}),
    {label: `Thread (${M.thread_m} m)`, qty: +(M.thread_m / 457).toFixed(2), unit: "spool", price: P.thread, key: "thread"},
    {label: `Sewing time (~${M.minutes} min)`, qty: +(M.minutes / 60).toFixed(2), unit: "h", price: P.hour, key: "hour"}];
  const cost = lines.reduce((a, l) => a + l.qty * l.price, 0);
  const pct = 0.065 + 0.03 + (+P.ads) / 100, fixed = 0.45, price = (cost + (+P.profit) + fixed) / (1 - pct), fees = price * pct + fixed;
  $("#costBox").hidden = false;     // shown once it has something to show
  $("#costBody").innerHTML = `<table><tr><th>Item</th><th class="num">Qty</th><th class="num">$ per</th><th class="num">$</th></tr>` +
    lines.map(l => `<tr><td>${l.label}</td><td class="num">${l.qty} ${l.unit}</td><td class="num"><input data-pk="${l.key}" value="${P[l.key]}" style="width:56px;text-align:right;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink)"></td><td class="num">${(l.qty * l.price).toFixed(2)}</td></tr>`).join("") +
    `<tr><td><b>Cost to make</b></td><td></td><td></td><td class="num"><b>${cost.toFixed(2)}</b></td></tr></table>
    <div class="grid2" style="margin-top:8px"><label class="f">Profit you want ($)<input type="text" data-pk="profit" value="${P.profit}"></label>
    <label class="f">Offsite Ads (%)<select data-pk="ads"><option value="0">none</option><option value="12">12%</option><option value="15">15%</option></select></label></div>
    <div class="stat" style="margin-top:8px"><small>Etsy price</small><span class="big">$${price.toFixed(2)}</span><small>Etsy fees $${fees.toFixed(2)} (listing $0.20, 6.5% transaction, 3% + $0.25 processing${+P.ads ? `, ${P.ads}% Offsite Ads` : ""}) · you keep $${(price - fees - cost + (+P.hour) * (M.minutes / 60)).toFixed(2)} incl. your time</small></div>
    <small style="color:var(--muted)">Selling the PDF pattern instead? No materials or sewing: $${((+P.profit + fixed) / (1 - pct)).toFixed(2)} keeps you $${(+P.profit).toFixed(2)} per sale.</small>`;
  $("#costBody select[data-pk=ads]").value = String(P.ads);
  $$("#costBody [data-pk]").forEach(inp => inp.onchange = () => { const Q = LS.get("prices", {}); Q[inp.dataset.pk] = parseFloat(inp.value) || 0; LS.set("prices", Q); renderCost() });
}
const YD2_CM2 = 91.44 * 112;   // a yard of 45" interfacing
// ---- turntable video: spin the 3D view and record the canvas
$("#vidGo").onclick = async () => {
  if (!ST.drape) { toast("Drape it first (Try on)"); return }
  go("preview"); await new Promise(r => setTimeout(r, 300));
  const cv = GL.canvas, types = ["video/mp4;codecs=avc1", "video/mp4", "video/webm;codecs=vp9", "video/webm"];
  const mime = types.find(t => window.MediaRecorder && MediaRecorder.isTypeSupported(t));
  if (!mime) { toast("This browser can't record video"); return }
  const rec = new MediaRecorder(cv.captureStream(30), {mimeType: mime, videoBitsPerSecond: 6e6}), chunks = [];
  rec.ondataavailable = e => e.data.size && chunks.push(e.data);
  const done = new Promise(r => rec.onstop = r);
  const y0 = GL.state.yaw, t0 = performance.now(), T = 6000;
  rec.start(); $("#player").style.display = "none";
  await new Promise(res => { const step = () => { const u = (performance.now() - t0) / T; GL.setView({yaw: y0 + u * 2 * Math.PI}); if (u < 1) requestAnimationFrame(step); else res() }; requestAnimationFrame(step) });
  rec.stop(); await done;
  const ext = mime.includes("mp4") ? "mp4" : "webm";
  download(new Blob(chunks, {type: mime.split(";")[0]}), `${garmentName().replace(/\s+/g, "_")}_turntable.${ext}`);
  toast(`Saved a ${ext.toUpperCase()} video` + (ext === "webm" ? " (convert to MP4 for Etsy with any free converter)" : ""), 5000);
  if (PL.rest) $("#player").style.display = "flex";
};
async function renderExport() {
  syncMultiOpts();
  if (ST.scratch && !ST.sfull) {
    $("#exports").innerHTML = `<p class="lead">Working out fabric and steps…</p>`;
    try { ST.sfull = await api("/api/scratch", {avatar: ST.avatar.id, design: serverDesign(), full: true}) } catch (e) { $("#exports").innerHTML = `<div class="err">${e.message}</div>`; return }
    if (ST.sfull.error) { $("#exports").innerHTML = `<div class="err">${ST.sfull.error}</div>`; ST.sfull = null; return }
  }
  const d = ST.scratch ? ST.sfull : ST.draft; if (!d) return;
  renderCost();
  $("#sav").textContent = fmtLen(ST.sa);
  const y = d.yardage;
  const card = (w, lbl) => y[w] && !y[w].error ? `<div class="stat"><small>${lbl}</small><span class="big">${ST.units === "in" ? fracYd(y[w].yards) + " yd" : y[w].metres.toFixed(1) + " m"}</span><small>${ST.units === "in" ? y[w].metres.toFixed(1) + " m" : fracYd(y[w].yards) + " yd"} · ${y[w].efficiency}% used</small></div>` : "";
  $("#yard").innerHTML = `<div style="width:100%"><h3>Fabric to buy</h3></div>` + card("150", ST.units === "in" ? '60" wide fabric' : "150 cm wide") + card("112", ST.units === "in" ? '45" wide fabric' : "112 cm wide");
  // grouped by what you are doing with it
  const expCard = ([k, t, s, needsDrape]) => `<button class="exp" data-k="${k}" ${needsDrape && !ST.drape ? "disabled title='Drape it first'" : ""}><b>${t}</b><small>${s}</small></button>`;
  $("#exports").innerHTML = EXPORT_GROUPS.map(([title, keys]) => `<div class="expgroup"><h3>${title}</h3><div class="exports">${
    EXPORTS.filter(e => keys.includes(e[0])).map(expCard).join("")}</div></div>`).join("");
  $$("#exports .exp").forEach(b => b.onclick = () => doExport(b.dataset.k));
  renderSimpleExports();
  $("#steplist").innerHTML = d.instructions.map(s => `<li><div><b>${s.title}</b><div>${s.text}</div></div></li>`).join("");
}
function fracYd(y) { const w = Math.floor(y), f = Math.round((y - w) * 8); const F = ["", "⅛", "¼", "⅜", "½", "⅝", "¾", "⅞"]; return (w || !f ? w : "") + F[f] }
// what an export needs from one garment (built while it's the active one: withGarment)
function exportReq(kind, extra) {
  return {avatar: ST.avatar.id, ...garmentReq(), kind, seam_allowance_cm: ST.sa, job: activeGarment().drapeJob || ST.job, fabric_width_cm: 150,
    fabric: ST.fabric, units: ST.units, title: ST.scratch ? (ST.design.from_starter && (ST.init.starters.find(x => x.key === ST.design.from_starter) || {}).label) || "My design" : undefined, ...extra};
}
const THREE_D = ["glb", "blender", "obj"];
const multi = () => PROJECT.garments.length > 1;
async function doExport(kind, extra = {}) {
  if (kind === "spec") return saveFile(false);
  toast("Preparing your file…");
  // patterns for every garment (one file each, named after it); 3D files for the whole outfit
  const every = multi() && $("#allGarments").checked && !THREE_D.includes(kind) && !kind.startsWith("sizes_") && kind !== "techpack";
  const list = every ? PROJECT.garments.filter(g => g.block || g.scratch) : [activeGarment()];
  for (const g of list) {
    try {
      const body = withGarment(g, () => exportReq(kind, extra));
      if (multi() && $("#outfit3d").checked && THREE_D.includes(kind))
        body.outfit = PROJECT.garments.filter(x => x !== g && x.visible && x.drape && (x.drapeJob || x.job)).map(x => ({job: x.drapeJob || x.job, fabric: x.fabric, name: x.name}));
      const r = await api("/api/export", body);
      let name = (r.headers.get("Content-Disposition") || "").match(/filename="(.+)"/)?.[1] || kind;
      if (multi()) name = `${safeName(g.name) || "garment"} - ${name}`;
      download(await r.blob(), name); toast("Downloaded " + name);
    } catch (e) { toast(`Export failed${multi() ? " for " + g.name : ""}: ${e.message}`, 5000) }
  }
}
function syncMultiOpts() {
  $("#multiOpts").hidden = !multi();
  $("#multiActive").textContent = activeGarment().name;
}
function download(blob, name) { const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove() }, 1000) }
// ------------------------------------------------------------ File: save and open .drape files
// A .drape file is the project as JSON (measurements, garment or design, every setting),
// marked {format: "drape-project"}. Where the browser can (Chrome, Edge), Save opens the
// system's save window and later saves go back to the same file; elsewhere it downloads.
// Older project .json files open too.
const DRAPE_TYPES = [{description: "Spunfection Studio project", accept: {"application/json": [".drape"]}}];
let fileHandle = null;
const safeName = s => (s || "").replace(/[^\w\- ]+/g, "_").trim();
function projectName() { return ST.name || (ST.scratch ? "my_design" : ST.block ? ST.block.replace(/_/g, " ") : "my_project") }
function drapeFile() { return JSON.stringify({format: "drape-project", app: BRAND.app, app_version: (ST.init && ST.init.version) || undefined, saved: new Date().toISOString(), ...project(), name: projectName()}, null, 2) }
async function saveFile(saveAs) {
  const name = (safeName(projectName()) || "my_design") + ".drape", blob = new Blob([drapeFile()], {type: "application/json"});
  if (window.showSaveFilePicker) {
    try {
      if (!fileHandle || saveAs) fileHandle = await showSaveFilePicker({suggestedName: name, types: DRAPE_TYPES});
      const w = await fileHandle.createWritable(); await w.write(blob); await w.close();
      ST.name = fileHandle.name.replace(/\.drape$/i, ""); autosave(); toast("Saved " + fileHandle.name); return true;
    } catch (e) { if (e.name === "AbortError") return false; fileHandle = null }    // cancelled; or not allowed here: download it
  }
  download(blob, name); toast("Downloaded " + name); return true;
}
async function openText(text, fname) {
  let p; try { p = JSON.parse(text) } catch (e) { throw new Error("it isn't a Spunfection Studio project file") }
  if (p && p.type === "garment") { await importGarment(p); toast("Added " + activeGarment().name + " to this project"); return }
  if (!p || typeof p !== "object" || (p.format && p.format !== "drape-project") || !(p.measurements || p.design || p.garments || p.avatar)) throw new Error("it isn't a Spunfection Studio project file");
  await openProject(p); ST.name = (typeof p.name === "string" && cleanFile(p.name)) || cleanFile(fname.replace(/\.(drape|json)$/i, "")); autosave();
  const miss = [...new Set(cleanGarment.dropped)];
  toast("Opened " + fname + (miss.length ? `. This copy doesn't have the ${miss.join(", ")}: picked the nearest it has` : ""), miss.length ? 7000 : 2600);
}
async function openFile() {
  if (window.showOpenFilePicker) {
    try {
      const [h] = await showOpenFilePicker({types: [{description: "Spunfection Studio project", accept: {"application/json": [".drape", ".json", ".garment"]}}]});
      await openText(await (await h.getFile()).text(), h.name); fileHandle = /\.drape$/i.test(h.name) ? h : null; return;
    } catch (e) { if (e.name === "AbortError") return; if (!/SecurityError|NotAllowedError/.test(e.name)) { toast("Couldn't open that file: " + e.message, 5000); return } }
  }
  $("#openproj").click();
}
function fileWindow() {
  const picker = !!window.showSaveFilePicker;
  modal("File", `<div style="display:grid;gap:12px;max-width:480px">
    <label class="f">Project name<input type="text" id="fwName" value="${projectName().replace(/[&<>"]/g, c => `&#${c.charCodeAt(0)};`)}"></label>
    <div class="row" style="flex-wrap:wrap;gap:8px">
      <button class="btn primary" id="fwSave">💾 Save</button>
      ${picker ? `<button class="btn" id="fwSaveAs">Save as…</button>` : ""}
      <button class="btn" id="fwOpen">📂 Open…</button></div>
    ${fileHandle ? `<small style="color:var(--muted)">Saving to <b>${fileHandle.name}</b></small>` : ""}
    <p class="lead" style="font-size:13px;margin:0">A <b>.drape</b> file keeps your measurements, the garment or your own design, and every setting.
      ${picker ? "Save asks where to put it the first time, then saves to the same file." : "Save downloads it (look in your Downloads folder)."}
      Open a .drape file (or an older project .json) to pick up where you left off.</p>
    <small style="color:var(--muted)">Ctrl+S saves · Ctrl+O opens · your last project is also kept in this browser</small>
    ${ST.scratch ? `<div class="row" style="gap:8px;border-top:1px solid var(--line);padding-top:10px"><span style="flex:1;font-size:13px">Start this design over:</span>
      <button class="btn small" id="fwExample">Gathered skirt example</button><button class="btn small" id="fwClear">Empty board</button></div>` : ""}</div>`);
  // Start over lives here too (the Design toolbar's copy is Advanced only)
  if ($("#fwExample")) { $("#fwExample").onclick = () => { $("#modal").classList.remove("show"); $("#dsExample").click() };
                         $("#fwClear").onclick = () => { $("#modal").classList.remove("show"); $("#dsClear").click() } }
  const nm = () => { const v = $("#fwName").value.trim(); if (v !== projectName()) { ST.name = v; fileHandle = null; autosave() } };
  $("#fwSave").onclick = async () => { nm(); if (await saveFile(false)) $("#modal").classList.remove("show") };
  if ($("#fwSaveAs")) $("#fwSaveAs").onclick = async () => { nm(); if (await saveFile(true)) $("#modal").classList.remove("show") };
  $("#fwOpen").onclick = () => { $("#modal").classList.remove("show"); openFile() };
}
$("#fileBtn").onclick = fileWindow;
// New: a clean project. It warns first (nothing tracks unsaved changes, so it always asks) and
// offers to save. Your measurements stay (they're you, not the project); the garment, design,
// name and undo history go. The page reloads, so every panel starts clean.
function startNew() {
  LS.set("project", {version: 2, name: "", avatar: {measurements: ST.meas}, scene: {units: ST.units}, garments: []}); LS.set("newProject", 1);
  fileHandle = null; setTimeout(() => location.reload(), 400);   // a download-style save gets to finish first
}
function newWindow() {
  modal("Start a new project?", `<div style="display:grid;gap:12px;max-width:560px">
    <p style="margin:0;padding:10px 12px;border-radius:10px;background:var(--warn-soft);font-size:14px"><b>⚠ Save first?</b> Anything you haven't saved to a
      .drape file will be lost: the garment, your design and your changes. Your measurements stay.</p>
    <div class="row" style="flex-wrap:wrap;gap:8px">
      <button class="btn primary" id="nwSave">💾 Save, then start new</button>
      <button class="btn danger" id="nwGo">Start new without saving</button>
      <button class="btn" id="nwCancel">Cancel</button></div></div>`);
  $("#nwSave").onclick = async () => { if (await saveFile(false)) startNew() };
  $("#nwGo").onclick = startNew;
  $("#nwCancel").onclick = () => $("#modal").classList.remove("show");
}
$("#newBtn").onclick = newWindow;
addEventListener("keydown", e => {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return; const k = e.key.toLowerCase();
  if (k === "s") { e.preventDefault(); saveFile(e.shiftKey) } else if (k === "o") { e.preventDefault(); openFile() }
});
$("#saveproj").onclick = () => saveFile(false);
$("#openproj").onchange = async e => {
  const f = e.target.files[0]; if (!f) return; e.target.value = "";
  try { await openText(await f.text(), f.name) } catch (err) { toast("Couldn't open that file: " + err.message, 5000) }
};
async function openProject(p) {
  p = migrateProject(p);                      // version 1 files open as a one-garment project
  ST.meas = (p.avatar && p.avatar.measurements) || {}; loadGarments(p);
  if (p.scene && p.scene.units && p.scene.units !== ST.units) $(`#units button[data-u="${p.scene.units}"]`).click();
  renderMeasFields(); renderFabrics(); if (typeof renderGarmentList === "function") renderGarmentList();
  await buildAvatar();
  if (ST.block || ST.scratch) { renderGarments(); go("fit"); await redraft(); pushHist() }
  else if (ST.step !== "body") { renderGarments(); go("garment") }    // no pattern yet: the picker (not the last project's panel)
}
// ---- one garment on its own: {type: "garment", version: 2, garment: {...}}, to move a garment between projects
function garmentFile(g) {
  return JSON.stringify({type: "garment", version: 2, app: BRAND.app, app_version: (ST.init && ST.init.version) || undefined,
                         saved: new Date().toISOString(), garment: garmentData(g)}, null, 2);
}
function exportGarment(g = activeGarment()) {
  download(new Blob([garmentFile(g)], {type: "application/json"}), (safeName(g.name) || "garment") + ".garment");
  toast("Exported " + g.name);
}
// an imported garment gets a fresh id and goes on the next free layer, and becomes the one you work on
async function importGarment(file) {
  if (!file.garment || typeof file.garment !== "object") throw new Error("that garment file is empty");
  cleanGarment.dropped = []; const d = cleanGarment(file.garment, PROJECT.garments.length);
  const top = Math.max(0, ...PROJECT.garments.map(g => g.layer));
  const g = newGarment(d.name, {...d, id: uid(), layer: top + 1, frozen: false, frozenMesh: undefined,
    choices: d.choices || {}, params: d.params || {}, scratch: !!d.scratch, design: d.design || {pieces: [], seams: []},
    fabric: d.fabric || "jersey", print: d.print || "none", printCm: d.printCm || 8});
  PROJECT.garments.push(g); setActiveGarment(g.id); pushHist();
  if (!ST.scratch && ST.block) await redraft();
}

