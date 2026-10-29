"""Tests for ModelState, where a ModelLoader is with its model."""
import pytest

from detectorist.model_state import ModelState


@pytest.mark.parametrize(("state", "expected"), [
    (ModelState.NONE, False),
    (ModelState.LOADING, True),
    (ModelState.LOADED, True),
    (ModelState.FAILED, False),
])
def test_only_a_loading_or_loaded_model_has_results_coming(state, expected):
    assert state.is_loaded_or_loading is expected
