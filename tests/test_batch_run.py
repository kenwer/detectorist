"""Tests for the Batch Run.

The models are faked (run_batch only needs detect(image) and classify(image, boxes)), images are tiny
PNGs written per test, and progress is a recording callback, so the whole
pipeline runs headless with no Qt and no ONNX model.
"""

import codecs
import csv
import os

import pytest
from PIL import Image

from detectorist.batch_run import (
    CLASSIFICATION_CSV_HEADER,
    CSV_ENCODING,
    DETECTIONS_CSV_HEADER,
    CropExportAction,
    SortByClassAction,
    classification_csv_name,
    detections_csv_name,
    run_batch,
    settings_json_name,
)
from detectorist.crop_planner import CropMode, CropSettings
from detectorist.structures import Detection
from tests.fakes import FakeClassifier, FakeDetector, make_images

CROP_SETTINGS = CropSettings(mode=CropMode.TOP_CONFIDENCE, padding=0.0, aspect=(1, 1))


def always_continue(index, total, filename):
    return True


DETECTIONS_CSV_FILENAME = "detections.csv"


def read_detections_csv_rows(output_dir):
    with open(os.path.join(output_dir, DETECTIONS_CSV_FILENAME), newline="", encoding=CSV_ENCODING) as f:
        return list(csv.reader(f))


def test_detections_csv_name_encodes_confidence_and_model():
    assert detections_csv_name(75, "fish-seg-transformer-2026-02-24.onnx.gz") == \
        "detectorist-detections-conf-75-fish-seg-transformer-2026-02-24.csv"
    assert detections_csv_name(50, None) == "detectorist-detections-conf-50-.csv"


def test_settings_json_name_encodes_confidence_and_model():
    assert settings_json_name(75, "fish-seg-transformer-2026-02-24.onnx.gz") == \
        "detectorist-settings-conf-75-fish-seg-transformer-2026-02-24.json"
    assert settings_json_name(50, None) == "detectorist-settings-conf-50-.json"


def test_crop_export_run(tmp_path):
    paths = make_images(tmp_path, ["with_fish.png", "empty.png"])
    detector = FakeDetector({"with_fish.png": [Detection((10, 10, 20, 20), 0.9, "Fish")]})
    output_dir = str(tmp_path / "out")

    result = run_batch(paths, detector, detection_confidence=0.5, exposure_correction=False,
                       output_dir=output_dir, detections_csv_filename=DETECTIONS_CSV_FILENAME, action=CropExportAction(CROP_SETTINGS),
                       progress=always_continue)

    assert not result.cancelled
    assert os.path.isfile(os.path.join(output_dir, "with_fish_crop.png"))
    assert os.path.isfile(os.path.join(output_dir, "empty_ncrop.png"))
    assert read_detections_csv_rows(output_dir) == [
        DETECTIONS_CSV_HEADER,
        ["with_fish.png", "0.9", "Fish", "1", "yes"],
        ["empty.png", "0", "N/A", "0", "no"],
    ]


def test_source_image_aspect_is_resolved_per_image(tmp_path):
    landscape = make_images(tmp_path, ["landscape.png"], size=(60, 40))
    portrait = make_images(tmp_path, ["portrait.png"], size=(40, 60))
    box = [Detection((10, 10, 20, 20), 0.9, "Fish")]
    detector = FakeDetector({"landscape.png": box, "portrait.png": box})
    output_dir = str(tmp_path / "out")
    settings = CropSettings(mode=CropMode.TOP_CONFIDENCE, padding=0.0, aspect="source_image")

    run_batch(landscape + portrait, detector, detection_confidence=0.5, exposure_correction=False,
              output_dir=output_dir, detections_csv_filename=DETECTIONS_CSV_FILENAME, action=CropExportAction(settings),
              progress=always_continue)

    with Image.open(os.path.join(output_dir, "landscape_crop.png")) as crop:
        assert crop.size == (30, 20)
    with Image.open(os.path.join(output_dir, "portrait_crop.png")) as crop:
        assert crop.size == (20, 30)


def test_detections_below_confidence_are_dropped(tmp_path):
    paths = make_images(tmp_path, ["faint.png"])
    detector = FakeDetector({"faint.png": [Detection((10, 10, 20, 20), 0.4, "Fish")]})
    output_dir = str(tmp_path / "out")

    result = run_batch(paths, detector, detection_confidence=0.5, exposure_correction=False,
                       output_dir=output_dir, detections_csv_filename=DETECTIONS_CSV_FILENAME, action=CropExportAction(CROP_SETTINGS),
                       progress=always_continue)

    assert result.detections_rows == [("faint.png", 0, "N/A", 0, "no")]
    assert os.path.isfile(os.path.join(output_dir, "faint_ncrop.png"))


