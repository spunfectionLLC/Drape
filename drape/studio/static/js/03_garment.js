// drape studio: step 2: the garment and starter galleries
// (classic script: shares one global scope with the others, loaded in order by index.html)
// ======================================================== 2. garment
const ICONS = {
  glove: '<path d="M38 74V44l-9-12c-3-4 2-8 5-5l6 7V14c0-4 6-4 6 0v20V9c0-4 6-4 6 0v25V11c0-4 6-4 6 0v24V17c0-4 6-4 6 0v29c0 10-4 16-8 18v10z"/>',
  mitten: '<path d="M38 74V46l-9-12c-3-4 2-8 5-5l6 7V22c0-12 26-12 26 0v26c0 8-4 14-8 16v10z"/><path d="M38 66h20"/>',
  fingerless: '<path d="M38 74V44l-9-10c-3-4 2-8 5-5l6 6V24h6v-4h6v4h6v-2h6v24c0 10-4 16-8 18v10z"/><path d="M40 24h24"/>',
  tee: '<path d="M38 14l-18 10 7 13 8-4v37h30V33l8 4 7-13-18-10c-2 6-7 9-12 9s-10-3-12-9z"/>',
  long_sleeve: '<path d="M38 14l-14 8-10 40 9 3 10-30v35h34V35l10 30 9-3-10-40-14-8c-2 6-7 9-12 9s-10-3-12-9z"/>',
  a_line_skirt: '<path d="M35 14h30l14 56H21z"/><path d="M35 20h30"/>',
  pencil_skirt: '<path d="M34 14h32l2 26-3 30H35l-3-30z"/><path d="M34 20h32"/>',
  shift_dress: '<path d="M38 10l-8 6 4 18-8 38h48l-8-38 4-18-8-6c-2 5-6 7-12 7s-10-2-12-7z"/>',
  trousers: '<path d="M32 10h36l6 62H55l-5-40-5 40H26z"/><path d="M32 16h36"/>',
  shirt: '<path d="M38 14l-14 8-10 40 9 3 10-30v35h34V35l10 30 9-3-10-40-14-8-12 10z"/><path d="M50 24v44" stroke-dasharray="1 5" stroke-width="3" stroke-linecap="round"/><path d="M38 14l12 10 12-10"/>',
  hoodie: '<path d="M38 18l-14 6-10 38 9 3 10-28v33h34V37l10 28 9-3-10-38-14-6c4-10-2-16-12-16s-16 6-12 16z"/><rect x="38" y="50" width="24" height="12" rx="3"/>',
  tank: '<path d="M36 12h6c1 7 4 10 8 10s7-3 8-10h6c0 9 4 14 8 18v40H28V30c4-4 8-9 8-18z"/>',
  shorts: '<path d="M30 16h40l6 34H55l-5-18-5 18H24z"/><path d="M30 22h40"/>',
  gathered: '<path d="M34 14h32l16 56H18z"/><path d="M34 20h32M40 20l-6 50M50 20v50M60 20l6 50" stroke-width="1"/>',
};
// how hard each basic pattern is to sew (the finished designs carry their own level)
const BLOCK_LEVEL = {tee: "Beginner", long_sleeve: "Beginner", a_line_skirt: "Beginner", shift_dress: "Beginner",
  pencil_skirt: "Intermediate", trousers: "Intermediate"};
