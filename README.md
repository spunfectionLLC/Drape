# Spunfection Studio™: free, open-source 2D sewing patterns → 3D drape in your browser. By Spunfection LLC.

**Try it: https://spunfection.studio**

The code package is named `drape` (`python -m drape.studio`, `import drape`).

Make sewing patterns that fit, without knowing patternmaking. Type in your
measurements, pick a garment, choose the fit in plain words, try it on a 3D
avatar, then print it at home or send it to a laser cutter. Everything runs on
your own computer.

```bash
pip install numpy numba scikit-image imageio ezdxf shapely pillow scipy matplotlib libigl
python -m drape.studio          # opens Spunfection Studio in your browser
```

## Spunfection Studio (the app)

Five steps across the top: **Body → Garment → Fit → Try on → Make it.**

| Step | What you do | What it does for you |
|---|---|---|
| Body | Pick a size, type height / bust / waist / hips (more if you have them) | Builds a realistic female or male avatar to those numbers (within ~1 cm) and shows how far off each one is. "How to measure" draws every tape line on your avatar. |
| Garment | T-shirt, long sleeve, A-line skirt, pencil skirt, shift dress, trousers | Drafts the pattern to the avatar's measurements. |
| Fit | Tap choices: Fit (snug…oversized), Length, Neckline, Sleeves, Shape, Rise | Redrafts live. Checks every seam (lengths match, edges meet smoothly) and the room at chest / waist / hips / thigh / neck / arm, in plain words, with **Fix it** buttons. Matching colors on the pattern = edges that sew together. |
| Try on | Pick a fabric, press Drape it (~15–25 s) | Sews the pieces and lets them fall on the avatar. Shows where it pulls (fit map) and offers a one-click fix, e.g. "the hem is resting on the feet". |
| Make it | Download | Fabric to buy (yards and metres, 45"/60"), print-at-home PDF (Letter/A4, 5 cm test square), projector PDF, cutting layout, DXF, **laser DXF** (LightBurn colors: red cut, blue stitch mark, green engrave; notches only snip the seam allowance), OBJ, numbered sewing steps. |

### Design from scratch

Garment → **Start from scratch**. The drawing board replaces the pattern library:

* **Add pieces:** rectangle, trapezoid, triangle, circle, oval, half circle. Type exact sizes, or drag
  corners to reshape, drag the dot on an edge to curve it, double-click an edge to split it.
  Duplicate, **mirror copy** (makes the left/right twin and places it on the other side of the body).
* **Put it on the body:** pick a spot (chest, waist, hips, neck, arms, thighs, back of the head…) or
  **tap the avatar** anywhere. Choose which part of the piece goes there (middle / top edge / …),
  wrap it around the body or lay it flat, turn it, and choose a layer (next to the skin / over other
  pieces) so a top can hang over a skirt.
* **Sew:** tap an edge, then the edge it joins. Same color = sewn. Spunfection Studio works out which way round
  the edges go from where the pieces sit, so seams don't come out twisted (there's a Flip button if
  you want it the other way). Different lengths are flagged with **Make them match** or **Gather**.
* **Elastic:** mark an edge elastic and it gathers to fit the body where it sits; the sewing steps
  tell you how long to cut the elastic.
* **Start from a template:** on any pattern's Fit step, **Edit freely** turns it (with your choices)
  into a from-scratch design: same outlines, seams and sleeve ease, and every piece keeps hanging where
  the pattern puts it, so you can lengthen, flare, curve, split, add pieces or re-sew. Undo goes back.
* **Make it a tube that fits here:** measures the body where the piece sits and sets the width (+6 cm ease)
  and sews the sides.

Try on, fit map, PDF/projector/DXF/laser export and sewing steps all work the same as for the
library garments. In Python: `drape.freeform.build_design(design_json, body)`.

### New in v1.7.1: AI edits keep your garment
- Editing with AI keeps the garment you have: "the hoodie is too small" on a dress now means its hood, not "make it
  a hoodie". The AI says first how it read your request, an edit that drops most of your pieces is sent back, and the
  review sticks to the parts you asked about. Patch pockets are sewn on properly.

### New in v1.7.0: design with AI (bring your own key)
- **✦ AI** in the header: describe a garment, or sketch it (over the 3D view, the pattern, a blank page or your own
  image: red removes, blue adds, green draws a new line, black is for notes), and Claude designs it. Start from
  scratch (a new garment) or edit the one you have.
- It works in rounds: the builder writes the pattern, the studio checks it (and sends any problem straight back to be
  fixed), it's draped on your avatar, and a critic looks at renders of the drape and the fit numbers and asks for
  specific changes. Every round is kept: pick the version you like.
- You type your own Anthropic API key each visit. It stays in that browser tab and goes only to Anthropic: it's never
  saved, put in a project file or sent to Spunfection. The panel shows what the rounds have cost on your key.

### New in v1.6.16: linings stay inside
- A lining is cut 2.5 cm shorter at its open edges (a hem), so it can't show below the shell, and tacked to the
  shell at each end of them (French tacks at the seams).
- A mirrored piece's lining (the right sleeve's) started outside it: fixed (pocket bags and patches too).
- Garments with a lining or a layer copy sew with contacts planned for fast-moving cloth, on the desktop and
  the website: on a lined dress the lining points ending outside the shell went from 30-60% to 1-13%.

### New in v1.6.14: move several corners at once
- Shift-click corners (or Ctrl-click), or shift-drag a box round them, then drag one: they all move together.
  The arrow keys nudge them (0.5 cm, 5 cm with Shift); Esc lets go. Symmetric keeps the mirror side matching.

