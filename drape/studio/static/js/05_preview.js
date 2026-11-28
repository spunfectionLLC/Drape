// drape studio: step 4: draping, live mode, prints, fit advice, move tests
// (classic script: shares one global scope with the others, loaded in order by index.html)
// ======================================================== 4. preview / drape
function renderFabrics() {
  if (window.GL && GL.setMaterial) GL.setMaterial(ST.fabric);
  // Simple mode: five common fabrics (plus yours and the chosen one); "More fabrics" shows the rest
  const COMMON = ["jersey", "poplin", "denim", "fleece", "rib"];
  $("#fabrics").innerHTML = ST.init.fabrics.map(f => `<button class="chip ${ST.fabric === f.key ? "on" : ""} ${COMMON.includes(f.key) || f.mine || ST.fabric === f.key ? "" : "extra"}" data-f="${f.key}" title="${f.gsm} g/m²">${f.mine ? "★ " : ""}${f.name}</button>`).join("")
    + `<button class="chip begi" id="moreFabrics">More fabrics ▸</button>`
    + `<button class="chip" id="myFabric" title="Measure a fabric you have: three quick tests">+ My fabric</button>`;
  $("#myFabric").onclick = myFabricModal;
  $("#moreFabrics").onclick = () => { const all = $("#fabrics").classList.toggle("all"); $("#moreFabrics").textContent = all ? "Fewer fabrics ◂" : "More fabrics ▸" };
  $$("#fabrics .chip[data-f]").forEach(c => c.onclick = () => { ST.fabric = c.dataset.f; ST.drape = null; renderFabrics(); autosave(); if (LIVE.sim) startLive(true) });
}
$("#secs").oninput = e => $("#secv").textContent = e.target.value + " s";
// ---- live GPU drape: the cloth moves while you watch, and you can pull it with the mouse
const LIVE = {sim: null, run: false, fps: 0, starting: false, all: false};   // all: every unfrozen garment moves (off until the layers start apart)
async function startLive(keep = false) {
  if (LIVE.starting) return;
  if (activeGarment().frozen) { toast(`${activeGarment().name} is frozen: unfreeze it (❄ in Garments) to move it again`, 4000); return }
  if (!(window.LiveSprings && await LiveSprings.supported())) {
    toast("Live mode needs a browser with WebGPU (Chrome or Edge 113+, Safari 26+). The regular Drape works everywhere.", 7000); return }
  LIVE.starting = true;
  const prev = keep && LIVE.sim ? {x: LIVE.sim.out.slice(), uv: LIVE.sim.uv, pid: LIVE.sim.pid, names: LIVE.sim.names, time: LIVE.sim.time} : null;
  stopLive(true);
  $("#liveBar").style.display = ""; $("#liveBar").innerHTML = `<div class="check"><span>Setting up the GPU…</span></div>`;
  try {
    const L = LIVE.all ? liveGarments() : [];     // every visible garment that isn't frozen moves, in one simulation
    const setup = await api("/api/live", {avatar: ST.avatar.id, ...(L.length > 1 ? {garments: L.map(g => ({...withGarment(g, garmentReq), fabric: g.fabric, name: g.name}))} : garmentReq()),
      fabric: ST.fabric, quality: ST.quality, ...colliderReq(PROJECT.activeGarmentId)});
    LIVE.gids = L.length > 1 ? L.map(g => g.id) : [];      // their still drapes are hidden while they move
    if (typeof refreshScene === "function") refreshScene();
    const sim = await new LiveSprings().init(setup);
    // several garments: the outer ones start a little stretched round the inner ones and pull in fast on the first
    // frame; planned from rest (speed 0) the contacts didn't look far enough and the layers went through each other
    // (1,350 crossings after frame 1). Planned as if at the speed cap, the first frames take more substeps.
    if (L.length > 1) { sim.startSpeed = sim.vClamp; sim.vMeasured = sim.startSpeed }
    sim.uv = b64(setup.uv, Float32Array); sim.pid = b64(setup.panel_id, Uint32Array); sim.names = setup.panel_names;
    if (prev && prev.uv) {
      const X = sim.out.slice(), n = sim.n; let matched = 0, newPieces = 0;
      for (let k = 0; k < sim.names.length; k++) {
        const ok = prev.names.indexOf(sim.names[k]); if (ok < 0) { newPieces++; continue }
        const olds = []; for (let j = 0; j < prev.pid.length; j++) if (prev.pid[j] === ok) olds.push(j);
        // the piece hangs from its top: keep heights measured down from the top, spread
        // widths in proportion; anything below the old hem hangs straight down from it
        const box = (uv, ids) => { let a = [1e9, 1e9], b = [-1e9, -1e9]; for (const j of ids) for (let q = 0; q < 2; q++) { a[q] = Math.min(a[q], uv[2 * j + q]); b[q] = Math.max(b[q], uv[2 * j + q]) } return [a, b] };
        const news = []; for (let i = 0; i < n; i++) if (sim.pid[i] === k) news.push(i);
        const [oa, ob] = box(prev.uv, olds), [na, nb] = box(sim.uv, news);
        const ow = Math.max(ob[0] - oa[0], 1e-6), nw = Math.max(nb[0] - na[0], 1e-6);
        for (const i of news) {
          const u = oa[0] + (sim.uv[2 * i] - na[0]) / nw * ow;
          let v = ob[1] - (nb[1] - sim.uv[2 * i + 1]), drop = 0;
          if (v < oa[1]) { drop = oa[1] - v; v = oa[1] }
          let best = -1, bd = 1e9;
          for (const j of olds) { const d = (prev.uv[2 * j] - u) ** 2 + (prev.uv[2 * j + 1] - v) ** 2; if (d < bd) { bd = d; best = j } }
          if (best >= 0) { X[3 * i] = prev.x[3 * best]; X[3 * i + 1] = prev.x[3 * best + 1] - drop; X[3 * i + 2] = prev.x[3 * best + 2]; matched++; continue }
        }
      }
      sim.dev.queue.writeBuffer(sim.X, 0, X); sim.out.set(X);
      sim.time = newPieces ? 0 : Math.max(prev.time, sim.prm.sew_time + sim.prm.gravity_ramp);
    }
    LIVE.sim = sim; LIVE.run = true; ST.drape = null; GL.setTrims(null);
    const C = b64(setup.colors, Uint8Array), cols = new Float32Array(C.length); for (let i = 0; i < C.length; i++) cols[i] = C[i] / 255;
    GL.setClothRaw(sim.out.slice(), b64(setup.tris, Uint32Array), cols, !keep);
    $("#liveBtn").textContent = "■ Stop"; $("#liveBtn").classList.add("primary");
    let plane = null;
    GL.setGrab({
      down(cx, cy) { const h = GL.pick(cx, cy, "cloth"); if (!h) return false; const r = GL.ray(cx, cy);
        plane = {p: h.point, n: r.d}; sim.setGrab(h.vertex, h.point); return true },
      move(cx, cy) { if (!plane) return; const r = GL.ray(cx, cy), dn = r.d[0] * plane.n[0] + r.d[1] * plane.n[1] + r.d[2] * plane.n[2]; if (Math.abs(dn) < 1e-6) return;
        const t = ((plane.p[0] - r.eye[0]) * plane.n[0] + (plane.p[1] - r.eye[1]) * plane.n[1] + (plane.p[2] - r.eye[2]) * plane.n[2]) / dn;
        sim.setGrab(sim.grab, [r.eye[0] + r.d[0] * t, r.eye[1] + r.d[1] * t, r.eye[2] + r.d[2] * t]) },
      up() { plane = null; sim.setGrab(-1) },
    });
    let frames = 0, t0 = performance.now();
    const loop = async () => {
      if (!LIVE.run || LIVE.sim !== sim) return;
      const out = await sim.step(1);
      if (out && LIVE.sim === sim) { GL.move("cloth", out.slice()); frames++ }
      const now = performance.now();
      if (now - t0 > 700) { LIVE.fps = frames * 1000 / (now - t0); frames = 0; t0 = now; liveStatus() }
      if (sim.lost) { toast("The GPU stopped (driver reset). Press Live again.", 6000); stopLive(); return }
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
    liveStatus();
  } catch (e) { toast("Live mode couldn't start: " + e.message, 7000); stopLive() }
  finally { LIVE.starting = false }
}
function liveStatus() {
  const s = LIVE.sim; if (!s) return;
  const t = s.time, st = s.stages || [[0, s.prm.sew_time]], last = st[st.length - 1];
  const settling = t < last[0] + last[1] + s.prm.gravity_ramp + 0.5;
  // staged sewing: which stage it's on (the body first, then hood / cuffs / pockets)
  const ph = s.phase ? s.phase() : null, staged = st.length > 1;
  const what = staged && settling ? `: <span id="liveStage">${ph[2]}</span> (stage ${ph[0]} of ${st.length})` : settling ? ": sewing and settling…" : "";
  const many = LIVE.gids && LIVE.gids.length > 1 ? ` · ${LIVE.gids.length} garments` : "";
  $("#liveBar").innerHTML = `<div class="check ok"><span><b>Live${what}</b>${many} ${LIVE.fps.toFixed(0)} frames/s · ${(LIVE.fps / s.prm.fps * 100).toFixed(0)}% of real time · ${s.n.toLocaleString()} points${s.adapterInfo ? " · " + s.adapterInfo : ""}
    · <span id="liveSub" style="${s.substeps > s.base ? "color:#c7801a;font-weight:600" : ""}" title="Steps per frame: more while the cloth moves fast, so layers can't pass through each other">${s.substeps} substeps</span>${s.speedLimited ? ` · <b style="color:#c7801a">slowed to stay untangled</b>` : ""}<br>
    <small>Drag the cloth to pull it; shift-drag turns the view. Switch fabrics on the fly. Live is a quick preview: press <b>Drape it</b> for the accurate result and the fit check.</small></span></div>
    <div class="row" style="gap:6px;margin-top:6px"><button class="btn small" id="liveReset">Start over</button></div>`;
  $("#liveReset").onclick = () => { s.reset(); GL.move("cloth", s.out.slice()) };
}
function stopLive(quiet) {
  LIVE.run = false; if (LIVE.sim) { LIVE.sim.destroy(); LIVE.sim = null }
  if (LIVE.gids && LIVE.gids.length) { LIVE.gids = []; if (typeof refreshScene === "function") refreshScene() }
  GL.setGrab(null); $("#liveBtn").textContent = "⚡ Live"; $("#liveBtn").classList.remove("primary");
  if (!quiet) $("#liveBar").style.display = "none";
}
$("#liveBtn").onclick = () => LIVE.sim ? stopLive() : startLive();
ST.quality = "quick"; ST.pose = null;
$("#quality").onclick = e => { const q = e.target.dataset.q; if (!q) return; ST.quality = q; $$("#quality button").forEach(b => b.classList.toggle("on", b.dataset.q === q)) };
const POSE_LIST = [["", "None"], ["sit", "Sitting"], ["walk", "Walking"], ["reach_up", "Arms up"], ["reach_forward", "Reaching forward"]];
function renderPoses() {
  if (ST.init && ST.init.web) {   // the website: poses need the moving body on the GPU (not there yet)
    ST.pose = null; $("#poses").innerHTML = `<small style="color:var(--muted)">Move tests (sitting, walking…) are in the desktop app for now; they're coming to the web version.</small>`; return }
  $("#poses").innerHTML = POSE_LIST.map(([k, l]) => `<button class="chip ${(ST.pose || "") === k ? "on" : ""}" data-p="${k}">${l}</button>`).join("");
  $$("#poses .chip").forEach(c => c.onclick = () => { ST.pose = c.dataset.p || null; renderPoses() });
}
renderPoses();
$("#drapeBtn").onclick = startDrape;
// Live moves every visible garment that isn't frozen, inner layer first (the order set in Garments)
function liveGarments() { return PROJECT.garments.filter(g => g.visible && !g.frozen && (g.block || g.scratch)).sort((a, b) => a.layer - b.layer) }
function garmentReq() { return ST.scratch ? {design: serverDesign(), title: "My design"} : {block: ST.block, choices: ST.choices, params: ST.params} }
// multi-garment, phase 4: the frozen, visible garments the cloth collides with (as the body: colliders.py), and a
// way to build another garment's request without switching to it on screen
function colliderReq(except) {
  const c = PROJECT.garments.filter(g => g.id !== except && g.visible && g.frozen && g.frozenMesh).map(g => ({v: g.frozenMesh.v, f: g.frozenMesh.f}));
  return c.length ? {colliders: c} : {};
}
function withGarment(g, f) { const was = PROJECT.activeGarmentId; PROJECT.activeGarmentId = g.id; try { return f() } finally { PROJECT.activeGarmentId = was } }
// the other visible garments that aren't frozen drape too, one after another, each against the body and the frozen
// ones (not against each other yet: the notice says so)
async function drapeOthers(done) {
  for (const x of PROJECT.garments.filter(x => x !== done && x.visible && !x.frozen && (x.block || x.scratch))) {
    if (x.draping || !PROJECT.garments.includes(x)) continue;       // its own drape is running; or it was deleted
    x.draping = true; syncTryOn();
    try {
      const {job} = await api("/api/drape", {avatar: ST.avatar.id, ...withGarment(x, garmentReq), fabric: x.fabric, seconds: +$("#secs").value,
        quality: ST.quality, ...colliderReq(x.id)});
      x.job = job;
      for (;;) { await new Promise(r => setTimeout(r, 600)); const j = await api("/api/job/" + job);
        if (j.state === "running") continue;
        if (j.state === "done") { x.drape = j; x.drapeJob = job; if (x === activeGarment()) showDrape(); else refreshScene() }
        else if (j.state === "error") throw new Error(j.error.split("\n")[0]);
        break }
    } catch (e) { toast(`${x.name} couldn't be draped: ${e.message}`, 4000) }
    finally { x.draping = false; syncTryOn() }
  }
}
const garmentName = () => ST.scratch ? "Your design" : blockInfo().label;
async function startDrape() {
  if (matchMedia("(max-width: 640px)").matches) $("#glcard").scrollIntoView({behavior: "smooth", block: "start"});   // phone: watch it fall
  if (LIVE.sim) stopLive();
  if (!ST.avatar || (!ST.block && !ST.scratch)) return;
  if (activeGarment().frozen) { toast(`${activeGarment().name} is frozen: unfreeze it (❄ in Garments) to drape it again`, 4000); return }
  // the drape belongs to this garment, even if another is picked while it runs; "busy" is per garment, so the
  // button works for another garment meanwhile, and the progress shows only on this one
  const g = activeGarment(); if (g.draping) return;
  // several visible garments that aren't frozen (desktop): one drape, layered by simulation, inner layer first
  const together = ST.init && !ST.init.web && !ST.pose ? liveGarments() : [];
  if (together.length > 1 && together.includes(g)) return drapeTogether(together);
  g.draping = true; syncTryOn(); $("#advice").innerHTML = ""; GL.overlay("Sewing the pieces…", "", 0);
  const mine = () => g === activeGarment();
  let drapedNow = false;
  try {
    stopPlayer();
    const {job} = await api("/api/drape", {avatar: ST.avatar.id, ...garmentReq(), fabric: ST.fabric, seconds: +$("#secs").value,
      quality: ST.quality, pose: ST.pose || undefined, ...colliderReq(g.id)});
    g.job = job;
    // `drawn`: the 3D view holds this job's cloth (so a positions-only frame can move it). A garment switch
    // replaces the view's cloth; coming back redraws it from the last full frame's triangles.
    let drawn = false, full = null, seen = GARMENT_SWITCHES;
    for (;;) {
      await new Promise(r => setTimeout(r, 450));
      const j = await api("/api/job/" + job);
      if (seen !== GARMENT_SWITCHES) { drawn = false; seen = GARMENT_SWITCHES }
      if (j.state === "running") {
        if (j.frame && j.frame.f) full = {f: j.frame.f, panel: j.frame.panel};
        if (j.frame && mine()) {     // watch it fall into place
          if (j.frame.f || (!drawn && full)) {
            const pc = b64(full.panel, Uint8Array), cols = new Float32Array(pc.length); for (let i = 0; i < pc.length; i++) cols[i] = pc[i] / 255;
            GL.setColored({v: j.frame.v, f: full.f}, cols); drawn = true;
          } else if (drawn) {
            const P16 = b64(j.frame.v, Int16Array), P = new Float32Array(P16.length); for (let i = 0; i < P.length; i++) P[i] = P16[i] / 1000;
            GL.move("cloth", P);
          }
        }
        if (mine()) {
          if (drawn) { GL.overlay(null); $("#gltitle").textContent = `${j.stage} · ${Math.round(j.progress * 100)}%` }
          else GL.overlay(j.stage, Math.round(j.progress * 100) + "%", j.progress);
        }
        continue;
      }
      if (j.state === "error") throw new Error(j.error.split("\n")[0]);
      g.drape = j; g.drapeJob = job; drapedNow = true;      // the job behind the drape shown (exports read it)
      if (mine()) { PL.vmap = null; showDrape(); renderAdvice(); if (hasLook()) applyPrint(); if (j.pose_anim) startPlayer(j) }
      else refreshScene();
      break;
    }
  } catch (e) {
    if (mine()) GL.overlay("The drape failed", e.message);
    else toast(`${g.name}: the drape failed: ${e.message}`, 5000);
  } finally { g.draping = false; syncTryOn() }
  if (drapedNow) drapeOthers(g);      // only after a drape that worked (a failed one keeps its old result)
}
// several garments in one drape (server._merged_design): they sew one after another in their layer order, each
// over the ones under it (frozen into the collision grid when it starts); then each garment gets its own result
async function drapeTogether(L) {
  if (L.some(x => x.draping)) return;
  L.forEach(x => x.draping = true); syncTryOn(); $("#advice").innerHTML = "";
  const shown = () => L.includes(activeGarment());
  GL.overlay(`Draping ${L.length} garments, inner layer first…`, "", 0);
  try {
    stopPlayer();
    const {job} = await api("/api/drape", {avatar: ST.avatar.id, fabric: ST.fabric, seconds: +$("#secs").value, quality: ST.quality,
      garments: L.map(x => ({...withGarment(x, garmentReq), fabric: x.fabric, name: x.name})), ...colliderReq(null)});
    L.forEach(x => x.job = job);
    let drawn = false, full = null, seen = GARMENT_SWITCHES;
    for (;;) {
      await new Promise(r => setTimeout(r, 450));
      const j = await api("/api/job/" + job);
      if (seen !== GARMENT_SWITCHES) { drawn = false; seen = GARMENT_SWITCHES }
      if (j.state === "running") {
        if (j.frame && j.frame.f) full = {f: j.frame.f, panel: j.frame.panel};
        if (j.frame && shown()) {            // all of them falling into place, one after another
          if (j.frame.f || (!drawn && full)) {
            const pc = b64(full.panel, Uint8Array), cols = new Float32Array(pc.length); for (let i = 0; i < pc.length; i++) cols[i] = pc[i] / 255;
            GL.setOthers([]); GL.setColored({v: j.frame.v, f: full.f}, cols); drawn = true;
          } else if (drawn) {
            const P16 = b64(j.frame.v, Int16Array), P = new Float32Array(P16.length); for (let i = 0; i < P.length; i++) P[i] = P16[i] / 1000;
            GL.move("cloth", P);
          }
        }
        if (shown()) {
          if (drawn) { GL.overlay(null); $("#gltitle").textContent = `${j.stage} · ${Math.round(j.progress * 100)}%` }
          else GL.overlay(j.stage, Math.round(j.progress * 100) + "%", j.progress);
        }
        continue;
      }
      if (j.state === "error") throw new Error(j.error.split("\n")[0]);
      const ids = j.garment_jobs || [];
      if (ids.length !== L.length) throw new Error("the drape came back without every garment");
      for (let k = 0; k < L.length; k++) {           // each garment's own result (its exports read its job)
        const jj = await api("/api/job/" + ids[k]);
        L[k].drape = jj; L[k].drapeJob = ids[k]; L[k].job = ids[k];
      }
      break;
    }
    PL.vmap = null;
    if (shown()) { showDrape(); renderAdvice(); if (hasLook()) applyPrint() }
    refreshScene();
    toast(`${L.length} garments draped together, inner layer first`, 4000);
  } catch (e) {
    if (shown()) GL.overlay("The drape failed", e.message); else toast(`The drape failed: ${e.message}`, 5000);
  } finally { L.forEach(x => x.draping = false); syncTryOn() }
}
// one primary button on Try on: "Drape it" until there's a drape, then "Looks good → make the pattern"
// ST.gpu known (boot): the note under Drape it, once
function gpuChanged() {
  if (!$("#nogpunote")) $("#drapeBtn").closest(".row").insertAdjacentHTML("afterend", `<small class="layernote" id="nogpunote" hidden>Draping on the website needs a graphics card your browser can use, and this one can't reach it (common on office computers). Try an up-to-date Chrome or Edge, or another computer. Designing, patterns and most exports work here as usual.</small>`);
  syncTryOn();
}
function syncTryOn() {
  const done = !!ST.drape;
  // the website drapes on the graphics card: without one it can use, the button says so instead of failing
  const noGpu = !!(ST.init && ST.init.web && ST.gpu === false);
  $("#drapeBtn").disabled = !!activeGarment().draping || noGpu;     // busy per garment: another one can drape meanwhile
  const nn = $("#nogpunote"); if (nn) nn.hidden = !noGpu;
  $("#drapeBtn").textContent = done ? "Drape again" : "Drape it";
  $("#drapeBtn").classList.toggle("primary", !done);
  $("#toExport").classList.toggle("primary", done);
  if (typeof syncFrozenNotice === "function") syncFrozenNotice();
}
// ---- prints: drawn on a 256 px tile that repeats every ST.printCm on the fabric
ST.print = "none"; ST.printCm = 8; ST.printImg = null;
const PRINTS = [["none", "Solid"], ["stripes", "Stripes"], ["plaid", "Plaid"], ["dots", "Dots"], ["gingham", "Gingham"], ["upload", "Your image…"]];
const LOOK_IMGS = new Map();     // a piece's own image (its data URL) -> a loaded Image
function lookImg(src) {
  if (!LOOK_IMGS.has(src)) { const im = new Image(); im.onload = () => { if (typeof applyPrint === "function") applyPrint() }; im.src = src; LOOK_IMGS.set(src, im) }
  const im = LOOK_IMGS.get(src); return im.complete && im.naturalWidth ? im : null;
}
// one 256 px tile of a look {print, color (the background, or a solid's colour), src (an image)}; the garment's by default
function printTile(L = {print: ST.print}, c = null, ox = 0) {
  if (!c) { c = document.createElement("canvas"); c.width = c.height = 256 }
  const x = c.getContext("2d"); x.save(); x.translate(ox, 0); x.beginPath(); x.rect(0, 0, 256, 256); x.clip();
  const k = L.print, img = k === "upload" ? (L.src ? lookImg(L.src) : ST.printImg) : null;
  x.fillStyle = L.color || (k === "none" ? "#e9e4da" : "#f3efe6"); x.fillRect(0, 0, 256, 256);
  if (img) x.drawImage(img, 0, 0, 256, 256);
  printMotif(x, k); x.restore(); return c;
}
function printMotif(x, k) {
  if (k === "stripes") { x.fillStyle = "#1f3a68"; for (let i = 0; i < 256; i += 64) x.fillRect(i, 0, 26, 256) }
  if (k === "plaid") { x.globalAlpha = .55; x.fillStyle = "#b8322a"; x.fillRect(0, 96, 256, 64); x.fillRect(96, 0, 64, 256);
    x.fillStyle = "#1f3a68"; x.fillRect(0, 20, 256, 14); x.fillRect(20, 0, 14, 256); x.globalAlpha = 1 }
  if (k === "gingham") { x.globalAlpha = .5; x.fillStyle = "#c2343a"; x.fillRect(0, 0, 128, 256); x.fillRect(0, 0, 256, 128); x.globalAlpha = 1 }
  if (k === "dots") { x.fillStyle = "#1f3a68"; for (const [a, b] of [[64, 64], [192, 192]]) { x.beginPath(); x.arc(a, b, 26, 0, 7); x.fill() } }
}
// a piece's own look (Design, its panel), else the garment's print
function hasLook() { return ST.print !== "none" || !!(ST.scratch && ST.design && ST.design.pieces.some(p => p.look)) }
function pieceLook(name) {
  const own = ST.scratch && ST.design && name ? (ST.design.pieces.find(p => p.name === name) || {}).look : null;
  return own ? {cm: ST.printCm, ...own} : {print: ST.print, cm: ST.printCm};
}
function renderPrints() {
  $("#prints").innerHTML = PRINTS.map(([k, l]) => `<button class="chip ${ST.print === k ? "on" : ""}" data-pr="${k}">${l}</button>`).join("");
  $("#printScale").style.display = ST.print === "none" ? "none" : "grid"; $("#prsv").textContent = fmtLen(ST.printCm);
  $$("#prints .chip").forEach(c => c.onclick = () => {
    if (c.dataset.pr === "upload") {
      const inp = document.createElement("input"); inp.type = "file"; inp.accept = "image/*";
      inp.onchange = () => { const f = inp.files[0]; if (!f) return; const im = new Image(); im.onload = () => { ST.printImg = im; ST.print = "upload"; renderPrints(); applyPrint() }; im.src = URL.createObjectURL(f) };
      inp.click(); return;
    }
    ST.print = c.dataset.pr; renderPrints(); applyPrint();
  });
}
$("#prs").oninput = e => { ST.printCm = +e.target.value; $("#prsv").textContent = fmtLen(ST.printCm); applyPrint() };
function applyPrint() {
  if (!ST.drape || !ST.drape.cloth_uv) return;
  if (!hasLook()) { showDrape(); if (PL.rest) showPlayFrame(PL.i); return }
  const C = ST.drape.cloth_uv, uv = b64(C.uv, Float32Array), n = uv.length / 2, t = new Float32Array(uv.length), cl = new Float32Array(n);
  const pid = C.pid ? b64(C.pid, Uint16Array) : new Uint16Array(n), names = C.names || [];
  const looks = (names.length ? names : [null]).map(pieceLook), keys = looks.map(L => JSON.stringify([L.print, L.color || "", L.src ? L.src.length + L.src.slice(-32) : ""]));
  const uniq = [...new Set(keys)], cell = keys.map(k => uniq.indexOf(k));
  const atlas = document.createElement("canvas"); atlas.width = 256 * uniq.length; atlas.height = 256;
  uniq.forEach((k, q) => printTile(looks[keys.indexOf(k)], atlas, 256 * q));
  for (let v = 0; v < n; v++) {               // metres -> repeats (grain runs up the pattern), each piece its own size
    const p = names.length ? Math.min(pid[v], names.length - 1) : 0, s = 100 / (looks[p].cm || ST.printCm);
    t[2 * v] = uv[2 * v] * s; t[2 * v + 1] = uv[2 * v + 1] * s; cl[v] = cell[p];
  }
  GL.setPrint(C, t, atlas, cl, uniq.length);
  $("#fitlegend").style.display = "none";
  if (PL.rest) showPlayFrame(PL.i);       // a move test is showing: keep its frame
}
renderPrints();
// ---- move-test playback: body keyframes blended, cloth frames as recorded
const PL = {on: false, i: 0, raf: 0};
function decode16(s) { const a = b64(s, Int16Array), o = new Float32Array(a.length); for (let i = 0; i < a.length; i++) o[i] = a[i] / 1000; return o }
function startPlayer(j) {
  const A = j.pose_anim; PL.frames = A.frames.map(decode16); PL.body = A.body.map(decode16); PL.t = A.t; PL.keys = A.keys;
  PL.rest = decode16(ST.avatar.mesh.v); PL.n = PL.frames.length; PL.fit = A.fit; PL.i = PL.n - 1;
  $("#player").style.display = "flex"; $("#playPos").max = PL.n - 1; $("#playPos").value = PL.n - 1; showPlayFrame(PL.n - 1);
}
function showPlayFrame(i) {
  PL.i = i; const t = PL.t[i], K = PL.keys, k = Math.min(Math.floor(t * (K.length - 1)), K.length - 2), u = (t - K[k]) / (K[k + 1] - K[k]);
  const a = PL.body[k], b = PL.body[k + 1], B = new Float32Array(a.length); for (let q = 0; q < a.length; q++) B[q] = a[q] + (b[q] - a[q]) * u;
  GL.move("body", B);
  if (hasLook() && ST.drape.cloth_uv) {
    const vm = PL.vmap || (PL.vmap = b64(ST.drape.cloth_uv.vmap, Uint32Array)), F = PL.frames[i], P = new Float32Array(vm.length * 3);
    for (let q = 0; q < vm.length; q++) { P[q * 3] = F[vm[q] * 3]; P[q * 3 + 1] = F[vm[q] * 3 + 1]; P[q * 3 + 2] = F[vm[q] * 3 + 2] }
    GL.move("cloth", P);
  } else GL.move("cloth", PL.frames[i]);
  $("#playLbl").textContent = `${ST.drape.pose.label} ${Math.round(t * 100)}%`;
}
function stopPlayer() { PL.on = false; cancelAnimationFrame(PL.raf); $("#player").style.display = "none"; $("#playBtn").textContent = "▶";
  if (PL.rest) { GL.move("body", PL.rest); PL.rest = null } }
$("#playBtn").onclick = () => {
  PL.on = !PL.on; $("#playBtn").textContent = PL.on ? "❚❚" : "▶"; if (!PL.on) return;
  if (PL.i >= PL.n - 1) PL.i = 0; let last = 0;
  const tick = ts => { if (!PL.on) return; if (ts - last > 50) { last = ts; showPlayFrame(PL.i); $("#playPos").value = PL.i; PL.i++; if (PL.i >= PL.n) { PL.on = false; $("#playBtn").textContent = "▶"; return } } PL.raf = requestAnimationFrame(tick) };
  PL.raf = requestAnimationFrame(tick);
};
$("#playPos").oninput = e => { PL.on = false; $("#playBtn").textContent = "▶"; showPlayFrame(+e.target.value) };
function showDrape() {
  if (!activeGarment().visible) { showAvatarOnly(); return }
  const c = ST.drape.cloth; GL.setTrims(ST.drape.trims); GL.setCloth(c, ST.colorby); GL.overlay(null); $("#gltitle").textContent = garmentName() + " on your avatar";
  refreshScene();
  $("#colorby").style.display = document.body.classList.contains("advanced") ? "inline-flex" : "none";
  $("#fitlegend").style.display = ST.colorby === "fit" ? "flex" : "none";
}
function showAvatarOnly() { GL.setTrims(null); GL.setCloth(null); $("#gltitle").textContent = "Avatar"; $("#fitlegend").style.display = "none"; $("#colorby").style.display = "none"; refreshScene() }
$("#colorby").onclick = e => { const c = e.target.dataset.c; if (!c || !ST.drape) return; ST.colorby = c; $$("#colorby button").forEach(b => b.classList.toggle("on", b.dataset.c === c)); showDrape() };
function renderAdvice() {
  const d = ST.drape;
  $("#advice").innerHTML = `<h3>How it fits</h3>` + [...d.advice, ...(d.pose ? d.pose.advice : [])].map(a => `<div class="check ${a.ok ? "ok" : a.level === "problem" ? "bad" : "note"}"><span class="ic">${a.ok ? "✓" : a.level === "problem" ? "!" : "i"}</span><div><b>${a.text}</b>${a.region ? ` <a href="#" class="showme" title="Show it on the avatar (the fit map)">Show me</a>` : ""}${a.share != null ? `<span class="tech adv-inline">${Math.round(a.share * 100)}% of the snug spots</span>` : ""}${a.fix ? `<div style="margin-top:6px"><button class="btn small primary" data-fp="${a.fix.param}" data-fv="${a.fix.value}">${a.fix.label}</button></div>` : ""}</div></div>`).join("")
    + (d.ease && d.ease.length ? `<h3>Ease on the drape</h3><p class="lead" style="font-size:12px;margin:0 0 6px">A tape round the draped garment, against the same tape round the body.</p>`
      + d.ease.map(r => `<div class="fitrow"><span>${cap(r.line)}</span><span>${fmtLen(r.garment_cm)} <small style="color:var(--muted)">${r.ease_cm >= 0 ? "+" : "−"}${fmtLen(Math.abs(r.ease_cm))}</small></span></div>`).join("") : "")
    + `<div class="row"><button class="btn small" id="seefit">Show the fit map</button></div>`;
  $$("#advice [data-fp]").forEach(bt => bt.onclick = async () => { applyFix(bt.dataset.fp, +bt.dataset.fv); await new Promise(r => setTimeout(r, 400)); startDrape() });
  renderLog();
  $$("#advice .showme").forEach(l => l.onclick = e => { e.preventDefault(); if (ST.colorby !== "fit") $("#seefit").click() });   // the fit map
  $("#seefit").onclick = () => { ST.colorby = ST.colorby === "fit" ? "panel" : "fit"; $$("#colorby button").forEach(b => b.classList.toggle("on", b.dataset.c === ST.colorby)); showDrape(); $("#seefit").textContent = ST.colorby === "fit" ? "Show the pieces" : "Show the fit map" };
  const m = d.metrics;
  $("#metrics").innerHTML = `<table><tr><th colspan=2>Simulation</th></tr>
    <tr><td>stretch (99th percentile)</td><td class="num">${m.strain_p99_pct.toFixed(1)}%</td></tr>
    <tr><td>stretch (max)</td><td class="num">${m.strain_max_pct.toFixed(1)}%</td></tr>
    <tr><td>poking into the body</td><td class="num">${m.penetrating_verts} pts</td></tr>
    <tr><td>closest to skin</td><td class="num">${m.min_skin_dist_mm.toFixed(1)} mm</td></tr>
    <tr><td>still moving (energy)</td><td class="num">${m.kinetic_energy_uJ.toFixed(1)} µJ</td></tr></table>`;
}
$("#toExport").onclick = () => go("export");
// ---- tap the garment: what's going on there?
const explainCb = async h => {
  const job = activeGarment().drapeJob || ST.job;      // the drape on screen (not a re-drape still running)
  if (!job || !ST.drape) return;
  const posed = !!(PL.rest && PL.i === PL.n - 1);
  $("#explain").innerHTML = `<div class="check"><span class="ic">…</span><div><b>Looking at that spot…</b></div></div>`;
  try {
    let v = h.vertex;
    if (hasLook() && ST.drape.cloth_uv) v = b64(ST.drape.cloth_uv.vmap, Uint32Array)[v];   // printed mesh is per piece
    const r = await api("/api/explain", {job, vertex: v, posed, pose_label: ST.drape.pose ? ST.drape.pose.label : null});
    const ok = /fine/i.test(r.title);
    $("#explain").innerHTML = `<div class="check ${ok ? "ok" : "bad"}"><span class="ic">${ok ? "✓" : "?"}</span><div><b>${r.title}</b>${r.text}
      <span class="tech">across the grain ${r.across_pct}% · along ${r.along_pct}% · on the bias ${r.bias_pct}%</span>
      ${r.fixes.map(f => `<div style="margin-top:6px"><button class="btn small primary" data-fp="${f.param}" data-fv="${f.value}">${f.label}</button></div>`).join("")}
      ${r.hint ? `<span class="tech">${r.hint}</span>` : ""}</div></div>`;
    $$("#explain [data-fp]").forEach(bt => bt.onclick = async () => { applyFix(bt.dataset.fp, +bt.dataset.fv); await new Promise(r => setTimeout(r, 400)); startDrape() });
  } catch (e) { $("#explain").innerHTML = `<div class="err">${e.message}</div>` }
};
explainCb.active = () => ST.step === "preview" && !!ST.drape && !DS.placing;

