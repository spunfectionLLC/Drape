// Spunfection Studio on the web: no server. Every fetch("/api/...") the studio makes is
// answered in the page: by Python in a Web Worker (py_worker.js -> drape/webapi.py), and
// the drape by the graphics card (LiveSprings, live_springs.js, the live mode solver).
// Loaded before the studio's scripts; the studio's own code doesn't change.
"use strict";
(() => {
  const worker = new Worker("py_worker.js", {type: "module"});
  const pending = new Map();
  let nextId = 1;
  // ---- the loading screen while Python starts (first visit: ~1 min; cached after)
  const cover = document.createElement("div");
  cover.id = "webLoading";
  cover.innerHTML = `<div class="wl-card"><div class="wl-title">Spunfection Studio</div>
    <div class="wl-msg" id="wlMsg">Starting…</div><div class="wl-bar"><i></i></div>
    <small>Everything runs in your browser: your measurements and designs stay on this computer.</small></div>`;
  const css = document.createElement("style");
  css.textContent = `#webLoading{position:fixed;inset:0;z-index:100;display:grid;place-items:center;background:var(--bg,#f6f3ee)}
    #webLoading .wl-card{max-width:440px;padding:28px;text-align:center;display:grid;gap:12px;font:15px/1.5 system-ui,sans-serif;color:var(--ink,#24211d)}
    #webLoading .wl-title{font-size:22px;font-weight:700}
    #webLoading .wl-bar{height:6px;border-radius:3px;background:var(--line,#e4ddd2);overflow:hidden}
    #webLoading .wl-bar i{display:block;height:100%;width:35%;background:var(--accent,#1f7a6d);border-radius:3px;animation:wl 1.2s ease-in-out infinite}
    @keyframes wl{0%{margin-left:-35%}100%{margin-left:100%}}
    #webLoading small{color:var(--muted,#7a7268)}`;
  document.head.appendChild(css);
  const showCover = () => document.body.appendChild(cover);
  if (document.body) showCover(); else addEventListener("DOMContentLoaded", showCover);
  worker.onmessage = e => {
    const d = e.data;
    if (d.status) {
      const m = document.getElementById("wlMsg");
      if (d.status === "ready") cover.remove(); else if (m) m.textContent = d.status;
      return;
    }
    const p = pending.get(d.id); if (!p) return;
    pending.delete(d.id);
    d.error ? p.reject(new Error(d.error)) : p.resolve(d.res);
  };
  worker.onerror = e => { const m = document.getElementById("wlMsg"); if (m) m.textContent = "Couldn't start: " + (e.message || e) };
  const py = (method, path, body) => new Promise((resolve, reject) => {
    const id = nextId++; pending.set(id, {resolve, reject}); worker.postMessage({id, method, path, body});
  });

  const b64ToBytes = s => { const b = atob(s), u = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return u };
  const bytesToB64 = u8 => { let s = ""; for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000)); return btoa(s) };
  const toResponse = r => {
    const headers = {"Content-Type": r.type};
    if (r.filename) headers["Content-Disposition"] = `attachment; filename="${r.filename}"`;
    return new Response(r.bytes_b64 != null ? b64ToBytes(r.bytes_b64) : r.body, {status: r.status, headers});
  };
  const json = (obj, status = 200) => new Response(JSON.stringify(obj), {status, headers: {"Content-Type": "application/json"}});

  // ---- the drape on the GPU: the page runs it, Python prepares it and finishes it
  const gpuJobs = new Map();       // job id -> {state, progress, stage, frame, rev, error}
  async function runDrape(r) {
    const job = {state: "running", progress: 0, stage: r.stage, frame: null, rev: 0};
    gpuJobs.set(r.job, job);
    (async () => {
      let sim;
      try {
        if (!navigator.gpu) throw new Error("this browser has no WebGPU: draping needs Chrome or Edge 113+ (or Safari 26+)");
        const S = r.gpu, n = r.frames;
        sim = await new LiveSprings().init(S);
        // as springs.py: cloth on cloth while the first stage sews only for layered designs (pocket bags,
        // linings): without it a pocket bag went through the dress front and stayed outside
        sim.selfWhileSewing = !!r.self_while_sewing;
        const tris = S.tris, colors = S.colors;
        const pid = b64ToBytes(S.panel_id); const P = new Uint32Array(pid.buffer);
        const base = b64ToBytes(colors);
        const colorFor = () => {        // pieces not sewn on yet: faded, as the desktop shows them
          if (sim.nStages < 2) return colors;
          const c = base.slice();
          for (let i = 0; i < sim.n; i++) if (sim.frozen(i)) for (let k = 0; k < 3; k++) c[3 * i + k] = Math.round(0.3 * c[3 * i + k] + 0.7 * 209);
          return bytesToB64(c);
        };
        let lastStage = 0, lastLabel = "";
        for (let f = 0; f < n; f += 2) {
          const k = Math.min(2, n - f);
          const x = await sim.step(k);
          if (!x) throw new Error("the graphics card stopped (device lost)");
          const [st, , label] = sim.phase();
          if (label !== lastLabel && sim.nStages > 1) { job.stage = `${label} (stage ${st} of ${sim.nStages})`; lastLabel = label }
          job.progress = (f + k) / n;
          if (f % 6 === 0 || f + k >= n) {
            const mm = new Int16Array(x.length); for (let i = 0; i < x.length; i++) mm[i] = Math.round(x[i] * 1000);
            const fr = {v: bytesToB64(new Uint8Array(mm.buffer)), nv: sim.n, rev: job.rev};
            if (st !== lastStage) { job.rev++; fr.rev = job.rev; fr.f = tris; fr.nf = S.ntris; fr.panel = colorFor(); lastStage = st }
            job.frame = fr;
          }
        }
        job.stage = "Checking the fit";
        const xf = new Float32Array(sim.out);
        const vf = new Float32Array(await readV(sim));
        const d = await py("POST", "/api/drape_done", JSON.stringify({job: r.job, x: bytesToB64(new Uint8Array(xf.buffer)), v: bytesToB64(new Uint8Array(vf.buffer))}));
        if (d.status !== 200) { let m = "the fit check failed"; try { m = JSON.parse(d.body).error || m } catch (_) {} throw Object.assign(new Error(m), {inPython: true}) }
        job.state = "python";            // finished on the GPU: Python has the result now
      } catch (e) {
        job.state = "error"; job.error = e.message || String(e);
        // free the job Python prepared (its simulator and body grid); drape_done already did if it got that far
        if (!e.inPython) py("POST", "/api/drape_cancel", JSON.stringify({job: r.job, reason: job.error})).catch(() => {});
      } finally {
        if (sim) sim.destroy();
      }
    })();
  }
  async function readV(sim) {        // the last velocities (LiveSprings keeps them on the GPU)
    const dev = sim.dev, buf = dev.createBuffer({size: sim.n * 12, usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST});
    const enc = dev.createCommandEncoder(); enc.copyBufferToBuffer(sim.V, 0, buf, 0, sim.n * 12); dev.queue.submit([enc.finish()]);
    await buf.mapAsync(GPUMapMode.READ); const v = buf.getMappedRange().slice(0); buf.unmap(); buf.destroy(); return v;
  }

  // ---- fetch: /api/... answered here, everything else as usual
  const realFetch = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith("/api/")) return realFetch(input, init);
    const method = (init.method || "GET").toUpperCase(), path = url.pathname;
    if (path.startsWith("/api/job/")) {
      const jid = path.split("/").pop(), j = gpuJobs.get(jid);
      if (j && j.state === "running") {
        const out = {state: "running", progress: j.progress, stage: j.stage};
        if (j.frame && j.frame !== j.sent) { out.frame = j.frame; j.sent = j.frame }
        return json(out);
      }
      if (j && j.state === "error") return json({state: "error", progress: j.progress, stage: j.stage, error: j.error});
    }
    const r = await py(method, path, init.body == null ? null : String(init.body));
    if (path === "/api/drape" && r.status === 200) {
      const d = JSON.parse(r.body);
      if (d.gpu) { runDrape(d); return json({job: d.job, pose_skipped: d.pose_skipped}) }
    }
    return toResponse(r);
  };
  window.SPUNFECTION_WEB = true;
})();
