# Spec: staged sewing (attach hoods, collars, cuffs and pockets after the body settles)

**For:** Claude Code, working in the drape repo (v1.4.x, with or without the springs solver).
**Version 2:** revised with design rules. **Section 0 overrides anything else in this file.**

---

## 0. Design rules (do not violate)

drape's staged sewing works like this:

1. **Never choose a piece's stage from the seams.** Stages come only from:
   - (a) where the piece sits on the body (its placement region);
   - (b) its role tag (hood, collar, cuff, pocket…);
   - (c) the user's own choice.

   No code may read the seam list, the seam graph, connectivity or "which pieces are sewn to which" to decide a stage. **Test 2b enforces this.**
2. **Arrange every piece exactly once, at the start, before any simulation.** Stages never re-place, re-wrap or re-arrange pieces. A pending piece stays frozen where it was placed and simply wakes up later.
3. **Stages are a construction (sewing) order in time, not an arrangement procedure.** Name things accordingly: `sew_order`, `stage`, "Sewing order" in the UI. Never "arrange", "iteration", "process patterns".
4. **There is no fallback that infers stages.** A piece with no placement region and no role tag goes to stage 1. Never fall back to analysing connectivity.
5. **Keep this file in the public repo with its commit date.** It serves as a dated defensive publication of drape's method.

Section 0 rules are **non-negotiable**. If a requirement elsewhere conflicts with them, section 0 wins: stop and flag it to Tyler instead of working around it.

**Problem (Tyler, hoodie test):**
- Adding a hood to a tee drags the whole shirt up while the seams pull in.
- The armholes end up off-centre on the arms, the hem rises, and the fit map lies.
- With a hood, a drape showed 565% max stretch, 27% p99 stretch and a point 6.4 mm inside the body, and the panel still said "fits fine".

**Root cause:**
- **Every seam pulls in at once.** All seams close over `sew_time` (0.8 s) with gravity off, and each seam correction is split by inverse mass. A hood and a shirt weigh about the same, so they **meet halfway**.
- **The hood starts far away.** It begins about 10–15 cm above the neckline, so the neckline is dragged up about 5–7 cm.
- **Nothing holds the shirt yet.** It isn't resting on the shoulders, so it rides up with the neckline.
- **The weld locks it in.** The weld happens at `sew_time`, and the hood catching on the head keeps it there.

**Fix:** sew in stages, like a person does.
1. Close the body garment (shoulders, sides, sleeves) and let it settle on the body with gravity on.
2. Then sew the attachments onto it. Already-settled pieces act heavy, so the attachment travels to them, not the other way round.

---

## 1. Data model

- **Each piece gets a stage, stored on the design:** `piece.stage`, an int from 1 to 3 or absent.
  - Absent means automatic (section 2).
  - Old design files have no stages, so they load as auto. No migration is needed.
- **Each piece also gets a role tag:** `piece.role`, one of `body`, `sleeve`, `hood`, `collar`, `cuff`, `waistband`, `pocket`, `other`, or absent.
  - Starters set it.
  - Users can set it in the piece inspector.
  - Freeform splits and copies inherit it.
- **A seam sews in the later of its two pieces' stages:** `seam_stage = max(stage[a], stage[b])`.
  - This is timing derived from piece stages. It is not stage selection from seams, so it's allowed under section 0.
  - Store it per seam in `Garment.meta["seam_stage"]`.
- **Design JSON:** bump the design format version if one exists. If none exists, add `"format": 2` now; it's needed for the alpha-warning work anyway.

## 2. Automatic stage assignment (placement and role only)

Run it in `freeform.build_design` (and wherever the starters build garments), so `Garment.meta["piece_stage"]` holds one int per piece. **Inputs are only each piece's placement region and role tag** (section 0, rule 1).

| Role tag | Placement region | Auto stage |
|---|---|---|
| `body`, `sleeve` | torso, legs, arms | **1** |
| `hood` | head | **2** |
| `collar` | neck | **2** |
| `cuff`, gloves on a garment | wrists, hands | **2** |
| `waistband` | waist band | **2** |
| `pocket` | on a garment surface | **3** |
| `other` / untagged | any | region rule above; **1** if no region (no inference) |

- **The role tag wins over the region when both are set.**
- **Placement regions** come from the existing placement keys (`pc.place.*` in the studio JS, `placement` in freeform).
- **A garment that's all one region** (gloves alone, a plain tee) gets all stage 1 and **behaves exactly like today**.
- **Starters must tag their pieces.** Go through `starters.py`, `garments.py` and `gloves.py`: every piece gets a role tag. Gloves sold as their own garment are `body` on the hands, so stage 1.
- **Separate garments** (top + skirt) are not stages: they sew in parallel within each stage as they do now.

