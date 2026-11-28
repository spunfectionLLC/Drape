"""The website (docs/WEBSITE.md): the studio entirely in the browser, for Cloudflare Pages.
Python in a Web Worker (Pyodide) answers the studio's /api calls (drape/webapi.py, through
web/site/web_shim.js); Drape it runs on the GPU in the page. The full run in Chrome needs
DRAPE_CHROME (a Chrome with WebGPU) and downloads Pyodide from its CDN."""
import functools
import http.server
import os
import re
import threading
import time
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "drape" / "studio" / "server.py").read_text(encoding="utf-8")
WEBAPI = (ROOT / "drape" / "webapi.py").read_text(encoding="utf-8")


def test_the_web_api_answers_every_route_the_server_has():
    routes = set(re.findall(r'self\.path == "(/api/[a-z_]+)"', SERVER))
    prefixes = set(re.findall(r'self\.path\.startswith\("(/api/[a-z_]+/)"\)', SERVER))
    assert len(routes) > 15
    for r in routes:
        assert f'"{r}"' in WEBAPI, r
    for r in prefixes:
        assert f'path.startswith("{r}")' in WEBAPI, r


def test_the_desktop_drape_is_the_same_job_split_in_two():
    """_drape_worker = _drape_job run straight through: prepare, step on the CPU, finish."""
    from drape.studio import server as S
    import inspect
    assert inspect.isgeneratorfunction(S._drape_job)
    src = inspect.getsource(S._drape_worker)
    assert "_drape_job(" in src and "next(job, None)" in src
    assert "for f in range(0 if stepped_elsewhere else n):" in inspect.getsource(S._drape_job)


def _headers(site):
    """Cloudflare's _headers file as [(path pattern, {name: value})]."""
    rules = []
    for line in (site / "_headers").read_text(encoding="utf-8").splitlines():
        if line and not line[0].isspace():
            rules.append((line.strip(), {}))
        elif line.strip():
            k, v = line.strip().split(":", 1)
            rules[-1][1][k.strip()] = v.strip()
    return rules


def _site_handler(site):
    """A local server that sends the site's _headers as Cloudflare does (so the CSP is tested too)."""
    rules = _headers(site)

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(site), **k)

        def log_message(self, *a):
            pass

        def end_headers(self):
            path = self.path.split("?")[0]
            for pat, hs in rules:
                if pat == path or (pat.endswith("*") and path.startswith(pat[:-1])):
                    for k, v in hs.items():
                        self.send_header(k, v)
            super().end_headers()

        def guess_type(self, path):
            return "text/javascript" if str(path).endswith((".js", ".mjs")) else super().guess_type(path)
    return H


def test_the_site_has_a_content_security_policy(site):
    csp = dict(_headers(site))["/*"]["Content-Security-Policy"]
    d = {x.split()[0]: x.split()[1:] for x in csp.split("; ")}
    assert "'unsafe-inline'" not in d["script-src"] and "'unsafe-eval'" not in d["script-src"]
    assert "*" not in " ".join(d["script-src"]) and d["object-src"] == ["'none'"]
    assert d["frame-ancestors"] == ["'none'"] and d["base-uri"] == ["'self'"]
    html = (site / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html), "an inline script would be blocked"
    js = "".join(p.read_text(encoding="utf-8") for p in (site / "js").glob("*.js")) + html
    assert not re.search(r"\son(click|change|input|load|error|submit)=", js), "inline handlers would be blocked"


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    import build_site
    return build_site.main(tmp_path_factory.mktemp("site") / "site")


def test_the_site_is_static_and_complete(site):
    for f in ("index.html", "web_shim.js", "py_worker.js", "live_springs.js", "drape_bundle.zip", "_headers",
              "css/studio.css", "js/01_core.js", "js/18_boot.js", "terms.html", "privacy.html"):
        assert (site / f).is_file(), f
    html = (site / "index.html").read_text(encoding="utf-8")
    assert html.index('src="web_shim.js?v=') < html.index('src="live_springs.js"') < html.index('src="js/01_core.js"')
    names = zipfile.ZipFile(site / "drape_bundle.zip").namelist()
    assert "drape/webapi.py" in names and "drape/data/makehuman.npz" in names and "measurements/female_M.json" in names
    assert not any("/static/" in n for n in names)
    assert all(p.stat().st_size < 25 * 1024 * 1024 for p in site.rglob("*") if p.is_file())   # Cloudflare's limit
    assert 'type: "module"' in (site / "web_shim.js").read_text(encoding="utf-8")


def test_poses_say_they_are_desktop_only_on_the_web():
    js = (ROOT / "drape" / "studio" / "static" / "js" / "05_preview.js").read_text(encoding="utf-8")
    assert "if (ST.init && ST.init.web)" in js and "Move tests" in js


@pytest.mark.slow
@pytest.mark.skipif(not os.environ.get("DRAPE_CHROME"), reason="needs DRAPE_CHROME (a Chrome with WebGPU)")
def test_the_website_drapes_a_tee_and_exports_in_the_browser(site):
    pw = pytest.importorskip("playwright.sync_api")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _site_handler(site))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=os.environ["DRAPE_CHROME"])
        pg = b.new_page(viewport={"width": 1400, "height": 900})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: "Content Security Policy" in m.text and errors.append(m.text))
        pg.add_init_script("window.__csp = []; addEventListener('securitypolicyviolation', "
                           "e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI))")
        pg.goto(url)
        pg.wait_for_function("() => window.__studio && window.__studio.ST.init", timeout=600000)
        if not pg.evaluate("!!navigator.gpu"):
            pytest.skip("no WebGPU in this Chrome")
        assert pg.evaluate("window.__studio.ST.init.web") and not pg.locator("#webLoading").count()
        pg.evaluate("document.querySelectorAll('#modal.show').forEach(m => m.classList.remove('show'))")
        pg.wait_for_function("() => window.__studio.ST.avatar", timeout=600000)     # Simple mode builds it by itself
        pg.click("#toGarment")
        pg.click('#gcards [data-k="tee"]')
        pg.wait_for_function("() => window.__studio.ST.block === 'tee' && window.__studio.ST.draft", timeout=600000)
        pg.evaluate("window.__studio.ST.maxStep = 4; renderSteps(); window.__studio.go('preview')")
        assert "desktop app" in pg.inner_text("#poses")
        t0 = time.time()
        pg.click("#drapeBtn")
        pg.wait_for_function("() => window.__studio.ST.drape", timeout=900000)
        m = pg.evaluate("window.__studio.ST.drape.metrics")
        assert m["penetrating_verts"] == 0 and m["strain_p99_pct"] < 6.0 and m["kinetic_energy_uJ"] < 20 and m["welded"]
        assert time.time() - t0 < 300
        for kind in ("pdf_letter", "projector", "dxf_laser", "techpack", "glb"):
            size = pg.evaluate("""async kind => { const r = await api('/api/export', {avatar: ST.avatar.id, ...garmentReq(), kind,
                                   seam_allowance_cm: 1.5, job: ST.job}); return (await r.blob()).size }""", kind)
            assert size > 10000, kind
        csp = pg.evaluate("window.__csp")
        assert not errors and not csp, (errors, csp)
        b.close()
