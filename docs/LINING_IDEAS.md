# Linings poking through the shell: what's done and what's next

Tyler noticed it on 2026-11-28: on a lined dress, the lining shows through the outer fabric.

## How a lining works

- `freeform._expand_linings` gives each lined piece a twin in the lining fabric, named `<piece>_lining`.
- The twin starts just inside its shell (`place._lining_of`).
- It's held to the shell along every edge that isn't left open. The hold uses attach springs (`freeform._attachments`).
- Linings of neighbouring pieces are sewn to each other like the shell.
- Only cloth-on-cloth contact keeps the two layers apart. That contact doesn't know which layer is meant to be inside: once the lining has been pushed through the shell, the contact holds it on the outside.
- Poly lining weighs about a third of what jersey does per m² and is slippery, so it's the layer that gets shoved through.

## Done (v1.6.16)

1. **The lining is cut like a real one**: shorter by `LINING_SHORTER_CM` (2.5 cm) at its open edges, such as the hem. Its two neighbouring edges are trimmed to meet the new hem (`freeform._shorten_open`). `lining.shorter_cm` sets it per piece, and 0 keeps the old cut.
2. **It's tacked to the shell like French tacks at the seams.** The two mesh points at each end of every shortened open edge are tied to the shell point under them, with the same attach springs as the held edges. `meta["lining_tacks"]` lists the tacked edges.

### Measured

A lined shift dress, jersey with a poly lining, on the GPU, cloth contact on while sewing (as the drape runs it):

| | Lining points outside the shell | Lining hem vs the shell's |
|---|---|---|
| Before | 1,037 of 5,731 | 0.2 cm lower (shows) |
| After | 905 of 5,541 | 2.5 cm higher (hidden) |

The hem no longer shows. The rest still pokes through: patches across the lower skirt, where the layers hang free.

### Then, on Tyler's own dress (`sleaved dress.drape`, 2026-11-28)

The dress has flannel linings in the bodice (held to the shell all round) and in both sleeves (open at the hem).
Two more causes turned up:

1. **A placement bug.** The right sleeve's lining started outside its sleeve: 865 of 946 points, before anything moved.
   - Cause: `freeform._host_normal` takes "outward" from the piece's 2D winding. The right sleeve is the left one mirrored, so its normal pointed into the arm.
   - Fix: the normal is turned to point away from the body (the sign of its dot product with the body's distance gradient). The fix covers linings, inside pocket bags and patches.
2. **The jump as sewing starts.** The layers flew through each other in the first frames, the same thing that tangled two garments.
   - The fix that cured that, contacts planned for the speed cap while sewing (`start_speed`, `cloth._fast_sewing`), was only on for merged garments.
   - Now it's on for any design with linings or layer copies (`meta["lining_joins"]`).
   - On the GPU, `live_springs.js` only planned for the first frame. Now it does what the CPU does during the whole sewing phase: plans for the speed cap, uses the full contact margin (`SELF_MARGIN_MAX`), and caps the speed at that margin per frame.

| Lining points outside the shell | Front bodice | Back bodice | Left sleeve | Right sleeve |
|---|---|---|---|---|
| CPU, 1 s, before | 475 | 324 | 432 | 428 |
| CPU, 1 s, fast sewing | 2 | 1 | 38 | 29 |
| Website (GPU, quick), end, before | 175/290 | 142/278 | 130/352 | 104/352 |
| Website, end, fast sewing | 3/290 | 2/278 | 38/352 | 46/352 |

CPU strain p99 at the end: 21.1 % before, 9.5 % with fast sewing (the lining is no longer tangled through the shell).
Kinetic energy is 1,050 vs 1,559 µJ: this dress is restless either way, and that's still to look at.

Options 3 and 4 below are still worth having for the sleeves' remaining 10 %.

## Next options (not built)

### 3. Sew the lining first, in its own stage

- The lining sews and settles on the body first. The shell then sews on over it, with the lining frozen into the collision grid while the shell sews, then both drape together.
- This is the freeze-style layering built for several garments (`cloth._freeze_garments_under`, `colliders.layered_grid`), applied inside one garment.
- **Design rule:** the stage comes from placement only (the lining sits on its piece's inside, `stages.region` → `("on", piece)`). That's allowed by STAGED_SEWING_SPEC §0, because it never reads seams. It currently gives a lining its piece's stage. A rule "a lining sews one stage before its piece" is still placement-only.
- **Constraints:** freezing stays all-or-nothing per piece (rule 7), and nothing is pushed outward (MULTI_GARMENT_SPEC constraint 2).
- **Effort:** about 1–2 h on the CPU, plus the Live port (Live freeze-style is still on the queue). Physics risk: moderate, the same kind of work as the garment layering, which cut crossings by about 90%.

### 4. One-sided contact between a lining and its own shell

- The design says which layer is inside, so the contact between a lining and its shell could always push the lining inward, never letting it settle outside. That's the side information the body grid has and the cloth contact lacks.
- It stays velocity-only: an impulse along the shell's inward normal at the contact. No position correction (rule 1), nothing inside the CG solve (rule 2).
- Needed:
  - **CPU:** a per-pair side flag in `springs._self_impulses` for lining↔shell pairs.
  - **GPU:** the same flag in `live_springs.js` `ptimp`/`eeimp`.
  - A guard in `tests/test_v19_velocity.py` and `tests/test_v20_gpu_springs.py`.
- **Effort:** about half a day for the CPU and GPU together. Physics risk: high, because a wrong side flag would push a layer through.

### Smaller things to try alongside

- **More tacks:** at the darts, and along the waist seam of a dress with a waist seam. Cheap: they use the same attach springs.
- **A lining 1–2 % narrower than its shell**, as real linings have a little less ease than the shell. It needs matching held edges (they're tied by position on the pattern, so they still line up), and it's worth measuring.
- **Measure first** on the design that shows it, using Tyler's saved `.drape` file. Count lining↔shell crossings at the start, during sewing and after settling. If the lining starts on the wrong side, it's placement (option 3). If it's pushed through later, it's the contact (option 4).
