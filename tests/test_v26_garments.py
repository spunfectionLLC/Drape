"""v26 multi-garment projects (spec 2026-11-24): a project holds several garments, each stored, edited,
exported and draped on its own; the project saves as one file (version 2).

Browser tests reuse test_browser.py's server and page (Chrome, Playwright).
"""
import json

import numpy as np
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
pytest.importorskip("playwright.sync_api")
from test_browser import ST, _ensure_avatar, _go_garment, page, server  # noqa: F401  (fixtures)

pytestmark = pytest.mark.slow

V1 = {"format": "drape-project", "version": 1, "name": "Old skirt", "measurements": {"sex": "female", "height": 166, "chest": 92,
      "waist": 74, "hip": 100}, "block": None, "choices": {}, "params": {}, "fabric": "poplin", "units": "cm", "scratch": True,
      "design": {"format": 2, "pieces": [{"name": "a", "verts": [[0, 0], [40, 0], [40, 60], [0, 60]],
                 "edges": [{"name": "bottom"}, {"name": "right"}, {"name": "top"}, {"name": "left"}]}], "seams": []}}


# ------------------------------------------------------------------ phase 2: file format v2 + migration
def test_v1_files_migrate_to_one_garment_and_v1_is_never_written(page):
    pg = page
    p = pg.evaluate(f"migrateProject({json.dumps(V1)})")
    assert p["version"] == 2 and len(p["garments"]) == 1
    g = p["garments"][0]
    assert g["name"] == "Garment 1" and g["layer"] == 1 and g["scratch"] and g["fabric"] == "poplin"
    assert [x["name"] for x in g["design"]["pieces"]] == ["a"] and p["avatar"]["measurements"]["waist"] == 74
    assert p["activeGarmentId"] == g["id"]
    assert pg.evaluate("project().version") == 2 and "garments" in pg.evaluate("project()")
    assert pg.evaluate("JSON.parse(drapeFile()).version") == 2


def test_an_old_file_opens_and_the_project_round_trips(page, tmp_path):
    pg = page
    _ensure_avatar(pg)
    v1 = dict(V1, design={"format": 2, "pieces": [pg.evaluate("makePiece('rect', {w: 40, h: 60}, 'a')")], "seams": []})
    path = tmp_path / "old.drape"
    path.write_text(json.dumps(v1), encoding="utf-8")
    pg.set_input_files("#openproj", str(path))
    pg.wait_for_function(f"{ST}.ST.name === 'Old skirt'", timeout=180000)
    assert pg.evaluate(f"{ST}.PROJECT.garments.length") == 1 and pg.evaluate("!!pieceBy('a')")
    # save -> load: everything the project holds comes back
    pg.evaluate(f"{ST}.PROJECT.garments[0].name = 'Skirt'; {ST}.PROJECT.garments[0].color = '#123456'")
    before = pg.evaluate("project()")
    pg.evaluate("openProject(JSON.parse(drapeFile()))")
    pg.wait_for_function(f"{ST}.PROJECT.garments[0].name === 'Skirt'", timeout=180000)
    after = pg.evaluate("project()")
    assert json.dumps(before["garments"], sort_keys=True) == json.dumps(after["garments"], sort_keys=True)
    assert before["avatar"] == after["avatar"] and before["activeGarmentId"] == after["activeGarmentId"]
    assert not pg.errors, pg.errors


def test_a_garment_moves_to_another_project_with_a_fresh_id_on_the_next_layer(page):
    pg = page
    _ensure_avatar(pg)
    file = json.loads(pg.evaluate("garmentFile(activeGarment())"))
    assert file["type"] == "garment" and file["version"] == 2 and "design" in file["garment"]
    old_id = file["garment"]["id"]
    n0 = pg.evaluate(f"{ST}.PROJECT.garments.length")
    top = pg.evaluate(f"Math.max(...{ST}.PROJECT.garments.map(g => g.layer))")
    pg.evaluate(f"importGarment({json.dumps(file)})")
    pg.wait_for_function(f"{ST}.PROJECT.garments.length === {n0 + 1}", timeout=60000)
    g = pg.evaluate(f"{ST}.PROJECT.garments[{n0}]")
    assert g["id"] != old_id and g["layer"] == top + 1 and g["name"] == file["garment"]["name"]
    assert pg.evaluate(f"{ST}.PROJECT.activeGarmentId") == g["id"]            # the imported one is active
    assert not pg.errors, pg.errors