### New in v1.6.13: a look per piece, fabric in Design, flared cuffs
- Fabric and print are set in Design now (Try on is only for simulating). Each piece can have its own look in its
  panel: a print, a solid colour (a black bodice over a plaid skirt) or your own image, with its own repeat size;
  Symmetric gives its mirror image the same. Each piece can still have its own fabric for the physics too.
- A cuff or hem band has a **Flare** slider (0-150%): its open edge gets longer than the seam, cut as part of a
  ring, so it drapes as a fluffy bell.
- The ALPHA badge shows the version.

### New in v1.6.12: the Sleeve tool works whichever armhole you click first
- It finds the front armhole from where it sits on the body. Clicking the back one first used to sew the sleeve's
  front half to the back, and the seams crossed over the shoulder: delete those sleeves and add them again.

### New in v1.6.10: curve handles
- Click an edge's curve dot and two handles appear, one at each end: drag them to set the curve's direction and
  strength there. Right-click the dot for **Symmetric curve** (both ends curve alike) or **Straighten**. A pattern's
  own curves (an armhole) get handles fitted to them, and dragging the dot keeps them smooth.

### New in v1.6.8: sleeves fit front and back armholes of different lengths
- The generated sleeve's cap is drafted half to the front armhole and half to the back one (on a dress the front
  is shorter), so neither seam is gathered or stretched; generated sleeves no longer say "not on the body".

### New in v1.6.7: a sleeve generator
- The Sleeve tool on the Design toolbar: click the front armhole edge, then the back one, and a set-in sleeve
  drafted to fit that armhole is sewn in (the other arm gets one too with Symmetric on). Pick the length (short,
  elbow, 3/4, long to the wrist), the fit (fitted, regular, loose) and the cap (smooth, or puffed and gathered).

### New in v1.6.6: several garments draped together
- With more than one garment showing (desktop), Drape it drapes them together, layered by simulation: they sew
  one after another in the layer order you set in Garments, inner layer first, and each one settles over the ones
  under it. Every garment still gets its own fit map, pattern and exports.

### New in v1.6.5: split pieces with a shape
- Draw a shape (or use a piece) across your pattern and split every piece under it, keeping all the parts:
  they're sewn back together along the shape, seams it crosses are sewn part to part, and the parts inside
  can be another fabric (a contrast midsection on a dress).

### New in v1.6.4: a new Design toolbar, edge tools you place by clicking
- The Design toolbar is square buttons in colour-coded groups: mode, pieces, edges, openings, view.
- Darts, pleats, gathers, hems, elastic, seam allowance and split are tools on the toolbar: pick one, click the
  spot on an edge. With Symmetric on, the mirror image gets the same; a marker shows where it will go.
- The edge list shows what's set on each edge instead of the same buttons on every edge.
- Phones: the toolbar, pattern and warnings no longer sit on top of each other.

### New in v1.6.3: loading indicators, a faster draft, no GPU buttons without a GPU
- Picking a garment or a starter shows that its controls and pattern are on their way; a change shows a spinner.
- Drafting is faster (a tee's draft 0.9 s -> 0.4 s): pieces are meshed without re-sorting every edge, and the
  avatar's tapes are measured once.
- ⚡ Live is hidden where the browser has no graphics card it can use; on the website, Drape it says why it can't
  run there instead of failing.

### New in v1.6.2: a second round of fixes
- The website sends a Content-Security-Policy: the page runs only its own scripts.
- The 3D view frees the memory of replaced meshes; Drape it is busy only for the garment being draped.
- Undo keeps the newest 300 steps.
- Numbers typed into fabric, closure, pocket and export fields get a plain message when they can't work,
  instead of saving something broken. Your saved fabrics file can no longer be wiped by one bad entry.
- A piece typed far too big gets a message instead of freezing the studio; nesting takes up to 10 garments.

### New in v1.6.1: fixes from a review of the code
- Names in a shared project or garment file can no longer put code into the page; files with unknown
  patterns, fabrics or units still open and say what was missing.
- The desktop studio only answers its own page; export file names are kept to plain characters.
- A drape that dies or fails ends with a message instead of waiting for ever; switching garments stops
  Live; exports use the drape on screen; temp folders are cleaned up.
- Measurements an avatar can't be built from (inches in cm fields, 0, text) say which number.
- Full list: docs/BUG_HUNT_2026-11-25.md.

### New in v1.6: outfits (several garments in one project)
- **Garments panel** at the top of the side panel: add a garment (new, from a `.garment` file, or a
  copy), rename it, drag to set its layer (layer 1 is closest to the body), hide it, freeze it.
  Click a garment in the list, or on the avatar, to work on it. The others show dimmed.
- **Freeze and drape over it:** drape the inner garment, freeze it (❄), then drape the next. The frozen
  garment holds its shape and the new one rests on it. A dress drapes over frozen leggings with no
  points through them, on the computer and on the website.
- **One file for the whole project** (version 2; older projects open as one garment). **Export garment**
  saves a single garment to move it to another project.
- **Make it** with several garments: patterns for the active garment, or for every garment (one file
  each). The 3D files can hold the whole outfit.
- Garment and Fit are one step now, **Design**.
- **Larger bodies:** the avatar reaches them. Optional measurements are worked out from your other
  numbers ("auto"), and the measurement checks only catch typos.

### New in v1.5.1: less is more
- **Simple mode shows the essentials.** Each step has one main button. The avatar follows your numbers
  as you type, with no build button. Garment shows finished designs first, with a difficulty on each card.
- **Design (Simple):** the pattern, Symmetric, Undo/Redo, an **＋ Add** menu (pockets, hood, bands,
  collar), and the selected piece's name, size and delete. Everything else is still in Advanced, in the
  same place. Switching modes keeps your work, selection and step.
- **Try on** shows five common fabrics, with the rest under *More fabrics*. **Make it** shows Print at
  home (Letter or A4 by your locale, with a switch), Cutting layout and Sewing instructions. Every
  other format is under *More formats*.
- **Fit messages have two levels:** a grey *note* when the cloth is snug but within what its fabric
  stretches comfortably, and a red *problem* past that. Each problem has a *Show me* link to the fit map.
  The rules are in one place (`server.py`, before `_advise`).
- **Pocket bags stay inside** the garment on the website's drape. The pattern shows them beside their
  piece, with plain names ("Pocket bag · right, front half").
- **One-time tips:** each step's intro line can be dismissed with ✕.
- **Starter fixes:** the hoodie has Regular cuffs (were Fitted) and the pencil skirt more hip and waist ease,
  so they show no red fit warning.
- Known issues: docs/KNOWN_ISSUES.md (elastic-waist pocket bags, hems caught on hands and feet).

### New in v1.5: shape with shapes, layers, and .drape files
- **Shape it** (select a piece → *Cut, join or trim with a shape…*): a dashed circle, oval,
  rectangle, triangle or half circle (or the outline of another piece) appears over the piece.
  Drag it and size it, then **Cut it away** (necklines, armholes, scallops, notches), **Join it on**
  (tabs, flares, a rounded hem) or **Keep the overlap**. The piece keeps its sewing: edges the shape
  doesn't touch keep their names, curves and seams; an edge it shortens stays sewn (the checks flag
  the length); an edge it cuts in two becomes `_1`/`_2` and is unsewn, with a note. A cut right
  through makes two pieces. With Symmetric on, the shape is mirrored onto the other side too. Holes
  in the middle of a piece aren't supported yet. In Python: `dedit.shape_with`.
