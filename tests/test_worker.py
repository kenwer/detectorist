"""Tests for the DetectionWorker's cache, prefetch scheduling and model loading.

The worker normally lives on a QThread. Here it stays on the test thread and
qtbot pumps the queued _process_loop invocations, so the tests run headless
with no real model. The detector is faked, either by assigning
worker.detector directly or through the injected detector factory.
"""

import os
from types import SimpleNamespace

from detectorist import worker as worker_module
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
    worker.model_loaded.connect(lambda ok, message, class_names, _is_segmentation: loaded.append((ok, message, class_names)))
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
    worker.classification_complete.connect(lambda path, taxonomy, ms: named.append((path, taxonomy)))
    worker.classifier_error.connect(errors.append)
    return worker, factory, named, errors


def test_detections_above_min_detection_score_of_the_classified_classes_are_named(qtbot, tmp_path):
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


def test_classification_time_sums_the_runs_until_another_classifier_is_loaded(qtbot, tmp_path, monkeypatch):
    # Each reading of the clock is 100 ms after the previous one, so a run takes 100 ms
    ticks = iter(range(1000))
    # The worker's own time module, as patching time.perf_counter would reach every caller
    monkeypatch.setattr(worker_module, "time", SimpleNamespace(perf_counter=lambda: next(ticks) / 10))
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    worker, _, _, _ = make_classifying_worker({"a.png": [FISH, FAINT_FISH]})
    times = []
    worker.classification_complete.connect(lambda path, taxonomy, ms: times.append(round(ms)))
    worker.process_image(path_a, False, [], 0.5)
    qtbot.waitUntil(lambda: len(times) == 1)

    worker.classify_image(path_a, 0.1)
    # Nothing is left to name
    worker.classify_image(path_a, 0.1)
    worker.set_classifier("/models/other.onnx", ["Fish"])
    worker.classify_image(path_a, 0.1)

    assert times == [100, 200, 200, 100]


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


def test_requesting_the_image_being_prefetched_shows_it_before_naming_its_boxes(qtbot, tmp_path):
    path_a, path_b = make_images(tmp_path, ["a.png", "b.png"], IMAGE_SIZE)
    worker, factory, named, _ = make_classifying_worker({"a.png": [FISH], "b.png": [FISH]})
    # The number of classify() calls made by the time each image is shown
    classified_when_shown = {}
    worker.image_loaded.connect(
        lambda path, image: classified_when_shown.setdefault(os.path.basename(path), len(factory.classified)))

    def request_b_while_prefetching_it(name):
        if name == "b.png":
            worker.process_image(path_b, False, [], 0.5)

    worker.detector.on_detect = request_b_while_prefetching_it

    worker.process_image(path_a, False, [path_b], 0.5)
    qtbot.waitUntil(lambda: len(named) == 2)

    # Only a.png was named when b.png was shown, b.png is named afterwards
    assert classified_when_shown["b.png"] == 1
    assert len(factory.classified) == 2
    assert named[1] == (path_b, {FISH.box: TAXONOMY})


def test_requesting_the_image_being_prefetched_shows_it_before_detecting(qtbot, tmp_path, monkeypatch):
    path_a, path_b = make_images(tmp_path, ["a.png", "b.png"], IMAGE_SIZE)
    worker, _, named, _ = make_classifying_worker({"a.png": [FISH], "b.png": [FISH]})
    events = []
    worker.image_loaded.connect(lambda path, image: events.append(("shown", os.path.basename(path))))
    worker.detector.on_detect = lambda name: events.append(("detected", name))
    create = worker_module.ImageObject.create

    def create_and_request(image_path):
        image = create(image_path)
        events.append(("decoded", os.path.basename(image_path)))
        if image_path == path_b and worker._latest_request_params[0] == path_a:
            worker.process_image(path_b, False, [], 0.5)
        return image

    monkeypatch.setattr(worker_module.ImageObject, "create", staticmethod(create_and_request))

    worker.process_image(path_a, False, [path_b], 0.5)
    qtbot.waitUntil(lambda: len(named) == 2)

    # The image decoded by the prefetch is handed to the request, not decoded again
    assert events[3:] == [("decoded", "b.png"), ("shown", "b.png"), ("detected", "b.png")]


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


