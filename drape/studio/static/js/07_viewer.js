// drape studio: the 3D viewer (WebGL)
// (classic script: shares one global scope with the others, loaded in order by index.html)
// ======================================================== 3D viewer (WebGL)
const GL = (() => {
  const cv = $("#gl"), gl = cv.getContext("webgl", {antialias: true}) ;
  let body = null, cloth = null, yaw = 0.5, pitch = 0.08, dist = 2.9, target = [0, 1.0, 0], spin = 0, dirty = true;
  if (!gl) { $("#glmsg").textContent = "This browser has no WebGL, so the 3D view is off."; return {setBody() {}, setCloth() {}, overlay() {}, bg() {}} }
  gl.getExtension("OES_element_index_uint");
  const vs = `attribute vec3 p; attribute vec3 n; attribute vec3 c; attribute vec2 t; attribute float ao; attribute float cl; uniform mat4 M; varying vec3 vn; varying vec3 vc; varying vec3 vp; varying vec2 vt; varying float vao; varying float vcl;
    void main(){ vn=n; vc=c; vp=p; vt=t; vao=ao; vcl=cl; gl_Position=M*vec4(p,1.0); }`;
  // fabric look: sheen (fuzzy fibres glow at grazing angles), specular (satin, lining),
  // a fine weave/knit texture, and darker hollows in the folds (vao). Full precision where the GPU has it:
  // phones honour mediump (16-bit floats), and sin(x * 2500) and pow(.., 60) at that precision came out as
  // black blotches and stripes on the cloth (desktops compute at full precision whatever is asked)
  const fs = `#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
    varying vec3 vn; varying vec3 vc; varying vec3 vp; varying vec2 vt; varying float vao; varying float vcl;
    uniform vec3 eye; uniform sampler2D tex; uniform float useTex; uniform float ncell; uniform vec4 mat; uniform vec2 weave;
    void main(){ vec3 N=normalize(vn); vec3 V=normalize(eye-vp); if(dot(N,V)<0.0) N=-N;
      vec3 L1=normalize(vec3(0.5,0.8,0.9)), L2=normalize(vec3(-0.7,0.3,-0.6));
      float occ=mix(0.5,1.0,clamp(vao,0.0,1.0));
      float d=(0.30*occ+0.62*max(dot(N,L1),0.0)+0.22*max(dot(N,L2),0.0))*mix(0.75,1.0,occ);
      float nv=max(dot(N,V),0.0);
      vec2 tc = vec2((floor(vcl + 0.5) + clamp(fract(vt.x), 0.004, 0.996)) / max(ncell, 1.0), clamp(fract(vt.y), 0.004, 0.996));
      vec3 base = useTex > 0.5 ? texture2D(tex, tc).rgb : vc;
      if (weave.x > 0.0) { float w1=sin(vp.x*weave.y+vp.z*weave.y*0.6), w2=sin(vp.y*weave.y);
        base *= 1.0 - weave.x*0.10*(0.5+0.5*w1*w2); }
      float rim=pow(1.0-nv,3.0)*0.18;
      vec3 sheen=base*pow(1.0-nv,2.0)*mat.x*1.4;
      vec3 H=normalize(L1+V); float s=pow(max(dot(N,H),0.0),mat.z)*mat.y;
      gl_FragColor=vec4(base*d+rim*(1.0-mat.x)+sheen+s,1.0); }`;
  const sh = (t, s) => { const o = gl.createShader(t); gl.shaderSource(o, s); gl.compileShader(o); return o };
  const pr = gl.createProgram(); gl.attachShader(pr, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, fs)); gl.linkProgram(pr); gl.useProgram(pr);
  const loc = {p: gl.getAttribLocation(pr, "p"), n: gl.getAttribLocation(pr, "n"), c: gl.getAttribLocation(pr, "c"), t: gl.getAttribLocation(pr, "t"),
    M: gl.getUniformLocation(pr, "M"), eye: gl.getUniformLocation(pr, "eye"), tex: gl.getUniformLocation(pr, "tex"), useTex: gl.getUniformLocation(pr, "useTex"),
    ao: gl.getAttribLocation(pr, "ao"), mat: gl.getUniformLocation(pr, "mat"), weave: gl.getUniformLocation(pr, "weave"),
    cl: gl.getAttribLocation(pr, "cl"), ncell: gl.getUniformLocation(pr, "ncell")};
  // per fabric: [sheen, specular, shininess], [weave strength, weave frequency (1/m)]
  const MATS = {skin: [[0.0, 0.06, 24], [0, 0]], jersey: [[0.25, 0.05, 14], [0.6, 900]], poplin: [[0.1, 0.10, 22], [0.4, 1500]],
    denim: [[0.12, 0.04, 10], [1.0, 700]], canvas: [[0.1, 0.04, 10], [0.9, 500]], fleece: [[0.75, 0.02, 8], [0.2, 400]],
    silk: [[0.05, 0.55, 60], [0.1, 2500]], chiffon: [[0.1, 0.30, 40], [0.15, 2500]], rib: [[0.25, 0.04, 12], [1.0, 350]],
    lining: [[0.05, 0.45, 50], [0.1, 2500]], flannel: [[0.55, 0.03, 8], [0.4, 600]], trim: [[0.0, 0.35, 40], [0, 0]]};
  let clothMat = MATS.jersey;
  function cavity(P, F, N) {   // how far each vertex sits in a hollow (fold), 1 = open, 0 = deep
    const n = P.length / 3, S = new Float32Array(P.length), cnt = new Float32Array(n), out = new Float32Array(n);
    for (let i = 0; i < F.length; i += 3) for (let a = 0; a < 3; a++) { const v = F[i + a];
      for (let b = 1; b < 3; b++) { const u = F[i + (a + b) % 3]; S[v * 3] += P[u * 3]; S[v * 3 + 1] += P[u * 3 + 1]; S[v * 3 + 2] += P[u * 3 + 2]; cnt[v]++ } }
    for (let v = 0; v < n; v++) {
      if (!cnt[v]) { out[v] = 1; continue }
      let nx = N[v * 3], ny = N[v * 3 + 1], nz = N[v * 3 + 2]; const l = Math.hypot(nx, ny, nz) || 1; nx /= l; ny /= l; nz /= l;
      if (nx * P[v * 3] + nz * P[v * 3 + 2] < 0) { nx = -nx; ny = -ny; nz = -nz }      // outward, away from the body
      const dx = S[v * 3] / cnt[v] - P[v * 3], dy = S[v * 3 + 1] / cnt[v] - P[v * 3 + 1], dz = S[v * 3 + 2] / cnt[v] - P[v * 3 + 2];
      const ln = Math.hypot(dx, dy, dz) + 1e-6, k = (dx * nx + dy * ny + dz * nz);
      out[v] = Math.min(1, Math.max(0, 1 - Math.max(0, k) / 0.003));
    }
    for (let it = 0; it < 2; it++) {   // soften
      const sm = new Float32Array(n), c2 = new Float32Array(n);
      for (let i = 0; i < F.length; i += 3) for (let a = 0; a < 3; a++) { const v = F[i + a]; for (let b = 0; b < 3; b++) { sm[v] += out[F[i + b]]; c2[v]++ } }
      for (let v = 0; v < n; v++) out[v] = c2[v] ? sm[v] / c2[v] : out[v];
    }
    return out;
  }
  // a mesh's GPU buffers are freed when it's replaced (the floor is rebuilt every frame of a move test)
  function swap(old, nu) { if (old && old !== nu) for (const k of ["p", "n", "c", "ib", "a", "t"]) if (old[k]) gl.deleteBuffer(old[k]); return nu }
  let floor = null;
  function makeFloor() {   // a soft shadow pool under the avatar, fading into the background
    if (!body) { floor = swap(floor, null); return }
    const y = body.lo[1] - 0.002, R = 0.55, seg = 48, P = [0, y, 0], C = [...bgc.map(v => v * 0.86)], F = [], N = [0, 1, 0];
    for (let r = 1; r <= 4; r++) for (let k = 0; k < seg; k++) { const a = k / seg * 2 * Math.PI, rr = R * r / 4;
      P.push(Math.cos(a) * rr, y, Math.sin(a) * rr * 0.75); const f = Math.pow(r / 4, 0.8); C.push(...bgc.map(v => v * (0.86 + 0.14 * f))); }
    for (let k = 0; k < seg; k++) F.push(0, 1 + k, 1 + (k + 1) % seg);
    for (let r = 1; r < 4; r++) for (let k = 0; k < seg; k++) { const a = 1 + (r - 1) * seg + k, b = 1 + (r - 1) * seg + (k + 1) % seg, c = a + seg, d = b + seg; F.push(a, c, b, b, c, d) }
    const Nn = new Float32Array(P.length / 3 * 3); for (let i = 0; i < Nn.length; i += 3) Nn[i + 1] = 1;
    floor = swap(floor, rawObj(new Float32Array(P), Nn, new Float32Array(C), new Uint32Array(F)));
  }
  let texObj = null;
  gl.enable(gl.DEPTH_TEST);
  function normals(P, F) {
    const N = new Float32Array(P.length);
    for (let i = 0; i < F.length; i += 3) {
      const a = F[i] * 3, b = F[i + 1] * 3, c = F[i + 2] * 3;
      const ux = P[b] - P[a], uy = P[b + 1] - P[a + 1], uz = P[b + 2] - P[a + 2], vx = P[c] - P[a], vy = P[c + 1] - P[a + 1], vz = P[c + 2] - P[a + 2];
      const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
      for (const k of [a, b, c]) { N[k] += nx; N[k + 1] += ny; N[k + 2] += nz }
    }
    return N;
  }
  function mesh(m, colors) {
    const P16 = b64(m.v, Int16Array), P = new Float32Array(P16.length); for (let i = 0; i < P.length; i++) P[i] = P16[i] / 1000;
    const F = b64(m.f, Uint32Array), N = normals(P, F);
    const buf = d => { const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, d, gl.STATIC_DRAW); return b };
    const ib = gl.createBuffer(); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, F, gl.STATIC_DRAW);
    let lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9]; for (let i = 0; i < P.length; i += 3) for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], P[i + k]); hi[k] = Math.max(hi[k], P[i + k]) }
    const C = colors(P.length / 3);
    return {p: buf(P), n: buf(N), c: buf(C), ib, count: F.length, lo, hi, P, F, N, C, a: buf(cavity(P, F, N))};
  }
  // ---- trims: buttons, snaps, zipper teeth drawn on the cloth
  let trimList = null, trimObj = null;
  function rawObj(P, N, C, F) {
    const buf = d => { const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, d, gl.STATIC_DRAW); return b };
    const ib = gl.createBuffer(); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, F, gl.STATIC_DRAW);
    return {p: buf(P), n: buf(N), c: buf(C), ib, count: F.length};
  }
  function buildTrims() {
    trimObj = swap(trimObj, null);
    if (!cloth || !trimList || !trimList.length || !cloth.N) return;
    const P = cloth.P, NN = cloth.N, raw = !!cloth.raw, pos = [], nor = [], col = [], idx = [];
    const outN = i => { let n = [NN[i * 3], NN[i * 3 + 1], NN[i * 3 + 2]]; const l = Math.hypot(...n) || 1; n = n.map(v => v / l);
      if (n[0] * P[i * 3] + n[2] * P[i * 3 + 2] < 0) n = n.map(v => -v); return n };
    const at = i => [P[i * 3], P[i * 3 + 1], P[i * 3 + 2]];
    const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
    const unit = a => { const l = Math.hypot(...a) || 1; return a.map(v => v / l) };
    const disc = (c, n, r, rgb, lift) => {
      const t1 = unit(cross(n, Math.abs(n[1]) < .9 ? [0, 1, 0] : [1, 0, 0])), t2 = cross(n, t1), base = pos.length / 3;
      const cc = c.map((v, k) => v + n[k] * lift); pos.push(...cc); nor.push(...n); col.push(...rgb);
      for (let k = 0; k < 14; k++) { const a = k / 14 * 2 * Math.PI, q = cc.map((v, j) => v + r * (Math.cos(a) * t1[j] + Math.sin(a) * t2[j]));
        pos.push(...q); nor.push(...n); col.push(...rgb.map(v => v * 0.8)); idx.push(base, base + 1 + k, base + 1 + (k + 1) % 14) }
    };
    const strip = (ids, w, rgb, lift) => {
      for (let k = 0; k + 1 < ids.length; k++) {
        const a = at(ids[k]), b = at(ids[k + 1]), n = outN(ids[k]), d = unit(b.map((v, j) => v - a[j])), s = unit(cross(n, d)), base = pos.length / 3;
        for (const p of [a, b]) for (const sg of [-1, 1]) { pos.push(...p.map((v, j) => v + n[j] * lift + s[j] * w * sg)); nor.push(...n); col.push(...rgb) }
        idx.push(base, base + 1, base + 2, base + 1, base + 3, base + 2);
      }
    };
    for (const t of trimList) {
      if (t.type === "button" || t.type === "snap") { const v = raw ? t.v0 : t.v; if (v == null || v * 3 >= P.length) continue;
        disc(at(v), outN(v), t.r, t.type === "button" ? [0.93, 0.9, 0.82] : [0.75, 0.76, 0.78], 0.0025);
        if (t.type === "button") for (const [dx, dy] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {   // four holes
          const n = outN(v), t1 = unit(cross(n, [0, 1, 0])), t2 = cross(n, t1), c = at(v).map((x, j) => x + (dx * t1[j] + dy * t2[j]) * t.r * 0.28);
          disc(c, n, t.r * 0.12, [0.25, 0.22, 0.2], 0.0032) } }
      else if (t.type === "seam" || t.type === "topstitch") {
        const I = raw ? t.ids0 : t.ids; if (!I || !I.length || I.some(q => q.some(v => v * 3 >= P.length))) continue;
        const pts = I.map((q, k) => { const b = t.bary[k]; return [0, 1, 2].map(j => b[0] * P[q[0] * 3 + j] + b[1] * P[q[1] * 3 + j] + b[2] * P[q[2] * 3 + j]) });
        const nrm = I.map(q => outN(q[0]));
        const seam = t.type === "seam", rgb = seam ? [0.0, 0.0, 0.0] : [0.93, 0.9, 0.82], w = seam ? 0.0007 : 0.0006;
        for (let k = 0; k + 1 < pts.length; k++) {
          if (!seam && k % 2) continue;                   // stitches: dashes
          const a = pts[k], b = pts[k + 1], n = nrm[k], d = unit(b.map((v, j) => v - a[j])), sd = unit(cross(n, d)), base = pos.length / 3;
          const bb = seam ? b : a.map((v, j) => v + (b[j] - v) * 0.75);
          for (const p of [a, bb]) for (const sg of [-1, 1]) { pos.push(...p.map((v, j) => v + n[j] * 0.0012 + sd[j] * w * sg)); nor.push(...n);
            col.push(...(seam && cloth.C ? [0, 1, 2].map(j => cloth.C[I[k][0] * 3 + j] * 0.55) : rgb)) }
          idx.push(base, base + 1, base + 2, base + 1, base + 3, base + 2);
        }
      }
      else if (t.type === "zip" || t.type === "tape") {
        const A = raw ? t.a0 : t.a, B = raw ? t.b0 : t.b; if (!A || A.some(v => v * 3 >= P.length)) continue;
        const rgb = t.type === "zip" ? [0.16, 0.16, 0.18] : [0.55, 0.5, 0.6];
        strip(A, 0.004, rgb, 0.0015); strip(B, 0.004, rgb, 0.0015);
        if (t.pull >= 0) { const v = A[t.pull]; disc(at(v), outN(v), 0.007, [0.8, 0.8, 0.82], 0.003) }
      }
    }
    if (!idx.length) return;
    trimObj = swap(trimObj, rawObj(new Float32Array(pos), new Float32Array(nor), new Float32Array(col), new Uint32Array(idx)));
  }
  function skinColor(n) { const c = new Float32Array(n * 3); for (let i = 0; i < n; i++) { c[i * 3] = .80; c[i * 3 + 1] = .74; c[i * 3 + 2] = .69 } return c }
  function weaveFade(freq) {   // the weave pattern fades out when one repeat is under ~2 screen pixels (no moire)
    const px = 2 * dist * Math.tan(0.31) / Math.max(cv.height, 1), per = 2 * Math.PI / Math.max(freq, 1);
    return Math.min(Math.max((per / px - 2) / 2, 0), 1);
  }
  function persp(f, a, n, fa) { const t = 1 / Math.tan(f / 2); return [t / a, 0, 0, 0, 0, t, 0, 0, 0, 0, (fa + n) / (n - fa), -1, 0, 0, 2 * fa * n / (n - fa), 0] }
  function mul(a, b) { const o = new Array(16).fill(0); for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) for (let k = 0; k < 4; k++) o[j * 4 + i] += a[k * 4 + i] * b[j * 4 + k]; return o }
  function look(e, t) {
    let z = [e[0] - t[0], e[1] - t[1], e[2] - t[2]]; let l = Math.hypot(...z); z = z.map(v => v / l);
    let x = [z[2], 0, -z[0]]; l = Math.hypot(...x); x = x.map(v => v / l); const y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]];
    return [x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -(x[0] * e[0] + x[1] * e[1] + x[2] * e[2]), -(y[0] * e[0] + y[1] * e[1] + y[2] * e[2]), -(z[0] * e[0] + z[1] * e[1] + z[2] * e[2]), 1];
  }
  let bgc = [0, 0, 0], clickCb = null, clothCb = null, down = null;
  let others = [], garmentCb = null;   // the project's other visible garments, dimmed; a click on one selects it
  function camera() {
    const r = cv.getBoundingClientRect();
    const eye = [target[0] + dist * Math.sin(yaw) * Math.cos(pitch), target[1] + dist * Math.sin(pitch), target[2] + dist * Math.cos(yaw) * Math.cos(pitch)];
    let z = [eye[0] - target[0], eye[1] - target[1], eye[2] - target[2]]; let l = Math.hypot(...z); z = z.map(v => v / l);
    let x = [z[2], 0, -z[0]]; l = Math.hypot(...x); x = x.map(v => v / l);
    const y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]];
    return {eye, x, y, z, r};
  }
  // which of the other garments the click hit first (and nearer than the active cloth and the body), or null
  function nearestOther(cx, cy) {
    let best = null, bt = Math.min((cloth && pick(cx, cy, cloth)) ?? 1e9, (body && pick(cx, cy, body)) ?? 1e9);
    for (const o of others) { const t = pick(cx, cy, o); if (t != null && t < bt) { bt = t; best = o.gid } }
    return best;
  }
  // ray from the camera through a screen point, against the avatar's triangles (target: "cloth", the body, or a
  // mesh object, for which it returns the distance along the ray)
  function pick(cx, cy, target) {
    const asObj = target && typeof target === "object";
    const obj = asObj ? target : target === "cloth" ? cloth : body;
    if (!obj) return null;
    const {eye, x, y, z, r} = camera(), t = Math.tan(0.31), asp = r.width / r.height;
    const nx = ((cx - r.left) / r.width * 2 - 1) * t * asp, ny = (1 - (cy - r.top) / r.height * 2) * t;
    let d = [-z[0] + nx * x[0] + ny * y[0], -z[1] + nx * x[1] + ny * y[1], -z[2] + nx * x[2] + ny * y[2]];
    const dl = Math.hypot(...d); d = d.map(v => v / dl);
    const P = obj.P, F = obj.F; let best = 1e9, hit = null, hitTri = -1;
    for (let i = 0; i < F.length; i += 3) {
      const a = F[i] * 3, b = F[i + 1] * 3, c = F[i + 2] * 3;
      const e1x = P[b] - P[a], e1y = P[b + 1] - P[a + 1], e1z = P[b + 2] - P[a + 2];
      const e2x = P[c] - P[a], e2y = P[c + 1] - P[a + 1], e2z = P[c + 2] - P[a + 2];
      const px = d[1] * e2z - d[2] * e2y, py = d[2] * e2x - d[0] * e2z, pz = d[0] * e2y - d[1] * e2x;
      const det = e1x * px + e1y * py + e1z * pz; if (Math.abs(det) < 1e-12) continue;
      const inv = 1 / det, tx = eye[0] - P[a], ty = eye[1] - P[a + 1], tz = eye[2] - P[a + 2];
      const u = (tx * px + ty * py + tz * pz) * inv; if (u < 0 || u > 1) continue;
      const qx = ty * e1z - tz * e1y, qy = tz * e1x - tx * e1z, qz = tx * e1y - ty * e1x;
      const v = (d[0] * qx + d[1] * qy + d[2] * qz) * inv; if (v < 0 || u + v > 1) continue;
      const tt = (e2x * qx + e2y * qy + e2z * qz) * inv;
      if (tt > 0 && tt < best) { best = tt; hitTri = i; hit = [eye[0] + d[0] * tt, eye[1] + d[1] * tt, eye[2] + d[2] * tt] }
    }
    if (asObj) return hit ? best : null;
    if (target === "cloth" && hit) {   // nearest vertex of the hit triangle
      let bv = -1, bd = 1e9; for (let q = 0; q < 3; q++) { const v = F[hitTri + q], dd = (P[v * 3] - hit[0]) ** 2 + (P[v * 3 + 1] - hit[1]) ** 2 + (P[v * 3 + 2] - hit[2]) ** 2; if (dd < bd) { bd = dd; bv = v } }
      return {point: hit, vertex: bv};
    }
    return hit;
  }
  function bg() { const s = getComputedStyle(document.body).getPropertyValue("--panel").trim(); const c = document.createElement("canvas").getContext("2d"); c.fillStyle = s; c.fillRect(0, 0, 1, 1); const d = c.getImageData(0, 0, 1, 1).data; bgc = [d[0] / 255, d[1] / 255, d[2] / 255]; if (typeof makeFloor === "function" && body) makeFloor(); dirty = true }
  bg();
  function draw(o) {
    gl.bindBuffer(gl.ARRAY_BUFFER, o.p); gl.enableVertexAttribArray(loc.p); gl.vertexAttribPointer(loc.p, 3, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, o.n); gl.enableVertexAttribArray(loc.n); gl.vertexAttribPointer(loc.n, 3, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, o.c); gl.enableVertexAttribArray(loc.c); gl.vertexAttribPointer(loc.c, 3, gl.FLOAT, false, 0, 0);
    if (o.t && texObj && loc.t >= 0) {
      gl.bindBuffer(gl.ARRAY_BUFFER, o.t); gl.enableVertexAttribArray(loc.t); gl.vertexAttribPointer(loc.t, 2, gl.FLOAT, false, 0, 0);
      gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, texObj); gl.uniform1i(loc.tex, 0); gl.uniform1f(loc.useTex, 1);
      gl.uniform1f(loc.ncell, o.ncell || 1);
      if (loc.cl >= 0) { if (o.cl) { gl.bindBuffer(gl.ARRAY_BUFFER, o.cl); gl.enableVertexAttribArray(loc.cl); gl.vertexAttribPointer(loc.cl, 1, gl.FLOAT, false, 0, 0) } else { gl.disableVertexAttribArray(loc.cl); gl.vertexAttrib1f(loc.cl, 0) } }
    } else { if (loc.t >= 0) { gl.disableVertexAttribArray(loc.t); gl.vertexAttrib2f(loc.t, 0, 0) } if (loc.cl >= 0) { gl.disableVertexAttribArray(loc.cl); gl.vertexAttrib1f(loc.cl, 0) } gl.uniform1f(loc.useTex, 0) }
    if (o.a && loc.ao >= 0) { gl.bindBuffer(gl.ARRAY_BUFFER, o.a); gl.enableVertexAttribArray(loc.ao); gl.vertexAttribPointer(loc.ao, 1, gl.FLOAT, false, 0, 0) }
    else if (loc.ao >= 0) { gl.disableVertexAttribArray(loc.ao); gl.vertexAttrib1f(loc.ao, 1) }
    const m = o.mat || (o === cloth ? clothMat : o === trimObj ? MATS.trim : MATS.skin);
    gl.uniform4f(loc.mat, m[0][0], m[0][1], m[0][2], 0); gl.uniform2f(loc.weave, o === cloth || o.mat ? m[1][0] * weaveFade(m[1][1]) : 0, m[1][1]);
    if (o === body) { gl.enable(gl.POLYGON_OFFSET_FILL); gl.polygonOffset(2, 2) }   // the skin drawn a hair behind the cloth over it
    else gl.disable(gl.POLYGON_OFFSET_FILL);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, o.ib); gl.drawElements(gl.TRIANGLES, o.count, gl.UNSIGNED_INT, 0);
  }
  function frame() {
    requestAnimationFrame(frame);
    if (spin) { yaw += spin; spin *= 0.94; if (Math.abs(spin) < 1e-4) spin = 0; dirty = true }
    const r = cv.getBoundingClientRect(), dpr = Math.min(devicePixelRatio || 1, 2), w = Math.round(r.width * dpr), h = Math.round(r.height * dpr);
    if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; dirty = true }
    if (!dirty) return; dirty = false;
    gl.viewport(0, 0, w, h); gl.clearColor(...bgc, 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (!body) return;
    const eye = [target[0] + dist * Math.sin(yaw) * Math.cos(pitch), target[1] + dist * Math.sin(pitch), target[2] + dist * Math.cos(yaw) * Math.cos(pitch)];
    // near/far follow the camera: a phone's 16-bit depth buffer with near = 5 cm left ~2.6 mm of depth
    // resolution at 3 m, less than the cloth's gap to the skin (the skin showed through in blotches)
    gl.uniformMatrix4fv(loc.M, false, mul(persp(0.62, w / h, Math.max(0.05, dist - 1.2), dist + 3), look(eye, target))); gl.uniform3fv(loc.eye, eye);
    if (floor) draw(floor); draw(body); for (const o of others) draw(o); if (cloth) draw(cloth); if (cloth && trimObj) draw(trimObj);
  }
  requestAnimationFrame(frame);
  // orbit: drag = turn, wheel/pinch = zoom, two-finger drag / shift-drag = pan up/down
  const ptrs = new Map(); let last = null, lastPinch = 0;
  let grab = null, grabbing = false;   // live mode: drag the cloth itself
  cv.addEventListener("pointerdown", e => {
    if (grab && cloth && !e.shiftKey && ptrs.size === 0 && grab.down(e.clientX, e.clientY)) { grabbing = true; cv.setPointerCapture(e.pointerId); spin = 0; return }
    down = [e.clientX, e.clientY]; cv.setPointerCapture(e.pointerId); ptrs.set(e.pointerId, [e.clientX, e.clientY]); last = [e.clientX, e.clientY, performance.now()]; spin = 0 });
  cv.addEventListener("pointermove", e => {
    if (grabbing) { grab.move(e.clientX, e.clientY); return }
    if (!ptrs.has(e.pointerId)) return; const prev = ptrs.get(e.pointerId); ptrs.set(e.pointerId, [e.clientX, e.clientY]);
    if (ptrs.size === 2) { const [a, b] = [...ptrs.values()]; const d = Math.hypot(a[0] - b[0], a[1] - b[1]); if (lastPinch) dist = Math.min(6, Math.max(0.25, dist * lastPinch / d)); lastPinch = d; target[1] += (e.clientY - prev[1]) * 0.002 * dist / 2; dirty = true; return }
    const dx = e.clientX - prev[0], dy = e.clientY - prev[1];
    if (e.shiftKey) target[1] += dy * 0.002 * dist; else { yaw -= dx * 0.008; pitch = Math.max(-1.2, Math.min(1.2, pitch + dy * 0.006)) }
    const now = performance.now(); spin = -dx * 0.008 * Math.min(1, 16 / Math.max(1, now - last[2])); last = [e.clientX, e.clientY, now]; dirty = true;
  });
  const up = e => {
    if (grabbing) { grabbing = false; grab.up(); return }
    ptrs.delete(e.pointerId); lastPinch = 0; if (performance.now() - (last ? last[2] : 0) > 60) spin = 0;
    if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) < 5) {
      spin = 0;
      // a dimmed garment in front of everything else: it becomes the one you work on
      const og = garmentCb && others.length ? nearestOther(e.clientX, e.clientY) : null;
      if (og) garmentCb(og);
      else if (clothCb && cloth && clothCb.active()) { const h = pick(e.clientX, e.clientY, "cloth"); if (h) clothCb(h) }
      else if (clickCb) { const h = pick(e.clientX, e.clientY); if (h) clickCb(h) }
    }
    down = null;
  };
  cv.addEventListener("pointerup", up); cv.addEventListener("pointercancel", up);
  cv.addEventListener("wheel", e => { e.preventDefault(); dist = Math.min(6, Math.max(0.25, dist * Math.exp(e.deltaY * 0.0012))); dirty = true }, {passive: false});
  cv.addEventListener("dblclick", () => frameTo(cloth || body));
  function frameTo(o) {
    if (!o) return;
    let lo = o.lo, hi = o.hi;
    const small = hi[1] - lo[1] < 0.5;           // gloves, socks, a hat: look at it close up
    if (small && o.P && hi[0] - lo[0] > 0.3) {   // a pair, one on each side: frame the right-hand one
      const mx = (lo[0] + hi[0]) / 2, P = o.P; lo = [1e9, 1e9, 1e9]; hi = [-1e9, -1e9, -1e9];
      for (let i = 0; i < P.length; i += 3) if (P[i] < mx) for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], P[i + k]); hi[k] = Math.max(hi[k], P[i + k]) }
    }
    target = small ? [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2] : [0, (lo[1] + hi[1]) / 2, 0];
    const r = cv.getBoundingClientRect(), asp = r.width / Math.max(r.height, 1);
    const hgt = hi[1] - lo[1], wid = Math.max(hi[0] - lo[0], hi[2] - lo[2]);
    if (small) { dist = Math.max(0.3, Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) * 1.25 / Math.tan(0.31) / Math.min(1, asp)); dirty = true; return }
    dist = Math.max(1.0, Math.max(hgt, wid / Math.max(asp, .3)) * 1.6 / Math.tan(0.31) / 2 + wid / 2); dirty = true }
  return {
    setBody(m) { body = swap(body, mesh(m, skinColor)); cloth = swap(cloth, null); others.forEach(o => swap(o, null)); others = []; makeFloor(); frameTo(body) },
    // the other visible garments: [{cloth, fabric, gid}], drawn dimmed so you can tell which one you're editing
    setOthers(list) {
      others.forEach(o => swap(o, null));
      others = (list || []).map(({cloth: c, fabric, gid}) => {
        const col = b64(c.panel, Uint8Array);
        const o = mesh(c, n => { const out = new Float32Array(n * 3); for (let i = 0; i < n * 3; i++) out[i] = 0.55 * col[i] / 255 + 0.3; return out });
        o.mat = MATS[fabric] || MATS.jersey; o.gid = gid; return o;
      });
      dirty = true;
    },
    onGarmentClick(f) { garmentCb = f },
    setMaterial(key) { clothMat = MATS[key] || MATS.jersey; dirty = true },
    setCloth(c, by) {
      if (!c) { cloth = swap(cloth, null); if (body) frameTo(body); dirty = true; return }
      const col = b64(by === "fit" ? c.fit : c.panel, Uint8Array);
      cloth = swap(cloth, mesh(c, n => { const o = new Float32Array(n * 3); for (let i = 0; i < n * 3; i++) o[i] = col[i] / 255; return o }));
      buildTrims(); frameTo(cloth); dirty = true;
    },
    overlay(msg, sub = "", prog) {
      const ov = $("#glov"); if (!msg) { ov.style.display = "none"; return } ov.style.display = "grid";
      $("#glmsg").textContent = msg; $("#glsub").textContent = sub || ""; $("#glbar").parentElement.style.display = prog == null ? "none" : "block";
      $("#glbar").style.width = prog < 0 ? "35%" : Math.round((prog || 0) * 100) + "%";
    },
    // positions only (same triangles): recompute normals, refill the buffers
    move(which, P) {
      const o = which === "body" ? body : cloth; if (!o) return;
      const N = normals(P, o.F); o.P = P; o.N = N;
      gl.bindBuffer(gl.ARRAY_BUFFER, o.p); gl.bufferData(gl.ARRAY_BUFFER, P, gl.DYNAMIC_DRAW);
      gl.bindBuffer(gl.ARRAY_BUFFER, o.n); gl.bufferData(gl.ARRAY_BUFFER, N, gl.DYNAMIC_DRAW);
      if (which !== "body") { if (o.a) { gl.bindBuffer(gl.ARRAY_BUFFER, o.a); gl.bufferData(gl.ARRAY_BUFFER, cavity(P, o.F, N), gl.DYNAMIC_DRAW) } buildTrims() }
      else makeFloor();
      dirty = true;
    },
    recolor(cols) { if (!cloth) return; cloth.C = cols; gl.bindBuffer(gl.ARRAY_BUFFER, cloth.c); gl.bufferData(gl.ARRAY_BUFFER, cols, gl.STATIC_DRAW); buildTrims(); dirty = true },
    hasCloth: () => !!cloth,
    setTrims(t) { trimList = t || null; buildTrims(); dirty = true },
    // a print on the fabric: per-piece mesh, texture coords from the flat pattern
    setPrint(m, tcoords, canvasEl, cells, ncell = 1) {   // cells: which tile of the canvas each point reads (pieces' own looks)
      cloth = swap(cloth, mesh(m, n => { const o = new Float32Array(n * 3); o.fill(1); return o })); cloth.raw = true; buildTrims();
      const tb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, tb); gl.bufferData(gl.ARRAY_BUFFER, tcoords, gl.STATIC_DRAW); cloth.t = tb;
      if (cells) { const cb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, cb); gl.bufferData(gl.ARRAY_BUFFER, cells, gl.STATIC_DRAW); cloth.cl = cb }
      cloth.ncell = ncell;
      if (!texObj) texObj = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, texObj);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, canvasEl);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);   // repeats in the shader (tiles side by side)
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      dirty = true;
    },
    get canvas() { return cv },
    setView(v) { if (v.yaw != null) yaw = v.yaw; if (v.pitch != null) pitch = v.pitch; dirty = true },
    setColored(m, cols) {
      trimList = null; trimObj = swap(trimObj, null);
      if (!m) { cloth = swap(cloth, null); dirty = true; return }
      cloth = swap(cloth, mesh(m, () => cols)); if (arguments[2]) frameTo(body); dirty = true;
    },
    pick, onClick(f) { clickCb = f }, onClothClick(f) { clothCb = f },
    setGrab(g) { grab = g; grabbing = false },
    ray(cx, cy) {   // camera ray through a screen point
      const {eye, x, y, z, r} = camera(), t = Math.tan(0.31), asp = r.width / r.height;
      const nx = ((cx - r.left) / r.width * 2 - 1) * t * asp, ny = (1 - (cy - r.top) / r.height * 2) * t;
      let d = [-z[0] + nx * x[0] + ny * y[0], -z[1] + nx * x[1] + ny * y[1], -z[2] + nx * x[2] + ny * y[2]];
      const l = Math.hypot(...d); return {eye, d: d.map(v => v / l)};
    },
    setClothRaw(P, F, C, frame) {    // a mesh straight from Float32Arrays (the live GPU solver)
      trimList = null; trimObj = swap(trimObj, null);
      const o = rawObj(P, normals(P, F), C, F);
      let lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9]; for (let i = 0; i < P.length; i += 3) for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], P[i + k]); hi[k] = Math.max(hi[k], P[i + k]) }
      const Nn = normals(P, F), ab = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, ab); gl.bufferData(gl.ARRAY_BUFFER, cavity(P, F, Nn), gl.DYNAMIC_DRAW);
      Object.assign(o, {lo, hi, P, F, N: Nn, C, a: ab}); cloth = swap(cloth, o); if (frame) frameTo(body); dirty = true;
    },
    bg, get state() { return {yaw, pitch, dist, hasBody: !!body, hasCloth: !!cloth} },
  };
})();

