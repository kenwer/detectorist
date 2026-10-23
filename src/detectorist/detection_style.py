"""The colors detections are drawn in, by their class or, with a classifier, by their taxon. Qt-free."""

from collections import defaultdict
from typing import NamedTuple

from .classifier import identified_ranks, short_name
from .structures import Detection

# 12 visually distinct segmentation-mask colors for the instance segmentation masks.
# Assigned to class names in sorted order, so each class keeps the same color across every image.
# An image usually holds only a few classes, which take the first colors, so each color is the one
# furthest in hue from all before it. The first four are 90° apart, and chartreuse, hard to tell from
# green, comes last.
MASK_COLORS = [
    (  0, 230,   0),   #  0  green       (120°)
    (230,   0, 230),   #  1  magenta     (300°)
    (230, 115,   0),   #  2  orange      ( 30°)
    (  0, 115, 230),   #  3  blue-violet (210°)
    (230,   0,   0),   #  4  red         (  0°)
    (  0, 230, 230),   #  5  cyan        (180°)
    (230, 230,   0),   #  6  yellow      ( 60°)
    (  0,   0, 230),   #  7  blue        (240°)
    (115,   0, 230),   #  8  purple      (270°)
    (  0, 230, 115),   #  9  teal        (150°)
    (115, 230,   0),   # 10  chartreuse  ( 90°)
    (230,   0, 115),   # 11  rose / pink (330°)
]

# Outside MASK_COLORS, so a detection the classifier could not name never looks like a family
UNIDENTIFIED_COLOR_RGB = (160, 160, 160)
# How far the lightest and darkest genus shades move from their family's hue. Further makes the
# darkest shades hard to see on dark images.
GENUS_SHADE_RANGE = 0.4


def build_class_color_map(class_names: list[str]) -> dict[str, tuple]:
    """Assigns each class name a fixed color from MASK_COLORS, in the given order."""
    return {name: MASK_COLORS[i % len(MASK_COLORS)] for i, name in enumerate(class_names)}


class DetectionStyle(NamedTuple):
    """How one detection is drawn: its color, the score its opacity follows and the label shown at its box, if any."""
    color: tuple
    score: float
    label: str | None = None


def shade(color: tuple, amount: float) -> tuple:
    """The color moved towards white by a negative amount, towards black by a positive one, as a fraction of the way."""
    if amount < 0:
        return tuple(round(c + (255 - c) * -amount) for c in color)
    return tuple(round(c * (1 - amount)) for c in color)


def taxon_styles(detections: list[Detection], taxonomy_by_box: dict, threshold: float) -> dict:
    """
    The style of each classified detection, keyed by box. A detection the
    classifier has not seen is left out, so it keeps the style of its class.

    The hue tells the family and a shade of it the genus. Both are spread over
    the families and genera among these detections only, sorted by name, as
    those of a whole model are too many to tell apart. They include the taxa
    below the threshold, so moving it never recolors another detection. The
    opacity follows the score of the deepest identified rank (see
    identified_ranks), which the label names. A detection not identified down
    to its family is gray and keeps its detection score.
    """
    taxonomies = [taxonomy_by_box[d.box] for d in detections if d.box in taxonomy_by_box]
    family_colors = build_class_color_map(sorted({t.family.name for t in taxonomies}))
    genera_by_family = defaultdict(set)
    for t in taxonomies:
        genera_by_family[t.family.name].add(t.genus.name)
    # A genus belongs to a single family, so it alone is the key
    genus_shades = {}
    for genera in genera_by_family.values():
        for i, genus in enumerate(sorted(genera)):
            genus_shades[genus] = GENUS_SHADE_RANGE * (2 * i / (len(genera) - 1) - 1) if len(genera) > 1 else 0

    styles = {}
    for d in detections:
        if d.box not in taxonomy_by_box:
            continue
        ranks = identified_ranks(taxonomy_by_box[d.box], threshold)
        if not ranks:
            styles[d.box] = DetectionStyle(UNIDENTIFIED_COLOR_RGB, d.score)
            continue
        color = family_colors[ranks[0].name]
        if len(ranks) > 1:
            color = shade(color, genus_shades[ranks[1].name])
        styles[d.box] = DetectionStyle(color, ranks[-1].score, short_name(ranks[-1].name))
    return styles
