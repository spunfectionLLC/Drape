// drape studio: the AI designer (header ✦ AI): a request in words and a sketch -> a builder model writes the design ->
// checks -> drape -> renders -> a critic model judges it -> the builder fixes it -> ... (docs/disclosures/2026-11-28_*).
// (classic script: shares one global scope with the others, loaded in order by index.html)
//
// The API key: typed by the person each visit, read from its field only when a request is sent, and sent only to
// Anthropic (api.anthropic.com). Never stored: not in localStorage, the project, autosave, a file, or sent to our server.
const AI_MODELS = {
  opus: {id: "claude-opus-5-5", label: "Claude Opus 5.5 (best)", in: 4, out: 20, cr: 0.2},
  sonnet: {id: "claude-sonnet-5-5", label: "Claude Sonnet 5.5 (half the price)", in: 2, out: 10, cr: 0.1},
};
const AI_API = "https://api.anthropic.com/v1/messages";
const AI_PENS = [["#d6453d", "remove / cut away"], ["#2f6fbf", "add / extend"], ["#1f9d55", "a new line (seam, neckline, hem)"], ["#222222", "notes and arrows"]];
const AI = {busy: false, ctrl: null, versions: [], cost: 0, pen: AI_PENS[1][0], strokes: [], bg: null, ref: null, log: [], mode: null};

// ------------------------------------------------------------------ the panel
function aiOpen(show = true) {
  const p = $("#aipanel"); p.hidden = !show; if (!show) return;
  if (!p.dataset.built) aiBuild();
  aiMode(AI.mode || (ST.scratch && ST.design && ST.design.pieces.length || ST.block ? "edit" : "scratch"));
  aiDrawPad();
}
function aiBuild() {
  const p = $("#aipanel"); p.dataset.built = "1";
  p.innerHTML = `<div class="aihead"><b>✦ Design with AI</b><button class="iconbtn" id="aiClose" title="Close">✕</button></div>
  <label class="f">Your Anthropic API key<input type="password" id="aikey" autocomplete="off" spellcheck="false" placeholder="sk-ant-…"></label>
  <p class="lead aismall">Kept only in this tab while it's open and sent only to Anthropic, never saved or sent to us. You'll type it again next visit.
    Your request, sketch, measurements, design and renders go to Anthropic with it, and the usage is billed to your key.
    <button class="btn small" id="aiForget">Forget the key</button></p>
  <div class="seg" id="aimode"><button data-m="scratch">Start from scratch</button><button data-m="edit">Edit this design</button></div>
  <label class="f">What should it make or change?<textarea id="aitext" rows="3" placeholder="A black knee-length A-line dress with a hood, lined in flannel…"></textarea></label>
  <div class="aipadbar"><span class="aismall">Sketch it (optional): draw on</span>
    <button class="chip" data-bg="3d" title="The 3D view as it is now">3D view</button><button class="chip" data-bg="pattern" title="The pattern pieces">Pattern</button>
    <button class="chip" data-bg="blank">Blank</button><button class="chip" data-bg="file">Your image…</button></div>
  <canvas id="aipad" width="800" height="600" title="Draw your changes"></canvas>
  <div class="aipadbar">${AI_PENS.map(([c, l]) => `<button class="aipen ${c === AI.pen ? "on" : ""}" data-pen="${c}" style="background:${c}" title="${l}"></button>`).join("")}
    <button class="chip" data-pen="text" title="Click on the sketch to put a note there">Aa note</button>
    <button class="chip" id="aiUndo">Undo</button><button class="chip" id="aiClear">Clear</button>
    <span class="aismall" id="aipenhint"></span></div>
  <div class="grid2"><label class="f">Model<select id="aimodel">${Object.entries(AI_MODELS).map(([k, m]) => `<option value="${k}">${m.label}</option>`).join("")}</select></label>
    <label class="f">Rounds (build, drape, review)<select id="airounds">${[1, 2, 3, 4, 5].map(n => `<option ${n === 3 ? "selected" : ""}>${n}</option>`).join("")}</select></label></div>
  <div class="row" style="gap:8px"><button class="btn primary" id="aiGo" style="flex:1">✦ Make it</button><button class="btn" id="aiStop" disabled>Stop</button></div>
  <div class="aismall" id="aicost"></div>
  <div id="ailog" class="checks"></div>
  <div id="aiversions"></div>`;
  $("#aiClose").onclick = () => aiOpen(false);
  $("#aiForget").onclick = () => { $("#aikey").value = ""; toast("The key is cleared from this page", 2500) };
  $$("#aimode [data-m]").forEach(b => b.onclick = () => aiMode(b.dataset.m));
  $$("#aipanel [data-bg]").forEach(b => b.onclick = () => aiBackground(b.dataset.bg));
  $$("#aipanel [data-pen]").forEach(b => b.onclick = () => { AI.pen = b.dataset.pen; $$("#aipanel [data-pen]").forEach(x => x.classList.toggle("on", x === b)); aiPenHint() });
  $("#aiUndo").onclick = () => { AI.strokes.pop(); aiDrawPad() };
  $("#aiClear").onclick = () => { AI.strokes = []; aiDrawPad() };
  $("#aiGo").onclick = () => aiRun();
  $("#aiStop").onclick = () => { AI.stopped = true; if (AI.ctrl) AI.ctrl.abort() };
  aiPadEvents(); aiPenHint();
}
function aiMode(m) {
  AI.mode = m;
  $$("#aimode [data-m]").forEach(b => b.classList.toggle("on", b.dataset.m === m));
  $("#aitext").placeholder = m === "edit" ? "Make the skirt longer and add patch pockets; or draw it on the sketch…" : "A black knee-length A-line dress with a hood, lined in flannel…";
}
function aiPenHint() { const p = AI_PENS.find(x => x[0] === AI.pen); $("#aipenhint").textContent = AI.pen === "text" ? "click to place a note" : p ? p[1] : "" }

