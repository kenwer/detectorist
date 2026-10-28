"""Tests for the Pipeline, which schedules decode and inference jobs and owns the caches.

The lanes run on real threads with fake models, so the queued signals
between the Pipeline and its workers are what runs in production. A
Recorder keeps everything the Pipeline reports.
"""

import os
import threading
import time
from types import SimpleNamespace

import pytest

from detectorist import inference_worker as inference_worker_module
from detectorist.batch_run import BatchOptions, BatchWriter, CropExportAction
from detectorist.export_planner import CropMode, CropSettings, ExportOptions
from detectorist.jobs import ShowRequest
from detectorist.pipeline import Pipeline, neighbours
from detectorist.structures import Detection
from tests.fakes import TAXONOMY, FakeClassifierFactory, FakeDetectorFactory, make_images

IMAGE_SIZE = (32, 24)
FISH = Detection((1, 1, 10, 10), 0.9, "Fish")
FAINT_FISH = Detection((2, 2, 10, 10), 0.3, "Fish")
CRAB = Detection((3, 3, 10, 10), 0.8, "Crab")
BATCH_CROP = CropSettings(mode=CropMode.MOST_CONFIDENT_DETECTION, padding=0.0, aspect=(1, 1))


class Recorder:
    """Everything a Pipeline reported, in order."""

    def __init__(self, pipeline: Pipeline):
        self.shown: list[str] = []
        self.displays: list = []
        self.completed: list[tuple[str, list]] = []
        self.named: list[tuple[str, dict]] = []
        self.times: list[int] = []
        self.errors: list[tuple[str, str]] = []
        self.classifier_errors: list[str] = []
        self.cached: list[list[str]] = []
        self.models: list[tuple[bool, str, list]] = []
        pipeline.image_loaded.connect(self._image_loaded)
        pipeline.detection_complete.connect(lambda path, results, ms: self.completed.append((path, results)))
        pipeline.classification_complete.connect(self._named)
        pipeline.error.connect(lambda path, message: self.errors.append((path, message)))
        pipeline.classifier_error.connect(self.classifier_errors.append)
        pipeline.cache_updated.connect(self.cached.append)
        pipeline.model_loaded.connect(lambda ok, message, names, _seg: self.models.append((ok, message, names)))

    def _image_loaded(self, path, image, display):
        self.shown.append(path)
        self.displays.append(display)

    def _named(self, path, names, ms):
        self.named.append((path, names))
        self.times.append(round(ms))

    @property
    def cached_now(self) -> list[str]:
        """What the image list would highlight now. cache_updated only reports changes, so none means none."""
        return self.cached[-1] if self.cached else []


@pytest.fixture
def models_dir(tmp_path):
    folder = tmp_path / "models"
    folder.mkdir()
    for name in ("a.onnx", "b.onnx", "species.onnx", "other.onnx", "broken.onnx"):
        (folder / name).write_bytes(b"model")
    return folder


@pytest.fixture
def make_pipeline(qtbot, models_dir):
    """Build Pipelines with fake models, the detector a.onnx loaded, shut down after the test."""
    pipelines = []

    def make(detections_by_file=None, patterns=None, classifier_factory=None, detector_factory=None, **kwargs):
        detector_factory = detector_factory or FakeDetectorFactory(detections_by_file)
        classifier_factory = classifier_factory or FakeClassifierFactory()
        pipeline = Pipeline(detector_factory, classifier_factory, **kwargs)
        pipelines.append(pipeline)
        recorder = Recorder(pipeline)
        pipeline.load_detector(str(models_dir / "a.onnx"))
        qtbot.waitUntil(lambda: bool(recorder.models))
        if patterns is not None:
            pipeline.load_classifier(str(models_dir / "species.onnx"), list(patterns))
        return SimpleNamespace(pipeline=pipeline, rec=recorder, detectors=detector_factory,
                               classifiers=classifier_factory)

    yield make
    for pipeline in pipelines:
        pipeline.shutdown()


def show(pipeline, path, threshold=0.5, exposure=False):
    pipeline.show(ShowRequest(path, exposure, threshold))


def detected(env) -> list[str]:
    return [name for detector in env.detectors.created for name in detector.detected]


