// drape studio: my fabric, and the fabric tester (Web Serial)
// (classic script: shares one global scope with the others, loaded in order by index.html)
function myFabricModal() {
  const u = ST.units, cmIn = v => ST.units === "in" ? (v / IN).toFixed(1) : v;
  modal("Measure your fabric", `<div style="display:flex;flex-direction:column;gap:12px;max-width:640px">
    <p class="lead">Three kitchen-table tests. Spunfection Studio runs the same tests in the simulator and finds the settings that give your numbers.
      <a href="#" id="mfTester">Have the Spunfection fabric tester? Use it instead →</a></p>
    <div class="ins"><b>1. Weight</b><span class="lead" style="font-size:13px">Cut a 10 × 10 cm (4 × 4 in) square and weigh it.</span>
      <div class="field"><label>Weight of the square<small>grams</small></label><div class="inp"><input id="mfSq" inputmode="decimal" placeholder="e.g. 1.5"><span>g</span></div></div>
      <small style="color:var(--muted)">No scale that fine? Use the label: g/m² ÷ 100 (oz/yd² × 0.34).</small></div>
    <div class="ins"><b>2. Droop</b><span class="lead" style="font-size:13px">Lay a strip 5 cm (2 in) wide on a table, push it out over the edge, and measure how far the tip hangs below the table top.
      If it hangs straight down, try a shorter overhang.</span>
      <div class="grid2"><label class="f">Sticking out (${u})<input type="text" id="mfOver" value="${cmIn(10)}"></label>
      <label class="f">Tip hangs down (${u})<input type="text" id="mfDroop" placeholder="e.g. ${cmIn(6)}"></label></div></div>
    <div class="ins"><b>3. Stretch</b> <small style="color:var(--muted)">(optional)</small><span class="lead" style="font-size:13px">Hang a strip 5 cm wide, mark 20 cm (8 in) on it, hang a weight from the bottom (a small water bottle in a bag), measure the marks again.</span>
      <div class="grid2"><label class="f">Weight hung (g)<input type="text" id="mfLoad" placeholder="e.g. 500"></label>
      <label class="f">Marks now (${u})<input type="text" id="mfStr" placeholder="e.g. ${cmIn(21)}"></label></div></div>
    <div class="grid2"><label class="f">Name<input type="text" id="mfName" value="My fabric"></label>
      <label class="f">Feel<select id="mfFric"><option value="slippery">slippery (satin, lining)</option><option value="normal" selected>normal</option><option value="grippy">grippy (fleece, velvet)</option></select></label></div>
    <div class="row"><button class="btn primary" id="mfGo">Measure it</button><span id="mfOut" class="lead" style="font-size:13px"></span></div></div>`);
  $("#mfTester").onclick = e => { e.preventDefault(); testerModal() };
  $("#mfGo").onclick = async () => {
    const num = id => { const v = parseFloat($(id).value); return isNaN(v) ? null : v };
    if (num("#mfSq") == null || num("#mfDroop") == null) { $("#mfOut").textContent = "Fill in tests 1 and 2"; return }
    $("#mfGo").disabled = true; $("#mfOut").textContent = "Running the tests in the simulator (about 20 s)…";
    try {
      const r = await api("/api/fabric", {name: $("#mfName").value, square_g: num("#mfSq"), overhang_cm: fromUnit(num("#mfOver")), droop_cm: fromUnit(num("#mfDroop")),
        load_g: num("#mfLoad"), stretched_cm: num("#mfStr") == null ? null : fromUnit(num("#mfStr")), friction: $("#mfFric").value});
      ST.init.fabrics = ST.init.fabrics.filter(f => f.key !== r.key);    // measured again: replace it
      ST.init.fabrics.push({key: r.key, name: r.fabric.name, gsm: r.fabric.gsm, mine: true}); ST.fabric = r.key; renderFabrics();
      $("#mfOut").innerHTML = `Saved <b>${r.fabric.name}</b> (${r.fabric.gsm} g/m²). Simulated droop ${fmtLen(r.check.droop_cm)}` +
        (r.check.stretched_cm ? `, marks ${fmtLen(r.check.stretched_cm)}` : "") + `. ${r.check.note || ""}`;
    } catch (e) { $("#mfOut").textContent = "Couldn't measure: " + e.message }
    $("#mfGo").disabled = false;
  };
}
// ---- the drape fabric tester (hardware/fabric_tester): ESP32 + load cell over Web Serial
const TESTER = {port: null, reader: null, writer: null, rec: null, tests: {warp: null, weft: null, bias: null}};
function testerModal() {
  const u = ST.units, cmIn = v => ST.units === "in" ? (v / IN).toFixed(1) : v;
  const row = d => `<div class="ins" style="gap:6px"><div class="row" style="justify-content:space-between"><b>${{warp: "Along the grain (warp)", weft: "Across the grain (weft)", bias: "On the bias (45°)"}[d]}</b>
      <span id="tst_${d}" style="font-size:12px;color:var(--muted)">not tested</span></div>
      <div class="row" style="gap:6px;flex-wrap:wrap"><button class="btn small" data-rec="${d}">● Record</button>
      <label class="btn small" style="cursor:pointer">Load CSV<input type="file" accept=".csv,.txt" data-csv="${d}" style="display:none"></label></div></div>`;
  modal("Fabric tester", `<div style="display:flex;flex-direction:column;gap:10px;max-width:680px">
    <p class="lead" style="font-size:13px">Clamp a 50 mm strip with 100 mm between the jaws, zero, record, and turn the crank slowly. Plans, firmware and the laser file are in <code>hardware/fabric_tester</code>.</p>
    <div class="row" style="gap:8px;flex-wrap:wrap"><button class="btn small primary" id="tConn">Connect tester</button>
      <button class="btn small" id="tTare" disabled>Tare</button><button class="btn small" id="tZero" disabled>Zero</button>
      <span id="tStat" style="font-size:12px;color:var(--muted)">${"serial" in navigator ? "USB, 115200 baud" : "No Web Serial in this browser: load CSV files instead"}</span></div>
    <canvas id="tPlot" width="640" height="160" style="width:100%;background:var(--bg);border-radius:8px"></canvas>
    ${["warp", "weft", "bias"].map(row).join("")}
    <div class="ins"><div class="grid2"><label class="f">Strip width (mm)<input type="text" id="tW" value="50"></label><label class="f">Between the jaws (mm)<input type="text" id="tL" value="100"></label></div>
    <div class="grid2"><label class="f">10 × 10 cm square weighs (g)<input type="text" id="tSq" placeholder="e.g. 1.5"></label>
      <label class="f">Droop at ${cmIn(10)} ${u} overhang (${u})<input type="text" id="tDroop" placeholder="e.g. ${cmIn(6)}"></label></div>
    <div class="grid2"><label class="f">Name<input type="text" id="tName" value="My fabric"></label>
      <label class="f">Feel<select id="tFric"><option value="slippery">slippery</option><option value="normal" selected>normal</option><option value="grippy">grippy</option></select></label></div></div>
    <div class="row"><button class="btn primary" id="tGo">Make my fabric</button><span id="tOut" class="lead" style="font-size:13px"></span></div></div>`);
  const plot = () => {
    const c = $("#tPlot"); if (!c) return; const x = c.getContext("2d"); x.clearRect(0, 0, c.width, c.height);
    const cols = {warp: "#2f6fbf", weft: "#d0742c", bias: "#2f9a7a"};
    const all = Object.entries(TESTER.tests).filter(([k, v]) => v && v.length);
    if (TESTER.rec) all.push([TESTER.rec.dir, TESTER.rec.samples]);
    let mx = 1, mf = 0.5; for (const [, S] of all) for (const [e, f] of S) { mx = Math.max(mx, e); mf = Math.max(mf, f) }
    x.font = "11px system-ui"; x.fillStyle = "#888"; x.fillText(`${mx.toFixed(1)} mm`, c.width - 50, c.height - 4); x.fillText(`${mf.toFixed(1)} N`, 4, 12);
    for (const [d, S] of all) { x.strokeStyle = cols[d]; x.lineWidth = 2; x.beginPath();
      S.forEach(([e, f], i) => { const px = e / mx * (c.width - 10) + 5, py = c.height - 5 - f / mf * (c.height - 20); i ? x.lineTo(px, py) : x.moveTo(px, py) }); x.stroke() }
  };
  const status = () => ["warp", "weft", "bias"].forEach(d => { const S = TESTER.tests[d], el = $("#tst_" + d); if (el) el.textContent = S && S.length ? `${S.length} readings, up to ${Math.max(...S.map(r => r[0])).toFixed(1)} mm / ${Math.max(...S.map(r => r[1])).toFixed(2)} N` : "not tested" });
  status(); plot();
  const send = async t => { if (TESTER.writer) await TESTER.writer.write(new TextEncoder().encode(t + "\n")) };
  $("#tConn").onclick = async () => {
    if (!("serial" in navigator)) { toast("This browser can't talk to USB devices: use Chrome or Edge, or load CSV files"); return }
    try {
      const port = await navigator.serial.requestPort(); await port.open({baudRate: 115200});
      TESTER.port = port; TESTER.writer = port.writable.getWriter();
      $("#tStat").textContent = "connected"; $("#tTare").disabled = $("#tZero").disabled = false;
      const reader = TESTER.reader = port.readable.pipeThrough(new TextDecoderStream()).getReader(); let buf = "";
      (async () => { while (true) { const {value, done} = await reader.read(); if (done) break; buf += value; let k;
        while ((k = buf.indexOf("\n")) >= 0) { const line = buf.slice(0, k).trim(); buf = buf.slice(k + 1);
          if (line.startsWith("#")) { $("#tStat") && ($("#tStat").textContent = line.slice(1).trim()); continue }
          const p = line.split(",").map(Number); if (p.length >= 3 && TESTER.rec && p.every(v => !isNaN(v))) { TESTER.rec.samples.push([p[1], p[2]]); if (TESTER.rec.samples.length % 4 === 0) plot() } } } })();
    } catch (e) { toast("Couldn't connect: " + e.message) }
  };
  $("#tTare").onclick = () => send("t"); $("#tZero").onclick = () => send("z");
  $$("[data-rec]").forEach(b => b.onclick = async () => {
    const d = b.dataset.rec;
    if (TESTER.rec && TESTER.rec.dir === d) { await send("x"); TESTER.tests[d] = TESTER.rec.samples; TESTER.rec = null; b.textContent = "● Record"; status(); plot(); return }
    if (!TESTER.port) { toast("Connect the tester first (or load a CSV)"); return }
    TESTER.rec = {dir: d, samples: []}; b.textContent = "■ Stop"; await send("s");
  });
  $$("[data-csv]").forEach(inp => inp.onchange = async () => {
    const f = inp.files[0]; if (!f) return; const txt = await f.text();
    TESTER.tests[inp.dataset.csv] = txt.split(/\r?\n/).map(l => l.split(/[,;\t]/).map(Number)).filter(r => r.length >= 2 && r.every(v => !isNaN(v)))
      .map(r => r.length >= 3 ? [r[1], r[2]] : [r[0], r[1]]);
    status(); plot();
  });
  $("#tGo").onclick = async () => {
    const num = id => { const v = parseFloat($(id).value); return isNaN(v) ? null : v };
    if (!TESTER.tests.warp) { $("#tOut").textContent = "Test a strip along the grain first"; return }
    if (num("#tSq") == null || num("#tDroop") == null) { $("#tOut").textContent = "Fill in the weight and the droop"; return }
    $("#tGo").disabled = true; $("#tOut").textContent = "Fitting the curves and running the droop test (about 20 s)…";
    try {
      const tests = Object.entries(TESTER.tests).filter(([, v]) => v).map(([dir, samples]) => ({dir, samples, gauge_mm: num("#tL"), width_mm: num("#tW")}));
      const r = await api("/api/tester_fit", {name: $("#tName").value, tests, square_g: num("#tSq"), droop_cm: fromUnit(num("#tDroop")), overhang_cm: 10, friction: $("#tFric").value});
      ST.init.fabrics = ST.init.fabrics.filter(f => f.key !== r.key); ST.init.fabrics.push({key: r.key, name: r.fabric.name, gsm: r.fabric.gsm, mine: true});
      ST.fabric = r.key; renderFabrics();
      const R = r.report;
      $("#tOut").innerHTML = `Saved <b>${r.fabric.name}</b>: ${r.fabric.gsm} g/m², across the grain ${R.weft_ratio.toFixed(1)}× and on the bias ${R.bias_ratio.toFixed(1)}× as stretchy as along it` +
        (R.lock_strain < 5 ? `, locks up at ${(R.lock_strain * 100).toFixed(1)} %` : "") + ".";
    } catch (e) { $("#tOut").textContent = "Couldn't make it: " + e.message }
    $("#tGo").disabled = false;
  };
}
