"""Tests for HEIF images that carry an alpha channel.

pillow-heif reports them as mode "RGBA" (or "RGBA;16" above 8 bit), which
also starts with "RGB", so the mode mapping has to tell the two apart.
"""

import numpy as np
import pillow_heif
import pytest
from PIL import Image

from detectorist.image_object import ImageObject
from detectorist.structures import ImageMode

SIZE = (64, 48)


def make_alpha_heif(path, bit_depth):
    if bit_depth == 8:
        pixels = np.full((SIZE[1], SIZE[0], 4), (60, 70, 80, 255), dtype=np.uint8)
        heif = pillow_heif.from_bytes("RGBA", SIZE, pixels.tobytes())
    else:
        pixels = np.full((SIZE[1], SIZE[0], 4), (15000, 18000, 20000, 65535), dtype=np.uint16)
        heif = pillow_heif.from_bytes("RGBA;16", SIZE, pixels.tobytes())
    heif.save(str(path), bit_depth=bit_depth)
    return str(path)


@pytest.mark.parametrize("bit_depth", [8, 10])
def test_alpha_heif_is_loaded_as_rgba(tmp_path, bit_depth):
    image = ImageObject.create(make_alpha_heif(tmp_path / "alpha.heic", bit_depth))

    assert image.mode == ImageMode.RGBA
    assert image.original_bpc == bit_depth
    assert image.image_data.shape == (SIZE[1], SIZE[0], 4)


@pytest.mark.parametrize("bit_depth", [8, 10])
def test_alpha_heif_converts_for_display_and_detection(tmp_path, bit_depth):
    image = ImageObject.create(make_alpha_heif(tmp_path / "alpha.heic", bit_depth))

    # Display and the detector both need exactly three 8-bit channels
    display = image.image_data_rgb_8bit_display
    assert display.shape == (SIZE[1], SIZE[0], 3)
    assert display.dtype == np.uint8
    assert image.preprocess_for_onnx_detr(32, 32).shape == (1, 3, 32, 32)


@pytest.mark.parametrize("bit_depth", [8, 10])
@pytest.mark.parametrize("exposure_correction", [False, True])
def test_crop_of_alpha_heif_keeps_the_alpha_channel(tmp_path, bit_depth, exposure_correction):
    image = ImageObject.create(make_alpha_heif(tmp_path / "alpha.heic", bit_depth))
    image.exposure_correction = exposure_correction
    output = str(tmp_path / "alpha_crop.heic")

    image.save_cropped((8, 8, 32, 24), output)

    with Image.open(output) as saved:
        assert saved.size == (32, 24)
        assert saved.mode == "RGBA"
