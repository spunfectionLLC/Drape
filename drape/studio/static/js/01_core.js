// drape studio: state, helpers, undo/redo, the step bar, top-bar toggles
// (classic script: shares one global scope with the others, loaded in order by index.html)
"use strict";
// ======================================================== state & helpers
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const ST = {
  init: null, step: "body", maxStep: 0, units: "cm",
  meas: {}, avatar: null, colorby: "panel", sa: 1.5,
};
// ======================================================== the project: one or more garments (multi-garment spec,
// 2026-11-24). Everything about a pattern lives in its garment; there's no other copy. ST.block, ST.design,
// ST.fabric … are views of the *active* garment (getters/setters below), so every tool resolves its target
// through PROJECT.garments[activeGarmentId].
const GARMENT_STATE = ["block", "choices", "params", "scratch", "design", "draft", "sfull", "fabric", "drape", "job",
                       "print", "printCm", "printImg"];
const GARMENT_COLORS = ["#1f7a6d", "#b5542c", "#3d5a99", "#8a5a9e", "#b08a1e", "#4f8a3c"];
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : "g" + Date.now().toString(36) + Math.random().toString(36).slice(2));
function newGarment(name, over = {}) {
  const n = (typeof PROJECT !== "undefined" ? PROJECT.garments.length : 0);
  return {id: uid(), name: name || `Garment ${n + 1}`, color: GARMENT_COLORS[n % GARMENT_COLORS.length],
          layer: n + 1, visible: true, frozen: false,
          block: null, choices: {}, params: {}, scratch: false, design: {pieces: [], seams: []},
          draft: null, sfull: null, fabric: "jersey", drape: null, job: null, print: "none", printCm: 8, printImg: null,
          ui: {sel: null, view: null}, ...over};
}
const PROJECT = {version: 2, garments: [], activeGarmentId: null};
PROJECT.garments.push(newGarment("Garment 1")); PROJECT.activeGarmentId = PROJECT.garments[0].id;
const garmentBy = id => PROJECT.garments.find(g => g.id === id);
const activeGarment = () => garmentBy(PROJECT.activeGarmentId) || PROJECT.garments[0];
for (const k of GARMENT_STATE)
  Object.defineProperty(ST, k, {get() { return activeGarment()[k] }, set(v) { activeGarment()[k] = v }, enumerable: true});
