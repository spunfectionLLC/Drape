# drape: the algorithms it uses

This lists every method drape uses: what it does, where the code is, and where the method comes
from.

How to read the "Source" column:
- **Published**: the method is from a paper or book, cited with its year. The older the citation,
  the stronger the prior art.
- **Standard**: textbook or industry practice, too common to have one author.
- **Ours**: drape's own idea or combination.

---

## 1. The cloth solver (`drape/springs.py`, `drape/cloth.py`)

The cloth is a triangle mesh of points with masses, joined by springs. Every frame is split into
substeps. In each substep: forces, then an implicit solve, then strain limit, cloth contact and body
contact (all as changes to velocity), then damping and the speed cap, then positions move by x += h·v.

| What | How | Source |
|---|---|---|
| Mass-spring cloth | Points with mass, springs along mesh edges (stretch and shear) | Published: Provot 1995, *Deformation constraints in a mass-spring model to describe rigid cloth behavior* (Graphics Interface) |
| Anisotropy | Each edge's stiffness depends on its direction on the pattern: softer across the grain (`weft_ratio`) and on the bias (`bias_ratio`) | Standard (woven/knit behaviour); ours in the details |
| Bending | Isometric bending energy: per interior edge, ½·k·s²·\|Σ Kᵢxᵢ\|², with cotangent weights K from the flat rest shape | Published: Bergou, Wardetzky, Harmon, Zorin, Grinspun 2006, *A quadratic bending model for inextensible surfaces* (SGP) |
| Time integration | Linearised backward Euler: (M + h²K)·Δv = h·(F + Mg − hKv), 40 substeps a frame | Published: Baraff & Witkin 1998, *Large steps in cloth simulation* (SIGGRAPH) |
| Solving the linear system | Conjugate gradients, matrix-free on the CPU, Jacobi preconditioner | Published: Hestenes & Stiefel 1952; Baraff & Witkin 1998 |
| Stiffness matrix kept positive | The compressed-spring term of K dropped | Published: Choi & Ko 2002, *Stable but responsive cloth* (SIGGRAPH), and Baraff & Witkin 1998 |
| Strain limit | An edge that would end the substep stretched past (1 + lock strain) has the stretching part of its ends' relative velocity removed, split by inverse mass | Published: Provot 1995 (the limit), applied as velocity impulses as in Bridson, Fedkiw & Anderson 2002 |
| Damping | Velocity scaled down a little each substep (more where cloth touches cloth) | Standard |
| Speed cap | No point faster than 3 m/s. The body's outward push goes first, sliding gets what's left. | Ours (a simple clamp) |
| Speed-based substeps | More substeps on fast frames, so a point can't jump through a layer between contact checks: nsub ≥ 2·v·k / (fps · safety · thickness) | Ours (`cloth.plan_substeps`); the idea of a CFL-style step limit is standard |
| Explicit fallback (tests only) | Symplectic Euler, substeps from the Gershgorin bound h·ω < 2 | Standard (Gershgorin 1931) |
| Deep-penetration safety net | A point more than 2 mm inside the body after a substep is moved back to the surface, and only its inward speed is dropped | Ours. **This is the one place positions are corrected directly, outside x += h·v.** It is rare (a grid error or a bone popping through), but mention it in the search. |
| Velocity-level rule | Positions change only by x += h·v. Nothing sets a velocity from a position difference. Predicted positions are read-only. | A design rule (see section 11). A test checks it (`tests/test_v19_velocity.py`). |

## 2. Contact and collision