def test_a_classifier_that_fails_to_load_reports_the_image_without_names(qtbot, tmp_path):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    worker, factory, named, errors = make_classifying_worker({"a.png": [FISH]})
    factory.error = RuntimeError("bad model file")
    worker.set_classifier("/models/broken.onnx", ["Fish"])

    worker.process_image(path_a, False, [], 0.5)
    qtbot.waitUntil(lambda: len(named) == 1)

    assert errors == ["Error loading classifier: bad model file"]
    assert named == [(path_a, {})]


def test_a_classifier_failing_in_the_prefetch_stays_silent_until_the_image_is_requested(qtbot, tmp_path):
    path_a, path_b = make_images(tmp_path, ["a.png", "b.png"], IMAGE_SIZE)
    worker, factory, named, errors = make_classifying_worker({"a.png": [FISH], "b.png": [FISH]})
    factory.classify_error = RuntimeError("out of memory")
    worker.set_classifier("/models/broken.onnx", ["Fish"])
    cached = []
    worker.cache_updated.connect(cached.append)

    worker.process_image(path_a, False, [path_b], 0.5)
    qtbot.waitUntil(lambda: worker.detector.detected == ["a.png", "b.png"])

    assert errors == ["a.png: out of memory"]
    assert named == [(path_a, {})]
    # Neither image is highlighted, as a request would still have to name its boxes
    assert cached[-1] == []

    # The request retries the classification the prefetch failed
    factory.created[-1].error = None
    worker.process_image(path_b, False, [], 0.5)
    qtbot.waitUntil(lambda: len(named) == 2)

    assert named[1] == (path_b, {FISH.box: TAXONOMY})


def test_a_classifier_that_fails_to_load_is_reported(qapp):
    worker, factory, _, errors = make_classifying_worker({})
    factory.error = OSError("not a classifier")

    worker.set_classifier("/models/broken.onnx", ["Fish"])

    assert errors == ["Error loading classifier: not a classifier"]
    assert worker.classifier is None


def test_a_classified_image_is_reported_only_once_its_boxes_are_named(qtbot, tmp_path):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    worker, _, named, _ = make_classifying_worker({"a.png": [FISH]})
    cached = []
    worker.cache_updated.connect(cached.append)

    worker.process_image(path_a, False, [], 0.5)
    qtbot.waitUntil(lambda: len(named) == 1)

    assert [path_a] not in cached[:-1]
    assert cached[-1] == [path_a]


def test_an_image_without_boxes_to_name_is_reported_with_its_detections(qtbot, tmp_path):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    worker, factory, named, _ = make_classifying_worker({"a.png": [CRAB]})
    cached = []
    worker.cache_updated.connect(cached.append)

    worker.process_image(path_a, False, [], 0.5)
    qtbot.waitUntil(lambda: len(named) == 1)

    assert factory.classified == []
    assert cached[-1] == [path_a]


def test_a_lower_confidence_unreports_the_images_with_boxes_left_to_name(qtbot, tmp_path):
    path_a, path_b = make_images(tmp_path, ["a.png", "b.png"], IMAGE_SIZE)
    worker, _, _, _ = make_classifying_worker({"a.png": [FISH, FAINT_FISH], "b.png": [FISH, FAINT_FISH]})
    cached = []
    worker.cache_updated.connect(cached.append)
    worker.process_image(path_a, False, [path_b], 0.5)
    qtbot.waitUntil(lambda: [path_a, path_b] in cached)

    # Names the faint fish of the shown image only
    worker.classify_image(path_a, 0.1)

    assert cached[-1] == [path_a]


def test_another_classifier_unreports_the_cached_images_until_they_are_named_again(qtbot, tmp_path):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    worker, _, named, _ = make_classifying_worker({"a.png": [FISH]})
    cached = []
    worker.cache_updated.connect(cached.append)
    worker.process_image(path_a, False, [], 0.5)
    qtbot.waitUntil(lambda: len(named) == 1)

    worker.set_classifier("/models/other.onnx", ["Fish"])
    assert cached[-1] == []

    worker.classify_image(path_a, 0.5)
    assert cached[-1] == [path_a]


def test_unloading_the_classifier_reports_the_detected_images(qtbot, tmp_path):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    worker, factory, _, _ = make_classifying_worker({"a.png": [FISH]})
    factory.classify_error = RuntimeError("out of memory")
    worker.set_classifier("/models/broken.onnx", ["Fish"])
    cached = []
    worker.cache_updated.connect(cached.append)
    worker.process_image(path_a, False, [], 0.5)
    qtbot.waitUntil(lambda: worker.detector.detected == ["a.png"])
    assert cached[-1] == []

    worker.set_classifier("", [])

    assert cached[-1] == [path_a]
