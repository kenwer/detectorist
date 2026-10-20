"""Tests for the species classifier: framing, rollup and the ONNX wrapper.

The window values were computed with species_probe.window from the
rf-detr-training repository, which cut the crops the model was trained on. A
difference here would cost accuracy without raising any error.
"""

import json
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from detectorist import classifier as classifier_module
from detectorist.classifier import (
    MAX_CLASSIFIED_BOXES,
    Classifier,
    class_matches,
    classification_window,
    describe,
    detections_to_classify,
    identified_ranks,
    letterbox,
    roll_up,
)
from detectorist.image_object import ImageObject
from detectorist.structures import Detection
from tests.fakes import TAXONOMY
from tests.tiny_models import (
    CLASSIFY_MARGIN,
    CLASSIFY_MODEL,
    CLASSIFY_SIZE,
    CLASSIFY_SPECIES,
    DETECT_MODEL,
)

RED, GREEN, BLUE, DARK = (255, 0, 0), (0, 255, 0), (0, 0, 255), (0, 0, 0)


@pytest.mark.parametrize(("box", "expected"), [
    ((400, 300, 200, 100), (390, 240, 610, 460)),  # centred
    # Moved back in at the left edge. 221 and not 220: 200 * 1.1 is a hair above 220 in floating point.
    ((0, 300, 200, 100), (0, 240, 221, 460)),
    ((800, 700, 200, 100), (780, 580, 1000, 800)),  # moved back in at the bottom right
    ((0, 0, 1000, 100), (0, 0, 1000, 800)),  # longer than the image is tall: not square
    ((0, 0, 1000, 800), (0, 0, 1000, 800)),  # the whole image
    ((403, 301, 37, 91), (371, 296, 472, 397)),  # a tall box with odd numbers
])
def test_window_matches_the_training_framing(box, expected):
    assert classification_window(box, 1000, 800, 0.05) == expected


def test_window_of_a_box_reaching_outside_the_image_is_that_of_the_clamped_box():
    assert classification_window((-50, 300, 250, 100), 1000, 800, 0.05) == \
        classification_window((0, 300, 200, 100), 1000, 800, 0.05)


def test_window_of_a_box_entirely_outside_the_image_is_still_inside_it():
    x1, y1, x2, y2 = classification_window((2000, 2000, 50, 50), 1000, 800, 0.05)

    assert 0 <= x1 < x2 <= 1000
    assert 0 <= y1 < y2 <= 800


# The same crop and the same answer as in test_species_probe.py of the
# rf-detr-training repository: both channel means end in .5, which rounds to even
HALVES_MEAN = (128, 0, 50)