def test_repeated_request_is_served_from_cache(qtbot, tmp_path, make_pipeline):
    path_a, path_b = make_images(tmp_path, ["a.png", "b.png"], IMAGE_SIZE)
    env = make_pipeline({"a.png": [FISH]})

    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.completed) == 1)
    show(env.pipeline, path_b)
    qtbot.waitUntil(lambda: len(env.rec.completed) == 2)
    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.completed) == 3)

    assert detected(env) == ["a.png", "b.png"]
    assert env.rec.completed[2] == (path_a, [FISH])


def test_identical_request_delivers_nothing_again(qtbot, tmp_path, make_pipeline):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    env = make_pipeline()
    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.completed) == 1)

    show(env.pipeline, path_a)
    qtbot.wait(50)

    assert len(env.rec.shown) == 1
    assert len(env.rec.completed) == 1


def test_prefetch_fills_cache_while_idle(qtbot, tmp_path, make_pipeline):
    path_a, path_b = make_images(tmp_path, ["a.png", "b.png"], IMAGE_SIZE)
    env = make_pipeline()

    show(env.pipeline, path_a)
    env.pipeline.prefetch([path_b])
    qtbot.waitUntil(lambda: detected(env) == ["a.png", "b.png"])
    assert [path for path, _ in env.rec.completed] == [path_a]

    show(env.pipeline, path_b)
    qtbot.waitUntil(lambda: len(env.rec.completed) == 2)
    assert detected(env) == ["a.png", "b.png"]
    assert env.rec.shown == [path_a, path_b]


def test_clear_caches_forces_reprocessing(qtbot, tmp_path, make_pipeline):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    env = make_pipeline()
    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.completed) == 1)

    env.pipeline.clear_caches()

    qtbot.waitUntil(lambda: len(env.rec.completed) == 2)
    assert detected(env) == ["a.png", "a.png"]


def test_cache_updated_reports_paths_after_detection_and_prefetch(qtbot, tmp_path, make_pipeline):
    path_a, path_b = make_images(tmp_path, ["a.png", "b.png"], IMAGE_SIZE)
    env = make_pipeline()

    show(env.pipeline, path_a)
    env.pipeline.prefetch([path_b])
    qtbot.waitUntil(lambda: env.rec.cached_now == [path_a, path_b])

    assert [path_a] in env.rec.cached


def test_cache_updated_reports_empty_after_clear_caches(qtbot, tmp_path, make_pipeline):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    env = make_pipeline()
    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: env.rec.cached_now == [path_a])

    env.pipeline.clear_caches()

    assert env.rec.cached_now == []


def test_prefetch_failure_is_silent_until_requested(qtbot, tmp_path, make_pipeline):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    env = make_pipeline()

    show(env.pipeline, path_a)
    env.pipeline.prefetch([str(broken)])
    qtbot.waitUntil(lambda: detected(env) == ["a.png"])
    qtbot.wait(50)
    assert env.rec.errors == []

    show(env.pipeline, str(broken))
    qtbot.waitUntil(lambda: bool(env.rec.errors))
    qtbot.wait(50)

    assert [path for path, _ in env.rec.errors] == [str(broken)]


def test_changed_file_is_detected_again(qtbot, tmp_path, make_pipeline):
    path_a, path_b = make_images(tmp_path, ["a.png", "b.png"], IMAGE_SIZE)
    # A budget this small keeps only the pinned image, so a's image is evicted when b is shown
    env = make_pipeline(image_budget_bytes=1)
    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.completed) == 1)
    show(env.pipeline, path_b)
    qtbot.waitUntil(lambda: len(env.rec.completed) == 2)

    make_images(tmp_path, ["a.png"], (40, 30))
    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.completed) == 3)

    assert detected(env) == ["a.png", "b.png", "a.png"]


def test_unchanged_file_is_only_decoded_again(qtbot, tmp_path, make_pipeline):
    path_a, path_b = make_images(tmp_path, ["a.png", "b.png"], IMAGE_SIZE)
    env = make_pipeline(image_budget_bytes=1)
    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.completed) == 1)
    show(env.pipeline, path_b)
    qtbot.waitUntil(lambda: len(env.rec.completed) == 2)

    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.completed) == 3)

    assert detected(env) == ["a.png", "b.png"]