// switch the garment every panel works on (the one place it changes: the 2D editor, fabric panel, 3D view and
// the garment list all read it from here)
function setActiveGarment(id, {quiet = false} = {}) {
  if (!garmentBy(id) || id === PROJECT.activeGarmentId) return;
  PROJECT.activeGarmentId = id;
  if (typeof onGarmentSwitch === "function") onGarmentSwitch(quiet);
}
// what the page redraws after a switch (defined here, called at run time, after every file has loaded)
let GARMENT_SWITCHES = 0;          // counted, so a running drape knows the 3D view's cloth was replaced
function onGarmentSwitch(quiet) {
  GARMENT_SWITCHES++;
  // another garment's drape progress (or "The drape failed") isn't about this one
  if (typeof GL !== "undefined" && GL.overlay && !activeGarment().draping) GL.overlay(null);
  if (typeof syncTryOn === "function") syncTryOn();
  // Live simulates one garment: the one it was started on (left running, the next pattern change would restart it
  // for this garment from the other one's cloth, matched by piece names, and clear this one's drape)
  if (typeof LIVE !== "undefined" && LIVE.sim) stopLive();
  if (typeof DS !== "undefined") DS.resp = null;          // the free editor's last answer was the other garment's
  $("#pattern").classList.toggle("design", ST.scratch);
  renderGarments(); renderStarters(); renderFabrics();
  if (typeof renderGarmentList === "function") renderGarmentList();
  if (!ST.scratch && ST.block) {
    if (ST.draft) renderDraft();                            // its own title, choices, sliders, checks and pattern
    else redraft();                                         // drafted the first time it's opened
  }
  if (ST.step === "fit" || ST.step === "garment") go(ST.block || ST.scratch ? "fit" : "garment");
  else if (ST.drape && (ST.step === "preview" || ST.step === "export")) showDrape();
  else if (ST.step !== "body") showAvatarOnly();
  if (ST.step === "export") renderExport();
  renderLog();
  if (!quiet) autosave();
}
// feature switches (drape/features.py): the server's copy from /api/init wins;
// this mirror is what the page assumes before it arrives
const FEATURES = {OPENING_BANDS: true, BINDING_TOOL: true, FACING_TOOL: true, CLOUD_DRAPE: false};
const feature = k => !!((ST.init && ST.init.features) || FEATURES)[k];
// the product's public name (drape/brand.py; tests/test_v22_rename.py keeps them the same). The code is `drape`;
// "drape" in the UI is only the sewing word
const BRAND = {app: "Spunfection Studio", tm: "Spunfection Studio™", company: "Spunfection LLC", domain: "spunfection.studio"};
// plain names for pieces and edges: "front.side_1_r" -> "Front · right side, part 1" (the seam list, the log)
const EDGE_WORDS = {r: "right", l: "left", cf: "centre front", cb: "centre back", cap: "sleeve cap", a: "leg a", b: "leg b"};
function plainPiece(n) {
  const w = n.split("_"), side = w.filter(x => x === "r" || x === "l").map(x => EDGE_WORDS[x]), rest = w.filter(x => x !== "r" && x !== "l");
  const s = rest.join(" "); return (s.charAt(0).toUpperCase() + s.slice(1)) + (side.length ? ` (${side[0]})` : "");
}
// a piece's name for people: a pocket bag says which pocket and which half ("Pocket bag · right (front half)").
// The side is where it sits on the piece it's inside (the same for both halves of a pocket: the back half
// is sewn to the back's own *left* seam, which is the right side when worn); the half is its layer.
function friendlyPiece(pc) {
  if (/_bag(_\d+)?$/.test(pc.name) && pc.place && pc.place.on && typeof pieceBy === "function" && pieceBy(pc.place.on)) {
    const h = pieceBy(pc.place.on), hb = bboxV(h), bb = bboxV(pc), pos = pc.place.pos || [0, 0];
    const side = (bb[0] + bb[2]) / 2 + pos[0] > (hb[0] + hb[2]) / 2 ? "right" : "left";
    return `Pocket bag · ${side}, ${pc.place.inside === 2 ? "back" : "front"} half`;
  }
  return plainPiece(pc.name);
}
function plainRef(ref) {
  const [pn, en] = ref.split(/\.(.*)/s), w = (en || "").split("_");
  const side = w.filter(x => x === "r" || x === "l").map(x => EDGE_WORDS[x]), nums = w.filter(x => /^\d+$/.test(x));
  const rest = w.filter(x => x !== "r" && x !== "l" && !/^\d+$/.test(x)).map(x => EDGE_WORDS[x] || x).join(" ");
  return `${plainPiece(pn)} · ${side.length ? side[0] + " " : ""}${rest}${nums.length ? `, part ${nums.join(".")}` : ""}`;
}
const STEPS = [["body", "Body"], ["garment", "Garment"], ["fit", "Fit"], ["preview", "Try on"], ["export", "Make it"]];
const LS = {get(k, d) { try { const v = localStorage.getItem("drape." + k); return v == null ? d : JSON.parse(v) } catch (e) { return d } },
            set(k, v) { try { localStorage.setItem("drape." + k, JSON.stringify(v)); return true } catch (e) { return false } }};