| What | How | Source |
|---|---|---|
| Body contact | A point that would end the substep closer than the contact thickness to the skin gets just enough outward speed to end it at that thickness | Published: Bridson, Fedkiw & Anderson 2002, *Robust treatment of collisions, contact and friction for cloth animation* (SIGGRAPH) |
| Friction | Coulomb: the sliding speed is cut by μ times the normal speed change | Published: Bridson et al. 2002 |
| Cloth-on-cloth (point–triangle) | Repulsion impulses on (point, triangle) pairs tested at the predicted positions. The side a point must stay on comes from the frame-start positions. | Published: Bridson et al. 2002 |
| Cloth-on-cloth (edge–edge) | The same for pairs of edges sliding past each other (GPU) | Published: Bridson et al. 2002, section 7.2 |
| Splitting a push over a triangle | Each push is shared by the triangle's corners by inverse mass and barycentric weight | Published: Bridson et al. 2002 |
| Layers already overlapping | Eased apart over `SELF_TAU` seconds instead of in one substep; to half the thickness where the layers are squeezed against the body | Ours (a tuning of Bridson's repulsion) |
| Contact order | The body, then cloth-on-cloth; with a moving (posed) body, the skin once more at zero thickness, so a cloth push can't press a layer into a limb | Ours (a choice of order) |
| Finding contact pairs | A uniform grid spatial hash built by counting sort; each triangle is listed in every cell its margin-inflated bounding box touches; candidate pairs found once a frame | Published: Teschner et al. 2003, *Optimized spatial hashing for collision detection of deformable objects* (VMV); counting sort is standard |
| Candidate rebuilds (GPU) | The pair lists are rebuilt every few substeps when cloth moves fast, so the motion between rebuilds fits the margin | Ours |
| Skipping a point's own triangles | A point ignores triangles round itself (welded mesh); on the GPU, triangles in its own seam group within the thickness | Standard idea; the seam-group rule is ours |

## 3. The GPU version (`drape/studio/static/live_springs.js`, `drape/live.py`)

The same solver as section 1, in WebGPU shaders. It doesn't weld seams (section 4).

| What | How | Source |
|---|---|---|
| Matrix assembly | The implicit system stored as 3×3 blocks per (point, neighbour) pair in compressed rows; the bending part is constant and precomputed | Standard (block CSR) |
| Linear solver | Conjugate gradients in the Chronopoulos–Gear form (one global sum per iteration), block-Jacobi preconditioner, warm start from the last Δv | Published: Chronopoulos & Gear 1989 (J. Comput. Appl. Math.); Ghysels & Vanroose 2014 |
| Parallel updates without conflicts | Greedy graph colouring: edges in one batch share no point, so a batch updates in parallel | Published: Welsh & Powell 1967 (greedy colouring); standard in GPU cloth |
| Adding pushes in parallel | Fixed-point integer atomic adds, with a weight, divided by max(weight, 1) when gathered | Standard GPU technique |
| Speed cap, substeps, contacts | Same rules as the CPU (sections 1–2) | As above |

## 4. Sewing, welding and staged sewing (`drape/cloth.py`, `drape/stages.py`)

| What | How | Source |
|---|---|---|
| Sewing | Each seam is a set of point pairs; springs between them shrink their rest length to zero over the sewing time, with gravity off | **Virtual sewing with seam springs is common in garment CAD.** Published: Volino & Magnenat-Thalmann 2000, *Virtual Clothing*, and earlier work at MIRALab. Search this area. |
| Opening crumpled pieces | While sewing, soft springs across every fold (the flat distance between the two triangles' far corners) unfold pieces that start creased | Ours |
| Welding | When a seam closes, each pair of points is merged into one point (one continuous mesh); rest lengths are averaged, bending is rebuilt across the seam from the unfolded flat triangles | Ours in the details; merging vertices is standard |
| Elastic | Edges in a casing get shorter rest lengths (`freeform._shrink_band`), eased in while sewing, and pull with an elastic's stiffness (`ELASTIC_K`) | Ours |
| Topstitching (pockets) | One-sided springs from a point to a spot on another triangle, pulling only when pulled away | Ours |
| **Staged sewing** | Pieces sewn in stages: body first, then hoods, collars, cuffs and waistbands, then pockets. Later pieces are frozen until their stage. While a later stage sews, the already-sewn side gets only `ANCHOR_W` (0.01) of the seam force. | **Ours** (STAGED_SEWING_SPEC section 0): a piece's stage comes only from where it is placed, its role tag or the user's order, never from the seams; pieces are placed once and never re-arranged. A test checks the stage code for it. |
| Untangling | Cloth caught inside a body part (a sleeve through the arm) gets slack (rest lengths up 18%) so it balloons out and the contact pushes it to the right side, then the slack is taken back in | Ours. Related published work: Baraff, Witkin & Kass 2003, *Untangling cloth* (different method) |

## 5. The avatar (`drape/human.py`, `drape/measurements.py`, `drape/meshbody.py`, `drape/body.py`, `drape/pose.py`)

| What | How | Source |
|---|---|---|
| Body shape | The MakeHuman base mesh plus weighted morph targets (CC0 data, via MPFB2) | Published data and method: MakeHuman (Bastioni et al.); morph targets are standard |
| Fitting the body to measurements | Least squares over the morph-target weights, with bounds (SciPy `least_squares`, trust-region reflective) | Published: Branch, Coleman & Li 1999 (the solver); fitting shape weights to measurements is common |
| Tape measurements on the mesh | A girth is the perimeter of the convex hull of the cross-section (a tape bridges hollows); skin weights keep the arms out of torso girths | Standard tailoring practice; convex hull by Qhull (Barber, Dobkin & Huhdanpaa 1996) |
| Collision body (realistic) | A signed distance grid from the mesh: sign from the fast winding number (libigl), sampled trilinearly | Published: Barill, Dickson, Schmidt, Levin & Jacobson 2018, *Fast winding numbers for soups and clouds* (SIGGRAPH) |
| Collision body (no libigl) | Exact point–triangle distance against the nearest triangles (k-d tree); sign from the parity of a ray along +z | Standard (Jordan curve parity; Bentley 1975 k-d tree) |
| Simple mannequin | Elliptical torso sections plus capsules, joined by a smooth minimum | Standard SDF modelling (smooth min, e.g. Quilez) |
| Hands and feet | Proportions as fractions of height (adult averages) | Standard anthropometry |
| Posing (sit, walk, reach) | Linear blend skinning with MakeHuman's game-engine skeleton (CC0); the moving body is a series of distance grids (keyframes) blended frame by frame, as the union eased toward the next key | Published: Magnenat-Thalmann, Laperrière & Thalmann 1988 (skinning); the keyframe blending is ours |

## 6. Patterns and meshing (`drape/draft.py`, `drape/blocks.py`, `drape/freeform.py`, `drape/mesh2d.py`, `drape/pattern.py`, `drape/dedit.py`)

| What | How | Source |
|---|---|---|
| Drafting curves | Lines, Bézier curves, arcs, splines, Hermite curves, offsets, mirrors | Standard geometry |
| Pattern blocks (tee, skirts, dress, trousers) | Drafted from the avatar's measurements with ease and darts, the way patternmakers draft | Standard patternmaking (drafting textbooks) |
| Gloves and mittens | Two layers of the same outline, fingers fanned out, each tube half the finger girth plus ease | Standard glove construction; drafting from the hand is ours |
| Hems | The turn-up allowance cut on, its corners mirrored across the fold line | Standard patternmaking ("folding the hem corner") |
| Closures | Button stand, facing, buttonhole marks, zipper stop added to the pieces | Standard patternmaking |
| Shape edits | Cut away, join on, keep the overlap (boolean operations on outlines); join along a seam; layer copies | Standard (Shapely/GEOS boolean operations) |
| Split with a shape (2026-11-25) | Every piece a drawn shape overlaps is cut into the parts outside and inside it (the same boolean operations), all kept; the parts are sewn together along the shape's line, and seams it crossed are sewn again part to part (ends matched by height on the pattern; an unsplit partner edge is cut at the same fractions). Parts keep their piece's place on the body (`place.center_cm`, `span_cm`). The user draws the shape and presses Split: nothing is inferred | Ours, from standard 2D booleans. |
| Edge tools placed by clicking (2026-11-25) | Darts, pleats, gathers, hems, elastic, seam allowance, split: the tool picked, the spot clicked on an edge (projected onto the edge's polyline), mirrored onto the matching edge when Symmetric is on | Standard UI |
| Sleeve generator (2026-11-27) | `dedit.add_sleeve`: a set-in sleeve for the armhole edges the user clicks (front, then back). Each cap half is as long as its armhole edge plus the cap ease (smooth 3%, puff 25%), the cap height solved for that (`garments.solve_cap_height`, the tee's drafting); width from the upper arm plus the fit's ease; length a fraction of the arm, a long sleeve tapering to the wrist. Placed round the arm (`garments.arm_wrap`). The arm side and each seam's direction come from where the clicked armhole sits on the body | Standard patternmaking (sleeve cap drafted to the armhole); the placement is our existing arm wrap |
| Bands round an opening | Edges put in order round the opening by following the seams | Ours (simple graph walk) |
| Triangulating a piece | The outline kept exactly; inside, a jittered triangular grid; Delaunay triangulation (Qhull); missed outline edges restored by edge flips; triangles outside dropped | Published: Delaunay 1934; Lawson 1977 and Sloan 1993 (edge flips); Qhull 1996 |
| Placing pieces on the body | "Wrap": an isometric wrap onto a cylinder round the body part under the anchor (lengths kept exactly). "Flat": laid on the tangent plane at the anchor. Points inside the body pushed out. | Standard geometry |
| Seam direction | Left unset, a seam's direction is chosen so the ends closer together sew together | Ours |
| Seam checks | Length match (with ease), twisted-seam detection, corner truing (angles adding to 180°) | Standard patternmaking ("walking the seams") |
| Seam marks | Seam numbers and colours; notches 40% along (single front, double back); match dots | Standard notch convention; the 40% rule is ours |
| Size runs | Pattern-library garments redrafted per size (ASTM D5585 women's table); free-form designs graded proportionally | Standard grading |

## 7. Fabrics and calibration (`drape/fabrics.py`, `drape/calibrate.py`, `drape/tester.py`)

| What | How | Source |
|---|---|---|
| Fabric presets | Density, stretch and bending stiffness, anisotropy, lock strain, thickness, friction, damping | Published fabric data (typical weights and bending lengths) |
| Bending from bending length | The cantilever test run in the simulator; stiffness found by bisection so the tip reaches the 41.5° line at 2c | Published: Peirce 1930 (the cantilever, B = w·c³); ASTM D1388 |
| My fabrics | A droop and a stretch test on the kitchen table, matched in the simulator by bisection on a log scale | Ours (the test design); bisection is standard |
| Fabric tester (hardware) | A load cell and a potentiometer; stiffness fitted to the force–extension curve by least squares, along, across and on the bias | Standard tensile testing (ASTM-style); the kit is ours |
| Interfacing | Fused layers combined like springs in parallel; bending doubled for a laminate | Standard (laminate approximation) |

## 8. Fit analysis (`drape/fitcheck.py`, `drape/explain.py`)

| What | How | Source |
|---|---|---|
| Ease report | Garment girth minus body girth at each girth line. The garment's girth comes from the drafting (body measurement + ease parameter, as drafted) before a drape, and from a tape round the draped 3D mesh (convex hull of its cross-section) after one; never from adding up 2D pattern lengths across pieces (changed 2026-11-20) | Standard |
| Strain map | Each edge's strain shown as colour | Standard |
| "What's wrong here?" | Around a tapped point, strain split into along-grain, across-grain and bias parts, mapped to plain-language fitting problems and the setting to change | Ours |
| Pose advice | "Sitting: pulling at the hips" from strain while posed | Ours |

## 9. Production outputs

| What | How | Source |
|---|---|---|
| Cutting layout and yardage (`layout.py`) | Pieces rasterised at 5 mm and placed bottom-left on an occupancy grid; every offset tested at once with an FFT convolution; grain kept along the fabric, 180° turns only | Published: Baker, Coffman & Rivest 1980 (bottom-left), Jakobs 1996; FFT collision tests are standard |
| Laser nesting (`nest.py`) | The same layout, sheet by sheet on the laser bed, one DXF for LightBurn | As above |
| DXF export | Cut line, sew line, notches, grain, text on layers | Standard file format |
| DXF-AAMA export | Pieces as blocks with the AAMA layer numbers | Published standard: ASTM D6673 |
| Print-at-home PDF | Tiled at true scale with page labels, alignment marks and a test square; projector PDF | Standard practice |
| Tech pack, cut list, costing, instructions | Points of measure on the drape, bill of materials, Etsy fees, sewing order (darts, shoulders, sleeves, sides, finishing, hems) | Standard industry documents |
| glTF and Blender render | The drape as a .glb plus a Blender script | Standard file format |

## 10. Import, tracing and rendering

| What | How | Source |
|---|---|---|
| DXF import (`importer.py`) | Closed outlines joined end to end; nested outlines dropped (cut line round sew line); pieces named from their text; edges split at corners | Standard |
| Trace from a photo (`trace.py`) | Scale from two tapped points; background colour from the border; Otsu threshold on the colour distance; largest connected blob; contour by marching squares; simplified by Douglas–Peucker; split at sharp corners | Published: Otsu 1979; Lorensen & Cline 1987 (marching cubes, the 2D form); Douglas & Peucker 1973 |
| Software renderer (`render.py`) | z-buffer rasteriser, Lambert shading | Published: Catmull 1974 (z-buffer); Lambert 1760 |
| 3D viewer (`viewer.py`) | Plain WebGL, meshes embedded as int16 | Standard |
| Seam and topstitch lines on the drape (`stitches.py`) | Placed on the flat pattern, carried onto the drape by barycentric coordinates | Standard |

## 11. Removed, and two design rules

- **XPBD (extended position-based dynamics)** was the old solver: constraint projection with
  Lagrange multipliers. It was removed in commit `4ba93db` (`solver.py`, `live.js`, `--solver xpbd`
  deleted). The springs solver replaced it.
- **Velocity level:** springs.py never projects positions onto constraints. Everything except
  x += h·v (and the deep-penetration net, section 1) works on velocities. The spec is
  docs/specs/SPRING_VELOCITY_LEVEL_SPEC.md; `tests/test_v19_velocity.py` checks it, including a source grep
  for `_solve_*`, Lagrange multipliers and compliance projection.
- **Sewing order from placement:** stages come only from placement, role or the user's order, never
  from the seams; pieces are never re-arranged (section 4). The spec is docs/specs/STAGED_SEWING_SPEC.md,
  section 0; a test checks the stage code.

## 12. Third-party code and data

The full list is in THIRD_PARTY_NOTICES.md. The main ones: NumPy, SciPy (Qhull), Numba,
scikit-image, Shapely (GEOS), libigl, ezdxf, Pillow, imageio, matplotlib, cryptography, and the
MakeHuman / MPFB2 assets (CC0). The Triangle library was removed (its licence forbids commercial use).
