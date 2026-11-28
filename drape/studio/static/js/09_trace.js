// drape studio: trace a pattern from a photo
// (classic script: shares one global scope with the others, loaded in order by index.html)
// ------------------------------------------------------------ trace from a photo
$("#traceBtn").onclick = () => {
  modal("Trace from a photo", `<div style="display:flex;flex-direction:column;gap:10px;max-width:900px">
    <p class="lead">Lay the garment (or a paper pattern) flat on a plain surface that contrasts with it, with a ruler or a sheet of
      letter paper next to it. Take the photo from straight above.</p>
    <div class="row"><label class="btn small primary" style="cursor:pointer">Choose photo<input type="file" id="trFile" accept="image/*" hidden></label>
      <span id="trHint" class="lead" style="font-size:13px"></span></div>
    <div style="position:relative;display:none" id="trWrap"><canvas id="trCanvas" style="max-width:100%;border-radius:8px;cursor:crosshair;touch-action:none"></canvas></div>
    <div class="row" id="trScale" style="display:none"><span>Distance between the two marks</span>
      <div class="inp" style="width:120px"><input id="trLen" inputmode="decimal" value="${ST.units === "in" ? "11" : "28"}"><span>${ST.units}</span></div>
      <button class="btn small" id="trReset">Re-mark</button><button class="btn small primary" id="trGo">Trace</button></div>
    <div id="trOut"></div></div>`);
  const T = {img: null, pts: [], res: null, url: null};
  const cv = $("#trCanvas"), cx = cv.getContext("2d");
  const draw = () => {
    if (!T.img) return; cx.drawImage(T.img, 0, 0, cv.width, cv.height); const k = cv.width / T.img.naturalWidth;
    if (T.res) { cx.strokeStyle = "#ff3b7f"; cx.lineWidth = 3; cx.beginPath(); T.res.outline_px.forEach(([x, y], i) => i ? cx.lineTo(x * k, y * k) : cx.moveTo(x * k, y * k)); cx.closePath(); cx.stroke() }
    cx.fillStyle = "#ffd400"; cx.strokeStyle = "#ffd400"; cx.lineWidth = 2;
    T.pts.forEach(([x, y]) => { cx.beginPath(); cx.arc(x * k, y * k, 6, 0, 7); cx.fill() });
    if (T.pts.length === 2) { cx.beginPath(); cx.moveTo(T.pts[0][0] * k, T.pts[0][1] * k); cx.lineTo(T.pts[1][0] * k, T.pts[1][1] * k); cx.stroke() }
  };
  const hint = () => $("#trHint").textContent = !T.img ? "" : T.pts.length < 2 ? `Tap both ends of something you know the length of (${2 - T.pts.length} to go)` : "Type that length, then Trace";
  $("#trFile").onchange = e => {
    const f = e.target.files[0]; if (!f) return; const rd = new FileReader();
    rd.onload = () => { T.url = rd.result; const im = new Image(); im.onload = () => { T.img = im; const W = Math.min(860, im.naturalWidth); cv.width = W; cv.height = W * im.naturalHeight / im.naturalWidth; $("#trWrap").style.display = "block"; T.pts = []; T.res = null; draw(); hint() }; im.src = rd.result };
    rd.readAsDataURL(f);
  };
  cv.onclick = e => { if (!T.img || T.pts.length >= 2) return; const r = cv.getBoundingClientRect(), k = T.img.naturalWidth / r.width;
    T.pts.push([(e.clientX - r.left) * k, (e.clientY - r.top) * k]); draw(); hint(); if (T.pts.length === 2) $("#trScale").style.display = "flex" };
  $("#trReset").onclick = () => { T.pts = []; T.res = null; $("#trScale").style.display = "none"; $("#trOut").innerHTML = ""; draw(); hint() };
  $("#trGo").onclick = async () => {
    $("#trOut").innerHTML = `<p class="lead">Tracing…</p>`;
    try {
      T.res = await api("/api/trace", {image: T.url, p1: T.pts[0], p2: T.pts[1], length_cm: fromUnit(parseFloat($("#trLen").value))}); draw();
      $("#trOut").innerHTML = `<div class="check ok"><span class="ic">✓</span><div><b>${fmtLen(T.res.width_cm)} wide × ${fmtLen(T.res.height_cm)} tall, ${T.res.edges.length} edges</b>
        <span class="tech">Pink is what was found. If it's wrong, try a plainer or more contrasting background.</span>
        <div class="row" style="margin-top:6px"><input type="text" id="trName" value="${uniqueName("traced", D().pieces.map(p => p.name))}" style="width:140px;padding:6px 8px;border:1px solid var(--line);border-radius:8px">
        <button class="btn small primary" id="trAdd">Add as a piece</button></div></div></div>`;
      $("#trAdd").onclick = () => {
        const nm = ($("#trName").value || "traced").replace(/[.\s]+/g, "_");
        const pc = {name: uniqueName(nm, D().pieces.map(p => p.name)), shape: {type: "custom"}, at: [0, 0], verts: T.res.verts,
          edges: T.res.edges.map(e => ({name: e.name, c1: null, c2: null, elastic: false, ...(e.pts ? {pts: e.pts} : {})})),
          place: {mode: "wrap", rotate: 0, offset_cm: 1.5, at: "center"}};
        D().pieces.push(pc); DS.sel = pc.name; tidy(); dsChanged(true, true); $("#modal").classList.remove("show");
        toast("Traced. A whole garment comes in as one piece: use ✂ Cut to split it (front/sleeves), then place it on the body.", 6000);
      };
    } catch (err) { $("#trOut").innerHTML = `<div class="err">${err.message}</div>` }
  };
};
