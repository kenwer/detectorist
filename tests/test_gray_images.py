"""Tests for grayscale files that Pillow reports in a mode other than "L".

A 1-bit file is mode "1" and a 16-bit grayscale PNG is mode "I;16". OpenCV
decodes both to a single-channel array, so they load as grayscale images.
"""

import numpy as np
import pytest
from PIL import Image

from detectorist import image_utils
from detectorist.image_object import ImageObject
from detectorist.structures import ImageMode

# Left half black, right half white
BILEVEL = np.zeros((48, 64), dtype=bool)
BILEVEL[:, 32:] = True
GRAY16 = np.zeros((48, 64), dtype=np.uint16)
GRAY16[:, 32:] = 65535

CASES = [
    pytest.param("bilevel.png", BILEVEL, 8, id="1-bit PNG"),
    pytest.param("bilevel.bmp", BILEVEL, 8, id="1-bit BMP"),
    pytest.param("gray16.png", GRAY16, 16, id="16-bit PNG"),
]


def make_image(tmp_path, name, pixels):
    path = str(tmp_path / name)
    Image.fromarray(pixels).save(path)
    return path


@pytest.mark.parametrize(("name", "pixels", "bits"), CASES)
def test_gray_file_is_loaded_for_display_and_detection(tmp_path, name, pixels, bits):
    image = ImageObject.create(make_image(tmp_path, name, pixels))

    assert image.mode == ImageMode.GRAY
    assert image.original_bpc == bits
    assert (image.width, image.height) == (64, 48)
    display = image.image_data_rgb_8bit_display
    assert display.shape == (48, 64, 3)
    assert display.dtype == np.uint8
    assert display[:, :32].max() == 0
    assert display[:, 32:].min() == 255
    assert image.preprocess_for_onnx_detr(32, 32).shape == (1, 3, 32, 32)


@pytest.mark.parametrize(("name", "pixels", "bits"), CASES)
def test_crop_of_gray_file_keeps_its_bit_depth(tmp_path, name, pixels, bits):
    image = ImageObject.create(make_image(tmp_path, name, pixels))
    output = str(tmp_path / ("crop_" + name))

    # Spans the black and white halves
    image.save_cropped((16, 8, 32, 24), output)

    crop = image_utils.imread(output)
    assert crop.shape == (24, 32)
    assert crop.dtype == (np.uint16 if bits == 16 else np.uint8)
    assert crop[:, :16].max() == 0
    assert crop[:, 16:].min() == np.iinfo(crop.dtype).max