const IN = 2.54;
const fmtLen = (cm, digits = 1) => ST.units === "in" ? (cm / IN).toFixed(digits) + '"' : cm.toFixed(digits) + " cm";
const toUnit = cm => ST.units === "in" ? cm / IN : cm;
const fromUnit = v => ST.units === "in" ? v * IN : v;
function toast(msg, ms = 2600) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), ms) }
async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  const ct = r.headers.get("Content-Type") || "";
  if (!ct.includes("json")) { if (!r.ok) throw new Error(r.statusText); return r }
  const j = await r.json(); if (!r.ok || j.error) throw new Error(j.error || r.statusText); return j;
}
const b64 = (s, T) => { const bin = atob(s), u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i); return new T(u.buffer) };
const debounce = (f, ms) => { let h; return (...a) => { clearTimeout(h); h = setTimeout(() => f(...a), ms) } };

// ======================================================== undo / redo
// One stack for the whole project. Each entry is one garment's change: {gid, before, after}. Undo puts that
// garment back to `before` (redo: `after`), switching to it first so the change is visible.
const UNDO_MAX = 300, UNDO_CHARS = 40e6;                 // undo keeps the newest steps (see pushHist)
const H = {stack: [], i: -1, lock: false, last: {}};      // last: each garment's state as last recorded
function snapshot(g = activeGarment()) { return JSON.stringify({block: g.block, choices: g.choices, params: g.params, scratch: g.scratch, design: g.design}) }
// g: the garment that changed (a debounced change can land after a switch: it still belongs to its own garment)
function pushHist(g = activeGarment()) {
  if (H.lock) return;
  const gid = g.id, s = snapshot(g), prev = H.last[gid];
  H.last[gid] = s;
  if (prev === undefined || prev === s) { updUndo(); if (prev === undefined) autosave(); return }   // the first is the baseline
  H.stack = H.stack.slice(0, H.i + 1); H.stack.push({gid, before: prev, after: s});
  // a long session: the oldest steps go (at most UNDO_MAX steps, and about UNDO_CHARS of snapshots: an entry's
  // before is the previous entry's after, the same string, so each step costs one snapshot)
  let chars = 0, keep = 0;
  for (let k = H.stack.length - 1; k >= 0 && keep < UNDO_MAX; k--) { chars += H.stack[k].after.length; if (chars > UNDO_CHARS && keep) break; keep++ }
  if (keep < H.stack.length) H.stack = H.stack.slice(H.stack.length - keep);
  H.i = H.stack.length - 1; updUndo(); autosave();
}
function updUndo() { $("#undo").disabled = H.i < 0; $("#redo").disabled = H.i >= H.stack.length - 1 }
async function goHist(d) {
  const e = d < 0 ? H.stack[H.i] : H.stack[H.i + 1]; if (!e) return;
  H.i += d < 0 ? -1 : 1; updUndo();
  if (e.gid !== PROJECT.activeGarmentId && garmentBy(e.gid)) setActiveGarment(e.gid, {quiet: true});
  const raw = d < 0 ? e.before : e.after, s = JSON.parse(raw); H.lock = true; H.last[e.gid] = raw;
  ST.block = s.block; ST.choices = s.choices; ST.params = s.params; ST.scratch = !!s.scratch; ST.design = s.design || {pieces: [], seams: []};
  if (DS.sel && !pieceBy(DS.sel)) DS.sel = null;
  ST.drape = null; ST.sfull = null; showAvatarOnly();
  $("#pattern").classList.toggle("design", ST.scratch); renderGarments(); renderStarters();
  if (ST.step === "fit") go("fit");
  if (!ST.scratch) await redraft();
  H.lock = false;
}
$("#undo").onclick = () => goHist(-1); $("#redo").onclick = () => goHist(1);
addEventListener("keydown", e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && e.target.tagName !== "INPUT") { e.preventDefault(); goHist(e.shiftKey ? 1 : -1) } });
// the browser keeps a few MB: frozen garments' draped shapes can pass that, and a save that didn't fit used to
// leave an *older* copy to come back to. Then it's kept without the frozen shapes (they unfreeze on reload) and
// the person is told once to save a file
let autosaveWarned = false;
function autosave() {
  if (LS.set("project", project())) return true;
  const p = project(); p.garments = p.garments.map(g => g.frozenMesh ? {...g, frozen: false, frozenMesh: undefined} : g);
  const ok = LS.set("project", p);
  if (!autosaveWarned) {
    autosaveWarned = true;
    toast(ok ? "This project is too big for the browser's own copy with its frozen garments: they'll be unfrozen if you reload. Save it to a file (💾) to keep everything."
             : "This project is too big for the browser's own copy: save it to a file (💾) to keep it.", 9000);
  }
  return ok;
}
// ---- project file, version 2 (multi-garment spec): {version: 2, avatar, scene, garments, activeGarmentId}.
// Version 1 (one garment at the top level) still opens (migrateProject) and is never written again.
const GARMENT_SAVED = ["id", "name", "color", "layer", "visible", "frozen", "block", "choices", "params", "scratch", "fabric",
                       "print", "printCm"];
