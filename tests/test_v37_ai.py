"""v1.7.0 (2026-11-28): the AI designer (header ✦ AI). A request in words and a sketch go to a builder model, which
writes the design; the page checks it (and sends problems back); it's draped; renders and fit numbers go to a critic
model; its corrections go back to the builder. The API key is typed each visit and never stored.

The browser test mocks the Anthropic API (Playwright routes), so it needs no key and costs nothing."""
import copy
import json
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from test_browser import ST, _ensure_avatar, page, server  # noqa: F401,E402  (fixtures)

ROOT = Path(__file__).resolve().parents[1]
KEY = "sk-ant-test-0000-not-a-real-key"


def test_the_ai_spec_script_is_generated_from_the_format_doc():
    import importlib.util
    spec = importlib.util.spec_from_file_location("make_ai_spec", ROOT / "tools" / "make_ai_spec.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert (ROOT / "drape" / "studio" / "static" / "js" / "19_ai_spec.js").read_text(encoding="utf-8") == m.source(), \
        "run python tools/make_ai_spec.py"


def test_the_website_may_call_the_anthropic_api_and_nothing_stores_the_key():
    import tools.build_site as B
    assert "https://api.anthropic.com" in B.CSP
    import re
    js = (ROOT / "drape" / "studio" / "static" / "js" / "20_ai.js").read_text(encoding="utf-8")
    js = re.sub(r"(?m)^\s*//.*$", "", js)                                      # the code, not the comments
    # the key is read from its field where a request is sent, and only put in that request's header
    assert js.count('$("#aikey").value.trim()') == 1 and '"x-api-key": key' in js   # (the other mention clears it)
    for bad in ("localStorage", "sessionStorage", "LS.set", "autosave", "indexedDB", "document.cookie"):
        assert bad not in js, bad


def _sse(blocks, stop="tool_use"):
    ev = [{"type": "message_start", "message": {"usage": {"input_tokens": 1200, "cache_read_input_tokens": 0}}}]
    for i, b in enumerate(blocks):
        if b["type"] == "tool_use":
            ev.append({"type": "content_block_start", "index": i, "content_block": {"type": "tool_use", "id": b["id"], "name": b["name"], "input": {}}})
            s = b["raw"] if "raw" in b else json.dumps(b["input"])
            for k in range(0, len(s), 400):
                ev.append({"type": "content_block_delta", "index": i, "delta": {"type": "input_json_delta", "partial_json": s[k:k + 400]}})
        else:
            ev.append({"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}})
            ev.append({"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": b["text"]}})
        ev.append({"type": "content_block_stop", "index": i})
    ev += [{"type": "message_delta", "delta": {"stop_reason": stop}, "usage": {"output_tokens": 900}}, {"type": "message_stop"}]
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in ev)


@pytest.mark.slow
def test_the_ai_loop_builds_checks_fixes_drapes_and_reviews(page):
    pg = page
    _ensure_avatar(pg)
    skirt = json.loads((ROOT / "docs" / "examples" / "a_line_skirt.drape").read_text(encoding="utf-8"))["garments"][0]["design"]
    bad = copy.deepcopy(skirt)
    bad["pieces"][1]["verts"] = [[-34, 0], [34, 0], [26, 50], [-26, 50]]          # a back 10 cm shorter: its side seams won't match
    calls = []

    def handle(route):
        req = route.request
        if req.method == "OPTIONS":
            route.fulfill(status=204, headers={"access-control-allow-origin": "*", "access-control-allow-headers": "*",
                                               "access-control-allow-methods": "POST"})
            return
        body = json.loads(req.post_data)
        calls.append({"headers": req.headers, "body": body})
        tool = body["tools"][0]["name"]
        if tool == "submit_design":
            fixing = any(isinstance(m["content"], list) and any(c.get("type") == "tool_result" for c in m["content"])
                         for m in body["messages"])
            blocks = [{"type": "text", "text": "Here it is."},
                      {"type": "tool_use", "id": f"toolu_{len(calls)}", "name": "submit_design",
                       "input": {"plan": "two panels", "design": skirt if fixing else bad, "fabric": "poplin", "summary": "An A-line skirt with an elastic waist."}}]
        else:
            blocks = [{"type": "tool_use", "id": "toolu_r", "name": "submit_review",
                       "input": {"pass": True, "scores": {"request": 8, "fit": 8, "construction": 9, "physics": 9},
                                 "corrections": [], "summary": "A tidy A-line skirt, as asked."}}]
        route.fulfill(status=200, headers={"content-type": "text/event-stream", "access-control-allow-origin": "*"}, body=_sse(blocks))

    pg.route("https://api.anthropic.com/v1/messages", handle)
    garments_before = pg.evaluate("PROJECT.garments.length")
    pg.click("#aiBtn")
    assert pg.locator("#aipanel").is_visible() and pg.get_attribute("#aikey", "type") == "password"
    pg.fill("#aikey", KEY)
    pg.click('#aimode [data-m="scratch"]')
    pg.fill("#aitext", "A knee-length A-line skirt with an elastic waist")
    box = pg.locator("#aipad").bounding_box()                                    # a sketch: a blue line
    pg.mouse.move(box["x"] + 40, box["y"] + 40); pg.mouse.down(); pg.mouse.move(box["x"] + 200, box["y"] + 120, steps=5); pg.mouse.up()
    pg.select_option("#airounds", "2")
    pg.click("#aiGo")
    pg.wait_for_function("!AI.busy && AI.versions.length > 0", timeout=900000)
    # three calls: the builder, the builder fixing what the checks found, the critic
    tools = [c["body"]["tools"][0]["name"] for c in calls]
    assert tools == ["submit_design", "submit_design", "submit_review"], tools
    h = calls[0]["headers"]
    assert h["x-api-key"] == KEY and h["anthropic-dangerous-direct-browser-access"] == "true" and h["anthropic-version"]
    b0 = calls[0]["body"]
    assert b0["model"] == "claude-opus-5-5" and b0["stream"] is True and b0["thinking"] == {"type": "adaptive"}
    assert b0["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "## 4. `design.seams`: what sews to what" in b0["system"][0]["text"]   # the spec goes with it
    assert any(c.get("type") == "image" for c in b0["messages"][0]["content"])    # the sketch
    fix = calls[1]["body"]["messages"][-1]["content"][0]
    assert fix["type"] == "tool_result" and fix["is_error"] and "lengths differ" in fix["content"]
    crit = calls[2]["body"]["messages"][0]["content"]
    assert sum(c.get("type") == "image" for c in crit) >= 3                       # the sketch and the renders
    assert "strain_p99_pct" in crit[0]["text"]
    # the design is in the editor, on a new garment, draped; the version is listed
    assert pg.evaluate("PROJECT.garments.length") == garments_before + 1
    assert pg.evaluate(f"{ST}.ST.design.pieces.map(p => p.name)") == ["front", "back"]
    assert pg.evaluate(f"!!{ST}.ST.drape") and pg.evaluate(f"{ST}.ST.fabric") == "poplin"
    assert pg.locator("#aiversions [data-aiv]").count() == 1 and "passed" in pg.inner_text("#aiversions")
    # the key went nowhere else
    stored = pg.evaluate("JSON.stringify(Object.fromEntries(Object.entries(localStorage))) + JSON.stringify(sessionStorage) + document.cookie")
    assert KEY not in stored
    assert KEY not in pg.evaluate("JSON.stringify(project())")
    assert not pg.errors, pg.errors


# ----------------------------------------------------------- debugging round 1: what goes wrong (mocked API)
SKIRT = json.loads((ROOT / "docs" / "examples" / "a_line_skirt.drape").read_text(encoding="utf-8"))["garments"][0]["design"]


def _design_reply(n, design=None):
    return [{"type": "tool_use", "id": f"toolu_d{n}", "name": "submit_design",
             "input": {"plan": "p", "design": design or SKIRT, "fabric": "poplin", "summary": "A skirt."}}]


REVIEW = [{"type": "tool_use", "id": "toolu_r", "name": "submit_review",
           "input": {"pass": True, "scores": {"request": 8, "fit": 8, "construction": 8, "physics": 8}, "corrections": [], "summary": "Good."}}]


def _run(pg, script, mode="scratch", text="A skirt", model="opus", drape=False, wait=True):
    """Run the AI panel against a mocked API: script(call_number, body) -> (status, headers, body text)."""
    calls = []

    def handle(route):
        req = route.request
        if req.method == "OPTIONS":
            route.fulfill(status=204, headers={"access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "POST"})
            return
        body = json.loads(req.post_data)
        calls.append(body)
        status, headers, text = script(len(calls), body)
        route.fulfill(status=status, headers={"access-control-allow-origin": "*", "access-control-expose-headers": "*", **headers}, body=text)
    _ensure_avatar(pg)
    pg.unroute("https://api.anthropic.com/v1/messages")
    pg.route("https://api.anthropic.com/v1/messages", handle)
    if pg.locator("#aipanel").is_hidden():
        pg.click("#aiBtn")
    pg.evaluate(f"AI.skipDrape = {'false' if drape else 'true'}; AI.versions = []; $('#aipanel').scrollTop = 0")
    pg.fill("#aikey", KEY)
    pg.evaluate(f"aiMode('{mode}')")
    pg.fill("#aitext", text)
    pg.select_option("#aimodel", model)
    pg.select_option("#airounds", "1")
    pg.evaluate("$('#aiGo').click()")
    if wait:
        pg.wait_for_function("!AI.busy", timeout=600000)
    return calls, pg.inner_text("#ailog")


SSE = {"content-type": "text/event-stream"}


def test_a_refused_key_says_so_and_isnt_retried(page):
    calls, log = _run(page, lambda n, b: (401, {"content-type": "application/json"}, json.dumps({"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})))
    assert len(calls) == 1 and "API key was refused" in log
    assert not page.errors, page.errors


def test_overloaded_and_cut_off_answers_are_retried_once(page):
    def script(n, b):
        if n == 1:
            return 529, {"content-type": "application/json", "retry-after": "1"}, json.dumps({"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})
        if n == 2:
            return 200, SSE, _sse(_design_reply(n)).rsplit("event: message_stop", 1)[0]      # the stream ends early
        if n == 3:
            return 200, SSE, _sse(_design_reply(n))
        return 200, SSE, _sse(REVIEW)
    calls, log = _run(page, script)
    assert [c["tools"][0]["name"] for c in calls] == ["submit_design", "submit_design", "submit_design", "submit_review"], log
    assert "passed" in log
    assert not page.errors, page.errors


def test_a_builder_that_never_calls_the_tool_or_sends_broken_json_is_told_and_then_stops(page):
    def script(n, b):
        if n == 1:   # the tool input stops mid-way: not valid JSON
            raw = json.dumps(_design_reply(n)[0]["input"])[:-40]
            return 200, SSE, _sse([{"type": "tool_use", "id": "toolu_x", "name": "submit_design", "raw": raw}], stop="max_tokens")
        return 200, SSE, _sse([{"type": "text", "text": "I'd rather describe it in words."}], stop="end_turn")
    calls, log = _run(page, script)
    assert len(calls) == 3
    fix = calls[1]["messages"][-1]["content"][0]
    assert fix["type"] == "tool_result" and fix["is_error"] and "cut off" in fix["content"]
    tu = [c for c in calls[1]["messages"][1]["content"] if c["type"] == "tool_use"][0]
    assert tu["input"] == {}                                    # echoed back as an object, as the API needs
    assert "couldn't produce a design" in log
    assert not page.errors, page.errors


def test_a_refusal_is_said_plainly(page):
    calls, log = _run(page, lambda n, b: (200, SSE, _sse([{"type": "text", "text": ""}], stop="refusal")))
    assert len(calls) == 1 and "declined" in log
    assert not page.errors, page.errors


def test_sonnet_can_be_picked_and_stop_stops(page):
    calls, log = _run(page, lambda n, b: (200, SSE, _sse(_design_reply(n) if b["tools"][0]["name"] == "submit_design" else REVIEW)),
                      model="sonnet")
    assert calls[0]["model"] == "claude-sonnet-5-5"
    # Stop right away: nothing is left running and it says so
    page.evaluate("aiRun(); AI.stopped = true; if (AI.ctrl) AI.ctrl.abort()")
    page.wait_for_function("!AI.busy", timeout=60000)
    assert "Stopped" in page.inner_text("#ailog")
    assert not page.errors, page.errors


def test_edit_mode_turns_a_library_pattern_into_a_design_and_sends_it(page):
    from test_browser import _go_garment
    _ensure_avatar(page)
    _go_garment(page, "tee")

    def script(n, b):
        if b["tools"][0]["name"] == "submit_review":
            return 200, SSE, _sse(REVIEW)
        txt = b["messages"][0]["content"][0]["text"]
        cur = json.loads(txt.split("Current design (editor format):\n", 1)[1].split("\n\n", 1)[0])
        cur["pieces"][0]["edges"][0]["hem"] = {"style": "double", "depth_cm": 2, "turn_cm": 1}      # the edit
        return 200, SSE, _sse(_design_reply(n, cur))
    before = page.evaluate("PROJECT.garments.length")
    calls, log = _run(page, script, mode="edit", text="Add a double hem")
    assert calls, page.inner_text("#toast")
    assert "Mode: edit the current design" in calls[0]["messages"][0]["content"][0]["text"]
    assert page.evaluate("PROJECT.garments.length") == before                       # edited in place
    sent = json.loads(calls[0]["messages"][0]["content"][0]["text"].split("Current design (editor format):\n", 1)[1].split("\n\n", 1)[0])
    p0, e0 = sent["pieces"][0]["name"], sent["pieces"][0]["edges"][0]["name"]
    got = page.evaluate(f"(() => {{ const p = {ST}.ST.design.pieces.find(p => p.name === '{p0}'); return p && JSON.parse(JSON.stringify(p.edges.find(e => e.name === '{e0}'))) }})()")
    assert page.evaluate(f"{ST}.ST.scratch") and got and got.get("hem", {}).get("style") == "double", (p0, e0, got, log)
    assert not page.errors, page.errors


def test_sketch_backgrounds_and_images_stay_small(page):
    page.evaluate(f"{ST}.go('fit')")
    page.wait_for_timeout(500)
    if page.locator("#aipanel").is_hidden():
        page.click("#aiBtn")
    page.evaluate("aiBackground('pattern')")
    page.wait_for_function("AI.bg && AI.bgKind === 'pattern'", timeout=10000)
    page.evaluate("AI.strokes = [{color: '#2f6fbf', w: 6, pts: [[10, 10], [300, 200]]}]; aiDrawPad()")
    sizes = page.evaluate("""(async () => { const out = [];
        for (const s of aiSketchImages()) { const im = new Image(); im.src = await aiShrink(s.data); await im.decode(); out.push(Math.max(im.width, im.height)) }
        return out })()""")
    assert len(sizes) == 2 and max(sizes) <= 1024
    big = page.evaluate("""(async () => { const c = document.createElement('canvas'); c.width = 3200; c.height = 2000;
        const im = new Image(); im.src = await aiShrink(c.toDataURL('image/png')); await im.decode(); return [im.width, im.height] })()""")
    assert big == [1024, 640]
    page.evaluate("AI.strokes = []; AI.bg = null; aiDrawPad()")
    assert not page.errors, page.errors


def test_an_edit_keeps_the_garment_even_when_the_model_makes_another_one(page):
    """Tyler (2026-11-28): "the hoodie is too small" on his dress came back as a hoodie: the builder read "hoodie" as
    the garment. An edit that drops most of the original pieces is sent back, whatever the model says."""
    from test_browser import _go_garment
    _ensure_avatar(page)
    _go_garment(page, "tee")
    hoodie = copy.deepcopy(SKIRT)
    for p, n in zip(hoodie["pieces"], ("hoodie_front", "hoodie_back")):
        p["name"] = n
    hoodie["seams"] = [{"a": "hoodie_front.side_r", "b": "hoodie_back.side_l", "ease": 0}, {"a": "hoodie_front.side_l", "b": "hoodie_back.side_r", "ease": 0}]

    def script(n, b):
        if b["tools"][0]["name"] == "submit_review":
            return 200, SSE, _sse(REVIEW)
        txt = b["messages"][0]["content"][0]["text"]
        if n == 1:                                                   # another garment altogether
            return 200, SSE, _sse(_design_reply(n, hoodie))
        cur = json.loads(txt.split("Current design (editor format):\n", 1)[1].split("\n\n", 1)[0])
        return 200, SSE, _sse(_design_reply(n, cur))                 # the tee, kept
    calls, log = _run(page, script, mode="edit", text="the hoodie is too small, can you fix that")
    first = calls[0]["messages"][0]["content"][0]["text"]
    assert "This is an edit of the user's tee" in first and "- front (" in first
    fix = calls[1]["messages"][-1]["content"][0]
    assert fix["is_error"] and "no longer keeps it" in fix["content"] and "front" in fix["content"]
    assert page.evaluate(f"{ST}.ST.design.pieces.map(p => p.name)") == [p["name"] for p in json.loads(first.split("Current design (editor format):\n", 1)[1].split("\n\n", 1)[0])["pieces"]]
    crit = [c for c in calls if c["tools"][0]["name"] == "submit_review"][0]["messages"][0]["content"][0]["text"]
    assert "This was an EDIT of the user's tee" in crit
    assert not page.errors, page.errors
