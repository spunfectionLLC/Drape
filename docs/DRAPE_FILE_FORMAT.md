# The `.drape` project file

A `.drape` file is one JSON document. It describes a whole Spunfection Studio project: the avatar's measurements and one or more garments. Each garment is made of flat pattern pieces, the seams that sew them together, and where each piece goes on the body. You open it with **File → Open** on spunfection.studio.

This document is enough to write a garment from scratch. A complete working example is [examples/a_line_skirt.drape](examples/a_line_skirt.drape): an A-line skirt with an elastic waist and a double-fold hem. It opens and drapes cleanly.

**Units.** Everything in a design is in **centimetres**, whatever `scene.units` says; `units` only changes how the page displays lengths.

**Coordinates.** On the pattern, **y points up**, as on paper with the hem at the bottom.

## 1. Top level

```json
{
  "format": "drape-project",
  "app": "Spunfection Studio",
  "version": 2,
  "name": "A-line skirt",
  "avatar": {"measurements": { ... }},
  "scene": {"units": "cm"},
  "garments": [ { ... } ],
  "activeGarmentId": "skirt-1"
}
```

### `avatar.measurements` (cm)

The avatar is built from these. Only `sex`, `height`, `chest`, `waist` and `hip` are needed; anything left out is filled in from the body's own proportions.

| key | meaning |
|---|---|
| `sex` | `"female"` or `"male"` |
| `height` | total height |
| `chest`, `waist`, `hip` | girths (round the body) |
| `shoulder_width` | across the back, shoulder point to shoulder point |
| `neck`, `upper_arm`, `wrist`, `thigh`, `ankle`, `underbust` | girths |
| `arm_length` | shoulder point to wrist |
| `inseam` | crotch to floor |
| `hand_length`, `hand_breadth`, `hand_girth`, `foot_length`, `foot_breadth` | for gloves and socks |

Every body is valid: any adult measurements work.

## 2. A garment

```json
{
  "id": "skirt-1",
  "name": "A-line skirt",
  "color": "#1f7a6d",
  "layer": 1,
  "visible": true,
  "frozen": false,
  "block": null,
  "choices": {},
  "params": {},
  "scratch": true,
  "fabric": "poplin",
  "print": "none",
  "printCm": 8,
  "design": { "format": 2, "pieces": [ ... ], "seams": [ ... ] }
}
```

- **`scratch: true`** means the garment is made from the pieces in `design`. Keep `block: null` for a garment made from scratch.
- **`id`**: letters, digits, `-` and `_` only. It must be unique in the file. `activeGarmentId` is the garment shown first.
- **`layer`**: 1 is next to the skin. A garment worn over another has a higher number.
- **`fabric`**: the whole garment's fabric, one of:

  | key | fabric |
  |---|---|
  | `jersey` | cotton jersey, a stretchy knit |
  | `poplin` | crisp shirt cotton |
  | `denim` | 12 oz denim |
  | `canvas` | cotton canvas, stiff |
  | `fleece` | polyester fleece |
  | `silk` | silk charmeuse, slippery and drapey |
  | `chiffon` | sheer and light |
  | `rib` | rib knit, very stretchy: cuffs and neckbands |
  | `lining` | slippery lining |
  | `flannel` | soft brushed cotton |

- **`print`** is the garment's look in 3D: `"none"` (plain), `"stripes"`, `"plaid"`, `"dots"` or `"gingham"`. `printCm` is the size of one repeat.

## 3. `design.pieces`: the pattern pieces

Each piece is a closed outline: a list of corners (`verts`) and one edge from each corner to the next.

```json
{
  "name": "front",
  "verts": [[-34, 0], [34, 0], [26, 60], [-26, 60]],
  "edges": [
    {"name": "hem",    "c1": null, "c2": null, "elastic": false, "hem": {"style": "double", "depth_cm": 2, "turn_cm": 1}},
    {"name": "side_r", "c1": null, "c2": null, "elastic": false},
    {"name": "waist",  "c1": null, "c2": null, "elastic": true},
    {"name": "side_l", "c1": null, "c2": null, "elastic": false}
  ],
  "shape": {"type": "custom"},
  "at": [0, 0],
  "role": "body",
  "place": {"landmark": "waist_front", "at": "top", "mode": "wrap", "rotate": 0, "offset_cm": 2}
}
```

### The outline

