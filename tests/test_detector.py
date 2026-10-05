"""Tests for Detector against the two tiny ONNX models in tests/data.

The models return fixed boxes, logits and masks (see tests/tiny_models.py),
so these tests check the code around the session exactly: metadata parsing,
box conversion from normalized centre format to image pixels, the sigmoid
score, class lookup, ordering, and mask upscaling.
"""

import gzip
import shutil

import numpy as np
import pytest

from detectorist.detector import Detector
from detectorist.image_object import ImageObject
from tests.fakes import make_images
from tests.tiny_models import DETECT_CLASS_NAMES, DETECT_MODEL, INPUT_SIZE, SEG_CLASS_NAMES, SEG_MODEL


def load_image(tmp_path, size):
    (path,) = make_images(tmp_path, ["image.png"], size=size)
    return ImageObject.create(path)


def test_model_metadata_is_read():
    detector = Detector(str(DETECT_MODEL))

    assert detector.class_names == DETECT_CLASS_NAMES
    assert (detector.input_width, detector.input_height) == (INPUT_SIZE, INPUT_SIZE)
    assert detector.is_segmentation is False
    assert detector.model_path == str(DETECT_MODEL)


@pytest.mark.parametrize(("size", "expected_boxes"), [
    ((200, 100), [[75, 25, 50, 50], [0, 0, 100, 50], [125, 62, 50, 25]]),
    ((64, 64), [[24, 16, 16, 32], [0, 0, 32, 32], [40, 40, 16, 16]]),
])
def test_boxes_are_converted_to_top_left_pixel_coordinates(tmp_path, size, expected_boxes):
    results = Detector(str(DETECT_MODEL)).detect(load_image(tmp_path, size))

    assert [list(detection.box) for detection in results] == expected_boxes


def test_scores_are_sigmoid_of_the_best_logit_sorted_descending(tmp_path):
    results = Detector(str(DETECT_MODEL)).detect(load_image(tmp_path, (200, 100)))

    # sigmoid(2), sigmoid(0), sigmoid(-2). The model emits the middle one first.
    assert [detection.score for detection in results] == pytest.approx([0.8808, 0.5, 0.1192], abs=1e-4)
    assert [detection.class_name for detection in results] == ["Fish", "Crab", "Fish"]


def test_detection_model_returns_no_masks(tmp_path):
    results = Detector(str(DETECT_MODEL)).detect(load_image(tmp_path, (200, 100)))

    assert all(detection.mask is None for detection in results)


def test_segmentation_model_uses_zero_based_class_names(tmp_path):
    detector = Detector(str(SEG_MODEL))

    results = detector.detect(load_image(tmp_path, (200, 100)))

    assert detector.is_segmentation is True
    assert detector.class_names == SEG_CLASS_NAMES
    assert [detection.class_name for detection in results] == ["Fish", "Crab", "Fish"]


def test_masks_are_binary_at_model_input_resolution(tmp_path):
    results = Detector(str(SEG_MODEL)).detect(load_image(tmp_path, (200, 100)))
    # Sorting by score puts the model's second detection first, and each
    # mask has to travel with its detection.
    top_half, left_half, empty = (detection.mask for detection in results)

    for mask in (left_half, top_half, empty):
        assert mask.shape == (INPUT_SIZE, INPUT_SIZE)
        assert mask.dtype == np.uint8
        assert set(np.unique(mask)) <= {0, 255}

    # The band around the middle is left out: interpolation decides where
    # exactly the edge falls there.
    assert (left_half[:, :12] == 255).all()
    assert (left_half[:, 20:] == 0).all()
    assert (top_half[:12] == 255).all()
    assert (top_half[20:] == 0).all()
    assert (empty == 0).all()


def test_gzipped_model_is_loaded(tmp_path):
    gz_path = tmp_path / "tiny-detect.onnx.gz"
    with open(DETECT_MODEL, "rb") as source, gzip.open(gz_path, "wb") as target:
        shutil.copyfileobj(source, target)

    detector = Detector(str(gz_path))

    assert detector.class_names == DETECT_CLASS_NAMES
    assert len(detector.detect(load_image(tmp_path, (200, 100)))) == 3


def test_missing_model_file_raises_oserror(tmp_path):
    with pytest.raises(OSError, match="Error loading ONNX model"):
        Detector(str(tmp_path / "missing.onnx"))


def test_corrupt_model_file_raises_oserror(tmp_path):
    corrupt = tmp_path / "corrupt.onnx"
    corrupt.write_bytes(b"this is not an onnx model")

    with pytest.raises(OSError, match="Error loading ONNX model"):
        Detector(str(corrupt))
