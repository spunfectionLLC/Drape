// drape studio: step 1: measurements and the avatar
// (classic script: shares one global scope with the others, loaded in order by index.html)
// ======================================================== 1. body
const MAIN_FIELDS = [["height", "Height", "standing, no shoes"], ["chest", "Bust / chest", "fullest part, tape level"],
  ["waist", "Waist", "natural waist, narrowest part"], ["hip", "Hips", "fullest part of the seat"]];
const MORE_FIELDS = [["underbust", "Underbust", "right under the bust"], ["shoulder_width", "Shoulder width", "across the back, bone to bone"],
  ["neck", "Neck", "around the base"], ["upper_arm", "Upper arm", "fullest part"], ["arm_length", "Arm length", "shoulder to wrist, elbow bent a little"],
  ["thigh", "Thigh", "fullest part"], ["inseam", "Inseam", "crotch to floor, inside the leg, barefoot"],
  ["hand_length", "Hand length", "for gloves: wrist crease to the tip of the middle finger"], ["hand_girth", "Hand girth", "for gloves: around the knuckles, thumb not included"],
  ["wrist", "Wrist", "for gloves and cuffs: around the wrist bone"]];
// a field left empty is "auto": the avatar works it out from your other numbers (its body shape grows
// together, the way bodies do); once built, the field shows what it came out at
function autoValue(k) {
  const r = ST.avatar && ST.avatar.rows && ST.avatar.rows.find(r => r.measurement === k);
  return r && r.avatar_cm != null ? `auto · ${(+toUnit(r.avatar_cm)).toFixed(ST.units === "in" ? 1 : 0)}` : "auto";
}
function measField([k, label, help]) {
  const v = ST.meas[k]; const val = v == null || v === "" ? "" : (+toUnit(v)).toFixed(ST.units === "in" ? 1 : 0);
  return `<div class="field"><label>${label}<small>${help}</small></label><div class="inp"><input inputmode="decimal" data-k="${k}" value="${val}" placeholder="${autoValue(k)}"><span>${ST.units}</span></div></div>`;
}
function renderMeasFields() {
  $("#mfields").innerHTML = MAIN_FIELDS.map(measField).join("");
  $("#mfields2").innerHTML = MORE_FIELDS.map(measField).join("");
  // while typing too (markStale debounces the rebuild by 600 ms in Simple mode)
  $$("#mfields input,#mfields2 input").forEach(inp => inp.oninput = inp.onchange = () => {
    const x = parseFloat(inp.value); if (isNaN(x)) delete ST.meas[inp.dataset.k]; else ST.meas[inp.dataset.k] = +fromUnit(x).toFixed(1);
    $("#example").value = ""; markStale();
  });
  $$("#sex button").forEach(b => b.classList.toggle("on", b.dataset.s === ST.meas.sex));
}
function markStale() {
  $("#build").textContent = ST.avatar ? "Update my avatar" : "Build my avatar";
  // Simple mode: no button, the avatar follows the numbers (600 ms after the last change)
  if (!document.body.classList.contains("advanced")) {
    clearTimeout(AUTO.t); AUTO.t = setTimeout(autoBuild, 600);
    const n = $("#nextslot"); if (n && !$("#toGarment")) n.innerHTML = `<small class="updating">Updating your avatar…</small>`;
  }
}
const AUTO = {t: null, busy: false, again: false};
async function autoBuild() {
  if (!ST.init) { AUTO.t = setTimeout(autoBuild, 300); return }
  if (AUTO.busy) { AUTO.again = true; return }      // one build at a time; the last change wins
  AUTO.busy = true;
  try { await buildAvatar() } finally { AUTO.busy = false }
  if (AUTO.again) { AUTO.again = false; autoBuild() }
}
$("#sex").onclick = e => { const s = e.target.dataset.s; if (!s) return; ST.meas.sex = s;
  const ex = ST.init.examples[s + "_M"]; if (ex && $("#example").value) loadExample(s + "_M"); renderMeasFields(); markStale() };