- **Join with a sewn piece**: *⊕ join with yoke along top* makes two pieces one, laid flat along
  their seam (same length and shape only), and the seam disappears. `dedit.join_along_seam`.
- **Copy onto the layer over it** (Fabric & layers): an overlay copy, one layer out, in its own
  fabric if you like: tulle over a skirt, a sheer over a bodice. Copies are sewn to each other like
  the originals; where the original is sewn to something else (a waistband) or gathered, the copy is
  *held* to it there, caught in the same seam (tap **held** on its edges to change). `dedit.layer_copy`.
- **📁 File** (top bar, Ctrl+S / Ctrl+O): save and open `.drape` project files. In Chrome and Edge,
  Save opens the system's save window and then keeps saving to the same file; elsewhere it downloads.
  Old project `.json` files still open.
- **Hoods, collars and bands go round in the right order**, whatever order you tap the edges in:
  Spunfection Studio follows the seams round the opening, and a hood opens at the centre front (splitting the
  front neckline there, or at the gap if part of the front is left out).
- **Live mode no longer flings and shakes cloth**: like the full Drape, it caps how fast any point
  can move (3 m/s). Without the cap, a hood squeezed between its seams and the head buzzed and fell
  onto the chest; now it settles round the head and stays still.
- The Warnings bar no longer covers the bottom of the side panel.
- **Sewn in stages, like you'd sew it**: the body of a garment (fronts, backs, sleeves) is sewn
  and settles on the avatar first; hoods, collars, cuffs, waistbands and pockets are sewn on after,
  and travel to the garment instead of dragging it to them. A tee with a 16" hood: the hem used to
  rise 1.8 cm and the armholes shift 1.2 cm; now 0.8 cm and 0.8 cm. Each extra stage adds
  1.4 s of simulated time. Each piece has a role (body, sleeve, hood, collar, cuff, waistband,
  pocket); Advanced mode: set a piece's sewing order (1, 2, 3 or auto) and role in its panel.
  `python tools/stage_report.py` compares staged with all at once.

### Toward a website that runs in the browser (v1.4.1)
- Spunfection Studio runs without Numba and libigl (neither exists in a browser): `drape/_jit.py` falls back to
  plain Python, and `drape/sdf_numpy.py` builds the body collision grid with numpy and SciPy (signs
  identical to libigl's on the watertight body, within 0.2 mm near the skin). Live mode then builds
  only the box around the garment, not the whole body: 42 s to 10 s without libigl.
- `tools/build_web_proof.py` builds `out/web_proof/`: a page that loads Pyodide, builds an avatar,
  drafts a tee, exports the PDF and DXF, and drapes it on the GPU, timing every step. Serve it with
  `python -m http.server` and open it on localhost.

### New in v1.4: pieces that only go together one way
(The first real shirt sewn from Spunfection Studio had its sleeves in upside down.)
- **Numbered, coloured seams.** Both edges of a seam carry the same number in the same colour,
  in the PDF, the laser DXF (layer `SEAMNO`, engrave lightly or turn off) and the studio's
  pattern view: ③ sews to ③, with "to BACK" (or whichever piece) under the number.
- **Notches that fit one way only.** They sit 40% along each seam rather than in the middle,
  so an edge turned end for end doesn't line up, and seams that touch a back piece get double
  notches (single for front), the usual convention: a sleeve put in back to front can't match.
- **Match dots** where two seams meet on a smooth curve: the top of a sleeve cap, which goes to
  the shoulder seam.
- Also in the AAMA export, size runs and nesting. Spunfection Studio's own DXF importer ignores the numbers
  and dots.

### Showing someone on your home network
`python -m drape.studio --share` (or `drape-studio --share` for the desktop app) lets phones,
tablets and other computers on the same Wi-Fi use the studio, live mode included: it prints the
address to open. It's served over https with a certificate Spunfection Studio makes for itself (kept in
`~/.drape/tls`), so the other browser warns once that the connection isn't private: choose
*Advanced* then *Continue*. After that the page counts as secure and live mode runs on that
device's own graphics card. Anyone on the network can use it while it runs; stop it with Ctrl+C.
`--share --http` skips the certificate (no warning, but no live mode on other devices).

