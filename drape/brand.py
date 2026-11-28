"""The product's public name (docs/specs/RENAME_SPEC.md, decided 2026-11-22).

Users see "Spunfection Studio", published by Spunfection LLC at spunfection.studio. The
code keeps its own name: the package `drape`, its modules, `python -m drape.studio`.
"drape" stays in the UI only as the sewing word (a drape, Drape it, drape on the avatar).

The trade mark sign goes once per surface (the page header, the README title, PDF and
tech-pack footers, the about box); "®" never (not registered). The studio's page and
scripts carry the same strings (BRAND in js/01_core.js); tests/test_v22_rename.py checks.
"""
APP = "Spunfection Studio"
APP_TM = "Spunfection Studio™"
SHORT = "Spunfection"
COMPANY = "Spunfection LLC"
DOMAIN = "spunfection.studio"
URL = "https://spunfection.studio/"
COPYRIGHT = "© 2026 Spunfection LLC"
MADE_WITH = f"Made with {APP_TM} · {DOMAIN}"

# The footer's links: the public repo (MPL-2.0) and its issues; Terms and Privacy are pages here.
REPO_URL = "https://github.com/spunfectionLLC/Drape"
SOURCE_URL = REPO_URL
ISSUES_URL = REPO_URL + "/issues"
# "Report a bug" (Tyler, 2026-11-24): a Google Form, so people without a GitHub account can report too
BUG_REPORT_URL = "https://docs.google.com/forms/d/1UtgLtItux0It6J0uolu7vAvpvrKTFt9J8RHhd3S5SeY/viewform"
TERMS_URL = "/terms"
PRIVACY_URL = "/privacy"

# placeholder pages: (title, text)
PAGES = {
    "/terms": ("Terms", "Coming before public launch."),
    "/privacy": ("Privacy", None),          # the full text: PRIVACY_HTML
    "/source": ("Source code", "Spunfection Studio is open source. The link to the public repository "
                               "goes here once it's published."),
    "/bugs": ("Report a bug", "Bug reports will go to the public repository's issues once it's published."),
}


# The privacy page. Keep it true: if the site ever adds analytics, ads, accounts, cloud
# saves or another outside service, this text must change first (and the date with it).
PRIVACY_UPDATED = "24 November 2026"
PRIVACY_HTML = f"""
<p><b>Last updated: {PRIVACY_UPDATED}</b></p>
<p>{APP} is made by {COMPANY}. This page says what happens to your information when you
use {APP} at <a href="https://{DOMAIN}/">{DOMAIN}</a>.</p>

<h2>The short version</h2>
<p>{APP} runs entirely in your web browser. Your measurements, your avatar, your designs
and the files you make stay on your computer. We don't collect them, we can't see them,
and we don't keep them anywhere. There are no accounts, no cookies, no analytics and no ads.</p>

<h2>What stays on your computer</h2>
<ul>
<li><b>Your measurements and designs.</b> The avatar, the patterns, the drape and every
export are made by your own browser and graphics card. Nothing you type is sent to us.</li>
<li><b>Your browser's storage.</b> {APP} saves your current project, any measurement profiles you save, and a few settings
(units, light or dark mode, whether you've seen the welcome notes) in your browser's own
storage, so your work is still there next time. Only this browser on this computer can
read it. Clearing your browser's data for this site deletes it.</li>
<li><b>Files you save or open.</b> A .drape project file or an export is saved where you
choose. Files and photos you open (a project, a fabric print, a pattern photo to trace)
are read by your browser on your computer and aren't uploaded.</li>
</ul>

<h2>Outside services the site uses</h2>
<p>To work, your browser downloads files from these services. Like any website, they
receive the technical details every browser sends with a request (such as your IP
address, the browser you use and the time), under their own privacy policies:</p>
<ul>
<li><b>Cloudflare</b> hosts the site (the page and the {APP} program files).</li>
<li><b>jsDelivr</b> supplies Python for the browser (Pyodide) and its packages.</li>
<li><b>The Python Package Index (PyPI)</b> supplies one more package (ezdxf, for DXF files).</li>
</ul>
<p>None of them receives your measurements, designs or files.</p>

<h2>Reporting a bug</h2>
<p><b>Report a bug</b> opens a Google Form. Only what you choose to type into the form is sent,
to Google, under Google's privacy policy, and to us so we can fix the problem. Nothing is sent
unless you fill in the form and submit it.</p>

<h2>Children</h2>
<p>{APP} doesn't ask for or collect personal information from anyone, of any age.</p>

<h2>Changes</h2>
<p>If {APP} ever adds something that sends information off your computer (for example
accounts, cloud saves or advertising), this page will be updated before it does, and the
date at the top will change.</p>

<h2>Questions</h2>
<p>Use <a href="{BUG_REPORT_URL}">Report a bug</a> to ask a question about this page.</p>
"""


def version() -> str:
    try:
        from importlib.metadata import version as v
        return v("drape")
    except Exception:
        return ""


def generator() -> str:
    """For file stamps: 'Spunfection Studio 1.5.0'."""
    v = version()
    return f"{APP} {v}".strip()


def pdf_footer(fig, extra="", y=None):
    """The footer line on a matplotlib page: 'Made with Spunfection Studio™ · spunfection.studio'."""
    h = fig.get_figheight()
    fig.text(0.5, (0.28 / h) if y is None else y, MADE_WITH + (f" · {extra}" if extra else ""),
             ha="center", va="center", fontsize=7, color="#888")


def pdf_metadata() -> dict:
    return {"Creator": generator(), "Producer": f"{generator()} ({DOMAIN})"}


def dxf_stamp(doc):
    """Who made a DXF, in its header (custom properties, R2004+): never as text on a layer,
    so a laser or plotter can't cut or engrave it."""
    if doc.dxfversion >= "AC1018":
        doc.header.custom_vars.append("Generator", generator())
        doc.header.custom_vars.append("Website", DOMAIN)
        doc.header.custom_vars.append("Copyright", COPYRIGHT)


def as_dict() -> dict:
    """What the studio page gets in /api/init."""
    return {"app": APP, "app_tm": APP_TM, "short": SHORT, "company": COMPANY, "domain": DOMAIN, "url": URL,
            "copyright": COPYRIGHT, "links": {"terms": TERMS_URL, "privacy": PRIVACY_URL,
                                              "source": SOURCE_URL, "bugs": BUG_REPORT_URL}}


def placeholder_page(path: str) -> bytes | None:
    """The small HTML page for a placeholder link (None: not one)."""
    if path not in PAGES:
        return None
    title, text = PAGES[path]
    body = PRIVACY_HTML if path == "/privacy" else f"<p>{text}</p>"
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{title} · {APP}</title><style>body{{font:16px/1.5 system-ui,sans-serif;'
            f'max-width:640px;margin:48px auto;padding:0 16px;color:#222}}a{{color:#1f7a6d}}</style></head>'
            f'<body><h1>{title}</h1>{body}<p><a href="/">Back to {APP}</a></p>'
            f'<p style="color:#666;font-size:13px">{COPYRIGHT}</p></body></html>').encode("utf-8")
