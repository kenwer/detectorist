"""
The inference lane: one thread holding both the detector and the classifier.
All inference runs on the CPU and an ONNX Runtime session uses every core,
so running one inference at a time is what keeps each one fast. That rule
follows from there being one worker, not from a gate somewhere else.
"""
import logging
import time

from PySide6.QtCore import QObject, Signal, Slot

from .classifier import CROPS_PER_RUN
from .jobs import ClassifyJob, DetectJob, ModelId

logger = logging.getLogger(__name__)


class InferenceWorker(QObject):
    """
    Runs one DetectJob or ClassifyJob at a time and answers each with
    exactly one of detected, classified, failed or cancelled. A job for a
    model other than the one loaded is cancelled, so a job sent just before
    a model switch cannot run with the new model.
    """
    detected = Signal(object, list, float)  # job, detections, detection_time_ms
    # job, {box: Taxonomy}, classification_time_ms. The dict goes as object: as a QVariantMap it would lose its tuple keys.
    classified = Signal(object, object, float)
    failed = Signal(object, str)  # job, message
    cancelled = Signal(object)  # job

    def __init__(self):
        super().__init__()
        self._detector = None
        self._detector_id: ModelId | None = None
        self._classifier = None
        self._classifier_id: ModelId | None = None

    @Slot(object, object)
    def set_detector(self, detector, model_id: ModelId | None):
        """Replaces the detector. None unloads it, which frees the model."""
        self._detector, self._detector_id = detector, model_id

    @Slot(object, object)
    def set_classifier(self, classifier, model_id: ModelId | None):
        """Replaces the classifier. None unloads it, which frees the model."""
        self._classifier, self._classifier_id = classifier, model_id

    @Slot(object)
    def run(self, job: DetectJob | ClassifyJob):
        if isinstance(job, DetectJob):
            self._detect(job)
        else:
            self._classify(job)

    def _detect(self, job: DetectJob):
        if job.token.cancelled or self._detector is None or job.model_id != self._detector_id:
            self.cancelled.emit(job)
            return
        try:
            start_time = time.perf_counter()
            detections = self._detector.detect(job.image)
            self.detected.emit(job, detections, (time.perf_counter() - start_time) * 1000)
        except Exception as e:
            logger.exception("Could not detect objects in %s", job.path)
            self.failed.emit(job, str(e))

    def _classify(self, job: ClassifyJob):
        """
        Names the boxes in chunks, checking the token in between. A job
        cancelled midway reports the names it got, as they are valid.
        """
        if job.token.cancelled or self._classifier is None or job.model_id != self._classifier_id:
            self.cancelled.emit(job)
            return
        names = {}
        start_time = time.perf_counter()
        try:
            for start in range(0, len(job.boxes), CROPS_PER_RUN):
                if job.token.cancelled:
                    break
                chunk = job.boxes[start:start + CROPS_PER_RUN]
                names.update(zip(chunk, self._classifier.classify(job.image, chunk), strict=True))
        except Exception as e:
            logger.exception("Could not classify the detections of %s", job.path)
            self.failed.emit(job, str(e))
            return
        self.classified.emit(job, names, (time.perf_counter() - start_time) * 1000)
