"""Tests for the ImageObject 8-bit conversion pipeline.

These pin the conversion contract before and after performance work on
image_object.py: expected channel order per source mode, 16 to 8 bit
scaling, and the guarantee that callers receive arrays that do not alias
the internal image data (mutating a result must never corrupt the source).
"""

import numpy as np
import pytest

from detectorist.image_object import ImageObject
from detectorist.structures import ImageMode


class SyntheticImage(ImageObject):
    """In-memory ImageObject exercising the base class conversion paths.

    Bypasses __init__ because the base class requires an existing file.
    """

    def __init__(self, data: np.ndarray, mode: ImageMode, bpc: int):
        self._image_path = f"<synthetic {mode.value} {bpc}bit>"
        self._image_data = data
        self._original_bpc = bpc
        self._mode = mode
        self._file_extension = ".synthetic"
        self._exif_dict = {}
        self._exposure_correction = False

    def save_cropped(self, rect, output_path):
        raise NotImplementedError


CHANNELS = {
    ImageMode.RGB: 3,
    ImageMode.RGBA: 4,
    ImageMode.BGR: 3,
    ImageMode.BGRA: 4,
    ImageMode.GRAY: None,
}

CASES = [
    (ImageMode.BGR, 8),
    (ImageMode.BGR, 16),
    (ImageMode.RGB, 8),
    (ImageMode.RGB, 16),
    (ImageMode.RGBA, 8),
    (ImageMode.BGRA, 8),
    (ImageMode.GRAY, 8),
]


def make_image(mode: ImageMode, bpc: int) -> SyntheticImage:
    channels = CHANNELS[mode]
    shape = (4, 3) if channels is None else (4, 3, channels)
    rng = np.random.default_rng(42)
    if bpc > 8:
        data = rng.integers(0, 2**16, size=shape, dtype=np.uint16)
    else:
        data = rng.integers(0, 2**8, size=shape, dtype=np.uint8)
    return SyntheticImage(data, mode, bpc)


def expected_bgr(data: np.ndarray, mode: ImageMode, bpc: int) -> np.ndarray:
    """Reference conversion: scale to 8 bit, then rearrange channels to BGR."""
    data_8bit = (data >> 8).astype(np.uint8) if bpc > 8 else data
    if mode == ImageMode.BGR:
        return data_8bit
    if mode == ImageMode.BGRA:
        return data_8bit[:, :, :3]
    if mode == ImageMode.RGB:
        return data_8bit[:, :, ::-1]
    if mode == ImageMode.RGBA:
        return data_8bit[:, :, 2::-1]
    if mode == ImageMode.GRAY:
        return np.repeat(data_8bit[:, :, np.newaxis], 3, axis=2)
    raise AssertionError(f"unhandled mode {mode}")


@pytest.mark.parametrize("mode,bpc", CASES, ids=lambda v: getattr(v, "value", v))
def test_bgr_8bit_channel_order_and_scaling(mode, bpc):
    image = make_image(mode, bpc)

    result = image.image_data_bgr_8bit

    assert result.dtype == np.uint8
    np.testing.assert_array_equal(result, expected_bgr(image._image_data, mode, bpc))


@pytest.mark.parametrize("mode,bpc", CASES, ids=lambda v: getattr(v, "value", v))
def test_rgb_8bit_is_channel_reverse_of_bgr(mode, bpc):
    image = make_image(mode, bpc)

    result = image.image_data_rgb_8bit

    assert result.dtype == np.uint8
    np.testing.assert_array_equal(result, image.image_data_bgr_8bit[:, :, ::-1])


@pytest.mark.parametrize("mode,bpc", CASES, ids=lambda v: getattr(v, "value", v))
def test_converted_arrays_do_not_alias_source(mode, bpc):
    image = make_image(mode, bpc)
    original = image._image_data.copy()

    for result in (image.image_data_bgr_8bit, image.image_data_rgb_8bit):
        result[:] = 0
        np.testing.assert_array_equal(image._image_data, original)


@pytest.mark.parametrize("mode,bpc", [(ImageMode.RGB, 16), (ImageMode.BGR, 8)])
def test_display_equals_rgb_when_correction_off(mode, bpc):
    image = make_image(mode, bpc)

    np.testing.assert_array_equal(image.image_data_rgb_8bit_display, image.image_data_rgb_8bit)
