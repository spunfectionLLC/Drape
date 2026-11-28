"""drape: open-source 2D pattern -> 3D garment draping."""
# --- Numba cache keyed to the package's source -------------------------------
# Numba caches each function by its own file's timestamp. springs.py inlines the
# body SDF from body.py into its compiled code, so editing body.py left a stale
# solver in the cache (it bit twice during development). Keying the cache
# directory on a hash of *all* package sources makes any edit start clean.
import hashlib as _hashlib
import os as _os
import shutil as _shutil
from pathlib import Path as _Path

try:
    import numba as _numba
except ImportError:          # a web browser (Pyodide): no numba, nothing to cache
    _numba = None

_pkg = _Path(__file__).parent
_h = _hashlib.sha1()
for _f in sorted(_pkg.glob("*.py")):
    _h.update(_f.name.encode()); _h.update(_f.read_bytes())
SOURCE_HASH = _h.hexdigest()[:12]
_root = _Path(_os.environ.get("DRAPE_CACHE_ROOT", _pkg.parent / ".numba_cache"))
if _numba is not None:
    _numba.config.CACHE_DIR = str(_root / SOURCE_HASH)
try:  # keep only the current cache
    for _d in _root.glob("*"):
        if _d.is_dir() and _d.name != SOURCE_HASH:
            _shutil.rmtree(_d, ignore_errors=True)
except OSError:
    pass

from .pattern import Panel, Seam, bezier, line, build_garment, cylinder_wrap  # noqa: E402
from .body import Body  # noqa: E402
from .cloth import Fabric  # noqa: E402
from .springs import SpringSimulator  # noqa: E402
Simulator = SpringSimulator   # the cloth solver (mass-spring, implicit: springs.py)