# ------------------------------------------------------------------ phase 3: the Garments panel
def _two_garments(pg):
    """A project with two garments: a tee (L1, made first) and an A-line skirt (L2, active)."""
    _ensure_avatar(pg)
    pg.evaluate(f"loadGarments({{garments: [], activeGarmentId: null}}); renderGarmentList()")
    _go_garment(pg, "tee")
    pg.evaluate(f"{ST}.PROJECT.garments[0].name = 'Tee'")
    pg.evaluate("document.querySelector('#addGarment').click()")
    pg.click('#addGarmentMenu [data-ga="blank"]')
    assert pg.evaluate(f"{ST}.ST.step") == "garment"             # a new garment opens the picker
    pg.click('#gcards [data-k="a_line_skirt"]')
    pg.wait_for_function(f"{ST}.ST.block === 'a_line_skirt' && {ST}.ST.draft", timeout=60000)
    pg.evaluate(f"activeGarment().name = 'Skirt'; renderGarmentList()")


def test_steps_are_body_design_try_on_make_it(page):
    labels = page.eval_on_selector_all("#steps button .t", "els => els.map(e => e.textContent)")
    assert labels == ["Body", "Design", "Try on", "Make it"]


def test_two_garments_named_reordered_hidden_and_in_sync(page):
    pg = page
    _two_garments(pg)
    rows = lambda: pg.eval_on_selector_all("#glist .grow", "els => els.map(e => [e.querySelector('.gname').textContent, e.querySelector('.glayer').textContent, e.classList.contains('on')])")
    assert rows() == [["Skirt", "L2", True], ["Tee", "L1", False]]       # top layer first; the active one marked
    # click the tee: the pattern, the step and the fabric follow it
    pg.click("#glist .grow:nth-child(2) .gname")
    assert pg.evaluate(f"{ST}.ST.block") == "tee" and rows()[1][2]
    pg.wait_for_function(f"{ST}.ST.draft && {ST}.ST.draft.pieces.some(p => /sleeve/.test(p.name))", timeout=60000)
    pg.evaluate(f"{ST}.ST.fabric = 'denim'; renderFabrics()")
    pg.click("#glist .grow:nth-child(1) .gname")
    assert pg.evaluate(f"{ST}.ST.fabric") == "jersey" and pg.evaluate("document.querySelector('#fabrics .chip.on').dataset.f") == "jersey"
    # drag the skirt under the tee: the layers follow the order
    pg.drag_and_drop("#glist .grow:nth-child(1)", "#glist .grow:nth-child(2)")
    pg.evaluate("void 0")
    order = rows()
    assert [r[0] for r in order] == ["Tee", "Skirt"] and [r[1] for r in order] == ["L2", "L1"], order
    # hide one: the eye toggles visible
    pg.click("#glist .grow:nth-child(2) [data-act=eye]")
    assert pg.evaluate(f"{ST}.PROJECT.garments.find(g => g.name === 'Skirt').visible") is False
    pg.click("#glist .grow:nth-child(2) [data-act=eye]")
    # rename inline (double-click)
    pg.dblclick("#glist .grow:nth-child(1) .gname")
    pg.fill("#glist .gnamein", "Long tee")
    pg.keyboard.press("Enter")
    assert pg.evaluate(f"{ST}.PROJECT.garments.some(g => g.name === 'Long tee')")
    assert not pg.errors, pg.errors


