"""The product's public name is Spunfection Studio (docs/specs/RENAME_SPEC.md, 2026-11-22).
Users see the new name, the code keeps `drape`, nothing a user sees names a competitor,
and no personal email address is anywhere in the repo or what it builds.
The footer and the saved-file stamp in the browser: test_browser.py."""
import hashlib
import io
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "drape" / "studio" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
# proper nouns, so case-sensitive ("data-clo" is a seam-closure attribute); the names are kept out of the public text
# (ROT13 here), so this file doesn't itself name them
import codecs
COMPETITORS = re.compile(r"\b(" + codecs.decode("PYB ?3Q|PYB|Pyb3Q|Zneirybhf Qrfvtare|Zneirybhf|Fglyr3Q|Oebjmjrne|Bcgvgrk|Yrpgen|Treore", "rot13") + r")\b")


def _js():
    from drape.studio.server import studio_source
    return studio_source()


def _visible(html):
    """Text a person sees or a search engine reads: no script, no style, no comments."""
    html = re.sub(r"(?s)<script.*?</script>|<style.*?</style>|<!--.*?-->", " ", html)
    metas = " ".join(re.findall(r'<meta[^>]+content="([^"]*)"', html))
    return re.sub(r"<[^>]+>", " ", html) + " " + metas


def _user_strings(js):
    """The string literals in the studio's scripts (comments dropped)."""
    code = re.sub(r"(?m)^\s*//.*$|(?<=[;{}),\s])//[^\n\"'`]*$", "", js)
    return " ".join(m.group(0) for m in re.finditer(r'"(?:[^"\\\n]|\\.)*"|`(?:[^`\\]|\\.)*`', code))


# ---------------------------------------------------------------- 1. the page --
def test_the_page_title_and_header_say_spunfection_studio_with_one_tm():
    from drape import brand
    assert re.search(r"<title>Spunfection Studio</title>", INDEX)
    header = INDEX[INDEX.index("<header>"):INDEX.index("</header>")]
    assert brand.APP_TM in header and header.count("™") == 1
    assert "®" not in INDEX and "®" not in _js()


def test_meta_tags_point_at_spunfection_studio():
    head = INDEX[:INDEX.index("</head>")]
    for tag in ('property="og:title" content="Spunfection Studio"', 'property="og:site_name" content="Spunfection Studio"',
                'property="og:url" content="https://spunfection.studio/"', '<link rel="canonical" href="https://spunfection.studio/">',
                'name="twitter:card"', 'name="description"'):
        assert tag in head, tag


def test_the_js_brand_mirror_matches_brand_py():
    from drape import brand
    m = re.search(r"const BRAND = (\{[^}]*\});", _js())
    js = json.loads(re.sub(r"(\w+):", r'"\1":', m.group(1)).replace("\\u2122", "™"))
    assert js == {"app": brand.APP, "tm": brand.APP_TM, "company": brand.COMPANY, "domain": brand.DOMAIN}


def test_the_about_box_and_alpha_notice_use_the_new_name():
    js = _js()
    assert 'modal("How Spunfection Studio works"' in js
    assert "modal(`${BRAND.app} is in alpha`" in js and "${BRAND.app}${ST.init && ST.init.version ? ` v${ST.init.version}` : \"\"} alpha" in js
    assert 'title="Spunfection Studio is in alpha: what that means"' in INDEX


# ----------------------------------------------- 2. "drape" only as the word --
def test_drape_is_never_the_product_name_in_what_users_see():
    seen = _visible(INDEX) + " " + _user_strings(_js()) + " " + _visible((ROOT / "web" / "proof.html").read_text(encoding="utf-8"))
    assert not re.search(r"(?i)drape studio", seen)
    assert "drape.studio" not in seen
    # the product-name phrasings that were there before
    for old in ("How drape works", "drape is in alpha", "drape project", "drape fabric tester", "drape runs"):
        assert old not in seen, old


def test_the_code_keeps_its_name():
    import drape
    import drape.studio.server  # noqa: F401
    toml = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'(?m)^name = "drape"$', toml) and 'drape-studio = "drape.studio.__main__:main"' in toml
    assert 'authors = [{name = "Spunfection LLC"}]' in toml and "Spunfection Studio" in toml
    assert Path(drape.__file__).parent.name == "drape"
    assert 'format: "drape-project"' in _js()          # old project files still open


