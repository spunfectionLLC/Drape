"""Laser-cut parts for the drape fabric tester (3 mm plywood or acrylic).
Writes hardware/fabric_tester/tester_jig_3mm.dxf: CUT layer red, ENGRAVE blue, mm.
    python tools/make_tester_jig.py
"""
from pathlib import Path

import ezdxf
import numpy as np

OUT = Path(__file__).resolve().parents[1] / "hardware" / "fabric_tester" / "tester_jig_3mm.dxf"
doc = ezdxf.new("R2010")
doc.units = ezdxf.units.MM
doc.layers.add("CUT", color=1)
doc.layers.add("ENGRAVE", color=5)
msp = doc.modelspace()


def rect(x, y, w, h, layer="CUT"):
    msp.add_lwpolyline([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], close=True, dxfattribs={"layer": layer})


def hole(x, y, d, layer="CUT"):
    msp.add_circle((x, y), d / 2, dxfattribs={"layer": layer})


def slot(x, y, length, w, layer="CUT"):      # rounded slot along x from (x, y) centre-line
    r = w / 2
    msp.add_line((x, y - r), (x + length, y - r), dxfattribs={"layer": layer})
    msp.add_line((x, y + r), (x + length, y + r), dxfattribs={"layer": layer})
    msp.add_arc((x, y), r, 90, 270, dxfattribs={"layer": layer})
    msp.add_arc((x + length, y), r, -90, 90, dxfattribs={"layer": layer})


def text(s, x, y, h=4, layer="ENGRAVE"):
    msp.add_text(s, dxfattribs={"layer": layer, "height": h, "insert": (x, y)})


def hexagon(x, y, af):     # nut trap: across flats
    r = af / np.sqrt(3)
    pts = [(x + r * np.cos(np.radians(30 + 60 * k)), y + r * np.sin(np.radians(30 + 60 * k))) for k in range(6)]
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "CUT"})


M4, M3, M8 = 4.3, 3.3, 8.4
# 1 base plate 320 x 90
rect(0, 0, 320, 90)
for x, y in ((8, 8), (312, 8), (8, 82), (312, 82)):
    hole(x, y, M4)
hole(25, 30, M4); hole(25, 60, M4)                      # fixed jaw
slot(70, 45, 170, M4)                                   # carriage guide (2 bolts ride in it)
rect(110, 70, 106, 6)                                   # slide pot knob window (pot under the plate)
hole(104, 73, M3); hole(222, 73, M3)
rect(296, 25, 3.2, 20); rect(296, 50, 3.2, 20)          # crank upright tabs
text("drape fabric tester  -  base", 70, 12, 5)
text("FIXED JAW", 14, 76, 3.5)
for k in range(0, 171, 10):                             # travel scale along the guide slot
    msp.add_line((70 + k, 52), (70 + k, 55 if k % 50 else 58), dxfattribs={"layer": "ENGRAVE"})
# 2-5 jaws: 4 plates 70 x 30 (fixed pair + moving pair), rubber strip glued on the inside faces
for i in range(4):
    ox = 0 + i * 78
    rect(ox, 100, 70, 30)
    hole(ox + 12, 115, M4); hole(ox + 58, 115, M4)
    text("FIXED" if i < 2 else "MOVING", ox + 22, 104, 3.5)
# 6 carriage 80 x 60
rect(0, 140, 80, 60)
hole(20, 170, M4); hole(60, 170, M4)                    # guide bolts (40 mm apart, same slot)
hole(15, 152, M4); hole(65, 152, M4)                    # moving jaw
hole(32.5, 188, M4); hole(47.5, 188, M4)                # load cell (bar 5 kg, 15 mm hole pitch)
hole(40, 152, M3)                                       # pot knob link
text("CARRIAGE", 22, 194, 3.5)
# 7 crank upright 90 x 60 with tabs, M8 lead screw hole
msp.add_lwpolyline([(90, 140), (100, 140), (100, 137), (120, 137), (120, 140), (125, 140), (125, 137), (145, 137),
                    (145, 140), (180, 140), (180, 200), (90, 200)], close=True, dxfattribs={"layer": "CUT"})
hole(135, 175, M8)
text("CRANK", 120, 190, 3.5)
# 8 nut block 40 x 40: M8 nut trap, glued behind the load cell's free end
rect(190, 140, 40, 40); hexagon(210, 160, 13.2)
hole(202.5, 147, M4); hole(217.5, 147, M4)
text("NUT", 203, 174, 3)
# 9 crank handle 70 x 20
msp.add_lwpolyline([(240, 150), (300, 150), (310, 160), (300, 170), (240, 170), (230, 160)], close=True,
                   dxfattribs={"layer": "CUT"})
hexagon(240, 160, 13.2); hole(298, 160, M4)
# 10 bending (droop) platform 220 x 60: overhang ruler, 0 at the front edge
rect(0, 215, 220, 60)
for k in range(0, 151, 5):
    y0 = 275
    L = 8 if k % 10 else 14
    msp.add_line((220 - k, y0), (220 - k, y0 - L), dxfattribs={"layer": "ENGRAVE"})
    if k % 20 == 0:
        text(f"{k // 10}", 220 - k - 2, y0 - 22, 4)
text("DROOP TEST: strip 5 cm wide, push out to 10 cm, read the drop on the scale", 4, 222, 3.2)
rect(30, 238, 3.2, 25)                                  # slot for the scale plate
# 11 vertical scale plate 140 x 40 (stands in the slot, 0 at the table top)
rect(0, 285, 40, 140)
for k in range(0, 121, 2):
    y = 285 + 140 - 10 - k
    L = 6 if k % 10 else 14
    msp.add_line((0, y), (L, y), dxfattribs={"layer": "ENGRAVE"})
    if k % 20 == 0:
        text(f"{k // 10}", 16, y - 1.5, 3.5)
text("cm down", 22, 290, 3)
# 12 templates: 10 x 10 cm weighing square, strip 50 x 140 (100 gauge + 2 x 20 in the jaws)
rect(60, 285, 100, 100); text("10 x 10 cm: weigh it (g)", 70, 330, 4)
rect(175, 285, 50, 140)
msp.add_line((175, 305), (225, 305), dxfattribs={"layer": "ENGRAVE"})
msp.add_line((175, 405), (225, 405), dxfattribs={"layer": "ENGRAVE"})
text("JAW", 192, 297, 3); text("JAW", 192, 412, 3); text("100 mm gauge", 180, 355, 3.2)
# bias guide: a 45 degree line to lay on the selvage
msp.add_line((240, 285), (340, 385), dxfattribs={"layer": "ENGRAVE"})
msp.add_line((240, 285), (340, 285), dxfattribs={"layer": "CUT"})
msp.add_line((340, 285), (340, 385), dxfattribs={"layer": "CUT"})
msp.add_line((240, 285), (340, 385), dxfattribs={"layer": "CUT"})
text("45 deg: BIAS", 290, 300, 4)
OUT.parent.mkdir(parents=True, exist_ok=True)
doc.saveas(OUT)
print("wrote", OUT)
