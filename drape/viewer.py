"""Self-contained interactive 3D viewer (one HTML file, plain WebGL, no
downloads): orbit with mouse/touch, pinch or wheel to zoom, toggle the fit
map and the avatar. Meshes are embedded as base64 int16 millimetres."""
from __future__ import annotations

import base64
import json

import numpy as np

from .render import body_mesh, strain_colors, garment_colors


def _b64(a):
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def _mesh_payload(v, f, colors=None):
    q = np.round(np.asarray(v) * 1000).astype(np.int16)          # mm
    d = {"v": _b64(q), "f": _b64(np.asarray(f, np.uint32)), "nv": int(len(v)), "nf": int(len(f))}
    if colors is not None:
        for k, c in colors.items():
            d[k] = _b64(np.round(np.clip(c, 0, 1) * 255).astype(np.uint8))
    return d


def export_viewer(path, body, x, tris, panel_id, edges, edge_rest, title="Spunfection Studio", info=None,
                  body_res=0.012, fine_res=0.005, max_strain=0.08):
    bv, bf = body.mesh(res=body_res, fine=fine_res) if hasattr(body, "mesh") else body_mesh(body, res=body_res, fine=fine_res)
    # orient faces outward (WebGL computes normals from winding): compare each
    # face normal with the SDF gradient at its centroid and flip the inward ones
    c = bv[bf].mean(1)
    fn = np.cross(bv[bf[:, 1]] - bv[bf[:, 0]], bv[bf[:, 2]] - bv[bf[:, 0]])
    e = 1e-4
    grad = np.stack([body.sdf(c + d) - body.sdf(c - d) for d in np.eye(3) * e], 1)
    inward = (fn * grad).sum(1) < 0
    bf = bf.copy(); bf[inward] = bf[inward][:, [0, 2, 1]]
    fit, _ = strain_colors(x, edges, edge_rest, max_strain)
    data = {
        "title": title,
        "info": info or {},
        "max_strain_pct": max_strain * 100,
        "body": _mesh_payload(bv, bf),
        "cloth": _mesh_payload(x, tris, {"panel": garment_colors(panel_id), "fit": fit}),
    }
    html = _TEMPLATE.replace("/*DATA*/", json.dumps(data)).replace("{{TITLE}}", title)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return {"body_tris": int(len(bf)), "cloth_tris": int(len(tris)), "bytes": len(html)}


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>{{TITLE}}</title>
<style>
  :root{--bg:#f4f3ef;--ink:#1f2328;--muted:#6b6f76;--line:#d9d6cf;--chip:#ffffff;--on:#1f2328;--onink:#fff}
  @media (prefers-color-scheme:dark){:root{--bg:#17181a;--ink:#ececec;--muted:#a0a3a8;--line:#33363b;--chip:#222428;--on:#ececec;--onink:#17181a}}
  html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);font:14px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;overflow:hidden}
  canvas{position:fixed;inset:0;width:100%;height:100%;touch-action:none;display:block}
  header{position:fixed;left:12px;top:10px;right:12px;pointer-events:none}
  h1{font-size:15px;margin:0 0 2px;font-weight:600}
  .sub{color:var(--muted);font-size:12px}
  .bar{position:fixed;left:50%;bottom:14px;transform:translateX(-50%);display:flex;gap:6px;flex-wrap:wrap;justify-content:center;max-width:94vw}
  button{appearance:none;border:1px solid var(--line);background:var(--chip);color:var(--ink);border-radius:999px;padding:8px 13px;font:inherit;font-size:13px;cursor:pointer}
  button[aria-pressed=true]{background:var(--on);color:var(--onink);border-color:var(--on)}
  .legend{position:fixed;right:12px;top:60px;display:none;align-items:stretch;gap:6px;font-size:11px;color:var(--muted)}
  .legend .grad{width:12px;height:160px;border-radius:3px;background:linear-gradient(to top,#3359cc,#26b366,#f2d933,#d9261f)}
  .legend .ticks{display:flex;flex-direction:column;justify-content:space-between;height:160px}
  .hint{position:fixed;left:12px;bottom:62px;color:var(--muted);font-size:11px}
  .stats{position:fixed;left:12px;top:52px;color:var(--muted);font-size:11px;white-space:pre;line-height:1.5}
</style></head><body>
<canvas id="c"></canvas>
<header><h1 id="t"></h1><div class="sub" id="s"></div></header>
<div class="stats" id="st"></div>
<div class="legend" id="lg"><div class="grad"></div><div class="ticks" id="tk"></div></div>
<div class="hint">drag to orbit · pinch / scroll to zoom · double-tap to reset</div>
<div class="bar">
  <button id="bFit" aria-pressed="false">Fit map</button>
  <button id="bBody" aria-pressed="true">Avatar</button>
  <button id="bFront">Front</button><button id="bSide">Side</button><button id="bBack">Back</button>
  <button id="bSpin" aria-pressed="false">Spin</button>
</div>
<script>
const D = /*DATA*/;
const $ = id => document.getElementById(id);
$("t").textContent = D.title;
$("s").textContent = D.info.subtitle || "";
$("st").textContent = Object.entries(D.info.stats || {}).map(([k,v]) => k + ": " + v).join("\n");
$("tk").innerHTML = [1,0.75,0.5,0.25,0].map(f => "<span>" + (f*D.max_strain_pct).toFixed(0) + "%</span>").join("");

function dec(b64, T){ const s = atob(b64), u = new Uint8Array(s.length); for (let i=0;i<s.length;i++) u[i]=s.charCodeAt(i); return new T(u.buffer); }
const cv = $("c"), gl = cv.getContext("webgl", {antialias:true}) ;
if (!gl) { document.body.innerHTML = "<p style='padding:20px'>WebGL is not available in this browser.</p>"; }
const ext = gl.getExtension("OES_element_index_uint");

function build(m, colorKeys){
  const q = dec(m.v, Int16Array), f = dec(m.f, Uint32Array);
  const pos = new Float32Array(q.length); for (let i=0;i<q.length;i++) pos[i] = q[i]/1000;
  const nrm = new Float32Array(pos.length);
  for (let t=0;t<f.length;t+=3){
    const a=f[t]*3,b=f[t+1]*3,c=f[t+2]*3;
    const ux=pos[b]-pos[a],uy=pos[b+1]-pos[a+1],uz=pos[b+2]-pos[a+2];
    const vx=pos[c]-pos[a],vy=pos[c+1]-pos[a+1],vz=pos[c+2]-pos[a+2];
    const nx=uy*vz-uz*vy, ny=uz*vx-ux*vz, nz=ux*vy-uy*vx;
    for (const k of [a,b,c]){ nrm[k]+=nx; nrm[k+1]+=ny; nrm[k+2]+=nz; }
  }
  for (let i=0;i<nrm.length;i+=3){ const l=Math.hypot(nrm[i],nrm[i+1],nrm[i+2])||1; nrm[i]/=l; nrm[i+1]/=l; nrm[i+2]/=l; }
  const mk = (data, target=gl.ARRAY_BUFFER) => { const b=gl.createBuffer(); gl.bindBuffer(target,b); gl.bufferData(target,data,gl.STATIC_DRAW); return b; };
  const o = {pos: mk(pos), nrm: mk(nrm), idx: mk(f, gl.ELEMENT_ARRAY_BUFFER), n: f.length, cols:{}};
  for (const k of colorKeys){
    const u = dec(m[k], Uint8Array), c = new Float32Array(u.length); for (let i=0;i<u.length;i++) c[i]=u[i]/255;
    o.cols[k] = mk(c);
  }
  if (!colorKeys.length){ const c=new Float32Array(pos.length); for(let i=0;i<c.length;i+=3){c[i]=0.78;c[i+1]=0.74;c[i+2]=0.70;} o.cols.solid = mk(c); }
  let mn=[1e9,1e9,1e9], mx=[-1e9,-1e9,-1e9];
  for (let i=0;i<pos.length;i+=3) for (let a=0;a<3;a++){ mn[a]=Math.min(mn[a],pos[i+a]); mx[a]=Math.max(mx[a],pos[i+a]); }
  o.min=mn; o.max=mx; return o;
}

const VS = `attribute vec3 p; attribute vec3 n; attribute vec3 c;
uniform mat4 M; varying vec3 vn; varying vec3 vc; varying vec3 vp;
void main(){ vn=n; vc=c; vp=p; gl_Position=M*vec4(p,1.0); }`;
const FS = `precision mediump float; varying vec3 vn; varying vec3 vc; varying vec3 vp;
uniform vec3 L; uniform vec3 E; uniform float twoSided;
void main(){ vec3 n=normalize(vn); vec3 v=normalize(E-vp);
  if (twoSided>0.5 && dot(n,v)<0.0) n=-n;
  float d=max(dot(n,L),0.0); float back=max(dot(n,-L),0.0)*0.15;
  vec3 h=normalize(L+v); float sp=pow(max(dot(n,h),0.0),24.0)*0.08;
  gl_FragColor=vec4(vc*(0.30+0.70*d+back)+sp,1.0); }`;
function sh(t,s){ const o=gl.createShader(t); gl.shaderSource(o,s); gl.compileShader(o); return o; }
const prog = gl.createProgram(); gl.attachShader(prog, sh(gl.VERTEX_SHADER,VS)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER,FS)); gl.linkProgram(prog); gl.useProgram(prog);
const A = {p:gl.getAttribLocation(prog,"p"), n:gl.getAttribLocation(prog,"n"), c:gl.getAttribLocation(prog,"c")};
const U = {M:gl.getUniformLocation(prog,"M"), L:gl.getUniformLocation(prog,"L"), E:gl.getUniformLocation(prog,"E"), two:gl.getUniformLocation(prog,"twoSided")};

const body = build(D.body, []), cloth = build(D.cloth, ["panel","fit"]);
const target = [0, (cloth.min[1]+cloth.max[1])/2, 0];
const home = {yaw: 0.5, pitch: 0.12, dist: Math.max(1.4, (cloth.max[1]-cloth.min[1])*2.3)};
let cam = {...home}, showFit=false, showBody=true, spin=false;

function persp(fov, asp, n, f){ const t=1/Math.tan(fov/2); return [t/asp,0,0,0, 0,t,0,0, 0,0,(f+n)/(n-f),-1, 0,0,2*f*n/(n-f),0]; }
function lookAt(e, c, u){ let z=[e[0]-c[0],e[1]-c[1],e[2]-c[2]]; let l=Math.hypot(...z); z=z.map(a=>a/l);
  let x=[u[1]*z[2]-u[2]*z[1], u[2]*z[0]-u[0]*z[2], u[0]*z[1]-u[1]*z[0]]; l=Math.hypot(...x); x=x.map(a=>a/l);
  const y=[z[1]*x[2]-z[2]*x[1], z[2]*x[0]-z[0]*x[2], z[0]*x[1]-z[1]*x[0]];
  return [x[0],y[0],z[0],0, x[1],y[1],z[1],0, x[2],y[2],z[2],0, -(x[0]*e[0]+x[1]*e[1]+x[2]*e[2]), -(y[0]*e[0]+y[1]*e[1]+y[2]*e[2]), -(z[0]*e[0]+z[1]*e[1]+z[2]*e[2]), 1]; }
function mul(a,b){ const o=new Array(16).fill(0); for(let i=0;i<4;i++)for(let j=0;j<4;j++)for(let k=0;k<4;k++) o[j*4+i]+=a[k*4+i]*b[j*4+k]; return o; }

function draw(o, colKey, two){
  gl.bindBuffer(gl.ARRAY_BUFFER,o.pos); gl.enableVertexAttribArray(A.p); gl.vertexAttribPointer(A.p,3,gl.FLOAT,false,0,0);
  gl.bindBuffer(gl.ARRAY_BUFFER,o.nrm); gl.enableVertexAttribArray(A.n); gl.vertexAttribPointer(A.n,3,gl.FLOAT,false,0,0);
  gl.bindBuffer(gl.ARRAY_BUFFER,o.cols[colKey]); gl.enableVertexAttribArray(A.c); gl.vertexAttribPointer(A.c,3,gl.FLOAT,false,0,0);
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,o.idx); gl.uniform1f(U.two, two?1:0);
  gl.drawElements(gl.TRIANGLES,o.n,gl.UNSIGNED_INT,0);
}
function frame(){
  const dpr=Math.min(window.devicePixelRatio||1,2), w=cv.clientWidth*dpr, h=cv.clientHeight*dpr;
  if (cv.width!==w||cv.height!==h){ cv.width=w; cv.height=h; }
  if (spin) cam.yaw += 0.006;
  const asp = w / h, dist = cam.dist * Math.max(1, 0.85 / asp);  // portrait screens: back off
  gl.viewport(0,0,w,h);
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  dark ? gl.clearColor(0.09,0.094,0.10,1) : gl.clearColor(0.957,0.953,0.937,1);
  gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT); gl.enable(gl.DEPTH_TEST);
  const e=[target[0]+dist*Math.sin(cam.yaw)*Math.cos(cam.pitch), target[1]+dist*Math.sin(cam.pitch), target[2]+dist*Math.cos(cam.yaw)*Math.cos(cam.pitch)];
  gl.uniformMatrix4fv(U.M,false,new Float32Array(mul(persp(0.62,w/h,0.05,20), lookAt(e,target,[0,1,0]))));
  const L=[e[0]-target[0]+0.6, e[1]-target[1]+1.2, e[2]-target[2]+0.4]; const l=Math.hypot(...L);
  gl.uniform3fv(U.L, L.map(a=>a/l)); gl.uniform3fv(U.E, e);
  if (showBody) draw(body,"solid",false);
  draw(cloth, showFit?"fit":"panel", true);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

// interaction: one pointer orbits, two pointers pinch-zoom
const pts=new Map(); let pinch0=null, lastTap=0;
cv.addEventListener("pointerdown",e=>{ cv.setPointerCapture(e.pointerId); pts.set(e.pointerId,[e.clientX,e.clientY]);
  const now=Date.now(); if (now-lastTap<300){ cam={...home}; } lastTap=now; });
cv.addEventListener("pointermove",e=>{ if(!pts.has(e.pointerId)) return; const [x0,y0]=pts.get(e.pointerId); pts.set(e.pointerId,[e.clientX,e.clientY]);
  if (pts.size===1){ cam.yaw -= (e.clientX-x0)*0.008; cam.pitch = Math.max(-1.2,Math.min(1.2,cam.pitch+(e.clientY-y0)*0.006)); }
  else if (pts.size===2){ const [a,b]=[...pts.values()]; const d=Math.hypot(a[0]-b[0],a[1]-b[1]); if(pinch0) cam.dist=Math.max(0.3,Math.min(8,cam.dist*pinch0/d)); pinch0=d; } });
const up=e=>{ pts.delete(e.pointerId); if(pts.size<2) pinch0=null; };
cv.addEventListener("pointerup",up); cv.addEventListener("pointercancel",up);
cv.addEventListener("wheel",e=>{ e.preventDefault(); cam.dist=Math.max(0.3,Math.min(8,cam.dist*Math.exp(e.deltaY*0.001))); },{passive:false});

const tog=(id,fn)=>$(id).addEventListener("click",()=>{ const v=$(id).getAttribute("aria-pressed")!=="true"; $(id).setAttribute("aria-pressed",v); fn(v); });
tog("bFit", v=>{ showFit=v; $("lg").style.display=v?"flex":"none"; });
tog("bBody", v=>{ showBody=v; });
tog("bSpin", v=>{ spin=v; });
$("bFront").onclick=()=>{ cam.yaw=0; cam.pitch=0.1; };
$("bSide").onclick=()=>{ cam.yaw=Math.PI/2; cam.pitch=0.1; };
$("bBack").onclick=()=>{ cam.yaw=Math.PI; cam.pitch=0.1; };
</script></body></html>
"""