# --------------------------------------------------------- 3. generated files --
@pytest.fixture(scope="module")
def tee():
    from drape.studio import server as S
    init = S.api_init()
    a = S.api_avatar({"measurements": init["examples"]["female_M"]})
    A = S.S.avatars[a["id"]]
    from drape.blocks import draft_block
    g, _ = draft_block("tee", A["body"], A["meas"])
    return g, A


def _texts_while(fn, monkeypatch):
    """Every string drawn on a figure or an axes while fn() runs, then fn's result."""
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure
    seen = []
    for cls in (Figure, Axes):
        orig = cls.text

        def wrap(self, x, y, s, *a, _orig=orig, **k):
            seen.append(str(s))
            return _orig(self, x, y, s, *a, **k)
        monkeypatch.setattr(cls, "text", wrap)
    out = fn()
    return seen, out


def test_pdf_footers_and_stamps(tee, tmp_path, monkeypatch):
    from drape import brand
    from drape.printpdf import projector_pdf, tiled_pdf
    from drape.techpack import techpack_pdf
    g, A = tee
    P, Sd = g.meta["panels"], g.meta["seam_defs"]
    f = tmp_path / "t.pdf"
    seen, info = _texts_while(lambda: tiled_pdf(P, Sd, f, "Tee"), monkeypatch)
    foot = [s for s in seen if s.startswith("Made with ")]
    assert len(foot) == info["pages"]                                    # one on every printed page
    assert all("Spunfection Studio™" in s and "spunfection.studio" in s for s in foot)
    assert f"/Creator ({brand.generator()})".encode() in f.read_bytes()
    f2 = tmp_path / "p.pdf"
    seen, _ = _texts_while(lambda: projector_pdf(P, Sd, f2, "Tee"), monkeypatch)
    assert brand.MADE_WITH in seen
    f3 = tmp_path / "tp.pdf"
    seen, _ = _texts_while(lambda: techpack_pdf(f3, g, A["body"], A["meas"], "Tee", "jersey", "M"), monkeypatch)
    foot = [s for s in seen if s.startswith("Made with ")]
    assert len(foot) >= 4 and all("Spunfection LLC" in s and "spunfection.studio" in s for s in foot)


def test_gltf_generator_and_blender_readme(tee, tmp_path):
    from drape.export_gltf import blender_bundle, garment_meshes, write_glb
    g, A = tee
    z = {"x0": g.x, "tris0": g.tris, "uv0": g.uv, "panel_id0": g.panel_id, "panel_names": np.array(g.panel_names)}

    class Z(dict):
        files = list(z)
    glb = tmp_path / "g.glb"
    write_glb(glb, garment_meshes(Z(z), A["body"]))
    raw = glb.read_bytes()
    jlen = int(np.frombuffer(raw[12:16], np.uint32)[0])
    asset = json.loads(raw[20:20 + jlen])["asset"]
    assert asset["generator"].startswith("Spunfection Studio") and asset["copyright"] == "© 2026 Spunfection LLC"
    kit = tmp_path / "k.zip"
    blender_bundle(kit, glb)
    readme = zipfile.ZipFile(kit).read("README.txt").decode()
    assert "Spunfection Studio" in readme and not COMPETITORS.search(readme)


def test_dxf_says_who_made_it_in_the_header_never_on_a_layer(tee, tmp_path):
    import ezdxf
    from drape import brand
    from drape.export_dxf import export_pattern_dxf
    g, _ = tee
    for laser in (False, True):
        f = tmp_path / f"p{laser}.dxf"
        export_pattern_dxf(f, g.meta["panels"], g.meta["seam_defs"], laser=laser)
        doc = ezdxf.readfile(f)
        cv = dict(doc.header.custom_vars)
        assert cv["Generator"] == brand.generator() and cv["Website"] == brand.DOMAIN
        texts = [e.dxf.text for e in doc.modelspace() if e.dxftype() in ("TEXT", "MTEXT")]
        assert not any("Spunfection" in t or "spunfection" in t for t in texts)


