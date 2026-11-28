// drape live, springs: the velocity-level mass-spring solver (drape/springs.py) on the
// GPU (WebGPU): live mode's cloth solver (it replaced XPBD, which was removed).
//
// Velocity level (SPRING_VELOCITY_LEVEL_SPEC, a design rule), never
// break it:
// - positions change ONLY in `finish`, by x += h v (plus the deep-penetration safety
//   net, which never sets a velocity from the move);
// - nothing sets a velocity from a position difference;
// - predicted positions x + h v are read-only temporaries.
// Per substep:
//  1. forces: springs, bending, topstitching, gathered per vertex;
//  2. implicit backward Euler (Baraff & Witkin 1998): (M + h^2 K) dv = h (F + M g - h K v),
//     solved by Jacobi-preconditioned conjugate gradients, matrix-free, on the GPU
//     (reductions per workgroup; every workgroup sums the partials itself, so there is
//     no read-back);
//  3. strain limit as velocity impulses, in colour batches;
//  4. body contact and friction impulses (the speed cap later lets the outward push go first);
//  5. cloth on cloth impulses, overlapping layers eased apart over SELF_TAU;
//  6. damping and the speed cap;
//  7. x += h v.
// Storage buffers: at most 8 per shader stage (the WebGPU default limit; module C uses all 8).
"use strict";

// Speed-based substeps (as cloth.py plan_substeps): two layers closing at 2 v must not get
// more than half the self-contact thickness closer between self-collision checks, or a point
// jumps past a triangle and the side test holds the crossing (a knot). Substeps follow the
// fastest point; what the cap can't cover is slowed down instead. Substeps are dynamic:
// never assume this.substeps is constant.
const SPEED_SAFETY = 0.5, SPEED_HEADROOM = 1.25, NSUB_CAP_LIVE = 96;
const SELF_MARGIN_MAX = 0.015;     // cloth.py's: the furthest a frame's cloth-on-cloth contact list reaches (m)
function planSubsteps(vMax, fps, base, selfEvery, thick, cap, prev) {
  const need = se => Math.ceil(2 * vMax * se / (fps * SPEED_SAFETY * thick) - 1e-9);
  let se = selfEvery, ns = need(se);
  if (ns > base && se !== 1) { se = 1; ns = need(1) }
  let nsub = Math.min(Math.max(base, ns), cap);
  if (prev != null && prev > nsub) nsub = Math.min(Math.max(nsub, Math.ceil(0.75 * prev - 1e-9)), cap);   // falls by 25% a frame at most
  if (nsub > base) se = 1;
  const limited = ns > cap;
  return {nsub, se, vClamp: limited ? cap * fps * SPEED_SAFETY * thick / (2 * se) : Infinity, limited};
}

const b64buf = (s, T) => { const b = atob(s), u = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return new T(u.buffer) };

const SPR_GRAB_K = 50;    // N/m: the mouse pulls the grabbed point with a spring (in the implicit solve)
const SPR_CG_BUDGET = 48;  // CG iterations queued per substep; they stop early (springs.py: mean 20, max 30 on a tee)
const SPR_CAND = 24;       // cloth-on-cloth candidate triangles kept per point each frame
const SPR_ECAND = 16;      // and candidate edges per edge (pairs kept by the lower edge id only)
const SPR_WG = 64;         // workgroup size of the per-vertex solve kernels (more, smaller groups spread better)

// the uniform: 4-byte scalars only (no padding to get wrong); the WGSL struct is generated from this list
const SPR_FIELDS = [
  ["h", "f32"], ["g", "f32"], ["damp", "f32"], ["ease", "f32"], ["cdamp", "f32"], ["thick", "f32"], ["mu", "f32"], ["n", "u32"],
  ["grab", "i32"], ["grabK", "f32"], ["selfThick", "f32"], ["cell", "f32"], ["tx", "f32"], ["ty", "f32"], ["tz", "f32"], ["vmax", "f32"],
  ["sox", "f32"], ["soy", "f32"], ["soz", "f32"], ["soh", "f32"], ["sdx", "u32"], ["sdy", "u32"], ["sdz", "u32"], ["ntri", "u32"],
  ["ncells", "u32"], ["slots", "u32"], ["ns", "u32"], ["nh", "u32"], ["ne", "u32"], ["sewStage", "u32"], ["unfoldOn", "u32"], ["nwg", "u32"],
  ["seamS0", "f32"], ["seamS1", "f32"], ["seamS2", "f32"], ["seamS3", "f32"], ["seamA0", "f32"], ["seamA1", "f32"], ["seamA2", "f32"], ["seamA3", "f32"],
  ["tau", "f32"], ["deep", "f32"], ["tol2", "f32"], ["cgMax", "u32"], ["cmargin", "f32"], ["candAt", "u32"],
  ["oSpr", "u32"], ["oIncs", "u32"], ["oInc", "u32"], ["oIncslot", "u32"], ["oRows", "u32"], ["oRcol", "u32"], ["oAtt", "u32"], ["oTri", "u32"],
  ["oGid", "u32"], ["pSpr", "u32"], ["pAtt", "u32"], ["pBk", "u32"], ["ecell", "f32"], ["eslots", "u32"], ["eHashAt", "u32"], ["eCandAt", "u32"],
];
const SPR_UBYTES = Math.ceil(SPR_FIELDS.length * 4 / 256) * 256;

// VEC: blocks of n vec4f
// R residual, U preconditioned residual, W = A u, P search direction, S = A p, MISC/MISC2 the preconditioner block
const VB = {F: 0, DV: 1, R: 2, P: 3, S: 4, U: 5, X0: 6, BN: 7, DVS: 8, MISC: 9, MISC2: 10, W: 11};
const VB_COUNT = 12;

const SPR_COMMON = /* wgsl */`
struct Frame { ${SPR_FIELDS.map(([k, t]) => `${k}: ${t}`).join(", ")} };
struct Batch { start: u32, count: u32, kind: u32, it: u32 };
fn xg(i: u32) -> vec3f { return vec3f(X[3u*i], X[3u*i+1u], X[3u*i+2u]); }
fn vg(i: u32) -> vec3f { return vec3f(V[3u*i], V[3u*i+1u], V[3u*i+2u]); }
fn wOf(i: u32) -> f32 { return PARAM[i]; }
fn vb(b: u32, i: u32) -> u32 { return b * F.n + i; }
fn seamS(st: u32) -> f32 { return select(select(select(F.seamS3, F.seamS2, st == 2u), F.seamS1, st == 1u), F.seamS0, st == 0u); }
fn seamA(st: u32) -> f32 { return select(select(select(F.seamA3, F.seamA2, st == 2u), F.seamA1, st == 1u), F.seamA0, st == 0u); }
`;
const SPR_SDF = /* wgsl */`
fn sdfAt(i: i32, j: i32, k: i32) -> f32 {
  let ii = clamp(i, 0, i32(F.sdx) - 1); let jj = clamp(j, 0, i32(F.sdy) - 1); let kk = clamp(k, 0, i32(F.sdz) - 1);
  let flat = u32(ii) * F.sdy * F.sdz + u32(jj) * F.sdz + u32(kk);
  let word = SDF[flat / 2u];
  var v: i32;
  if ((flat & 1u) == 0u) { v = (word << 16u) >> 16u; } else { v = word >> 16u; }
  return f32(v) * 1e-5;
}
fn sdf(p: vec3f) -> f32 {
  let D = vec3f(f32(F.sdx), f32(F.sdy), f32(F.sdz));
  let f = (p - vec3f(F.sox, F.soy, F.soz)) / F.soh;
  let c = clamp(f, vec3f(0.0), D - vec3f(1.000001));
  let out = length(f - c) * F.soh;
  let i = vec3i(floor(c)); let t = c - floor(c);
  let c00 = mix(sdfAt(i.x, i.y, i.z), sdfAt(i.x+1, i.y, i.z), t.x);
  let c10 = mix(sdfAt(i.x, i.y+1, i.z), sdfAt(i.x+1, i.y+1, i.z), t.x);
  let c01 = mix(sdfAt(i.x, i.y, i.z+1), sdfAt(i.x+1, i.y, i.z+1), t.x);
  let c11 = mix(sdfAt(i.x, i.y+1, i.z+1), sdfAt(i.x+1, i.y+1, i.z+1), t.x);
  return mix(mix(c00, c10, t.y), mix(c01, c11, t.y), t.z) + out;
}
fn sdfNormal(p: vec3f) -> vec3f {   // as meshbody.grid_sdf_grad: central differences, normalised
  let e = 0.5 * F.soh;
  let g = vec3f(sdf(p + vec3f(e,0,0)) - sdf(p - vec3f(e,0,0)), sdf(p + vec3f(0,e,0)) - sdf(p - vec3f(0,e,0)),
                sdf(p + vec3f(0,0,e)) - sdf(p - vec3f(0,0,e)));
  return g / (length(g) + 1e-12);
}
`;