def halves(height: int, width: int, vertical: bool) -> np.ndarray:
    """A crop whose two halves are red and dark blue, split along its long side."""
    crop = np.zeros((height, width, 3), dtype=np.uint8)
    crop[:] = (0, 0, 101)
    if vertical:
        crop[: height // 2] = RED
    else:
        crop[:, : width // 2] = RED
    return crop


def test_letterbox_of_a_wide_crop_adds_bars_of_its_mean_colour_above_and_below():
    framed = letterbox(halves(20, 40, vertical=False), 16)

    assert framed.shape == (16, 16, 3)
    assert framed.dtype == np.uint8
    assert (framed[:4] == HALVES_MEAN).all()
    assert (framed[12:] == HALVES_MEAN).all()
    # Away from the seam between the halves, which the resize blends
    assert (framed[4:12, :6] == RED).all()
    assert (framed[4:12, 10:] == (0, 0, 101)).all()


def test_letterbox_of_a_tall_crop_adds_bars_of_its_mean_colour_left_and_right():
    framed = letterbox(halves(40, 20, vertical=True), 16)

    assert (framed[:, :4] == HALVES_MEAN).all()
    assert (framed[:, 12:] == HALVES_MEAN).all()
    assert (framed[:6, 4:12] == RED).all()
    assert (framed[10:, 4:12] == (0, 0, 101)).all()


def test_letterbox_of_a_square_crop_has_no_bars():
    crop = np.full((50, 50, 3), GREEN, dtype=np.uint8)

    assert (letterbox(crop, 16) == GREEN).all()


# Two families. The first holds two genera, so the genus step has a choice.
SPECIES = ["Aa_one", "Aa_two", "Aa_three", "Bb_one", "Cc_one"]
GENERA = ["Aa", "Bb", "Cc"]
FAMILIES = ["Xidae", "Yidae"]
GENUS_OF = np.array([0, 0, 0, 1, 2])
FAMILY_OF = np.array([0, 0, 0, 0, 1])


def test_roll_up_sums_species_into_genus_and_family():
    probs = np.array([0.5, 0.2, 0.1, 0.15, 0.05])

    taxonomy = roll_up(probs, SPECIES, GENERA, FAMILIES, GENUS_OF, FAMILY_OF)

    assert taxonomy.family.name == "Xidae"
    assert taxonomy.family.score == pytest.approx(0.95)
    assert taxonomy.genus.name == "Aa"
    assert taxonomy.genus.score == pytest.approx(0.8)
    assert taxonomy.species.name == "Aa_one"
    assert taxonomy.species.score == pytest.approx(0.5)


def test_roll_up_picks_the_species_inside_the_chosen_genus():
    # Bb_one is the single most probable species, but genus Aa outweighs genus Bb
    probs = np.array([0.2, 0.2, 0.2, 0.3, 0.1])

    taxonomy = roll_up(probs, SPECIES, GENERA, FAMILIES, GENUS_OF, FAMILY_OF)

    assert taxonomy.genus.name == "Aa"
    assert taxonomy.genus.score == pytest.approx(0.6)
    assert taxonomy.species.name == "Aa_one"
    assert taxonomy.species.score == pytest.approx(0.2)


def test_roll_up_picks_the_genus_inside_the_chosen_family():
    # Cc is the most probable genus, but family Xidae outweighs family Yidae
    probs = np.array([0.3, 0.0, 0.0, 0.3, 0.4])

    taxonomy = roll_up(probs, SPECIES, GENERA, FAMILIES, GENUS_OF, FAMILY_OF)

    assert taxonomy.family.name == "Xidae"
    assert taxonomy.genus.name in ("Aa", "Bb")
    assert taxonomy.family.score >= taxonomy.genus.score >= taxonomy.species.score


def painted_image(tmp_path, mode="RGB"):
    """A 200x100 dark image with a red square on the left and a blue one on the right."""
    image = Image.new("RGB", (200, 100), DARK)
    image.paste(RED, (10, 30, 50, 70))
    image.paste(BLUE, (140, 30, 180, 70))
    path = tmp_path / "painted.png"
    image.convert(mode).save(path)
    return ImageObject.create(str(path))


RED_BOX = (10, 30, 40, 40)
BLUE_BOX = (140, 30, 40, 40)
DARK_BOX = (80, 10, 20, 20)


@pytest.fixture(scope="module")
def classifier():
    return Classifier(str(CLASSIFY_MODEL))


def test_classifier_reads_its_framing_from_the_model(classifier):
    assert classifier.model_path == str(CLASSIFY_MODEL)
    assert classifier.size == CLASSIFY_SIZE
    assert classifier.margin == CLASSIFY_MARGIN
    assert classifier.species == [CLASSIFY_SPECIES[i] for i in range(4)]


def test_classify_returns_one_taxonomy_per_box_in_order(classifier, tmp_path):
    image = painted_image(tmp_path)

    blue, red, dark = classifier.classify(image, [BLUE_BOX, RED_BOX, DARK_BOX])

    assert red.species.name == "Amphiprion_ocellaris"
    assert red.genus.name == "Amphiprion"
    assert red.family.name == "Pomacentridae"
    assert blue.species.name == "Halichoeres_hortulanus"
    assert blue.family.name == "Labridae"
    assert dark.species.name == "Halichoeres_marginatus"
    assert all(isinstance(t.species.score, float) for t in (blue, red, dark))
    assert red.family.score >= red.genus.score >= red.species.score > 0.5


def test_classify_without_boxes_returns_nothing(classifier, tmp_path):
    assert classifier.classify(painted_image(tmp_path), []) == []


def test_classify_accepts_a_box_given_as_a_list(classifier, tmp_path):
    (red,) = classifier.classify(painted_image(tmp_path), [list(RED_BOX)])

    assert red.species.name == "Amphiprion_ocellaris"


@pytest.mark.parametrize("mode", ["L", "RGBA"])
def test_classify_handles_images_that_are_not_plain_rgb(classifier, tmp_path, mode):
    taxonomies = classifier.classify(painted_image(tmp_path, mode), [RED_BOX, BLUE_BOX])

    assert len(taxonomies) == 2


def test_a_detector_file_is_not_a_classifier():
    with pytest.raises(OSError, match="not a classifier"):
        Classifier(str(DETECT_MODEL))


def test_a_missing_file_is_reported_as_oserror(tmp_path):
    with pytest.raises(OSError, match="missing.onnx"):
        Classifier(str(tmp_path / "missing.onnx"))


@pytest.mark.parametrize("fill", ["edge-repeat", [89, 107, 119]])
def test_a_model_trained_with_another_fill_is_refused(fill, monkeypatch):
    # The tiny model says "crop-mean", so its metadata is rewritten as the classifier reads it.
    # Only the classifier module's json is replaced, the real one stays untouched.
    monkeypatch.setattr(classifier_module, "json", SimpleNamespace(loads=lambda text: {**json.loads(text), "fill": fill}))

    with pytest.raises(OSError, match="unsupported letterbox fill"):
        Classifier(str(CLASSIFY_MODEL))


@pytest.mark.parametrize(("patterns", "class_name", "expected"), [
    (["Fish*"], "Fish", True),
    (["Fish*"], "Fish_out-of-focus", True),
    (["Fish*"], "Apoidea", False),
    (["Fish*"], "fish", False),  # the same on every platform, unlike a file name
    (["Fish*", "Apoidea"], "Apoidea", True),
    (["*"], "person", True),
    ([], "Fish", False),
])
def test_class_matches_a_pattern_list(patterns, class_name, expected):
    assert class_matches(patterns, class_name) is expected


def test_detections_to_classify_are_those_above_min_score_of_the_named_classes_best_first():
    faint = Detection((0, 0, 1, 1), 0.3, "Fish")
    fish = Detection((1, 1, 1, 1), 0.6, "Fish")
    crab = Detection((2, 2, 1, 1), 0.9, "Crab")
    best = Detection((3, 3, 1, 1), 0.8, "Fish")

    assert detections_to_classify([faint, fish, crab, best], 0.5, ["Fish"]) == [best, fish]


def test_detections_to_classify_are_capped():
    many = [Detection((i, 0, 1, 1), 0.9, "Fish") for i in range(MAX_CLASSIFIED_BOXES + 5)]

    assert len(detections_to_classify(many, 0.0, ["*"])) == MAX_CLASSIFIED_BOXES


@pytest.mark.parametrize(("threshold", "expected"), [
    (0.0, "Pomacentridae · A. ocellaris 0.44"),
    (0.5, "Pomacentridae · Amphiprion 0.97"),
    (0.98, "Pomacentridae 0.99"),
    (1.0, "Unidentified"),
])
def test_describe_names_the_family_and_the_deepest_rank_at_or_above_the_threshold(threshold, expected):
    assert describe(TAXONOMY, threshold) == expected


def test_describe_keeps_a_species_name_without_a_genus_part():
    taxonomy = TAXONOMY._replace(species=TAXONOMY.species._replace(name="ocellaris"))

    assert describe(taxonomy, 0.0) == "Pomacentridae · ocellaris 0.44"


@pytest.mark.parametrize(("threshold", "expected"), [
    (0.0, list(TAXONOMY)),
    (0.98, [TAXONOMY.family]),
    (1.0, []),
])
def test_identified_ranks_stop_at_the_first_rank_below_the_threshold(threshold, expected):
    assert identified_ranks(TAXONOMY, threshold) == expected
