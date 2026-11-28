"""A real run of the AI designer against the Anthropic API: skipped unless SPUNFECTION_TEST_ANTHROPIC_KEY is set (a
user environment variable; the key is typed into the page's field and never printed, logged or written anywhere).
It costs real money (about $0.30-1.50 a test), so it never runs in the normal suite:

    pytest tests/test_zz_live_ai.py -s -m live
"""
import os

import pytest

pytest.importorskip("playwright.sync_api")
from test_browser import ST, _ensure_avatar, _go_garment, page, server  # noqa: F401,E402  (fixtures)


def _key():
    k = os.environ.get("SPUNFECTION_TEST_ANTHROPIC_KEY")
    if not k and os.name == "nt":              # set after this shell started: read the user's own variables
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as h:
                k = winreg.QueryValueEx(h, "SPUNFECTION_TEST_ANTHROPIC_KEY")[0]
        except OSError:
            k = None
    return k.strip() if k else k


KEY = _key()
pytestmark = [pytest.mark.live, pytest.mark.skipif(not KEY, reason="SPUNFECTION_TEST_ANTHROPIC_KEY isn't set")]


def _run(pg, mode, text, model, rounds):
    statuses = []
    pg.on("response", lambda r: r.url.startswith("https://api.anthropic.com/") and statuses.append(r.status))
    if pg.locator("#aipanel").is_hidden():
        pg.click("#aiBtn")
    pg.evaluate("AI.skipDrape = false; AI.versions = []; $('#aipanel').scrollTop = 0")
    pg.fill("#aikey", KEY)
    pg.click(f'#aimode [data-m="{mode}"]')
    pg.fill("#aitext", text)
    pg.select_option("#aimodel", model)
    pg.select_option("#airounds", str(rounds))
    pg.click("#aiGo")
    pg.wait_for_function("!AI.busy", timeout=3600000)
    log, cost = pg.inner_text("#ailog"), pg.inner_text("#aicost")
    vers = pg.evaluate("AI.versions.map(v => ({round: v.round, pass: v.verdict.pass, scores: v.verdict.scores, summary: v.summary, corrections: v.verdict.corrections}))")
    print(f"\n--- {model} / {mode}: {text}\nHTTP statuses: {statuses}\n{log}\n{cost}")
    for v in vers:
        print(v)
    pg.fill("#aikey", "")
    assert KEY not in pg.evaluate("JSON.stringify(Object.fromEntries(Object.entries(localStorage))) + JSON.stringify(project())")
    return statuses, log, vers


def test_live_sonnet_from_scratch(page):
    _ensure_avatar(page)
    statuses, log, vers = _run(page, "scratch", "A simple knee-length A-line skirt with an elastic waist, in poplin", "sonnet", 2)
    assert statuses and all(s == 200 for s in statuses), statuses
    assert vers, log


def test_live_opus_edits_the_tee(page):
    _ensure_avatar(page)
    _go_garment(page, "tee")
    statuses, log, vers = _run(page, "edit", "Add a patch pocket on the left chest and make it 5 cm longer", "opus", 2)
    assert statuses and all(s == 200 for s in statuses), statuses
    assert vers, log


def test_live_opus_fixes_the_dress_hood_and_keeps_the_dress(page):
    """Tyler's case (2026-11-28): "the hoodie ... too small" on a dress with a hood came back as a hoodie."""
    _ensure_avatar(page)
    _go_garment(page, "shift_dress")
    page.click("#toScratch")
    page.wait_for_function(f"{ST}.ST.scratch && {ST}.ST.design.pieces.some(p => p.name === 'front')", timeout=60000)
    page.evaluate(f"(async () => {{ await serverEdit('band', {{kind: 'hood', loop: ['front.neck', 'back.neck'], avatar: {ST}.ST.avatar.id}}) }})()")
    page.wait_for_function(f"{ST}.ST.design.pieces.some(p => p.role === 'hood')", timeout=60000)
    before = page.evaluate(f"{ST}.ST.design.pieces.map(p => p.name)")
    statuses, log, vers = _run(page, "edit", "the hoodie is not draping correctly. its too small. can you fix that.", "opus", 1)
    after = page.evaluate(f"{ST}.ST.design.pieces.map(p => p.name)")
    print("pieces before", before, "\npieces after", after)
    assert statuses and all(s == 200 for s in statuses), statuses
    assert all(any(a == b or a.startswith(b + "_") for a in after) for b in before if b in ("front", "back")), (before, after)