// ---- module A: forces, the implicit solve, the strain limit (7 storage buffers)
const SPR_SOLVE_WGSL = /* wgsl */`
@group(0) @binding(0) var<uniform> F: Frame;
@group(0) @binding(1) var<storage, read> X: array<f32>;
@group(0) @binding(2) var<storage, read_write> V: array<f32>;
@group(0) @binding(3) var<storage, read> PARAM: array<f32>;   // inverse masses, spring / topstitch data, bending blocks
@group(0) @binding(4) var<storage, read> TOPO: array<u32>;
@group(0) @binding(5) var<storage, read_write> VEC: array<vec4f>;
@group(0) @binding(6) var<storage, read_write> TMP: array<vec4f>;   // per spring 3, then the matrix: 2 per slot
@group(0) @binding(7) var<storage, read_write> SCAL: array<f32>;    // reduction partials, CG scalars
@group(1) @binding(0) var<uniform> B: Batch;
${SPR_COMMON}
fn sa(e: u32, k: u32) -> f32 { return PARAM[F.pSpr + 8u*e + k]; }
fn si(e: u32) -> u32 { return TOPO[F.oSpr + 2u*e]; }
fn sj(e: u32) -> u32 { return TOPO[F.oSpr + 2u*e + 1u]; }
fn uv(i: u32) -> vec3f { return VEC[vb(${VB.U}u, i)].xyz; }
fn mat(s: u32) -> u32 { return 3u * F.ns + 2u * s; }   // the matrix block of row slot s in TMP
// a symmetric 3x3 block as (xx, yy, zz, xy), (xz, yz, -, -)
fn bmul(a: vec4f, b: vec4f, u: vec3f) -> vec3f {
  return vec3f(a.x * u.x + a.w * u.y + b.x * u.z, a.w * u.x + a.y * u.y + b.y * u.z, b.x * u.x + b.y * u.y + a.z * u.z);
}
// SCAL layout: 4 partial arrays of nwg ((r,u), (w,u), (r,r), (b,b)), then: -, iterations this
// substep, most this frame, budget hit (1), gamma[0..budget], alpha[0..budget], done[0..budget]
fn sBase() -> u32 { return 4u * F.nwg; }
fn gAt(it: u32) -> u32 { return sBase() + 4u + it; }
fn aAt(it: u32) -> u32 { return sBase() + 6u + ${SPR_CG_BUDGET}u + it; }
fn doneAt(it: u32) -> u32 { return sBase() + 8u + ${2 * SPR_CG_BUDGET}u + it; }
fn restOf(e: u32) -> f32 {
  let kind = u32(sa(e, 4u)); let r = sa(e, 0u);
  if (kind == 0u) { return r + (sa(e, 1u) - r) * F.ease; }
  if (kind == 1u) { return r * max(seamS(min(u32(sa(e, 5u)), 3u)), 0.0); }
  return r;
}

var<workgroup> wflag: f32;   // the done flag, read once per workgroup (uniform: it can return before the sums)
var<workgroup> red0: array<f32, ${SPR_WG}>;
var<workgroup> red1: array<f32, ${SPR_WG}>;
fn wgSum2(l: u32, a: f32, b: f32) -> vec2f {
  red0[l] = a; red1[l] = b; workgroupBarrier();
  for (var s = ${SPR_WG / 2}u; s > 0u; s >>= 1u) { if (l < s) { red0[l] += red0[l + s]; red1[l] += red1[l + s]; } workgroupBarrier(); }
  let r = vec2f(red0[0], red1[0]); workgroupBarrier(); return r;
}
fn sumPart(at: u32, l: u32) -> f32 {   // every workgroup adds the partials up itself, in the same order
  var s = 0.0; for (var k = l; k < F.nwg; k += ${SPR_WG}u) { s += SCAL[at + k]; }
  return wgSum2(l, s, 0.0).x;
}

// 1. per spring: force and direction. Seams of a later stage while they sew are explicit
// and one-sided (springs.py _seam_forces_one_sided), not in K.
@compute @workgroup_size(64) fn forces(@builtin(global_invocation_id) id: vec3u) {
  let e = id.x; if (e >= F.ns) { return; }
  let i = si(e); let j = sj(e);
  let kind = u32(sa(e, 4u)); let k = sa(e, 2u);
  var on = true; var fi = 1.0; var fj = 1.0; var isImp = 1.0;
  if (kind == 1u) {
    let st = min(u32(sa(e, 5u)), 3u);
    if (seamS(st) < 0.0) { on = false; }
    if (F.sewStage > 0u && st + 1u == F.sewStage) {
      isImp = 0.0; let an = u32(sa(e, 6u));
      if ((an & 1u) != 0u) { fi = seamA(st); }
      if ((an & 2u) != 0u) { fj = seamA(st); }
    }
  } else if (kind == 2u && F.unfoldOn == 0u) { on = false; }
  let rest = restOf(e);
  let d = xg(i) - xg(j); let L = length(d);
  var nd = vec3f(0.0); var fac = 0.0; var f = vec3f(0.0);
  if (on && L > 1e-12) { nd = d / L; fac = max(0.0, 1.0 - rest / L); f = d * (-k * (L - rest) / L); }
  else { isImp = 0.0; }
  TMP[3u*e] = vec4f(nd, fac); TMP[3u*e+1u] = vec4f(f * fi, isImp); TMP[3u*e+2u] = vec4f(-f * fj, 0.0);
}

// topstitching (explicit, one-sided: only when pulled away), colour batches add into VEC.F
@compute @workgroup_size(64) fn attach(@builtin(global_invocation_id) id: vec3u) {
  if (id.x >= B.count) { return; }
  let c = B.start + id.x;
  let o = F.oAtt + 4u*c; let p0 = F.pAtt + 8u*c;
  let sc = seamS(min(u32(PARAM[p0 + 5u]), 3u)); if (sc < 0.0) { return; }
  let i = TOPO[o]; let a = TOPO[o+1u]; let b = TOPO[o+2u]; let d = TOPO[o+3u];
  let ba = PARAM[p0]; let bb = PARAM[p0 + 1u]; let bd = PARAM[p0 + 2u];
  let rest = max(PARAM[p0 + 3u] * sc, F.selfThick + 0.0005);
  let D = xg(i) - (ba * xg(a) + bb * xg(b) + bd * xg(d)); let L = length(D);
  if (L < 1e-12 || L <= rest) { return; }
  // explicit, so capped at half its stability limit (k h^2 W < 1, W the pair's inverse mass):
  // at full strength (SEAM_K x the fabric's k) the dress front shook against the pocket bags
  // stitched to it (KE 1900 uJ; with the cap 20-ish, as with no stitches at all)
  let W = wOf(i) + ba * ba * wOf(a) + bb * bb * wOf(b) + bd * bd * wOf(d);
  let kc = min(PARAM[p0 + 4u], 0.5 / (F.h * F.h * max(W, 1e-12)));
  let f = D * (kc * (L - rest) / L);
  VEC[vb(0u, i)] -= vec4f(f, 0.0);
  VEC[vb(0u, a)] += vec4f(f * ba, 0.0); VEC[vb(0u, b)] += vec4f(f * bb, 0.0); VEC[vb(0u, d)] += vec4f(f * bd, 0.0);
}

// 2a. per vertex row (dv starts from the last substep's answer: fewer CG iterations, the
// same tolerance): K = -dF/dx assembled as 3x3 blocks (bending: constant bk I per slot;
// each implicit spring: k [(1 - f) n n^T + f I] on the diagonal, minus it at the partner),
// the forces (springs, topstitching, bending -K_b x, the mouse), b = h (F + M g - h K v),
// the block-Jacobi preconditioner P = (M + h^2 K_ii)^-1, r = b - A dv0, u = P r
@compute @workgroup_size(${SPR_WG}) fn cgInit(@builtin(global_invocation_id) gid: vec3u, @builtin(local_invocation_id) lid: vec3u,
                                        @builtin(workgroup_id) wid: vec3u) {
  let i = gid.x; let l = lid.x;
  var bn = 0.0;
  if (gid.x == 0u) { SCAL[doneAt(0u)] = 0.0; SCAL[sBase() + 1u] = 0.0; }
  if (i < F.n) {
    let r0 = TOPO[F.oRows + i]; let r1 = TOPO[F.oRows + i + 1u];
    var f = VEC[vb(${VB.F}u, i)].xyz;
    var ds = r0;
    for (var s = r0; s < r1; s++) {
      let c = TOPO[F.oRcol + s]; let b = PARAM[F.pBk + s];
      if (c == i) { ds = s; }
      f -= b * xg(c);
      TMP[mat(s)] = vec4f(b, b, b, 0.0); TMP[mat(s) + 1u] = vec4f(0.0);
    }
    var Da = vec4f(0.0); var Db = vec4f(0.0);   // the springs' part of the diagonal block
    let a = TOPO[F.oIncs + i]; let bE = TOPO[F.oIncs + i + 1u];
    for (var c = a; c < bE; c++) {
      let ent = TOPO[F.oInc + c]; let e = ent >> 1u; let t1 = TMP[3u*e+1u];
      if ((ent & 1u) == 0u) { f += t1.xyz; } else { f += TMP[3u*e+2u].xyz; }
      if (t1.w > 0.0) {
        let nf = TMP[3u*e]; let n = nf.xyz; let fa = nf.w; let k = sa(e, 2u); let q = k * (1.0 - fa);
        let Ka = vec4f(q * n.x * n.x + k * fa, q * n.y * n.y + k * fa, q * n.z * n.z + k * fa, q * n.x * n.y);
        let Kb = vec4f(q * n.x * n.z, q * n.y * n.z, 0.0, 0.0);
        Da += Ka; Db += Kb;
        let ps = TOPO[F.oIncslot + c];
        TMP[mat(ps)] -= Ka; TMP[mat(ps) + 1u] -= Kb;
      }
    }
    if (i32(i) == F.grab) { f += F.grabK * (vec3f(F.tx, F.ty, F.tz) - xg(i)); Da += vec4f(F.grabK, F.grabK, F.grabK, 0.0); }
    TMP[mat(ds)] += Da; TMP[mat(ds) + 1u] += Db;
    var kv = vec3f(0.0); var kd = vec3f(0.0);   // K v, and K dv0 (dv0: the last substep's answer, the start guess)
    for (var s = r0; s < r1; s++) {
      let c = TOPO[F.oRcol + s]; let A = TMP[mat(s)]; let Bm = TMP[mat(s) + 1u];
      kv += bmul(A, Bm, vg(c)); kd += bmul(A, Bm, VEC[vb(${VB.DV}u, c)].xyz);
    }
    let w = wOf(i);
    var r = vec3f(0.0); var b0 = vec3f(0.0); var Pa = vec4f(1.0, 1.0, 1.0, 0.0); var Pb = vec4f(0.0);
    if (w > 0.0) {
      let m = 1.0 / w; let h2 = F.h * F.h;
      b0 = F.h * (f + vec3f(0.0, m * F.g, 0.0) - F.h * kv);
      r = b0 - (m * VEC[vb(${VB.DV}u, i)].xyz + h2 * kd);   // r = b - A dv0
      let A = TMP[mat(ds)]; let Bd = TMP[mat(ds) + 1u];
      let xx = m + h2 * A.x; let yy = m + h2 * A.y; let zz = m + h2 * A.z; let xy = h2 * A.w; let xz = h2 * Bd.x; let yz = h2 * Bd.y;
      let c11 = yy * zz - yz * yz; let c12 = xz * yz - xy * zz; let c13 = xy * yz - yy * xz;
      let c22 = xx * zz - xz * xz; let c23 = xy * xz - xx * yz; let c33 = xx * yy - xy * xy;
      let det = xx * c11 + xy * c12 + xz * c13;
      Pa = vec4f(c11, c22, c33, c12) / det; Pb = vec4f(c13, c23, 0.0, 0.0) / det;
    }
    VEC[vb(${VB.R}u, i)] = vec4f(r, 0.0); VEC[vb(${VB.U}u, i)] = vec4f(bmul(Pa, Pb, r), 0.0);
    VEC[vb(${VB.MISC}u, i)] = Pa; VEC[vb(${VB.MISC2}u, i)] = Pb;
    bn = dot(b0, b0);
  }
  let s = wgSum2(l, bn, 0.0);
  if (l == 0u) { SCAL[3u * F.nwg + wid.x] = s.x; }
}
// 2b. CG, Chronopoulos-Gear form (one global sum per iteration; Ghysels and Vanroose 2014,
// algorithm 2): cgW then cgStep, B.it = the iteration
// cgW: w = A u, and this state's sums (r,u), (w,u), (r,r) per workgroup
@compute @workgroup_size(${SPR_WG}) fn cgW(@builtin(global_invocation_id) gid: vec3u, @builtin(local_invocation_id) lid: vec3u,
                                     @builtin(workgroup_id) wid: vec3u) {
  let i = gid.x; let l = lid.x;
  if (l == 0u) { wflag = SCAL[doneAt(B.it)]; }
  if (workgroupUniformLoad(&wflag) != 0.0) { return; }
  var ru = 0.0; var wu = 0.0; var rr = 0.0;
  if (i < F.n) {
    let w = wOf(i);
    var wv = vec3f(0.0);
    let u = uv(i);
    if (w > 0.0) {
      var ku = vec3f(0.0);
      for (var s = TOPO[F.oRows + i]; s < TOPO[F.oRows + i + 1u]; s++) { ku += bmul(TMP[mat(s)], TMP[mat(s) + 1u], uv(TOPO[F.oRcol + s])); }
      wv = u / w + F.h * F.h * ku;
    }
    VEC[vb(${VB.W}u, i)] = vec4f(wv, 0.0);
    let r = VEC[vb(${VB.R}u, i)].xyz;
    ru = dot(r, u); wu = dot(wv, u); rr = dot(r, r);
  }
  let s = wgSum2(l, ru, wu); let s2 = wgSum2(l, rr, 0.0);
  if (l == 0u) { SCAL[wid.x] = s.x; SCAL[F.nwg + wid.x] = s.y; SCAL[2u * F.nwg + wid.x] = s2.x; }
}
// cgStep: every workgroup adds the sums up itself; stop when |r| <= tol |b| (as springs.py);
// else beta = g / g_prev, alpha = g / (d - beta g / alpha_prev), p = u + beta p, s = w + beta s,
// dv += alpha p, r -= alpha s, u = P r
@compute @workgroup_size(${SPR_WG}) fn cgStep(@builtin(global_invocation_id) gid: vec3u, @builtin(local_invocation_id) lid: vec3u) {
  let i = gid.x; let l = lid.x; let it = B.it;
  if (l == 0u) { wflag = SCAL[doneAt(it)]; }
  if (workgroupUniformLoad(&wflag) != 0.0) {
    if (gid.x == 0u) { SCAL[doneAt(it + 1u)] = 1.0; }
    return;
  }
  let g = sumPart(0u, l); let d = sumPart(F.nwg, l); let rr = sumPart(2u * F.nwg, l); let bn = sumPart(3u * F.nwg, l);
  let dn = false;
  let conv = bn == 0.0 || rr <= F.tol2 * bn;
  var beta = 0.0; var al = 0.0;
  if (it == 0u) { al = g / d; }
  else { beta = g / SCAL[gAt(it - 1u)]; al = g / (d - beta * g / SCAL[aAt(it - 1u)]); }
  let bad = !(al > 0.0) || !(al < 1e30) || !(abs(beta) < 1e30);
  let fin = dn || conv || bad;
  if (gid.x == 0u) {
    SCAL[doneAt(it + 1u)] = select(0.0, 1.0, fin);
    if (!fin) {
      SCAL[gAt(it)] = g; SCAL[aAt(it)] = al;
      SCAL[sBase() + 1u] = f32(it + 1u); SCAL[sBase() + 2u] = max(SCAL[sBase() + 2u], f32(it + 1u));
      if (it + 1u >= F.cgMax) { SCAL[sBase() + 3u] = 1.0; }   // the budget ran out before it converged
    }
  }
  if (i < F.n && !fin) {
    let u = uv(i); let w = VEC[vb(${VB.W}u, i)].xyz;
    var p = u; var sv = w;
    if (it > 0u) { p = u + beta * VEC[vb(${VB.P}u, i)].xyz; sv = w + beta * VEC[vb(${VB.S}u, i)].xyz; }
    let r = VEC[vb(${VB.R}u, i)].xyz - al * sv;
    VEC[vb(${VB.P}u, i)] = vec4f(p, 0.0); VEC[vb(${VB.S}u, i)] = vec4f(sv, 0.0);
    VEC[vb(${VB.DV}u, i)] = vec4f(VEC[vb(${VB.DV}u, i)].xyz + al * p, 0.0);
    VEC[vb(${VB.R}u, i)] = vec4f(r, 0.0);
    VEC[vb(${VB.U}u, i)] = vec4f(bmul(VEC[vb(${VB.MISC}u, i)], VEC[vb(${VB.MISC2}u, i)], r), 0.0);
  }
}
@compute @workgroup_size(64) fn applyDv(@builtin(global_invocation_id) id: vec3u) {
  let i = id.x; if (i >= F.n || wOf(i) == 0.0) { return; }
  let v = vg(i) + VEC[vb(${VB.DV}u, i)].xyz;
  V[3u*i] = v.x; V[3u*i+1u] = v.y; V[3u*i+2u] = v.z;
}

// 3. strain limit (Provot 1995) as velocity impulses (Bridson et al. 2002), colour batches
// of the mesh edges: only stretching speed is taken away, so it can't add energy
@compute @workgroup_size(64) fn strain(@builtin(global_invocation_id) id: vec3u) {
  if (id.x >= B.count) { return; }
  let e = B.start + id.x; let i = si(e); let j = sj(e);
  let wi = wOf(i); let wj = wOf(j); let ws = wi + wj; if (ws == 0.0) { return; }
  let vi = vg(i); let vj = vg(j);
  let d = (xg(i) + F.h * vi) - (xg(j) + F.h * vj);   // predicted: read-only
  let L = length(d); let Lmax = (1.0 + sa(e, 3u)) * restOf(e);
  if (L <= Lmax || L < 1e-12) { return; }
  let n = d / L; let u = dot(vi - vj, n);
  if (u <= 0.0) { return; }
  let dv = min((L - Lmax) / F.h, u);
  let a = vi - n * (wi / ws * dv); let b = vj + n * (wj / ws * dv);
  V[3u*i] = a.x; V[3u*i+1u] = a.y; V[3u*i+2u] = a.z;
  V[3u*j] = b.x; V[3u*j+1u] = b.y; V[3u*j+2u] = b.z;
}
`;

