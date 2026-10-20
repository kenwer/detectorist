import pytest

from detectorist.structures import clamp_box


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
