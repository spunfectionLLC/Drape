# drape (Spunfection Studio): notes for Claude Code

drape is a free, open-source garment design tool: 2D sewing patterns draped on a
3D avatar built from body measurements. Owner: Tyler (maker, 50 W laser, Etsy shop).
Version in `pyproject.toml`; what changed in each version is in `README.md`.

## Naming (docs/specs/RENAME_SPEC.md, 2026-11-22)
- Users see **Spunfection Studio** (short: "Spunfection"), by **Spunfection LLC**, at **spunfection.studio**.
  The code keeps its name: the package `drape`, modules, imports, `python -m drape.studio`, test and
  file names, the `.drape` project extension and `format: "drape-project"` (old files must open).
- One source for the strings: `drape/brand.py` (mirrored as `BRAND` in `js/01_core.js`; the page and
  footers carry them too; `tests/test_v22_rename.py` checks).
- "Spunfection Studio™" once per surface (page header, README title, PDF/tech-pack footer, about
  box); plain elsewhere; never "®". "drape" in the UI only as the sewing word (Drape it, the drape).
- No competitor names in anything a user sees (UI, meta tags, README, generated files). No personal
  email anywhere in the repo or its output (a test greps for it); contact is via the Report a bug form.
- Generated files: PDF footers "Made with Spunfection Studio™ · spunfection.studio", tech pack adds
  © Spunfection LLC, glTF `asset.generator`, DXF header custom properties (never text on a layer:
  a laser would cut or engrave it), saved projects get `"app": "Spunfection Studio"`.
- Report a bug goes to a Google Form (`brand.BUG_REPORT_URL`, 2026-11-24: no GitHub account needed; the privacy
  page says so). Footer links (Terms, Privacy, Source code, Report a bug) go to placeholder pages (`brand.PAGES`)
  until the texts and the public repo exist.

## Run it
- Studio (the app): `python -m drape.studio` → http://127.0.0.1:8765
  - `--share`: other devices on the home network, over https with drape's own
    certificate (`~/.drape/tls`), so live mode (WebGPU) works there too
  - `--share --http`: plain http, no live mode on other devices
- Test tools: `pip install -e .[test]` then `playwright install chromium`, plus
  Poppler on PATH for the PDF scale test.
