"""Characterization tests for the crop planner.
"""

import pytest

from detectorist.crop_planner import CropMode, CropSettings, plan_crops

# Detections are ((x, y, w, h), score, class_name); the planner reads box and score.
# Class names come from the model's metadata (e.g. 'Fish', 'Apoidea') and are all
# alike within one run, since the specialized models are single-class.
D1 = ((100, 200, 50, 80), 0.9, "Fish")
D2 = ((400, 100, 120, 60), 0.7, "Fish")
D3 = ((300, 300, 40, 40), 0.95, "Fish")
DETECTIONS = [D1, D2, D3]

HEIGHT, WIDTH = 400, 600


def plan(detections, mode, padding, aspect, height=HEIGHT, width=WIDTH):
    return plan_crops(detections, height, width, CropSettings(mode=mode, padding=padding, aspect=aspect))


def test_no_detections_yields_no_crops():
    assert plan([], CropMode.TOP_CONFIDENCE, 0.1, (1, 1)) == []


def test_top_confidence_picks_highest_score():
    # D3 wins on score. With no padding its 40x40 box is already square
    assert plan(DETECTIONS, CropMode.TOP_CONFIDENCE, 0.0, (1, 1)) == [(300, 300, 40, 40)]


def test_top_confidence_with_padding_and_aspect():
    assert plan(DETECTIONS, CropMode.TOP_CONFIDENCE, 0.1, (3, 2)) == [(284, 296, 72, 48)]


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
    assert plan([((0, 0, 60, 60), 0.5, "c")], CropMode.TOP_CONFIDENCE, 0.5, (1, 1)) == [(0, 0, 120, 120)]


def test_crop_larger_than_image_is_scaled_down():
    assert plan([((10, 10, 500, 350), 0.5, "c")], CropMode.TOP_CONFIDENCE, 0.5, (1, 1)) == [(60, 0, 400, 400)]


def test_wide_box_with_tall_target_ratio():
    assert plan([((50, 50, 300, 30), 0.5, "c")], CropMode.TOP_CONFIDENCE, 0.0, (9, 16)) == [(87, 0, 225, 400)]


def test_zero_area_detection_still_crashes():
    # Wart inherited from the original implementation: a zero-height box reaches
    # the aspect-fit division. Pinned so a future fix is a deliberate change.
    with pytest.raises(ZeroDivisionError):
        plan([((50, 50, 0, 0), 0.5, "c")], CropMode.TOP_CONFIDENCE, 0.0, "detection_frame")


class TestCropModeFromSetting:
    def test_parses_current_names(self):
        assert CropMode.from_setting("union") is CropMode.UNION
        assert CropMode.from_setting("top_confidence") is CropMode.TOP_CONFIDENCE
        assert CropMode.from_setting("most_centered") is CropMode.MOST_CENTERED
        assert CropMode.from_setting("all_detected_objects") is CropMode.EACH_OBJECT

    def test_parses_legacy_largest_area_as_union(self):
        assert CropMode.from_setting("largest_area") is CropMode.UNION

    def test_unknown_and_missing_are_none(self):
        assert CropMode.from_setting("bogus") is None
        assert CropMode.from_setting(None) is None