// ------------------------------------------------------------------ the sketch pad
function aiDrawPad() {
  const c = $("#aipad"); if (!c) return; const x = c.getContext("2d");
  x.fillStyle = "#fff"; x.fillRect(0, 0, c.width, c.height);
  if (AI.bg) { const s = Math.min(c.width / AI.bg.width, c.height / AI.bg.height), w = AI.bg.width * s, h = AI.bg.height * s; x.drawImage(AI.bg, (c.width - w) / 2, (c.height - h) / 2, w, h) }
  for (const st of AI.strokes) {
    if (st.text) { x.fillStyle = st.color; x.font = "bold 22px sans-serif"; x.fillText(st.text, st.pts[0][0], st.pts[0][1]); continue }
    x.strokeStyle = st.color; x.lineWidth = st.w; x.lineCap = x.lineJoin = "round"; x.beginPath();
    st.pts.forEach(([a, b], i) => i ? x.lineTo(a, b) : x.moveTo(a, b)); if (st.pts.length === 1) x.lineTo(st.pts[0][0] + 0.1, st.pts[0][1]); x.stroke();
  }
}
function aiPadEvents() {
  const c = $("#aipad"); let cur = null;
  const at = e => { const r = c.getBoundingClientRect(); return [(e.clientX - r.left) * c.width / r.width, (e.clientY - r.top) * c.height / r.height] };
  c.addEventListener("pointerdown", e => {
    if (AI.pen === "text") { const t = prompt("Note"); if (t) { AI.strokes.push({color: "#222222", text: t.slice(0, 120), pts: [at(e)]}); aiDrawPad() } return }
    cur = {color: AI.pen, w: 6, pts: [at(e)]}; AI.strokes.push(cur); c.setPointerCapture(e.pointerId); aiDrawPad();
  });
  c.addEventListener("pointermove", e => { if (!cur) return; cur.pts.push(at(e)); aiDrawPad() });
  const end = () => { cur = null }; c.addEventListener("pointerup", end); c.addEventListener("pointercancel", end);
}
async function aiBackground(kind) {
  const load = src => new Promise((ok, no) => { const im = new Image(); im.onload = () => ok(im); im.onerror = no; im.src = src });
  try {
    if (kind === "blank") AI.bg = null;
    else if (kind === "3d") {
      const v = GL.view, s = GL.snapshot([v.yaw], "image/png"); if (!s.length) { toast("Open the 3D view first (Try on, or ◐ 3D view in Design)", 4000); return }
      AI.bg = await load(s[0]);
    } else if (kind === "pattern") {
      const sv = $("#board"), r = sv && sv.getBoundingClientRect();
      if (!sv || !r.width) { toast("Open the pattern in Design first", 4000); return }
      const css = getComputedStyle(document.body);
      let xml = new XMLSerializer().serializeToString(sv).replace(/var\((--[\w-]+)\)/g, (m, v) => css.getPropertyValue(v).trim() || "#888");
      if (!/^<svg[^>]*\swidth=/.test(xml)) xml = xml.replace("<svg", `<svg width="${Math.round(r.width)}" height="${Math.round(r.height)}"`);
      if (!xml.includes("xmlns=")) xml = xml.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"');
      AI.bg = await load("data:image/svg+xml;charset=utf-8," + encodeURIComponent(xml));
    } else if (kind === "file") {
      const f = await new Promise(ok => { const i = document.createElement("input"); i.type = "file"; i.accept = "image/*"; i.onchange = () => ok(i.files[0]); i.click() });
      if (!f) return; AI.bg = await load(URL.createObjectURL(f));
    }
    AI.bgKind = kind; aiDrawPad();
  } catch (e) { toast("Couldn't use that as the sketch: " + e.message, 4000) }
}
// the sketch as images for the model: the marked-up one, and the clean one under it (when there's both)
function aiSketchImages() {
  if (!AI.strokes.length && !AI.bg) return [];
  const c = $("#aipad"), out = [{label: `The user's sketch (drawn on ${AI.bg ? {"3d": "the 3D view of the current drape", pattern: "the pattern pieces", file: "their own image"}[AI.bgKind] || "an image" : "a blank page"}). Pen colours: red = remove or cut away, blue = add or extend, green = a new line (seam, neckline, hem), black = notes and arrows.`, data: c.toDataURL("image/jpeg", 0.85)}];
  if (AI.bg && AI.strokes.length) {
    const k = document.createElement("canvas"); k.width = c.width; k.height = c.height; const x = k.getContext("2d");
    const keep = AI.strokes; AI.strokes = []; aiDrawPad(); x.drawImage(c, 0, 0); AI.strokes = keep; aiDrawPad();
    out.push({label: "The same image without the user's marks.", data: k.toDataURL("image/jpeg", 0.85)});
  }
  return out;
}

