# Spec: speed-based substeps (stop fast cloth tunnelling through itself)

**For:** Claude Code, working in the drape repo (v1.4.1).

**Problem:** a violent mouse move in live mode leaves the cloth knotted/bunched (seen at a shirt hem). The cause is geometric:

| | live (GPU) today | full drape (CPU) today |
|---|---|---|
| substeps per frame | 24 | 40 (quick: 24) |
| self-collision every | 2nd substep (`selfEvery = 2`) | every substep |
| cloth speed cap | none in `velocity` kernel | `MAX_SPEED` = 3 m/s |
| self-contact thickness | 3 mm (`self_thickness`) | 3 mm |

Two cloth layers moving toward each other close at up to **2 × v**. At 3 m/s in live mode, that is 2 × 3 m/s ÷ 60 ÷ 24 × 2 ≈ **8.3 mm** of closing between checks, against a 3 mm contact layer. A point jumps clean past the triangle. Then `selfcol` decides "the side it was on at the start of the substep" (the wrong side), and holds the crossing in place. That's the knot.

**Fix (this spec only):** choose the substep count every frame so that no two layers can close more than half the contact thickness between self-collision checks. Then cap what can't be covered. Nothing else changes: no new collision types and no untangling.

---

## 1. The rule

```
closing per check  = 2 · v_max · (1/fps) / nsub · self_every
require            closing per check ≤ SPEED_SAFETY · self_thickness      (SPEED_SAFETY = 0.5)

nsub_speed = ceil( 2 · v_max · self_every / (fps · SPEED_SAFETY · self_thickness) )
nsub       = clamp( max(nsub_base, nsub_speed), nsub_base, nsub_cap )
```

- `nsub_base` is today's count (24 live, 40/24 CPU), or the stability count once the spring solver from `SPRING_SOLVER_SPEC.md` exists. **Slow frames must use exactly `nsub_base`**, so results for calm scenes don't change.
- **`self_every` switch:** when `nsub_speed > nsub_base`, set `self_every = 1` for that frame before computing `nsub_speed`. Halving the checks while doubling the substeps never pays off.
- **Caps:** `nsub_cap` = 96 live, 160 CPU. Constants go at the top of `solver.py` and `live.js`.
- **When the cap is hit, slow the cloth instead of letting it tunnel.** Lower the velocity clamp for that frame so the rule holds at the cap:

  ```
  v_clamp = nsub_cap · fps · SPEED_SAFETY · self_thickness / (2 · self_every)
  ```

  At live settings that is about 2.2 m/s, so motion slows slightly during a violent yank. The cloth can no longer tunnel. Record it in metrics/HUD as `speed_limited: true`.
- **Hysteresis:** `nsub` may rise immediately, but may fall by at most 25% per frame. Without it, the count oscillates as the cloth slows and the substep budget relaxes.
- **Worked numbers** (3 mm, safety 0.5, 60 fps, `self_every` 1):

  | v_max | nsub_speed | live result |
  |---|---|---|
  | 0.3 m/s | 7 | 24 (base) |
  | 1 m/s | 23 | 24 (base) |
  | 2 m/s | 45 | 45 |
  | 3 m/s | 67 | 67 |
  | 5 m/s | 112 | 96, clamped to 2.2 m/s |

## 2. Where `v_max` comes from

**CPU (`Simulator`):** exact. In `step()`, before the substeps, take `v_max = sqrt(max(sum(v², 1)))` over vertices with `w > 0`.

- Use the max, not the p99 the hash margin uses. The few fast points are exactly the ones that tunnel.
- Add 25% headroom (`v_max · 1.25`), because velocity can grow within the frame (gravity, a seam snapping in).
- Pass the per-frame `v_clamp` into `_substeps` in place of the constant `self.max_speed`, as `min(MAX_SPEED, v_clamp)`.

**GPU (`LiveSim`):** read back without stalling.

- In the `velocity` kernel, `atomicMax` the speed into a 1-element `atomic<u32>` buffer `VMAX`. Bit-cast the f32: positive floats order the same as their u32 bits.
- Clear `VMAX` at the start of each `step()` call, copy it into the existing `staging` readback after the last frame (extend `staging` by 16 bytes), and read it along with positions. **Don't add a separate `mapAsync`.**
- The value is therefore one `step()` call late. Use it as:

  ```
  v_est = max(1.25 · v_measured_last, v_grab)
  ```

  where `v_grab` is how fast the grab target moved since the last call: |target − previous target| ÷ elapsed time. The CPU knows it immediately, so a sudden yank raises substeps on that same frame, without waiting for the readback.