- Tests in parallel (Tyler's PC has 8 cores and a GPU; CPU drapes, GPU and browser tests run at the
  same time): `pytest -n auto --dist loadfile` (pytest-xdist; `loadfile` keeps each file in one worker,
  so the browser tests' module-scoped server and page stay together). Set `DRAPE_CHROME` for the
  GPU/browser tests. The body-grid cache is written atomically, so workers can share it.
- Tests one at a time: `pytest` (~15 min, 190+ tests). Run in batches if the machine is slow:
  `tests/test_drape.py`, then `test_v8 test_v9 test_v10 test_v15 test_mesh2d`,
  then `test_studio test_v11..v14 test_v16`, then `test_browser.py`.
- Browser tests (`tests/test_browser.py`): Playwright + Chrome; they start their own
  studio server. Skipped if Playwright or a browser is missing. Set `DRAPE_CHROME`
  to a Chrome binary if it isn't found.
- Desktop app: `pyinstaller packaging/drape.spec` (one-folder build); CI builds
  Windows/Mac/Linux on tags (`.github/workflows/build.yml`).
- In-browser speed test: `python tools/build_web_proof.py`, then serve
  `out/web_proof/` (`python -m http.server`) and open it on localhost.

## How it's built
- `human.py`: MakeHuman (CC0) avatar fitted to `Measurements` by least squares
  (girths, lengths, inseam, hand girth). `meshmeasure.py`: tape measurements on the mesh.
- `meshbody.py`: the body for collision: a signed distance grid, built lazily
  (libigl, or `sdf_numpy.py` when libigl is missing).
- `blocks.py`, `garments.py`, `gloves.py`, `starters.py`, `freeform.py`: pattern drafting,
  ready-made designs (gallery), and free-form designs from the editor.
- `dedit.py`: design edits in the editor format (cm), also the server side of the studio's
  `/api/edit`: shapes (`shape_with`: cut away / join on / keep the overlap, keeping edge names
  and seams), `join_along_seam`, `layer_copy` (overlay copies, `place.layer_of` + `held` edges,
  tied like a lining by `freeform._layer_joins`), bands. `freeform.order_loop` puts a band's edges
  in order round the opening by following the seams (a hood opens at the centre front).
- Project files: `.drape` = the project JSON with `format: "drape-project"` (`06_export.js`).
- `pattern.py` + `mesh2d.py`: pieces meshed for the solver (no points added on the
  outline, so seams stay matched). `mesh2d.py` replaced the Triangle library, whose
  licence forbids commercial use. Don't bring Triangle back.
- `cloth.py`: the solver-independent cloth code. `Fabric`, the speed/stage constants,
  `plan_substeps`, hinge setup, contact hash and candidates, and `ClothSim` (fabrics and
  masses, weld, staged sewing timeline, body, `_prepare`, `_plan_speed`, untangle, metrics).
- `springs.py`: the cloth solver (`SpringSimulator(ClothSim)`, exported as `drape.Simulator`).
- `live.py` + `studio/static/live_springs.js`: the same solver on the GPU (WebGPU/WGSL),
  including cloth-on-cloth contact. `live_setup()` prepares everything it needs.
- `seammarks.py`: seam numbers and colours, one-sided notches (single = front,
  double = back, 40% along), match dots. Used by the PDF, DXF, AAMA and the studio.
- Exports: `printpdf.py` (tiled/projector PDF), `export_dxf.py` (plain/laser),
  `export_aama.py`, `export_gltf.py` (+ Blender script), `techpack.py`, `sizerun.py`,
  `nest.py`, `costing.py`, `instructions.py`. `importer.py` reads DXF patterns back.
- `studio/server.py`: the studio's HTTP API (ThreadingHTTPServer). `studio/tls.py`:
  https for `--share` (handshake per connection thread, or an idle browser
  connection blocks every request).
- `studio/static/`: `index.html` (markup only), `css/studio.css`, and `js/01_core.js`
  … `js/18_boot.js` (17 is the garment panel): classic scripts sharing one global scope, loaded in order. A
  function a file needs *while loading* must be defined in an earlier file.
  `server.studio_source()` concatenates them in load order (tests use it).
- Layout (2026-11-23): each step has its own layout, set in `studio.css` from `body[data-step]` (set by
  `go()`; the page starts at `body`): the pattern box only on Fit and Design; Garment and Make it get the width with
  the avatar beside them. A step's main buttons sit in a sticky `.actions` bar at the bottom of the side panel.
  Try on's options are tabs (`.tabs`/`.tabpane`); checks and the avatar's numbers are one-line `details.sumbox`.
  Units, dark mode and help are in the ⚙ menu (`#setmenu`); Simple/Advanced stays in the header (tests click it).
  Seam names shown to people go through `plainRef()` (`front.side_1_r` -> "Front · right side, part 1").
- Design (2026-11-24): top toolbar (`#toolcard`) = everything not about the selected piece (Shape/Sew,
  Symmetric, Seams and Start over dropdowns, Add a piece / Finish an opening chips, ◐ 3D view, Try it on);
  the left bar (the side panel's design pane) = the selected piece (`#inspector`, `#cutBtn`); the pattern
  gets the rest, kept above the pinned Warnings bar (`--logh`). The 3D view shows only with `body.show3d`
  or while placing a piece. Steps are never locked: `stepNeed(k)` says what a step needs; `go()` then
  greys it (`body[data-blocked]`) and shows `#blockmsg` with a button to the step it needs.
- Toolbar (2026-11-25): groups of square `.tb` buttons (`tbInner(icon, label)`, icons in `TOOL_ICONS`, 08_design.js),
  one colour per group (`.g-mode/.g-piece/.g-edge/.g-open/.g-view`, `--gc`). Edge tools (`EDGE_TOOLS`, 12_pieces.js):
  `DS.tool = "edge"`, `DS.edgeTool`; a click on an edge applies it at that spot (`applyEdgeTool`), `edgeTargets` adds
  the mirror images (Symmetric), the board draws `.edgemark` where it would go; options live in the board's `#toolpop`.
- Split with a shape (2026-11-25, `dedit.split_with`, edit op `split`): every overlapped piece -> parts outside + inside
  (`shape_with` cut + keep on a clone), sewn along the shape, crossed seams re-sewn part to part (`_resew`). Parts keep
  their piece's spot on the body through `place.center_cm` + `place.span_cm` (freeform `_piece_place`); re-anchoring a
  part drops them. From the piece panel (`#psplit`: a piece as the cutter, it goes) or the shape tool's panel.
- Tool previews (pockets): `livePreview(op, args, inputs)` asks `/api/edit` without keeping the result and
  draws what would change, dashed (`DS.ghost` new pieces, `DS.ghostEdges` moved edges, compared on the board);
  the form's button then commits exactly that. Add one to any server-edit form the same way.
- Simple vs Advanced (2026-11-24, "less is more"): Simple hides, never deletes. Use `.adv`/`.beg` for
  blocks and `.advi`/`.begi` for inline items, plus the `body:not(.advanced)` block in studio.css. The
  toolbar dropdowns use `.dd.advdd`/`.dd.begdd`, and Make it's extra formats use `.moreonly`. Switching
  mode re-renders only; it never resets state. One primary button per step (`tests/test_v25_simple.py`).
  Fit messages have a `level` (note/problem): the constants and `vertex_comfort` sit before `_advise` in
  server.py. Change a starter's ease, not the thresholds, to clear a red.
- Multi-garment projects (docs/specs/MULTI_GARMENT_SPEC.md, 2026-11-24):
  - `PROJECT = {version: 2, garments, activeGarmentId}` lives in `js/01_core.js`. Everything about a pattern
    (block, choices, params, design, fabric, drape, job, print, the editor's selection and view) is in its garment.
  - `ST.block` / `ST.design` / ... and `DS.sel` / `DS.view` are getters of the active garment. Don't add a
    global copy of garment state.
  - `setActiveGarment()` is the only way to switch; `onGarmentSwitch()` redraws.
  - Undo is one stack of `{gid, before, after}`.
  - File version 2 (`migrateProject` opens version 1). A `.garment` file holds one garment; on import it gets
    a fresh id and the next layer.
  - The Garments panel is `js/17_garments.js` (`#gpanel`). Its rows are top layer first.
  - Layer order is only ever set by the user (a design rule). Freezing is all or nothing per garment.
  - Garment and Fit are one "Design" step: `go("fit")` opens the picker while the active garment has no pattern.
- `_jit.py`: numba if installed, plain Python otherwise (the browser).

## Bodies (Tyler, 2026-11-24): every body is valid
- Never warn about, judge or question a body's size, shape or proportions. A larger user was told
  their measurements' "ratios were wrong" when the avatar was built; that must never happen again.
- Measurement checks catch only typos: inches typed into cm fields (a value far *below* any adult's)
  and a tape taken the wrong way (shoulder width measured round, not across). No upper limit on any
  girth, no ratio between girths, no "unusual" / "too large". Word each message about the number
  ("Waist 30 cm: if you measured in inches…"), never about the person. `tests/test_v25_bodies.py`.
- When the avatar can't reach someone's numbers, that's the avatar's limit: say so in neutral words
  (no warning colour, no "!"), never imply the person's numbers are wrong.
- Fit advice is about the garment ("give it more room at the hips"), never the body.
- The avatar reaches larger bodies (`human.fit_human`, 2026-11-24). MakeHuman's weight macro may go a little
  past its slider (`WEIGHT_MAX` 1.6), and the fitter also uses MakeHuman's belly and seat shapes. A waist that
  is still short gets a round belly (`human._widen`), mostly forward, ending at the underbust line. That body
  is then measured round the middle at the belly's level. The waist tape stays near the natural waist on the
  skeleton, and the chest tape at bust level (`meshmeasure.Tape.lines`).
  Bodies MakeHuman reaches on its own are unchanged. `python tools/avatar_range.py` prints the numbers and
  renders the bodies to out/avatar_range/.
- Optional measurements left empty are "auto": no target, so MakeHuman's body shape decides them; the field
  then shows the avatar's value. Size presets fill only height, chest, waist and hips. Still least squares on
  the morph targets: no regressor (design rule 11).

## Conventions
- Measure before claiming: physics changes get numbers before/after (strain p95/p99,
  crossings, penetrations, kinetic energy). Several "obvious" ideas measured worse.
- Every version adds `tests/test_vNN.py`; UI changes get a browser test.
- Keep `THIRD_PARTY_NOTICES.md` current; every dependency must allow commercial use.
- Plain language in the UI; units follow the user's cm/in setting.
- Fabric presets are researched estimates until measured on the tester
  (`hardware/fabric_tester`, not built yet).

## The website (docs/WEBSITE.md; built 2026-11-22 for the Cloudflare Pages launch)
- `python tools/build_site.py` -> `out/site/`, static files only. The studio's own page and scripts, plus
  `web/site/web_shim.js` (loaded first: answers every `fetch("/api/...")` in the page) and
  `web/site/py_worker.js` (Pyodide in a module Web Worker, from jsDelivr, running `drape_bundle.zip`).
- `drape/webapi.py` routes the requests to the server's own `api_*` functions (a test checks every
  server route is there). `/api/init` says `web: true`; the page hides move tests (poses) then.
- Drape it on the web: `/api/drape` runs `server._drape_job` up to its yield (garment, simulator, body
  grid: ~26 s in Chrome, the numpy grid at 8 mm, `DRAPE_GRID_H`), returns `live.sim_setup`; the page runs
  LiveSprings for the job's frames (~6 s for a tee), posts the positions to `/api/drape_done`, which welds
  and resumes the job (fit, ease, result.npz), so `/api/job` and every export work as on the desktop.
  The desktop's `_drape_worker` runs the same generator straight through on the CPU.
- No numba and no libigl in the browser: anything they speed up runs as plain Python/numpy there.
- The site sends a Content-Security-Policy (`build_site.CSP`, 2026-11-25): no inline script, no eval, scripts only
  from the site and jsDelivr's Pyodide. Anything new from another host (AdSense, fonts) needs adding there;
  `test_v23_web` drapes and exports under it. Playwright's `wait_for_function` needs `() => ...` there (eval is blocked).
- Measured (GTX 1060, Chrome): Python ready 14 s, avatar 12 s, tee 5 s, drape 33 s, every export works.

## Cloudflare (deploying the website; Tyler's rules, 2026-11-22)
- A Worker with static assets only (no server code): `wrangler.jsonc` (name `spunfection-studio`, assets
  `./out/site`) is the source of truth. Account `759f8c8b69c9f5600bf45ab18d41775e`; never deploy elsewhere.
- Auth only from the environment: `CLOUDFLARE_API_TOKEN` (scoped, "Edit Cloudflare Workers") and
  `CLOUDFLARE_ACCOUNT_ID`. Never print, log or commit the token, never put it in `wrangler.jsonc` or
  `.dev.vars`. If it's missing, stop and tell Tyler: don't run `wrangler login` (interactive, it hangs).
- Deploy: `python tools/build_site.py`, then `npx wrangler deploy --dry-run --outdir <tmp>`, then
  `npx wrangler deploy`; report the URL and the version ID. Ask first if a change touches bindings,
  routes or secrets.
- Never without Tyler's approval: `wrangler delete`/`rollback`, deleting R2/D1/KV, account settings,
  DNS or zone changes (spunfection.studio + www are Custom Domains in `wrangler.jsonc`, live since 2026-11-22), new
  dependencies or frameworks.

## Where it's going (decided with Tyler)
1. **Website, all in the visitor's browser** (no server compute; a static site on
   Cloudflare Pages with Tyler's domain). Python runs in Pyodide; draping runs on
   WebGPU. Done so far: numba/libigl optional, `sdf_numpy.py`, cropped live grid,
   `out/web_proof` speed test. **Next:** run the speed test on a real laptop; then
   port the studio's HTTP calls to in-browser Python calls, make the GPU drape the
   default "Drape it", move fabric presets to a data file (with versions, so saved
   designs can say "this fabric was updated"), static build + deploy.
2. **Ads are the main revenue**: AdSense to start (needs guide pages, privacy policy,
   contact page, cookie consent). No ads beside download/export buttons and no forced
   ad before an export (both against AdSense policy). Export can offer an *opt-in*
   rewarded ad ("watch a short ad to export, or go Pro") via Google Ad Manager
   rewarded ads, which needs approval. If no ad is available, export just proceeds.
3. **Pro tier (~$10/month), later**: no design features behind the paywall. Free:
   everything that runs on your computer, browser save, file save/open. Pro: cloud
   library with version history and share links, cloud drapes (AWS Lambda per job),
   drape every size at once, seller kit (size-run PDFs, A0 copy-shop files,
   instructions, cover images, branding), measured fabric library, no ads.
   Teams tier later. Side income: fabric-tester kits, printed-pattern referrals.
4. Open questions: the first sewn shirt (from drape's pattern) fit together; fit
   numbers (chest, length, sleeve, tight spots) are still to be compared with drape's.

## The cloth solver (XPBD was removed by design)
- Plan approved by Tyler (2026-11-18), all four steps done: springs passes every bar;
  the GPU springs port replaced Live; the shared code moved to `cloth.py`; XPBD
  (`solver.py`, `live.js`, `--solver xpbd`) deleted in its own commit, no history rewrite.
  Don't bring any of it back: no constraint projection, no Lagrange multipliers.
- Old XPBD-era numbers and the specs in docs/specs/ that mention `solver.py` / `live.js`
  are history (the specs are dated records; leave them as written).
- `springs.py` `SpringSimulator` is the solver (docs/specs/SPRING_SOLVER_SPEC.md,
  SPRING_VELOCITY_LEVEL_SPEC.md and its section 9 notes). It is mass-spring forces with
  **implicit backward Euler** by default (Baraff & Witkin 1998, matrix-free CG,
  `IMPLICIT_SUBSTEPS = 40`). Strain limit, body and cloth contacts are velocity impulses
  (Bridson 2002).
- **Velocity level, never break it:**
  - positions change only by x += h v (plus the DEEP_PEN safety net);
  - no velocity from a position difference; predicted x + h v is read-only;
  - no XPBD code path in springs.py: no `_solve_*`, no Lagrange multipliers, no
    compliance projection.
  - `test_v19_velocity.py` checks all of this (the per-substep debug check and a source
    grep). If a fix seems to need a position correction, stop and ask Tyler.
- Contacts:
  - overlapping cloth layers ease apart over `SELF_TAU`;
  - the speed cap lets the body's outward push go first (sliding gets what's left).
  - Both were measured: without them the tee never settles and the gloves end up in the hand.
  - The push is capped at the speed cap too: uncapped, sitting made pushes of overlap / h
    (up to 600 m/s for a substep, the trousers buzzed); capped, 3.00 m/s max, KE 11690 -> 5213 uJ.
  - Order in a substep: the body, then cloth on cloth; with a posed (moving) body, the skin
    once more at thickness 0. Without that last pass, sitting left 3 trouser points inside
    (bar 2). With it for a still body too, the gloves ended with 1-3 points inside (bar 0);
    body last at full thickness pushed a sheet on a ball through the one over it.
  - Elastic casings (edges `freeform._shrink_band` shortened, `ClothSim._elastic_e`, kept
    through the weld) pull with `ELASTIC_K` (1000 N/m per edge), not the fabric's springs:
    with jersey's own (75 N/m across the grain) the example skirt slid 7 cm down the hips.
- `implicit=False` keeps the explicit path (symplectic Euler, Gershgorin bound
  h * omega < 2, `plan_stable`, softening past `MAX_SUBSTEPS`). Only the stability tests use it.
- The staged-sewing timeline and `_prepare_staged` are in `cloth.py` (moved line for line);
  stage choice stays in `stages.py` (section 0).
- `calibrate.py` (My fabrics) fits the compliances by running its strips on springs.
- Benchmark: `python tools/bench_cloth.py` (table + out/bench/ renders).
- **GPU:** `studio/static/live_springs.js` (`LiveSprings`), data from `live_setup()`
  (`_springs_payload`). Used by Drape it's live mode; the CPU `SpringSimulator` runs Drape it.
  - Each substep assembles the implicit matrix as 3x3 blocks per vertex row (bending part constant,
    precomputed); CG is Chronopoulos-Gear (2 dispatches/iteration), block-Jacobi, warm-started
    from the last dv, budget per frame from the last frame's worst substep.
  - Live never welds: cloth-on-cloth uses seam groups (points sewn together = one group). A
    point skips a triangle only where a corner of it is in its own group AND within the contact
    thickness: while a seam is still open the sewn edge must collide with the triangles round
    its partner (else it went round them: the shoulder knot). Don't skip triangles touching a
    *neighbouring* group (as `_is_near` does on the welded mesh): the cloth next to a seam then
    folds through the piece it's sewn to (tee: 23 crossings vs 2).
  - Each contact's push is split over all its points by inverse mass and barycentric weight
    (Bridson 2002; springs.py does the same, sequentially). On the GPU the shares add into `DVA`
    as fixed-point i32 atomics with a weight; `gather` divides by max(weight, 1). Pushing only
    the point let a seam pull a triangle through a point pinned against the body. Summing
    without the division is unstable (3+ m/s).
  - Edge-edge contacts too (Bridson 2002 7.2; `ehinsert`/`ecand`/`eeimp`): point-triangle can't
    see edges sliding past each other round a triangle's border. Mesh edges = first `ne` springs.
  - Overlapping layers are eased apart to the full thickness, or to half of it when any of the
    pair's points touched the body that substep: squeezed layers between arm and side can't
    get 3 mm apart (easing them to it buzzed at 0.2-0.3 m/s); no easing at all let them creep
    through each other. Contacts run every substep (every other one buzzed at the shoulder).
  - Measured (default-measurement avatar, `/api/avatar` with `{}`): the 10-crossing shoulder
    knot is gone (0 before and after the yank, settled 0.08-0.11 m/s).
  - The yank test's crossing count skips a triangle with a corner anywhere in the edge's seam
    group (at a 4-piece underarm corner an edge end and a triangle corner are one sewn point,
    0.03 mm apart, joined through the corner's other points). GPU runs are not bit-repeatable.
  - Candidate rebuilds: the lists hold what's within cmargin (capped at 15 mm), so moving fast
    they're rebuilt every `rebuildEvery` substeps (set in `_plan` from the fastest point and the
    mouse) so the motion between rebuilds fits the margin. Built once a frame, a fast yank folded
    the chest through itself about one yank in 20; with rebuilds 12/12 yanks clean.
  - Positions are written only in the `finish` kernel (x += h v); `tests/test_v20_gpu_springs.py`
    guards the shaders like test_v19 guards springs.py. Storage buffers <= 8 per stage (module C uses 8).
  - Status (GTX Pascal): tee 54 ms/frame (the old XPBD Live: 27), gloves 122; strain/settling match
    springs.py.
  - GPU browser tests on Windows need `DRAPE_CHROME` = the installed Chrome; Playwright's own
    Chromium fails `requestDevice` (dxcompiler.dll).

## Staged sewing (docs/specs/STAGED_SEWING_SPEC.md)
- **Design rule (spec section 0), never break it:** a piece's
  stage comes ONLY from where it's placed (`stages.region`, from `place.*` keys and the
  placed centre), its `role` tag, or the user's `piece.stage`. No stage code may read seams,
  the seam graph or which pieces are sewn to which (a test greps the source); no fallback
  that infers stages; pieces are placed once, never re-placed by a stage. Name things
  "sewing order" / "stage", never "arrange" / "iteration". If a feature seems to need any
  of that, stop and ask Tyler.
- Roles: body/sleeve 1; hood/collar/cuff/waistband 2; pocket 3. Without a role: region
  (band round an opening, head, neck, hands 2; on a garment's surface 3; on its piece's
  inside / lining / layer copy = its piece's stage; else 1). Stages are renumbered without
  gaps (gloves alone, a hood alone: stage 1). Starters, bands, pockets, gloves and block
  templates set `role`; copies inherit it. A seam sews with the later of its two pieces.
  `build_design` stores `meta["piece_stage"]`, `meta["seam_stage"]` (per vertex pair).
- `Simulator` with more than one stage: `_prepare_staged` + `_stage_events`. Pieces not
  sewn on yet are frozen (w = 0, out of self-collision); each stage's seams ease over its
  own sewing time (`SEW2_TIME` after the first), then `weld(mask)` welds just them
  (the rest stay seams, renumbered); `ANCHOR_W` makes the sewn side heavy *for the seams
  only* while a later stage sews (springs: `_seam_forces_one_sided`). It is 0.01, not the
  spec's 0.05 (XPBD's): as a share of a spring force over the sewing time, 0.05 lifted the
  shirt (hood window p95 15.6 mm; 0.01: 5.7 mm; the tee alone 1.7). Run
  `seconds + sim.extra_time`. One stage takes the old path, bit for bit (a test forces
  the staged path on a tee and compares).
- Live mode (no welds): per-stage seam scales and anchor weights in `Frame.seamS/seamA`,
  frozen pieces as W = 0 rewritten when a stage starts.
- `python tools/stage_report.py`: tee vs tee + hood, staged vs all at once,
  numbers + out/stages/*.png.

## Design rules
Set on 2026-11-20. Never break these; if a feature seems to need it, ask Tyler.
1. **Solver:** no position projection onto constraints (PBD/XPBD), no Lagrange multipliers or
   compliance projection, no velocity from a position difference. Positions change only by
   `x += h·v`, plus the documented deep-penetration net.
2. **Implicit solve:** no constraint filtering or projection of contact-constrained nodes inside the
   CG solve. Contacts stay separate velocity impulses after the solve.
   (Pinned and frozen points, w = 0, are left out by their mass.)
3. **Staged sewing:** STAGED_SEWING_SPEC section 0 (stages never from seams; pieces placed once,
   never re-arranged).
4. **Seams:** colours are identity only; a mismatch is text. No snapping partial-seam tool with
   live match colours.
5. **Measuring:** single edges, or tape measures on a 3D mesh. No cross-piece 2D point-to-point
   measure with gap correction. The ease report takes drafted girths (`meta["girths"]`) or the
   drape (`fitcheck.drape_ease`), never summed 2D pattern lengths.
6. **Creating pieces:** only from the 2D editor or drafting. No 3D-click piece creation, and no
   "duplicate piece in 3D". Facings, when built: a new offset
   shape of the opening, seams the user confirms. A bias binding: a cut piece only.
7. **Placement and grab:** single-pass placement; no seam closing before the physics; no
   drag-onto-avatar wrap preview; no graded-falloff pin brush. Stage freezing stays binary per piece.
8. **Layers:** layer order per piece (stage, "next to the skin" / "over it"). No UI that assigns a
   front/behind relation between two seam lines.
9. **Corner truing:** numeric (angles and lengths reported). No ghost copy of a piece moved along
   another's outline.
10. **Projector PDF:** a static true-scale file only. No projector control, calibration or keystone
    features.
11. **Body:** direct bounded least squares on the morph targets. No learned regressor, and no photo
    or scan input for the body, without asking Tyler first.
12. **Fit diagnosis:** advisory, about the user's own design. No retail size recommendation or
    e-commerce framing.
13. **Anything resembling a commercial garment-CAD tool:** add it to `docs/ALGORITHMS.md` and ask Tyler
    before building it.
- **Feature switches** (`drape/features.py`, mirrored as `FEATURES` in `js/01_core.js`; the
  server's copy goes out in `/api/init`): `OPENING_BANDS`, `BINDING_TOOL`, `FACING_TOOL`
  (on), `CLOUD_DRAPE` (off, not built). A switch that's off hides the buttons and answers
  403; existing designs still load, drape and export. Hoods aren't bands (`dedit.add_hood`).

## Gotchas
- Substeps are dynamic (speed-based in both solvers, stability-based in springs):
  never assume `sim.nsub` / `this.substeps` is the count used; `sim.nsub_frame` is.
  Slow frames use exactly the base count, so calm results don't change.
- Caches: numba in `.numba_cache/<source hash>`, body grids in `.sdf_cache/`
  (`DRAPE_SDF_CACHE`), user data in `~/.drape/`. Delete `~/.drape/fabrics.json`
  before packaging.
- A sandbox proxy (if any) breaks `https://` to LAN addresses in tests: Chrome needs
  `--no-proxy-server`, urllib needs `ProxyHandler({})`.
- The studio server takes 10–20 s to start (numba imports) before printing its address.