def test_exposure_change_rebuilds_only_the_display(qtbot, tmp_path, make_pipeline):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    env = make_pipeline()
    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.completed) == 1)

    show(env.pipeline, path_a, exposure=True)
    qtbot.waitUntil(lambda: len(env.rec.shown) == 2)
    qtbot.wait(50)

    assert len(env.rec.completed) == 1
    assert detected(env) == ["a.png"]


def test_load_detector_reports_sorted_class_names(qtbot, make_pipeline, models_dir):
    factory = FakeDetectorFactory(class_names={1: "Fish", 2: "Crab"})
    env = make_pipeline(detector_factory=factory)

    assert env.rec.models == [(True, f"Loaded model: {models_dir / 'a.onnx'}", ["Crab", "Fish"])]


def test_load_detector_failure_is_reported(qtbot, make_pipeline, models_dir):
    env = make_pipeline()
    env.detectors.error = OSError("boom")

    env.pipeline.load_detector(str(models_dir / "b.onnx"))
    qtbot.waitUntil(lambda: len(env.rec.models) == 2)

    assert env.rec.models[1] == (False, "Error loading model: boom", [])


def test_loading_the_same_detector_twice_is_skipped(qtbot, make_pipeline, models_dir):
    env = make_pipeline()

    env.pipeline.load_detector(str(models_dir / "a.onnx"))
    qtbot.wait(50)

    assert len(env.detectors.created) == 1
    assert len(env.rec.models) == 1


def test_loading_another_detector_drops_cached_results(qtbot, tmp_path, make_pipeline, models_dir):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    env = make_pipeline()
    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.completed) == 1)

    env.pipeline.load_detector(str(models_dir / "b.onnx"))
    qtbot.waitUntil(lambda: len(env.rec.completed) == 2)

    # Results from the first model must not be served for the second
    assert [detector.detected for detector in env.detectors.created] == [["a.png"], ["a.png"]]


def test_request_after_unload_reports_an_error(qtbot, tmp_path, make_pipeline):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    env = make_pipeline()

    env.pipeline.unload_detector()
    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: bool(env.rec.errors))

    assert env.rec.errors == [(path_a, "Model not loaded.")]


def test_rapid_requests_end_on_the_last_one(qtbot, tmp_path, make_pipeline):
    paths = make_images(tmp_path, [f"{i:02}.png" for i in range(50)], IMAGE_SIZE)
    env = make_pipeline()

    for path in paths:
        show(env.pipeline, path)
    qtbot.waitUntil(lambda: bool(env.rec.completed) and env.rec.completed[-1][0] == paths[-1])
    qtbot.wait(50)

    assert env.rec.shown[-1] == paths[-1]
    assert env.rec.completed[-1][0] == paths[-1]
    assert len(detected(env)) < 10


def test_result_of_a_replaced_detector_is_dropped(qtbot, tmp_path, make_pipeline, models_dir):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    env = make_pipeline({"a.png": [FISH]})
    first = env.detectors.created[0]
    release = threading.Event()
    first.on_detect = lambda name: release.wait(5)
    # Its own dict, so the next detector's answer cannot leak into it
    first.detections_by_file = {"a.png": [FISH]}

    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: first.detected == ["a.png"])
    env.detectors.detections_by_file["a.png"] = [CRAB]
    env.pipeline.load_detector(str(models_dir / "b.onnx"))
    qtbot.waitUntil(lambda: len(env.rec.models) == 2)
    release.set()
    qtbot.waitUntil(lambda: bool(env.rec.completed))
    qtbot.wait(50)

    assert env.rec.completed == [(path_a, [CRAB])]


def make_classifying(make_pipeline, detections_by_file, patterns=("Fish",)):
    return make_pipeline(detections_by_file, patterns=patterns)


def test_detections_above_the_threshold_of_the_classified_classes_are_named(qtbot, tmp_path, make_pipeline):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    env = make_classifying(make_pipeline, {"a.png": [FISH, FAINT_FISH, CRAB]})

    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.named) == 1)

    assert env.rec.named == [(path_a, {FISH.box: TAXONOMY})]
    assert env.classifiers.classified == [[FISH.box]]