def test_undo_switches_back_to_the_garment_it_changes(page):
    pg = page
    _two_garments(pg)                                                # skirt active
    skirt = pg.evaluate(f"{ST}.PROJECT.activeGarmentId")
    pg.evaluate(f"{ST}.ST.choices = {{...{ST}.ST.choices, Length: 'Midi'}}; pushHist()")
    tee = pg.evaluate(f"{ST}.PROJECT.garments.find(g => g.block === 'tee').id")
    pg.evaluate(f"setActiveGarment('{tee}')")
    pg.click("#undo")
    pg.wait_for_function(f"{ST}.PROJECT.activeGarmentId === '{skirt}'", timeout=10000)
    assert pg.evaluate(f"{ST}.ST.choices.Length") != "Midi"
    pg.click("#redo")
    pg.wait_for_function(f"{ST}.ST.choices.Length === 'Midi'", timeout=10000)
    assert not pg.errors, pg.errors


# ------------------------------------------------------------------ switching garments: the panel follows (bug, 2026-11-24)
# Tyler: switching between two drafted garments left the first one's Fit/Length chips and sliders on screen.
_PANEL = """(() => ({title: document.querySelector('#fitTitle').textContent,
    on: Object.fromEntries([...document.querySelectorAll('#choices .chip.on')].map(c => [c.dataset.c, c.dataset.o])),
    cats: [...document.querySelectorAll('#choices h3')].map(h => h.textContent),
    sliders: Object.fromEntries([...document.querySelectorAll('#sliders input')].map(s => [s.dataset.p, [+s.value, +s.step]])),
    pane: document.querySelector('.pane.on').dataset.pane, step: window.__studio.ST.step}))()"""


def _expect_panel(pg, gid):
    """The side panel shows garment `gid`'s own pattern: its title, its choices, its slider values."""
    g = pg.evaluate(f"""(() => {{ const g = garmentBy('{gid}'), b = {ST}.ST.init.blocks.find(x => x.key === g.block);
        return {{label: b.label, cats: Object.keys(b.presets), choices: g.choices, params: g.draft.params}} }})()""")
    pg.wait_for_function(f"document.querySelector('#fitTitle').textContent === {json.dumps(g['label'])}", timeout=15000)   # a busy machine
    p = pg.evaluate(_PANEL)
    assert p["pane"] == "fit" and p["step"] == "fit", p
    assert p["title"] == g["label"] and p["cats"] == g["cats"], (p, g)
    for c, o in g["choices"].items():
        assert p["on"].get(c) == o, (c, o, p["on"])
    assert set(p["sliders"]) == set(g["params"]) and all(abs(p["sliders"][k][0] - g["params"][k]) <= p["sliders"][k][1] / 2 + 1e-6 for k in g["params"]), (p, g)   # a slider snaps to its step


def _other_choice(pg):
    """A choice the active garment's draft isn't on yet: (category, option)."""
    return pg.evaluate(f"""(() => {{ const p = blockInfo().presets, c = Object.keys(p).find(k => Object.keys(p[k]).length > 1);
        return [c, Object.keys(p[c]).find(x => x !== {ST}.ST.draft.choices[c].option)] }})()""")


def test_switching_between_two_drafted_garments_switches_the_panel(page):
    pg = page
    _two_garments(pg)                                                # tee (L1), skirt (L2, active)
    tee = pg.evaluate(f"{ST}.PROJECT.garments.find(g => g.block === 'tee').id")
    skirt = pg.evaluate(f"{ST}.PROJECT.garments.find(g => g.block === 'a_line_skirt').id")
    # give each garment a choice of its own (the second option of its first category)
    for gid in (skirt, tee):
        pg.evaluate(f"setActiveGarment('{gid}')")
        pg.wait_for_function(f"{ST}.ST.draft", timeout=60000)
        c, o = _other_choice(pg)
        pg.click(f'#choices .chip[data-c="{c}"][data-o="{o}"]')
        pg.wait_for_function(f"{ST}.ST.draft && {ST}.ST.draft.choices['{c}'].option === '{o}'", timeout=60000)
        pg.wait_for_timeout(400)
        _expect_panel(pg, gid)
    # back and forth, from the panel's rows: the panel follows every time, without a new draft
    for gid in (skirt, tee, skirt, tee):
        pg.evaluate("__n = 0; if (!window.__a0) window.__a0 = api; window.api = (p, b) => (p === '/api/draft' && __n++, __a0(p, b)); 0")
        pg.click(f'#glist .grow[data-id="{gid}"] .gname')
        _expect_panel(pg, gid)
        pg.wait_for_timeout(400)                                      # past the 250 ms redraft debounce
        assert pg.evaluate("__n") == 0                                # drafted already: just shown
    assert not pg.errors, pg.errors


