"""Build the website: out/site/, a static folder for Cloudflare Pages (spunfection.studio).

The whole studio runs in the visitor's browser: the page and its scripts (the studio's
own static files), Python in a Web Worker (web/site/py_worker.js, Pyodide from the
jsDelivr CDN) running drape's code (drape_bundle.zip), and the drape on the graphics
card (live_springs.js). web/site/web_shim.js answers the studio's /api calls in the page.

    python tools/build_site.py            then test:  python -m http.server -d out/site 8000
    npx wrangler pages deploy out/site --project-name spunfection-studio
"""
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out" / "site"
STATIC = ROOT / "drape" / "studio" / "static"
MAX_FILE = 25 * 1024 * 1024        # Cloudflare Pages: 25 MiB per file
# A second guard against injected script (bug hunt 2026-11-25): only the site's own scripts and Pyodide
# from jsDelivr run; no inline script, no eval (WebAssembly only: 'wasm-unsafe-eval'). micropip fetches
# the wheels Pyodide doesn't ship (ezdxf) from PyPI. Inline style attributes are used throughout the page.
# The worker gets the same header (it applies to /*). AdSense, when it comes, needs its hosts added here.
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'wasm-unsafe-eval' https://cdn.jsdelivr.net/pyodide/",
    "worker-src 'self'",
    "connect-src 'self' https://cdn.jsdelivr.net https://pypi.org https://files.pythonhosted.org",
    "img-src 'self' data: blob:",
    "media-src 'self' blob:",
    "style-src 'self' 'unsafe-inline'",
    "font-src 'self' data:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


def bundle(path):
    """drape's Python code, data and the example measurements (no studio static files)."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted((ROOT / "drape").rglob("*")):
            rel = f.relative_to(ROOT)
            if f.is_dir() or "__pycache__" in rel.parts or "static" in rel.parts:
                continue
            if f.suffix in (".py", ".npz", ".md", ".json"):
                z.write(f, rel.as_posix())
        for f in sorted((ROOT / "measurements").glob("*.json")):
            z.write(f, f.relative_to(ROOT).as_posix())
        import re      # the version the page shows (server._version reads it: no pyproject.toml in the browser)
        z.writestr("drape/VERSION", re.search(r'(?m)^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8")).group(1))


def main(out=None):
    out = Path(out or OUT)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(STATIC, out, ignore=shutil.ignore_patterns("__pycache__"))
    html = (out / "index.html").read_text(encoding="utf-8")
    tag = '<script src="live_springs.js"></script>'
    assert html.count(tag) == 1
    html = html.replace(tag, '<script src="web_shim.js"></script>\n' + tag)   # before the studio's scripts
    (out / "index.html").write_text(html, encoding="utf-8")
    for f in ("py_worker.js", "web_shim.js"):
        shutil.copy(ROOT / "web" / "site" / f, out / f)
    bundle(out / "drape_bundle.zip")
    # each build's Python and worker get their own address, so a visitor's browser never keeps last build's copy
    import hashlib
    ver = hashlib.sha256((out / "drape_bundle.zip").read_bytes()).hexdigest()[:12]
    for f, old, new in (("py_worker.js", 'fetch("drape_bundle.zip")', f'fetch("drape_bundle.zip?v={ver}")'),
                        ("web_shim.js", 'new Worker("py_worker.js"', f'new Worker("py_worker.js?v={ver}"')):
        t = (out / f).read_text(encoding="utf-8")
        assert t.count(old) == 1, (f, old)
        (out / f).write_text(t.replace(old, new), encoding="utf-8")
    html = (out / "index.html").read_text(encoding="utf-8")
    (out / "index.html").write_text(html.replace('<script src="web_shim.js">', f'<script src="web_shim.js?v={ver}">'), encoding="utf-8")
    sys.path.insert(0, str(ROOT))
    from drape import brand
    for path in brand.PAGES:                     # /terms -> terms.html (Cloudflare Pages)
        (out / f"{path.strip('/')}.html").write_bytes(brand.placeholder_page(path))
    (out / "_headers").write_text(
        "/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n"
        f"  Content-Security-Policy: {CSP}\n"
        "/drape_bundle.zip\n  Cache-Control: public, max-age=3600\n", encoding="utf-8")
    big = [p for p in out.rglob("*") if p.is_file() and p.stat().st_size > MAX_FILE]
    assert not big, f"over Cloudflare's 25 MiB per file: {big}"
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"built {out} ({size / 1e6:.1f} MB, bundle {(out / 'drape_bundle.zip').stat().st_size / 1e6:.1f} MB)")
    return out


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
