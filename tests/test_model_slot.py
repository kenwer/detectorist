"""Tests for the ModelSlot, which loads a model on a pool thread and reports only the one wanted last."""
import threading

import pytest

from detectorist.jobs import ModelId
from detectorist.model_slot import ModelSlot


@pytest.fixture
def model_paths(tmp_path):
    paths = []
    for name in ("a.onnx", "b.onnx"):
        path = tmp_path / name
        path.write_bytes(b"model")
        paths.append(str(path))
    return paths


def test_reports_the_loaded_model(qtbot, model_paths):
    path = model_paths[0]
    slot = ModelSlot(lambda path, *args: ("model", path, args))

    with qtbot.waitSignal(slot.loaded) as blocker:
        slot.load(path, ["Fish"])
        assert slot.loading == ModelId.from_path(path)
        assert slot.expected

    assert blocker.args == [("model", path, (["Fish"],)), path]
    assert slot.model_id == ModelId.from_path(path)
    assert slot.loading is None
    assert slot.wants(path)
    slot.shutdown()


def test_reports_a_failing_factory(qtbot, model_paths):
    def factory(path):
        raise RuntimeError("broken")
    slot = ModelSlot(factory)

    with qtbot.waitSignal(slot.failed) as blocker:
        slot.load(model_paths[0])

    assert blocker.args == ["broken"]
    assert slot.requested and not slot.expected
    slot.shutdown()


def test_a_missing_file_fails_right_away(qtbot, tmp_path):
    slot = ModelSlot(lambda path: "model")

    with qtbot.waitSignal(slot.failed, timeout=0):
        slot.load(str(tmp_path / "missing.onnx"))

    assert slot.requested and not slot.expected
    assert not slot.wants(str(tmp_path / "missing.onnx"))


def test_reports_only_the_model_wanted_last(qtbot, model_paths):
    first, second = model_paths
    release = threading.Event()
    loaded = []

    def factory(path):
        if path == first:
            release.wait()
        return path
    slot = ModelSlot(factory)
    slot.loaded.connect(lambda model, path: loaded.append(model))

    slot.load(first)
    with qtbot.waitSignal(slot.loaded):
        slot.load(second)
    release.set()
    slot.shutdown()
    qtbot.wait(50)  # lets the superseded result arrive, if it were reported

    assert loaded == [second]


def test_a_dropped_load_is_not_reported(qtbot, model_paths):
    release = threading.Event()

    def factory(path):
        release.wait()
        return path
    slot = ModelSlot(factory)
    with qtbot.assertNotEmitted(slot.loaded, wait=50):
        slot.load(model_paths[0])
        slot.drop()
        release.set()
        slot.shutdown()

    assert not slot.requested and not slot.expected
