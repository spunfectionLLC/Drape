# Technical disclosure: AI-assisted garment design with a builder and critic loop on simulated drapes

**Published by:** Spunfection LLC (Spunfection Studio™, https://spunfection.studio)
**Date of first publication:** 2026-11-28
**Status:** public technical disclosure, released so that anyone may use these methods. The open-source code is published under the project's licence.

---

## 1. Summary

This document describes a system for designing sewable garments from a written description:

1. **A language model ("builder") writes a structured garment design file.** The file holds flat pattern pieces, seams, placement on a body, fabric and appearance. The pieces are drafted to a specific person's body measurements.
2. **A cloth simulation** sews the pieces together and drapes them on a 3D avatar of that person. It runs inside the user's web browser.
3. **Renders from several viewpoints, plus numeric fit and construction metrics,** are given to a second model ("critic"), which judges the garment against the request and returns specific corrections.
4. **The builder applies the corrections** and the cycle repeats, up to a set number of rounds or until the critic accepts the garment.
5. **The user sees every version,** picks one, and gets printable patterns, cutting layouts and sewing instructions.

The aim is to let someone with no patternmaking training get a garment that fits their body and can actually be sewn.

## 2. The design file the models write

The builder doesn't draw images or meshes. It writes a JSON project file in a fixed, documented format: `DRAPE_FILE_FORMAT.md` in this repository, with an example in `examples/a_line_skirt.drape`. In outline:

- **Avatar measurements** in centimetres: sex, height, chest, waist, hip, and optionally shoulder width, neck, upper arm, wrist, thigh, ankle, underbust, arm length, inseam, and hand and foot measurements.
- **Garments**, each with an id, layer number (1 is next to the skin), fabric key, and print or colour.
- **Pattern pieces**, each a closed counter-clockwise outline in centimetres (y up, hem at the bottom):
  - corners and one edge per corner; edges are straight, cubic Bézier, or explicit polylines;
  - edge options: elastic, hem style and depth, seam allowance;
  - piece options: role (body, sleeve, hood, collar, cuff, waistband, pocket), fabric, interfacing, lining (with edges left open), appearance, and sewing stage;
  - a placement: a body landmark, which part of the piece sits on it, wrap or flat, and the starting gap to the skin. Sleeves are placed by arm; bands by the loop of edges they're sewn around.
- **Seams**, each joining two named edges, with an ease fraction (for gathering or for a stretch band cut shorter), an optional direction flag, and optional closures (buttons, snaps, zipper, hook-and-loop).

Because the output is this structured file, every design can be checked by plain geometry before any simulation:
- the outline is closed and doesn't cross itself;
- every seam joins two existing edges, each edge sewn at most once;
- sewn edge lengths match, apart from the stated ease;
- openings the body passes through are large enough, or have a closure;
- widths at each girth line exceed the body measurement plus ease.

A design that fails these checks goes back to the builder with the failures listed, before any rendering.

## 3. Builder

**Input:**
- the user's request in plain language (for example, "a black, gothic, knee-length A-line dress with a hood, lined in flannel");
- the wearer's measurements, or a preset body;
- the file format specification and one or more example files;
- drafting rules:
  - draft to the measurements plus ease;
  - match seam lengths;
  - curve necklines and armholes;
  - mirror symmetric pieces;
  - size openings for the head and limbs;
  - place front pieces at front landmarks and back pieces at back landmarks.

**Working method**, which the builder is told to follow:
1. Plan in text first: each piece, its key dimensions worked out from the measurements with the arithmetic shown, every seam, and every opening.
2. Draft each outline.
3. Compute both lengths of every seam and adjust or add ease.
4. Place the pieces on the body and lay them out on the pattern board without overlaps.
5. Run the checklist, then output the file.

**On later rounds,** the builder receives its previous file and the critic's corrections, and outputs either a revised file or a list of edits ("move vertex 4 of `front` up 3 cm", "change `hood_a.cb` to a curve with controls …", "add a dart"). Edit lists keep unaffected parts of the design unchanged between rounds.

**Variations:**
- the builder may instead fill in parameters of an existing drafted garment (garment type, lengths, widths, neckline depth, sleeve style, closures) rather than writing outlines from scratch;
- several builder drafts may be produced in parallel and the critic asked to rank them;
- the builder may ask the user a clarifying question before drafting when the request is ambiguous.

## 4. Simulation and observation

The design is loaded into the cloth simulator in the user's browser:
- pieces are placed around the avatar;
- seams are sewn closed;
- the garment drapes under gravity;
- body contact and cloth-on-cloth contact are handled;
- pieces may be sewn in stages: body pieces first, then hoods, collars, cuffs and waistbands, then pockets.

When the drape settles, the browser produces:

**Renders**, at a fixed resolution, with a plain background and the same lighting each time:
- front, back, left side, right side, and front three-quarter;
- optionally a close-up of any region the critic asked about in the previous round;
- a strain ("fit map") view coloured by fabric stretch.

**Fit metrics:**
- stretch percentiles (95th and 99th) and maximum;
- the number of cloth points inside the body, and the deepest penetration;
- distance to the skin;
- seam gap after sewing;
- remaining motion (to confirm it settled);
- per-region tightness (neck and shoulders, upper chest and armholes, bust, waist, hips, arms, thighs) in plain words;
- garment length from the floor at centre front and centre back, and hem level difference (for high-low hems);
- neckline depth and width, armhole circumference, opening sizes;
- ease at each girth line (garment girth measured on the draped mesh minus body girth).

**Construction metrics** (from the file, not the drape):
- seam-length mismatches;
- hems on curved edges whose turned allowance would have to stretch more than the fabric allows;
- the number of pieces and seams, as a measure of sewing difficulty;
- fabric yardage.

The renders and metrics go to the critic. The design file and the simulation stay with the user unless they choose otherwise.

## 5. Critic

**Input:**
- the original request;
- the measurements;
- the renders;
- the fit and construction metrics;
- the current design file;
- a rubric with separate scores for:
  - **match to the request:** silhouette, length, neckline, sleeves, hood, colour and print, style words such as "gothic" or "relaxed";
  - **fit:** tight or loose areas, the garment riding up, pieces off-centre on the body, hems uneven where they should be level;
  - **construction:** seams that won't sew, openings too small, hems that won't fold flat, missing closures;
  - **physical plausibility:** cloth inside the body, twisted seams, linings showing through, pieces caught on the wrong side.

**Output:**
- scores per category;
- **pass or fail;**
- a short list of **specific, actionable corrections**, each with a location and amount where possible ("hem is 15 cm too low; raise the front and back by 15 cm", "the hood forms a peak; replace the straight crown seam with an outward curve of about 2 cm", "the shoulders are empty because the bodice is placed too low; place it at the neck landmark").

The critic is told to rely on the numeric metrics for fit, and on the images for style, proportion and visible faults.

**Variations:**
- **several specialised critics** (fit, style, sewability) whose corrections are merged, with conflicts resolved by fixed priority: physical problems first, then construction, then fit, then style;
- **comparison against reference images** supplied by the user (a sketch or photo of the desired garment), in addition to the text;
- **comparison between two candidate designs,** choosing the better one;
- the **user's own comments** on a round ("make it longer", "less boxy") added to the critic's corrections.

## 6. Loop control

- **A round is:** builder output → geometric checks → simulation → renders and metrics → critic.
- **Stop when:** the critic passes the design; a maximum number of rounds is reached (typically 3); or the critic's scores stop improving for two rounds.
- **Every round's design is kept** as a version, with its renders and scores. The user can open, compare and choose any version, or continue from it with their own edits in the editor.
- **Hard per-user and per-request limits** on rounds and model calls are enforced by the server.

## 7. System layout

- **The browser app is open source:** pattern editor, simulator, renders, metrics, exports.
- **A small server API** receives requests from logged-in users. It:
  - checks the account, plan and quota;
  - calls the language models for the builder and critic;
  - validates every returned design file against the format (allowed keys, value ranges, identifier formats, text escaped before display) before sending it to the browser;
  - returns it.
- **The simulation runs in the user's browser,** not on the server. Only text, the design file, renders and metrics are sent to the server, and measurements only with the user's consent.
- **The server can switch between model providers** without changes to the app.

## 8. Charging

- Per completed design (up to a set number of rounds), per round, or through credits.
- A subscription that includes a monthly number of designs, with credit packs for more.
- A small free allowance so users can try it.

## 9. Outputs after a design is chosen

From the chosen design file, the app produces:
- print-at-home tiled PDFs (Letter or A4) with a test square;
- a projector file;
- a cutting layout with fabric yardage;
- DXF and DXF-AAMA files;
- a tech pack;
- step-by-step sewing instructions in construction order (darts, shoulders, sleeves, sides, finishing, hems), including facings, linings with tacks, and closures;
- 3D exports.

The user can hand the design and its documents to a sewist to have it made.

## 10. Related techniques disclosed here

1. **Body weight as a volume target.** Optionally, the avatar fitted to the user's measurements can also be fitted to their weight. The avatar mesh's enclosed volume multiplied by an average body density (about 1.0–1.06 g/cm³) is added as one more target in the least-squares fit of the body-shape parameters, alongside the tape measurements.
2. **Text-to-fabric choice.** The builder may map words in the request ("drapey", "structured", "cosy", "stretchy") to fabric presets and interfacing from the app's fabric list, and the critic may correct the choice when the drape looks wrong for the request (too stiff, too limp).
3. **Lining and layering in AI designs.** The builder may line pieces by naming a lining fabric and the edges left open, and may stack garments in layers (layer 1 next to the skin), with inner layers draped and frozen before outer ones.
4. **Safety of AI-written files.** Every file from a model is treated as untrusted input:
   - names, ids and colours are checked against strict formats and escaped wherever displayed;
   - numbers are clamped to sane ranges;
   - unknown keys are dropped;
   - files that fail are rejected with the reasons sent back to the builder.

## 11. Sketching corrections over the render

*Added 2026-11-28 (second revision of this document).*

The user can ask for changes by drawing them instead of describing them. The drawing goes to the models as a reference alongside the text.

### 11.1 What the user draws on

- **Over a 3D render:** a still of the draped garment on the avatar from any viewpoint the user turns to. The camera is recorded with the drawing: position, direction, field of view and image size.
- **Over a 2D sketch:** a flat front or back drawing of the garment (a technical flat) made from the design, or a blank body outline (a croquis) from the avatar's silhouette, for drawing a new garment from nothing.
- **Over the pattern pieces:** the flat pieces as shown in the editor.
- **Over the user's own image:** a photo or hand sketch, placed beside or behind the render for reference.

### 11.2 The drawing tools

- **Freehand strokes**, in colours with fixed meanings:
  - red: cut away or remove;
  - blue: add or extend;
  - green: a new line (a seam, a neckline, a hem);
  - black: notes and arrows.
- **Arrows** for "move this here" or "longer / shorter".
- **Circles** around an area meaning "look at this".
- **Filled areas** meaning "this part in another fabric or look".
- **Short text notes** placed on the drawing ("more gathered", "pocket here", "like this but flared").
- **Undo, erase, and layers**, so the clean render and the markings stay separate.

### 11.3 What the models receive

- The clean render and the marked-up version.
- The strokes as data: each stroke's type, colour, points in image coordinates, and any text.
- The camera, so a point on the image can be turned into a ray into the 3D scene.
- **Strokes carried onto the garment.** Each stroke point drawn over the garment is projected:
  - cast a ray from the camera through the pixel;
  - find the triangle of the draped mesh it hits;
  - take the point's barycentric coordinates in that triangle;
  - from those, find the matching point on the flat pattern piece the triangle belongs to.

  A drawn new hem line therefore becomes a curve in each pattern piece's own coordinates, and a circled area becomes a set of pieces and regions. Points that miss the garment are kept as offsets from the nearest garment edge or from the body, so "extend down to here" keeps its length.
- **For strokes on a 2D sketch or croquis:** the flat drawing is generated from known views of the avatar and the design, so its coordinates map to the body's landmarks and to the pieces in the same way.
- **Lengths in centimetres:** measured from the projected strokes, for example "the new hem is 12 cm above the current one at centre front".

### 11.4 How the builder uses them

- The builder reads each stroke with its meaning and turns it into edits on the design file. For example:
  - a green line across the bodice becomes a split of the front piece along that curve, with a seam;
  - a blue outline below the hem becomes a longer hem, following the drawn shape;
  - red over a sleeve becomes a shorter sleeve or no sleeve;
  - a filled area becomes a piece split with its own look or fabric;
  - an arrow on the neckline becomes a neckline lowered by the arrow's length.
- Before applying them, the builder states its reading of the drawing in plain words, one line per stroke ("I read this as: lower the front neckline by 4 cm and make it a V"). The user confirms or corrects each line.
- The critic gets the same drawing on the next round, rendered from the same camera with the strokes laid over the new drape, so it can check that every stroke was carried out and nothing else changed.

### 11.5 Variations

- Drawing on several views at once (front, back, side); the projected strokes are merged on the pattern pieces.
- A stroke the projection can't place (it misses the garment and the body) is asked about instead of guessed.
- The user's strokes kept with each version, so the history shows what was asked and what was done.
- The same drawing tools used without any model: the strokes become guide lines on the pattern pieces for the user to edit by hand.

---

*This disclosure describes methods only. Spunfection LLC publishes it so that these methods remain free for anyone to use.*
