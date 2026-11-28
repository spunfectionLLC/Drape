"""v1.3: hand measurements for gloves (length, girth around the knuckles, wrist)."""
import dataclasses

import pytest

from drape.measurements import Measurements


def test_avatar_hand_follows_girth_and_length():
    from drape.human import fit_human
    m = Measurements.load("measurements/male_M.json")
    h, rows = fit_human(dataclasses.replace(m, hand_girth=22.5, hand_length=19.5))
    r = {x["measurement"]: x for x in rows}
    assert abs(r["hand_girth"]["error_cm"]) < 0.3 and abs(r["hand_length"]["error_cm"]) < 0.3
    assert abs(r["height"]["avatar_cm"] - m.height) < 0.5 and abs(r["chest"]["error_cm"]) < 1.5


def test_default_hands_are_realistic():
    """Exact cross-sections, not a vertex slab (the old reading said 16.7 cm for a man)."""
    from drape.human import fit_human
    from drape.meshmeasure import Tape
    for who, lo, hi in (("male_M", 19.5, 23.5), ("female_M", 16.5, 20.0)):
        T = Tape(fit_human(Measurements.load(f"measurements/{who}.json"))[0])
        assert lo < T.hand_girth() * 100 < hi, who


def test_glove_pattern_uses_hand_girth():
    from drape.gloves import glove_outline, hand_sizes
    from drape.human import fit_human
    from drape.meshbody import MeshBody
    m = dataclasses.replace(Measurements.load("measurements/male_M.json"), hand_girth=23.0)
    h, _ = fit_human(m)
    body = MeshBody(h, measurements=m)
    hs = hand_sizes(body, m)
    assert hs["hand_girth"] == pytest.approx(23.0)
    poly, chords, lobes, dims = glove_outline(hs, "gloves", ease=1.0)
    assert dims["P"] * 4 == pytest.approx(23.0, rel=1e-6)       # palm width = girth / 4 per half-layer side


def test_hand_fields_and_validation():
    m = Measurements.load("measurements/male_M.json")
    assert [w for w in dataclasses.replace(m, hand_girth=8.5).validate() if "hand girth" in w.lower()]   # inches typed
    assert not [w for w in dataclasses.replace(m, hand_girth=21.5).validate() if "hand girth" in w.lower()]
    from drape.studio import server as S
    src = S.studio_source()
    for k in ('"hand_length"', '"hand_girth"', '"wrist"'):
        assert k in src.split("MORE_FIELDS")[1].split("];")[0], k
    from drape.render import LABELS
    assert LABELS["hand_girth"] == "Hand girth"


def test_studio_is_split_into_files():
    """index.html is markup only; styles and scripts live in css/ and js/, all loaded."""
    from drape.studio import server as S
    html = (S.STATIC / "index.html").read_text(encoding="utf-8")
    assert "<style>" not in html and len(html.splitlines()) < 400
    loaded = set(__import__("re").findall(r'src="(js/[^"]+)"', html))
    on_disk = {f"js/{f.name}" for f in (S.STATIC / "js").glob("*.js")}
    assert loaded == on_disk and len(on_disk) >= 10
    assert 'href="css/studio.css"' in html


def test_static_route_stays_inside_the_studio():
    from drape.studio.server import _static_file
    assert _static_file("/js/01_core.js") is not None and _static_file("/css/studio.css") is not None
    assert _static_file("/live_springs.js") is not None
    for bad in ("/../server.py", "/js/../../server.py", "/js/../../../pyproject.toml", "/%2e%2e/server.py",
                "/data/makehuman.npz", "/js/01_core.py"):
        assert _static_file(bad) is None, bad


def test_share_on_home_network():
    """--share listens on every network interface (default: this computer only)."""
    import inspect
    from drape.studio import __main__ as M
    from drape.studio.server import serve
    assert inspect.signature(serve).parameters["host"].default == "127.0.0.1"
    src = inspect.getsource(M.main)
    assert '"--share"' in src and '"0.0.0.0" if a.share' in src


def test_shared_studio_is_https(tmp_path, monkeypatch):
    """--share serves https with drape's own certificate, so live mode (WebGPU) works on
    the other device; the certificate covers this computer's network address."""
    import socket
    import ssl
    import threading
    import urllib.request
    from cryptography import x509
    monkeypatch.setenv("DRAPE_TLS_DIR", str(tmp_path))
    from drape.studio import server as Srv
    from drape.studio.tls import ensure_cert
    cp, kp = ensure_cert(["192.168.1.23"])
    san = x509.load_pem_x509_certificate(cp.read_bytes()).extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert {"127.0.0.1", "192.168.1.23"} <= {str(a) for a in san.get_values_for_type(x509.IPAddress)}
    assert ensure_cert(["192.168.1.23"])[0].read_bytes() == cp.read_bytes()        # made once
    before = cp.read_bytes()
    ensure_cert(["10.0.0.7"])                                                        # address changed: remade
    assert cp.read_bytes() != before
    # a real https round trip
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    monkeypatch.setattr(Srv, "_lan_ip", lambda: "127.0.0.1")
    from drape.studio.tls import https_server
    srv = https_server(Srv.ThreadingHTTPServer, ("127.0.0.1", port), Srv.Handler, ["127.0.0.1"])
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    try:
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ctx))
        # browsers keep spare connections open without sending anything: they must not block the rest
        idle = [socket.create_connection(("127.0.0.1", port)) for _ in range(3)]
        for path in ("/", "/css/studio.css", "/js/01_core.js"):
            assert opener.open(f"https://127.0.0.1:{port}{path}", timeout=5).status == 200, path
        for c in idle:
            c.close()
    finally:
        srv.shutdown()
