"""Tests for the ModelLoader, which loads a model on a pool thread and reports only the one wanted last."""
import threading

import pytest

from detectorist.model_loader import ModelLoader
from detectorist.utils import FileStamp


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
    loader = ModelLoader(lambda path, *args: ("model", path, args))

    with qtbot.waitSignal(loader.loaded) as blocker:
        loader.load(path, ["Fish"])
        assert loader.is_loaded_or_loading
        assert not loader.needs_load(path)

    assert blocker.args == [("model", path, (["Fish"],)), path]
    assert loader.model_id == FileStamp.from_path(path)
    assert not loader.needs_load(path)
    loader.shutdown()


def test_reports_a_failing_factory(qtbot, model_paths):
    def factory(path):
        raise RuntimeError("broken")
    loader = ModelLoader(factory)

    with qtbot.waitSignal(loader.failed) as blocker:
        loader.load(model_paths[0])

    assert blocker.args == ["broken"]
    assert loader.requested and not loader.is_loaded_or_loading
    loader.shutdown()


def test_a_missing_file_fails_right_away(qtbot, tmp_path):
    loader = ModelLoader(lambda path: "model")

    with qtbot.waitSignal(loader.failed, timeout=0):
        loader.load(str(tmp_path / "missing.onnx"))

    assert loader.requested and not loader.is_loaded_or_loading
    assert loader.needs_load(str(tmp_path / "missing.onnx"))


def test_reports_only_the_model_wanted_last(qtbot, model_paths):
    first, second = model_paths
    release = threading.Event()
    loaded = []

    def factory(path):
        if path == first:
            release.wait()
        return path
    loader = ModelLoader(factory)
    loader.loaded.connect(lambda model, path: loaded.append(model))

    loader.load(first)
    with qtbot.waitSignal(loader.loaded):
        loader.load(second)
    release.set()
    loader.shutdown()
    qtbot.wait(50)  # lets the superseded result arrive, if it were reported

    assert loaded == [second]


def test_a_load_cancelled_by_unload_is_not_reported(qtbot, model_paths):
    release = threading.Event()

    def factory(path):
        release.wait()
        return path
    loader = ModelLoader(factory)
    with qtbot.assertNotEmitted(loader.loaded, wait=50):
        loader.load(model_paths[0])
        loader.unload()
        release.set()
        loader.shutdown()

    assert not loader.requested and not loader.is_loaded_or_loading
