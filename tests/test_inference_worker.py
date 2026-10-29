"""Tests for the InferenceWorker, the inference lane, on a real thread, and the ModelLoader."""

import pytest
from PySide6.QtCore import QObject, QThread, Signal

from detectorist.image_object import ImageObject
from detectorist.inference_worker import InferenceWorker
from detectorist.jobs import CancelToken, ClassifyJob, DetectJob, FileStamp, ModelId
from detectorist.model_loader import ModelLoader
from detectorist.structures import Detection
from tests.fakes import TAXONOMY, FakeClassifier, FakeDetector, make_images

DETECTOR_ID = ModelId("detector.onnx", 1)
CLASSIFIER_ID = ModelId("classifier.onnx", 1)
FISH = Detection((1, 1, 10, 10), 0.9, "Fish")
BOXES = [(i, 0, 5, 5) for i in range(11)]


class Sender(QObject):
    """Calls the worker across threads the way the Pipeline does, through queued signals."""
    set_detector = Signal(object, object)
    set_classifier = Signal(object, object)
    submit = Signal(object)


@pytest.fixture
def worker(qtbot):
    thread = QThread()
    worker = InferenceWorker()
    worker.moveToThread(thread)
    sender = Sender()
    sender.set_detector.connect(worker.set_detector)
    sender.set_classifier.connect(worker.set_classifier)
    sender.submit.connect(worker.run)
    thread.start()
    yield worker, sender
    thread.quit()
    thread.wait()


@pytest.fixture
def image(tmp_path):
    (path,) = make_images(tmp_path, ["a.png"])
    return ImageObject.create(path)


def test_detect_job_reports_detections(qtbot, worker, image):
    lane, sender = worker
    sender.set_detector.emit(FakeDetector({"a.png": [FISH]}), DETECTOR_ID)
    job = DetectJob(image.image_path, image, FileStamp.from_path(image.image_path), DETECTOR_ID, CancelToken())

    with qtbot.waitSignal(lane.detected) as blocker:
        sender.submit.emit(job)

    assert blocker.args[0] is job
    assert blocker.args[1] == [FISH]


def test_detect_job_for_another_model_is_cancelled(qtbot, worker, image):
    lane, sender = worker
    detector = FakeDetector({"a.png": [FISH]})
    sender.set_detector.emit(detector, DETECTOR_ID)
    job = DetectJob(image.image_path, image, FileStamp.from_path(image.image_path), ModelId("old.onnx", 1), CancelToken())

    with qtbot.waitSignal(lane.cancelled):
        sender.submit.emit(job)

    assert detector.detected == []


def test_classify_job_names_every_box_in_chunks(qtbot, worker, image):
    lane, sender = worker
    classifier = FakeClassifier()
    sender.set_classifier.emit(classifier, CLASSIFIER_ID)

    with qtbot.waitSignal(lane.classified) as blocker:
        sender.submit.emit(ClassifyJob(image.image_path, image, BOXES, CLASSIFIER_ID, CancelToken()))

    assert blocker.args[1] == dict.fromkeys(BOXES, TAXONOMY)
    assert [len(boxes) for boxes in classifier.classified] == [8, 3]


class CancellingClassifier(FakeClassifier):
    """Cancels its job's token during the first chunk, as a new request would."""
    token: CancelToken

    def classify(self, image, boxes):
        self.token.cancel()
        return super().classify(image, boxes)


def test_classify_job_cancelled_between_chunks_reports_partial_names(qtbot, worker, image):
    lane, sender = worker
    classifier = CancellingClassifier()
    job = ClassifyJob(image.image_path, image, BOXES, CLASSIFIER_ID, CancelToken())
    classifier.token = job.token
    sender.set_classifier.emit(classifier, CLASSIFIER_ID)

    with qtbot.waitSignal(lane.classified) as blocker:
        sender.submit.emit(job)

    assert list(blocker.args[1]) == BOXES[:8]


def test_failing_classifier_reports_failed(qtbot, worker, image):
    lane, sender = worker
    sender.set_classifier.emit(FakeClassifier(error=RuntimeError("broken")), CLASSIFIER_ID)
    job = ClassifyJob(image.image_path, image, BOXES, CLASSIFIER_ID, CancelToken())

    with qtbot.waitSignal(lane.failed) as blocker:
        sender.submit.emit(job)

    assert blocker.args == [job, "broken"]


def test_model_loader_reports_loaded(qtbot):
    loader = ModelLoader(lambda path: f"model from {path}", ("a.onnx",), DETECTOR_ID)

    with qtbot.waitSignal(loader.loaded) as blocker:
        loader.start()

    assert blocker.args == [DETECTOR_ID, "model from a.onnx"]


def test_model_loader_reports_failed(qtbot):
    def factory(path):
        raise OSError(f"cannot read {path}")
    loader = ModelLoader(factory, ("a.onnx",), DETECTOR_ID)

    with qtbot.waitSignal(loader.failed) as blocker:
        loader.start()

    assert blocker.args == [DETECTOR_ID, "cannot read a.onnx"]