def test_a_lower_threshold_names_only_the_boxes_it_reveals(qtbot, tmp_path, make_pipeline):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    env = make_classifying(make_pipeline, {"a.png": [FISH, FAINT_FISH]})
    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.named) == 1)

    show(env.pipeline, path_a, threshold=0.1)
    qtbot.waitUntil(lambda: len(env.rec.named) == 2)

    assert env.classifiers.classified == [[FISH.box], [FAINT_FISH.box]]
    assert env.rec.named[1] == (path_a, {FISH.box: TAXONOMY, FAINT_FISH.box: TAXONOMY})
    # The image and its detections are not served again
    assert len(env.rec.shown) == 1
    assert len(env.rec.completed) == 1


def test_classification_time_sums_the_runs_until_another_classifier_is_loaded(qtbot, tmp_path, make_pipeline,
                                                                             monkeypatch, models_dir):
    # Each reading of the clock is 100 ms after the previous one, so a run takes 100 ms
    ticks = iter(range(1000))
    # The worker's own time module, as patching time.perf_counter would reach every caller
    monkeypatch.setattr(inference_worker_module, "time", SimpleNamespace(perf_counter=lambda: next(ticks) / 10))
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    env = make_classifying(make_pipeline, {"a.png": [FISH, FAINT_FISH]})
    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.times) == 1)

    show(env.pipeline, path_a, threshold=0.1)
    qtbot.waitUntil(lambda: len(env.rec.times) == 2)
    env.pipeline.load_classifier(str(models_dir / "other.onnx"), ["Fish"])
    qtbot.waitUntil(lambda: len(env.rec.times) == 3)

    assert env.rec.times == [100, 200, 100]


def test_prefetch_names_the_neighbours(qtbot, tmp_path, make_pipeline):
    path_a, path_b = make_images(tmp_path, ["a.png", "b.png"], IMAGE_SIZE)
    env = make_classifying(make_pipeline, {"a.png": [FISH], "b.png": [FISH]})

    show(env.pipeline, path_a)
    env.pipeline.prefetch([path_b])
    qtbot.waitUntil(lambda: len(env.classifiers.classified) == 2)
    show(env.pipeline, path_b)
    qtbot.waitUntil(lambda: len(env.rec.named) == 2)

    assert len(env.classifiers.classified) == 2


def test_requesting_the_image_being_prefetched_shows_it_before_naming_its_boxes(qtbot, tmp_path, make_pipeline):
    path_a, path_b = make_images(tmp_path, ["a.png", "b.png"], IMAGE_SIZE)
    env = make_classifying(make_pipeline, {"a.png": [FISH], "b.png": [FISH]})
    release = threading.Event()
    env.detectors.created[0].on_detect = lambda name: name == "b.png" and release.wait(5)

    show(env.pipeline, path_a)
    env.pipeline.prefetch([path_b])
    qtbot.waitUntil(lambda: "b.png" in detected(env))
    show(env.pipeline, path_b)
    qtbot.waitUntil(lambda: len(env.rec.shown) == 2)
    classified_when_shown = len(env.classifiers.classified)
    release.set()
    qtbot.waitUntil(lambda: len(env.rec.named) == 2)

    # Only a.png was named when b.png was shown, and b.png was detected once
    assert classified_when_shown == 1
    assert detected(env) == ["a.png", "b.png"]
    assert env.rec.named[1] == (path_b, {FISH.box: TAXONOMY})


def test_another_classifier_names_a_cached_image_again_without_serving_it_again(qtbot, tmp_path, make_pipeline,
                                                                              models_dir):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    env = make_classifying(make_pipeline, {"a.png": [FISH]})
    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.named) == 1)

    env.pipeline.load_classifier(str(models_dir / "other.onnx"), ["*"])
    qtbot.waitUntil(lambda: len(env.rec.named) == 2)

    assert env.rec.named[1] == (path_a, {FISH.box: TAXONOMY})
    assert env.classifiers.created[1].classified == [[FISH.box]]
    assert len(env.rec.completed) == 1


def test_unloading_the_classifier_reports_nothing(qtbot, tmp_path, make_pipeline):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    env = make_classifying(make_pipeline, {"a.png": [FISH]})
    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.named) == 1)

    env.pipeline.load_classifier(None, [])
    show(env.pipeline, path_a, threshold=0.1)
    qtbot.wait(50)

    assert len(env.rec.named) == 1