// ---- module B: the body, damping, the speed cap, the position update (6 storage buffers)
const SPR_BODY_WGSL = /* wgsl */`
@group(0) @binding(0) var<uniform> F: Frame;
@group(0) @binding(1) var<storage, read_write> X: array<f32>;
@group(0) @binding(2) var<storage, read_write> V: array<f32>;
@group(0) @binding(3) var<storage, read> PARAM: array<f32>;
@group(0) @binding(4) var<storage, read_write> VEC: array<vec4f>;
@group(0) @binding(5) var<storage, read> SDF: array<i32>;
${SPR_COMMON}
${SPR_SDF}
fn vs(i: u32, v: vec3f) { V[3u*i] = v.x; V[3u*i+1u] = v.y; V[3u*i+2u] = v.z; }

// 4. body contact (Bridson et al. 2002): a point that would end the substep closer than
// thick gets just the outward speed to end it at thick; Coulomb friction on the rest
@compute @workgroup_size(64) fn body(@builtin(global_invocation_id) id: vec3u) {
  let i = id.x; if (i >= F.n || wOf(i) == 0.0) { return; }
  var v = vg(i);
  let ps = xg(i) + F.h * v;            // predicted: read-only
  let d = sdf(ps); if (d >= F.thick) { return; }
  let n = sdfNormal(ps);
  let dvn = (F.thick - d) / F.h;
  v += dvn * n;
  VEC[vb(${VB.BN}u, i)] = vec4f(n, 1.0);
  let vn = dot(v, n); let t = v - vn * n; let tl = length(t);
  if (tl > 1e-12) { v = vn * n + t * (max(0.0, tl - F.mu * dvn) / tl); }
  vs(i, v);
}

// 5-8. cloth-on-cloth result, damping, the speed cap, x += h v (the only position update),
// and the safety net for a point deep in the body (it never sets a velocity from the move)
@compute @workgroup_size(64) fn finish(@builtin(global_invocation_id) id: vec3u) {
  let i = id.x; if (i >= F.n) { return; }
  VEC[vb(${VB.F}u, i)] = vec4f(0.0);            // topstitch forces add into it next substep
  let ds = VEC[vb(${VB.DVS}u, i)]; VEC[vb(${VB.DVS}u, i)] = vec4f(0.0);
  let bn = VEC[vb(${VB.BN}u, i)]; VEC[vb(${VB.BN}u, i)] = vec4f(0.0);
  if (wOf(i) == 0.0) { vs(i, vec3f(0.0)); return; }
  var v = vg(i) + ds.xyz;
  v *= 1.0 - (F.damp + F.cdamp * ds.w);
  let sp = length(v);
  var capped = false;
  if (bn.w > 0.0) {   // the body pushed it: the outward push first (up to vmax), the sliding part gets the rest
    var vn = dot(v, bn.xyz);
    if (vn > 0.0 && sp > F.vmax) {
      let t = v - vn * bn.xyz; let tl = length(t);
      vn = min(vn, F.vmax);
      let room = sqrt(max(F.vmax * F.vmax - vn * vn, 0.0));
      v = vn * bn.xyz + t * select(1.0, room / tl, tl > room);
      capped = true;
    }
  }
  if (!capped && sp > F.vmax) { v *= F.vmax / sp; }
  var x = xg(i) + F.h * v;
  let d = sdf(x);
  if (d < -F.deep) {
    let n = sdfNormal(x);
    x += (F.thick - d) * n;
    let vn = dot(v, n); if (vn < 0.0) { v -= vn * n; }
  }
  X[3u*i] = x.x; X[3u*i+1u] = x.y; X[3u*i+2u] = x.z;
  vs(i, v);
}
`;