def test_class_filter_drops_detections_of_other_classes(tmp_path):
    paths = make_images(tmp_path, ["both.png", "fish_only.png"])
    fish = Detection((10, 10, 20, 20), 0.9, "Fish")
    crab = Detection((30, 20, 10, 10), 0.8, "Crab")
    detector = FakeDetector({"both.png": [fish, crab], "fish_only.png": [fish]})
    output_dir = str(tmp_path / "out")

    result = run_batch(paths, detector, detection_confidence=0.5, exposure_correction=False,
                       output_dir=output_dir, detections_csv_filename=DETECTIONS_CSV_FILENAME, action=CropExportAction(CROP_SETTINGS),
                       progress=always_continue, class_filter="Crab")

    # The crab wins although the fish scores higher. An image without a crab counts as empty
    assert result.detections_rows == [
        ("both.png", 0.8, "Crab", 1, "yes"),
        ("fish_only.png", 0, "N/A", 0, "no"),
    ]
    with Image.open(os.path.join(output_dir, "both_crop.png")) as crop:
        assert crop.size == (10, 10)
    assert os.path.isfile(os.path.join(output_dir, "fish_only_ncrop.png"))


def test_sort_by_class_run(tmp_path):
    paths = make_images(tmp_path, ["a.png", "b.png"])
    detector = FakeDetector({"a.png": [Detection((10, 10, 20, 20), 0.8, "Fish")]})
    output_dir = str(tmp_path / "out")

    result = run_batch(paths, detector, detection_confidence=0.5, exposure_correction=False,
                       output_dir=output_dir, detections_csv_filename=DETECTIONS_CSV_FILENAME, action=SortByClassAction(),
                       progress=always_continue)

    assert os.path.isfile(os.path.join(output_dir, "Fish", "a.png"))
    assert os.path.isfile(os.path.join(output_dir, "no-detection", "b.png"))
    assert result.detections_rows == [
        ("a.png", 0.8, "Fish", 1, "no"),
        ("b.png", 0, "no-detection", 0, "no"),
    ]


def test_load_failure_skips_image_and_continues(tmp_path):
    paths = make_images(tmp_path, ["good_a.png", "good_b.png"])
    # A nonexistent file makes ImageObject.create raise on the prefetch thread
    paths.insert(1, str(tmp_path / "missing.png"))
    detector = FakeDetector({"good_a.png": [Detection((10, 10, 20, 20), 0.9, "Fish")]})
    output_dir = str(tmp_path / "out")

    result = run_batch(paths, detector, detection_confidence=0.5, exposure_correction=False,
                       output_dir=output_dir, detections_csv_filename=DETECTIONS_CSV_FILENAME, action=CropExportAction(CROP_SETTINGS),
                       progress=always_continue)

    assert not result.cancelled
    assert result.detections_rows == [
        ("good_a.png", 0.9, "Fish", 1, "yes"),
        ("missing.png", 0, "load-error", 0, "n/a"),
        ("good_b.png", 0, "N/A", 0, "no"),
    ]
    assert result.failed == ["missing.png"]
    assert os.path.isfile(os.path.join(output_dir, "good_a_crop.png"))
    assert os.path.isfile(os.path.join(output_dir, "good_b_ncrop.png"))


def test_processing_failure_skips_image_and_continues(tmp_path):
    paths = make_images(tmp_path, ["good_a.png", "bad.png", "good_b.png"])

    def fail_on_bad(name):
        if name == "bad.png":
            raise ValueError("boom")

    detector = FakeDetector({"good_a.png": [Detection((10, 10, 20, 20), 0.9, "Fish")]}, on_detect=fail_on_bad)
    output_dir = str(tmp_path / "out")

    result = run_batch(paths, detector, detection_confidence=0.5, exposure_correction=False,
                       output_dir=output_dir, detections_csv_filename=DETECTIONS_CSV_FILENAME, action=CropExportAction(CROP_SETTINGS),
                       progress=always_continue)

    assert not result.cancelled
    assert result.detections_rows == [
        ("good_a.png", 0.9, "Fish", 1, "yes"),
        ("bad.png", 0, "process-error", 0, "n/a"),
        ("good_b.png", 0, "N/A", 0, "no"),
    ]
    assert result.failed == ["bad.png"]
    assert read_detections_csv_rows(output_dir)[2] == ["bad.png", "0", "process-error", "0", "n/a"]
    assert os.path.isfile(os.path.join(output_dir, "good_b_ncrop.png"))


