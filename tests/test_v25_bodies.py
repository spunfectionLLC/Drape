"""Every body is valid (2026-11-24, CLAUDE.md "Bodies"): the measurement checks catch typos (inches typed
as cm, a tape taken round instead of across) and never judge a body's size or proportions."""
import dataclasses
from pathlib import Path

from drape.measurements import Measurements

ROOT = Path(__file__).resolve().parents[1]


def test_larger_and_smaller_bodies_get_no_warnings():
    m = Measurements()
    for kw in (dict(height=165, chest=140, waist=150, hip=160, upper_arm=52, neck=48, thigh=85),   # larger body
               dict(height=190, chest=190, waist=200, hip=190, upper_arm=60, neck=55),
               dict(height=150, chest=78, waist=58, hip=82),                                          # small and slim
               dict(height=110, chest=90, waist=90, hip=95)):                                          # short stature
        w = dataclasses.replace(m, **kw).validate()
        assert w == [], (kw, w)


def test_typos_are_still_caught_and_worded_about_the_number():
    m = Measurements()
    for kw, word in ((dict(height=66), "Height"), (dict(waist=30), "Waist"), (dict(inseam=30), "Inseam")):
        w = dataclasses.replace(m, **kw).validate()
        assert len(w) == 1 and w[0].startswith(word) and "inches" in w[0], w


def test_no_body_judging_words_in_messages():
    src = (ROOT / "drape" / "measurements.py").read_text(encoding="utf-8")
    body = src[src.index("def validate"):src.index("return w", src.index("def validate"))]
    for bad in ("unusual", "too large", "too big", "too small", "abnormal", "looks wrong", "ratio"):
        assert bad not in body.lower().split('"""')[-1], bad
    js = (ROOT / "drape" / "studio" / "static" / "js" / "02_body.js").read_text(encoding="utf-8")
    assert "limit of the avatar, not your numbers" in js


def _fit(**kw):
    from drape.human import fit_human
    m = Measurements(**kw)
    for k in ("shoulder_width", "neck", "upper_arm", "arm_length"):     # on auto, as the studio sends them
        setattr(m, k, None)
    h, rows = fit_human(m)
    return h, {r["measurement"]: r for r in rows}


def test_larger_bodies_reach_their_numbers():
    """MakeHuman's own shapes stopped at a 92 cm waist for a 150 cm one; the avatar now reaches it (a belly
    where the waist is past MakeHuman's range, measured round the middle). tools/avatar_range.py"""
    for kw in (dict(sex="female", height=165, chest=140, waist=150, hip=160),
               dict(sex="male", height=178, chest=150, waist=160, hip=150)):
        h, R = _fit(**kw)
        for k in ("chest", "waist", "hip"):
            assert abs(R[k]["avatar_cm"] - kw[k]) < 5.0, (kw, k, R[k]["avatar_cm"])
        assert h.shape.widen and h.shape.widen["belly"] > 0


def test_bodies_in_makehumans_range_are_unchanged():
    """No belly for a body MakeHuman reaches on its own: the avatar is exactly the morph fit."""
    h, R = _fit(sex="female", height=166, chest=92, waist=74, hip=100)
    assert not h.shape.widen
    for k in ("chest", "waist", "hip"):
        assert abs(R[k]["error_cm"]) < 0.5
