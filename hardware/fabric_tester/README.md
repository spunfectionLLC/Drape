# drape fabric tester

Measures a fabric the way the simulator needs it: how it stretches along the
grain, across it and on the bias, where it stops giving (lock strain), and
(with the droop platform) how stiff it is to bend. About $25 of parts and a
3 mm sheet through the laser.

## Parts

| Qty | Part | Notes |
|---|---|---|
| 1 | ESP32 DevKit (any) | USB to the computer running drape studio |
| 1 | 5 kg bar load cell + HX711 board | the common "TAL220 / HX711" kit |
| 1 | 10 kΩ slide potentiometer, 100 mm travel | e.g. Bourns PTA6043 / generic 100 mm |
| 1 | M8 threaded rod, 150 mm, + 3 M8 nuts | the crank's lead screw |
| 10 | M4 × 16 bolts + nuts, 2 M3 × 10 | jaws, carriage, pot |
| 1 | strip of rubber (bike inner tube) | glued on the jaw faces: grips without tearing |
| opt. | VL53L0X time-of-flight sensor | reads the droop test automatically |
| 1 | 3 mm plywood or acrylic, 350 × 450 mm | `tester_jig_3mm.dxf`: red = cut, blue = engrave |

## Build

1. Cut `tester_jig_3mm.dxf` (red layer cut, blue layer engrave / score).
2. Screw the slide pot under the base, knob up through the window. Link the
   knob to the carriage's small hole with a bent paperclip or an M3 standoff.
3. Bolt the fixed jaw pair to the base, rubber faces inward.
4. Put two M4 bolts down through the carriage into the guide slot (nuts under,
   snug but sliding). Bolt the moving jaw pair to the carriage's front holes.
5. Bolt one end of the load cell to the carriage's rear holes; glue the nut
   block to its free end. Thread the M8 rod through the crank upright (two nuts
   lock it to the handle side) into the nut block: turning the crank pulls the
   load cell, which pulls the carriage.
6. Wire as in `fabric_tester.ino`, flash it (Arduino IDE, board "ESP32 Dev
   Module", library "HX711" by Bogdan Necula).
7. Calibrate once: with nothing in the jaws send `t` (tare), hang a known
   weight from the moving jaw (a 500 g bag of rice, a 1 L water bottle = 1000 g)
   with the jig stood on its end, send `c 500`. It's remembered.

## Test a fabric

1. Weigh a 10 × 10 cm square (template on the sheet).
2. Droop: lay a 5 cm wide strip on the droop platform, slide it out to the 10 cm
   mark, read how far the tip hangs down on the upright scale.
3. Cut three 50 × 140 mm strips with the strip template: along the grain
   (warp), across it (weft) and at 45° (bias, use the triangle on the selvage).
4. In drape studio: Try on → Fabric → **+ My fabric** → **Fabric tester**.
   Connect (Chrome/Edge: Web Serial), clamp the warp strip with 20 mm in each
   jaw (100 mm between them), press **Zero**, then **Record** and turn the crank
   slowly until the strip has stretched a few percent (wovens) or about 30 %
   (knits). Stop. Repeat for weft and bias.
5. **Make my fabric**: drape fits the curves (stiffness, anisotropy, the strain
   where the yarns lock up), runs the droop test in the simulator for bending,
   and adds the fabric to your list.

No Web Serial (Firefox, Safari)? Use any serial monitor, copy the
`ms,ext_mm,force_N` lines into a .csv per strip and load them in the same
dialog.
