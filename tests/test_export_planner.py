"""Tests for the export planner: crop rectangles and file names."""

import pytest

from detectorist.export_planner import (
    CropMode,
    CropSettings,
    ExportOptions,
    plan_crops,
    safe_name,
    taxon_prefix,
)
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
        assert CropMode.from_setting("most_confident") is CropMode.MOST_CONFIDENT_DETECTION
        assert CropMode.from_setting("most_centered") is CropMode.MOST_CENTERED
        assert CropMode.from_setting("each_object") is CropMode.EACH_OBJECT
        assert CropMode.from_setting("best_classification") is CropMode.BEST_CLASSIFICATION

    @pytest.mark.parametrize("value", ["union", "largest_area", "top_confidence", "all_detected_objects"])
    def test_names_of_earlier_versions_are_no_longer_known(self, value):
        assert CropMode.from_setting(value) is None

    def test_unknown_and_missing_are_none(self):
        assert CropMode.from_setting("bogus") is None
        assert CropMode.from_setting(None) is None


EDGE = Detection((0, 0, 10, 10), 0.9, "Crab")
CENTER = Detection((45, 45, 10, 10), 0.6, "Fish")


def whole_image_name(detections, mode):
    options = ExportOptions(CropSettings(mode, 0.0, "detection_frame"), crop=False)
    (planned,) = options.plan("IMG.jpg", detections, 100, 100, {})
    return planned.name


def test_each_crop_is_named_by_the_detection_it_frames():
    planned = ExportOptions(CropSettings(CropMode.EACH_OBJECT, 0.0, (1, 1))).plan("IMG.jpg", [EDGE, CENTER], 100, 100, {})
    assert [file.name for file in planned] == ["Crab_IMG_crop_0.jpg", "Fish_IMG_crop_1.jpg"]


@pytest.mark.parametrize(("mode", "expected"), [
    (CropMode.MOST_CONFIDENT_DETECTION, "Crab_IMG.jpg"),
    (CropMode.EACH_OBJECT, "Crab_IMG.jpg"),
    (CropMode.MOST_CENTERED, "Fish_IMG.jpg"),
])
def test_a_whole_image_is_named_by_the_detection_the_crop_mode_picks(mode, expected):
    assert whole_image_name([EDGE, CENTER], mode) == expected


def test_a_whole_image_is_named_by_the_top_score_when_no_box_has_area():
    flat = [Detection((0, 0, 5, 0), 0.6, "Fish"), Detection((0, 0, 0, 5), 0.9, "Crab")]
    assert whole_image_name(flat, CropMode.MOST_CENTERED) == "Crab_IMG.jpg"


def test_a_crop_without_area_falls_back_to_a_whole_image():
    flat = [Detection((0, 0, 5, 0), 0.6, "Fish")]
    (planned,) = ExportOptions(CropSettings(CropMode.EACH_OBJECT, 0.0, (1, 1))).plan("IMG.jpg", flat, 100, 100, {})
    assert planned == (None, "Fish_IMG.jpg")


FULL = [RankedName("Pomacentridae", 0.99), RankedName("Amphiprion", 0.97), RankedName("Amphiprion_ocellaris", 0.9)]


@pytest.mark.parametrize("name, safe", [("Amphiprion_sp.", "Amphiprion_sp"), ('a:b*c?"<>|', "a_b_c_____"), ("ok", "ok")])
def test_safe_name_replaces_characters_windows_rejects(name, safe):
    assert safe_name(name) == safe


def test_taxon_prefix_makes_species_names_safe():
    odd = [RankedName("Fam:x", 1.0), RankedName("Gen", 1.0), RankedName("Gen_sp.", 1.0)]
    assert taxon_prefix(odd) == "Fam_x_Gen_sp"


@pytest.mark.parametrize(("ranks", "prefix"), [
    (FULL, "Pomacentridae_Amphiprion_ocellaris"),
    (FULL[:2], "Pomacentridae_Amphiprion_unidentified"),
    (FULL[:1], "Pomacentridae_unidentified"),
    ([], "unidentified"),
])
def test_taxon_prefix_names_the_identified_ranks_then_unidentified(ranks, prefix):
    assert taxon_prefix(ranks) == prefix