def test_detection_without_area_is_exported_uncropped(tmp_path):
    paths = make_images(tmp_path, ["flat.png"])
    detector = FakeDetector({"flat.png": [Detection((10, 10, 20, 0), 0.9, "Fish")]})
    output_dir = str(tmp_path / "out")

    result = run_batch(paths, detector, detection_confidence=0.5, exposure_correction=False,
                       output_dir=output_dir, detections_csv_filename=DETECTIONS_CSV_FILENAME, action=CropExportAction(CROP_SETTINGS),
                       progress=always_continue)

    assert result.detections_rows == [("flat.png", 0.9, "Fish", 1, "no")]
    assert result.failed == []
    assert os.path.isfile(os.path.join(output_dir, "flat_ncrop.png"))


def test_progress_can_cancel_the_run(tmp_path):
    paths = make_images(tmp_path, ["a.png", "b.png", "c.png"])
    detector = FakeDetector({})
    output_dir = str(tmp_path / "out")
    seen = []

    def cancel_after_first(index, total, filename):
        seen.append((index, total, filename))
        return index < 1

    result = run_batch(paths, detector, detection_confidence=0.5, exposure_correction=False,
                       output_dir=output_dir, detections_csv_filename=DETECTIONS_CSV_FILENAME, action=SortByClassAction(),
                       progress=cancel_after_first)

    assert result.cancelled
    assert seen == [(0, 3, "a.png"), (1, 3, "b.png")]
    assert len(result.detections_rows) == 1  # only a.png was processed
    # The CSV still holds what was processed before the cancel
    assert len(read_detections_csv_rows(output_dir)) == 2  # header + a.png


def test_second_run_updates_touched_rows_and_preserves_the_rest(tmp_path):
    output_dir = str(tmp_path / "out")

    paths = make_images(tmp_path, ["a.png", "b.png"])
    detector = FakeDetector({"a.png": [Detection((10, 10, 20, 20), 0.6, "Fish")]})
    run_batch(paths, detector, detection_confidence=0.5, exposure_correction=False,
              output_dir=output_dir, detections_csv_filename=DETECTIONS_CSV_FILENAME, action=CropExportAction(CROP_SETTINGS),
              progress=always_continue)

    # Re-running on just a.png, now with a stronger detection, should update
    # its row in place and leave b.png's row from the first run untouched.
    detector2 = FakeDetector({"a.png": [Detection((10, 10, 20, 20), 0.95, "Fish")]})
    result = run_batch([paths[0]], detector2, detection_confidence=0.5, exposure_correction=False,
                       output_dir=output_dir, detections_csv_filename=DETECTIONS_CSV_FILENAME, action=CropExportAction(CROP_SETTINGS),
                       progress=always_continue)

    assert result.detections_rows == [("a.png", 0.95, "Fish", 1, "yes")]
    assert read_detections_csv_rows(output_dir) == [
        DETECTIONS_CSV_HEADER,
        ["a.png", "0.95", "Fish", "1", "yes"],
        ["b.png", "0", "N/A", "0", "no"],
    ]


def test_mismatched_header_in_existing_csv_is_ignored(tmp_path):
    output_dir = str(tmp_path / "out")
    os.makedirs(output_dir)
    with open(os.path.join(output_dir, DETECTIONS_CSV_FILENAME), "w", newline="") as f:
        csv.writer(f).writerows([["Filename", "Old", "Header"], ["stale.png", "x", "y"]])

    paths = make_images(tmp_path, ["a.png"])
    result = run_batch(paths, FakeDetector({}), detection_confidence=0.5, exposure_correction=False,
                       output_dir=output_dir, detections_csv_filename=DETECTIONS_CSV_FILENAME, action=CropExportAction(CROP_SETTINGS),
                       progress=always_continue)

    assert not result.cancelled
    assert read_detections_csv_rows(output_dir) == [
        DETECTIONS_CSV_HEADER,
        ["a.png", "0", "N/A", "0", "no"],
    ]


def test_csv_is_utf8_with_bom_and_keeps_non_latin_filenames(tmp_path):
    # Names outside the Windows cp1252 code page, which the CSV used to be written in there
    first = make_images(tmp_path, ["рыба.png"])
    second = make_images(tmp_path, ["魚.png"])
    output_dir = str(tmp_path / "out")

    for paths in (first, second):
        run_batch(paths, FakeDetector(), detection_confidence=0.5, exposure_correction=False,
                  output_dir=output_dir, detections_csv_filename=DETECTIONS_CSV_FILENAME, action=CropExportAction(CROP_SETTINGS),
                  progress=always_continue)

    with open(os.path.join(output_dir, DETECTIONS_CSV_FILENAME), "rb") as f:
        raw = f.read()
    # The byte order mark is what lets Excel detect UTF-8
    assert raw.startswith(codecs.BOM_UTF8)
    # The second run read the first run's row back and kept it
    assert [row[0] for row in read_detections_csv_rows(output_dir)] == ["Filename", "рыба.png", "魚.png"]


