"""Tests for the DetectionWorker's cache, prefetch scheduling and model loading.

The worker normally lives on a QThread. Here it stays on the test thread and
qtbot pumps the queued _process_loop invocations, so the tests run headless
with no real model. The detector is faked, either by assigning
worker.detector directly or through the injected detector factory.
"""

from detectorist.structures import Detection
from detectorist.worker import DetectionWorker
from tests.fakes import TAXONOMY, FakeClassifierFactory, FakeDetector, FakeDetectorFactory, make_images

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

    worker.process_image(path_a, False, [], 0.0)
    qtbot.waitUntil(lambda: len(completed) == 1)

    worker.process_image(path_a, False, [], 0.0)
    qtbot.waitUntil(lambda: len(completed) == 2)

    assert worker.detector.detected == ["a.png"]
    assert completed[0] == completed[1]


def test_prefetch_hint_fills_cache_while_idle(qtbot, tmp_path):
    path_a, path_b = make_images(tmp_path, ["a.png", "b.png"], IMAGE_SIZE)
    worker, completed = make_worker()

    worker.process_image(path_a, False, [path_b], 0.0)
    qtbot.waitUntil(lambda: worker.detector.detected == ["a.png", "b.png"])
    assert len(completed) == 1  # prefetching emits no signals

    worker.process_image(path_b, False, [], 0.0)
    qtbot.waitUntil(lambda: len(completed) == 2)
    assert worker.detector.detected == ["a.png", "b.png"]  # no re-detection
    assert completed[1][0] == path_b


def test_clear_cache_forces_reprocessing(qtbot, tmp_path):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    worker, completed = make_worker()

    worker.process_image(path_a, False, [], 0.0)
    qtbot.waitUntil(lambda: len(completed) == 1)

    worker.clear_cache()
    worker.process_image(path_a, False, [], 0.0)
    qtbot.waitUntil(lambda: len(completed) == 2)
    assert worker.detector.detected == ["a.png", "a.png"]


def test_cache_updated_reports_paths_after_detection_and_prefetch(qtbot, tmp_path):
    path_a, path_b = make_images(tmp_path, ["a.png", "b.png"], IMAGE_SIZE)
    worker, completed = make_worker()
    cache_updates = []
    worker.cache_updated.connect(cache_updates.append)

    worker.process_image(path_a, False, [path_b], 0.0)
    qtbot.waitUntil(lambda: worker.detector.detected == ["a.png", "b.png"])

    assert cache_updates[-2] == [path_a]
    assert cache_updates[-1] == [path_a, path_b]


def test_cache_updated_reports_empty_after_clear_cache(qtbot, tmp_path):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    worker, completed = make_worker()
    cache_updates = []
    worker.cache_updated.connect(cache_updates.append)

    worker.process_image(path_a, False, [], 0.0)
    qtbot.waitUntil(lambda: len(completed) == 1)

    worker.clear_cache()
    assert cache_updates[-1] == []


def test_prefetch_failure_is_swallowed(qtbot, tmp_path):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    missing = str(tmp_path / "missing.png")
    worker, completed = make_worker()
    errors = []
    worker.error.connect(lambda path, message: errors.append(path))

    worker.process_image(path_a, False, [missing], 0.0)
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
    worker.process_image(path_a, False, [], 0.0)
    qtbot.waitUntil(lambda: len(completed) == 1)

    worker.load_model("/models/b.onnx")
    worker.process_image(path_a, False, [], 0.0)
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
    worker.process_image(path_a, False, [], 0.0)
    qtbot.waitUntil(lambda: len(errors) == 1)

    assert errors == [(path_a, "Model not loaded.")]


FISH = Detection((1, 1, 10, 10), 0.9, "Fish")
FAINT_FISH = Detection((2, 2, 10, 10), 0.3, "Fish")
CRAB = Detection((3, 3, 10, 10), 0.8, "Crab")


def make_classifying_worker(detections_by_file, patterns=("Fish",)):
    """A worker with a fake detector and a fake classifier for the given patterns."""
    factory = FakeClassifierFactory()
    worker = DetectionWorker(classifier_factory=factory)
    worker.detector = FakeDetector(detections_by_file)
    worker.set_classifier("/models/species.onnx", list(patterns))
    named, errors = [], []
    worker.classification_complete.connect(lambda path, taxonomy: named.append((path, taxonomy)))
    worker.classifier_error.connect(errors.append)
    return worker, factory, named, errors