// ------------------------------------------------------------------ talking to the model
// one streamed Messages request; returns {content, stop, usage}. The key goes in this request's header and nowhere else.
async function aiCall(key, req) {
  for (let attempt = 0; ; attempt++) {
    try { return await aiCallOnce(key, req) }
    catch (e) {
      if (AI.stopped || attempt >= 2 || !e.retry) throw e;       // up to two retries
      const wait = Math.min(30, e.retryAfter || 5);
      aiStatus(`${e.message}: trying again in ${wait} s`);
      await new Promise(r => setTimeout(r, wait * 1000));
    }
  }
}
async function aiCallOnce(key, {model, system, messages, tools, effort}) {
  let res;
  try { res = await fetch(AI_API, {
    method: "POST", signal: AI.ctrl.signal,
    headers: {"content-type": "application/json", "x-api-key": key, "anthropic-version": "2026-10-21",
              "anthropic-dangerous-direct-browser-access": "true", "anthropic-beta": "server-side-fallback-2026-07-01"},
    body: JSON.stringify({model: model.id, max_tokens: 64000, stream: true, thinking: {type: "adaptive"}, output_config: {effort},
                          fallbacks: "default", system, messages, tools, tool_choice: {type: "auto"}}),
  }) } catch (e) {
    if (e.name === "AbortError") throw e;
    const err = new Error("couldn't reach the Anthropic API (offline, or blocked by a firewall or extension)"); err.retry = true; throw err;
  }
  if (!res.ok) {
    let msg = ""; try { msg = (await res.json()).error.message } catch (e) { msg = res.statusText }
    const why = {401: "the API key was refused: check it", 403: "this key isn't allowed to use that model", 429: "rate limited: wait a minute and try again",
                 529: "the API is overloaded right now: try again shortly"}[res.status] || msg;
    const err = new Error(`${res.status}: ${why}`); err.status = res.status;
    err.retry = res.status === 429 || res.status === 529 || res.status >= 500;
    err.retryAfter = +res.headers.get("retry-after") || 0; throw err;
  }
  const rd = res.body.getReader(), dec = new TextDecoder(), content = [], usage = {in: 0, out: 0, cw: 0, cr: 0};
  let buf = "", stop = null, ended = false;
  const handle = ev => {
    if (ev.type === "message_start") { const u = ev.message.usage || {}; usage.in += u.input_tokens || 0; usage.cw += u.cache_creation_input_tokens || 0; usage.cr += u.cache_read_input_tokens || 0 }
    else if (ev.type === "content_block_start") { content[ev.index] = {...ev.content_block}; if (content[ev.index].type === "tool_use") { content[ev.index]._json = ""; content[ev.index].input = {} } }
    else if (ev.type === "content_block_delta") {
      const b = content[ev.index], d = ev.delta;
      if (d.type === "text_delta") b.text = (b.text || "") + d.text;
      else if (d.type === "input_json_delta") b._json += d.partial_json;
      else if (d.type === "thinking_delta") b.thinking = (b.thinking || "") + d.thinking;
      else if (d.type === "signature_delta") b.signature = (b.signature || "") + d.signature;
      if (d.type === "input_json_delta") aiStatus(`writing… ${Math.round(b._json.length / 1000)} k characters`);
    }
    else if (ev.type === "content_block_stop") { const b = content[ev.index]; if (b && b.type === "tool_use") { try { b.input = b._json ? JSON.parse(b._json) : {} } catch (e) { b.input = {}; b._bad = true } delete b._json } }
    else if (ev.type === "message_delta") { stop = ev.delta.stop_reason || stop; if (ev.usage) usage.out = ev.usage.output_tokens || usage.out }
    else if (ev.type === "message_stop") ended = true;
    else if (ev.type === "error") {
      const err = new Error(ev.error ? `${ev.error.type || "error"}: ${ev.error.message}` : "the stream failed");
      err.retry = !!(ev.error && /overloaded|api_error/.test(ev.error.type || "")); throw err;
    }
  };
  for (;;) {
    const {value, done} = await rd.read(); if (done) break;
    buf += dec.decode(value, {stream: true}); let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
      const data = chunk.split("\n").filter(l => l.startsWith("data:")).map(l => l.slice(5).trim()).join("");
      if (data) handle(JSON.parse(data));
    }
  }
  if (!ended) { const err = new Error("the answer was cut off (the connection closed early)"); err.retry = true; throw err }
  AI.cost += (usage.in * model.in + usage.cw * model.in * 1.25 + usage.cr * model.cr + usage.out * model.out) / 1e6;
  $("#aicost").textContent = `Spent so far with this panel: about $${AI.cost.toFixed(2)} (on your key)`;
  return {content: content.filter(Boolean), stop, usage};
}
const aiImg = dataUrl => ({type: "image", source: {type: "base64", media_type: dataUrl.slice(5, dataUrl.indexOf(";")), data: dataUrl.slice(dataUrl.indexOf(",") + 1)}});
// an image at most `max` px on its long side, as a JPEG (renders come at the canvas's device-pixel size: 3000+ px
// costs several times the tokens for nothing the model can use)
async function aiShrink(dataUrl, max = 1024) {
  const im = new Image(); im.src = dataUrl; await im.decode();
  const s = Math.min(1, max / Math.max(im.width, im.height)), c = document.createElement("canvas");
  c.width = Math.round(im.width * s); c.height = Math.round(im.height * s);
  const x = c.getContext("2d"); x.fillStyle = "#fff"; x.fillRect(0, 0, c.width, c.height); x.drawImage(im, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", 0.85);
}

const AI_DESIGN_TOOL = {
  name: "submit_design", eager_input_streaming: true,
  description: "Hand over the garment design. Call it exactly once per reply, with the whole design (every piece and seam).",
  input_schema: {type: "object", properties: {
    plan: {type: "string", description: "Short plan: each piece and its key dimensions worked out from the measurements (show the arithmetic), every seam with both edges' lengths, every opening; and how you read each mark on the user's sketch."},
    design: {type: "object", description: "The design: {pieces: [...], seams: [...]} in the editor format of the specification (verts + edges)."},
    fabric: {type: "string", description: "The garment's fabric key."},
    reading: {type: "string", description: "One plain sentence for the user: how you read the request and the sketch, naming the parts of the garment they refer to (\"the hood is too small: I'll make the hood piece bigger\")."},
    summary: {type: "string", description: "One or two plain sentences for the user: what you made or changed."},
  }, required: ["reading", "plan", "design", "summary"]},
};
const AI_REVIEW_TOOL = {
  name: "submit_review", strict: true,
  description: "Hand over the review of the draped garment. Call it exactly once.",
  input_schema: {type: "object", additionalProperties: false, required: ["pass", "scores", "corrections", "summary"], properties: {
    pass: {type: "boolean", description: "true only when the garment clearly matches the request and has no problem-level fit issue or physical fault"},
    scores: {type: "object", additionalProperties: false, required: ["request", "fit", "construction", "physics"], properties: {
      request: {type: "integer", description: "1-10"}, fit: {type: "integer", description: "1-10"},
      construction: {type: "integer", description: "1-10"}, physics: {type: "integer", description: "1-10"}}},
    corrections: {type: "array", description: "At most 6, most important first", items: {type: "object", additionalProperties: false, required: ["where", "change"], properties: {
      where: {type: "string", description: "piece and edge names from the design, or a body region"},
      change: {type: "string", description: "what to change, with the amount in cm where possible"}}}},
    summary: {type: "string", description: "One or two plain sentences for the user"},
  }},
};
function aiBuilderSystem() {
  const I = ST.init;
  return [{type: "text", cache_control: {type: "ephemeral"}, text:
`You are the patternmaker of the AI designer in Spunfection Studio, a free web app that sews flat pattern pieces together and drapes them on a 3D avatar of the wearer with a cloth simulation. You design one garment at a time as a design object in the editor format of the specification below, and you hand it over by calling the submit_design tool, exactly once per reply.

How to work:
- Draft to the wearer's measurements plus ease, and show the arithmetic in "plan".
- Edges are straight or one cubic Bézier (c1, c2). Use "pts" only when a curve can't be one cubic. Centimetres, y up, counter-clockwise outlines, symmetric pieces mirrored about x = 0 with _r / _l names.
- Every seam: work out both edges' lengths; they must match unless the seam's ease says how much longer one is.
- Place every piece: front pieces at a *_front landmark, back pieces at *_back, sleeves with place.arm, bands with place.loop.
- Patch pockets, patches and appliqués are topstitched onto their piece with place.on (pos, sewn), never with seams or by cutting the piece.
- When editing, the garment stays the same kind of garment (a dress stays a dress) unless the request plainly asks for a different one. The request's words name parts of the current design: map each to its pieces ("hoodie" or "hood" is the hood piece, "skirt" the part below the waist, "sleeve" the sleeve pieces). Change only what the request, the sketch or the corrections ask for; keep every other piece, edge name, seam and placement exactly as it is. Always return the whole design, not just the changes.
- Allowed fabric keys: ${I.fabrics.map(f => f.key).join(", ")}. Landmarks: ${Object.keys(I.landmarks).join(", ")}. Hem styles: ${Object.keys(I.hem_styles).join(", ")}. Interfacings: ${I.interfacings.map(f => f.key).join(", ")}.
- The user may sketch: red = remove or cut away, blue = add or extend, green = a new line (seam, neckline, hem), black = notes and arrows. Say in "plan" how you read each mark.
- Every body is valid: design for the wearer, never comment on their body.

<specification>
${AI_SPEC}
</specification>

<example_design>
${JSON.stringify(AI_EXAMPLE)}
</example_design>`}];
}
const AI_CRITIC_SYSTEM = [{type: "text", cache_control: {type: "ephemeral"}, text:
`You are the critic of the AI designer in Spunfection Studio. You judge one garment, sewn and draped by a cloth simulation on the wearer's avatar, against what the user asked for, and you hand over your verdict by calling submit_review, exactly once.

You get the request, the user's sketch if there is one, renders of the drape (front, back, side), the simulation's fit numbers and notes, and the design file.
Scores, 1-10:
- request: silhouette, length, neckline, sleeves, details, colour and style words;
- fit: tight or loose spots, riding up, pieces off-centre, hems uneven where they should be level;
- construction: seams that won't sew, openings too small to get into, hems that won't fold, missing closures;
- physics: cloth inside the body, twisted seams, linings showing through, pieces caught on the wrong side.
Rely on the numbers for fit and on the images for style, proportion and visible faults. Every body is valid: judge the garment, never the body.
pass is true only when the garment clearly matches the request and has no problem-level fit issue or physical fault.
corrections: at most 6, most important first, each specific and actionable, naming pieces and edges from the design and giving amounts in cm where you can ("raise front.hem and back.hem by 15 cm").
For an edit, judge the parts the request names (read its words as parts of that garment: "the hoodie" on a dress is its hood). Your corrections stay within those parts, except for physical faults (cloth inside the body, open or twisted seams). Fit notes about parts the request didn't name don't fail the edit: mention them in the summary as an idea instead.`}];

// ------------------------------------------------------------------ checking a design before it's used
// what kind of garment a design is, and its pieces in a line each (the builder and the critic get it for an edit)
function aiGarmentKind(d) {
  const t = (d.pieces || []).map(p => p.place && p.place.template && p.place.template.block).find(Boolean);
  return (d.from_block || t || ST.block || "garment").replace(/_/g, " ");
}
function aiPieceList(d) {
  return (d.pieces || []).map(p => {
    const pl = p.place || {}, xs = (p.verts || []).map(v => v[0]), ys = (p.verts || []).map(v => v[1]);
    const where = pl.landmark || (pl.template && `the pattern's ${pl.template.piece}`) || (pl.arm && `round the ${pl.arm > 0 ? "right" : "left"} arm`) || (pl.loop && `round ${pl.loop.join(" + ")}`) || (pl.on && `sewn on ${pl.on}`) || "placed";
    return `- ${p.name} (${p.role || "piece"}, ${where}, about ${Math.round(Math.max(...xs) - Math.min(...xs))} x ${Math.round(Math.max(...ys) - Math.min(...ys))} cm)`;
  }).join("\n");
}
// an edit keeps its garment: most of the pieces from before the request are still there (by name, or split into
// parts named after them, front -> front_mid). Returns the problem, or "".
function aiEditGuard(orig, d) {
  if (!orig || !orig.pieces.length) return "";
  const names = d.pieces.map(p => p.name), kept = n => names.some(m => m === n || m.startsWith(n + "_"));
  const lost = orig.pieces.map(p => p.name).filter(n => !kept(n));
  const body = orig.pieces.filter(p => (p.role || "body") === "body").map(p => p.name), bodyLost = body.filter(n => !kept(n));
  if (lost.length * 2 > orig.pieces.length || (body.length && bodyLost.length * 2 > body.length))
    return `This is an edit of the user's ${aiGarmentKind(orig)}, but the design no longer keeps it: ${lost.length} of its ${orig.pieces.length} pieces are gone (${lost.join(", ")}). Keep the existing garment and its pieces and change only the parts the request names (it doesn't ask for a different garment: to make a new one the user starts from scratch).`;
  return "";
}
function aiCheck(d) {
  const E = [], I = ST.init, fab = new Set(I.fabrics.map(f => f.key)), lms = new Set(Object.keys(I.landmarks));
  const NAME = /^[A-Za-z][A-Za-z0-9_]{0,39}$/, num = v => typeof v === "number" && Number.isFinite(v) && Math.abs(v) < 1000;
  const pt = p => Array.isArray(p) && p.length === 2 && num(p[0]) && num(p[1]);
  if (!d || !Array.isArray(d.pieces) || !d.pieces.length) return {errors: ["design.pieces must be a non-empty list"]};
  if (d.pieces.length > 40) E.push("more than 40 pieces");
  d.seams = Array.isArray(d.seams) ? d.seams : [];
  const pieces = {}, used = new Map();
  for (const p of d.pieces) {
    const at = `piece "${p && p.name}"`;
    if (!p || !NAME.test(p.name || "")) { E.push(`${at}: name must be letters, digits and _ (starting with a letter)`); continue }
    if (pieces[p.name]) { E.push(`${at}: two pieces have this name`); continue }
    pieces[p.name] = p;
    if (!Array.isArray(p.verts) || p.verts.length < 3 || !p.verts.every(pt)) { E.push(`${at}: verts must be at least 3 [x, y] points in cm`); continue }
    if (!Array.isArray(p.edges) || p.edges.length !== p.verts.length) { E.push(`${at}: needs exactly one edge per corner (${p.verts.length} corners, ${Array.isArray(p.edges) ? p.edges.length : 0} edges)`); continue }
    const names = new Set();
    p.edges.forEach((e, i) => {
      if (!e || !NAME.test(e.name || "")) { E.push(`${at} edge ${i}: needs a name of letters, digits and _`); return }
      if (names.has(e.name)) E.push(`${at}: two edges are called ${e.name}`); names.add(e.name);
      if (e.c1 != null || e.c2 != null) { if (!pt(e.c1) || !pt(e.c2)) E.push(`${at}.${e.name}: c1 and c2 must both be [x, y], or both null`) } else { e.c1 = null; e.c2 = null }
      if (e.pts != null) {
        if (!Array.isArray(e.pts) || e.pts.length < 2 || e.pts.length > 300 || !e.pts.every(pt)) E.push(`${at}.${e.name}: pts must be 2-300 [x, y] points`);
        else { e.pts[0] = [...p.verts[i]]; e.pts[e.pts.length - 1] = [...p.verts[(i + 1) % p.verts.length]] }   // ends on its corners
      }
      if (e.hem && !(e.hem.style in I.hem_styles)) E.push(`${at}.${e.name}: hem style must be one of ${Object.keys(I.hem_styles).join(", ")}`);
      e.elastic = !!e.elastic;
    });
    const pl = p.place || {};
    // every way the studio places a piece (a library pattern's pieces use place.template; tapped ones place.anchor)
    if (!(lms.has(pl.landmark) || pl.arm || (Array.isArray(pl.loop) && pl.loop.length) || pl.on || pl.template || pl.glove || pl.layer_of
          || (Array.isArray(pl.anchor) && pl.anchor.length === 3 && pl.anchor.every(num))))
      E.push(`${at}: place it on the body (place.landmark, place.arm, place.loop or place.on)`);
    if (pl.landmark && !lms.has(pl.landmark)) E.push(`${at}: unknown landmark ${pl.landmark}`);
    if (p.fabric && !fab.has(p.fabric)) E.push(`${at}: unknown fabric ${p.fabric}`);
    if (p.look && p.look.print && !PRINTS.some(([k]) => k === p.look.print)) E.push(`${at}: look.print must be one of ${PRINTS.map(x => x[0]).filter(k => k !== "upload").join(", ")}`);
    p.shape = {type: "custom"}; if (!pt(p.at)) p.at = [0, 0]; p.place = {rotate: 0, offset_cm: 1, at: "center", mode: "wrap", ...pl};
  }
  for (const p of Object.values(pieces)) {          // sewn onto a piece: that piece exists, its stitched edges are real
    const pl = p.place || {};
    if (pl.on && !pieces[pl.on]) E.push(`piece "${p.name}": place.on names "${pl.on}", which isn't a piece`);
    if (pl.on && pl.sewn != null && (!Array.isArray(pl.sewn) || pl.sewn.some(n => !p.edges.some(e => e.name === n)))) E.push(`piece "${p.name}": place.sewn must list its own edge names`);
    if (pl.on && pl.pos != null && !pt(pl.pos)) E.push(`piece "${p.name}": place.pos must be [x, y] in cm on ${pl.on}`);
  }
  if (E.length) return {errors: E};
  // outlines that cross themselves can't be meshed
  for (const p of Object.values(pieces)) {
    const ring = p.edges.flatMap((e, i) => edgePts(p, i).slice(0, -1)), n = ring.length;
    const cross = (a, b, c, d) => { const o = (p, q, r) => Math.sign((q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])); return o(a, b, c) * o(a, b, d) < 0 && o(c, d, a) * o(c, d, b) < 0 };
    outer: for (let i = 0; i < n; i++) for (let j = i + 2; j < n; j++) { if (i === 0 && j === n - 1) continue; if (cross(ring[i], ring[(i + 1) % n], ring[j], ring[(j + 1) % n])) { E.push(`piece "${p.name}": its outline crosses itself`); break outer } }
  }
  // seams: real edges, each sewn once, lengths that match (or say how they differ)
  const len = ref => { const [pn, en] = String(ref).split("."), p = pieces[pn]; if (!p) return null; const i = p.edges.findIndex(e => e.name === en); return i < 0 ? null : plen(edgePts(p, i)) };
  d.seams.forEach((s, k) => {
    const la = len(s && s.a), lb = len(s && s.b);
    if (la == null || lb == null) { E.push(`seam ${k} (${s && s.a} - ${s && s.b}): both sides must be existing "piece.edge" names`); return }
    for (const r of [s.a, s.b]) { used.set(r, (used.get(r) || 0) + 1); if (used.get(r) === 2) E.push(`${r} is sewn more than once (split the edge to sew it to two places)`) }
    s.ease = num(s.ease) ? Math.max(0, s.ease) : 0;
    const want = 1 + s.ease, got = Math.max(la, lb) / Math.max(1e-6, Math.min(la, lb));
    if (Math.abs(la - lb) > Math.max(0.5, 0.02 * Math.min(la, lb)) && Math.abs(got - want) > 0.05 * want)
      E.push(`seam ${s.a} (${la.toFixed(1)} cm) - ${s.b} (${lb.toFixed(1)} cm): lengths differ by ${Math.abs(la - lb).toFixed(1)} cm with ease ${s.ease}; make them match, or set ease to ${(got - 1).toFixed(3)} if one is gathered or stretched on purpose`);
  });
  return {errors: E, design: d};
}

