# Third-party software and data in Spunfection Studio

Spunfection Studio is made by Spunfection LLC; its code package is named `drape`.

Everything Spunfection Studio bundles or depends on can be used commercially. Keep this file
(and the licence files the packages install) with any copy you distribute.

| Component | Used for | Licence |
|---|---|---|
| MakeHuman base mesh, targets and rig (`drape/data`) | the avatars | CC0 1.0 (public domain); see `drape/data/MAKEHUMAN_LICENSE_CC0.md` |
| NumPy | arrays | BSD-3-Clause |
| SciPy (with Qhull) | Delaunay meshing, fitting, distance grids | BSD-3-Clause; Qhull licence (free, commercial use allowed) |
| Numba | the CPU cloth solver | BSD-2-Clause |
| Shapely (with GEOS) | pattern geometry | BSD-3-Clause; GEOS is LGPL-2.1, used as a shared library |
| scikit-image | contour tracing | BSD-3-Clause |
| libigl (Python bindings) | signed distance to the body | MPL-2.0 |
| ezdxf | DXF / DXF-AAMA export | MIT |
| ReportLab | PDF patterns and tech packs | BSD |
| Pillow | images | MIT-CMU |
| imageio | images and video | BSD-2-Clause |
| matplotlib | charts | matplotlib licence (PSF-based, permissive) |
| PyInstaller (desktop build only) | packaging | GPL-2.0 with the bootloader exception, which allows commercial apps |

Meshing used to use J. R. Shewchuk's Triangle, whose licence does not allow
commercial distribution without the author's permission. It was replaced in
v1.2.1 by `drape/mesh2d.py` (numpy, SciPy, Shapely only).

The women's size table in `drape/sizerun.py` lists body measurements published in
ASTM D5585-95. The men's table is Spunfection Studio's own rule of thumb.

## Methods the cloth solvers follow (published work, no code taken)

- Mass-spring solver (`drape/springs.py`): X. Provot, "Deformation constraints in a
  mass-spring model to describe rigid cloth behavior", Graphics Interface 1995
  (springs, explicit integration, strain limiting).
- Implicit integration in the mass-spring solver (the default): D. Baraff and A. Witkin,
  "Large steps in cloth simulation", SIGGRAPH 1998 (linearised backward Euler solved by
  conjugate gradients).
- Contacts, friction and strain limiting as velocity impulses: R. Bridson, R. Fedkiw and
  J. Anderson, "Robust treatment of collisions, contact and friction for cloth animation",
  SIGGRAPH 2002.
- The springs solver on the GPU (`studio/static/live_springs.js`): conjugate gradients in the
  form of A. T. Chronopoulos and C. W. Gear, "s-step iterative methods for symmetric linear
  systems", J. Comput. Appl. Math. 25, 1989 (as written up by P. Ghysels and W. Vanroose,
  "Hiding global synchronization latency in the preconditioned Conjugate Gradient
  algorithm", Parallel Computing 40, 2014, algorithm 2), with a block-Jacobi preconditioner.
- Design rules (specs in `docs/specs/`): the springs solver works at velocity level
  (SPRING_VELOCITY_LEVEL_SPEC.md), and the sewing order comes from placement, never from the
  seams (STAGED_SEWING_SPEC.md). The methods above were chosen as old, published work.
- Bending in both solvers: M. Bergou, M. Wardetzky, D. Harmon, D. Zorin, E. Grinspun,
  "A quadratic bending model for inextensible surfaces", Eurographics SGP 2006
  (isometric bending).
