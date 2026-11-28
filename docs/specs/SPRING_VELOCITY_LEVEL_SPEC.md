# Spec: velocity-level contacts and strain limiting for the springs solver (+ retire XPBD)

**For:** Claude Code, working in the drape repo, after the springs solver from `SPRING_SOLVER_SPEC.md` exists.
**Supersedes:** in `SPRING_SOLVER_SPEC.md`,
- the "Strain limiting" paragraph of section 1;
- substep steps 3–5 of section 4;
- the `predict` / `limit` / `applyD` / `velocity` order of section 5.

Everything else in that spec still holds: forces, stiffness, the Gershgorin stability bound, dynamic substeps, the ω cache, the UI switch and the benchmark.

---

## 0. Why (keep this section in the file)

Position-based methods follow a loop:
1. **estimate** each vertex's next position from position + velocity;
2. **update that estimate** to satisfy constraints;
3. then **compute the next position and velocity** from the current and the corrected estimate.

The first springs spec had that pattern in it:
- `x += h·v`, then position-clamp over-stretched edges and push points out of collisions;
- then `v = (x - xprev)/h`.

drape's solver is designed not to work that way.

**Fix:** move everything except the final `x += h·v` to **velocity level**, the approach of Bridson, Fedkiw and Anderson (SIGGRAPH 2002), plus Provot (1995) for the strain-limit idea.
- Constraints and contacts change **velocities** with impulses.
- Positions change **only** by `x += h·v`.
- **No velocity is ever computed from a position difference.**

It's simpler to reason about, and better against tunnelling.

**Hard rules for the springs path (CPU and GPU):**
1. Positions change only by `x += h·v`, plus the deep-penetration safety net (section 2.6), which never feeds back into velocity.
2. No code computes `(x_new − x_old)/h`, `(X − P)/h` or any equivalent to set a velocity.
3. Predicted positions `p* = x + h·v` may be computed as **read-only temporaries** for tests (lengths, distances). They are never stored back, corrected or used to derive velocity.
4. Keep the springs path free of any XPBD code. That still applies.

Keep this file public and dated.

---

## 1. New substep order (CPU, `_spring_substeps`)

```
for each substep:
  1. forces      v += h · w · kscale · f(x)            (springs, bends, seams, unfold, attach — unchanged)
  2. gravity     v.y += g · h                          (w > 0)
  3. strain      velocity impulses on over-stretched edges          (2.1)   × LIMIT_ITERS
  4. body        velocity impulses for contact + Coulomb friction   (2.2)
  5. self        velocity impulses for cloth-cloth contacts         (2.3)   (every self_every substeps)
  6. damping     v *= (1 − damp);  contact damping on touched verts; MAX_SPEED / v_clamp
  7. advance     x += h · v                            ← the only position update
  8. safety net  deep-penetration fix                               (2.6)
```

`xprev` is kept **only** as the start-of-substep snapshot for self-collision side memory. It's never used to compute velocity.

## 2. The pieces

### 2.1 Strain limiting with velocity impulses (Provot's limit, applied as Bridson-style impulses)