def test_a_draft_on_its_way_stays_with_its_own_garment(page):
    pg = page
    _two_garments(pg)
    tee = pg.evaluate(f"{ST}.PROJECT.garments.find(g => g.block === 'tee').id")
    skirt = pg.evaluate(f"{ST}.PROJECT.activeGarmentId")
    # slow the skirt's next draft down, change its length, and switch to the tee before it comes back
    pg.evaluate("const a1 = api; window.api = async (p, b) => { const r = await a1(p, b); if (p === '/api/draft' && b.block === 'a_line_skirt') await new Promise(z => setTimeout(z, 1500)); return r }; 0")
    c, o = _other_choice(pg)
    pg.click(f'#choices .chip[data-c="{c}"][data-o="{o}"]')
    pg.wait_for_timeout(400)                                          # the debounced redraft is on its way
    pg.evaluate(f"setActiveGarment('{tee}')")
    pg.wait_for_function(f"garmentBy('{skirt}').draft.choices['{c}'].option === '{o}'", timeout=60000)
    pg.wait_for_timeout(300)
    assert pg.evaluate(f"garmentBy('{tee}').draft.block || garmentBy('{tee}').block") == "tee"
    assert pg.evaluate(f"garmentBy('{tee}').draft.pieces.some(p => /sleeve/.test(p.name))")   # still the tee's pattern
    _expect_panel(pg, tee)                                            # and the tee still on screen
    pg.evaluate(f"setActiveGarment('{skirt}')")
    _expect_panel(pg, skirt)
    assert not pg.errors, pg.errors


def test_a_choice_made_just_before_a_switch_drafts_its_own_garment(page):
    """The 250 ms redraft after a choice belongs to the garment it was made on, not the one active when it fires."""
    pg = page
    _two_garments(pg)
    tee = pg.evaluate(f"{ST}.PROJECT.garments.find(g => g.block === 'tee').id")
    skirt = pg.evaluate(f"{ST}.PROJECT.activeGarmentId")
    pg.evaluate(f"setActiveGarment('{tee}')")
    pg.wait_for_function(f"{ST}.ST.draft && {ST}.ST.block === 'tee'", timeout=60000)
    skirt_draft = pg.evaluate(f"JSON.stringify(garmentBy('{skirt}').draft)")
    c, o = _other_choice(pg)
    pg.click(f'#choices .chip[data-c="{c}"][data-o="{o}"]')
    pg.evaluate(f"setActiveGarment('{skirt}')")                       # within the 250 ms
    pg.wait_for_function(f"garmentBy('{tee}').draft.choices['{c}'].option === '{o}'", timeout=60000)
    pg.wait_for_timeout(400)
    assert pg.evaluate(f"JSON.stringify(garmentBy('{skirt}').draft)") == skirt_draft     # the skirt wasn't redrafted
    _expect_panel(pg, skirt)
    pg.evaluate(f"setActiveGarment('{tee}')")
    _expect_panel(pg, tee)
    # undo puts the tee's choice back (the change was recorded on the tee)
    pg.click("#undo")
    pg.wait_for_function(f"{ST}.PROJECT.activeGarmentId === '{tee}' && {ST}.ST.choices['{c}'] !== '{o}'", timeout=10000)
    assert not pg.errors, pg.errors


