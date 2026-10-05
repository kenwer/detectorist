"""Tests for the DetectionWorker's cache, prefetch scheduling and model loading.

The worker normally lives on a QThread. Here it stays on the test thread and
qtbot pumps the queued _process_loop invocations, so the tests run headless
with no real model. The detector is faked, either by assigning
worker.detector directly or through the injected detector factory.
"""

from detectorist.worker import DetectionWorker
from tests.fakes import FakeDetector, FakeDetectorFactory, make_images

IMAGE_SIZE = (32, 24)


def make_worker():
    worker = DetectionWorker()
    worker.detector = FakeDetector()
    completed = []
    worker.detection_complete.connect(lambda path, results, ms: completed.append((path, results)))
    return worker, completed


def test_repeated_request_is_served_from_cache(qtbot, tmp_path):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    worker, completed = make_worker()

    worker.process_image(path_a, False, [])
    qtbot.waitUntil(lambda: len(completed) == 1)

    worker.process_image(path_a, False, [])
    qtbot.waitUntil(lambda: len(completed) == 2)

    assert worker.detector.detected == ["a.png"]
    assert completed[0] == completed[1]


def test_prefetch_hint_fills_cache_while_idle(qtbot, tmp_path):
    path_a, path_b = make_images(tmp_path, ["a.png", "b.png"], IMAGE_SIZE)
    worker, completed = make_worker()

    worker.process_image(path_a, False, [path_b])
    qtbot.waitUntil(lambda: worker.detector.detected == ["a.png", "b.png"])
    assert len(completed) == 1  # prefetching emits no signals

    worker.process_image(path_b, False, [])
    qtbot.waitUntil(lambda: len(completed) == 2)
    assert worker.detector.detected == ["a.png", "b.png"]  # no re-detection
    assert completed[1][0] == path_b


def test_clear_cache_forces_reprocessing(qtbot, tmp_path):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    worker, completed = make_worker()

    worker.process_image(path_a, False, [])
    qtbot.waitUntil(lambda: len(completed) == 1)

    worker.clear_cache()
    worker.process_image(path_a, False, [])
    qtbot.waitUntil(lambda: len(completed) == 2)
    assert worker.detector.detected == ["a.png", "a.png"]


def test_cache_updated_reports_paths_after_detection_and_prefetch(qtbot, tmp_path):
    path_a, path_b = make_images(tmp_path, ["a.png", "b.png"], IMAGE_SIZE)
    worker, completed = make_worker()
    cache_updates = []
    worker.cache_updated.connect(cache_updates.append)

    worker.process_image(path_a, False, [path_b])
    qtbot.waitUntil(lambda: worker.detector.detected == ["a.png", "b.png"])

    assert cache_updates[-2] == [path_a]
    assert cache_updates[-1] == [path_a, path_b]


def test_cache_updated_reports_empty_after_clear_cache(qtbot, tmp_path):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    worker, completed = make_worker()
    cache_updates = []
    worker.cache_updated.connect(cache_updates.append)

    worker.process_image(path_a, False, [])
    qtbot.waitUntil(lambda: len(completed) == 1)

    worker.clear_cache()
    assert cache_updates[-1] == []


def test_prefetch_failure_is_swallowed(qtbot, tmp_path):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    missing = str(tmp_path / "missing.png")
    worker, completed = make_worker()
    errors = []
    worker.error.connect(lambda path, message: errors.append(path))

    worker.process_image(path_a, False, [missing])
    # The request and its prefetch hints are served by one _process_loop
    # invocation, so once the result is in, the failed prefetch has run too.
    qtbot.waitUntil(lambda: len(completed) == 1)

    assert errors == []
    assert worker.detector.detected == ["a.png"]


def make_loading_worker(factory):
    worker = DetectionWorker(detector_factory=factory)
    loaded = []
    worker.model_loaded.connect(lambda ok, message, class_names: loaded.append((ok, message, class_names)))
    return worker, loaded


def test_load_model_reports_sorted_class_names(qapp):
    factory = FakeDetectorFactory(class_names={1: "Fish", 2: "Crab"})
    worker, loaded = make_loading_worker(factory)

    worker.load_model("/models/a.onnx")

    assert loaded == [(True, "Loaded model: /models/a.onnx", ["Crab", "Fish"])]
    assert worker.detector is factory.created[0]


def test_load_model_failure_is_reported_and_leaves_no_detector(qapp):
    factory = FakeDetectorFactory()
    factory.error = OSError("boom")
    worker, loaded = make_loading_worker(factory)

    worker.load_model("/models/a.onnx")

    assert loaded == [(False, "Error loading model: boom", [])]
    assert worker.detector is None


def test_loading_the_same_model_twice_is_skipped(qapp):
    factory = FakeDetectorFactory()
    worker, loaded = make_loading_worker(factory)

    worker.load_model("/models/a.onnx")
    worker.load_model("/models/a.onnx")

    assert len(factory.created) == 1
    assert len(loaded) == 1


def test_loading_another_model_drops_cached_results(qtbot, tmp_path):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    factory = FakeDetectorFactory()
    worker, loaded = make_loading_worker(factory)
    completed = []
    worker.detection_complete.connect(lambda path, results, ms: completed.append(path))

    worker.load_model("/models/a.onnx")
    worker.process_image(path_a, False, [])
    qtbot.waitUntil(lambda: len(completed) == 1)

    worker.load_model("/models/b.onnx")
    worker.process_image(path_a, False, [])
    qtbot.waitUntil(lambda: len(completed) == 2)

    # Results from the first model must not be served for the second
    assert [detector.detected for detector in factory.created] == [["a.png"], ["a.png"]]


def test_request_after_unload_reports_an_error(qtbot, tmp_path):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    worker, loaded = make_loading_worker(FakeDetectorFactory())
    errors = []
    worker.error.connect(lambda path, message: errors.append((path, message)))

    worker.load_model("/models/a.onnx")
    worker.unload_model()
    worker.process_image(path_a, False, [])
    qtbot.waitUntil(lambda: len(errors) == 1)

    assert errors == [(path_a, "Model not loaded.")]
