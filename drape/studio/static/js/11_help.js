// drape studio: the help tour
// (classic script: shares one global scope with the others, loaded in order by index.html)
// ---- help: a short tour, shown once
const TOUR = [
  ["1 · Body", "Type your measurements (or pick a size). The avatar is built from them, with guide lines showing where each one is taken."],
  ["2 · Garment", "Start from a pattern (tee, skirt, trousers…), a finished design (30 of them, with pockets, buttons and zippers), or a blank board."],
  ["3 · Design / Fit", "Change any piece: drag points, bend edges, add darts, pleats, bands, pockets inside or out, openings with buttons or zippers. Seams list shows what's sewn to what and whether lengths match."],
  ["4 · Try on", "Drape it on the avatar in any fabric (or yours, measured). ⚡ Live runs it on your graphics card: pull the cloth with the mouse, switch fabrics on the fly. Tap the cloth to ask what's going on there; try sitting or walking."],
  ["Sewing order", "Big pieces sew first and settle on the body; hoods, collars, cuffs and pockets are sewn on afterwards, the way you'd sew them. Change a piece's sewing order (its panel, Advanced mode) if it should go on earlier or later."],
  ["5 · Make it", "Print at home, projector, laser and plotter DXF, DXF-AAMA for factories, a tech pack, a size run, cost and Etsy price, a turntable video, a Blender kit for photo-real renders."],
  ["Your fabric", "Fabric chips → + My fabric: three kitchen-table tests, or the Spunfection fabric tester (ESP32 + load cell, plans in hardware/fabric_tester) for stretch along, across and on the bias."],
];
function helpModal() {
  modal("How Spunfection Studio works", `<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;max-width:760px">${TOUR.map(([t, d]) =>
    `<div class="ins"><b>${t}</b><span class="lead" style="font-size:13px">${d}</span></div>`).join("")}</div>
    <p class="lead" style="font-size:12px;margin-top:10px">Simple mode keeps it to the essentials; Advanced shows every number. Undo/redo: ⌘Z / ⌘⇧Z. Save your project as a .drape file with 📁 File (Ctrl+S); open it again the same way (Ctrl+O).</p>`);
  LS.set("toured", 1);
}
$("#helpBtn").onclick = helpModal;

// ------------------------------------------------------------ alpha notice
function alphaNotice(after) {
  modal(`${BRAND.app} is in alpha`, `<div style="display:grid;gap:10px;max-width:520px;font-size:14px">
    <p class="lead" style="margin:0">You're using ${BRAND.app}${ST.init && ST.init.version ? ` v${ST.init.version}` : ""} alpha, an early test version. Thanks for trying it!</p>
    <ul style="margin:0;padding-left:20px;display:grid;gap:6px">
      <li><b>Things will change.</b> Tools are still being added and some are rough around the edges.</li>
      <li><b>Check before you cut.</b> The 3D drape and fit numbers are a guide: sew a test garment (a toile) before cutting good fabric.</li>
      <li><b>Save often.</b> Use 📁 File → Save (Ctrl+S) to keep a .drape file; the copy kept in this browser can be lost.</li>
      <li><b>Found a bug or have an idea?</b> Please tell us what you were doing and what you expected.</li>
    </ul>
    <div class="row" style="justify-content:flex-end"><button class="btn primary" id="alphaOk">Got it</button></div></div>`);
  const done = () => { LS.set("alphaSeen", (ST.init && ST.init.version) || "1"); if (after) after() };
  $("#alphaOk").onclick = () => { $("#modal").classList.remove("show"); done() };
  $("#mclose").addEventListener("click", done, {once: true});
}
$("#alphaBtn").onclick = () => alphaNotice();

// ------------------------------------------------------------ the settings menu (units, dark mode, help)
{
  const menu = $("#setmenu"), btn = $("#setBtn");
  const show = on => { menu.hidden = !on; btn.setAttribute("aria-expanded", String(on)) };
  btn.onclick = e => { e.stopPropagation(); show(menu.hidden) };
  document.addEventListener("click", e => { if (!menu.hidden && !e.target.closest(".menuwrap")) show(false) });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && !menu.hidden) show(false) });
  $("#helpBtn").addEventListener("click", () => show(false));
}
// ------------------------------------------------------------ the Design toolbar's dropdowns (seams, start over)
$$(".dd").forEach(dd => {
  const btn = dd.querySelector(".ddbtn"), menu = dd.querySelector(".ddmenu");
  btn.onclick = e => { e.stopPropagation(); const open = menu.hidden; $$(".ddmenu").forEach(m => m.hidden = true); menu.hidden = !open };
  menu.addEventListener("click", e => { if (e.target.closest("#dsExample, #dsClear, #traceBtn")) menu.hidden = true });
});
document.addEventListener("click", e => { if (!e.target.closest(".dd")) $$(".ddmenu").forEach(m => m.hidden = true) });
document.addEventListener("keydown", e => { if (e.key === "Escape") $$(".ddmenu").forEach(m => m.hidden = true) });
// the 3D view beside the pattern in Design: off unless asked for (remembered in this browser)
{
  const set3d = on => { document.body.classList.toggle("show3d", on); $("#show3d").classList.toggle("on", on); LS.set("show3d", on) };
  $("#show3d").onclick = () => set3d(!document.body.classList.contains("show3d"));
  set3d(!!LS.get("show3d", false));
}
// ------------------------------------------------------------ one-time tips: each step's intro line can be
// dismissed (✕) and stays dismissed in this browser (LS wraps localStorage in try/catch)
$$(".pane > p.lead").forEach(p => {
  const key = "tip:" + (p.closest(".pane").dataset.pane || "");
  if (LS.get(key, 0)) { p.remove(); return }
  p.classList.add("tip");
  const x = document.createElement("button"); x.className = "tipx"; x.title = "Got it: don't show this again"; x.textContent = "✕";
  x.onclick = () => { LS.set(key, 1); p.remove() };
  p.appendChild(x);
});
// ------------------------------------------------------------ tabs (Try on: fabric / print / speed & motion)
$$(".tabs").forEach(bar => bar.querySelectorAll(".tab").forEach(b => b.onclick = () => {
  bar.querySelectorAll(".tab").forEach(x => x.classList.toggle("on", x === b));
  bar.parentElement.querySelectorAll(":scope > .tabpane").forEach(p => p.classList.toggle("on", p.dataset.tab === b.dataset.tab));
}));