def test_switching_to_a_free_edit_garment_or_an_empty_one_and_back(page):
    pg = page
    _two_garments(pg)
    tee = pg.evaluate(f"{ST}.PROJECT.garments.find(g => g.block === 'tee').id")
    skirt = pg.evaluate(f"{ST}.PROJECT.activeGarmentId")
    # the skirt becomes free edit (the design editor); the tee stays drafted
    pg.click("#toScratch")
    pg.wait_for_function(f"{ST}.ST.scratch && {ST}.ST.design.pieces.length", timeout=60000)
    pg.wait_for_timeout(800)
    assert pg.evaluate(_PANEL)["pane"] == "design"
    pg.evaluate(f"setActiveGarment('{tee}')")
    _expect_panel(pg, tee)
    pg.evaluate(f"setActiveGarment('{skirt}')")
    assert pg.evaluate(_PANEL)["pane"] == "design" and pg.evaluate("document.querySelector('#inspector').textContent.length") > 0
    # an empty garment opens the picker; a drafted one goes back to its pattern; the empty one to the picker again
    pg.evaluate("document.querySelector('#addGarment').click()")
    pg.click('#addGarmentMenu [data-ga="blank"]')
    empty = pg.evaluate(f"{ST}.PROJECT.activeGarmentId")
    assert pg.evaluate(_PANEL)["pane"] == "garment"
    pg.evaluate(f"setActiveGarment('{tee}')")
    _expect_panel(pg, tee)
    pg.evaluate(f"setActiveGarment('{empty}')")
    assert pg.evaluate(_PANEL)["pane"] == "garment"
    # on Try on, switching stays on Try on (each garment's own fabric)
    pg.evaluate(f"setActiveGarment('{tee}'); {ST}.go('preview')")
    pg.evaluate(f"setActiveGarment('{skirt}')")
    assert pg.evaluate(f"{ST}.ST.step") == "preview"
    assert not pg.errors, pg.errors


def test_a_drafted_pattern_has_no_3d_view_and_basic_patterns_come_first(page):
    pg = page
    _ensure_avatar(pg)
    _go_garment(pg, "tee")
    for mode in ("beg", "adv"):                                       # Simple and Advanced alike
        pg.click(f"#mode [data-m={mode}]")
        assert not pg.locator("#glcard").is_visible(), mode
        assert pg.locator("#patcard").is_visible()
    pg.evaluate(f"{ST}.go('garment')")
    pg.wait_for_timeout(300)
    assert pg.evaluate("document.querySelector('#gcards').compareDocumentPosition(document.querySelector('#scards')) & 4")
    assert pg.locator("#gcards").bounding_box()["y"] < pg.locator("#scards").bounding_box()["y"]
    pg.click(f'#gcards [data-k="tee"]')
    assert not pg.errors, pg.errors


# ------------------------------------------------------------------ phase 4: frozen garments as colliders
def _fake_cloth(pg, z=0.35):
    """A small draped-looking mesh for the page: a 40 x 60 cm sheet in front of the avatar (b64 like a drape)."""
    return pg.evaluate(f"""(() => {{
        const nx = 9, ny = 13, V = new Int16Array(nx * ny * 3), F = [];
        for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {{ const k = (j * nx + i) * 3; V[k] = -200 + 50 * i; V[k + 1] = 700 + 50 * j; V[k + 2] = {int(z * 1000)} }}
        for (let j = 0; j < ny - 1; j++) for (let i = 0; i < nx - 1; i++) {{ const a = j * nx + i; F.push(a, a + 1, a + nx, a + 1, a + nx + 1, a + nx) }}
        const b64 = u => btoa(String.fromCharCode(...new Uint8Array(u.buffer)));
        const P = new Uint8Array(nx * ny * 3).fill(180);
        return {{v: b64(V), f: b64(new Uint32Array(F)), panel: b64(P), nv: nx * ny, nf: F.length / 3}};
    }})()""")


