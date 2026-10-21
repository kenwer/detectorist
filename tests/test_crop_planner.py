"""Characterization tests for the crop planner.
"""

import pytest

from detectorist.crop_planner import CropMode, CropSettings, plan_crops
from detectorist.structures import Detection, RankedName, Taxonomy

# The planner reads only a Detection's box and score. Class names come from
# the model's metadata (e.g. 'Fish', 'Apoidea') and are all alike within one
# run, since the specialized models are single-class.
D1 = Detection((100, 200, 50, 80), 0.9, "Fish")
D2 = Detection((400, 100, 120, 60), 0.7, "Fish")
D3 = Detection((300, 300, 40, 40), 0.95, "Fish")
DETECTIONS = [D1, D2, D3]

HEIGHT, WIDTH = 400, 600


def plan(detections, mode, padding, aspect, height=HEIGHT, width=WIDTH):
    return plan_crops(detections, height, width, CropSettings(mode=mode, padding=padding, aspect=aspect))


def test_no_detections_yields_no_crops():
    assert plan([], CropMode.MOST_CONFIDENT_DETECTION, 0.1, (1, 1)) == []


def test_top_confidence_picks_highest_score():
    # D3 wins on score. With no padding its 40x40 box is already square
    assert plan(DETECTIONS, CropMode.MOST_CONFIDENT_DETECTION, 0.0, (1, 1)) == [(300, 300, 40, 40)]


def test_top_confidence_with_padding_and_aspect():
    assert plan(DETECTIONS, CropMode.MOST_CONFIDENT_DETECTION, 0.1, (3, 2)) == [(284, 296, 72, 48)]


def test_union_frames_all_detections():
    # UNION spans from D1's left edge to D2's right edge, one crop containing everything
    assert plan(DETECTIONS, CropMode.UNION, 0.0, "detection_frame") == [(100, 100, 420, 240)]


def test_union_padded_square_is_clamped_to_image_height():
    assert plan(DETECTIONS, CropMode.UNION, 0.25, (1, 1)) == [(110, 0, 400, 400)]


def test_union_of_single_detection_is_its_own_box():
    assert plan([D1], CropMode.UNION, 0.1, (4, 3)) == [(61, 192, 128, 96)]


def test_most_centered_picks_detection_closest_to_image_center():
    # The image center is (300, 200) and D3's center (320, 320) is closest to it
    assert plan(DETECTIONS, CropMode.MOST_CENTERED, 0.1, (2, 3)) == [(296, 284, 48, 72)]


def test_each_object_yields_one_crop_per_detection():
    assert plan(DETECTIONS, CropMode.EACH_OBJECT, 0.1, (1, 1)) == [
        (77, 192, 96, 96),
        (388, 58, 144, 144),
        (296, 296, 48, 48),
    ]


def test_crop_is_translated_back_inside_the_image():
    # Padding pushes the box past the top-left corner; it gets moved to (0, 0)
    assert plan([Detection((0, 0, 60, 60), 0.5, "c")], CropMode.MOST_CONFIDENT_DETECTION, 0.5, (1, 1)) == [(0, 0, 120, 120)]


def test_crop_larger_than_image_is_scaled_down():
    assert plan([Detection((10, 10, 500, 350), 0.5, "c")], CropMode.MOST_CONFIDENT_DETECTION, 0.5, (1, 1)) == [(60, 0, 400, 400)]


def test_wide_box_with_tall_target_ratio():
    assert plan([Detection((50, 50, 300, 30), 0.5, "c")], CropMode.MOST_CONFIDENT_DETECTION, 0.0, (9, 16)) == [(87, 0, 225, 400)]


def test_source_image_aspect_follows_each_image():
    # The same box and settings yield a landscape crop in a landscape image
    # and a portrait crop in a portrait image
    box = [Detection((100, 100, 40, 40), 0.5, "c")]
    assert plan(box, CropMode.MOST_CONFIDENT_DETECTION, 0.0, "source_image", height=400, width=600) == [(90, 100, 60, 40)]
    assert plan(box, CropMode.MOST_CONFIDENT_DETECTION, 0.0, "source_image", height=600, width=400) == [(100, 90, 40, 60)]