// ------------------------------------------------------------------ the loop
function aiStatus(t) { const s = $("#ailog .aicur span"); if (s) s.textContent = t }
function aiLog(text, kind = "note") {
  $$("#ailog .aicur").forEach(x => x.classList.remove("aicur"));
  const div = document.createElement("div"); div.className = `check ${kind === "ok" ? "ok" : kind === "bad" ? "bad" : "note"} aicur`;
  div.innerHTML = `<span class="ic">${kind === "ok" ? "✓" : kind === "bad" ? "!" : "…"}</span><div><b>${esc(text)}</b> <span class="tech"></span></div>`;
  $("#ailog").appendChild(div); div.scrollIntoView({block: "nearest"});
}
async function aiApply(design, fabric, newGarment_) {
  if (newGarment_) {
    const g = newGarment(("AI: " + ($("#aitext").value.trim() || "design")).slice(0, 40), {layer: topLayer() + 1});
    PROJECT.garments.push(g); setActiveGarment(g.id);
  }
  ST.design = JSON.parse(JSON.stringify(design)); ST.scratch = true; ST.drape = null; ST.sfull = null;
  if (fabric && ST.init.fabrics.some(f => f.key === fabric)) { ST.fabric = fabric; renderFabrics() }
  tidy(); DS.view = null; DS.sel = null; renderGarmentList(); go("fit"); pushHist();
  await dsRefresh();
}
async function aiRun() {
  if (AI.busy) return;
  const key = $("#aikey").value.trim(), request = $("#aitext").value.trim();
  if (!key) { toast("Type your Anthropic API key first", 3500); $("#aikey").focus(); return }
  if (!request && !AI.strokes.length && !AI.bg) { toast("Say what to make or change, or draw it", 3500); return }
  if (!ST.avatar) { toast("Make your avatar first (Body)", 3500); return }
  AI.busy = true; AI.stopped = false;   // from here on: no second run, and "busy" covers the slow steps before the first request
  $("#aiGo").disabled = true; $("#aiStop").disabled = false;
  try { await aiRun2(key, request) } finally { AI.busy = false; AI.ctrl = null; $("#aiGo").disabled = false; $("#aiStop").disabled = true }
}
async function aiRun2(key, request) {
  const sketch = await Promise.all(aiSketchImages().map(async s => ({...s, data: await aiShrink(s.data)})));
  const model = AI_MODELS[$("#aimodel").value], rounds = +$("#airounds").value, fromScratch = AI.mode === "scratch";
  if (!fromScratch && !ST.scratch && ST.block) {      // a pattern from the library: edited as a free-form design
    try {
      const r = await api("/api/to_scratch", {avatar: ST.avatar.id, block: ST.block, choices: ST.choices, params: ST.params});
      ST.design = r.design; ST.scratch = true; ST.drape = null; ST.sfull = null; tidy(); DS.view = null; renderGarments(); pushHist();
    } catch (e) { toast("Couldn't turn the pattern into an editable design: " + e.message, 5000); return }
  }
  if (!fromScratch && !(ST.design && ST.design.pieces.length)) { toast("There's no design to edit yet: pick Start from scratch, or choose a garment first", 4500); return }
  if (AI.stopped) { aiLog("Stopped.", "note"); return }
  AI.ctrl = new AbortController();
  $("#ailog").innerHTML = "";
  let design = fromScratch ? null : JSON.parse(JSON.stringify(ST.design)), verdict = null, renders = [], lastScore = -1, flat = 0, made = false;
  const orig = design && JSON.parse(JSON.stringify(design));        // the garment from before this request: every round keeps it
  try {
    for (let round = 1; round <= rounds && !AI.stopped; round++) {
      // 1. the builder writes (or fixes) the design
      aiLog(`Round ${round}: the builder is ${design ? "revising" : "drafting"} the design`);
      const txt = [`Request: ${request || "(see the sketch)"}`, `Mode: ${design ? "edit the current design" : "start from scratch"}`,
        `Wearer's measurements (cm): ${JSON.stringify(ST.meas)}`, `Garment fabric now: ${ST.fabric}`];
      if (orig) txt.push(`This is an edit of the user's ${aiGarmentKind(orig)}. Before this request it had these pieces:\n${aiPieceList(orig)}\nKeep it a ${aiGarmentKind(orig)}: the request's words name parts of it.`);
      if (design) txt.push(`Current design (editor format):\n${JSON.stringify(design)}`);
      if (verdict) txt.push(`Round ${round}. The critic's review of the last drape (scores ${JSON.stringify(verdict.scores)}): ${verdict.summary}\nCorrections:\n${verdict.corrections.map((c, i) => `${i + 1}. ${c.where}: ${c.change}`).join("\n")}`);
      const content = [{type: "text", text: txt.join("\n\n")}];
      for (const s of sketch) content.push({type: "text", text: s.label}, aiImg(s.data));
      ["front", "back", "side"].forEach((v, i) => { if (renders[i]) content.push({type: "text", text: `The last drape, ${v} (each piece is drawn in its own colour, to tell them apart; it is not the fabric):`}, aiImg(renders[i])) });
      const msgs = [{role: "user", content}];
      let out = null;
      for (let attempt = 0; attempt < 3 && !AI.stopped; attempt++) {
        const r = await aiCall(key, {model, system: aiBuilderSystem(), messages: msgs, tools: [AI_DESIGN_TOOL], effort: "high"});
        if (r.stop === "refusal") throw new Error("the model declined this request");
        const tu = r.content.find(b => b.type === "tool_use" && b.name === "submit_design");
        msgs.push({role: "assistant", content: r.content.map(b => { const {_bad, ...c} = b; return c })});
        if (!tu) { msgs.push({role: "user", content: "Call submit_design with the whole design."}); continue }
        const chk = !tu._bad && tu.input && tu.input.design ? aiCheck(cleanFile(tu.input.design))
          : {errors: [r.stop === "max_tokens" || tu._bad ? "the design was cut off or wasn't valid JSON: keep it shorter (Bézier edges instead of long pts lists, fewer pieces)" : "submit_design needs a design object"]};
        if (!chk.errors.length && orig) { const g = aiEditGuard(orig, chk.design); if (g) chk.errors.push(g) }
        if (!chk.errors.length) { out = {design: chk.design, fabric: tu.input.fabric, summary: tu.input.summary || "", plan: tu.input.plan || "", reading: tu.input.reading || ""}; break }
        aiLog(`The design has ${chk.errors.length} problem${chk.errors.length > 1 ? "s" : ""}: sent back to fix`, "bad"); aiStatus(chk.errors.slice(0, 2).join("; "));
        msgs.push({role: "user", content: [{type: "tool_result", tool_use_id: tu.id, is_error: true, content: "The design didn't pass the checks:\n- " + chk.errors.slice(0, 20).join("\n- ") + "\nFix them and call submit_design again with the whole design."}]});
      }
      if (!out) throw new Error("the builder couldn't produce a design that passes the checks");
      // 2. into the editor; the studio's own checks
      await aiApply(out.design, out.fabric, fromScratch && !made); made = true; design = JSON.parse(JSON.stringify(ST.design));
      if (out.reading && round === 1) aiLog(`How it read your request: ${out.reading}`, "note");
      aiLog(`Round ${round}: ${out.summary}`, "ok");
      const fails = ((DS.resp && DS.resp.check) || []).filter(c => !c.ok).map(c => c.text);
      if (fails.length) aiStatus("studio checks: " + fails.slice(0, 3).join("; "));
      // 3. drape it, and look at it
      aiLog(`Round ${round}: draping`);
      go("preview"); await new Promise(r => setTimeout(r, 300));
      if (!AI.skipDrape) { await startDrape(); if (!ST.drape) throw new Error("the drape didn't finish") }
      await new Promise(r => setTimeout(r, 600));
      renders = await Promise.all(GL.snapshot([0, Math.PI, Math.PI / 2]).map(u => aiShrink(u)));
      // 4. the critic
      if (AI.stopped) break;
      aiLog(`Round ${round}: the critic is looking at it`);
      const m = (ST.drape && ST.drape.metrics) || {}, adv = ((ST.drape && ST.drape.advice) || []).map(a => `${a.ok ? "ok" : a.level || "note"}: ${a.text}`);
      const cc = [{type: "text", text: [`Request: ${request || "(see the sketch)"}`, `Round ${round} of ${rounds}.`,
        `Simulation numbers: ${JSON.stringify({strain_p99_pct: m.strain_p99_pct, penetrating_points: m.penetrating_verts, kinetic_energy_uJ: m.kinetic_energy_uJ, seam_gap_max_mm: m.seam_gap_max_mm})}`,
        `Fit notes: ${adv.join(" | ") || "none"}`, `Ease on the drape: ${JSON.stringify((ST.drape && ST.drape.ease) || [])}`,
        `Studio checks that failed: ${fails.join(" | ") || "none"}`,
        ...(orig ? [`This was an EDIT of the user's ${aiGarmentKind(orig)}. Before the request it had these pieces:\n${aiPieceList(orig)}\nIf the result is no longer that kind of garment, or lost parts the request didn't ask to remove, pass is false and the first correction says to restore it.`] : []),
        `Design file:\n${JSON.stringify(design)}`].join("\n\n")}];
      for (const s of sketch) cc.push({type: "text", text: s.label}, aiImg(s.data));
      ["front", "back", "side"].forEach((v, i) => { if (renders[i]) cc.push({type: "text", text: `The drape, ${v} (each piece is drawn in its own colour, to tell them apart; it is not the fabric):`}, aiImg(renders[i])) });
      const r = await aiCall(key, {model, system: AI_CRITIC_SYSTEM, messages: [{role: "user", content: cc}], tools: [AI_REVIEW_TOOL], effort: "medium"});
      if (r.stop === "refusal") throw new Error("the critic declined to review this");
      const tu = r.content.find(b => b.type === "tool_use" && b.name === "submit_review");
      verdict = tu && !tu._bad && tu.input && tu.input.scores ? tu.input : {pass: false, scores: {request: 0, fit: 0, construction: 0, physics: 0}, corrections: [], summary: "The critic gave no review this round."};
      verdict.corrections = Array.isArray(verdict.corrections) ? verdict.corrections.slice(0, 6) : [];
      AI.versions.push({round, design: JSON.parse(JSON.stringify(design)), fabric: ST.fabric, summary: out.summary, verdict, thumb: renders[0], gid: PROJECT.activeGarmentId});
      aiRenderVersions();
      const score = Object.values(verdict.scores).reduce((a, b) => a + b, 0);
      aiLog(`Round ${round}: ${verdict.pass ? "the critic passed it" : "the critic asks for changes"}: ${verdict.summary}`, verdict.pass ? "ok" : "note");
      if (verdict.pass) break;
      flat = score <= lastScore ? flat + 1 : 0; lastScore = Math.max(lastScore, score);
      if (flat >= 2) { aiLog("The scores stopped improving: stopping here. Pick the version you like below.", "note"); break }
    }
    if (AI.stopped) aiLog("Stopped.", "note");
  } catch (e) {
    aiLog(AI.stopped ? "Stopped." : `It stopped: ${e.message}`, AI.stopped ? "note" : "bad");
  }
}
function aiRenderVersions() {
  $("#aiversions").innerHTML = AI.versions.length ? `<h3>Versions</h3>` + AI.versions.map((v, k) => `<div class="aiver">
    ${v.thumb ? `<img src="${v.thumb}" alt="round ${v.round}">` : ""}<div><b>Round ${v.round}</b> ${v.verdict.pass ? "✓ passed" : ""}
    <div class="aismall">${esc(v.summary)}</div><div class="aismall">request ${v.verdict.scores.request} · fit ${v.verdict.scores.fit} · construction ${v.verdict.scores.construction} · physics ${v.verdict.scores.physics}</div>
    <button class="btn small" data-aiv="${k}">Use this one</button></div></div>`).reverse().join("") : "";
  $$("#aiversions [data-aiv]").forEach(b => b.onclick = async () => {
    const v = AI.versions[+b.dataset.aiv]; if (garmentBy(v.gid)) setActiveGarment(v.gid);
    await aiApply(v.design, v.fabric, false); toast(`Round ${v.round} is back in the editor: Drape it to see it again`, 3500);
  });
}
$("#aiBtn").onclick = () => aiOpen($("#aipanel").hidden);
