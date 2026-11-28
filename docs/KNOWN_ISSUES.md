# Known issues

Open problems we know about, with what's been measured and tried, so they aren't lost.
Newest first.

---

## Pockets: an in-seam pocket on a dress's side seam didn't look right (reported 2026-11-22)

**Status:** fixed 2026-11-23 (tests/test_v24_pockets.py); one small thing left (below).

**What was wrong:**
1. **Placement.** The opening was measured down the seam edge from its top. A dress's side seam
   starts at the armpit (or the bust dart), so the opening landed around the bust; the dress
   starters put it 1 cm above the waist. Now it's placed by the avatar's waist (3 cm under it,
   16 cm long by default), on whichever part of the seam is at that height
   (`dedit.body_height_offsets`: pattern y + one offset per piece = height on the avatar, exact).
2. **Shape.** The bag was drawn along the opening's straight line, so on a slanted seam it hung
   tilted and reached up toward the dart. Now the opening follows the seam (straight, slanted or
   curved), the bag hangs straight down from it (`_hanging_bag`), keeps 5 mm inside a narrowing
   seam (pencil skirt), follows the seam above the opening, and its top stays 5 mm under the
   piece's top edge across its width (a skirt's curved waist).
3. **The GPU drape shook.** The bags' stay stitches are explicit springs on the GPU, far stiffer
   than their stability limit: the dress front shook (KE ~1900 uJ, crumpled). The GPU now caps
   each stitch at half its stability limit (live_springs.js `attach`): KE 30, the bags lie flat
   from under the waist to past the hips, the pocket tee's patch pocket is unchanged.

**Left:** a few red specks of bag show through the dress at the hips in the renders, where the
dress sits closest to the body with two bag layers under it.

---

## GPU drape: cloth doesn't fully settle (cloth-on-cloth contact keeps a little motion)

**Status:** open. Doesn't show in the finished drape; fails the "settled" bar on some garments.