def test_freeze_needs_a_drape_then_goes_with_the_next_drape_and_into_the_file(page):
    pg = page
    _two_garments(pg)                                               # skirt (L2) active, tee (L1)
    tee = pg.evaluate(f"{ST}.PROJECT.garments.find(g => g.block === 'tee').id")
    pg.click(f'#glist .grow[data-id="{tee}"] [data-act=freeze]')    # no drape yet: it can't freeze
    assert pg.evaluate(f"{ST}.PROJECT.garments.find(g => g.id === '{tee}').frozen") is False
    assert "Drape" in pg.inner_text("#toast")
    cloth = _fake_cloth(pg)
    pg.evaluate(f"garmentBy('{tee}').drape = {{cloth: {json.dumps(cloth)}}}")
    pg.click(f'#glist .grow[data-id="{tee}"] [data-act=freeze]')
    assert pg.evaluate(f"garmentBy('{tee}').frozen") is True
    req = pg.evaluate(f"colliderReq({json.dumps(pg.evaluate(f'{ST}.PROJECT.activeGarmentId'))})")
    assert len(req["colliders"]) == 1 and req["colliders"][0]["v"] == cloth["v"]
    saved = pg.evaluate("project()")
    g = next(x for x in saved["garments"] if x["id"] == tee)
    assert g["frozen"] and g["frozenMesh"]["v"] == cloth["v"]       # it keeps its shape in the file
    pg.evaluate(f"garmentBy('{tee}').visible = false")                # hidden: not a collider
    assert pg.evaluate(f"colliderReq('x')") == {}
    pg.evaluate(f"garmentBy('{tee}').visible = true")
    pg.evaluate(f"setActiveGarment('{tee}')")
    pg.evaluate("startDrape()")                                       # a frozen garment doesn't drape
    assert "frozen" in pg.inner_text("#toast")
    assert not pg.errors, pg.errors


def test_clicking_a_dimmed_garment_in_3d_selects_it(page):
    pg = page
    _two_garments(pg)
    tee = pg.evaluate(f"{ST}.PROJECT.garments.find(g => g.block === 'tee').id")
    cloth = _fake_cloth(pg, z=0.40)                                   # a sheet in front of the avatar
    pg.evaluate(f"garmentBy('{tee}').drape = {{cloth: {json.dumps(cloth)}}}")
    pg.evaluate(f"{ST}.go('preview')")
    pg.evaluate("refreshScene(); GL.setView({yaw: 0, pitch: 0})")
    pg.wait_for_timeout(400)
    # click where the sheet is: scan for a point that hits it
    pts = pg.evaluate("""(() => { const r = document.querySelector('#gl').getBoundingClientRect(), out = [];
        for (let y = r.top + 20; y < r.bottom - 20; y += 10) for (let x = r.left + 20; x < r.right - 20; x += 10) out.push([x, y]); return out })()""")
    for x, y in pts:
        pg.mouse.click(x, y)
        if pg.evaluate(f"{ST}.PROJECT.activeGarmentId") == tee:
            break
    assert pg.evaluate(f"{ST}.PROJECT.activeGarmentId") == tee
    assert not pg.errors, pg.errors


def test_the_collider_field_is_negative_under_a_garment_and_positive_outside_and_past_its_edge():
    from drape.colliders import garment_field
    from drape.studio import server as S
    init = S.api_init()
    a = S.api_avatar({"measurements": init["examples"]["female_M"]})
    body = S.S.avatars[a["id"]]["body"]
    # a tube round the torso, 3 cm off the skin at the waist, from hip to bust height
    y0, y1 = body.lines["hip"], body.lines["chest"]
    th = np.linspace(0, 2 * np.pi, 48, endpoint=False)
    rings = []
    for y in np.linspace(y0, y1, 12):
        r = (body.girth_at_y(y) / (2 * np.pi)) + 0.03
        rings.append(np.stack([r * np.cos(th), np.full_like(th, y), r * np.sin(th) + body.torso_center_z()], 1))
    V = np.concatenate(rings)
    F = []
    for j in range(len(rings) - 1):
        for i in range(48):
            a0, a1, b0, b1 = j * 48 + i, j * 48 + (i + 1) % 48, (j + 1) * 48 + i, (j + 1) * 48 + (i + 1) % 48
            F += [[a0, a1, b0], [a1, b1, b0]]
    F = np.array(F)
    ym = 0.5 * (y0 + y1)
    r = body.girth_at_y(ym) / (2 * np.pi) + 0.03
    z0 = body.torso_center_z()
    h = 0.004
    xs = np.arange(-0.4, 0.4 + h, h); ys = np.arange(y0 - 0.15, y1 + 0.05, h); zs = np.arange(z0 - 0.4, z0 + 0.4 + h, h)
    grid = garment_field(V, F, body, xs, ys, zs, thickness=0.0015)
    from drape.meshbody import grid_sdf_batch
    s = lambda p: float(grid_sdf_batch(np.array([p], float), grid, np.array([xs[0], ys[0], zs[0]]), h)[0])
    assert s([r - 0.01, ym, z0]) < 0                        # 1 cm under it (the body's side)
    assert s([r + 0.01, ym, z0]) > 0                        # 1 cm outside
    assert s([r - 0.005, y0 - 0.08, z0]) > 0                # below its edge: not under it


