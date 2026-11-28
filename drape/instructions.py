"""Sewing instructions generated from a garment's actual seams, in the order
a sewist would do them, in plain language.

Order (standard construction): darts -> shoulders -> set in sleeves ->
side seams + sleeve underarms in one pass -> centre / crotch seams for
trousers (legs first) -> finish neckline / armholes / waist -> hems.
"""
from __future__ import annotations

PRETTY = {"side": "side seam", "underarm": "underarm seam", "cap": "sleeve cap", "arm": "armhole",
          "shoulder": "shoulder", "dart": "dart", "bust": "bust dart", "centre": "centre seam",
          "crotch": "crotch curve", "inseam": "inseam", "outseam": "outside leg seam", "hem": "hem",
          "neck": "neckline", "waist": "waist"}


def _kind(edge):
    e = edge.lower()
    for k in ("bust", "dart", "cap", "underarm", "shoulder", "side", "crotch", "centre", "inseam", "outseam", "arm"):
        if k in e:
            return k
    return "other"


def _piece(name):
    n = name.replace("_r", " (right)").replace("_l", " (left)")
    return n.replace("_", " ")


def instructions(g, sa_cm=1.5, fabric=None) -> list[dict]:
    """[{title, text, seams: [seam names]}] for the studio and the PDF."""
    seams = g.meta["seam_defs"]
    panels = g.meta["panels"]
    steps = []
    names = [p.name for p in panels]
    steps.append(dict(title="Cut", seams=[], text=(
        f"Cut {len(panels)} pieces: " + ", ".join(_piece(n) for n in names) +
        f". Seam allowance is {sa_cm:g} cm ({sa_cm / 2.54:.2g} in) on every edge, already included in the "
        "cut line. Keep the grain arrow parallel to the fabric's selvedge. Snip the little notches: they "
        "line up with the matching notch on the piece it's sewn to.")))
    groups = {}
    for s in seams:
        k = _kind(s.edge_a)
        if s.panel_a == s.panel_b and k in ("dart", "bust"):
            k = "dart"
        groups.setdefault(k, []).append(s)

    def add(k, title, text):
        if k in groups:
            steps.append(dict(title=title, text=text, seams=[s.name for s in groups[k]]))

    add("dart", "Sew the darts", "Fold each dart in half, right sides together, matching the two lines. "
        "Sew from the wide end to the point, ending right at the edge of the fold; don't backstitch at the "
        "point, tie the threads instead. Press the dart toward the centre (or down for bust darts).")
    add("shoulder", "Sew the shoulders", "Front to back at the shoulders, right sides together. Press the "
        "seams open or toward the back.")
    if "cap" in groups:
        steps.append(dict(title="Set in the sleeves", seams=[s.name for s in groups["cap"]], text=(
            "Match the sleeve's top (crown) to the shoulder seam and the sleeve's underarm corners to the "
            "body's side seams. The sleeve edge is a little longer than the armhole on purpose: that's "
            "'ease'. Sew a long basting stitch along the sleeve cap and pull it gently to gather it in "
            "evenly before you sew, with the sleeve on top.")))
    if "side" in groups or "underarm" in groups:
        steps.append(dict(title="Side seams" + (" and sleeve seams" if "underarm" in groups else ""),
                          seams=[s.name for s in groups.get("side", []) + groups.get("underarm", [])],
                          text="Right sides together, sew from the hem up the side, through the armpit"
                               + (" and down the sleeve to the cuff, in one go" if "underarm" in groups else "")
                               + ". Line up the armpit seams exactly."))
    if "outseam" in groups or "inseam" in groups:
        steps.append(dict(title="Sew each leg", seams=[s.name for s in groups.get("outseam", []) + groups.get("inseam", [])],
                          text="For each leg, sew front to back along the outside leg seam and the inseam. "
                               "You now have two tubes."))
    if "crotch" in groups or "centre" in groups:
        steps.append(dict(title="Join the legs (crotch seam)", seams=[s.name for s in groups.get("centre", []) + groups.get("crotch", [])],
                          text="Turn one leg right side out and slip it inside the other (right sides "
                               "together). Sew the crotch in one continuous seam from the front waist, down "
                               "and under, up to the back waist, matching the inseams. Sew it twice: it takes "
                               "the most strain. Clip the curve so it lies flat."))
    if "other" in groups:    # hand-made designs: seams with your own edge names
        steps.append(dict(title="Sew the seams", seams=[s.name for s in groups["other"]], text=(
            "Right sides together, sew each pair: " + "; ".join(
                f"{_piece(s.panel_a)} '{s.edge_a}' to {_piece(s.panel_b)} '{s.edge_b}'"
                + (" (gather the first one to fit)" if s.ease > 0.01 else "") for s in groups["other"])
            + ". Press each seam open before crossing it with another.")))
    elastic = g.meta.get("elastic")
    if elastic:
        steps.append(dict(title="Add the elastic", seams=[], text=(
            "Fold each elastic edge over twice to make a casing a little wider than your elastic, stitch "
            "it down leaving a 3 cm gap, thread the elastic through with a safety pin, try it on, overlap "
            "the ends 2 cm and zigzag them together, then close the gap. Cut the elastic to " +
            ", ".join(f"{e['elastic_cm'] + 2:.0f} cm ({(e['elastic_cm'] + 2) / 2.54:.1f} in)" for e in elastic) +
            " (2 cm of that is the overlap)." + "")))
    # pockets inside the garment, then closures
    if any(p.name.startswith("pocket_bag") for p in panels):
        steps.append(dict(title="In-seam pockets", seams=[], text=(
            "Before sewing the side seam: sew a pocket bag to the front and one to the back along the "
            "marked opening, right sides together, and press them out. Then sew the side seam above and "
            "below the opening, pivot and sew round the two bags together. Press the bags toward the front.")))
    if any("yoke" in p.name for p in panels):
        steps.append(dict(title="Front hip pockets", seams=[], text=(
            "Face the curved pocket opening on the front (a strip of lining or the pocket bag), understitch "
            "and topstitch it. Lay the front on the pocket yoke, matching the waist and side edges, and stitch "
            "the bag closed behind it. Baste the yoke to the front at the waist and side: from here on it's "
            "one piece.")))
    for c in g.meta.get("closures", []):
        a, b = (x.replace("_", " ") for x in c["seam"])
        if c["type"] == "zipper":
            steps.append(dict(title="Put in the zipper", seams=[], text=(
                f"Use a {c['zip_cm']:g} cm ({c['zip_cm'] / 2.54:.0f} in) zipper between {a} and {b}. Sew the "
                "seam below the zipper-stop mark, baste the opening closed, press it open, centre the zipper "
                "face down on it and sew both sides with a zipper foot; unpick the basting.")))
        elif c["type"] == "buttons":
            steps.append(dict(title="Buttonholes and buttons", seams=[], text=(
                f"{c['count']} × {c['size_mm']:g} mm buttons. Fold the facing back along the fold line and "
                f"interface it. Sew {c['count']} buttonhole{'s' if c['count'] > 1 else ''} "
                f"{c['size_mm'] + 3:g} mm long on {a} at the marks, then lap it over {b} with the centre "
                "lines matching and sew the buttons on the marks.")))
        elif c["type"] == "snaps":
            steps.append(dict(title="Snaps", seams=[], text=(
                f"{c['count']} × {c['size_mm']:g} mm snaps: sockets on {b}, studs on {a}, at the marks, "
                "through the folded-back facing.")))
        elif c["type"] == "hook_loop":
            steps.append(dict(title="Hook & loop tape", seams=[], text=(
                f"Fold the facings back. Sew the soft (loop) side to the inside of {a} and the hook side to "
                f"the outside of {b}, round all four edges, inside the marked strips.")))
    # free edges -> finishing
    seamed = {(s.panel_a, s.edge_a) for s in seams} | {(s.panel_b, s.edge_b) for s in seams}
    free = {}
    for p in panels:
        for n, _ in p.edges:
            if (p.name, n) not in seamed:
                free.setdefault(_kind(n) if _kind(n) != "other" else n.split("_")[0], []).append(f"{p.name}.{n}")
    if "neck" in free:
        steps.append(dict(title="Finish the neckline", seams=[], text=(
            "Knits: a neckband ~85% the length of the neckline, folded in half, stretched evenly as you sew. "
            "Wovens: a facing or bias binding. Understitch so it rolls to the inside.")))
    if "arm" in free:
        steps.append(dict(title="Finish the armholes", seams=[], text="Bias binding or a facing, as for the neckline."))
    if "waist" in free and not elastic:
        steps.append(dict(title="Finish the waist", seams=[], text=(
            "Add a waistband or an elastic casing (fold the top edge down 1 cm, then by the elastic's width + "
            "0.5 cm, sew, thread elastic cut to about 90% of your waist). Wovens without elastic need a zip "
            "or opening: put it in the centre back seam or a side seam before sewing that seam closed.")))
    from .hems import STYLES
    hemmed = {}                   # hems cut on (hems.py): exact steps per style and size
    for p in panels:
        for en, hm in (getattr(p, "hems", None) or {}).items():
            hemmed.setdefault((hm["style"], hm["depth_cm"], hm["turn_cm"]), []).append(f"{p.name}.{en}")
    for (style, depth, turn), refs in hemmed.items():
        st = STYLES.get(style, STYLES["double"])
        size = f"{depth:g} cm deep" + (f", {turn:g} cm turned under first" if turn else "")
        steps.append(dict(title=st["label"] + ("s" if len(refs) > 1 and style != "casing" else ""), seams=[], text=(
            f"{', '.join(refs)}: {size}. The fold lines are marked on the pattern. {st['how']}")))
    if not hemmed or any((p.name, n) not in seamed and not (getattr(p, "hems", None) or {}).get(n)
                         and _kind(n) == "hem" for p in panels for n, _ in p.edges):
        steps.append(dict(title="Hems", seams=[], text=(
            "Press up the hem allowance, tuck the raw edge under, and stitch. Knits: a twin needle or zigzag so "
            "the hem can still stretch.")))
    for i, s in enumerate(steps, 1):
        s["n"] = i
    return steps
