// drape studio: start-up
// (classic script: shares one global scope with the others, loaded in order by index.html)
// ======================================================== boot
(async function boot() {
  const th = LS.get("theme", matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : ""); document.documentElement.dataset.theme = th; GL.bg();
  ST.units = LS.get("units", "cm"); $$("#units button").forEach(b => b.classList.toggle("on", b.dataset.u === ST.units));
  if (LS.get("mode", "beg") === "adv") $("#mode button[data-m=adv]").click();
  ST.init = await api("/api/init"); if (ST.init.version) { $("#alphaBtn").textContent = `ALPHA v${ST.init.version}`; $("#alphaBtn").title += ` (version ${ST.init.version})` } if (ST.init.web) renderPoses();
  // ⚡ Live only where there's a GPU it can use (an office PC's blocked or missing WebGPU: no button that can't work)
  ST.gpu = null;
  (window.LiveSprings ? LiveSprings.supported() : Promise.resolve(false)).then(ok => {
    ST.gpu = ok; $("#liveBtn").style.display = ok ? "" : "none"; if (typeof gpuChanged === "function") gpuChanged() });
  $("#example").innerHTML = `<option value="">my own</option>` + Object.keys(ST.init.examples).filter(k => !k.startsWith("example")).map(k => `<option value="${k}">${k.replace("_", " ")}</option>`).join("");
  loadExample("female_M"); renderGarments(); renderStarters(); renderFabrics();
  if (!navigator.webdriver) {
    const tour = () => { if (!LS.get("toured", 0)) setTimeout(helpModal, 200) };
    if (LS.get("alphaSeen", "") !== (ST.init.version || "1")) setTimeout(() => alphaNotice(tour), 600); else tour();
  }
  renderProfiles(); renderSteps();
  const saved = LS.get("project", null);
  const fresh = LS.get("newProject", 0); LS.set("newProject", 0);
  const sp = saved && migrateProject(saved), sm = sp && sp.avatar && sp.avatar.measurements;
  if (sm && Object.keys(sm).length) {
    ST.meas = sm; ST.name = sp.name || ""; loadGarments(sp); renderMeasFields(); $("#example").value = "";
    renderGarments(); renderStarters(); renderFabrics(); if (typeof renderGarmentList === "function") renderGarmentList();
    toast(fresh ? "New project: your measurements are kept" : "Welcome back: your last project is loaded");
  }
  window.__studio = {ST, GL, go, openProject, DS, PROJECT};
})();
