"""Numba when it's there (desktop: fast), plain Python when it isn't (a web
browser through Pyodide, where the cloth solver runs on the GPU instead)."""
try:
    from numba import njit, prange
    HAVE_NUMBA = True
except ImportError:          # pragma: no cover - exercised in the browser build
    HAVE_NUMBA = False
    prange = range

    def njit(*args, **kwargs):
        if len(args) == 1 and callable(args[0]) and not kwargs:
            f = args[0]
            f.py_func = f
            return f

        def wrap(f):
            f.py_func = f
            return f
        return wrap
