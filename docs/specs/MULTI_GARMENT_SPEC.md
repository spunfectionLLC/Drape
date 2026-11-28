# Spec: Multi-garment projects (Spunfection Studio / drape)

*Received 2026-11-24 from Tyler. A dated record: leave it as written; what was built is in the commits,
CLAUDE.md and docs/KNOWN_ISSUES.md.*

## Goal

Let one project hold multiple garments (e.g. leggings + a dress). Each garment is stored separately, can be edited on its own, exported on its own, and shown together on the avatar in the 3D viewer. The whole project saves as one file.

## Before you start

- Read the codebase first and map every place that reads or writes "the current pattern" (pieces, seams, fabric assignments, sim setup, undo, save/load, export). That list is the core of this job.
- Don't change solver behavior except where Phase 4 says to.
- Work in phases. Each phase must leave the app fully working and shippable. Commit after each one.

---

## Data model

```
Project
  version: 2
  avatar: (existing avatar data)
  scene: (existing scene/camera/sim settings)
  garments: Garment[]
  activeGarmentId: string
  undo: single global history (see below)

Garment
  id: string (uuid)
  name: string
  color: string        // UI swatch color only
  layer: int           // 1 = closest to body; user-assigned, never auto-computed
  visible: bool        // shown in 3D
  frozen: bool         // excluded from sim, acts as a static collider
  pieces: Piece[]      // existing piece structure
  seams: Seam[]        // existing seam structure; may only reference pieces in THIS garment
  fabrics: ...         // existing per-piece fabric assignments, scoped to this garment
```

Rules:
- Piece and seam IDs are scoped to their garment. Two garments may both have a piece named "Front" without conflict.
- **Seams never cross garments.** A liner or lining belongs to the same garment as its shell.
- Each garment keeps its own fabric assignments.

## State management

- `activeGarmentId` lives in ONE shared store. The 2D editor, the fabric/properties panel, the 3D picker and the garment panel all subscribe to it. No component keeps its own copy of the selection.
- Every editing tool resolves its target via `project.garments[activeGarmentId]`. No global "current pattern" remains after Phase 1.
- Undo/redo: one global stack. Each entry records which garment it touched. Undoing an action on a non-active garment switches the selection to that garment so the change is visible.

---

## Phase 1: Internal refactor (no visible change)

1. Introduce `Project` and `Garment` as above.
2. Wrap the existing single pattern as `garments[0]` and set it active.
3. Route every read/write of the old global pattern through the active garment.
4. Remove the old global pattern state entirely.

**Done when:** the app looks and behaves exactly as before. Draping, editing, undo, save/load and export all work. Anything that breaks here was secretly depending on global state; fix it before moving on.

## Phase 2: File format v2 + migration

- Project file: `{ "version": 2, "avatar": ..., "scene": ..., "garments": [...], "activeGarmentId": ... }`.
- The loader detects old single-garment files (no `version` or `version: 1`) and converts them to a v2 project with one garment named "Garment 1", layer 1. Never write v1 again.
- Add a **single-garment file** format (`{ "type": "garment", "version": 2, "garment": {...} }`) for exporting and importing one garment into another project. On import, assign fresh IDs and put the garment on the next free layer.

**Done when:** alpha users' existing saves open correctly, and round-tripping save → load preserves everything.

## Phase 3: Garment panel UI

Merge the garment and fit/design tabs into a single combined design tab. Add a **Garments** panel docked at the top of the left side panel, above the existing tool and fabric settings. Make it collapsible.

Panel contents:
- Header: "Garments" label + **Add garment** button.
- One row per garment, sorted by layer: color swatch, name, layer badge (L1, L2…), eye toggle (`visible`), snowflake toggle (`frozen`).
- The active row is highlighted.
- Footer: **Export garment** and **Save project** buttons, plus a hint line: "Layer 1 is closest to the body. Frozen garments act as colliders."

Interactions:
- Click a row → make it active. The 2D editor shows only that garment's pieces, and the fabric/properties panel shows its values.
- Click cloth in the 3D viewer → select the owning garment.
- Drag rows to reorder → renumber `layer` to match the new order.
- Double-click the name → rename inline.
- Right-click a row → Rename, Duplicate, Delete (with confirm), Export garment.
- **Add garment** menu → New blank garment / Import garment file / Duplicate active garment. New garments go on top (highest layer) and become active.
- On narrow windows, collapse the panel into a dropdown selector showing the active garment.

3D viewer:
- Show all `visible` garments.
- Draw non-active garments slightly dimmed (e.g. reduced saturation or opacity) so the user can tell what they're editing.

## Phase 4: Layered simulation (stage 1: freeze-and-collide)

- When a sim runs, only garments that are `visible && !frozen` simulate.
- Frozen and visible garments are added to the collider set **as static triangle meshes**, using the same collision path the avatar body already uses.
- Add a configurable collision thickness for garment colliders (default ~1.5 mm) so the outer garment doesn't z-fight the inner one.
- Recommended workflow (surface it in the UI hint and docs): drape the inner garment → freeze it → drape the next layer.
- If multiple unfrozen garments are visible, simulate them together but **without cloth-to-cloth collision yet**. Each collides only with the body and frozen garments. Show a small non-blocking notice: "Freeze inner layers for best results."

**Done when:** leggings draped and frozen, then a dress draped over them, rests on the leggings with no visible interpenetration. Live mode stays near current fps when only one garment is unfrozen.

## Phase 5: Export

- **Save project**: v2 project file, all garments.
- **Export garment**: single-garment file (Phase 2 format).
- **Pattern export (PDF/DXF)**: per garment, defaulting to the active garment. Optionally "export all", producing one file per garment, named after it.
- **3D export**: an option for the combined outfit (all visible garments) or the active garment only.

## Later (not in this job): stage 2 cloth-to-cloth collision

Leave hooks but don't build yet:
- GPU spatial hash across all active garments' particles, with point–triangle repulsion (standard textbook approach, Bridson et al. 2002).
- Tangle resolution uses the user-assigned layer index: when interpenetrating, the higher layer is pushed outward.
- The stability-limited timestep must account for cloth-cloth contact stiffness.

---

## Design constraints (do not violate)

These keep the implementation away from claims we identified. Don't "improve" past them without checking with me.

1. **Layer order is user-assigned only.** Never compute or auto-sort layer order from garment distance to the body mesh.
2. **Layering is done by physical simulation** (outer cloth colliding with the inner garment's mesh). Never geometrically inflate, expand, or push garment meshes outward to resolve layering.
3. **Freezing is all-or-nothing per garment.** No per-vertex or per-region pin strength or "fix intensity" feature for user-selected areas.

---

## Acceptance checklist

- [ ] Old single-garment files open as one-garment projects
- [ ] Two garments can be created, named, reordered, hidden and frozen
- [ ] Selecting a garment in the panel or by clicking it in 3D keeps the 2D editor, fabric panel and 3D highlight in sync
- [ ] Undo works across garment switches
- [ ] Dress drapes over frozen leggings without interpenetration
- [ ] A garment exports and imports into a different project with fresh IDs
- [ ] Per-garment PDF/DXF pattern export works
- [ ] Project save → load round-trips with no data loss
- [ ] Live sim fps with one unfrozen garment is within ~10% of the pre-change build