For each edge (i, j) with eased rest length `r` and lock `λ`:
```
L_max = (1 + λ) · r
d*    = (x_i + h v_i) − (x_j + h v_j)        # predicted, read-only
L*    = |d*|
if L* > L_max:
    n   = d* / L*
    Δ   = (L* − L_max) / h                    # relative speed to remove along n
    v_i −= (w_i / (w_i + w_j)) · Δ · n
    v_j += (w_j / (w_i + w_j)) · Δ · n
```
- **CPU:** Gauss–Seidel over edges, `LIMIT_ITERS = 2` (raise to 4 if the strain test fails).
- **Seams while sewing:** no strain limit (they're springs pulling in). After the weld they're ordinary edges.
- This only ever **removes** stretching velocity, so it can't add energy. Assert that in debug builds: the kinetic energy after step 3 is ≤ before, within float tolerance.

### 2.2 Body collision and friction with velocity impulses

Per vertex with `w > 0`:
```
p*  = x + h v                                 # read-only
d*  = sdf(p*)   (posed: same bone-frame lookup as _collide_posed, with end-of-substep transforms)
if d* < thick:
    n    = ∇sdf(p*) (normalized; posed: rotated to world)
    Δvn  = (thick − d*) / h                   # normal speed needed to end at the contact surface
    v   += Δvn · n
    vt   = v − (v·n) n
    |vt| ← max(0, |vt| − μ · Δvn)             # Coulomb friction, impulse-limited
```
- **Moving bodies:** this works unchanged, because `sdf` at `p*` uses the body where it will be at the end of the substep. A limb moving into the cloth raises `Δvn`.
- **Reuse:** reuse the distance/gradient helpers (`grid_sdf`, `grid_sdf_grad`, `_label_at`, the posed bone loop), not `_collide`/`_collide_posed` themselves. Those write positions.

### 2.3 Self-collision with velocity impulses

On the per-frame candidate pairs (vertex v, triangle abc), with the side taken from the start-of-frame snapshot as now:
```
predicted points p*_v, p*_a, p*_b, p*_c   (read-only)
s*  = side · ((p*_v − closest point on triangle(p*_a,p*_b,p*_c)) · n*)
if s* < self_thickness:
    Δ   = min(self_thickness − s*, 0.5 · self_thickness) / h      # same half-thickness cap as today
    distribute as an impulse along side·n* with barycentric weights (bu, bv, bw):
       v_v += w_v · Δ / denom · side·n*
       v_a −= w_a · bu · Δ / denom · side·n*      (same for b, c)
       denom = w_v + bu²w_a + bv²w_b + bw²w_c
    mark touched (contact damping)
```
This is Bridson et al. 2002's repulsion impulse. It also helps the speed-substeps work: tests run on **predicted** positions, so a fast point is stopped **before** it crosses, not found afterwards.

### 2.4 Topstitch attach

It's already a one-sided force spring in the springs spec. No change.

### 2.5 Damping, speed caps

Unchanged, but applied to `v` directly (step 6). `MAX_SPEED` and the speed-substeps `v_clamp` (from `SPEED_SUBSTEPS_SPEC.md`) clamp `v` here.

### 2.6 Deep-penetration safety net (rare)

After `x += h·v`, any vertex more than `DEEP_PEN = 2 mm` inside the body (grid error, a bone popping through) is fixed like this:
1. Its **position** is moved out to `thick` along `n`.
2. Its velocity gets **only** its inward normal component zeroed: `v −= min(0, v·n)·n`.
3. **No velocity is computed from the move.**

Count these per frame in metrics as `safety_pushes`. In a healthy drape it should be 0. Make it a test bar.

## 3. GPU (live mode)

Same order, as per-vertex kernels. Most of these replace the springs-path use of `predict` / `limit` / `applyD` / `collide` / `velocity`.

| kernel | what it does | writes |
|---|---|---|
| `snapshot` | `P = X` (side memory only) | P |
| `forces` | as before, plus gravity | V |
| `vlimit` (× iters) | gather Δv from violated kind-0 springs (Jacobi, averaged by violated-count) | D |
| `applyDV` (× iters) | `V += D` | V |
| `vcollide` | section 2.2 per vertex | V |
| `vselfcol` (every `selfEvery`) | gather the section 2.3 impulses per vertex into D (vertex side and triangle side via the existing hash) | D |
| `applyDV` | `V += D` | V |
| `damp` | damping and speed clamp | V |
| `advance` | `X += h·V`; deep-pen safety net; **mouse grab** | X, V |

- **Mouse grab:** the grabbed vertex is kinematic (`W = 0`). Set its **position** directly toward the target (rate-limited per `SPEED_SUBSTEPS_SPEC.md`) and its velocity to 0. Never derive velocity from its move.
- **Triangle-side impulses in `vselfcol`:** to stay race-free, each vertex gathers impulses from triangles near it, and gathers its own share as a triangle corner. Use the existing triangle hash, with a second pass over its incident triangles; alternatively accumulate with fixed-point `atomicAdd` into an i32 D buffer (scale 1e6 m/s). Pick whichever benchmarks faster, and note it in `CLAUDE.md`.
- **Dispatches per substep:** about 9–11. That's about 1,500–3,300 per frame at 150–300 substeps. If that's too slow, fuse `snapshot` into `forces`, and `damp` into `advance`.
- **Buffer limit:** still ≤ 8 storage buffers per stage (X, P, V, W, SDF + adj, par, D). Self-collision's T/CNT/SLOT/PART live in their own pipeline layout as today.

## 4. Phase 2: make springs the default and retire XPBD

**Do this only after** the section 6 tests and the `SPRING_SOLVER_SPEC.md` benchmark pass their bars, **and Tyler approves the benchmark table**.

1. Default `solver = "springs"` everywhere: server, live, `run_demo.py`, studio.
2. **Remove XPBD from the shipped code:**
   - `_solve_edges`, `_solve_dist`, `_solve_hinges` and `_solve_attach` (and their callers), plus `_substeps`;
   - XPBD's WGSL `dist`/`hinge`/`attach` kernels and their colour batches;
   - `Simulator`'s XPBD-only state (`elam`, `blam`, `slam`, compliance/h² math);
   - the UI solver select.

   Keep `_prepare()`, collisions, weld, hashing and metrics: they're shared infrastructure. Fold `SpringSimulator` into `Simulator` or keep the subclass, whichever leaves less code.
3. **Fabric presets:** compliances are no longer used for stretch. Keep `bend_compliance` (it's springs' `k_b = 1/bend_compliance`). Keep `stretch_compliance` only as the fallback that derives `stretch_k`; rename the field's docstring to say so. Don't break `~/.drape/fabrics.json` loading.
4. **Tests:** every test that constructed the XPBD `Simulator` now runs springs, with the **same bars**. If a bar fails, report it to Tyler with numbers. **Don't loosen bars without his OK.**
5. **Git history:** don't rewrite history. Removing XPBD going forward is the plan; ask Tyler before any history surgery.
6. Update `CLAUDE.md`, `THIRD_PARTY_NOTICES.md` (cite Bridson, Fedkiw & Anderson 2002; Provot 1995; Bergou 2006) and the README solver description.

## 5. Constants

At the top of `springs.py` (mirror them in `live.js`):

`LIMIT_ITERS = 2`, `DEEP_PEN = 0.002`, plus the existing `SAFETY`, `MAX_SUBSTEPS`, `SEAM_K`, `REF_SUBSTEPS`.

## 6. Tests (`tests/test_v19_velocity.py`, plus browser)

1. **Positions follow velocities (the design-around guard).** Run a tee drape for 2 s. On every substep (debug hook), for every vertex **not** in that substep's `safety_pushes` set, `x_new == x_old + h·v_new` within 1e-12 (CPU float64).
   - **GPU:** the same check on a debug readback of 1 substep, within 1e-6 (float32).
   - This is the test that proves velocity is never derived from positions.
2. **Static guard:** the source of `_spring_substeps` and the springs WGSL kernels contains no expression that divides a position difference by `h`. Grep for `xprev` used in arithmetic with `/ h`, and for `(X` … `- P` … `/ F.h` patterns. Comment why the test exists (section 0).
3. **Strain still locks:** a 30 × 30 cm poplin strip (lock 4%) hanging with a 50 g point load settles with max strain ≤ 4.5%.
4. **Contacts hold:**
   - tee on male M: `penetrating_verts == 0` and `safety_pushes == 0` over the last second;
   - knit gloves: `safety_pushes` ≤ 5 total;
   - the sheet-fling tunnelling test from `SPEED_SUBSTEPS_SPEC.md`: 0 crossings.
5. **Friction works:** a jersey sleeve rests on a 30°-tilted arm segment without sliding more than 5 mm in 1 s at μ = 0.4, and slides at μ = 0.05.
6. **Energy:** the impulse steps never increase kinetic energy (debug assert from section 2.1). A hanging sheet settles below 20 µJ by 3 s.
7. **Fit parity:** the same bars as `SPRING_SOLVER_SPEC.md` section 7, test 5 (tee and gloves).
8. **Browser:** live springs mode, 300 frames, with a scripted 40 cm grab-yank. Positions stay finite, 0 crossings at the end, and the HUD shows `safety_pushes` = 0 (show it in the HUD in debug mode only).

## 7. Report back to Tyler

- Before/after benchmark rows for the springs solver (position-level vs velocity-level): speed, strain p95/p99, penetration, settle time, `safety_pushes`.
- Screenshots of the tee and the hoodie.
- Whether it still "feels like it has weight". He liked that; impulse contacts shouldn't change it, but confirm by running the pendulum-period check: a 50 cm strip swinging from 20°, period about 1.2 s, within 10%.

## 8. Don'ts

- Don't add any velocity computed from a position change in the springs path, for any reason, including "just for the grab" or "just for stability".
- Don't store or correct predicted positions.
- Don't remove XPBD before Tyler approves the benchmark.
- Don't loosen test bars without approval.
- Don't exceed 8 storage buffers per shader stage.

---

## 9. Changes after measurement (2026-11-19, approved by Tyler)

Section 0 still holds for all of these: positions change only by `x += h·v` (plus the
section 2.6 safety net), no velocity is computed from a position difference, and
predicted positions stay read-only temporaries. The debug check (test 1) and the
static guard (test 2) pass unchanged.

1. **Integration is implicit (backward Euler), not explicit.** Steps 1–2 solve
   `(M + h²K) Δv = h (F + M g − h K v)` once per substep by Jacobi-preconditioned
   conjugate gradients (Baraff and Witkin 1998), with `K = −∂F/∂x` and the compressed-spring
   term dropped so it stays positive semi-definite. The solve only produces a velocity change.
   - Base count: `IMPLICIT_SUBSTEPS = 40` per frame (the speed plan can raise it).
   - The explicit path stays behind `implicit=False`, for comparison.
   - **Why:** explicit springs needed 200–700 substeps per frame and still failed the
     gloves thumb bar (thumb strain p95 39–59% vs the 25% bar, under every contact variant
     tried; friction was ruled out). Implicit springs pass it at 6.0% (XPBD: 4.5%).
2. **Cloth on cloth (2.3): an overlapping pair is eased apart over `SELF_TAU = 5 ms`.**
   Pairs that are approaching still get exactly the 2.3 formula.
   - **Why:** the 2.3 formula gives an already-overlapping pair a separating speed of
     overlap/h. Nothing removes it, so layers kept bouncing on each other. The tee on the
     capsule body never settled: KE 4,924 µJ at 3.5 s, against the 20 µJ bar.
3. **Speed cap (2.5): a point the body pushed this substep keeps its outward push.**
   Only its sliding part is trimmed to the cap.
   - **Why:** scaling the whole velocity cut the body's push. With implicit-sized
     substeps, points crossing the curved fingers at the cap in frame 1 ended up deep in
     the hand (56 safety pushes).
   - Applying the cap *before* the contacts instead was measured and is worse: some
     gloves edges stretched to 10× their length.
4. **2.1 strain limit: the energy rule wins over the formula.** The impulse is capped at
   the edge's own stretching speed: `Δ = min((L* − L_max)/h, u)`, and nothing is done if
   `u ≤ 0`. The section's two statements can't both hold, because pulling a stationary
   over-lock edge back adds energy. Applying the formula as written was measured and is
   worse on the gloves: whole-glove p95 22%, 12 safety pushes.
5. **Measured and rejected:**
   - easing *body* overlaps out over τ (5 ms lets fingers into the glove; 4 and 16
     substeps were inconsistent);
   - running cloth-on-cloth before the body (no change);
   - 10× stiffer jersey springs (blew up while sewing).

The method list is in `docs/ALGORITHMS.md`.
