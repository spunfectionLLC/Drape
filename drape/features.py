"""Feature switches: one boolean per feature that can be turned off in a build, read everywhere the
feature is offered: the studio's buttons (sent to it by /api/init), the API routes and
the starters.

A switch that's off only stops *creating* new pieces of that kind. Designs that
already contain them still load, drape and export.

    from drape import features
    features.require("OPENING_BANDS")      # raises FeatureOff when it's off
"""
from __future__ import annotations

FEATURES = {
    # "Finish an opening": neckband, collar, waistband, cuff, hem band (dedit.add_band),
    # from the editor and in the starters. Hoods aren't bands
    # and stay on regardless (dedit.add_hood).
    "OPENING_BANDS": True,
    # bias binding (EDGE_FINISH_SPEC): not built yet
    "BINDING_TOOL": True,
    # one-click facing: not built yet
    "FACING_TOOL": True,
    # drapes run on a server: not built, off
    "CLOUD_DRAPE": False,
}

LABELS = {
    "OPENING_BANDS": "Bands round an opening (neckband, collar, waistband, cuff, hem band)",
    "BINDING_TOOL": "Bias binding",
    "FACING_TOOL": "Facings",
    "CLOUD_DRAPE": "Cloud drapes",
}


class FeatureOff(Exception):
    """A switched-off feature was asked for (the studio answers 403)."""


def on(name: str) -> bool:
    return bool(FEATURES[name])


def require(name: str) -> None:
    if not on(name):
        raise FeatureOff(f"{LABELS.get(name, name)}: not available in this build")
