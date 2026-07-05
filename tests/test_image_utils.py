"""Tests for the LUT-based exposure adjustment in image_utils.

adjust_exposure_inplace applies a precomputed lookup table for speed. These
tests pin its output to a direct per-pixel reference implementation of the
same math, so the optimization cannot drift from the intended policy.
"""

import numpy as np
import pytest

from detectorist import image_utils


def reference_adjust(color_data, ev, gamma):
    """Per-pixel float implementation of the exposure adjustment policy."""
    max_val = (2 ** (color_data.dtype.itemsize * 8)) - 1
    normalized = color_data.astype(np.float32) / max_val
    adjusted = np.power(np.power(normalized, gamma) * (2.0 ** ev), 1.0 / gamma) * max_val
    return np.clip(adjusted, 0, max_val).astype(color_data.dtype)


@pytest.mark.parametrize("dtype", [np.uint8, np.uint16])
@pytest.mark.parametrize("ev", [-1.0, -0.3, 0.7, 1.0])
def test_matches_per_pixel_reference(dtype, ev):
    rng = np.random.default_rng(42)
    max_val = (2 ** (np.dtype(dtype).itemsize * 8)) - 1
    data = rng.integers(0, max_val + 1, size=(32, 24, 3), dtype=dtype)

    adjusted = image_utils.adjust_exposure(data, ev, 2.2)

    np.testing.assert_array_equal(adjusted, reference_adjust(data, ev, 2.2))


def test_alpha_channel_is_not_adjusted():
    rng = np.random.default_rng(42)
    data = rng.integers(0, 256, size=(32, 24, 4), dtype=np.uint8)

    adjusted = image_utils.adjust_exposure(data, 1.0, 2.2)

    np.testing.assert_array_equal(adjusted[:, :, 3], data[:, :, 3])
    np.testing.assert_array_equal(adjusted[:, :, :3], reference_adjust(data[:, :, :3], 1.0, 2.2))


def test_grayscale_is_adjusted():
    rng = np.random.default_rng(42)
    data = rng.integers(0, 256, size=(32, 24), dtype=np.uint8)

    adjusted = image_utils.adjust_exposure(data, 1.0, 2.2)

    np.testing.assert_array_equal(adjusted, reference_adjust(data, 1.0, 2.2))


def test_non_contiguous_input_is_adjusted_in_place():
    rng = np.random.default_rng(42)
    padded = rng.integers(0, 256, size=(32, 24, 4), dtype=np.uint8)
    view = padded[:, :, :3]
    expected = reference_adjust(view.copy(), 1.0, 2.2)
    untouched_channel = padded[:, :, 3].copy()

    image_utils.adjust_exposure_inplace(view, 1.0, 2.2)

    np.testing.assert_array_equal(view, expected)
    np.testing.assert_array_equal(padded[:, :, 3], untouched_channel)