def test_detections_above_min_score_of_the_classified_classes_are_named(qtbot, tmp_path):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    worker, factory, named, _ = make_classifying_worker({"a.png": [FISH, FAINT_FISH, CRAB]})

    worker.process_image(path_a, False, [], 0.5)
    qtbot.waitUntil(lambda: len(named) == 1)

    assert named == [(path_a, {FISH.box: TAXONOMY})]
    assert factory.classified == [[FISH.box]]


def test_names_are_cached_with_the_image(qtbot, tmp_path):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    worker, factory, named, _ = make_classifying_worker({"a.png": [FISH, FAINT_FISH]})

    worker.process_image(path_a, False, [], 0.5)
    qtbot.waitUntil(lambda: len(named) == 1)
    # A lower confidence only costs the boxes not named yet
    worker.process_image(path_a, False, [], 0.1)
    qtbot.waitUntil(lambda: len(named) == 2)

    assert factory.classified == [[FISH.box], [FAINT_FISH.box]]
    assert named[1][1] == {FISH.box: TAXONOMY, FAINT_FISH.box: TAXONOMY}


def test_classify_image_names_the_boxes_a_lower_confidence_reveals(qtbot, tmp_path):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    worker, factory, named, _ = make_classifying_worker({"a.png": [FISH, FAINT_FISH]})
    worker.process_image(path_a, False, [], 0.5)
    qtbot.waitUntil(lambda: len(named) == 1)
    served = []
    worker.detection_complete.connect(lambda path, results, ms: served.append(path))

    worker.classify_image(path_a, 0.1)

    assert factory.classified == [[FISH.box], [FAINT_FISH.box]]
    assert named[1] == (path_a, {FISH.box: TAXONOMY, FAINT_FISH.box: TAXONOMY})
    assert served == []


def test_classify_image_ignores_an_image_that_is_not_cached(tmp_path):
    worker, factory, named, _ = make_classifying_worker({})

    worker.classify_image(str(tmp_path / "gone.png"), 0.1)

    assert factory.classified == []
    assert named == []


def test_prefetch_names_the_neighbours(qtbot, tmp_path):
    path_a, path_b = make_images(tmp_path, ["a.png", "b.png"], IMAGE_SIZE)
    worker, factory, named, _ = make_classifying_worker({"a.png": [FISH], "b.png": [FISH]})

    worker.process_image(path_a, False, [path_b], 0.5)
    qtbot.waitUntil(lambda: len(factory.classified) == 2)
    worker.process_image(path_b, False, [], 0.5)
    qtbot.waitUntil(lambda: len(named) == 2)

    assert len(factory.classified) == 2


def test_another_classifier_names_a_cached_image_again_without_serving_it_again(qtbot, tmp_path):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    worker, factory, named, _ = make_classifying_worker({"a.png": [FISH]})
    worker.process_image(path_a, False, [], 0.5)
    qtbot.waitUntil(lambda: len(named) == 1)
    served = []
    worker.detection_complete.connect(lambda path, results, ms: served.append(path))

    worker.set_classifier("/models/other.onnx", ["*"])
    worker.classify_image(path_a, 0.5)

    assert named[1] == (path_a, {FISH.box: TAXONOMY})
    assert factory.created[1].classified == [[FISH.box]]
    assert served == []


def test_unloading_the_classifier_reports_nothing(qtbot, tmp_path):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    worker, _, named, _ = make_classifying_worker({"a.png": [FISH]})
    worker.process_image(path_a, False, [], 0.5)
    qtbot.waitUntil(lambda: len(named) == 1)

    worker.set_classifier("", [])
    worker.classify_image(path_a, 0.5)

    assert worker.classifier is None
    assert len(named) == 1


def test_a_failing_classifier_is_reported_and_the_detections_stay(qtbot, tmp_path):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    worker, factory, named, errors = make_classifying_worker({"a.png": [FISH]})
    factory.classify_error = RuntimeError("out of memory")
    worker.set_classifier("/models/broken.onnx", ["Fish"])

    worker.process_image(path_a, False, [], 0.5)
    qtbot.waitUntil(lambda: len(named) == 1)

    assert errors == ["a.png: out of memory"]
    assert named == [(path_a, {})]


def test_a_classifier_that_fails_to_load_is_reported(qapp):
    worker, factory, _, errors = make_classifying_worker({})
    factory.error = OSError("not a classifier")

    worker.set_classifier("/models/broken.onnx", ["Fish"])

    assert errors == ["Error loading classifier: not a classifier"]
    assert worker.classifier is None