def test_a_dress_drapes_over_frozen_leggings_without_going_through():
    """The spec's acceptance test, on the GPU (the website's drape): leggings draped and frozen, then a dress over
    them; none of the dress's points end up under the leggings by more than 1 mm (without the leggings as a
    collider: hundreds do). tools/layer_check.py"""
    gpu = pytest.importorskip("drape.gpu")
    ok, why = gpu.gpu_info()
    if not ok:
        pytest.skip(why)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import layer_check
    layer_check.GPU, layer_check.NOCOLL = True, False
    assert layer_check.main() == 0


# ------------------------------------------------------------------ phase 5: export
def test_patterns_export_for_the_active_garment_or_every_garment(page):
    pg = page
    _two_garments(pg)                                                    # tee + skirt (active)
    pg.evaluate(f"{ST}.go('export')")
    pg.wait_for_function("!document.querySelector('#multiOpts').hidden", timeout=60000)
    assert pg.inner_text("#multiActive") == "Skirt"
    with pg.expect_download() as dl:                                     # default: the active garment
        pg.evaluate("doExport('dxf')")
    assert dl.value.suggested_filename.startswith("Skirt - ") and dl.value.suggested_filename.endswith(".dxf")
    pg.check("#allGarments")
    names = []
    pg.on("download", lambda d: names.append(d.suggested_filename))
    pg.evaluate("doExport('dxf')")
    pg.wait_for_function("true", timeout=1000)
    for _ in range(60):
        if len(names) >= 2:
            break
        pg.wait_for_timeout(500)
    assert sorted(n.split(" - ")[0] for n in names) == ["Skirt", "Tee"], names
    pg.uncheck("#allGarments")
    assert not pg.errors, pg.errors


def test_3d_export_of_the_whole_outfit():
    """Two drapes (quick, on the CPU) and a glb / obj holding both garments."""
    import time
    from drape.studio import server as S
    init = S.api_init()
    a = S.api_avatar({"measurements": init["examples"]["female_M"]})
    jobs = []
    for req in ({"block": "trousers", "choices": {"Fit": "Slim"}}, {"block": "tee"}):
        jid = S.api_drape({"avatar": a["id"], **req, "fabric": "jersey", "quality": "quick", "seconds": 1.5})["job"]
        while S.api_job(jid)["state"] == "running":
            time.sleep(1)
        assert S.api_job(jid)["state"] == "done"
        jobs.append(jid)
    one = S.api_export({"avatar": a["id"], "block": "tee", "kind": "glb", "job": jobs[1], "fabric": "jersey"})
    both = S.api_export({"avatar": a["id"], "block": "tee", "kind": "glb", "job": jobs[1], "fabric": "jersey",
                         "outfit": [{"job": jobs[0], "fabric": "jersey", "name": "Leggings"}]})
    assert b"Leggings: " in both[2] and b"Leggings: " not in one[2] and len(both[2]) > len(one[2])
    o1 = S.api_export({"avatar": a["id"], "block": "tee", "kind": "obj", "job": jobs[1]})
    o2 = S.api_export({"avatar": a["id"], "block": "tee", "kind": "obj", "job": jobs[1], "outfit": [{"job": jobs[0], "name": "Leggings"}]})
    assert o2[2].count(b"\nf ") > o1[2].count(b"\nf ")