@pytest.mark.parametrize("box", [(50, 50, 0, 0), (50, 50, 20, 0), (50, 50, 0, 20)])
def test_zero_area_detection_yields_no_crop(box):
    assert plan([Detection(box, 0.5, "c")], CropMode.MOST_CONFIDENT_DETECTION, 0.0, "detection_frame") == []


def test_zero_area_detection_is_ignored_next_to_usable_ones():
    # The empty box scores highest, yet the crop frames the best box with an area
    empty = Detection((50, 50, 20, 0), 0.99, "c")
    assert plan([empty, D3], CropMode.MOST_CONFIDENT_DETECTION, 0.0, (1, 1)) == [(300, 300, 40, 40)]


def taxonomy(family, genus, species):
    return Taxonomy(RankedName("Fam", family), RankedName("Gen", genus), RankedName("Gen_spec", species))


def plan_best(detections, taxonomy_by_box, threshold=0.5):
    settings = CropSettings(mode=CropMode.BEST_CLASSIFICATION, padding=0.0, aspect="detection_frame", taxon_confidence=threshold)
    return plan_crops(detections, HEIGHT, WIDTH, settings, taxonomy_by_box)


class TestBestClassification:
    def test_deeper_rank_beats_higher_score_at_a_shallower_rank(self):
        # D1 is named to the genus with a near certain score, D2 to the species with a modest one
        taxonomies = {D1.box: taxonomy(0.99, 0.97, 0.48), D2.box: taxonomy(0.90, 0.70, 0.55)}
        assert plan_best(DETECTIONS, taxonomies) == [D2.box]

    def test_higher_score_wins_at_the_same_rank(self):
        taxonomies = {D1.box: taxonomy(0.99, 0.98, 0.60), D2.box: taxonomy(0.90, 0.80, 0.70)}
        assert plan_best(DETECTIONS, taxonomies) == [D2.box]

    def test_detection_score_breaks_a_tie(self):
        # D1 (0.9) and D2 (0.7) are named alike, D1 is the more confident detection
        taxonomies = {D1.box: taxonomy(0.9, 0.8, 0.7), D2.box: taxonomy(0.9, 0.8, 0.7)}
        assert plan_best(DETECTIONS, taxonomies) == [D1.box]

    def test_an_identified_detection_beats_unclassified_ones(self):
        # D3 is the most confident detection but was never classified
        taxonomies = {D2.box: taxonomy(0.6, 0.3, 0.1)}
        assert plan_best(DETECTIONS, taxonomies) == [D2.box]

    def test_without_any_identification_the_most_confident_detection_wins(self):
        taxonomies = {D1.box: taxonomy(0.4, 0.3, 0.2), D2.box: taxonomy(0.45, 0.4, 0.3)}
        assert plan_best(DETECTIONS, taxonomies) == [D3.box]

    def test_without_taxonomies_the_most_confident_detection_wins(self):
        assert plan_best(DETECTIONS, {}) == [D3.box]

    def test_threshold_decides_the_depth(self):
        taxonomies = {D1.box: taxonomy(0.99, 0.97, 0.48), D2.box: taxonomy(0.90, 0.70, 0.55)}
        # At 0.4 both are named to the species, and D2 scores higher there
        assert plan_best(DETECTIONS, taxonomies, threshold=0.4) == [D2.box]
        # At 0.6 neither species counts, and D1's genus scores higher
        assert plan_best(DETECTIONS, taxonomies, threshold=0.6) == [D1.box]


class TestCropModeFromSetting:
    def test_parses_current_names(self):
        assert CropMode.from_setting("union") is CropMode.UNION
        assert CropMode.from_setting("top_confidence") is CropMode.MOST_CONFIDENT_DETECTION
        assert CropMode.from_setting("most_centered") is CropMode.MOST_CENTERED
        assert CropMode.from_setting("all_detected_objects") is CropMode.EACH_OBJECT
        assert CropMode.from_setting("best_classification") is CropMode.BEST_CLASSIFICATION

    def test_parses_legacy_largest_area_as_union(self):
        assert CropMode.from_setting("largest_area") is CropMode.UNION

    def test_unknown_and_missing_are_none(self):
        assert CropMode.from_setting("bogus") is None
        assert CropMode.from_setting(None) is None