## 3. Timeline (shared by XPBD and springs)

Implement the timeline once, in the shared frame preparation (`Simulator._prepare()` if the springs refactor exists; otherwise create it), so both solvers get it.

For each stage `k = 1..K`:

| phase | duration | what happens |
|---|---|---|
| sew_k | `sew_time` (0.8 s) for k = 1; `SEW2_TIME` = 0.6 s for k > 1 | stage-k seams shrink to 0 rest length, eased as today |
| weld_k | instant | weld **only stage-k seams** (partial weld, section 4) |
| settle_k | `gravity_ramp` (0.3 s) + `SETTLE_TIME` = 0.5 s for k < K; for k = K the user's remaining "seconds to simulate" | gravity ramps in at stage 1; it stays on afterwards |

- **Gravity is off only during sew_1, as today.** For k > 1, gravity stays **on**: the anchor is resting on the body, and gravity helps the attachment fall toward its seam.
- **No re-arrangement (section 0, rule 2).** All pieces are placed once, before frame 0. Nothing in this timeline moves a piece except physics after it wakes.
- **Pending pieces** (stage > current) are **frozen**:
  - inverse mass `w = 0`;
  - no gravity;
  - excluded from self-collision candidates (both as vertex and as triangle);
  - still drawn, but shown faded in the studio preview.
  - They wake (`w` restored from mass) when their stage's sew phase begins, with zero velocity.
- **Anchor weighting during sew_k, for k > 1:** for stage-k seams only, vertices on pieces from earlier stages use `w · ANCHOR_W` with `ANCHOR_W = 0.05`.
  - Effect: the attachment does about 95% of the moving, so the neckline moves under 1 cm instead of about 7.
  - **XPBD:** pass a separate `w_seam` array to `_solve_dist` for the seam call only. Stretch, bending and collision keep the real `w`.
  - **Springs:** scale the seam force applied to anchor-side vertices by `ANCHOR_W`. Newton's third law is deliberately broken here, and only for unwelded seams while sewing. Comment it so.
- **Total extra simulated time:** about 1.4 s per extra stage (0.6 + 0.3 + 0.5). Show the timeline in the progress text: "Sewing body · Settling · Attaching hood · Draping".
- **Move tests (`pose`)** start only after the last weld. Untangling (`_untangle_step`) stays off until then too, since pending pieces aren't on the body yet.
- **Constants** go at the top of `solver.py`: `SEW2_TIME`, `SETTLE_TIME`, `ANCHOR_W`.

## 4. Partial weld

Refactor `Simulator.weld()` to `weld(mask=None)`, where `mask` selects which seams to merge. `None` means all, today's behaviour.

- Union-find only over `seams[mask]`. Everything downstream is unchanged: mass, x/v averaging, tris, edges, rest lengths, bends, hinges, per-vertex fabric arrays, `_att`, `vmap`.
- **Remaining seams** survive, remapped: `seams = new_id[seams[~mask]]`, with `seam_rest0` and `seam_stage` filtered the same way.
  - Drop any remaining seam whose two ends now map to the same vertex.
  - This happens where a stage-2 seam ends on a stage-1 seam vertex. Treat it as already sewn.
- **`self.welded` becomes "all seams welded".** Add `self.weld_stage`, the last stage welded.
  - Every place that checks `self.welded` to gate self-collision must allow it after a partial weld. Exclude only pairs within 2 edge-rings of a still-unwelded seam vertex.
  - Reuse the `_seamv`/`layer_pairs` exclusion idea, rebuilt after each weld.
- Edge-rest easing (`_erest_start`) applies per stage. Recompute it at the start of each sew phase for the newly woken pieces' edges only.
- **Fit metrics** (`metrics()`, `seam_gap_max_mm`) still use `g0` and `vmap`, and must work after each partial weld.
- **Springs solver:** its ω cache key becomes `(weld_stage, sewing_stage)` instead of `(welded, sewing)`.

## 5. Live mode (GPU)

Live never welds, so staging there means freezing, per-stage seam easing and anchor weighting.

- **Setup (`live_setup`):**
  - seams get a per-seam `stage` field;
  - a per-seam anchor flag: bit 0 = vertex i is on an earlier-stage piece, bit 1 = j is;
  - `params.stages` holds per-stage start times, computed from the same timeline constants;
  - send `piece_stage` per piece, so JS can freeze and wake by `panel_id`.
- **Kernel:** the `dist` kind-1 (seam) path uses `seamScale[stage]` from a `vec4f` in `Frame` (stages 1–4) instead of the single `seamScale`.
  - If the anchor bit is set, scale that side's `W` by `ANCHOR_W` for this constraint only.
  - Seam data needs 3 floats (`rest`, `stage`, `anchor`); there's room in A0–A2. **Stay within 8 storage buffers per stage.**