- **Binding limit:** the `velocity` pipeline lives in `LIVE_WGSL` group 0, which already has 5 storage buffers. `VMAX` makes 6 there, and the total per stage must stay ≤ 8. If the group-1 spring buffers from the other spec are present, that is exactly 8. **Check it, and if it's over, fold `VMAX` into an existing buffer** (for example a spare word at the end of `P`) instead of adding a binding.
- **Velocity clamp on GPU:** today's `velocity` kernel has no speed cap. Add one. Put `v_clamp` in the `Frame` uniform (use the spare `_q` slot or the new `ks` vec4 from the spring spec; keep the layouts identical between `LIVE_WGSL` and `SELF_WGSL`, or keep `SELF_WGSL` a prefix of it). Also set `MAX_SPEED` 3 m/s as the ceiling, matching the CPU.

## 3. The mouse grab must not speed up with more substeps

**Hidden bug this change would expose:** `predict` moves the grabbed point by `mix(p, target, grabK)` with `grabK = 0.08` **per substep**. More substeps per frame means the grab moves faster, which raises `v_max`, which adds more substeps: a feedback loop.

- Make the grab rate per frame, matched to today's feel at 24 substeps: `grabK_sub = 1 - (1 - 0.08)^(24 / nsub)`.
- Cap the grabbed point's speed: per substep, move at most `GRAB_MAX_SPEED · h` toward the target (`GRAB_MAX_SPEED = 2.0` m/s). Do it in `predict` with a `min(length, max_step)` on the displacement.

## 4. Per-substep constants must be rescaled

`nsub` now varies frame to frame, so anything tuned "per substep" must be expressed per frame and converted:

- `damp = 1 - (1 - damping)^(1/nsub)`: already per frame on both sides; keep it.
- Sewing damping floor (CPU `max(damp, 0.01)`, GPU same): change to `1 - 0.99^(nsub_base / nsub)`.
- CPU `contact_damp` 0.15 per substep: change to `1 - 0.85^(nsub_base / nsub)`.
- `h` must be recomputed from the frame's `nsub` and written into the uniform each frame (`this.h` in `_frame()`).
- XPBD compliances are divided by `h²` inside `step()` already, so they follow automatically. Confirm nothing caches `self.h` from `__init__`.

## 5. Visibility

- **CPU:** add `metrics()` keys `substeps` (last frame), `substeps_max` (over the run), `v_max_mm_s`, `speed_limited`.
- **Live HUD:** show the substep count and turn it amber when above base. Show "slowed to stay untangled" while `speed_limited`.
- Add a `CLAUDE.md` note under gotchas: "substeps are dynamic; never assume `sim.nsub`/`this.substeps` is constant."

## 6. Tests (`tests/test_v17_speed.py`, plus one browser test)

1. **Planner unit test:** the worked-numbers table in section 1 reproduces exactly, including the cap and `v_clamp` at 5 m/s.
2. **Calm scenes are unchanged:** the tee drape from `test_drafted_tee_drapes_on_its_avatar` gives identical `x` (exact array compare) before and after. Its speeds stay under the base budget. If it doesn't match, the rule is firing when it shouldn't.
3. **Tunnelling regression:** two parallel 20×20 cm sheets 1 cm apart, no body, gravity off, top sheet given 3 m/s toward the bottom one.
   - With the old fixed settings (24 substeps, `self_every = 2`), assert that edge–triangle crossings appear (segment-vs-triangle test over all pairs; write the helper in the test). This proves the test can catch it.
   - With the new planner, assert crossings are 0 after 30 frames.
4. **Hysteresis:** feed the planner a speed spike then calm. `nsub` jumps up on frame 1 and decays by ≤25% per frame.
5. **Grab is substep-independent:** with the grab target fixed 10 cm away, the grabbed point's position after 10 frames matches within 1 mm at `nsub = 24` vs `nsub = 96`.
6. **Browser (Playwright):** start live on a tee, script a grab that yanks 40 cm in 2 frames, run 120 frames.
   - Positions stay finite.
   - The HUD showed substeps > 24 during the yank and back to 24 within about 1 s after.
   - A `window.LiveSim` debug hook reports zero edge–triangle crossings in the final positions. Do the check on the JS side over the downloaded positions; it's fine if it's slow, since this is a test only.

## 7. Don'ts

- Don't change behaviour for slow scenes. Test 2 is the guard.
- Don't add a second GPU readback/map per frame.
- Don't exceed 8 storage buffers per shader stage.
- Don't add untangling or edge–edge collision in this change. They're separate work if this isn't enough.

## 8. Report back to Tyler

Re-create the violent-move case on a tee in live mode, before and after, and send screenshots of the hem. Report:

- the substep peak during the yank;
- how long the frame rate dipped;
- whether `speed_limited` triggered.

If knots still form with zero tunnelling, the remaining cause is pre-weld sewing (pieces of one garment don't collide with each other while sewing). That's the next fix to try.
