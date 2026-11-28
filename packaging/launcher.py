"""Spunfection Studio as a desktop app: double-click, it opens in your browser.
(The entry point PyInstaller freezes; see packaging/drape.spec.)"""
import multiprocessing
import os
import sys
from pathlib import Path


def main():
    multiprocessing.freeze_support()           # the solver runs in a spawned worker process
    home = Path.home() / ".drape"
    os.environ.setdefault("NUMBA_CACHE_DIR", str(home / "numba_cache"))   # the app folder may be read-only
    os.environ.setdefault("DRAPE_SDF_CACHE", str(home / "sdf_cache"))
    home.mkdir(exist_ok=True)
    from drape.studio.server import serve
    port = int(os.environ.get("DRAPE_PORT", "8765"))
    share = "--share" in sys.argv or os.environ.get("DRAPE_SHARE") == "1"
    print(f"Spunfection Studio: http://127.0.0.1:{port}/  (close this window to quit)")
    serve(port, open_browser="--no-browser" not in sys.argv, host="0.0.0.0" if share else "127.0.0.1",
          https=share and "--http" not in sys.argv)


if __name__ == "__main__":
    main()