def test_a_failing_classifier_is_reported_and_the_detections_stay(qtbot, tmp_path, make_pipeline):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    classifiers = FakeClassifierFactory()
    classifiers.classify_error = RuntimeError("out of memory")
    env = make_pipeline({"a.png": [FISH]}, patterns=["Fish"], classifier_factory=classifiers)

    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.named) == 1)

    assert env.rec.classifier_errors == ["a.png: out of memory"]
    assert env.rec.named == [(path_a, {})]
    assert env.rec.completed == [(path_a, [FISH])]


def test_failing_classifier_is_not_retried_in_a_loop(qtbot, tmp_path, make_pipeline):
    path_a, path_b, path_c = make_images(tmp_path, ["a.png", "b.png", "c.png"], IMAGE_SIZE)
    classifiers = FakeClassifierFactory()
    classifiers.classify_error = RuntimeError("out of memory")
    env = make_pipeline({"a.png": [FISH], "b.png": [FISH], "c.png": [FISH]}, patterns=["Fish"],
                        classifier_factory=classifiers)
    calls = []
    # A failing FakeClassifier records nothing, so count its calls on the instance make_pipeline loaded
    qtbot.waitUntil(lambda: bool(classifiers.created))
    created = classifiers.created[0]
    failing = created.classify
    created.classify = lambda image, boxes: calls.append(os.path.basename(image.image_path)) or failing(image, boxes)

    show(env.pipeline, path_a)
    env.pipeline.prefetch([path_b, path_c])
    qtbot.waitUntil(lambda: detected(env) == ["a.png", "b.png", "c.png"])
    qtbot.wait(100)

    assert sorted(calls) == ["a.png", "b.png", "c.png"]


def test_a_classifier_that_fails_to_load_reports_the_image_without_names(qtbot, tmp_path, make_pipeline):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    classifiers = FakeClassifierFactory()
    classifiers.error = RuntimeError("bad model file")
    env = make_pipeline({"a.png": [FISH]}, patterns=["Fish"], classifier_factory=classifiers)

    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.named) == 1)

    assert env.rec.classifier_errors == ["Error loading classifier: bad model file"]
    assert env.rec.named == [(path_a, {})]


def test_a_classifier_failing_in_the_prefetch_stays_silent_until_the_image_is_requested(qtbot, tmp_path,
                                                                                      make_pipeline):
    path_a, path_b = make_images(tmp_path, ["a.png", "b.png"], IMAGE_SIZE)
    classifiers = FakeClassifierFactory()
    classifiers.classify_error = RuntimeError("out of memory")
    env = make_pipeline({"a.png": [FISH], "b.png": [FISH]}, patterns=["Fish"], classifier_factory=classifiers)

    show(env.pipeline, path_a)
    env.pipeline.prefetch([path_b])
    qtbot.waitUntil(lambda: detected(env) == ["a.png", "b.png"])
    qtbot.wait(50)

    assert env.rec.classifier_errors == ["a.png: out of memory"]
    assert env.rec.named == [(path_a, {})]
    # Neither image is highlighted, as a request would still have to name its boxes
    assert env.rec.cached_now == []

    # The request retries the classification the prefetch failed
    classifiers.created[-1].error = None
    show(env.pipeline, path_b)
    qtbot.waitUntil(lambda: len(env.rec.named) == 2)

    assert env.rec.named[1] == (path_b, {FISH.box: TAXONOMY})


def test_a_classified_image_is_reported_only_once_its_boxes_are_named(qtbot, tmp_path, make_pipeline):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    env = make_classifying(make_pipeline, {"a.png": [FISH]})

    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.named) == 1)

    assert [path_a] not in env.rec.cached[:-1]
    assert env.rec.cached_now == [path_a]


def test_an_image_without_boxes_to_name_is_reported_with_its_detections(qtbot, tmp_path, make_pipeline):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    env = make_classifying(make_pipeline, {"a.png": [CRAB]})

    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.named) == 1)

    assert env.classifiers.classified == []
    assert env.rec.cached_now == [path_a]


