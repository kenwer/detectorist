import numpy as np
import pytest

from detectorist.structures import PackedMask, clamp_box


@pytest.mark.parametrize(("box", "expected"), [
    ((10, 20, 30, 40), (10, 20, 40, 60)),
    ((-5, -8, 30, 40), (0, 0, 25, 32)),
    ((90, 70, 30, 40), (90, 70, 100, 80)),
    # Entirely outside: zero area, so callers can skip it
    ((150, 10, 20, 20), (100, 10, 100, 30)),
    ((-50, 10, 20, 20), (0, 10, 0, 30)),
])
def test_clamp_box_keeps_the_part_inside_the_image(box, expected):
    assert clamp_box(box, 100, 80) == expected


def test_packed_mask_round_trips():
    mask = np.random.default_rng(0).choice([0, 255], size=(504, 504)).astype(np.uint8)

    assert np.array_equal(PackedMask.pack(mask).unpack(), mask)


def test_packed_mask_counts_its_area():
    mask = np.zeros((40, 30), dtype=np.uint8)
    mask[5:15, 10:20] = 255

    assert PackedMask.pack(mask).area == 100


def test_packed_mask_is_small_for_a_sparse_mask():
    mask = np.zeros((504, 504), dtype=np.uint8)
    mask[100:150, 200:250] = 255

    assert PackedMask.pack(mask).nbytes < 2000
