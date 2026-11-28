"""Fabric presets.

Weights are typical fabric weights (g/m^2 -> kg/m^2). Bending and stretch
are compliances (1 / stiffness: bigger = softer) at the default 15 mm mesh spacing;
the solver turns them into spring and bending stiffness (cloth.spring_k).
Anisotropy (weft_ratio, bias_ratio: how much softer across the grain and on
the bias) and the lock strain (where the yarns straighten and it stops giving)
follow the usual behaviour of each construction: wovens barely stretch on the
grain but shear on the bias; knits stretch crosswise.
Bending is set from typical published bending lengths (cantilever test,
ASTM D1388: chiffon ~1 cm ... canvas ~5.5 cm) by running that same test in
the simulator (calibrate.bend_for_bending_length). Stretch is tuned by eye.
Measure your own fabric with calibrate.calibrate (the studio's "My fabrics").
'jersey' is the default every result in the README was measured with.
"""
from .cloth import Fabric, spring_k

FABRICS = {
    #                   name                density  stretch  bend    thick   self    friction damping
    "jersey":   Fabric("cotton jersey",      0.15,   1e-7, 2e6,     0.004,  0.003,  0.40,   0.02, weft_ratio=4.0, bias_ratio=3.0, lock_strain=0.3),
    "poplin":   Fabric("cotton poplin",      0.12,   2e-8, 2.8e5,   0.004,  0.003,  0.40,   0.02, weft_ratio=1.5, bias_ratio=8.0, lock_strain=0.04),
    "denim":    Fabric("12 oz denim",        0.40,   1e-8, 1.5e4,   0.005,  0.004,  0.50,   0.03, weft_ratio=1.3, bias_ratio=6.0, lock_strain=0.03),
    "canvas":   Fabric("cotton canvas",      0.35,   1e-8, 8.6e3,   0.005,  0.004,  0.50,   0.03, weft_ratio=1.2, bias_ratio=5.0, lock_strain=0.03),
    "fleece":   Fabric("polyester fleece",   0.25,   2e-7, 1.4e5,   0.006,  0.005,  0.60,   0.03, weft_ratio=2.5, bias_ratio=2.0, lock_strain=0.4),
    "silk":     Fabric("silk charmeuse",     0.08,   5e-8, 6e6,     0.003,  0.0025, 0.20,   0.01, weft_ratio=1.5, bias_ratio=10.0, lock_strain=0.05),
    "chiffon":  Fabric("poly chiffon",       0.05,   5e-8, 3e7,     0.003,  0.0025, 0.25,   0.01, weft_ratio=1.5, bias_ratio=10.0, lock_strain=0.05),
    "rib":      Fabric("cotton rib knit",    0.22,   6e-7, 3e5,     0.005,  0.004,  0.45,   0.03, weft_ratio=12.0, bias_ratio=5.0, lock_strain=0.6),
    "lining":   Fabric("poly lining",        0.07,   3e-8, 1e7,     0.003,  0.0025, 0.15,   0.01, weft_ratio=1.3, bias_ratio=8.0, lock_strain=0.04),
    "flannel":  Fabric("cotton flannel",     0.17,   3e-8, 1.7e5,   0.005,  0.004,  0.50,   0.02, weft_ratio=1.5, bias_ratio=8.0, lock_strain=0.05),
}

def _add_user_fabrics():
    """Fabrics you measured (studio: My fabrics), kept in ~/.drape/fabrics.json."""
    try:
        from .calibrate import load_user_fabrics
        FABRICS.update(load_user_fabrics())
    except Exception:
        pass


_add_user_fabrics()

# Interfacing is fused (ironed) onto a piece: the two act as one sheet.
INTERFACINGS = {
    "light":  Fabric("light fusible (shirt collars, facings)", 0.03, 5e-8, 6e5, 0, 0, 0, 0),
    "medium": Fabric("medium fusible (waistbands, cuffs)",     0.06, 2e-8, 8e4, 0, 0, 0, 0),
    "knit":   Fabric("knit fusible (stays stretchy)",          0.04, 4e-7, 3e5, 0, 0, 0, 0),
    "heavy":  Fabric("heavy fusible / canvas (bags, brims)",   0.12, 8e-9, 5e3, 0, 0, 0, 0),
}


def fused(base: Fabric, interfacing: Fabric) -> Fabric:
    """A fabric with interfacing fused to it. Stiffnesses of bonded layers add
    (compliances combine like springs in parallel); a laminate bends much
    stiffer than its layers apart, so bending gets an extra factor 2."""
    par = lambda a, b: 1.0 / (1.0 / a + 1.0 / b)
    return Fabric(f"{base.name} + {interfacing.name.split(' (')[0]}", base.density + interfacing.density,
                  par(base.stretch_compliance, interfacing.stretch_compliance),
                  0.5 * par(base.bend_compliance, interfacing.bend_compliance),
                  base.thickness, base.self_thickness, base.friction, base.damping,
                  weft_ratio=base.weft_ratio, bias_ratio=base.bias_ratio,
                  lock_strain=min(base.lock_strain, 0.05),     # fused interfacing is woven-like: it locks early
                  stretch_k=spring_k(base) + spring_k(interfacing))   # springs solver: bonded layers add


def get(name: str) -> Fabric:
    try:
        return FABRICS[name.lower()]
    except KeyError:
        raise ValueError(f"unknown fabric {name!r}; choose from {', '.join(FABRICS)}") from None


def panel_fabrics(g, main: Fabric):
    """Resolve a garment's per-piece fabric keys ((fabric, interfacing) per
    piece, from a design) into Fabric objects for the Simulator."""
    keys = (g.meta or {}).get("panel_fabric_keys")
    if not keys or not any(f or i for f, i in keys):
        return g
    out = []
    for f, i in keys:
        base = get(f) if f else main           # a clear message for a fabric this copy doesn't have (a file's custom one)
        if i and i not in INTERFACINGS:
            raise ValueError(f"unknown interfacing {i!r}; choose from {', '.join(INTERFACINGS)}")
        out.append(fused(base, INTERFACINGS[i]) if i else (base if f else None))
    g.meta["panel_fabrics"] = out
    return g