**What happens:** after a GPU drape (the website's Drape it, and `drape/gpu.py`), loose folds
keep jiggling by 1–2 mm a frame. The CPU solver (`springs.py`) settles the same garments almost
completely.

| Garment (default female avatar) | CPU KE | GPU KE (several runs) | Bar |
|---|---|---|---|
| trousers, poplin | 0.13 µJ (jersey) | 18, 35, 42, 58 µJ | < 20 µJ |
| trousers, jersey | 0.13 µJ | 28–31 µJ | < 20 µJ |
| A-line skirt | — | 20–22 µJ | < 20 µJ |
| tee, hoodie, pencil skirt, gloves | — | 0.04–12 µJ (hoodie 0.5) | pass |

Points inside the body stay at 0 and stretch stays within the bars in every run. GPU runs are
not repeatable (atomics), and the trousers' KE ranges 18–58 µJ between identical runs, so
compare several runs, not one.

**Where it comes from:** cloth-on-cloth contact. With it off, the trousers settle to ~4 µJ.
The fastest points are loose folds ~3 cm off the skin (layers touching layers, not the body),
on all four pieces.

**Tried (2026-11-22, trousers poplin unless noted), none fixed it:**

| Change, GPU only | KE (µJ) | Result |
|---|---|---|
| skip triangles with a corner next to the point (springs.py's `_is_near`), unwelded | 33 | no help |
| the same, plus welds at springs.py's times (the CPU's exact combination) | 56 | no help |
| no "pressed" half-thickness target (as springs.py) | 43, 44 | no help |
| two contact passes per substep, the second seeing the first's pushes | 49, 58 | no help |
| candidate lists 64 triangles / 32 edges (from 24 / 16) | 21, 26 | within the noise |
| contact damping ×2 | 23 | a little |
| overlap easing time (SELF_TAU) ×2 | 20 | a little |
| edge-edge contacts off | 31 | no help |
| CG budget 200 (from 48) | — | no effect (sewing test) |

The contact formulas, timing (every substep) and contact damping match springs.py line by line.
The remaining differences: the GPU applies contacts in parallel and averages them per point
(springs.py applies them one by one); float32; the GPU has edge-edge contacts; the seam groups
(no welds while draping on the web).

**Options:**
1. A settling phase on the GPU: raise the damping step by step over the drape's last ~0.3 s.
   Quick; should bring KE under 20 µJ without changing the shape. It changes the GPU's numerics,
   so it needs Tyler's OK first.
2. A deeper dig: log which contacts fire on the fastest points frame by frame, and whether
   pairs flip sides or keep re-entering the overlap easing.
3. Leave it: it doesn't show in the result.

**Fixed along the way (commit f83b0b1, live since 2026-11-22):** the GPU planned extra
substeps from the cloth's speed even while contact was off during sewing, which stalled every
seam at ~60 mm. Now it plans them only while contact runs, as springs.py does, and its sewing
follows springs.py's (p99 gap 40.6 vs 40.9 mm at frame 44).

**Scripts used** (in `tools/gpu_experiments/`, run from the repo root): `sew.py` (sewing frame by frame), `modes.py`
(full drapes, welds at springs.py's times vs at the end), `ke.py` (where the motion is),
`settle.py` (shader variants on a test copy of live_springs.js).

## Pocket bags show through on elastic-waist garments (2026-11-24, "less is more" spec 1.1)

The bags of in-seam pockets used to show through the front on the website's drape. Cause: the web shim
turned cloth-on-cloth contact off while the seams were sewing (`selfWhileSewing = false`), so the bags
passed through the front before contact came on. Fixed: `/api/drape` now says `self_while_sewing` for
layered designs (pocket bags, linings), the same rule as the desktop's CPU drape. Bag points left outside
the garment (female_M, GPU): shift_pockets 0.2%, swing dress + 2 pockets 0.4%, joggers 0.3%,
a_line_pockets 0.3%, shirt_dress 0.2%.

**Still failing (target: at most 2% outside):** scrub_pants 2.6-2.8%, shorts 3.3-5.6%, gathered_skirt
10-12%. All three have elastic waists: the waist gathers in and the bag tops, sewn just under it, ride
out over the gathered front. Lowering the bag tops onto the elastic made the gathered skirt blow up
(494 points inside the body), so that was reverted. `tests/test_v25_simple.py::test_pocket_bags_stay_inside`
marks these three strict xfail: when one gets fixed, the test says so.

## Red fit warnings from hems caught on hands and feet (2026-11-24, spec 1.3)

Checking every starter on {female_M, male_M} x {jersey, its own fabric} on the GPU drape, the remaining
reds all look the same: a few dozen points at a sleeve hem, cuff or trouser hem, stretched 60-170%.
No fabric does that (denim locks at 3%), so the cloth is caught on a hand or foot, not too tight.
GPU drapes aren't repeatable, so a starter can be red one run and clean the next (mittens did).

Cleared with drafting changes, verified on both avatars: the hoodie (Regular cuffs, 7 cm over the wrist, were
Fitted 4; the zip hoodie shares the change but still goes red on the male avatar's hands) and the pencil skirt (hip ease 6, waist ease 3, were 4 and 2). Other changes cleared
one avatar but not the other, so they were reverted: henley and cardigan cuffs, the chore jacket 2 cm
shorter in the sleeve, and jeans at ankle length.

Still red (xfail in `test_starter_shows_no_red_fit_warning`): button_up, cardigan, chinos, chore_jacket,
fingerless_gloves, henley, jeans, joggers, mittens, oversized_tee, pajama_pants, scrub_pants, shift_zip,
zip_hoodie (the male avatar's hands) and zip_jacket. Joggers didn't change with hem height (8, 12 or 15 cm)
or leg opening (24, 28 or 36 cm).
Open question for Tyler: fix the catching in the drape,
or leave points past the fabric's lock strain out of the fit advice (they're a drape glitch, not fit).
Diagnostic script: per piece, the snug points' strain vs their fabric (`tools/gpu_experiments/starter_check.py`, `fit_diag.py`; bags: `visible_bags.py`).


## Larger avatars: reached, with rough edges (2026-11-24)

Reported by a user: building the avatar told them their ratios were wrong. That message is gone (CLAUDE.md "Bodies").
The bigger problem was that MakeHuman's shapes stopped short. A body with chest 140, waist 150 and hips 160 got
an avatar measuring 119, 92 and 135, and patterns are drafted from the avatar, so nothing would fit. Now
(`human.fit_human`, CLAUDE.md "Bodies"; `python tools/avatar_range.py`):

| Body (height · chest · waist · hips, cm) | Before | Now |
|---|---|---|
| Woman 165 · 125 · 118 · 135 | 26 cm off | within 1.2 |
| Woman 165 · 140 · 150 · 160 | 58 cm off | within 3.4 |
| Man 178 · 150 · 160 · 150 | 52 cm off | within 3.5 |
| Woman 160 · 160 · 165 · 180 | 74 cm off | waist exact; chest and hips 14 short |
| Man 180 · 130 · 130 · 125 | 22 cm off | hips 8 over |

Bodies MakeHuman reaches on its own are unchanged, to the vertex (male_L compared with the old code).
Still rough: a ledge at the sides where the added belly starts, on the largest bodies; the largest
body's chest and hips; men's hips a little over when the belly is large. Not yet checked: draping
garments on these avatars (collision with the bigger belly), and the fit time on the web (the wider fit
runs a second solve: about twice as long, only for these bodies).

## Multi-garment: what stage 1 doesn't do yet (2026-11-24)

- Garments that aren't frozen don't collide with each other (spec: stage 2, cloth to cloth across
  garments). Each one drapes against the body and the frozen ones, one after another. With two or more
  unfrozen visible garments, Try on shows "Freeze inner layers for best results."
- Live mode moves the active garment only. Frozen garments are in its collisions. Other unfrozen
  garments keep their last drape.
- Poses (sitting, walking) move the avatar but not a frozen garment, so leave the pose off when layering.
  Poses aren't on the website yet anyway.
- A frozen garment holds the shape it was frozen in. Changing its pattern doesn't redrape it:
  unfreeze, drape it again, freeze again.