- **Edges follow the corners.** `edges[i]` runs from `verts[i]` to `verts[i+1]`, and the last edge closes back to `verts[0]`. So there are exactly as many edges as corners. A piece needs at least 3 corners.
- **Go counter-clockwise**, with the hem at the bottom: along the bottom from left to right, up the right side, back across the top, down the left side.
- **Keep the outline simple**: no edge crosses another, and there are no holes.
- **Names:** piece names are unique in the design. Edge names are unique within their piece. Use letters, digits and `_`.
- **Curves.** An edge is straight when `c1` and `c2` are `null`. For a curve, either:
  - give `c1` and `c2`, the two control points of a cubic Bézier from `verts[i]` to `verts[i+1]` (in cm), or
  - give `"pts"`: the full polyline in cm, from `verts[i]` to `verts[i+1]`, both ends included. `pts` wins over `c1`/`c2`.
- **Left and right.** On a front piece, +x is the right of the pattern as you look at the wearer. So the `_r` side seam of the front sews to the `_l` side seam of the back. A back piece's +x is to the right as you look at the wearer's back.
- **`shape`**: always `{"type": "custom"}` for a piece you write yourself.
- **`at`**: where the piece sits on the pattern board, in cm. It's only for display: lay the pieces out side by side so they don't overlap.

### Edge options

| key | meaning |
|---|---|
| `elastic: true` | the edge is gathered with elastic to fit the body: a waist, a cuff |
| `hem: {...}` | a hem turned up on this edge. `style` is `double`, `single`, `narrow`, `blind` or `casing`; `depth_cm` is the hem depth; `turn_cm` is the first turn-under. Only on an edge that isn't sewn to anything |
| `sa` | this edge's own seam allowance in cm. Leave it out for the default |

### Piece options

| key | meaning |
|---|---|
| `role` | `body`, `sleeve`, `hood`, `collar`, `cuff`, `waistband`, `pocket` or `other`. It sets the sewing order: body and sleeves first, then collars, cuffs and waistbands, then pockets |
| `fabric` | this piece's own fabric (a key from the table above). Leave it out to use the garment's |
| `interfacing` | `light`, `medium`, `knit` or `heavy`: a stiffening fused to the piece (collars, waistbands, facings) |
| `lining` | `{"fabric": "lining", "open": ["hem"]}`: the piece is lined. A copy is made in that fabric and held to the piece along every edge not listed in `open` |
| `look` | how the piece looks in 3D. `{"print": "plaid"}`, or `{"print": "none", "color": "#111111"}` for a solid colour. Optional: `"cm"`, the repeat size |
| `stage` | `1`, `2` or `3`: set the sewing order by hand. Leave it out normally |

### `place`: where the piece goes on the body

Pieces are wrapped round the body at a landmark, then sewn and draped by the simulation, so the placement only has to be roughly right.

| key | meaning |
|---|---|
| `landmark` | where it goes (list below) |
| `at` | which part of the piece goes on the landmark: `center`, `top`, `bottom`, `left` or `right` |
| `mode` | `wrap` (wrapped round the body there, the usual choice) or `flat` (laid flat on it) |
| `rotate` | degrees, normally 0 |
| `offset_cm` | the air gap to the skin when it starts, 0.5 to 3 |

**Landmarks:**
- body: `chest_front`, `chest_back`, `waist_front`, `waist_back`, `hip_front`, `hip_back`, `hip_right`, `hip_left`, `neck_front`, `neck_back`, `head_back`;
- arms: `upper_arm_right`, `upper_arm_left`, `forearm_right`, `forearm_left`;
- legs: `thigh_right`, `thigh_left`.

**A sleeve** wraps round an arm, crown on top, instead of using a landmark:

```json
"place": {"arm": 1, "top_cm": 58, "wrist": true, "offset_cm": 0.5}
```

- `arm: 1` is the arm on the front pattern's +x side, and `-1` the other.
- `top_cm` is the height of the sleeve's crown above its hem on the pattern, which is the sleeve piece's top y.
- `wrist: true` makes a long sleeve follow the forearm.
- Draft the sleeve with its hem along y = 0, the cap on top, and +x toward the front. Name the cap's two halves `cap_r` (front) and `cap_l` (back), and the underarm edges `underarm_r` and `underarm_l`. Sew `underarm_r` to `underarm_l` to close the sleeve.

**A piece sewn onto another one**, such as a patch pocket, a patch or an appliqué, is topstitched onto its host. It isn't sewn with `seams`:

```json
"place": {"on": "front", "pos": [-9, 38], "rotate": 0, "sewn": ["left", "bottom", "right"]}
```