function renderGarments() {
  // the basic patterns, then a blank canvas last (not highlighted: it's the advanced start)
  $("#gcards").innerHTML = ST.init.blocks.map(b => `<button class="gcard ${ST.block === b.key ? "on" : ""}" data-k="${b.key}">
    <svg viewBox="0 0 100 80" fill="var(--accent-soft)" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round">${ICONS[b.key] || '<rect x="25" y="10" width="50" height="60"/>'}</svg>
    <b>${b.label}</b><small>${b.category}</small><span class="lvl">${BLOCK_LEVEL[b.key] || "Intermediate"}</span></button>`).join("")
    + `<button class="gcard ${ST.scratch ? "on" : ""}" data-k="__scratch">
    <svg viewBox="0 0 100 80" fill="none" stroke="var(--muted)" stroke-width="2" stroke-linejoin="round"><rect x="14" y="16" width="30" height="40" rx="2"/><circle cx="68" cy="30" r="14"/><path d="M52 66l14-20 14 20z"/></svg>
    <b>Blank canvas (advanced)</b><small>your own shapes, anywhere on the body</small></button>`;
  $$("#gcards .gcard").forEach(c => c.onclick = async () => {
    if (!ST.avatar) { toast("Build your avatar first"); go("body"); return }
    if (c.dataset.k === "__scratch") {
      if (!document.body.classList.contains("advanced")) {   // a blank canvas needs the full tools
        $("#mode button[data-m=adv]").click(); toast("Switched to Advanced: a blank canvas uses every design tool.", 4500) }
      if (!ST.scratch) { ST.scratch = true; ST.block = null; ST.drape = null; ST.sfull = null }
      if (!ST.design.pieces.length) { ST.design = exampleToClient(ST.init.example_design); DS.sel = ST.design.pieces[0].name; DS.view = null; toast("Here's a simple skirt to start from. Change it, or press Blank.", 4000) }
      $("#pattern").classList.add("design"); renderGarments(); go("fit"); pushHist(); return;
    }
    ST.scratch = false; $("#pattern").classList.remove("design");
    if (ST.block !== c.dataset.k) { ST.block = c.dataset.k; ST.choices = {}; ST.params = {}; ST.drape = null }
    renderGarments(); go("fit"); await redraft(); pushHist();
  });
}

let starterCat = "All", starterLoading = null;     // the starter being sized: its card spins
function renderStarters() {
  const S = ST.init.starters || [], cats = ["All", ...new Set(S.map(x => x.category))];
  $("#scats").innerHTML = cats.map(c => `<button class="chip ${c === starterCat ? "on" : ""}" data-c="${c}">${c}</button>`).join("");
  $$("#scats .chip").forEach(b => b.onclick = () => { starterCat = b.dataset.c; renderStarters() });
  $("#scards").innerHTML = S.filter(x => starterCat === "All" || x.category === starterCat).map(x => `<button class="gcard ${ST.design && ST.design.from_starter === x.key && ST.scratch ? "on" : ""} ${x.key === starterLoading ? "loadingcard" : ""}" data-s="${x.key}" title="${x.blurb}">
    <svg viewBox="0 0 100 80" fill="var(--accent-soft)" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round">${ICONS[x.icon] || ICONS.tee}</svg>
    <b>${x.label}</b><small>${x.blurb}</small><span class="lvl">${x.level}</span></button>`).join("");
  $$("#scards .gcard").forEach(c => c.onclick = () => openStarter(c.dataset.s));
}
async function openStarter(key) {
  if (!ST.avatar) { toast("Build your avatar first"); go("body"); return }
  if (ST.scratch && ST.design.pieces.length && !ST.design.from_starter && !confirm("This replaces your current from-scratch design. Continue?")) return;
  const info = ST.init.starters.find(x => x.key === key);
  toast(`Sizing the ${info.label.toLowerCase()} to your avatar…`);
  starterLoading = key; renderStarters();
  patternLoading(`Sizing the ${info.label.toLowerCase()} to your avatar…`);
  try {
    const r = await api("/api/starter", {avatar: ST.avatar.id, key}).finally(() => { patternLoading(null); starterLoading = null; renderStarters() });
    ST.design = r.design; ST.scratch = true; ST.block = null; ST.drape = null; ST.sfull = null;
    if (r.design.suggest_fabric && ST.init.fabrics.some(f => f.key === r.design.suggest_fabric)) { ST.fabric = r.design.suggest_fabric; renderFabrics() }
    DS.sel = null; DS.view = null; tidy(); $("#pattern").classList.add("design");
    renderGarments(); renderStarters(); go("fit"); pushHist();
    toast(`${info.label}: ${r.design.pieces.length} pieces. Tap any piece to change it, or go to Try on.`, 5000);
  } catch (e) { toast("Couldn't open it: " + e.message, 6000) }
}

