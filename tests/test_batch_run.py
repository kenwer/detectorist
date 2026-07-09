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
    output_dir_name,
    run_batch,
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


def read_csv_rows(output_dir):
    with open(os.path.join(output_dir, "detections.csv"), newline="") as f:
        return list(csv.reader(f))


def test_output_dir_name_encodes_confidence_and_model():
    assert output_dir_name(75, "fish-seg-transformer-2026-02-24.onnx.gz") == \
        "detectorist_conf-75_fish-seg-transformer-2026-02-24"
    assert output_dir_name(50, None) == "detectorist_conf-50_"


def test_crop_export_run(tmp_path):
    paths = make_images(tmp_path, ["with_fish.png", "empty.png"])
    detector = FakeDetector({"with_fish.png": [Detection((10, 10, 20, 20), 0.9, "Fish")]})
    output_dir = str(tmp_path / "out")

    result = run_batch(paths, detector, confidence=0.5, exposure_correction=False,
                       output_dir=output_dir, action=CropExportAction(CROP_SETTINGS),
                       progress=always_continue)

    assert not result.cancelled
    assert os.path.isfile(os.path.join(output_dir, "cropped", "with_fish_crop.png"))
    assert os.path.isfile(os.path.join(output_dir, "not-cropped", "empty.png"))
    assert read_csv_rows(output_dir) == [
        CSV_HEADER,
        ["with_fish.png", "0.9", "Fish", "1", "cropped"],
        ["empty.png", "0", "N/A", "0", "not-cropped"],
    ]


def test_detections_below_confidence_are_dropped(tmp_path):
    paths = make_images(tmp_path, ["faint.png"])
    detector = FakeDetector({"faint.png": [Detection((10, 10, 20, 20), 0.4, "Fish")]})
    output_dir = str(tmp_path / "out")

    result = run_batch(paths, detector, confidence=0.5, exposure_correction=False,
                       output_dir=output_dir, action=CropExportAction(CROP_SETTINGS),
                       progress=always_continue)

    assert result.rows == [("faint.png", 0, "N/A", 0, "not-cropped")]
    assert os.path.isfile(os.path.join(output_dir, "not-cropped", "faint.png"))


def test_sort_by_class_run(tmp_path):
    paths = make_images(tmp_path, ["a.png", "b.png"])
    detector = FakeDetector({"a.png": [Detection((10, 10, 20, 20), 0.8, "Fish")]})
    output_dir = str(tmp_path / "out")

    result = run_batch(paths, detector, confidence=0.5, exposure_correction=False,
                       output_dir=output_dir, action=SortByClassAction(),
                       progress=always_continue)

    assert os.path.isfile(os.path.join(output_dir, "Fish", "a.png"))
    assert os.path.isfile(os.path.join(output_dir, "no-detection", "b.png"))
    assert result.rows == [
        ("a.png", 0.8, "Fish", 1, "Fish"),
        ("b.png", 0, "no-detection", 0, "no-detection"),
    ]


def test_load_failure_skips_image_and_continues(tmp_path):
    paths = make_images(tmp_path, ["good_a.png", "good_b.png"])
    # A nonexistent file makes ImageObject.create raise on the prefetch thread
    paths.insert(1, str(tmp_path / "missing.png"))
    detector = FakeDetector({"good_a.png": [Detection((10, 10, 20, 20), 0.9, "Fish")]})
    output_dir = str(tmp_path / "out")

    result = run_batch(paths, detector, confidence=0.5, exposure_correction=False,
                       output_dir=output_dir, action=CropExportAction(CROP_SETTINGS),
                       progress=always_continue)

    assert not result.cancelled
    assert result.rows == [
        ("good_a.png", 0.9, "Fish", 1, "cropped"),
        ("missing.png", 0, "load-error", 0, ""),
        ("good_b.png", 0, "N/A", 0, "not-cropped"),
    ]
    assert os.path.isfile(os.path.join(output_dir, "cropped", "good_a_crop.png"))
    assert os.path.isfile(os.path.join(output_dir, "not-cropped", "good_b.png"))


def test_progress_can_cancel_the_run(tmp_path):
    paths = make_images(tmp_path, ["a.png", "b.png", "c.png"])
    detector = FakeDetector({})
    output_dir = str(tmp_path / "out")
    seen = []

    def cancel_after_first(index, total, filename):
        seen.append((index, total, filename))
        return index < 1

    result = run_batch(paths, detector, confidence=0.5, exposure_correction=False,
                       output_dir=output_dir, action=SortByClassAction(),
                       progress=cancel_after_first)

    assert result.cancelled
    assert seen == [(0, 3, "a.png"), (1, 3, "b.png")]
    assert len(result.rows) == 1  # only a.png was processed
    # The CSV still holds what was processed before the cancel
    assert len(read_csv_rows(output_dir)) == 2  # header + a.png