def test_a_lower_threshold_unreports_the_images_with_boxes_left_to_name(qtbot, tmp_path, make_pipeline):
    path_a, path_b = make_images(tmp_path, ["a.png", "b.png"], IMAGE_SIZE)
    env = make_classifying(make_pipeline, {"a.png": [FISH, FAINT_FISH], "b.png": [FISH, FAINT_FISH]})
    show(env.pipeline, path_a)
    env.pipeline.prefetch([path_b])
    qtbot.waitUntil(lambda: [path_a, path_b] in env.rec.cached)

    # Names the faint fish of the shown image first, then of the prefetched one
    show(env.pipeline, path_a, threshold=0.1)

    assert env.rec.cached_now == []
    qtbot.waitUntil(lambda: env.rec.cached_now == [path_a, path_b])


def test_another_classifier_unreports_the_cached_images_until_they_are_named_again(qtbot, tmp_path, make_pipeline,
                                                                                 models_dir):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    env = make_classifying(make_pipeline, {"a.png": [FISH]})
    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.named) == 1)

    env.pipeline.load_classifier(str(models_dir / "other.onnx"), ["Fish"])
    assert env.rec.cached_now == []

    qtbot.waitUntil(lambda: env.rec.cached_now == [path_a])


def test_unloading_the_classifier_reports_the_detected_images(qtbot, tmp_path, make_pipeline):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    classifiers = FakeClassifierFactory()
    classifiers.classify_error = RuntimeError("out of memory")
    env = make_pipeline({"a.png": [FISH]}, patterns=["Fish"], classifier_factory=classifiers)
    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.named) == 1)
    assert env.rec.cached_now == []

    env.pipeline.load_classifier(None, [])

    assert env.rec.cached_now == [path_a]


def start_batch(env, paths, output_dir, threshold=0.5, class_filter=None, with_classification=False):
    writer = BatchWriter(str(output_dir), CropExportAction(ExportOptions(BATCH_CROP)),
                         with_classification=with_classification, patterns=["Fish"], taxon_confidence=0.0)
    writer.open()
    finished, progress = [], []
    env.pipeline.batch_finished.connect(finished.append)
    env.pipeline.batch_progress.connect(lambda index, total, name: progress.append((index, total, name)))
    env.pipeline.start_batch_run(paths, BatchOptions(threshold, class_filter, False), writer)
    return finished, progress


def row_names(result) -> list[str]:
    return [row.filename for row in result.detections_rows]


def test_batch_run_writes_every_image_in_order(qtbot, tmp_path, make_pipeline):
    paths = make_images(tmp_path, ["a.png", "b.png", "c.png"], IMAGE_SIZE)
    env = make_pipeline({"a.png": [FISH], "c.png": [FISH, CRAB]})

    finished, progress = start_batch(env, paths, tmp_path / "out")
    qtbot.waitUntil(lambda: bool(finished))

    assert row_names(finished[0]) == ["a.png", "b.png", "c.png"]
    assert [row.object_count for row in finished[0].detections_rows] == [1, 0, 2]
    assert progress == [(0, 3, "a.png"), (1, 3, "b.png"), (2, 3, "c.png")]
    assert not finished[0].cancelled


def test_batch_run_names_the_detections_it_keeps(qtbot, tmp_path, make_pipeline):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    env = make_classifying(make_pipeline, {"a.png": [FISH, FAINT_FISH]})

    finished, _ = start_batch(env, [path_a], tmp_path / "out", with_classification=True)
    qtbot.waitUntil(lambda: bool(finished))

    assert env.classifiers.classified == [[FISH.box]]
    assert [row.family for row in finished[0].classification_rows] == ["Pomacentridae"]


def test_batch_run_reuses_cached_detections(qtbot, tmp_path, make_pipeline):
    path_a, path_b = make_images(tmp_path, ["a.png", "b.png"], IMAGE_SIZE)
    env = make_pipeline({"a.png": [FISH]})
    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.completed) == 1)

    finished, _ = start_batch(env, [path_a, path_b], tmp_path / "out")
    qtbot.waitUntil(lambda: bool(finished))

    assert detected(env) == ["a.png", "b.png"]
    assert row_names(finished[0]) == ["a.png", "b.png"]


def test_batch_run_records_a_load_failure(qtbot, tmp_path, make_pipeline):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    env = make_pipeline()

    finished, _ = start_batch(env, [str(broken), path_a], tmp_path / "out")
    qtbot.waitUntil(lambda: bool(finished))

    assert finished[0].failed == ["broken.png"]
    assert row_names(finished[0]) == ["broken.png", "a.png"]