### New in v1.3: hands, and a studio that's easier to work on
- **Hand measurements for gloves** in *More measurements*: hand length (wrist crease to middle
  fingertip), **hand girth** (around the knuckles, thumb not included: the measurement glove
  sizes use) and wrist. The avatar's hand is widened or narrowed to the girth, separately from
  its length (both hit within 0.1 cm), and glove patterns are drafted from it. Hand girth is on
  the how-to-measure sheet. It's measured on exact cross-sections of the hand: the old vertex
  slab read a man's hand as 16.7 cm instead of about 21.
- **The studio is split up.** `index.html` is markup only (about 200 lines); styles are in
  `css/studio.css` and the code in 17 files in `js/`, one per area, loaded in order
  (`01_core.js` ... `17_boot.js`). They are plain scripts sharing one scope, so behaviour is
  unchanged.
- **Browser tests in the repo.** `tests/test_browser.py` drives the studio in Chrome: the body
  step, the fit and design layouts, mirrored drags and splits, the warnings log and its popup
  (including that it never blocks a handle), symmetry off, and a glove drape. It is skipped when
  Playwright or a browser isn't installed: `pip install playwright` (and `playwright install
  chromium`, or set `DRAPE_CHROME` to a Chrome binary).

### New in v1.2.1: free for commercial use
- The Triangle mesh library (free only for non-commercial use) is gone. Pattern pieces are now
  meshed by `drape/mesh2d.py`: a jittered triangular grid inside, SciPy's Delaunay, outline
  segments restored by edge flips. Same point density as before (within 3%), better-shaped
  triangles on average, outline points untouched so seams stay matched. Checked on all 40
  garments and on awkward shapes (fingers, thin strips, zigzags).
- `THIRD_PARTY_NOTICES.md` lists every bundled component and its licence; all allow commercial use.

### New in v1.2: an editor laid out for work
- **Controls split by job.** The left pane holds only the current step's controls. In the design
  step, the drawing tools (shape/sew, add a piece, finish an opening, the selected piece) sit in
  their own column beside the 2D pattern. A big **Convert to free edit** button tops the fit step.
- **Warnings log** along the bottom of the window, always in view: mismatched seams, design
  problems, fit problems from the drafted pattern and from the drape. Each seam mismatch has
  one-click fixes: make both edges the first one's length, the second one's, or gather the longer.
- **Popups on the pattern.** Every edge with a problem gets a "!" badge; a new problem (or one
  clicked in the log) opens a popup on the edge itself, with the same text and fixes.
- **Symmetric editing** (on by default, toggle in the tools): left/right pieces such as
  `front_r` / `front_l` stay mirror images, and a piece symmetric about its own centre (a tee
  front) stays symmetric. Dragging corners, curving edges, splitting edges and the seam-length
  fixes are all mirrored; a curve that crosses the centre line stays symmetric. Found from the
  shapes, so it works on any design.
- **Inseam** (crotch to floor, barefoot) is a body measurement: the avatar's thigh and shin
  lengths follow it (within 0.2 cm, girths unchanged within 1 cm), it's on the how-to-measure
  sheet, and trousers and shorts get an inseam point of measure in the tech pack.

### New in v1.1.1: gloves
- **Four glove templates** under *Accessories* in the gallery: gloves, mittens, fingerless gloves and
  long (evening) gloves. Each is a two-layer pattern (back and palm, sewn round) drafted from the
  avatar's hand: finger lengths from its skeleton, girths from the hand breadth, the palm from the mesh.
- **Fit fixes found while testing them:**
  - the studio dropped a design's own mesh size when draping, so gloves ran on a 2.5 cm mesh and
    fingers poked through; designs now keep it;
  - the 4 mm air gap the cloth keeps to the skin adds 2.5 cm round a finger (about 40% tension on a
    5.5 cm finger), so small garments can ask for 2 mm;
  - the palm is drafted through its measured girth over the ball of the thumb, not a straight line
    from wrist to knuckles, and the thumb tube widens toward its root.
  - Male L knit gloves, stretch at p95 (the worst 5% of edges): thumb 31% → 18%, palm 17.5% → 10%,
    ring and little fingers under 10%.
- The fit advice names hands and arms by the skin underneath, not by height (hands hang at hip height).

### New in v1.1
- **Cloth-on-cloth collision in live mode (GPU).** Triangles go into a spatial hash each substep and every
  vertex is pushed off the nearest triangle on the side it started on; seam partners are skipped. On the
  A-line skirt with pockets, crossed layers drop from 4,688 to 1,222 (‑74%). Costs about 2× per frame.
- **Live editing.** Change length, ease or a style while live is running and the cloth keeps its drape:
  each piece hangs from its top, and new cloth hangs below the old hem instead of restarting from flat.
- **Calmer move test.** Cloth speed is capped at 3 m/s (motion energy ‑98% when sitting), and the move test
  runs 6 stretch passes plus *untangle*: where cloth is caught inside the body or over-stretched, its edges
  are let out by up to 18% and then eased back.
- **Desktop app.** `packaging/drape.spec` builds a one-folder app with PyInstaller (no Python needed);
  `.github/workflows/build.yml` builds Windows, Mac and Linux on each tagged release.

#### What the physics experiments showed (CPU, measured)
| Idea | Where | Result | Kept? |
|---|---|---|---|
| Let fabric expand where it's caught | sitting | strain p99 67% → 45% | yes, move test only |
| Let fabric expand where it's caught | still drapes | trousers p99 3.9% → 18% (baggy) | no |
| Higher tension (6 stretch passes) | arms up | crossings 28,664 → 1,924 | yes, move test |
| Smaller time steps (80 substeps) | both | little change, 1.6–1.8× slower | no |
| Speed cap 3 m/s | sitting | motion energy ‑98% (vertices hit 150 m/s before) | yes, always |

### New in v1.0

**⚡ Live drape on your graphics card.** Try on → *Live* runs the cloth solver in the browser on the GPU
(WebGPU: Chrome/Edge 113+, Safari 26+). Same model as the full drape (stretch, isometric bending, seams
that pull in, topstitching, the avatar as a distance field, friction), with every constraint type split
into colour batches so each batch runs in parallel. Drag the cloth with the mouse, switch fabrics while
it moves. It leaves out cloth-on-cloth collision and seam welding: *Drape it* is still the accurate
result and the fit check. (`drape/live.py` packs the garment, `studio/static/live_springs.js` is the solver.)

**Fabric that behaves like fabric.** Each fabric now has its own stretch across the grain and on the bias
(wovens give on the bias, knits stretch crosswise) and a lock strain where the yarns straighten and it
stops giving. The fit map ignores bias shear (that's drape, not tightness).

**DIY fabric tester** (`hardware/fabric_tester`): ESP32 + 5 kg load cell + slide pot, a hand crank, and a
laser-cut 3 mm jig (DXF). Pull strips along, across and on the bias; the studio reads it over USB (Web
Serial) or from CSV, fits stiffness, anisotropy and lock strain, runs the droop test for bending, and adds
your fabric.

**Exports for the trade:** DXF-AAMA (pieces as named blocks, AAMA layers: cut, sew, notches, grain,
internal, drill) for factories and pattern CAD; a **tech pack** PDF (views, measurement spec with
tolerances measured on the drape, bill of materials, cut list, pieces, construction); a **Blender kit**
(the draped garment, buttons and avatar as .glb plus a script that renders a studio photo with fabric
sheen and weave in free Blender); and plain **.glb**.

**Per-edge seam allowance** (tap "SA" on an edge: a deep hem, a narrow neckline), mitred in every export.

**Looks:** fabric shading (sheen on fleece and flannel, gloss on silk and lining, a fine weave or rib
texture), darker hollows in folds, a soft floor shadow, seam lines and dashed topstitching 8 mm in from
every hem, drawn on the drape so they move with it.

**Help:** the **?** button explains each step.

### New in v0.9

**30 starter designs.** The Garment step now has a gallery of finished garments, sized to your avatar and
filtered by category: tees (classic, cropped, oversized, pocket, sleeveless, long-sleeve, henley), workwear
(scrub top and pants), loungewear (hoodie, zip hoodie, joggers, pajama pants, sleep shirt), shirts and jackets
(button-up, camp shirt, chore jacket, cardigan, zip jacket), pants (jeans, chinos, pull-on shorts), skirts
(A-line with pockets, pencil, button-front, gathered) and dresses (shift, swing with pockets, shirt dress,
tee dress). Each one opens in the design editor, already finished with bands, pockets and closures, and
suggests a fabric. `drape/starters.py` builds them from the pattern library plus `drape/dedit.py`.

**Closures.** Any seam can close with buttons, snaps, a zipper or hook & loop tape (pick it in the seam list),
with a count and size, and *done up / half open / open* for the try-on. "Open down the middle…" cuts a piece
along its centre line and closes it; "top part only…" puts a zipper or placket in the top of a seam (skirt
backs, flies, henleys). On the cut pieces you get the button stand and grown-on facing, a fold line,
buttonhole and button marks (buttonholes on the wearer's right or left), and zipper stops: in the PDFs and
on a `MARK` layer in the DXFs and laser nests (score it lightly or chalk it). Buttons, snaps and zippers are
drawn on the 3D garment, and go into the cost & price and the sewing steps.

**Inside pockets.** *Pocket in a seam* splits a seam, leaves the opening unsewn and adds two pocket bags
inside, sewn to the opening and to each other and caught at the waist. *Front hip pocket* cuts the curved
jeans/chino opening from the waist-side corner and adds a pocket yoke behind it, sewn into the side seam and
the waistband. Patch pockets can also go on the inside face (a jacket's inner pocket). While sewing, the
solver keeps bags and the piece over them apart; in the viewer the bag is always drawn under its piece.

**Solver fix.** v0.8 made pieces that start crumpled (trouser legs) weld before they opened out, so trousers
hung with the crotch at the knees. Edges now pull straight to their rest length while sewing (only elastic
casings ease in), with soft springs across folds until the weld. Trousers are back to ~4 % strain.

### New in v0.8

**Layers and fabrics per piece.** Any piece can have its own fabric (rib-knit cuffs on a jersey top),
fused **interfacing** (light, medium, knit, heavy: the piece really gets stiffer and heavier), or a **lining**
(a twin piece in lining fabric, sewn to its neighbours' linings and joined to the shell at every edge you
don't leave open). Garments worn over each other (a top over a skirt) start apart and stay apart.

**Pockets and patches.** "+ Pocket on this piece", or set any piece to *sewn onto another piece*: drag it where
you want it on that piece; each edge is *sewn* (topstitched) or *open*.

**Darts, pleats, gathers** on any edge (from-scratch and converted patterns), with the seam added for you.

**Collars, neckbands, waistbands, cuffs, hem bands, hoods.** Tap the edges round an opening; the band is sized
to it (rib bands cut 85–90% so they stretch on), placed round the opening, sewn on, and closed into a ring
(a hood opens at the centre front).

**Trace a garment from a photo.** Lay it flat on a contrasting surface next to a ruler, tap the ruler's ends;
the outline comes in at true size with its corners as edges. **✂ Cut a piece** splits any piece along a line
(sewn back together; unsew it if they should stay apart).

**Move test.** Sitting, walking stride, arms up, reaching forward: the avatar moves (MakeHuman's CC0
skeleton) and the garment moves with it. Collision follows each bone exactly, frame by frame. You get a
playback slider and "Sitting: pulling at the hips" style advice.

**Measure your own fabric.** Weigh a 10 × 10 cm square, measure how far a strip droops over a table edge
(and optionally how much it stretches under a weight); Spunfection Studio runs the same tests in the simulator and saves
a matching fabric. The built-in fabrics now use published bending lengths (chiffon ~1 cm … canvas ~5.5 cm),
and bending uses a curvature-based model, so stiff fabrics really stand away from the body.

**Prints.** Stripes, plaid, gingham, dots or your own image on the draped garment, at any repeat size:
check that stripes meet at the seams before you cut.

**Sell it.**
- **Size-run PDF pattern:** every size (women's 2–20 from ASTM D5585 body measurements, or men's chest 34–52)
  nested on the same tiled pages, with a size chart and test square.
- **Laser nesting:** pack one or more garments onto your bed size, sheet by sheet, in one LightBurn DXF.
- **Cost and price:** materials (fabric per type, interfacing, elastic, thread), sewing time, and the Etsy
  price that covers costs, your profit and Etsy's fees ($0.20 listing, 6.5%, 3% + $0.25, optional Offsite Ads).
- **Turntable video** of the draped garment (MP4 where the browser supports it, else WebM).

**Faster and live.** "Quick look" drapes in ~10 s on a coarser mesh; every drape streams to the 3D view as it
falls. **Tap the garment** anywhere to ask what's going on there: too tight across, pulled up and down,
diagonal drag lines or extra fabric, with a fix.

**Advanced** (top right) shows every drafting parameter as a slider, the seam table, and simulation numbers.
Also: cm/in toggle, dark mode, undo/redo (Ctrl+Z), saved measurement profiles, project files you can
reopen, and it works on a phone. Your last project reopens automatically.

## Python API and command line

```bash
python run_demo.py --measurements measurements/female_M.json --draft          # tee drafted to you, rendered
python run_demo.py --garment skirt --measurements measurements/me.json --draft
python import_pattern.py my_pattern.dxf                                       # patterns from Seamly2D/Inkscape/CAD
python -m pytest -q                                                           # 111 tests, ~6 min
```

* `drape.blocks`: the pattern library. `draft_block("trousers", body, m, {"hip_ease": 8})`.
* `drape.draft`: drafting tools (lines, beziers, arcs, splines, hermite, offset, mirror, split/join,
  darts, cut-on-fold, notches, round corners, grading) in a path builder.
* `drape.layout`, `drape.printpdf`, `drape.instructions`, `drape.export_dxf` (`laser=True`).

## How it works
| Module | What it does |
|---|---|
| `pattern.py` | Panels made of named edges (lines + cubic Béziers). Seamed edges get identical vertex counts. Meshing in `mesh2d.py`: a jittered triangular grid inside, SciPy Delaunay, outline restored by edge flips, no points added on the outline (seams stay matched). Rest state = the **flat** pattern. Isometric placement: `cylinder_wrap` (around the torso) and `axis_wrap` (around any axis, e.g. an arm). |
| `measurements.py` | **Avatar from tape measurements** (height, chest, waist, hip, shoulder width, neck, upper arm, arm length, optional thigh/underbust). Torso = elliptical sections with anthropometric depth/breadth ratios, Catmull-Rom between them. Then a **virtual tape** (convex hull of the torso cross-section, as a tape bridges hollows) measures it back and the torso is rescaled until every girth matches: all three test bodies come out within 0.2 mm. The torso is kept from swallowing the arm at each height (otherwise there's no armpit for an armhole). Input validation catches inches-as-cm and across-vs-around mistakes. |
| `seamcheck.py` | **Sewing checks before simulating.** (1) Length: both sides of every seam match, or differ by the ease declared on the seam. (2) Direction: detects a seam sewn end-to-end the wrong way from the 3D placement. (3) Truing: corners sewn together are grouped into junctions; an edge junction (hem, neckline) must sum to 180°, an inside junction (sleeve crown + shoulder seam) to 360°, else it reports a point, dip, cone or ripple. Corner tangents use a 2nd-order estimate (chords were off by ~2°). |
| `fitcheck.py` | **Ease report:** garment girth minus body girth at chest (taken at the underarm), waist, hip, neckline, upper arm, with a fit verdict. |
| `extremities.py` | Hands and feet (see v0.5 notes), plus the virtual measuring for them. |
| `importer.py` | DXF → panels + seams (see v0.5 notes). |
| `fabrics.py` | Named fabric presets. |
| `viewer.py` | Self-contained WebGL viewer export. |
| `garments.py` | `tank_top()`, `tshirt()`, `tshirt_for()`, `a_line_skirt_for()`, every dimension a parameter. The T-shirt's sleeve-cap height is **solved** (bisection) so each cap half = armhole length × (1 + ease), the way a patternmaker drafts it. |
| `body.py` | Mannequin as a signed distance field: elliptical torso slices + capsules, smooth-min blended, scaled by chest girth. |
| `cloth.py` | What the solvers share: the fabric, **sewing → weld → gravity** and staged sewing, the body, cloth-on-cloth contact candidates (spatial hash), speed-based substeps, metrics (`ClothSim`). |
| `springs.py` | The cloth solver: mass-spring forces and bending with implicit backward Euler (Baraff & Witkin 1998, conjugate gradients, 40 substeps/frame). Strain limit, body contact with friction and cloth-on-cloth contact are velocity impulses (Bridson et al. 2002); positions only ever move by x += h v. Sewing, weld and staged sewing from `cloth.py`. |
| `studio/static/live_springs.js` | The springs solver on the GPU (WebGPU) for live mode: the implicit solve assembled as 3x3 blocks and solved by conjugate gradients on the GPU, contacts as velocity impulses. |
| `render.py` | Numba z-buffer rasterizer (no GPU/display), body via marching cubes, **fit map** (strain heat map), OBJ export. |
| `export_dxf.py` | Flat pattern → DXF in mm. Layers CUT (seam allowance included), SEW (dashed), NOTCH, GRAIN, TEXT. Opens in LightBurn, Inkscape, LibreCAD, Seamly2D. |

## v0.6: realistic female and male avatars (MakeHuman, CC0)
The avatar is now the **MakeHuman base mesh** shaped by MakeHuman's artist-sculpted
morph targets (CC0, via MPFB2; `drape/data/makehuman.npz`, 6.9 MB, licence in
`drape/data/MAKEHUMAN_LICENSE_CC0.md`). `sex` in the measurements file picks the body.

- **Shape model** (`human.py`): sex, muscle, weight, height, breast size/firmness and
  ethnicity macros combined exactly as MakeHuman does, plus 19 "measure" targets
  (bust, underbust, waist, hips, shoulders, neck, upper arm, thigh, arm length...).
  Dress-form chest by default (MakeHuman's nipple-flattening targets).
- **Fitting** (`fit_human`): height slider from the height (tall people get tall
  proportions), then least squares over **body weight + one measure target per
  measurement**, with a small penalty on the local targets so the solver explains as
  much as it can with whole-body weight. That's what makes sizes grow like people:
  average → max weight for a man adds waist +10.6 cm, hip +5.9, chest +2.7, upper arm
  +2.2, neck +0.1 (tested). Beyond MakeHuman's range (e.g. a 100 cm male waist) the
  targets extrapolate, at an extra cost. Exact height by uniform scale.
- **Tape on the mesh** (`meshmeasure.py`): convex hull of plane cuts (a tape bridges
  hollows); skin-weight regions keep arms out of torso girths; hip = level where the
  seat protrudes most; armpit = highest level with air between arm and chest;
  shoulder width = shoulder tips (acromion) across the back along the hull.
- **Fit accuracy**, six example bodies (`measurements/{female,male}_{S,M,L}.json`):
  within 0.7 cm on every measurement for S and M; L within 1.4 cm (waist slightly
  under: the largest bodies are at the edge of MakeHuman's range).
- **Collision** (`meshbody.py`): signed distance grid from the mesh (libigl fast
  winding number, 6 mm, trilinear), cached on disk per body (~20 s once, then
  instant). 95 % of grid samples within 1.5 mm of the exact distance (tested).
- Garments, fit checks, importer and renderers use one small body interface, so the
  old capsule mannequin still works (`--mannequin`).

Bugs found while building it: the first shoulder-width tape zig-zagged between
vertices (51 cm on an average man; 44 now, along the hull); skin-weight armpit was
5 cm too high (gave a 22 % strain shirt; 2.6 % after); the fitter's quick armpit
estimate and the final tape disagreed by 1.2 cm on the chest (now calibrated once per
fit); the ease report's chest window missed deep armholes.

## v0.5 (overnight): hands, feet, DXF import, fabrics, viewer, skirt
- **Hands and feet.** Palm, four fingers and thumb (relaxed, palms to thighs, slight curl); feet as tapered, flattened cones standing on the floor, 7° toe-out; forearms and shins re-tapered to wrist/ankle girth. New optional measurements (hand length/breadth, foot length/breadth, wrist, ankle), defaults from height. Measured back like the rest: every hand/foot measurement within 0.05 cm for S/M/L, soles sit within 0.02 mm of the floor. New SDF primitives: rounded box, round cone, flattened cone, each with its own blend radius (a 3.5 cm body blend would melt fingers into a mitten). Bounding-sphere culling keeps it cheap: +4 % sim time for 24 extra primitives. Renders mesh hands/feet at 3 mm in patches over an 8 mm body.
- **DXF import** (`importer.py`, `import_pattern.py`). Reads closed polylines or chains of LINE/ARC/SPLINE, any units ($INSUNITS), optional seam-allowance inset for cut-line-only files, names pieces from text labels, splits outlines into edges at corners, writes a labelled preview and an editable JSON spec. **Seam suggestion**: nearest-first matching of equal-length edges (or within 6 % ease), with every candidate checked against the junction rules; a piece only sews to itself as a tube (both edges border its hem). Round trip: export the tee, import it, and the suggester recovers all 10 original seams including which cap half goes to front vs back, with the 3 % ease detected.
- **Fabric presets** (`--fabric`): jersey (the default, unchanged), poplin, denim, canvas, fleece, silk, chiffon. Differences on the skirt are in the right direction but modest (hem width 48.7 / 49.2 / 51.0 cm chiffon / jersey / denim): at a 15 mm mesh the cut dominates; visible chiffon ripples need a finer mesh and calibrated bending (roadmap).
- **A-line skirt drafted to measurements** (`a_line_skirt_for`): each piece is an annular sector, so waist and hem meet the side seams at exactly 90°: trued by construction (seam check: 180.0° at all four junctions). The flare is solved so the skirt is exactly (hip + ease) at hip depth. Drapes and stays within 2 mm of the natural waist on its +2 cm ease.
- **Bugs found and fixed tonight**
  - `Fabric.density` was never used: mass always came from the garment builder's 0.15 kg/m². Now the fabric sets the mass (test added).
  - Ease report looked up torso sections by the measured avatar's row order; on the default mannequin every line was one section off (its "chest" was the upper chest). Bodies now carry named sections. **Default-mannequin ease numbers from v0.4 were measured at the wrong heights** (e.g. chest 81.4 → 87.2 cm).
  - Truing tangents: duplicated points from edge splitting gave a 358° corner; unevenly spaced DXF points broke the vertex formula (277° corner); a fixed arc-length window fell inside coarse chords (1.4° error). Now a least-squares quadratic in arc length, exact for all three (tests for each).
  - Two unlabeled imported pieces were both placed in front, producing wrong seams; placements now never stack.
  - Numba cache now keyed to a hash of all package sources, so editing any file can't leave stale compiled code. (Honest note: I saw stale behaviour twice during development but couldn't reproduce it in a clean controlled test of the old scheme; the new scheme rules it out regardless.)
  - Viewer: avatar normals pointed inward (dark body) because marching-cubes winding is inconsistent; faces are now oriented by the SDF gradient.

## v0.4 findings (what the new checks found and what was fixed)
- **Seam check on my own patterns:** neckline met the shoulder seam at 140° (dip), armhole at 220° (point), sleeve cap left the underarm at 107°, and the cap's 3% ease was never declared. Patterns re-trued: every junction now within 0.1°.
- **Virtual tape on the first avatar:** chest read 163 cm vs 112 because the tape wrapped the A-pose arms; hips +0.8 cm from thighs poking out. Fixed: torso-only tape, legs start below the seat line.
- **Root cause of shoulder/underarm strain (measured, converged, noise ±0.2%):** not cap height or shoulder width (wider shoulders tested *worse*: 6.5% → 8.8%), but **armhole clearance below the avatar's armpit.** S/M/L at 4.9/6.0/4.9 cm clearance gave 6.5/3.5/7.3% p99. The drafted tee now sets its armhole depth from the avatar's armpit + 6 cm.
- **Avatar shape:** a flat chest ellipse (depth/breadth 0.68) made the upper torso wide enough to fill the armpit. Anthropometric ratios (0.76) and a per-height arm clearance limit fixed it.
- **Armpit jitter:** layers squeezed between arm and torso ping-ponged (21 vertices at up to 2.6 m/s). Fixed with capped self-collision pushes, contact damping, and a p99-speed hash margin (candidate pairs 27,822 → 124).

| Drafted tee on its own avatar (p99 strain) | before v0.4 fixes | v0.4 |
|---|---|---|
| S (162 cm, chest 88) | 10.8 % | 5.2 % |
| M (175 cm, chest 96) | 9.8 % | 4.2 % |
| L (183 cm, chest 112) | 12.6 % | 6.1 % |
| M tee on L body (−4 cm chest ease) | — | ~24 %, red across the chest, as it should be |

`max` strain varies 29–43 % between runs nudged by 0.5 mm, so it isn't a reliable metric; use p99 or mean.

## Measured results, v0.3 (3–3.5 s simulated, 2 CPU cores)
| | Tank v0.2 | Tank v0.3 | T-shirt v0.3 |
|---|---|---|---|
| Vertices | 3,429 | 3,429 | 4,396 |
| Seam gap | 0 | 0 (welded) | 0 (welded) |
| Penetrating vertices | 0 | 0 | 0 |
| Strain p99 / max | 2.4 % / 22.3 % | **1.6 % / 10.7 %** | 4.4 % / 18.2 % |
| Wall time / real-time factor | 13 s / 0.23× | 18 s / 0.19× | 23 s / 0.15× |

T-shirt strain was checked for convergence: going from 1 to 2 stretch iterations
took p99 from 6.1 % to 4.4 %; 3 iterations or 60 substeps both stay at 4.35 %.
So the remaining strain is **real**: this pattern is tight across the shoulders
on this mannequin, and the fit map shows exactly where.

Self-collision check: two sheets dropped onto a sphere. Off → 91 vertices pass
through (7.9 mm deep). On → 0 crossings, 2.0 mm minimum gap. Overhead ≈ 7 %.

## Known limitations / next steps
1. **Stretch isn't calibrated as well as bending.** The solver's stretch is mostly set by its iteration count; your
   measured stretch is honoured in the calibration test but garments still stretch about alike.
2. **Move test** poses joints rigidly (crease spots at the knee or elbow can show the body through for a frame),
   takes ~1 min, and there's no chair: sitting is sitting in the air.
3. **Tracing** needs a plain, contrasting background; a whole garment comes in as one piece to cut apart.
4. **Size runs** grade library patterns properly; from-scratch designs are scaled proportionally. The men's size table is a
   rule of thumb (the ASTM men's tables aren't freely available).
5. **Closures are modelled as seams.** Done-up buttons sew the two centre lines together (no real overlap
   or gaping between buttons); the stand and facing exist only on the cut pieces. Bands assume a closed
   opening unless their end seam is removed or given a closure.
6. **Pocket bags** are simulated, but at the tight hip the bag can still push through the front in a quick
   drape; the viewer draws it underneath. Welt pockets aren't there yet.
7. **Speed.** Full (accurate) drapes take 15–45 s on 2 CPU cores. Live mode is real-time on a GPU; its
   cloth-on-cloth collision is vertex-to-triangle only (no edge-edge), so thin layers can still cross in fast drags.
8. **The desktop app is ~500 MB unpacked** and isn't code-signed: Windows SmartScreen and macOS Gatekeeper warn on first run.
9. **Not yet:** grading rules per point (sizes still scale between the size table's measurements),
   photo-to-measurements, more poses and motion capture, seam puckering, real button overlap.

## Licence

Spunfection Studio is licensed under the Mozilla Public License 2.0 (see `LICENSE`). Bundled third-party
components keep their own licences, listed in `THIRD_PARTY_NOTICES.md`. Source: https://github.com/spunfectionLLC/Drape

© 2026 Spunfection LLC. Spunfection Studio is a trade mark of Spunfection LLC.