function loadExample(key) {
  // a size fills only the main four (and sex): the rest stay on auto, so they follow your own numbers
  // (a preset's neck or underbust left behind contradicted a larger chest or waist typed over it)
  const ex = ST.init.examples[key]; if (!ex) return; ST.meas = {};
  for (const [k, v] of Object.entries(ex)) if (["sex", ...MAIN_FIELDS.map(f => f[0])].includes(k) && ST.init.fields.includes(k)) ST.meas[k] = v;
  $("#example").value = key; renderMeasFields(); markStale();
}
$("#example").onchange = e => e.target.value && loadExample(e.target.value);
$("#howto").onclick = () => {
  if (ST.avatar) modal("How to measure", `<p class="lead">Where each tape goes, drawn on your avatar.</p><p id="guideload">Drawing the tape lines on your avatar…</p><img id="guideimg" alt="">`);
  if (ST.avatar) fetch(`/api/guide/${ST.avatar.id}.png`).then(async r => { if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || "it didn't draw"); return r.blob() }).then(b => {   // through fetch: the web build answers it in the page
    const im = $("#guideimg"); if (!im) return; im.onload = () => { const g = $("#guideload"); if (g) g.remove() }; im.src = URL.createObjectURL(b) })
    .catch(e => { const g = $("#guideload"); if (g) g.textContent = "Couldn't draw the tape lines: " + e.message });
  else modal("How to measure", `<p>Use a soft tape, snug but not tight, over light clothes.</p><ul>${[...MAIN_FIELDS, ...MORE_FIELDS].map(f => `<li><b>${f[1]}</b>: ${f[2]}</li>`).join("")}</ul><p class="lead">Build your avatar to see each tape line drawn on the body.</p>`);
};
function renderProfiles() {
  const P = LS.get("profiles", {});
  $("#profiles").innerHTML = Object.keys(P).map((n, i) => `<button class="chip" data-i="${i}"></button>`).join("");
  $$("#profiles .chip").forEach((c, i) => c.textContent = Object.keys(P)[i]);       // a name typed in: text, not markup
  $$("#profiles .chip").forEach(c => c.onclick = () => { c.dataset.p = c.textContent; ST.meas = {...P[c.dataset.p]}; $("#example").value = ""; renderMeasFields(); markStale(); toast(`Loaded ${c.dataset.p}`) });
}
$("#saveprof").onclick = () => { const n = prompt("Name this profile (e.g. 'Me', 'Mom')"); if (!n) return; const P = LS.get("profiles", {}); P[n] = {...ST.meas}; LS.set("profiles", P); renderProfiles(); toast("Saved in this browser") };

$("#build").onclick = buildAvatar;
async function buildAvatar() {
  const btn = $("#build"); btn.disabled = true; GL.overlay("Building your avatar…", "about 5 seconds the first time", -1);
  try {
    const a = await api("/api/avatar", {measurements: ST.meas});
    ST.avatar = a; GL.setBody(a.mesh); GL.overlay(null); showAvatarOnly(); renderFitRows();
    $$("#mfields input, #mfields2 input").forEach(i => i.placeholder = autoValue(i.dataset.k));   // in place: typing keeps focus
    if (a.warnings && a.warnings.length) toast(a.warnings.join(" · "), 5000);
    // only the label goes back (markStale would schedule another build in Simple mode: a rebuild loop)
    btn.textContent = "Avatar ready ✓"; setTimeout(() => { btn.textContent = "Update my avatar" }, 1500);
    ST.maxStep = Math.max(ST.maxStep, 1); renderSteps(); autosave();
    if (ST.block) { ST.drape = null; await redraft() }
  } catch (e) { GL.overlay("Couldn't build the avatar", e.message); }
  btn.disabled = false;
}
function renderFitRows() {
  if (!ST.avatar) { $("#fitrows").innerHTML = ""; $("#nextslot").innerHTML = ""; return }
  const rows = ST.avatar.rows.filter(r => r.target_cm != null).map(r => ({name: r.measurement.replace(/_/g, " "), got: r.avatar_cm, target: r.target_cm}));
  const worst = rows.reduce((m, r) => Math.max(m, Math.abs(r.got - r.target)), 0), off = rows.filter(r => Math.abs(r.got - r.target) >= 1.5).length;
  // one line that says how close the avatar is; the table opens from it
  // when the avatar can't reach a number it's the avatar's limit, never the person's: neutral words, no warning
  // colour (CLAUDE.md, "Bodies")
  const sum = off ? `Our avatar can't reach ${off} of your measurement${off > 1 ? "s" : ""} yet. That's a limit of the avatar, not your numbers.`
                  : `Avatar matches your numbers (all within ${fmtLen(Math.max(worst, 0.1))})`;
  $("#fitrows").innerHTML = `<details class="sumbox"><summary><span class="ic ${off ? "info" : "ok"}">${off ? "i" : "✓"}</span>${sum}</summary>` + rows.map(r => {
    const d = r.got - r.target;
    return `<div class="fitrow"><span>${r.name}</span><span>${fmtLen(r.got)} <small style="color:var(--muted)">${d >= 0 ? "+" : ""}${toUnit(d).toFixed(1)}</small></span></div>`
  }).join("") + `</details>`;
  $("#nextslot").innerHTML = `<button class="btn primary next-step" id="toGarment">Next: pick a garment →</button>`;
  $("#toGarment").onclick = e => { e.preventDefault(); go("garment") };
}