def test_blank_lines_in_existing_csv_are_skipped(tmp_path):
    paths = make_images(tmp_path, ["new.png"])
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    lines = [",".join(DETECTIONS_CSV_HEADER), "old.png,0.9,Fish,1,yes", "", ""]
    (output_dir / DETECTIONS_CSV_FILENAME).write_text("\n".join(lines), encoding=CSV_ENCODING)

    run_batch(paths, FakeDetector(), detection_confidence=0.5, exposure_correction=False,
              output_dir=str(output_dir), detections_csv_filename=DETECTIONS_CSV_FILENAME, action=CropExportAction(CROP_SETTINGS),
              progress=always_continue)

    assert [row[0] for row in read_detections_csv_rows(str(output_dir))] == ["Filename", "old.png", "new.png"]


def test_undecodable_existing_csv_is_ignored(tmp_path):
    paths = make_images(tmp_path, ["new.png"])
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    # 0x81 is invalid as UTF-8 and unassigned in cp1252
    (output_dir / DETECTIONS_CSV_FILENAME).write_bytes(",".join(DETECTIONS_CSV_HEADER).encode() + b"\nold\x81.png,0.9,Fish,1,yes\n")

    run_batch(paths, FakeDetector(), detection_confidence=0.5, exposure_correction=False,
              output_dir=str(output_dir), detections_csv_filename=DETECTIONS_CSV_FILENAME, action=CropExportAction(CROP_SETTINGS),
              progress=always_continue)

    assert [row[0] for row in read_detections_csv_rows(str(output_dir))] == ["Filename", "new.png"]


def test_unwritable_csv_fails_before_any_image_is_processed(tmp_path):
    paths = make_images(tmp_path, ["a.png"])
    output_dir = tmp_path / "out"
    # A directory in the CSV's place cannot be opened for writing on any platform
    (output_dir / DETECTIONS_CSV_FILENAME).mkdir(parents=True)
    detector = FakeDetector()

    with pytest.raises(OSError, match="Cannot write detections.csv"):
        run_batch(paths, detector, detection_confidence=0.5, exposure_correction=False,
                  output_dir=str(output_dir), detections_csv_filename=DETECTIONS_CSV_FILENAME, action=CropExportAction(CROP_SETTINGS),
                  progress=always_continue)

    assert detector.detected == []
    assert not (output_dir / "a_ncrop.png").exists()


CLASSIFICATION_CSV_FILENAME = "classification.csv"


def read_classification_csv_rows(output_dir):
    with open(os.path.join(output_dir, CLASSIFICATION_CSV_FILENAME), newline="", encoding=CSV_ENCODING) as f:
        return list(csv.reader(f))


def run_classified_sort(tmp_path, detections_by_file, classifier, taxon_confidence=0.0):
    """Sort the images named in detections_by_file with a classifier. Returns the BatchResult."""
    paths = make_images(tmp_path, list(detections_by_file))
    return run_batch(paths, FakeDetector(detections_by_file), detection_confidence=0.5, exposure_correction=False,
                     output_dir=str(tmp_path / "out"), detections_csv_filename=DETECTIONS_CSV_FILENAME, action=SortByClassAction(),
                     progress=always_continue, classifier=classifier, taxon_confidence=taxon_confidence,
                     classification_csv_filename=CLASSIFICATION_CSV_FILENAME)


def test_classification_csv_name_encodes_taxon_confidence_and_classifier():
    assert classification_csv_name(73, "sulawesi-fish-classification-2026-10-17.onnx.gz") == \
        "detectorist-classification-conf-73-sulawesi-fish-classification-2026-10-17.csv"


def test_every_named_detection_gets_a_classification_row(tmp_path):
    detections = [Detection((30, 20, 10, 10), 0.8, "Fish"), Detection((10, 10, 20, 20), 0.9, "Fish")]

    run_classified_sort(tmp_path, {"a.png": detections}, FakeClassifier())

    names = ["Pomacentridae", "0.99", "Amphiprion", "0.97", "Amphiprion_ocellaris", "0.44", "fake-classifier"]
    assert read_classification_csv_rows(str(tmp_path / "out")) == [
        CLASSIFICATION_CSV_HEADER,
        ["a.png", "1", "Fish", "0.9", "10", "10", "20", "20", *names],
        ["a.png", "2", "Fish", "0.8", "30", "20", "10", "10", *names],
    ]