def test_taxon_prefix_makes_names_safe_for_windows():
    assert taxon_prefix([RankedName("Fam:ily", 1.0)]) == "Fam_ily_unidentified"


SETTINGS = CropSettings(mode=CropMode.EACH_OBJECT, padding=0.0, aspect="detection_frame", taxon_confidence=0.5)
FISH = Detection((10, 10, 20, 20), 0.9, "Fish")
OTHER = Detection((40, 10, 10, 10), 0.8, "Fish")
TAXONOMY = {FISH.box: Taxonomy(*FULL), OTHER.box: Taxonomy(*FULL[:2], RankedName("Amphiprion_ocellaris", 0.3))}


def names(detections, crop=True, prefix_class=False, prefix_taxa=True, patterns=("*",), settings=SETTINGS):
    options = ExportOptions(settings, crop=crop, prefix_class=prefix_class, prefix_taxa=prefix_taxa,
                            classifier_patterns=patterns)
    return [file.name for file in options.plan("IMG.jpg", detections, 48, 64, TAXONOMY)]


def test_plan_names_each_crop_by_its_taxa():
    assert names([FISH, OTHER]) == ["Pomacentridae_Amphiprion_ocellaris_IMG_crop_0.jpg",
                                    "Pomacentridae_Amphiprion_unidentified_IMG_crop_1.jpg"]


def test_plan_by_class_ignores_the_taxa():
    assert names([FISH], prefix_class=True, prefix_taxa=False) == ["Fish_IMG_crop.jpg"]


def test_plan_by_class_and_taxa_names_the_class_first():
    assert names([FISH], prefix_class=True) == ["Fish_Pomacentridae_Amphiprion_ocellaris_IMG_crop.jpg"]


def test_plan_by_class_and_taxa_names_a_class_the_classifier_skips_once():
    assert names([FISH], prefix_class=True, patterns=("Crab",)) == ["Fish_IMG_crop.jpg"]


def test_plan_without_a_prefix_keeps_the_file_name():
    assert names([FISH], prefix_taxa=False) == ["IMG_crop.jpg"]
    assert names([FISH], crop=False, prefix_taxa=False) == ["IMG.jpg"]
    assert names([], prefix_taxa=False) == ["IMG.jpg"]


def test_plan_without_crop_copies_the_whole_image_once():
    options = ExportOptions(SETTINGS, crop=False, prefix_class=False, prefix_taxa=True, classifier_patterns=("*",))
    (planned,) = options.plan("IMG.jpg", [FISH, OTHER], 48, 64, TAXONOMY)
    assert planned == (None, "Pomacentridae_Amphiprion_ocellaris_IMG.jpg")


def test_plan_by_taxa_without_a_classifier_names_by_class():
    assert names([FISH], patterns=None) == ["Fish_IMG_crop.jpg"]


def test_plan_of_an_image_without_detections():
    assert names([]) == ["no-detection_IMG.jpg"]


@pytest.mark.parametrize(("crop", "prefix_class", "prefix_taxa", "patterns", "scheme"), [
    (True, False, True, ("*",), "<Family>_<Genus>_<Species>_<Filename>_crop[_<n>].HIF"),
    (True, True, True, ("*",), "<Class>_<Family>_<Genus>_<Species>_<Filename>_crop[_<n>].HIF"),
    (True, True, False, ("*",), "<Class>_<Filename>_crop[_<n>].HIF"),
    (True, False, True, None, "<Class>_<Filename>_crop[_<n>].HIF"),
    (False, False, False, ("*",), "<Filename>.HIF"),
])
def test_name_scheme_spells_out_what_plan_names(crop, prefix_class, prefix_taxa, patterns, scheme):
    options = ExportOptions(SETTINGS, crop=crop, prefix_class=prefix_class, prefix_taxa=prefix_taxa,
                            classifier_patterns=patterns)
    assert options.name_scheme(".HIF") == scheme