- `on`: the host piece's name.
- Draft the pocket round its own (0, 0), for example a rectangle from (-6, -7) to (6, 7) with edges `bottom`, `right`, `top`, `left`.
- `pos`: where the pocket's (0, 0) sits on the host's pattern, in cm in the host's own coordinates. Keep the whole pocket at least 1 cm inside the host's outline.
- `rotate`: degrees.
- `sewn`: the pocket's edges that are stitched down. Leave out the opening, usually `top`. With no `sewn`, every edge except the top one is stitched.
- Give it `"role": "pocket"`. Add `"inside": true` for a pocket on the inside face, like a jacket's inner pocket.
- Don't add seams for a sewn-on piece's edges: `place.on` stitches them.

**A band round an opening**, such as a neckband, collar, cuff or waistband, goes along the edges it's sewn to:

```json
"place": {"loop": ["front.neck", "back.neck"], "dir": "up", "offset_cm": 0.5}
```

- `dir` is `up` (collar, neckband) or `down` (cuff, hem band).
- Draft the band as a rectangle: its sewn edges along y = 0, named `join_1`, `join_2` … one per loop edge, in order. Then `end_r` up the right, `top` across, and `end_l` down the left.
- Sew each `join_k` to its loop edge, and `end_r` to `end_l` to close the ring.
- A neckband or cuff in `rib` is cut about 85–90 % of the opening's length, so it stretches to fit. Give its seams the matching `ease`, as described below (0.18 for 85 %).

## 4. `design.seams`: what sews to what

```json
{"a": "front.side_r", "b": "back.side_l", "ease": 0}
```

- `a` and `b` are `"piece.edge"`. Each edge is sewn at most once; an unsewn edge is an opening (the hem, the neck, the armholes before sleeves go in).
- **Lengths must match.** Two sewn edges should be the same length. The page warns when they differ by more than a few millimetres.
- **`ease`** (0 or more) is how much longer the longer of the two edges is meant to be, as a fraction. Whichever edge is longer gets eased or gathered into the other.
  - `0.03`: a sleeve cap 3 % longer than its armhole, eased in.
  - `0.5`: a skirt gathered onto a bodice.
  - `0.18`: an opening 18 % longer than the rib band that stretches to fit it.
  - Leave it at `0` when the lengths match.
- **Direction.** `reverse: false` sews `a`'s start to `b`'s start; `true` sews `a`'s start to `b`'s end. Leave `reverse` out and the ends that are closer together on the body are sewn together, which is right for most seams. Set it when two edges run the same way round, such as a dart's two legs or a sleeve's underarm.
- **`closure`** makes the seam open and close: `{"type": "buttons", "count": 5, "size_mm": 15}`. `type` is `buttons`, `snaps`, `zipper` or `hook_loop`. Use it for a front opening or a zipper in a side seam.

### A dart

A dart is a V cut into the outline: two edges that meet at the dart's point, sewn to each other.

```json
{"a": "front.dart_a", "b": "front.dart_b", "ease": 0, "reverse": true}
```

## 5. Rules for a garment that sews and drapes well

1. **Draft to the measurements.** Each piece's width round the body adds up to the girth plus ease. For example, a skirt's front and back hip widths should add up to the hip girth plus 4–10 cm. Stretch fabrics (`jersey`, `rib`) can have less ease, even 0.
2. **Sewn edges match in length**, apart from deliberate `ease`.
3. **Every opening the body passes through is big enough**, or has a closure:
   - the neck opening is at least the head's girth (about 56 cm), unless it's stretchy or has a closure;
   - a waist with `elastic: true` can be smaller, since the elastic fits it;
   - armholes are about 40–48 cm round.
4. **Front and back:** put front pieces at `*_front` landmarks and back pieces at `*_back`, both with `"at": "top"` at the waist or chest so they hang down.
5. **Keep it symmetric** when the garment is: mirror the outline about x = 0 and use `_r` / `_l` edge names.
6. **Darts and curves:** a waist that's narrower than the hip needs darts or shaped side seams. A neckline or armhole is a curve, so use `pts` or Bézier controls.

## 6. A minimal checklist before saving

- [ ] `format` is `"drape-project"` and `version` is `2`. The garment has `scratch: true` and a `design` with `"format": 2`.
- [ ] Every piece has `name`, `verts`, `edges` (one per corner), `shape: {"type": "custom"}`, `at` and `place`.
- [ ] The outline is counter-clockwise and doesn't cross itself.
- [ ] Every seam names two existing edges, and no edge is sewn twice.
- [ ] Sewn edges match in length (or the seam has `ease`).
- [ ] The measurements are in cm, and so is every design number.
