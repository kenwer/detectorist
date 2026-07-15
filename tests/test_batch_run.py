"""Tests for the Batch Run.

The detector is faked (run_batch only needs detect(image)), images are tiny
PNGs written per test, and progress is a recording callback, so the whole
pipeline runs headless with no Qt and no ONNX model.
"""

import csv
import os

from PIL import Image

from detectorist.batch_run import (
    CSV_HEADER,
    CropExportAction,
    SortByClassAction,
    detections_csv_name,
    run_batch,
    settings_json_name,
)
from detectorist.crop_planner import CropMode, CropSettings
from detectorist.structures import Detection

CROP_SETTINGS = CropSettings(mode=CropMode.TOP_CONFIDENCE, padding=0.0, aspect=(1, 1))


class FakeDetector:
    """detect() returns canned detections keyed by image filename."""

    def __init__(self, detections_by_file):
        self.detections_by_file = detections_by_file

    def detect(self, image):
        return self.detections_by_file.get(os.path.basename(image.image_path), [])


def make_images(dir_path, names, size=(64, 48)):
    paths = []
    for name in names:
        path = str(dir_path / name)
        Image.new("RGB", size, color=(120, 130, 140)).save(path)
        paths.append(path)
    return paths


def always_continue(index, total, filename):
    return True


CSV_FILENAME = "detections.csv"


def read_csv_rows(output_dir):
    with open(os.path.join(output_dir, CSV_FILENAME), newline="") as f:
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

    result = run_batch(paths, detector, confidence=0.5, exposure_correction=False,
                       output_dir=output_dir, csv_filename=CSV_FILENAME, action=CropExportAction(CROP_SETTINGS),
                       progress=always_continue)

    assert not result.cancelled
    assert os.path.isfile(os.path.join(output_dir, "with_fish_crop.png"))
    assert os.path.isfile(os.path.join(output_dir, "empty_ncrop.png"))
    assert read_csv_rows(output_dir) == [
        CSV_HEADER,
        ["with_fish.png", "0.9", "Fish", "1", "yes"],
        ["empty.png", "0", "N/A", "0", "no"],
    ]


def test_detections_below_confidence_are_dropped(tmp_path):
    paths = make_images(tmp_path, ["faint.png"])
    detector = FakeDetector({"faint.png": [Detection((10, 10, 20, 20), 0.4, "Fish")]})
    output_dir = str(tmp_path / "out")

    result = run_batch(paths, detector, confidence=0.5, exposure_correction=False,
                       output_dir=output_dir, csv_filename=CSV_FILENAME, action=CropExportAction(CROP_SETTINGS),
                       progress=always_continue)

    assert result.rows == [("faint.png", 0, "N/A", 0, "no")]
    assert os.path.isfile(os.path.join(output_dir, "faint_ncrop.png"))


def test_sort_by_class_run(tmp_path):
    paths = make_images(tmp_path, ["a.png", "b.png"])
    detector = FakeDetector({"a.png": [Detection((10, 10, 20, 20), 0.8, "Fish")]})
    output_dir = str(tmp_path / "out")

    result = run_batch(paths, detector, confidence=0.5, exposure_correction=False,
                       output_dir=output_dir, csv_filename=CSV_FILENAME, action=SortByClassAction(),
                       progress=always_continue)

    assert os.path.isfile(os.path.join(output_dir, "Fish", "a.png"))
    assert os.path.isfile(os.path.join(output_dir, "no-detection", "b.png"))
    assert result.rows == [
        ("a.png", 0.8, "Fish", 1, "no"),
        ("b.png", 0, "no-detection", 0, "no"),
    ]


def test_load_failure_skips_image_and_continues(tmp_path):
    paths = make_images(tmp_path, ["good_a.png", "good_b.png"])
    # A nonexistent file makes ImageObject.create raise on the prefetch thread
    paths.insert(1, str(tmp_path / "missing.png"))
    detector = FakeDetector({"good_a.png": [Detection((10, 10, 20, 20), 0.9, "Fish")]})
    output_dir = str(tmp_path / "out")

    result = run_batch(paths, detector, confidence=0.5, exposure_correction=False,
                       output_dir=output_dir, csv_filename=CSV_FILENAME, action=CropExportAction(CROP_SETTINGS),
                       progress=always_continue)

    assert not result.cancelled
    assert result.rows == [
        ("good_a.png", 0.9, "Fish", 1, "yes"),
        ("missing.png", 0, "load-error", 0, "n/a"),
        ("good_b.png", 0, "N/A", 0, "no"),
    ]
    assert os.path.isfile(os.path.join(output_dir, "good_a_crop.png"))
    assert os.path.isfile(os.path.join(output_dir, "good_b_ncrop.png"))


def test_progress_can_cancel_the_run(tmp_path):
    paths = make_images(tmp_path, ["a.png", "b.png", "c.png"])
    detector = FakeDetector({})
    output_dir = str(tmp_path / "out")
    seen = []

    def cancel_after_first(index, total, filename):
        seen.append((index, total, filename))
        return index < 1

    result = run_batch(paths, detector, confidence=0.5, exposure_correction=False,
                       output_dir=output_dir, csv_filename=CSV_FILENAME, action=SortByClassAction(),
                       progress=cancel_after_first)

    assert result.cancelled
    assert seen == [(0, 3, "a.png"), (1, 3, "b.png")]
    assert len(result.rows) == 1  # only a.png was processed
    # The CSV still holds what was processed before the cancel
    assert len(read_csv_rows(output_dir)) == 2  # header + a.png


def test_second_run_updates_touched_rows_and_preserves_the_rest(tmp_path):
    output_dir = str(tmp_path / "out")

    paths = make_images(tmp_path, ["a.png", "b.png"])
    detector = FakeDetector({"a.png": [Detection((10, 10, 20, 20), 0.6, "Fish")]})
    run_batch(paths, detector, confidence=0.5, exposure_correction=False,
              output_dir=output_dir, csv_filename=CSV_FILENAME, action=CropExportAction(CROP_SETTINGS),
              progress=always_continue)

    # Re-running on just a.png, now with a stronger detection, should update
    # its row in place and leave b.png's row from the first run untouched.
    detector2 = FakeDetector({"a.png": [Detection((10, 10, 20, 20), 0.95, "Fish")]})
    result = run_batch([paths[0]], detector2, confidence=0.5, exposure_correction=False,
                       output_dir=output_dir, csv_filename=CSV_FILENAME, action=CropExportAction(CROP_SETTINGS),
                       progress=always_continue)

    assert result.rows == [("a.png", 0.95, "Fish", 1, "yes")]
    assert read_csv_rows(output_dir) == [
        CSV_HEADER,
        ["a.png", "0.95", "Fish", "1", "yes"],
        ["b.png", "0", "N/A", "0", "no"],
    ]


def test_mismatched_header_in_existing_csv_is_ignored(tmp_path):
    output_dir = str(tmp_path / "out")
    os.makedirs(output_dir)
    with open(os.path.join(output_dir, CSV_FILENAME), "w", newline="") as f:
        csv.writer(f).writerows([["Filename", "Old", "Header"], ["stale.png", "x", "y"]])

    paths = make_images(tmp_path, ["a.png"])
    result = run_batch(paths, FakeDetector({}), confidence=0.5, exposure_correction=False,
                       output_dir=output_dir, csv_filename=CSV_FILENAME, action=CropExportAction(CROP_SETTINGS),
                       progress=always_continue)

    assert not result.cancelled
    assert read_csv_rows(output_dir) == [
        CSV_HEADER,
        ["a.png", "0", "N/A", "0", "no"],
    ]
