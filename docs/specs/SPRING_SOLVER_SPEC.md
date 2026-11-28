# Spec: mass-spring cloth solver with stability-limited dynamic substeps

**For:** Claude Code, working in the drape repo (v1.4.1).
**Goal:** add a second cloth solver, a force-based mass-spring model (Provot 1995 era), behind a switch, **on both CPU (numba) and GPU (WebGPU live mode)**. Choose the substep count each frame from the explicit-integration stability limit so the cloth can never blow up. Then benchmark it against the current XPBD solver.

**Why:** drape uses mass-spring cloth (explicit integration and strain limiting, 1995–2003) instead of XPBD. **Do not route the new solver through any XPBD code path**: no Lagrange multipliers, no compliance-based constraint projection. Collision push-out and self-collision can be shared; they are standard collision handling. Keep the strain-limit clamp (step 4 below) isolated in its own function, so it can be reviewed by itself.

XPBD stays the default. Don't change its behaviour; all existing tests must still pass.

---

## 1. Model

Each particle is a mesh vertex with mass `m` (from `garment.mass`, after the density rescale the Simulator already does).

| Term | Force on vertex | Stiffness source |
|---|---|---|
| **Stretch/shear springs**: every mesh edge, rest length = `edge_rest` (flat pattern) | `f_i = -k_e (L - r) d/L`, `f_j = -f_i`, where `d = x_i - x_j` | `k_e = k_fabric / aniso_factor` (see 2) |
| **Bending**: reuse the isometric hinges (`hinge_setup`: `H = Σ K_q x_q`, scale `s`) | energy `½ k_b s² ‖H‖²` gives `f_q = -k_b s² K_q H` | `k_b = 1 / bend_compliance`. This is the same energy XPBD minimizes, so **no re-tuning is needed**. The energy is quadratic with a constant Hessian, so it is perfectly stable for explicit integration. |
| **Seams while sewing** (before the weld): spring with rest `seam_rest0 · (1 - tight)` | same as stretch | `k_s = SEAM_K · max(k_v[a], k_v[b])`, where `k_v` is the stiffest edge at a vertex. `SEAM_K = 2`. |
| **Unfold springs while sewing** (`g.bends`, same condition as today's XPBD unfold) | same as stretch | `k_u = 1 / UNFOLD_COMPLIANCE` (100 N/m) |
| **Topstitch/attach**, one-sided: only when `L > rest` | on `av`: `-k_a C D/L`; on triangle vertex r: `+k_a C b_r D/L`, where `D = x_av - Σ b_r x_r` and `C = L - rest` | `k_a = SEAM_K · k_v[av]` |
| **Gravity** | `m g` (ramped, as today) | — |

**Strain limiting (Provot 1995):** after each position update, any edge longer than `(1 + lock_strain) · rest` is clamped back to that length, split by inverse mass. This is what makes wovens behave: soft springs give a little, then the yarns lock. This step replaces XPBD's `LOCK_FACTOR` stiffening. **Do not add stiffening to the springs**, because that would invalidate the stability bound.

**Body collision, friction, self-collision, posed bodies, the speed clamp (`MAX_SPEED`), untangling:** reuse the existing jitted functions (`_collide`, `_collide_posed`, `_self_collide`) unchanged.

## 2. Fabric stiffness

- Add a field to `Fabric`: `stretch_k: float = 0.0`, the in-plane stiffness along the grain in N/m. 0 means derive it: `k = K_PER_COMPLIANCE / stretch_compliance` with `K_PER_COMPLIANCE = 3e-5`.
  - Results: jersey ≈ 300, poplin ≈ 1500, denim/canvas ≈ 3000, rib ≈ 50 N/m.
  - These are placeholders until Tyler's tester jig measures real values. Say so in the docstring.
- **Do not use `1/stretch_compliance` directly.** XPBD compliances like 1e-7 mean k = 10⁷ N/m, which would need about 7,000 substeps per frame. Strain limiting does the job that near-infinite stiffness does in XPBD.
- Per-piece fabrics: build a per-vertex `_vk` exactly like `_vstretch` (from `meta["panel_fabrics"]`). Average it at the weld with the same `bincount` pattern.
- `fused()`: stiffnesses of bonded layers add, so `stretch_k = k(base) + k(interfacing)`.
- `load_user_fabrics` uses `Fabric(**v)`, so a defaulted new field stays backward compatible. Calibration (`calibrate.py`) should later fit `stretch_k` too; that's out of scope now, but leave a TODO.
- Per edge: `k_e = mean(_vk[i], _vk[j]) / _aniso()[e]`. `_aniso()` returns a compliance multiplier, so divide by it.

## 3. Dynamic substeps: the stability limit

Symplectic (semi-implicit) Euler is stable when `h · ω_max < 2`, where `ω_max²` is the largest eigenvalue of `M⁻¹K`.

**One mass on one spring** gives `ω = √(k/m)`, so `h < 2√(m/k)`. In a mesh, each particle feels all its springs, so use the **Gershgorin bound**:

```
row[i]  = Σ over springs touching i of 2·k            (diag k + off-diagonal k per spring)
        + Σ over hinges touching i of k_b s² |K_q| Σ_r |K_r|
        + Σ over attaches touching i of k_a |u_q| Σ|u|,  u = (1, -b0, -b1, -b2)
ω_max²  ≤ max_i ( row[i] · w[i] )                     (w = 1/m; pinned w = 0 drop out)
h_max   = SAFETY · 2 / ω_max                          SAFETY = 0.7
```

Check: for a 1-D chain this gives `ω = 2√(k/m)`, which is exact.

**Per frame:**

```
need  = ω_max · (1/fps) / (2 · SAFETY)
nsub  = clamp(ceil(need), 1, MAX_SUBSTEPS)
if need > MAX_SUBSTEPS:                        # never explode: soften instead
    kscale = (MAX_SUBSTEPS / need)²            # ω ∝ √k, so this lands exactly on the cap
else:
    kscale = 1
h = 1 / (fps · nsub)
```

- `MAX_SUBSTEPS` is 1500 on CPU and 300 on GPU. Surface `kscale < 1` in `metrics()` as `stiffness_scale` and in the studio log as a warning ("fabric softened to stay stable").
- **Recompute `ω_max` only when its inputs change.** Cache it keyed by `(welded, sewing)`. It changes at the weld (masses merge, seams disappear) and when sewing ends (the unfold springs drop out). Choosing `nsub` from the cached ω every frame costs nothing.
- **Rescale every per-substep constant** so behaviour doesn't change with `nsub`. These were tuned at 40 substeps (`REF_SUBSTEPS = 40`):
  - `damp = 1 - (1 - fabric.damping)^(1/nsub)` (as today);
  - sewing damping floor: `1 - 0.99^(40/nsub)` instead of a flat 0.01 per substep;
  - contact damping: `1 - (1 - 0.15)^(40/nsub)`.
- Report `substeps` and `omega` in `metrics()`.

**Expected numbers** (15 mm mesh; vertex mass ≈ 0.15 kg/m² × 1.95 cm² ≈ 2.9×10⁻⁵ kg; 6 neighbours):

- Jersey: `row ≈ 12·300 = 3600` → ω ≈ 1.1×10⁴ → about 150 substeps at 60 fps.
- Poplin: about 330 substeps.

Small boundary triangles have less mass, so they set the limit. Log the worst vertex in debug mode; if it's always a sliver triangle, `mesh2d` clearance is the fix, not the solver.

## 4. Substep loop (CPU)

New module `drape/springs.py` with `SpringSimulator(Simulator)`.

1. **Refactor first.** Split `Simulator.step()` into `_prepare()` and the XPBD-specific remainder.
   - `_prepare()` covers the weld trigger, `tight`, `srest`, `gscale`, self-collision candidates, eased `erest` with the `_relax` factor, `arest`, an `unfold` flag and a `sewing` flag.
   - Both solvers call it. XPBD output must be bit-identical before and after; verify against `test_drape`.
2. `SpringSimulator.step()`:
   - `P = self._prepare()`;
   - get ω from the cache and plan `nsub`, `kscale`, `h`;
   - call jitted `_spring_substeps(...)`, which mirrors `_substeps`' signature for the collision arguments.
3. Each substep:
   1. **Forces:** read `x`, add `h · w · kscale · f` into `v` for springs, bends, seams, unfold and attach. Serial scatter is fine on CPU, because forces read only `x`.
   2. **Gravity and drift:** `v.y += g·h` (for `w > 0`), `xprev = x`, `x += h·v`.
   3. **Strain limit:** `LIMIT_ITERS = 2` Gauss–Seidel passes, clamping only edges past the lock. Separate function `_strain_limit`.
   4. **Self-collision and body collision:** existing functions.
   5. **Velocity:** `v = (x - xprev)/h · (1 - damp)` plus the existing `MAX_SPEED` clamp.
4. Override `weld()` to call `super().weld()`, then average `_vk` with `new_id = self.vmap` (assert vmap was the identity before the weld), and clear the ω cache.

## 5. GPU (live mode)

**Don't port the colour-batch scatter.** At about 150–300 substeps × about 40 colour batches, that is about 10k dispatches per frame, which is too slow. Use a **per-vertex gather** instead: each vertex sums the forces of everything touching it. That is race-free, needs one dispatch, and computes each spring twice, which is cheap.

**Python side** (`live_setup(..., solver="xpbd"|"springs")`):

- **`adj: u32[]`**, one packed buffer with a header at `[0..10]` holding the section bases.
  - Spring CSR: `soff[n+1]`, then entries `j | kind<<30`, where kind is 0 = edge (eased rest), 1 = seam (rest × `seamScale`), 2 = unfold (only while sewing).
  - Hinge incidences: `hoff[n+1]`, entries `hinge<<2 | q`, then `hidx[4·nh]`.
  - Attach incidences: `aoff[n+1]`, entries `att<<2 | slot`, then `aidx[4·na]`.
- **`par: f32[]`**, one packed buffer.
  - Per spring entry (vec4): `rest, start, k, lock`.
  - Per hinge (8 floats): `K0..K3, s, k_b`.
  - Per attach (8 floats): `b0, b1, b2, rest, k_a`.
- **`params`** gains `solver`, `omega_sew`, `omega_run` (live never welds, so seams stay springs in both), `safety`, `max_substeps`, `limit_iters`.

**WGSL** (new kernels in `live.js`, own bind group 1 = `adj`, `par`, `D`):

- **Buffer limit:** group 0 keeps X, P, V, W, SDF, so the total is **8 storage buffers, which is WebGPU's default limit**. Don't add a ninth; pack more into `adj`/`par` instead.
- `forces` (per vertex): loop the springs, hinges and attaches; `V[i] += h · W[i] · kscale · f`. One dispatch.
- Then the existing `predict` (gravity, `P = X`, `X += hV`, mouse grab).
- `limit` + `applyD`: Jacobi strain limit. Gather the clamp corrections from violated kind-0 springs into `D`, averaged by count. Then `X += D`, so that no kernel reads X while another writes it. That's 2 dispatches × `limit_iters`.
- Then the existing `selfcol` (every `selfEvery`), `collide` and `velocity`.
- About 7 dispatches per substep: roughly 2,100 per frame at 300 substeps, all in one compute pass.

**Uniform:**

- Extend `Frame` with `ks: vec4f` (`kscale`, `unfoldOn`, 0, 0) at offset 112, so the buffer becomes 128 bytes.
- `SELF_WGSL`'s shorter struct can bind the larger buffer as-is.

**JS `_frame()`:**

- Pick `omega_sew` or `omega_run` and compute `nsub`/`kscale` with the same formula as section 3.
- Set `this.substeps` and `this.h`, and rescale the damping as in section 3.
- The substep loop length becomes dynamic.
- Show `substeps` and a softened warning in the live HUD.

## 6. Switch and UI

- **Server:**
  - `/api/drape` and `/api/live` accept `solver` (default `"xpbd"`).
  - `server.py` line ~453 and `live.py` choose the class.
  - `run_demo.py --solver`.
- **Studio:** a small select next to Quality: "Solver: Standard (XPBD) / Springs (beta)". Keep it in `ST.solver` and send it in `garmentReq`-adjacent calls in `05_preview.js`.
- **Docs:**
  - Add a `CLAUDE.md` section explaining the stability rule and the "no XPBD code paths in springs.py" rule.
  - Add `THIRD_PARTY_NOTICES.md` citations: Provot 1995 ("Deformation constraints in a mass-spring model…") and Bergou 2006 (bending).

## 7. Tests (`tests/test_v17.py`)

1. **Bound is right:**
   - A 1-D chain of N masses: Gershgorin ω equals `2√(k/m)` within 1%.
   - Measured blow-up: run a free square sheet at `h = 1.05 · 2/ω_true` and it diverges; at the planned `h` it stays finite for 600 frames.
2. **Never explodes:** a poplin sheet with `MAX_SUBSTEPS = 20` forced. `kscale < 1`, `finite`, max speed ≤ `MAX_SPEED`.
3. **Dynamic replan:** `nsub` changes at the weld, and the ω cache is invalidated.
4. **Energy:** a hanging sheet settles, with kinetic energy < 20 µJ by 3 s.
5. **Fit parity with XPBD** (slow), same garment, avatar and fabric:
   - tee on male M: `penetrating_verts == 0`, `seam_gap_max_mm < 0.01`, `strain_p99_pct < 6`, the same bars as `test_drafted_tee_drapes_on_its_avatar`;
   - knit gloves: thumb p95 < 25%, overall p95 < 15%, the same as `test_gloves_fit`.
6. **Refactor safety:** an XPBD run before and after the `_prepare` split gives identical `x` (hash compare).
7. **Browser (Playwright):** live mode with `solver=springs` runs 120 frames with finite positions, and the HUD shows the substep count.

## 8. Benchmark to report back to Tyler

Add `tools/bench_solvers.py`. Run each of these through both solvers:

- tee: jersey and poplin;
- A-line skirt: poplin;
- knit gloves.

Print one table:

| garment / fabric | solver | substeps/frame | kscale | wall s per sim s | strain p95 / p99 % | max penetration mm | seam gap mm | settle time s (KE < 20 µJ) |
|---|---|---|---|---|---|---|---|---|

Also save side-by-side renders to `out/bench/`.

**Decision rule to state in the report:** springs are "good enough" if fit metrics are within the XPBD test bars and speed is within 4× of XPBD on CPU. If they're slower than that, likely fixes are:

- coarser live mesh;
- `SAFETY` 0.8;
- skipping self-collision on alternate substeps;
- later, an implicit (backward Euler) step for stiff wovens. Baraff–Witkin 1998.

## 9. Don'ts

- Don't edit XPBD's numerics or defaults.
- Don't reuse `_solve_edges`, `_solve_dist`, `_solve_hinges` or `_solve_attach` in the spring path.
- Don't stiffen springs past the lock strain; clamp instead, or the bound is wrong.
- Don't exceed 8 storage buffers per shader stage.
- Don't commit generated `out/` files.