- **Freeze/wake:**
  - JS writes `W = 0` for pending pieces' vertices at reset.
  - When a stage starts, it writes back `Wd` for them and zeroes their `V`.
  - The grab can't pick frozen vertices.
- **Springs on GPU:** the seam force gather applies `ANCHOR_W` to anchor-side vertices in the same way.

## 6. Studio UI

- **Piece inspector** (Advanced mode only): a "Sewing order: 1 / 2 / 3 / auto" control and a "Role" select. Auto shows the computed stage greyed.
  - Changing either re-runs nothing until the next drape.
  - Store them in `piece.stage` and `piece.role`, and include both in undo/redo.
- **Seam popups:** a read-only "sews in stage N" line, since a seam's stage comes from its pieces.
- **Help text (`11_help.js`):** "Big pieces sew first and settle on the body; hoods, collars, cuffs and pockets are sewn on afterwards, the way you'd sew them. Change a piece's sewing order if it should go on earlier or later."

## 7. Tests (`tests/test_v18_stages.py`, plus one browser test)

1. **No attachments: identical to today.** A plain tee (all stage 1) gives a bit-identical `x` before and after, for both XPBD and springs if present. This guards the default path.
2. **Auto assignment:**
   - the tee + hood design (hood tagged `hood`) gives the hood stage 2 and everything else stage 1;
   - its hood-to-neck seams come out as stage 2;
   - a pocket goes to stage 3;
   - gloves alone are all stage 1;
   - a shirt with cuffs puts the cuffs in stage 2;
   - an untagged piece with no region goes to stage 1;
   - an old design file without stages or roles loads and auto-assigns.

   2b. **Design-around guard: assignment ignores seams.** For several designs:
   - shuffle the seam list, delete all seams, or add random seams between pieces;
   - `piece_stage` must stay **identical** in every case.

   Also add a static check: the assignment function's source must not reference `seams`, `seam_`, `edges` or any connectivity helper. Use a simple `inspect.getsource` grep, and comment why it exists (section 0).

   2c. **No re-arrangement:** record every piece's vertex positions at frame 0. A pending piece's positions are unchanged at the frame it wakes.
3. **Partial weld bookkeeping:**
   - after the stage-1 weld, `seams` holds only the stage-2 pairs, correctly remapped;
   - `vmap` maps every original vertex;
   - `metrics()` runs;
   - after the stage-2 weld, `welded` is True and the result matches the vertex count of an all-at-once weld.
4. **The hoodie fix (slow).** Same avatar, tee + hood vs tee alone. Both must hold:
   - the neckline (mean height of front/back neck vertices) rises **< 1.0 cm** vs tee alone (today: about 5–7 cm);
   - the armhole centroid is within **1.0 cm** of the tee-alone armhole centroid, on both sides;
   - the hem rises < 1.5 cm;
   - `penetrating_verts == 0`, `strain_max_pct < 100`.

   Use a hood big enough for the avatar's head, e.g. 22" × 16" with curved crown edges. This test is about sewing order, not hood sizing.
5. **Anchor weighting is seam-only.** During sew_2, the stage-1 pieces' stretch/bending still use real masses. Check: a stage-1 vertex's displacement during sew_2 stays small, and its stretch strain stays under its lock strain.
6. **Frozen pieces:** during stage 1, a stage-2 piece's vertices don't move (max displacement 0), and no self-collision contacts involve them.
7. **User override:**
   - setting the hood piece's sewing order to 1 reproduces today's behaviour (the neckline rises) without crashing;
   - setting a pocket to 1 works too: it just sews with the body.
8. **Browser (Playwright), live mode with tee + hood:**
   - the hood stays frozen until about 1.6 s;
   - the progress/HUD text shows the stage names;
   - positions stay finite for 300 frames;
   - the neckline rise is < 1.5 cm (looser than CPU, since live doesn't weld).

## 8. Don'ts

- Don't break any section 0 rule. If a feature seems to need it (for example "auto-detect which piece is the hood from its seams"), stop and ask Tyler.
- Don't change single-stage results. Test 1 is the guard.
- Don't add any code path that re-places or re-wraps pieces after frame 0.
- Don't apply `ANCHOR_W` to anything except unwelded seams of the current stage.
- Don't turn gravity off again after stage 1.
- Don't start pose tests or untangling before the last weld.
- Don't exceed 8 storage buffers per shader stage.

## 9. Report back to Tyler

Before/after screenshots of the tee + hood drape: front, side and fit map. Report these numbers from test 4:
- neckline rise;
- armhole offset on each side;
- hem rise;
- the extra drape time.

Also note this: once the shirt stays put, any remaining problem is the hood's own size and shape. A hood generated from head measurements is the next feature to spec.