# ---------------------------------------------------- 5. the footer's targets --
def test_footer_links_go_to_the_placeholder_pages():
    from drape import brand
    foot = INDEX[INDEX.index('<footer class="site-footer"'):INDEX.index("</footer>")]
    assert "© 2026 Spunfection LLC · Spunfection Studio™ is alpha software, provided as-is" in foot
    links = dict((t, h) for h, t in re.findall(r'<a href="([^"]+)"[^>]*>([^<]+)</a>', foot))
    assert links == {"Terms": brand.TERMS_URL, "Privacy": brand.PRIVACY_URL, "Source code": brand.SOURCE_URL,
                     "Report a bug": brand.BUG_REPORT_URL}
    assert brand.BUG_REPORT_URL.startswith("https://docs.google.com/forms/")    # no GitHub account needed
    assert brand.SOURCE_URL == "https://github.com/spunfectionLLC/Drape" and brand.ISSUES_URL == brand.SOURCE_URL + "/issues"
    for path in (brand.TERMS_URL, brand.PRIVACY_URL):          # the pages served here
        page = brand.placeholder_page(path).decode()
        assert "Spunfection Studio" in page and "© 2026 Spunfection LLC" in page
    assert "Coming before public launch" in brand.placeholder_page("/terms").decode()
    priv = brand.placeholder_page("/privacy").decode()       # the privacy text (2026-11-22)
    for must in ("runs entirely in your web browser", "no cookies, no analytics and no ads", "Cloudflare", "jsDelivr",
                 "PyPI", "Last updated", "Report a bug"):
        assert must in priv, must


def test_web_build_has_the_footer_meta_and_pages(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "tools"))
    import build_web_proof as B
    monkeypatch.setattr(B, "OUT", tmp_path / "web")
    B.main()
    html = (tmp_path / "web" / "index.html").read_text(encoding="utf-8")
    assert "<title>Spunfection Studio" in html and 'og:url" content="https://spunfection.studio/"' in html
    assert "© 2026 Spunfection LLC" in html and 'href="/terms"' in html and 'href="https://github.com/spunfectionLLC/Drape"' in html
    for name in ("terms", "privacy", "source", "bugs"):
        assert "Spunfection Studio" in (tmp_path / "web" / f"{name}.html").read_text(encoding="utf-8")
    _no_email_in(tmp_path / "web")


# ----------------------------------------------------------- 6. privacy guard --
EMAIL = re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
ALLOWED = (rb"noreply@", rb"@example.com", rb"@example.org")
# the owner's personal domain, by hash (writing it here would put it in the repo)
PERSONAL = "38fd692a43c8862616815f9f0e09fd7b"


def _no_email_in(root, files=None):
    files = files if files is not None else [p for p in Path(root).rglob("*") if p.is_file()]
    bad = []
    for p in files:
        if p.suffix.lower() in (".npz", ".png", ".jpg", ".glb", ".ttf", ".woff", ".woff2", ".pyc"):
            continue
        raw = p.read_bytes()
        if p.suffix == ".zip":
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                raw = b"".join(z.read(n) for n in z.namelist() if not n.endswith((".npz", ".png")))
        for m in EMAIL.finditer(raw):
            s = m.group(0)
            if not any(a in s for a in ALLOWED):
                bad.append((str(p), s.decode(errors="replace")))
        for dom in set(re.findall(rb"[a-z0-9-]+\.com", raw.lower())):
            if hashlib.md5(dom).hexdigest() == PERSONAL:
                bad.append((str(p), "<the personal domain>"))
    assert not bad, bad


def test_no_personal_email_anywhere_in_the_repo():
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True, check=True)
    files = [ROOT / f for f in out.stdout.splitlines() if (ROOT / f).is_file()]
    assert len(files) > 100
    _no_email_in(ROOT, files)


def test_the_guard_catches_a_planted_address(tmp_path):
    (tmp_path / "a.txt").write_text("contact: someone" + "@" + "somewhere.net", encoding="utf-8")
    with pytest.raises(AssertionError):
        _no_email_in(tmp_path)
    (tmp_path / "a.txt").write_text("Co-Authored-By: x <noreply" + "@" + "example.com>", encoding="utf-8")
    _no_email_in(tmp_path)


# --------------------------------------------------------- 7. no competitors --
def test_no_competitor_names_in_what_users_see():
    seen = {"page": _visible(INDEX), "scripts": _user_strings(_js()),
            "web": _visible((ROOT / "web" / "proof.html").read_text(encoding="utf-8")),
            "readme": (ROOT / "README.md").read_text(encoding="utf-8")}
    for where, text in seen.items():
        m = COMPETITORS.search(text)
        assert not m, (where, text[max(0, m.start() - 60):m.end() + 60])


def test_init_sends_the_brand():
    from drape import brand
    from drape.studio import server as S
    assert S.api_init()["brand"] == brand.as_dict()
