"""Tests for the colors and labels detections are drawn with."""

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


def test_shade_lightens_towards_white_and_darkens_towards_black():
    assert shade((200, 100, 0), -0.5) == (228, 178, 128)
    assert shade((200, 100, 0), 0.5) == (100, 50, 0)
    assert shade((200, 100, 0), 0) == (200, 100, 0)
