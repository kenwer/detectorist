"""
Tests for Browsing, which decides what the shown image and its neighbours
still need and what is ready to report. Plain calls stand in for the
Pipeline: each test hands back the outcome of the job Browsing asked for.
"""
import numpy as np

from detectorist.browsing import (
    Browsing,
    CacheUpdated,
    ClassificationComplete,
    ClassifierError,
    DetectionComplete,
    ImageError,
    ImageLoaded,
)
from detectorist.cache import ImageStore
from detectorist.jobs import ClassifyJob, DecodeJob, DetectJob, DisplayJob, ShowRequest
from detectorist.model_state import Models, ModelState
from detectorist.structures import Detection
from detectorist.utils import FileStamp
from tests.fakes import TAXONOMY, FakeImage

DETECTOR = FileStamp("detector.onnx", 1, 0)
CLASSIFIER = FileStamp("classifier.onnx", 1, 0)
FISH = Detection((0, 0, 10, 10), 0.9, "Fish")
DISPLAY = np.zeros(10, dtype=np.uint8)


def models(detector=ModelState.LOADED, classifier=ModelState.NONE) -> Models:
    return Models(DETECTOR if detector is ModelState.LOADED else None, detector,
                  CLASSIFIER if classifier is ModelState.LOADED else None, classifier, ("Fish",))


def make_browsing(path="a.png") -> tuple[Browsing, FakeImage]:
    browsing = Browsing(ImageStore(10_000, 10_000))
    browsing.show(ShowRequest(path, exposure_correction=False, detection_threshold=0.5))
    return browsing, FakeImage(path)


def decode_and_display(browsing: Browsing, image: FakeImage, m: Models) -> None:
    decode = browsing.next_decode(m)
    browsing.on_decoded(decode, image)
    display = browsing.next_decode(m)
    browsing.on_displayed(display, DISPLAY)


def test_the_shown_image_is_decoded_then_displayed_then_reported():
    browsing, image = make_browsing()
    m = models()

    decode = browsing.next_decode(m)
    assert isinstance(decode, DecodeJob) and decode.path == "a.png"
    browsing.on_decoded(decode, image)
    display = browsing.next_decode(m)
    assert isinstance(display, DisplayJob) and display.image is image
    browsing.on_displayed(display, DISPLAY)

    reports = browsing.reports(m)
    assert [type(r) for r in reports] == [ImageLoaded]
    assert browsing.next_decode(m) is None


def test_nothing_is_detected_while_the_detector_loads():
    browsing, image = make_browsing()
    decode_and_display(browsing, image, models(detector=ModelState.LOADING))

    assert browsing.next_inference(models(detector=ModelState.LOADING)) is None
    job = browsing.next_inference(models())
    assert isinstance(job, DetectJob) and job.model_id == DETECTOR


def test_detections_of_a_replaced_detector_are_dropped():
    browsing, image = make_browsing()
    decode_and_display(browsing, image, models())
    job = browsing.next_inference(models())

    replaced = Models(FileStamp("other.onnx", 1, 0), ModelState.LOADED, None, ModelState.NONE, ())
    browsing.on_detected(job, [FISH], 1.0, replaced)

    assert isinstance(browsing.next_inference(models()), DetectJob)


def test_names_are_reported_once_the_classifier_named_every_box():
    browsing, image = make_browsing()
    m = models(classifier=ModelState.LOADED)
    decode_and_display(browsing, image, m)
    browsing.on_detected(browsing.next_inference(m), [FISH], 1.0, m)

    classify = browsing.next_inference(m)
    assert isinstance(classify, ClassifyJob) and classify.boxes == [FISH.box]
    assert [type(r) for r in browsing.reports(m)] == [ImageLoaded, DetectionComplete]
    browsing.on_classified(classify, {FISH.box: TAXONOMY}, 2.0, m)

    reports = browsing.reports(m)
    assert [type(r) for r in reports] == [ClassificationComplete, CacheUpdated]
    assert reports[0].names == {FISH.box: TAXONOMY}
    assert reports[1].paths == ["a.png"]


def test_a_classifier_that_failed_to_load_reports_the_image_without_names():
    browsing, image = make_browsing()
    m = models(classifier=ModelState.FAILED)
    decode_and_display(browsing, image, m)
    browsing.on_detected(browsing.next_inference(m), [FISH], 1.0, m)

    reports = browsing.reports(m)

    assert [type(r) for r in reports] == [ImageLoaded, DetectionComplete, ClassificationComplete, CacheUpdated]
    assert reports[2].names == {}


def test_a_failed_box_counts_as_named_for_the_shown_image_but_not_for_the_cache():
    browsing, image = make_browsing()
    m = models(classifier=ModelState.LOADED)
    decode_and_display(browsing, image, m)
    browsing.on_detected(browsing.next_inference(m), [FISH], 1.0, m)

    browsing.on_classify_failed(browsing.next_inference(m), "out of memory", m)

    reports = browsing.reports(m)
    assert [type(r) for r in reports] == [ClassifierError, ImageLoaded, DetectionComplete, ClassificationComplete]
    assert browsing.next_inference(m) is None


def test_a_decode_failure_of_the_shown_image_is_reported_once_and_not_retried():
    browsing, _ = make_browsing()
    m = models()
    browsing.on_decode_failed(browsing.next_decode(m), "corrupt")

    assert browsing.reports(m) == [ImageError("a.png", "corrupt")]
    assert browsing.reports(m) == []
    assert browsing.next_decode(m) is None


def test_the_shown_image_preempts_naming_a_neighbour():
    browsing, image = make_browsing()
    m = models(classifier=ModelState.LOADED)
    neighbour = ClassifyJob(FakeImage("b.png"), [FISH.box], CLASSIFIER, None)

    assert not browsing.should_preempt(neighbour, m)  # the shown image is not decoded yet
    decode_and_display(browsing, image, m)
    assert browsing.should_preempt(neighbour, m)