function garmentData(g) {
  const o = {}; for (const k of GARMENT_SAVED) o[k] = g[k];
  // design format 2: pieces may have a "stage" and a "role" (sewing order); format 1 files load as automatic
  o.design = g.design && {...g.design, format: 2};
  if (g.frozen && g.frozenMesh) o.frozenMesh = g.frozenMesh;      // the draped shape it's frozen in (phase 4)
  return o;
}
function project() {
  return {version: 2, name: ST.name || undefined, avatar: {measurements: ST.meas}, scene: {units: ST.units},
          garments: PROJECT.garments.map(garmentData), activeGarmentId: PROJECT.activeGarmentId};
}
// A project or garment file is someone else's text (files are shared): piece, edge and garment names end up in
// the page's HTML in many places. So every string a file brings is cleaned once, here, of the characters HTML
// needs (& becomes "and"; seams keep matching their edges because both sides change the same way). Ids and
// colours must have their own shape; units are cm or in.
const SAFE_ID = /^[\w-]{1,80}$/, SAFE_COLOR = /^#[0-9a-f]{3,8}$/i;
function cleanFile(x) {
  if (typeof x === "string") return x.replace(/[<>"`]/g, "").replace(/&/g, "and");
  if (Array.isArray(x)) return x.map(cleanFile);
  if (x && typeof x === "object") {
    const o = {};
    for (const [k, v] of Object.entries(x)) if (k !== "__proto__" && k !== "constructor" && k !== "prototype") o[cleanFile(k)] = cleanFile(v);
    return o;
  }
  return x;
}
function cleanGarment(d, i = 0) {
  d = cleanFile(d || {});
  if (d.id != null && !SAFE_ID.test(String(d.id))) d.id = uid();
  if (d.color != null && !SAFE_COLOR.test(String(d.color))) d.color = GARMENT_COLORS[i % GARMENT_COLORS.length];
  if (typeof d.name !== "string" || !d.name.trim()) d.name = `Garment ${i + 1}`;
  if (!(Number.isFinite(d.layer) && d.layer >= 1)) d.layer = i + 1;
  // frozen with no frozen shape: it could neither drape (frozen) nor collide (no shape)
  if (d.frozen && !(d.frozenMesh && typeof d.frozenMesh.v === "string" && typeof d.frozenMesh.f === "string")) { d.frozen = false; d.frozenMesh = undefined }
  // a pattern or fabric this copy doesn't have (a newer file, or a custom fabric from another browser): the
  // garment still opens (block: pick another pattern; fabric: jersey; a piece's own fabric: the garment's)
  const I = typeof ST !== "undefined" && ST.init;
  if (I) {
    const fab = k => I.fabrics.some(f => f.key === k);
    if (d.block && !I.blocks.some(b => b.key === d.block)) { cleanGarment.dropped.push(`pattern "${d.block}"`); d.block = null }
    if (d.fabric && !fab(d.fabric)) { cleanGarment.dropped.push(`fabric "${d.fabric}"`); d.fabric = "jersey" }
    for (const pc of (d.design && Array.isArray(d.design.pieces) ? d.design.pieces : []))
      if (pc && pc.fabric && !fab(pc.fabric)) { cleanGarment.dropped.push(`fabric "${pc.fabric}"`); pc.fabric = null }
  }
  return d;
}
cleanGarment.dropped = [];      // what the last file named that this copy doesn't have (openText says so)
// any project file (or the copy kept in this browser) as version 2
function migrateProject(p) {
  p = cleanFile(p && typeof p === "object" ? p : {}); cleanGarment.dropped = [];
  if (p.scene && !["cm", "in"].includes(p.scene.units)) p.scene.units = undefined;
  if (!["cm", "in"].includes(p.units)) p.units = undefined;
  if (p.version === 2 && Array.isArray(p.garments)) {
    const seen = new Set();
    p.garments = p.garments.map(cleanGarment).map(g => { if (!g.id || seen.has(g.id)) g.id = uid(); seen.add(g.id); return g });   // ids are unique
    return p;
  }
  const g = newGarment("Garment 1", {layer: 1});
  for (const k of ["block", "choices", "params", "scratch", "fabric", "design"]) if (p[k] !== undefined) g[k] = p[k];
  g.scratch = !!g.scratch; g.choices = g.choices || {}; g.params = g.params || {};
  return {version: 2, name: p.name, avatar: {measurements: p.measurements || {}}, scene: {units: p.units},
          garments: [cleanGarment(garmentData(g))], activeGarmentId: g.id};
}
// put a version 2 project's garments in place (fresh session state: no drafts or drapes yet)
function loadGarments(p) {
  PROJECT.garments = (p.garments || []).map((d, i) => newGarment(d.name, {...d, layer: d.layer || i + 1,
    choices: d.choices || {}, params: d.params || {}, scratch: !!d.scratch, design: d.design || {pieces: [], seams: []},
    fabric: d.fabric || "jersey", print: d.print || "none", printCm: d.printCm || 8, id: d.id || uid()}));
  if (!PROJECT.garments.length) PROJECT.garments.push(newGarment("Garment 1"));
  PROJECT.activeGarmentId = garmentBy(p.activeGarmentId) ? p.activeGarmentId : PROJECT.garments[0].id;
  H.stack = []; H.i = -1; H.last = {};
}

// ======================================================== steps nav
// Garment and Fit/Design are one step, "Design" (multi-garment spec): it opens the garment picker while the
// active garment has no pattern yet, and the pattern once it has one. go("garment") still opens the picker.
const NAV = STEPS.filter(s => s[0] !== "garment");
function renderSteps() {
  $("#steps").innerHTML = NAV.map(([k, t], n) => {
    const i = STEPS.findIndex(s => s[0] === k), on = ST.step === k || (k === "fit" && ST.step === "garment");
    return `<button data-k="${k}" class="${on ? "on" : ""} ${i < ST.maxStep ? "done" : ""}" ${stepNeed(k) ? `title="${stepNeed(k)[1]}"` : ""}><span class="n">${i < ST.maxStep ? "✓" : n + 1}</span><span class="t">${k === "fit" ? "Design" : t}</span></button>`;
  }).join("");
  $$("#steps button").forEach(b => b.onclick = () => go(b.dataset.k));
}
// every step opens at any time; one that isn't ready says what it needs, and its controls are greyed out
function stepNeed(k) {
  if (k === "body") return null;
  if (!ST.avatar) return ["body", "Build your avatar first: every pattern is drafted to fit it."];
  if (k === "garment") return null;
  if (!ST.block && !ST.scratch) return ["garment", "Pick a garment or start from scratch first."];
  return null;
}
function go(k) {
  // Live keeps running on Try on and in the free editor (◐ 3D view); a drafted pattern's step has no 3D view
  if (typeof LIVE !== 'undefined' && LIVE.sim && !(k === 'preview' || (k === 'fit' && ST.scratch))) stopLive();
  if (k === "fit" && ST.avatar && !ST.block && !ST.scratch) k = "garment";   // a garment with no pattern yet: pick one
  const need = stepNeed(k), i = STEPS.findIndex(s => s[0] === k); ST.step = k;
  if (!need) ST.maxStep = Math.max(ST.maxStep, i);
  const pane = k === "fit" && ST.scratch ? "design" : k;
  document.body.dataset.step = pane;          // each step's layout (studio.css)
  { const box = $("#garlook"), host = $(`.pane[data-pane="${pane}"]`);      // fabric + print: on the design steps
    if (box && host && (pane === "design" || pane === "fit") && box.parentElement !== host) { const at = pane === "design" ? host.querySelector(":scope > h2") : host.querySelector(":scope > .actions"); host.insertBefore(box, at || null) } }
  $$(".pane").forEach(p => p.classList.toggle("on", p.dataset.pane === pane)); renderSteps();
  $(".stage").classList.toggle("tooled", pane === "design" && !need); closePop(); if (typeof renderToolPop === "function") renderToolPop();
  if (need) {
    const label = STEPS.find(s => s[0] === need[0])[1];
    document.body.dataset.blocked = "1";
    $("#blockmsg").innerHTML = `<span style="flex:1">${need[1]}</span><button class="btn small primary" id="blockGo">Go to ${label} →</button>`;
    $("#blockGo").onclick = () => go(need[0]);
    window.scrollTo({top: 0, behavior: "smooth"}); $("#side").scrollTop = 0; renderLog(); return;
  }
  delete document.body.dataset.blocked; $("#blockmsg").innerHTML = "";
  if (pane === "design") { renderShapes(); renderBands(); renderSymBtn(); toolHint(); renderInspector(); drawDesign(); dsRefresh() }
  if (k !== "fit") { DS.placing = false; $("#glcard").classList.remove("placing") }
  if (k !== "preview" && typeof stopPlayer === "function" && PL.rest) stopPlayer();
  if (k === "export") renderExport();
  if (k === "preview" && typeof syncTryOn === "function") syncTryOn();
  if (k === "body") showAvatarOnly();
  else if (ST.scratch && !ST.drape && k !== "fit") dsRefresh();
  else if (ST.drape && (k === "preview" || k === "export")) { showDrape(); if (hasLook()) applyPrint() }
  window.scrollTo({top: 0, behavior: "smooth"}); $("#side").scrollTop = 0;
  renderLog();
}

// ======================================================== toggles
$("#units").onclick = e => { const u = e.target.dataset.u; if (!u) return; ST.units = u; LS.set("units", u);
  $$("#units button").forEach(b => b.classList.toggle("on", b.dataset.u === u)); renderMeasFields(); if (ST.draft && !ST.scratch) renderDraft(); renderFitRows(); if (ST.step === "export") renderExport();
  if (ST.scratch && ST.step === "fit") { renderInspector(); drawDesign(); renderDsSeams(); renderDsChecks() } };
$("#mode").onclick = e => { const m = e.target.dataset.m; if (!m) return; document.body.classList.toggle("advanced", m === "adv"); LS.set("mode", m);
  $$("#mode button").forEach(b => b.classList.toggle("on", b.dataset.m === m)); $("#colorby").style.display = m === "adv" && ST.drape ? "inline-flex" : "none"; renderMeasFields();
  if (typeof renderLog === "function") renderLog() };   // nothing else changes: the design, selection and step stay
$("#theme").onclick = () => { const d = document.documentElement.dataset.theme === "dark" ? "" : "dark"; document.documentElement.dataset.theme = d; LS.set("theme", d); GL.bg() };
$("#mclose").onclick = () => $("#modal").classList.remove("show");
$("#modal").onclick = e => { if (e.target.id === "modal") $("#modal").classList.remove("show") };
function modal(title, html) { $("#mtitle").textContent = title; $("#mbody").innerHTML = html; $("#modal").classList.add("show") }

