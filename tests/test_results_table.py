"""Tests for how the results table shows scores."""

import pytest

from detectorist.results_table import format_score


@pytest.mark.parametrize(("score", "expected"), [
    (0.0, "0.00"),
    (0.534, "0.53"),
    (0.987, "0.99"),
    # Would round to 1.00, which claims a certainty the model never has
    (0.9951, "0.99"),
    (0.9996, "0.99"),
    (1.0, "0.99"),
    # A family's score is a float32 sum of its species' probabilities and can pass 1
    (1.0000002, "0.99"),
])
def test_format_score_never_shows_one(score, expected):
    assert format_score(score) == expected