def test_cancel_batch_run_keeps_the_rows_written(qtbot, tmp_path, make_pipeline):
    paths = make_images(tmp_path, ["a.png", "b.png", "c.png"], IMAGE_SIZE)
    env = make_pipeline()
    release = threading.Event()
    env.detectors.created[0].on_detect = lambda name: name == "b.png" and release.wait(5)

    finished, _ = start_batch(env, paths, tmp_path / "out")
    qtbot.waitUntil(lambda: "b.png" in detected(env))
    env.pipeline.cancel_batch_run()
    release.set()

    assert finished[0].cancelled
    assert row_names(finished[0]) == ["a.png"]
    qtbot.wait(50)
    assert len(finished) == 1


def test_interactive_requests_wait_for_the_batch_run(qtbot, tmp_path, make_pipeline):
    path_a, path_b = make_images(tmp_path, ["a.png", "b.png"], IMAGE_SIZE)
    env = make_pipeline()
    release = threading.Event()
    env.detectors.created[0].on_detect = lambda name: name == "a.png" and release.wait(5)

    finished, _ = start_batch(env, [path_a], tmp_path / "out")
    qtbot.waitUntil(lambda: "a.png" in detected(env))
    show(env.pipeline, path_b)
    qtbot.wait(50)
    assert env.rec.shown == []

    release.set()
    qtbot.waitUntil(lambda: env.rec.shown == [path_b])
    assert finished


def test_shutdown_during_batch_run_returns(qtbot, tmp_path, make_pipeline):
    paths = make_images(tmp_path, [f"{i}.png" for i in range(5)], IMAGE_SIZE)
    env = make_pipeline()

    start_batch(env, paths, tmp_path / "out")
    env.pipeline.shutdown()

    assert True  # returning at all is the point, a hang would trip faulthandler_timeout


def test_cancelling_from_the_progress_signal_keeps_the_images_before(qtbot, tmp_path, make_pipeline):
    paths = make_images(tmp_path, ["a.png", "b.png", "c.png"], IMAGE_SIZE)
    env = make_pipeline()
    # a's detection outlasts b's decode, so b is ready the moment a is through inference
    env.detectors.created[0].on_detect = lambda name: name == "a.png" and time.sleep(0.2)
    env.pipeline.batch_progress.connect(lambda index, total, name: index == 1 and env.pipeline.cancel_batch_run())

    finished, _ = start_batch(env, paths, tmp_path / "out")
    qtbot.waitUntil(lambda: bool(finished))

    assert finished[0].cancelled
    assert row_names(finished[0]) == ["a.png"]


def test_hints_beyond_the_image_budget_are_decoded_once(qtbot, tmp_path, make_pipeline, monkeypatch):
    from detectorist import image_loader
    decoded = []
    create = image_loader.ImageObject.create
    monkeypatch.setattr(image_loader.ImageObject, "create",
                        staticmethod(lambda path: decoded.append(os.path.basename(path)) or create(path)))
    path_a, *hints = make_images(tmp_path, ["a.png", "b.png", "c.png", "d.png"], IMAGE_SIZE)
    # One 32x24 image with its display takes 32 * 24 * 6 bytes, so two fit
    env = make_pipeline(image_budget_bytes=2 * 32 * 24 * 6)

    show(env.pipeline, path_a)
    env.pipeline.prefetch(hints)
    qtbot.wait(300)

    # Only the neighbour that fits next to the shown image, once
    assert decoded == ["a.png", "b.png"]


def test_a_new_detector_delivers_the_image_again(qtbot, tmp_path, make_pipeline, models_dir):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    env = make_pipeline()
    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.completed) == 1)

    # The window may have replaced the image by a message meanwhile, e.g. a model that failed to load
    env.pipeline.load_detector(str(models_dir / "b.onnx"))
    qtbot.waitUntil(lambda: len(env.rec.completed) == 2)

    assert env.rec.shown == [path_a, path_a]