// ---- module C: cloth on cloth (8 storage buffers, the most a stage may bind). Triangles hashed into a grid once a
// frame (by centroid); every point checks the triangles in the 27 cells around it.
const SPR_FIX = 1048576, SPR_FIXW = 65536;   // fixed-point scales of DVA: dv (m/s), weight
const SPR_SELF_WGSL = /* wgsl */`
@group(0) @binding(0) var<uniform> F: Frame;
@group(0) @binding(1) var<storage, read> X: array<f32>;
@group(0) @binding(2) var<storage, read> V: array<f32>;
@group(0) @binding(3) var<storage, read> PARAM: array<f32>;
@group(0) @binding(4) var<storage, read> TOPO: array<u32>;
@group(0) @binding(5) var<storage, read_write> VEC: array<vec4f>;
@group(0) @binding(6) var<storage, read_write> CNT: array<atomic<u32>>;
@group(0) @binding(7) var<storage, read_write> SLOT: array<u32>;
@group(0) @binding(8) var<storage, read_write> DVA: array<atomic<i32>>;   // per point: dv x, y, z, weight (fixed point)
${SPR_COMMON}
fn tv(t: u32, k: u32) -> u32 { return TOPO[F.oTri + 3u*t + k]; }
fn gone(i: u32) -> bool { return wOf(i) == 0.0 && i32(i) != F.grab; }   // frozen: not there yet
fn x0g(i: u32) -> vec3f { return VEC[vb(${VB.X0}u, i)].xyz; }
fn cellOf(p: vec3f) -> vec3i { return vec3i(floor(p / F.cell)); }
fn hashCell(c: vec3i) -> u32 {
  let h = (u32(c.x) * 73856093u) ^ (u32(c.y) * 19349663u) ^ (u32(c.z) * 83492791u);
  return h % F.ncells;
}
@compute @workgroup_size(64) fn frameStart(@builtin(global_invocation_id) id: vec3u) {
  if (id.x < F.n) { VEC[vb(${VB.X0}u, id.x)] = vec4f(xg(id.x), 0.0); }
  if (id.x < 2u * F.ncells) { atomicStore(&CNT[id.x], 0u); }   // triangles' cells, then the edges'
}
@compute @workgroup_size(64) fn hinsert(@builtin(global_invocation_id) id: vec3u) {
  let t = id.x; if (t >= F.ntri) { return; }
  let h = hashCell(cellOf((xg(tv(t, 0u)) + xg(tv(t, 1u)) + xg(tv(t, 2u))) / 3.0));
  let k = atomicAdd(&CNT[h], 1u);
  if (k < F.slots) { SLOT[h * F.slots + k] = t; }
}
// the candidates, once a frame (as cloth.py ClothSim._self_candidates): triangles within cmargin of
// the point (contact thickness + how far things move this frame), not touching the point's
// seam group (points sewn together: one point once welded). Triangles touching a group next
// to it are NOT skipped (cloth.py _is_near does on the welded mesh): at the armpits and the
// shoulder points the cloth next to a seam lies against the piece it's sewn to, and without
// those contacts it folded through it while sewing (23 edge crossings on the tee, 2 with
// them). Stored after the hash slots: a count, then up to SPR_CAND ids.
fn closestOnTri(p: vec3f, a: vec3f, b: vec3f, c: vec3f) -> vec3f {
  // Ericson, Real-Time Collision Detection 5.1.5
  let ab = b - a; let ac = c - a; let ap = p - a;
  let d1 = dot(ab, ap); let d2 = dot(ac, ap);
  if (d1 <= 0.0 && d2 <= 0.0) { return a; }
  let bp = p - b; let d3 = dot(ab, bp); let d4 = dot(ac, bp);
  if (d3 >= 0.0 && d4 <= d3) { return b; }
  let vc = d1 * d4 - d3 * d2;
  if (vc <= 0.0 && d1 >= 0.0 && d3 <= 0.0) { return a + ab * (d1 / (d1 - d3)); }
  let cp = p - c; let d5 = dot(ab, cp); let d6 = dot(ac, cp);
  if (d6 >= 0.0 && d5 <= d6) { return c; }
  let vb2 = d5 * d2 - d1 * d6;
  if (vb2 <= 0.0 && d2 >= 0.0 && d6 <= 0.0) { return a + ac * (d2 / (d2 - d6)); }
  let va = d3 * d6 - d5 * d4;
  if (va <= 0.0 && (d4 - d3) >= 0.0 && (d5 - d6) >= 0.0) { return b + (c - b) * ((d4 - d3) / ((d4 - d3) + (d5 - d6))); }
  let den = 1.0 / (va + vb2 + vc);
  return a + ab * (vb2 * den) + ac * (vc * den);
}
@compute @workgroup_size(64) fn candidates(@builtin(global_invocation_id) id: vec3u) {
  let p = id.x; if (p >= F.n) { return; }
  let base = F.candAt + p * ${SPR_CAND + 1}u;
  var cnt = 0u;
  if (!gone(p)) {
    let xp = xg(p); let c0 = cellOf(xp);
    let gp = TOPO[F.oGid + p];
    for (var dx = -1; dx <= 1; dx++) { for (var dy = -1; dy <= 1; dy++) { for (var dz = -1; dz <= 1; dz++) {
      let hc = hashCell(c0 + vec3i(dx, dy, dz));
      let n = min(atomicLoad(&CNT[hc]), F.slots);
      for (var k = 0u; k < n; k++) {
        if (cnt >= ${SPR_CAND}u) { break; }
        let t = SLOT[hc * F.slots + k];
        let a = tv(t, 0u); let b = tv(t, 1u); let c = tv(t, 2u);
        if (gone(a) || gone(b) || gone(c)) { continue; }
        let ga = TOPO[F.oGid + a]; let gb = TOPO[F.oGid + b]; let gc = TOPO[F.oGid + c];
        if ((ga == gp && length(xp - xg(a)) < F.selfThick) || (gb == gp && length(xp - xg(b)) < F.selfThick) ||
            (gc == gp && length(xp - xg(c)) < F.selfThick)) { continue; }
        if (length(xp - closestOnTri(xp, xg(a), xg(b), xg(c))) >= F.cmargin) { continue; }
        var dup = false;    // a triangle can sit in two of the hashed cells' lists only once, but cells can collide
        for (var k3 = 0u; k3 < cnt; k3++) { if (SLOT[base + 1u + k3] == t) { dup = true; break; } }
        if (dup) { continue; }
        SLOT[base + 1u + cnt] = t; cnt++;
      }
    }}}
  }
  SLOT[base] = cnt;
}
// springs.py _self_impulses on this frame's candidates (Bridson et al. 2002): the pair's
// relative speed change is split over the point and the triangle's three points by inverse
// mass and barycentric weight, so the triangle side moves too even when no contact of its
// own sees the point (a seam pulling the triangle through a point pinned against the body:
// the shoulder knot). Each point's share adds into DVA (fixed point: WGSL has no float
// atomics) with a weight (1 as the point, its barycentric one as a triangle corner);
// gather divides by max(weight, 1), so a lone contact is applied in full and a point in
// several gets their average. Tested at the predicted positions (read-only), the side from
// the frame start. Approaching: just the speed to end at thick; already overlapping: eased
// apart over tau, to thick, or to half of it when one of them is pressed against the
// body this substep (see below).
fn addDv(i: u32, d: vec3f, wt: f32) {
  let q = vec3i(round(d * ${SPR_FIX.toFixed(1)}));
  atomicAdd(&DVA[4u*i], q.x); atomicAdd(&DVA[4u*i+1u], q.y); atomicAdd(&DVA[4u*i+2u], q.z);
  atomicAdd(&DVA[4u*i+3u], i32(round(wt * ${SPR_FIXW.toFixed(1)})));
}
@compute @workgroup_size(64) fn selfimp(@builtin(global_invocation_id) id: vec3u) {
  let p = id.x; if (p >= F.n || gone(p)) { return; }
  let base = F.candAt + p * ${SPR_CAND + 1}u;
  let cnt = SLOT[base]; if (cnt == 0u) { return; }
  let vp = vg(p); let pp = xg(p) + F.h * vp; let wp = wOf(p);
  for (var k = 0u; k < cnt; k++) {
    let t = SLOT[base + 1u + k];
    let a = tv(t, 0u); let b = tv(t, 1u); let c = tv(t, 2u);
    let va = vg(a); let vb_ = vg(b); let vc = vg(c);
    let A = xg(a) + F.h * va; let Bp = xg(b) + F.h * vb_; let C = xg(c) + F.h * vc;
    let e1 = Bp - A; let e2 = C - A;
    var nrm = cross(e1, e2); let nl = length(nrm); if (nl < 1e-14) { continue; }
    nrm = nrm / nl;
    let ap = pp - A; let dist = dot(ap, nrm);
    if (abs(dist) >= F.selfThick) { continue; }
    let d00 = dot(e1, e1); let d01 = dot(e1, e2); let d11 = dot(e2, e2); let d20 = dot(ap, e1); let d21 = dot(ap, e2);
    let den = d00 * d11 - d01 * d01; if (den < 1e-20) { continue; }
    let bv = (d11 * d20 - d01 * d21) / den; let bw = (d00 * d21 - d01 * d20) / den; let bu = 1.0 - bv - bw;
    if (bu < -0.02 || bv < -0.02 || bw < -0.02) { continue; }
    let s0 = dot(x0g(p) - x0g(a), cross(x0g(b) - x0g(a), x0g(c) - x0g(a)));
    var side = select(-1.0, 1.0, s0 > 0.0);
    if (s0 == 0.0) { side = select(-1.0, 1.0, dist >= 0.0); }
    let gap = side * dist; if (gap >= F.selfThick) { continue; }
    let ua = max(bu, 0.0); let ub = max(bv, 0.0); let uc = max(bw, 0.0);
    let wa = wOf(a); let wb = wOf(b); let wc = wOf(c);
    let wsum = wp + ua * ua * wa + ub * ub * wb + uc * uc * wc; if (wsum <= 0.0) { continue; }
    var need = (F.selfThick - gap) / F.h;
    let vrel = side * dot(vp - ua * va - ub * vb_ - uc * vc, nrm);
    let gapNow = gap - F.h * vrel;
    if (gapNow < F.selfThick) {
      // already overlapping: eased apart over tau. Pressed against the body (one of them
      // touched it this substep), only to half of thick: layers squeezed between the
      // arm and the side can't get thick apart, and easing them to it only fights the body
      // push every substep (0.2 m/s on still points at the armpits); with no easing at all
      // they crept through each other.
      let pressed = VEC[vb(${VB.BN}u, p)].w + VEC[vb(${VB.BN}u, a)].w + VEC[vb(${VB.BN}u, b)].w + VEC[vb(${VB.BN}u, c)].w > 0.0;
      need = max(select(F.selfThick, 0.5 * F.selfThick, pressed) - gapNow, 0.0) / F.tau - vrel;
      if (need <= 0.0) { continue; } }
    let I = nrm * (side * min(need, 0.5 * F.selfThick / F.h) / wsum);
    addDv(p, wp * I, 1.0);
    if (ua * wa > 0.0) { addDv(a, -ua * wa * I, ua); }
    if (ub * wb > 0.0) { addDv(b, -ub * wb * I, ub); }
    if (uc * wc > 0.0) { addDv(c, -uc * wc * I, uc); }
  }
}
// ---- edge on edge (Bridson et al. 2002, section 7.2): point-triangle contacts can't see two
// edges sliding past each other around a triangle's border (seam corners, a fold through the
// piece it's sewn to: the shoulder knot). Mesh edges are the first F.ne springs. Hashed by
// midpoint into cells of F.ecell (wider than the longest edge plus the margin), candidates
// once a frame, each pair kept by its lower edge id only.
fn eiv(e: u32) -> u32 { return TOPO[F.oSpr + 2u*e]; }
fn ejv(e: u32) -> u32 { return TOPO[F.oSpr + 2u*e + 1u]; }
fn ecellOf(p: vec3f) -> vec3i { return vec3i(floor(p / F.ecell)); }
// closest points of segments p1-q1 and p2-q2 (Ericson, Real-Time Collision Detection 5.1.9): (s, t)
fn segST(p1: vec3f, q1: vec3f, p2: vec3f, q2: vec3f) -> vec2f {
  let d1 = q1 - p1; let d2 = q2 - p2; let r = p1 - p2;
  let a = dot(d1, d1); let e = dot(d2, d2); let f = dot(d2, r);
  if (a <= 1e-14 || e <= 1e-14) { return vec2f(0.0); }
  let c = dot(d1, r); let b = dot(d1, d2); let den = a * e - b * b;
  var s = 0.0; if (den > 1e-20) { s = clamp((b * f - c * e) / den, 0.0, 1.0); }
  var t = (b * s + f) / e;
  if (t < 0.0) { t = 0.0; s = clamp(-c / a, 0.0, 1.0); } else if (t > 1.0) { t = 1.0; s = clamp((b - c) / a, 0.0, 1.0); }
  return vec2f(s, t);
}
fn sameSpot(i: u32, j: u32) -> bool {   // one point, or sewn together and (nearly) there
  return i == j || (TOPO[F.oGid + i] == TOPO[F.oGid + j] && length(xg(i) - xg(j)) < F.selfThick);
}
@compute @workgroup_size(64) fn ehinsert(@builtin(global_invocation_id) id: vec3u) {
  let e = id.x; if (e >= F.ne) { return; }
  let h = hashCell(ecellOf(0.5 * (xg(eiv(e)) + xg(ejv(e)))));
  let k = atomicAdd(&CNT[F.ncells + h], 1u);
  if (k < F.eslots) { SLOT[F.eHashAt + h * F.eslots + k] = e; }
}
@compute @workgroup_size(64) fn ecand(@builtin(global_invocation_id) id: vec3u) {
  let e = id.x; if (e >= F.ne) { return; }
  let base = F.eCandAt + e * ${SPR_ECAND + 1}u;
  var cnt = 0u;
  let i = eiv(e); let j = ejv(e);
  if (!gone(i) && !gone(j)) {
    let xi = xg(i); let xj = xg(j); let c0 = ecellOf(0.5 * (xi + xj));
    for (var dx = -1; dx <= 1; dx++) { for (var dy = -1; dy <= 1; dy++) { for (var dz = -1; dz <= 1; dz++) {
      let hc = hashCell(c0 + vec3i(dx, dy, dz));
      let m = min(atomicLoad(&CNT[F.ncells + hc]), F.eslots);
      for (var k = 0u; k < m; k++) {
        if (cnt >= ${SPR_ECAND}u) { break; }
        let f = SLOT[F.eHashAt + hc * F.eslots + k];
        if (f <= e) { continue; }
        let a = eiv(f); let b = ejv(f);
        if (gone(a) || gone(b)) { continue; }
        if (sameSpot(i, a) || sameSpot(i, b) || sameSpot(j, a) || sameSpot(j, b)) { continue; }
        let xa = xg(a); let xb = xg(b); let st = segST(xi, xj, xa, xb);
        if (length(mix(xi, xj, st.x) - mix(xa, xb, st.y)) >= F.cmargin) { continue; }
        var dup = false;
        for (var k3 = 0u; k3 < cnt; k3++) { if (SLOT[base + 1u + k3] == f) { dup = true; break; } }
        if (dup) { continue; }
        SLOT[base + 1u + cnt] = f; cnt++;
      }
    }}}
  }
  SLOT[base] = cnt;
}
// as selfimp, for edge e against its candidates: closest points at the predicted positions, the
// direction across the pair from cross(edge, edge) (from the line between the closest points
// when they're near parallel), the side from the frame start. The push is split over the four
// points by inverse mass and segment weight.
@compute @workgroup_size(64) fn eeimp(@builtin(global_invocation_id) id: vec3u) {
  let e = id.x; if (e >= F.ne) { return; }
  let base = F.eCandAt + e * ${SPR_ECAND + 1}u;
  let cnt = SLOT[base]; if (cnt == 0u) { return; }
  let i = eiv(e); let j = ejv(e);
  let vi = vg(i); let vj = vg(j); let wi = wOf(i); let wj = wOf(j);
  let pi = xg(i) + F.h * vi; let pj = xg(j) + F.h * vj;
  for (var k = 0u; k < cnt; k++) {
    let f = SLOT[base + 1u + k];
    let a = eiv(f); let b = ejv(f);
    let va = vg(a); let vb_ = vg(b); let wa = wOf(a); let wb = wOf(b);
    let pa = xg(a) + F.h * va; let pb = xg(b) + F.h * vb_;
    let st = segST(pi, pj, pa, pb); let s = st.x; let t = st.y;
    let dv = mix(pi, pj, s) - mix(pa, pb, t); let dist = length(dv);
    if (dist >= F.selfThick) { continue; }
    let d1 = pj - pi; let d2 = pb - pa;
    let cr = cross(d1, d2); let cl = length(cr);
    var nrm: vec3f;
    if (cl > 0.05 * sqrt(dot(d1, d1) * dot(d2, d2))) { nrm = cr / cl; }       // more than ~3 degrees apart
    else if (dist > 1e-9) { nrm = dv / dist; } else { continue; }
    let d0 = mix(x0g(i), x0g(j), s) - mix(x0g(a), x0g(b), t);
    let s0 = dot(d0, nrm);
    var side = select(-1.0, 1.0, s0 > 0.0);
    if (s0 == 0.0) { side = select(-1.0, 1.0, dot(dv, nrm) >= 0.0); }
    let gap = side * dot(dv, nrm); if (gap >= F.selfThick) { continue; }
    let ci = 1.0 - s; let cj = s; let ca = 1.0 - t; let cb = t;
    let wsum = ci * ci * wi + cj * cj * wj + ca * ca * wa + cb * cb * wb; if (wsum <= 0.0) { continue; }
    var need = (F.selfThick - gap) / F.h;
    let vrel = side * dot(ci * vi + cj * vj - ca * va - cb * vb_, nrm);
    let gapNow = gap - F.h * vrel;
    if (gapNow < F.selfThick) {   // as selfimp
      let pressed = VEC[vb(${VB.BN}u, i)].w + VEC[vb(${VB.BN}u, j)].w + VEC[vb(${VB.BN}u, a)].w + VEC[vb(${VB.BN}u, b)].w > 0.0;
      need = max(select(F.selfThick, 0.5 * F.selfThick, pressed) - gapNow, 0.0) / F.tau - vrel;
      if (need <= 0.0) { continue; } }
    let I = nrm * (side * min(need, 0.5 * F.selfThick / F.h) / wsum);
    if (ci * wi > 0.0) { addDv(i, ci * wi * I, ci); }
    if (cj * wj > 0.0) { addDv(j, cj * wj * I, cj); }
    if (ca * wa > 0.0) { addDv(a, -ca * wa * I, ca); }
    if (cb * wb > 0.0) { addDv(b, -cb * wb * I, cb); }
  }
}
// the contacts' sum per point into VEC.DVS (finish adds it), divided by max(weight, 1); clears DVA
@compute @workgroup_size(64) fn gather(@builtin(global_invocation_id) id: vec3u) {
  let i = id.x; if (i >= F.n) { return; }
  let q = vec3f(f32(atomicExchange(&DVA[4u*i], 0)), f32(atomicExchange(&DVA[4u*i+1u], 0)), f32(atomicExchange(&DVA[4u*i+2u], 0)));
  let wt = f32(atomicExchange(&DVA[4u*i+3u], 0)) / ${SPR_FIXW.toFixed(1)};
  let any = q.x != 0.0 || q.y != 0.0 || q.z != 0.0 || wt > 0.0;
  if (any) { VEC[vb(${VB.DVS}u, i)] = vec4f(q / (${SPR_FIX.toFixed(1)} * max(wt, 1.0)), 1.0); }
}
`;

