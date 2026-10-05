"""Smoke tests that load the real models from ./models.

Slow and opt-in (pytest -m slow). The model files are Git LFS objects of
more than 100 MB each. A checkout without them, such as CI, holds small
pointer files instead, and each test then skips itself.

These check that a shipped model satisfies what Detector assumes about it.
Exact pre and postprocessing is covered in test_detector.py against the tiny
models, where the expected values are known.
"""

import json
from pathlib import Path

import pytest

from detectorist.detector import Detector
from detectorist.image_object import ImageObject
from detectorist.model_downloader import model_filename_from_url
from tests.fakes import make_images

pytestmark = pytest.mark.slow

MODELS_DIR = Path(__file__).parent.parent / "models"
FILENAMES = [model_filename_from_url(entry["url"]) for entry in json.loads((MODELS_DIR / "models.json").read_text())]

# An LFS pointer file is about 130 bytes, a real model over 100 MB
MIN_MODEL_BYTES = 1_000_000


@pytest.mark.parametrize("filename", FILENAMES)
def test_shipped_model_satisfies_the_detector_contract(filename, tmp_path):
    path = MODELS_DIR / filename
    if not path.is_file() or path.stat().st_size < MIN_MODEL_BYTES:
        pytest.skip(f"{filename} is not present (Git LFS object not fetched)")

    detector = Detector(str(path))
    assert detector.class_names, "model has no 'names' metadata"

    (image_path,) = make_images(tmp_path, ["gray.png"], size=(640, 480))
    results = detector.detect(ImageObject.create(image_path))

    scores = [detection.score for detection in results]
    assert scores == sorted(scores, reverse=True)
    for detection in results:
        assert 0.0 <= detection.score <= 1.0
        assert len(detection.box) == 4
        assert detection.class_name in detector.class_names.values()
        if detector.is_segmentation:
            assert detection.mask.shape == (detector.input_height, detector.input_width)
        else:
            assert detection.mask is None