def test_batch_run_without_a_detector_fails_instead_of_waiting(qtbot, tmp_path, make_pipeline, models_dir):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    env = make_pipeline()
    env.detectors.error = OSError("boom")
    env.pipeline.load_detector(str(models_dir / "b.onnx"))
    qtbot.waitUntil(lambda: len(env.rec.models) == 2)
    failures = []
    env.pipeline.batch_failed.connect(failures.append)

    finished, _ = start_batch(env, [path_a], tmp_path / "out")
    qtbot.waitUntil(lambda: bool(failures or finished))

    assert failures == ["Model not loaded."]


def test_shutdown_during_batch_run_reports_it_cancelled(qtbot, tmp_path, make_pipeline):
    paths = make_images(tmp_path, ["a.png", "b.png"], IMAGE_SIZE)
    env = make_pipeline()

    finished, _ = start_batch(env, paths, tmp_path / "out")
    env.pipeline.shutdown()

    assert len(finished) == 1 and finished[0].cancelled


def slow_classifier(env, seconds=0.15):
    """Makes the loaded fake classifier take a while per batch of crops, recording the image of each call."""
    classifier = env.classifiers.created[0]
    calls = []
    classify = classifier.classify

    def slow(image, boxes):
        calls.append(os.path.basename(image.image_path))
        time.sleep(seconds)
        return classify(image, boxes)
    classifier.classify = slow
    return calls


CROWD = [Detection((i * 2, 0, 2, 2), 0.9, "Fish") for i in range(24)]  # three batches of 8 crops


def test_the_shown_image_preempts_naming_a_neighbour(qtbot, tmp_path, make_pipeline):
    path_a, path_b, path_c = make_images(tmp_path, ["a.png", "b.png", "c.png"], IMAGE_SIZE)
    env = make_classifying(make_pipeline, {"a.png": [], "b.png": [FISH], "c.png": CROWD})
    qtbot.waitUntil(lambda: bool(env.classifiers.created))
    calls = slow_classifier(env)
    show(env.pipeline, path_a)
    env.pipeline.prefetch([path_c])
    qtbot.waitUntil(lambda: calls == ["c.png"])

    # c stays a neighbour, so only the shown image's need can stop naming it
    show(env.pipeline, path_b)
    env.pipeline.prefetch([path_c])
    qtbot.waitUntil(lambda: len(env.rec.named) == 2)

    assert env.rec.named[1] == (path_b, {FISH.box: TAXONOMY})
    assert calls[:2] == ["c.png", "b.png"]


def test_another_classifier_stops_naming_with_the_old_one(qtbot, tmp_path, make_pipeline, models_dir):
    (path_a,) = make_images(tmp_path, ["a.png"], IMAGE_SIZE)
    env = make_classifying(make_pipeline, {"a.png": CROWD})
    qtbot.waitUntil(lambda: bool(env.classifiers.created))
    calls = slow_classifier(env)
    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(calls) == 1)

    env.pipeline.load_classifier(str(models_dir / "other.onnx"), ["Fish"])
    qtbot.waitUntil(lambda: len(env.rec.named) == 1)

    assert len(calls) == 1


def test_neighbours_alternate_ahead_and_behind_nearest_first():
    paths = [str(i) for i in range(10)]

    assert neighbours(paths, "5", 2) == ["6", "4", "7", "3"]
    assert neighbours(paths, "0", 2) == ["1", "2"]
    assert neighbours(paths, "9", 3) == ["8", "7", "6"]
    assert neighbours(paths, "gone", 2) == []


def test_prefetch_stops_at_what_the_budget_holds(qtbot, tmp_path, make_pipeline, monkeypatch):
    from detectorist import image_loader
    decoded = []
    create = image_loader.ImageObject.create
    monkeypatch.setattr(image_loader.ImageObject, "create",
                        staticmethod(lambda path: decoded.append(os.path.basename(path)) or create(path)))
    path_a, *hints = make_images(tmp_path, ["a.png", "b.png", "c.png", "d.png", "e.png"], IMAGE_SIZE)
    # One 32x24 image with its display takes 32 * 24 * 6 bytes, so the shown image and two neighbours fit
    env = make_pipeline(image_budget_bytes=3 * 32 * 24 * 6)

    show(env.pipeline, path_a)
    qtbot.waitUntil(lambda: len(env.rec.completed) == 1)
    env.pipeline.prefetch(hints)
    qtbot.wait(300)

    assert decoded == ["a.png", "b.png", "c.png"]