class LiveSprings {
  // a GPU this solver can use: WebGPU, an adapter (not a blocklisted driver), and a device that opens with the
  // limits it needs (8 storage buffers per stage). Asked once per page; the answer is kept.
  static supported() {
    return LiveSprings._ok || (LiveSprings._ok = (async () => {
      if (!navigator.gpu) return false;
      try {
        const a = await navigator.gpu.requestAdapter();
        if (!a || a.limits.maxStorageBuffersPerShaderStage < 8) return false;
        const d = await a.requestDevice(); d.destroy(); return true;
      } catch (e) { return false }
    })());
  }
  async init(setup) {
    const adapter = await navigator.gpu.requestAdapter();
    if (!adapter) throw new Error("no GPU adapter");
    this.adapterInfo = adapter.info ? `${adapter.info.vendor} ${adapter.info.architecture || ""} ${adapter.info.description || ""}`.trim() : "";
    const dev = this.dev = await adapter.requestDevice({requiredLimits: {
      maxStorageBufferBindingSize: Math.min(adapter.limits.maxStorageBufferBindingSize, 256 << 20)}});
    this.lost = false; dev.lost.then(() => { this.lost = true });
    const S = setup, SP = S.springs, prm = this.prm = S.params, C = this.consts = SP.consts;
    this.solver = "springs";
    this.n = S.n; this.time = 0; this.capSub = NSUB_CAP_LIVE; this.base = C.substeps; this.substeps = C.substeps; this.h = 1 / prm.fps / C.substeps;
    this.sp = SP; this.nwg = Math.ceil(this.n / SPR_WG);
    this.x0 = b64buf(S.x, Float32Array);
    const mk = (data, usage = GPUBufferUsage.STORAGE) => {
      const size = Math.max(16, Math.ceil(data.byteLength / 4) * 4);
      const b = dev.createBuffer({size, usage: usage | GPUBufferUsage.COPY_DST, mappedAtCreation: true});
      new Uint8Array(b.getMappedRange()).set(new Uint8Array(data.buffer, data.byteOffset, data.byteLength)); b.unmap(); return b;
    };
    const zeros = bytes => dev.createBuffer({size: Math.max(16, bytes), usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST | GPUBufferUsage.COPY_SRC});
    this.X = mk(this.x0, GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC);
    this.V = mk(new Float32Array(this.n * 3), GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC);
    this.param = b64buf(SP.param, Float32Array);
    this.Wfull = this.param.slice(0, this.n);
    const pid = b64buf(S.panel_id, Uint32Array), ps = S.piece_stage || [];
    this.vstage = new Uint8Array(this.n); for (let i = 0; i < this.n; i++) this.vstage[i] = ps[pid[i]] || 1;
    this.stages = prm.stages && prm.stages.length ? prm.stages : [[0, prm.sew_time]];
    this.nStages = this.stages.length; this.stage = 1;
    this.Wd = this._wFor(1); this.param.set(this.Wd, 0);
    this.PARAM = mk(this.param);
    this.TOPO = mk(b64buf(SP.topo, Uint32Array));
    this.VEC = zeros(VB_COUNT * this.n * 16);
    this.TMP = zeros((3 * SP.ns + 2 * SP.nnz) * 16);
    this.SCAL = zeros((4 * this.nwg + 8 + 3 * (SPR_CG_BUDGET + 2)) * 4);
    const sd = S.sdf, q16 = b64buf(sd.data, Int16Array);
    const packed = new Int16Array(q16.length + (q16.length & 1)); packed.set(q16);
    this.SDF = mk(new Int32Array(packed.buffer));
    this.sdfInfo = sd;
    // hash cells hold triangles by centroid: wide enough that a triangle within the candidate margin (<= 15 mm) of a point is in its 27 cells
    this.ntri = S.ntris; this.ncells = 1 << 16; this.slots = 24; this.cell = (S.self_cell || 0.035) + 0.008;
    // edges hashed by midpoint: a cell wider than the longest edge (stretched 20%) plus the largest candidate margin
    const TR = b64buf(S.tris, Uint32Array); let lmax = 0;
    for (let t = 0; t < TR.length; t += 3) for (let q = 0; q < 3; q++) {
      const a = 3 * TR[t + q], b = 3 * TR[t + (q + 1) % 3], X = this.x0;
      lmax = Math.max(lmax, Math.hypot(X[a] - X[b], X[a + 1] - X[b + 1], X[a + 2] - X[b + 2])) }
    this.ecell = 1.2 * lmax + 0.016; this.eslots = 48;
    this.eHashAt = this.ncells * this.slots + this.n * (SPR_CAND + 1); this.eCandAt = this.eHashAt + this.ncells * this.eslots;
    this.CNT = zeros(2 * this.ncells * 4); this.DVA = zeros(this.n * 16);
    this.SLOT = zeros((this.eCandAt + SP.ne * (SPR_ECAND + 1)) * 4);
    this.frameBuf = dev.createBuffer({size: SPR_UBYTES, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST});
    this.staging = dev.createBuffer({size: this.n * 12, usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST});
    this.vStaging = dev.createBuffer({size: this.n * 12, usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST});
    this.scalStaging = dev.createBuffer({size: 16, usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST});
    // batches (dynamic-offset uniforms, 256-byte stride): slot 0 = none, then CG iterations, strain, topstitch
    const slots = [[0, 0, 0, 0]];
    this.itSlot = []; for (let it = 0; it <= SPR_CG_BUDGET; it++) { this.itSlot.push(slots.length); slots.push([0, 0, 0, it]) }
    const batchSlots = offs => { const r = []; for (let k = 0; k + 1 < offs.length; k++) { r.push([slots.length, offs[k + 1] - offs[k]]); slots.push([offs[k], offs[k + 1] - offs[k], 0, 0]) } return r };
    this.strainSlots = batchSlots(SP.edge_batches); this.attachSlots = SP.na ? batchSlots(SP.attach_batches) : [];
    const ub = new Uint32Array(slots.length * 64); slots.forEach((s, k) => ub.set(s, k * 64));
    this.batchBuf = mk(ub, GPUBufferUsage.UNIFORM);
    dev.pushErrorScope("validation");
    const compile = async code => {
      const m = dev.createShaderModule({code}); const info = await m.getCompilationInfo();
      const errs = info.messages.filter(x => x.type === "error"); if (errs.length) throw new Error("WGSL: " + errs.map(x => `${x.lineNum}: ${x.message}`).join("; "));
      return m;
    };
    const layout = types => dev.createBindGroupLayout({entries: types.map((t, b) => ({binding: b, visibility: GPUShaderStage.COMPUTE,
      buffer: {type: t === "u" ? "uniform" : t === "r" ? "read-only-storage" : "storage"}}))});
    const LB = dev.createBindGroupLayout({entries: [{binding: 0, visibility: GPUShaderStage.COMPUTE, buffer: {type: "uniform", hasDynamicOffset: true}}]});
    const group = (L, bufs) => dev.createBindGroup({layout: L, entries: bufs.map((b, i) => ({binding: i, resource: {buffer: b}}))});
    // module A: solve
    const LA = layout(["u", "r", "s", "r", "r", "s", "s", "s"]);
    const mA = await compile(SPR_SOLVE_WGSL), plA = dev.createPipelineLayout({bindGroupLayouts: [LA, LB]});
    this.pA = Object.fromEntries(["forces", "attach", "cgInit", "cgW", "cgStep", "applyDv", "strain"].map(e => [e, dev.createComputePipeline({layout: plA, compute: {module: mA, entryPoint: e}})]));
    this.gA = group(LA, [this.frameBuf, this.X, this.V, this.PARAM, this.TOPO, this.VEC, this.TMP, this.SCAL]);
    this.gB = dev.createBindGroup({layout: LB, entries: [{binding: 0, resource: {buffer: this.batchBuf, size: 16}}]});
    // module B: body + finish
    const LBo = layout(["u", "s", "s", "r", "s", "r"]);
    const mB = await compile(SPR_BODY_WGSL), plB = dev.createPipelineLayout({bindGroupLayouts: [LBo]});
    this.pB = Object.fromEntries(["body", "finish"].map(e => [e, dev.createComputePipeline({layout: plB, compute: {module: mB, entryPoint: e}})]));
    this.gBo = group(LBo, [this.frameBuf, this.X, this.V, this.PARAM, this.VEC, this.SDF]);
    // module C: cloth on cloth
    const LC = layout(["u", "r", "r", "r", "r", "s", "s", "s", "s"]);
    const mC = await compile(SPR_SELF_WGSL), plC = dev.createPipelineLayout({bindGroupLayouts: [LC]});
    this.pC = Object.fromEntries(["frameStart", "hinsert", "candidates", "selfimp", "ehinsert", "ecand", "eeimp", "gather"].map(e => [e, dev.createComputePipeline({layout: plC, compute: {module: mC, entryPoint: e}})]));
    this.gC = group(LC, [this.frameBuf, this.X, this.V, this.PARAM, this.TOPO, this.VEC, this.CNT, this.SLOT, this.DVA]);
    const verr = await dev.popErrorScope(); if (verr) throw new Error("GPU setup: " + verr.message);
    this.selfOn = true; this.selfEnabled = true; this.selfWhileSewing = true; this.selfEvery = 1; this.selfEveryBase = 1;
    // contacts every substep: every other one, the forces closed squeezed layers in between and the next contact pushed them apart again (0.3 m/s buzz at the shoulder)
    this.eeOn = true;   // edge-edge contacts (profiling can turn them off)
    this.grab = -1; this.target = [0, 0, 0]; this.out = new Float32Array(this.n * 3); this.out.set(this.x0);
    this.busy = false; this.steps = 0; this.ms = 0; this.startSpeed = prm.start_speed || 0; this.vMeasured = 0; this.vClamp = prm.max_speed || 3;
    this.speedLimited = false; this.substepsMax = this.substeps; this.lastTarget = null; this.cgIters = 0; this.cgBudget = SPR_CG_BUDGET;
    return this;
  }
  setGrab(i, target) {   // a spring to the mouse (in the implicit solve), not a moved point
    if (i >= 0 && this.frozen(i)) i = -1;    // a piece not sewn on yet can't be pulled
    this.grab = i; if (target) this.target = target;
  }
  reset() {
    this.dev.queue.writeBuffer(this.X, 0, this.x0); this.dev.queue.writeBuffer(this.V, 0, new Float32Array(this.n * 3));
    this.dev.queue.writeBuffer(this.VEC, 0, new Float32Array(VB_COUNT * this.n * 4));   // dv (the CG start guess) too
    this.time = 0; this.out.set(this.x0); this.vMeasured = this.startSpeed; this._setStage(1);
  }
  _wFor(k) { const w = this.Wfull.slice(); for (let i = 0; i < this.n; i++) if (this.vstage[i] > k) w[i] = 0; return w }
  _setStage(k) {
    if (k === this.stage && k !== 1) return;
    this.stage = k; this.Wd = this._wFor(k);
    if (this.startSpeed > 0) this.vMeasured = Math.max(this.vMeasured, this.startSpeed);   // its pieces fly in: plan for it
    this.dev.queue.writeBuffer(this.PARAM, 0, this.Wd);   // inverse masses sit at the start of PARAM
  }
  frozen(i) { return this.vstage[i] > this.stage }
  phase() {   // [stage, "sew" | "settle", label], as ClothSim.phase()
    const t = this.time, S = this.stages, K = this.nStages;
    let k = 1; for (let i = 0; i < K; i++) if (t >= S[i][0]) k = i + 1;
    const sew = t < S[k - 1][0] + S[k - 1][1], nm = (this.prm.stage_names || {})[k] || "the rest";
    const lab = sew ? (k === 1 ? (K > 1 ? "Sewing the body" : "Sewing") : `Attaching ${nm}`) : (k < K ? "Settling" : "Draping");
    return [k, sew ? "sew" : "settle", lab];
  }
  _plan(frames) {   // substeps for this step() call, from the fastest point last time and the mouse
    let vGrab = 0;
    if (this.grab >= 0 && this.lastTarget) vGrab = Math.hypot(...this.target.map((v, k) => v - this.lastTarget[k])) * this.prm.fps / frames;
    this.lastTarget = this.grab >= 0 ? [...this.target] : null;
    // speed substeps only while cloth-on-cloth runs (as springs.py _plan_speed): with it off while the first
    // stage sews (selfWhileSewing false: the drape), extra substeps there stalled every seam at ~60 mm
    const [stg, ph] = this.phase(), sewing1 = stg === 1 && ph === "sew";
    // fast sewing (startSpeed: layers, a lining, several garments), as cloth.py _fast_sewing: while a stage sews, plan
    // for pieces at the speed cap and cap their speed so nothing moves further in a frame than the contact margin
    const fast = this.fastSew = this.startSpeed > 0 && ph === "sew";
    const self = this.selfOn && this.selfEnabled && (!sewing1 || this.selfWhileSewing), vEst = Math.max(SPEED_HEADROOM * this.vMeasured, vGrab, fast ? this.startSpeed : 0);
    const r = self ? planSubsteps(vEst, this.prm.fps, this.base, this.selfEveryBase, this.prm.self_thickness || 0.003, this.capSub,
      this.substeps > this.base ? this.substeps : null) : {nsub: this.base, se: this.selfEveryBase, vClamp: Infinity, limited: false};
    this.substeps = r.nsub; this.selfEvery = r.se; this.h = 1 / this.prm.fps / r.nsub;
    this.vClamp = Math.min(this.prm.max_speed || 3, r.vClamp); this.speedLimited = r.limited;
    if (fast && self) this.vClamp = Math.min(this.vClamp, (SELF_MARGIN_MAX - (this.prm.self_thickness || 0.003)) * this.prm.fps);
    this.substepsMax = Math.max(this.substepsMax, r.nsub);
    // Candidate rebuilds: the lists hold what lies within cmargin, capped at 15 mm, so something
    // moving faster than that between rebuilds can meet a triangle that isn't on its list (a fast
    // yank moves the cloth ~10 cm a frame and folded it through itself about one yank in 20).
    // Rebuild every `rebuildEvery` substeps so the motion between rebuilds fits in the margin.
    const st = this.prm.self_thickness || 0.003, fit = (0.015 - st) / 2;
    const dFrame = Math.min(this.vClamp, Math.max(1.25 * this.vMeasured, vGrab)) / this.prm.fps;
    const nReb = Math.min(this.substeps, Math.max(1, Math.ceil(dFrame / fit)));
    this.rebuildEvery = Math.ceil(this.substeps / nReb);
    this.dRebuild = dFrame * this.rebuildEvery / this.substeps;
  }
  _frame() {
    const p = this.prm, C = this.consts, SP = this.sp, t = this.time, sew = p.sew_time;
    const tight = sew > 0 ? Math.min(t / sew, 1) : 1;
    const [k, ph] = this.phase(); if (k !== this.stage) this._setStage(k);
    const sewingNow = ph === "sew";
    const gs = p.gravity_ramp > 0 ? Math.min(Math.max((t - sew) / p.gravity_ramp, 0), 1) : 1;
    const ns = this.substeps, ref = C.ref_substeps || 40;
    let damp = 1 - Math.pow(1 - p.damping, 1 / ns);
    if (sewingNow) damp = Math.max(damp, 1 - Math.pow(0.99, ref / ns));   // as springs.py step()
    const cdamp = 1 - Math.pow(1 - C.contact_damp, ref / ns);
    const buf = new ArrayBuffer(SPR_UBYTES), fv = new Float32Array(buf), uv = new Uint32Array(buf), iv = new Int32Array(buf);
    const set = (name, val) => {
      const k = SPR_FIELDS.findIndex(f => f[0] === name), ty = SPR_FIELDS[k][1];
      (ty === "f32" ? fv : ty === "u32" ? uv : iv)[k] = val;
    };
    const s = this.sdfInfo, T = SP.toff, P = SP.poff;
    const vals = {h: this.h, g: -9.81 * gs, damp, ease: 1 - tight, cdamp, thick: p.thickness, mu: p.friction, n: this.n,
      grab: this.grab, grabK: this.grab >= 0 ? SPR_GRAB_K : 0, selfThick: p.self_thickness || 0.003, cell: this.cell,
      tx: this.target[0], ty: this.target[1], tz: this.target[2], vmax: this.vClamp,
      sox: s.origin[0], soy: s.origin[1], soz: s.origin[2], soh: s.h, sdx: s.dims[0], sdy: s.dims[1], sdz: s.dims[2],
      ntri: this.ntri, ncells: this.ncells, slots: this.slots, ns: SP.ns, nh: SP.nh, ne: SP.ne,
      sewStage: k > 1 && sewingNow ? k : 0, unfoldOn: k === 1 && t < sew ? 1 : 0, nwg: this.nwg,
      tau: C.self_tau, deep: C.deep, tol2: C.cg_tol * C.cg_tol, cgMax: this.cgBudget,
      // candidate margin as cloth.py: thickness + 2 x the motion between rebuilds (a frame's, when
      // the lists are built once a frame), 1 mm .. 15 mm
      cmargin: this.fastSew ? SELF_MARGIN_MAX : Math.min(Math.max((p.self_thickness || 0.003) + 2 * (this.dRebuild ?? this.vMeasured / p.fps), (p.self_thickness || 0.003) + 0.001), SELF_MARGIN_MAX),
      candAt: this.ncells * this.slots, ecell: this.ecell, eslots: this.eslots, eHashAt: this.eHashAt, eCandAt: this.eCandAt,
      oSpr: T.spr, oIncs: T.incs, oInc: T.inc, oIncslot: T.incslot, oRows: T.rows, oRcol: T.rcol, oAtt: T.att, oTri: T.tri,
      oGid: T.gid, pSpr: P.spr, pAtt: P.att, pBk: P.bk};
    for (const [name, val] of Object.entries(vals)) set(name, val);
    for (let q = 0; q < 4; q++) {   // per stage: seam rest scale (-1: not started), the sewn side's share while it sews
      const st = this.stages[q];
      const tk = st ? (st[1] > 0 ? Math.min(Math.max((t - st[0]) / st[1], 0), 1) : 1) : 1;
      set("seamS" + q, st && q + 1 <= k ? 1 - tk : -1);
      set("seamA" + q, st && q > 0 && q + 1 === k && sewingNow ? (p.anchor_w || 0.05) : 1);
    }
    this.dev.queue.writeBuffer(this.frameBuf, 0, buf);
    return sewingNow && k === 1;
  }
  async step(frames = 1) {
    if (this.busy || this.lost) return null;
    this.busy = true; const t0 = performance.now();
    const dev = this.dev, SP = this.sp, wg = (n, s = 64) => Math.ceil(n / s);
    this._plan(frames);
    if (this.fixedBudget != null) this.cgBudget = this.fixedBudget;   // profiling and tests
    for (let fr = 0; fr < frames; fr++) {
      const sewing = this._frame();
      dev.queue.writeBuffer(this.SCAL, (4 * this.nwg + 2) * 4, new Float32Array([0, 0]));   // most iterations, budget hit: per frame
      const self = this.selfEnabled && (!sewing || this.selfWhileSewing);
      const enc = dev.createCommandEncoder(), pass = enc.beginComputePass();
      const A = (e, n, slot = 0) => { pass.setPipeline(this.pA[e]); pass.setBindGroup(0, this.gA); pass.setBindGroup(1, this.gB, [slot * 256]); pass.dispatchWorkgroups(n) };
      const Bo = (e) => { pass.setPipeline(this.pB[e]); pass.setBindGroup(0, this.gBo); pass.dispatchWorkgroups(wg(this.n)) };
      const Cs = (e, n) => { pass.setPipeline(this.pC[e]); pass.setBindGroup(0, this.gC); pass.dispatchWorkgroups(n) };
      const reb = this.rebuildEvery || this.substeps;
      for (let s = 0; s < this.substeps; s++) {
        if (s % reb === 0) {   // frame start (and, moving fast, every reb substeps): the lists and the sides
          Cs("frameStart", wg(Math.max(this.n, 2 * this.ncells)));
          if (self) { Cs("hinsert", wg(this.ntri)); Cs("candidates", wg(this.n)); if (this.eeOn) { Cs("ehinsert", wg(SP.ne)); Cs("ecand", wg(SP.ne)) } }
        }
        for (const [slot, cnt] of this.attachSlots) A("attach", wg(cnt), slot);
        A("forces", wg(SP.ns));
        A("cgInit", this.nwg); A("cgW", this.nwg, this.itSlot[0]);
        for (let it = 0; it < this.cgBudget; it++) {
          A("cgStep", this.nwg, this.itSlot[it]);
          if (it + 1 < this.cgBudget) A("cgW", this.nwg, this.itSlot[it + 1]);
        }
        A("applyDv", wg(this.n));
        for (let li = 0; li < this.consts.limit_iters; li++) for (const [slot, cnt] of this.strainSlots) A("strain", wg(cnt), slot);
        Bo("body");
        if (self && (s % this.selfEvery === this.selfEvery - 1)) { Cs("selfimp", wg(this.n)); if (this.eeOn) Cs("eeimp", wg(SP.ne)); Cs("gather", wg(this.n)) }
        Bo("finish");
      }
      pass.end();
      if (fr === frames - 1) {
        enc.copyBufferToBuffer(this.X, 0, this.staging, 0, this.n * 12);
        enc.copyBufferToBuffer(this.V, 0, this.vStaging, 0, this.n * 12);
        enc.copyBufferToBuffer(this.SCAL, (4 * this.nwg + 1) * 4, this.scalStaging, 0, 12);
      }
      dev.queue.submit([enc.finish()]);
      this.time += 1 / this.prm.fps; this.steps++;
    }
    this.msEncode = performance.now() - t0;
    try { await Promise.all([this.staging.mapAsync(GPUMapMode.READ), this.vStaging.mapAsync(GPUMapMode.READ), this.scalStaging.mapAsync(GPUMapMode.READ)]) }
    catch (e) { this.busy = false; return null }   // destroyed meanwhile
    this.out.set(new Float32Array(this.staging.getMappedRange())); this.staging.unmap();
    const sc = new Float32Array(this.scalStaging.getMappedRange()).slice(); this.scalStaging.unmap();
    // CG iterations: the most any substep used; the next call's budget follows it (and grows
    // if the budget stopped a solve before it converged)
    this.cgIters = sc[1]; this.cgBudgetHit = sc[2] > 0.5;
    this.cgBudget = this.cgBudgetHit ? Math.min(SPR_CG_BUDGET, this.cgBudget + 8) : Math.min(SPR_CG_BUDGET, Math.max(8, sc[1] + 2));
    let v2 = 0;
    // the fastest point, from the solver's own velocities (as springs.py reads sim.v): it sets
    // the next call's substeps and the cloth-on-cloth margin
    const vel = new Float32Array(this.vStaging.getMappedRange());
    for (let i = 0; i < this.n; i++) { const d = vel[3*i] * vel[3*i] + vel[3*i+1] * vel[3*i+1] + vel[3*i+2] * vel[3*i+2]; if (d > v2) v2 = d }
    this.vStaging.unmap();
    this.vMeasured = Math.sqrt(v2);
    this.ms = performance.now() - t0; this.busy = false;
    return this.out;
  }
  destroy() { try { this.dev.destroy() } catch (e) { } }
}
window.LiveSprings = LiveSprings;
