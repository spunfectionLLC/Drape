"""Settling experiments: shader variants on a test copy of live_springs.js, the drape in 'ref' (welds
at springs.py's times) or 'end' mode. usage: settle.py variant mode [block fabric]"""
import json, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, "."); sys.path.insert(0, "tools")
import numpy as np
variant, mode = sys.argv[1], sys.argv[2]
block = sys.argv[3] if len(sys.argv) > 3 else "trousers"; fabn = sys.argv[4] if len(sys.argv) > 4 else "poplin"
import export_wgsl as E
from drape import gpu
src = E.SRC.read_text(encoding="utf-8")
NBR = '''fn meshNbr(p: u32, q: u32) -> bool {
  for (var c = TOPO[F.oIncs + p]; c < TOPO[F.oIncs + p + 1u]; c++) {
    let ent = TOPO[F.oInc + c]; let e = ent >> 1u;
    if (e >= F.ne) { continue; }
    let o = select(TOPO[F.oSpr + 2u*e], TOPO[F.oSpr + 2u*e + 1u], (ent & 1u) == 0u);
    if (o == q) { return true; }
  }
  return false;
}
@compute @workgroup_size(64) fn candidates('''
if "nbr" in variant:
    src = src.replace("@compute @workgroup_size(64) fn candidates(", NBR, 1)
    src = src.replace("(gc == gp && length(xp - xg(c)) < F.selfThick)) { continue; }",
                      "(gc == gp && length(xp - xg(c)) < F.selfThick)) { continue; }\n        if (meshNbr(p, a) || meshNbr(p, b) || meshNbr(p, c)) { continue; }", 1)
if "nopress" in variant:     # the target is always the full thickness (as springs.py)
    n0 = src.count("select(F.selfThick, 0.5 * F.selfThick, pressed)")
    src = src.replace("select(F.selfThick, 0.5 * F.selfThick, pressed)", "F.selfThick"); assert n0 == 2
if "iter2" in variant:       # contacts see the pushes already gathered this substep; gather adds up
    src = src.replace("fn x0g(i: u32) -> vec3f {", "fn vgs(i: u32) -> vec3f { return vg(i) + VEC[vb(${VB.DVS}u, i)].xyz; } fn x0g(i: u32) -> vec3f {", 1)
    a = src.index("fn selfimp("); b = src.index("fn gather(")
    body = src[a:b]
    for old, new in (("let vp = vg(p);", "let vp = vgs(p);"), ("let va = vg(a); let vb_ = vg(b); let vc = vg(c);", "let va = vgs(a); let vb_ = vgs(b); let vc = vgs(c);"),
                     ("let vi = vg(i); let vj = vg(j);", "let vi = vgs(i); let vj = vgs(j);"), ("let va = vg(a); let vb_ = vg(b); let wa", "let va = vgs(a); let vb_ = vgs(b); let wa")):
        assert old in body, old; body = body.replace(old, new)
    src = src[:a] + body + src[b:]
    old = "if (any) { VEC[vb(${VB.DVS}u, i)] = vec4f(q / (${SPR_FIX.toFixed(1)} * max(wt, 1.0)), 1.0); }"
    assert old in src
    src = src.replace(old, "if (any) { let pv = VEC[vb(${VB.DVS}u, i)]; VEC[vb(${VB.DVS}u, i)] = vec4f(pv.xyz + q / (${SPR_FIX.toFixed(1)} * max(wt, 1.0)), 1.0); }")
if "cand" in variant:        # longer candidate lists per point / per edge
    assert "const SPR_CAND = 24;" in src and "const SPR_ECAND = 16;" in src
    src = src.replace("const SPR_CAND = 24;", "const SPR_CAND = 64;").replace("const SPR_ECAND = 16;", "const SPR_ECAND = 32;")
tmp = Path(sys.argv[0]).parent / f"lsp_{variant}.js"; tmp.write_text(src, encoding="utf-8")
gpu._W = json.loads(subprocess.run(["node", "-e", E.NODE_SCRIPT, str(tmp)], capture_output=True, text=True, encoding="utf-8", check=True).stdout)
if "iter2" in variant: gpu.SELF_ITERS = 2
from drape.fabrics import get, panel_fabrics
from drape.springs import SpringSimulator
from drape.live import sim_setup
from drape.studio import server as Srv
init = Srv.api_init(); a = Srv.api_avatar({"measurements": init["examples"]["female_M"]}); A = Srv.S.avatars[a["id"]]
from drape.blocks import draft_block
g, _ = draft_block(block, A["body"], A["meas"]); fab = get(fabn)
sim = SpringSimulator(panel_fabrics(g, fab), A["body"], fab)
n = int((3.5 + sim.extra_time) * sim.fps)
t0 = time.time()
if mode == "ref":
    gpu.drape_on_gpu(sim, n)
else:
    gp = gpu.GPUSprings(sim_setup(sim, sim.body, fabn, grid_h=sim.body.h)); gp.self_while_sewing = False
    for _ in range(n): gp.step(1)
    sim.x[:] = gp.positions(); sim.v[:] = gp.velocities(); sim.time = gp.time
    if sim.do_weld and not sim.welded and len(sim.g.seams): sim.weld()
m = sim.metrics()
print(f"{block}/{fabn} {variant} {mode}: {time.time()-t0:.0f} s  KE {m['kinetic_energy_uJ']:.2f} uJ  inside {m['penetrating_verts']}  p99 {m['strain_p99_pct']:.2f}%  v_max {m['max_speed_mm_s']:.0f} mm/s", flush=True)
