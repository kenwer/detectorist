"""Tests for the colors and labels detections are drawn with."""

import colorsys

from detectorist.detection_style import (
    GENUS_SHADE_RANGE,
    MASK_COLORS,
    UNIDENTIFIED_COLOR_RGB,
    DetectionStyle,
    shade,
    taxon_styles,
)
from detectorist.structures import Detection, RankedName, Taxonomy


def taxonomy(family, genus, species, score=0.9):
    return Taxonomy(RankedName(family, score), RankedName(genus, score), RankedName(species, score))


def test_taxon_style_takes_the_family_hue_and_the_deepest_identified_rank():
    fish = Detection((0, 0, 10, 10), 0.9, "Fish")
    named = Taxonomy(RankedName("Pomacentridae", 0.99), RankedName("Amphiprion", 0.97),
                     RankedName("Amphiprion_ocellaris", 0.44))

    style = taxon_styles([fish], {fish.box: named}, 0.5)[fish.box]

    # The only genus of its family keeps the family's own hue
    assert style == DetectionStyle(MASK_COLORS[0], 0.97, "Amphiprion")
    assert taxon_styles([fish], {fish.box: named}, 0.4)[fish.box].label == "A. ocellaris"
    assert taxon_styles([fish], {fish.box: named}, 0.98)[fish.box] == DetectionStyle(
        MASK_COLORS[0], 0.99, "Pomacentridae")


def test_families_get_hues_and_their_genera_shades_from_light_to_dark_by_name():
    a, b, c = (Detection((i * 10, 0, 10, 10), 0.9, "Fish") for i in range(3))
    taxonomy_by_box = {
        a.box: taxonomy("Pomacentridae", "Chromis", "Chromis_viridis"),
        b.box: taxonomy("Pomacentridae", "Amphiprion", "Amphiprion_ocellaris"),
        c.box: taxonomy("Labridae", "Labroides", "Labroides_dimidiatus"),
    }

    styles = taxon_styles([a, b, c], taxonomy_by_box, 0.5)

    assert styles[c.box].color == MASK_COLORS[0]  # Labridae
    assert styles[b.box].color == shade(MASK_COLORS[1], -GENUS_SHADE_RANGE)  # Pomacentridae, Amphiprion is lighter
    assert styles[a.box].color == shade(MASK_COLORS[1], GENUS_SHADE_RANGE)   # Chromis, darker


def test_a_detection_without_a_family_is_gray_and_an_unclassified_one_keeps_its_class_style():
    unclassified = Detection((0, 0, 10, 10), 0.8, "Crab")
    unidentified = Detection((10, 0, 10, 10), 0.7, "Fish")

    styles = taxon_styles([unclassified, unidentified],
                          {unidentified.box: taxonomy("Labridae", "Labroides", "L_d", 0.2)}, 0.5)

    assert styles == {unidentified.box: DetectionStyle(UNIDENTIFIED_COLOR_RGB, 0.7)}


def test_the_threshold_does_not_change_the_colors_of_other_detections():
    sure, unsure = (Detection((i * 10, 0, 10, 10), 0.9, "Fish") for i in range(2))
    taxonomy_by_box = {
        sure.box: taxonomy("Siganidae", "Siganus", "Siganus_argenteus", 0.99),
        unsure.box: taxonomy("Labridae", "Labroides", "Labroides_dimidiatus", 0.53),
    }

    low = taxon_styles([sure, unsure], taxonomy_by_box, 0.5)
    high = taxon_styles([sure, unsure], taxonomy_by_box, 0.6)

    assert low[sure.box].color == high[sure.box].color == MASK_COLORS[1]
    assert high[unsure.box].color == UNIDENTIFIED_COLOR_RGB


def test_the_threshold_does_not_change_the_shades_of_other_genera():
    a, b = (Detection((i * 10, 0, 10, 10), 0.9, "Fish") for i in range(2))
    taxonomy_by_box = {
        a.box: taxonomy("Pomacentridae", "Chromis", "Chromis_viridis", 0.99),
        b.box: Taxonomy(RankedName("Pomacentridae", 0.99), RankedName("Amphiprion", 0.55),
                        RankedName("Amphiprion_ocellaris", 0.5)),
    }

    low = taxon_styles([a, b], taxonomy_by_box, 0.5)
    high = taxon_styles([a, b], taxonomy_by_box, 0.6)

    assert low[a.box].color == high[a.box].color == shade(MASK_COLORS[0], GENUS_SHADE_RANGE)
    # Below the threshold the genus is not named, so its fish takes the plain family hue
    assert high[b.box].color == MASK_COLORS[0]


def test_the_first_four_colors_are_at_least_90_degrees_of_hue_apart():
    hues = [colorsys.rgb_to_hsv(*(c / 255 for c in color))[0] * 360 for color in MASK_COLORS[:4]]

    for i, a in enumerate(hues):
        for b in hues[i + 1:]:
            assert min(abs(a - b), 360 - abs(a - b)) >= 90


def test_shade_lightens_towards_white_and_darkens_towards_black():
    assert shade((200, 100, 0), -0.5) == (228, 178, 128)
    assert shade((200, 100, 0), 0.5) == (100, 50, 0)
    assert shade((200, 100, 0), 0) == (200, 100, 0)