def test_detections_csv_keeps_its_columns_with_a_classifier(tmp_path):
    run_classified_sort(tmp_path, {"a.png": [Detection((10, 10, 20, 20), 0.9, "Fish")]}, FakeClassifier())

    assert read_detections_csv_rows(str(tmp_path / "out")) == [DETECTIONS_CSV_HEADER, ["a.png", "0.9", "Fish", "1", "no"]]


@pytest.mark.parametrize(("taxon_confidence", "names"), [
    (0.5, ["Pomacentridae", 0.99, "Amphiprion", 0.97, "", ""]),
    (0.98, ["Pomacentridae", 0.99, "", "", "", ""]),
    # Not identified at all, but still counted
    (1.0, ["", "", "", "", "", ""]),
])
def test_ranks_below_the_taxon_confidence_are_left_empty(tmp_path, taxon_confidence, names):
    result = run_classified_sort(tmp_path, {"a.png": [Detection((10, 10, 20, 20), 0.9, "Fish")]},
                                 FakeClassifier(), taxon_confidence)

    assert [list(row[8:14]) for row in result.classification_rows] == [names]


def test_classification_rows_cover_only_the_classes_the_classifier_names(tmp_path):
    crab, fish = Detection((10, 10, 20, 20), 0.9, "Crab"), Detection((30, 20, 10, 10), 0.8, "Fish")

    result = run_classified_sort(tmp_path, {"a.png": [crab, fish]}, FakeClassifier(patterns=("Fish",)))

    assert [row[:3] for row in result.classification_rows] == [("a.png", 1, "Fish")]


def test_classification_boxes_are_clamped_to_the_image(tmp_path):
    # The images are 64 x 48
    result = run_classified_sort(tmp_path, {"a.png": [Detection((-5, 40, 20, 20), 0.9, "Fish")]}, FakeClassifier())

    assert result.classification_rows[0][4:8] == (0, 40, 15, 8)


def test_without_a_classifier_no_classification_csv_is_written(tmp_path):
    run_classified_sort(tmp_path, {"a.png": [Detection((10, 10, 20, 20), 0.9, "Fish")]}, None)

    assert not (tmp_path / "out" / CLASSIFICATION_CSV_FILENAME).exists()


def test_a_failing_classifier_leaves_the_image_without_classification_rows(tmp_path):
    classifier = FakeClassifier(error=RuntimeError("out of memory"))

    result = run_classified_sort(tmp_path, {"a.png": [Detection((10, 10, 20, 20), 0.9, "Fish")]}, classifier)

    assert result.failed == []
    assert result.detections_rows == [("a.png", 0.9, "Fish", 1, "no")]
    assert read_classification_csv_rows(str(tmp_path / "out")) == [CLASSIFICATION_CSV_HEADER]
    assert (tmp_path / "out" / "Fish" / "a.png").is_file()


def test_second_run_replaces_all_classification_rows_of_the_images_it_touches(tmp_path):
    two_fish = [Detection((10, 10, 5, 5), 0.9, "Fish"), Detection((30, 10, 5, 5), 0.8, "Fish")]
    run_classified_sort(tmp_path, {"a.png": two_fish, "b.png": two_fish[:1]}, FakeClassifier())

    run_classified_sort(tmp_path, {"a.png": two_fish[1:]}, FakeClassifier())

    rows = read_classification_csv_rows(str(tmp_path / "out"))
    assert [row[:5] for row in rows[1:]] == [["a.png", "1", "Fish", "0.8", "30"], ["b.png", "1", "Fish", "0.9", "10"]]


def test_classification_rows_of_an_image_that_fails_to_load_are_dropped(tmp_path):
    run_classified_sort(tmp_path, {"a.png": [Detection((10, 10, 5, 5), 0.9, "Fish")]}, FakeClassifier())
    os.remove(tmp_path / "a.png")

    run_batch([str(tmp_path / "a.png")], FakeDetector(), detection_confidence=0.5, exposure_correction=False,
              output_dir=str(tmp_path / "out"), detections_csv_filename=DETECTIONS_CSV_FILENAME, action=SortByClassAction(),
              progress=always_continue, classifier=FakeClassifier(),
              classification_csv_filename=CLASSIFICATION_CSV_FILENAME)

    assert read_classification_csv_rows(str(tmp_path / "out")) == [CLASSIFICATION_CSV_HEADER]
