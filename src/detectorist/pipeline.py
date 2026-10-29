"""
The Pipeline: runs the decode and inference jobs of browsing and of an
Export on two lanes, an ImageWorker and an InferenceWorker, each on a thread
of its own and each given one job at a time, so a newer request never queues
up behind stale work in a lane's event queue. It lives on the GUI thread and
decides nothing about images: Browsing decides what the shown image and its
neighbours need, an ExportRun what an export needs. The Pipeline sends each
idle lane the next job of whoever is in charge, an export while one runs,
and hands every outcome back to whoever made the job.

Outcomes come back as queued signals, so the caches and queues are only
touched on the GUI thread and need no locks.
"""
import logging

from PySide6.QtCore import QObject, QThread, Signal

from .browsing import (
    Browsing,
    CacheUpdated,
    ClassificationComplete,
    ClassifierError,
    DetectionComplete,
    ImageError,
    ImageLoaded,
    Report,
)
from .cache import ImageStore, image_cache_budget, results_cache_budget
from .classifier import Classifier
from .detector import Detector
from .export_run import DetectionFilter, ExportRun, ExportWriter
from .image_object import ImageObject
from .image_worker import ImageWorker
from .inference_worker import InferenceWorker
from .jobs import ClassifyJob, DecodeJob, DetectJob, DisplayJob, ShowRequest
from .model_loader import ModelLoader
from .model_state import Models
from .utils import physical_memory_bytes

logger = logging.getLogger(__name__)


def neighbours(paths: list[str], current: str, per_side: int) -> list[str]:
    """
    Up to per_side paths on each side of current in paths, nearest first and
    the next one ahead before the one behind (+1, -1, +2, -2, ...). The
    Pipeline prefetches as many of them as its image budget holds, so cutting
    the list short keeps the window symmetric.
    """
    try:
        row = paths.index(current)
    except ValueError:
        return []
    window = []
    for distance in range(1, per_side + 1):
        window += [paths[i] for i in (row + distance, row - distance) if 0 <= i < len(paths)]
    return window


class Pipeline(QObject):
    """
    Loads the models, runs the jobs of Browsing and of an Export, and
    reports to the window. The signals to the UI keep the payloads the
    window already handled.
    """
    model_loaded = Signal(bool, str, list, bool)  # success, message, sorted class names, is segmentation model
    image_loaded = Signal(str, object, object)  # image_path, ImageObject, display array
    detection_complete = Signal(str, list, float)  # image_path, unfiltered detections, detection_time_ms
    # image_path, {box: Taxonomy}, classification_time_ms. The dict goes as object: as a QVariantMap it would lose its tuple keys.
    classification_complete = Signal(str, object, float)
    error = Signal(str, str)  # image_path, error_message
    classifier_error = Signal(str)  # error_message
    cache_updated = Signal(list)  # cached paths a request would be served for without further work
    export_progress = Signal(int, int, str)  # index, total, file name of the image an export starts on
    export_finished = Signal(object)  # ExportResult
    export_failed = Signal(str)  # error message, e.g. the disk is full

    _decode = Signal(object)  # DecodeJob or DisplayJob, to the ImageWorker
    _infer = Signal(object)  # DetectJob or ClassifyJob, to the InferenceWorker
    _set_detector = Signal(object, object)  # detector, FileStamp of its model file
    _set_classifier = Signal(object, object)  # classifier, FileStamp of its model file

    def __init__(self, detector_factory=Detector, classifier_factory=Classifier,
                 image_budget_bytes: int | None = None, results_budget_bytes: int | None = None,
                 parent: QObject | None = None):
        """
        Args:
            detector_factory: Called with a model path to build a detector.
            classifier_factory: Called with a model path and the classes it
                names to build a classifier.
            image_budget_bytes: Budget of the cache of decoded images.
                Defaults to a share of the RAM (see image_cache_budget).
            results_budget_bytes: Budget of the cache of inference results.
                Defaults to a share of the RAM (see results_cache_budget).
        """
        super().__init__(parent)
        ram = physical_memory_bytes()
        # Shared by Browsing and every export, so neither infers what the other already did
        self._store = ImageStore(image_budget_bytes if image_budget_bytes is not None else image_cache_budget(ram),
                                 results_budget_bytes if results_budget_bytes is not None else results_cache_budget(ram))
        self._browsing = Browsing(self._store)
        self._export: ExportRun | None = None  # the export under way, which pauses browsing

        self._decode_job: DecodeJob | DisplayJob | None = None  # the job the ImageWorker is busy with
        self._inference_job: DetectJob | ClassifyJob | None = None  # the job the InferenceWorker is busy with

        self._detector = ModelLoader(detector_factory, self)
        self._detector.loaded.connect(self._on_detector_loaded)
        self._detector.failed.connect(self._on_detector_failed)
        self._classifier = ModelLoader(classifier_factory, self)
        self._classifier.loaded.connect(self._on_classifier_loaded)
        self._classifier.failed.connect(self._on_classifier_failed)
        self._patterns: tuple[str, ...] = ()  # the detection classes the classifier names
        self._shut_down = False

        self._image_thread = QThread()
        self._image_worker = ImageWorker()
        self._image_worker.moveToThread(self._image_thread)
        self._decode.connect(self._image_worker.run)
        self._image_worker.decoded.connect(self._on_decoded)
        self._image_worker.displayed.connect(self._on_displayed)
        self._image_worker.failed.connect(self._on_decode_failed)
        self._image_worker.cancelled.connect(self._on_decode_cancelled)

        self._inference_thread = QThread()
        self._inference = InferenceWorker()
        self._inference.moveToThread(self._inference_thread)
        self._infer.connect(self._inference.run)
        self._set_detector.connect(self._inference.set_detector)
        self._set_classifier.connect(self._inference.set_classifier)
        self._inference.detected.connect(self._on_detected)
        self._inference.classified.connect(self._on_classified)
        self._inference.failed.connect(self._on_inference_failed)
        self._inference.cancelled.connect(self._on_inference_cancelled)

        self._image_thread.start()
        self._inference_thread.start()

    def show(self, request: ShowRequest):
        """Makes request the one to serve (see Browsing.show)."""
        self._browsing.show(request)
        self._cancel_unwanted()
        self._schedule()

    def prefetch(self, paths: list[str]):
        """Sets the images to prepare ahead of time while idle, nearest first (see Browsing.prefetch)."""
        self._browsing.prefetch(paths)
        self._cancel_unwanted()
        self._schedule()

    def load_detector(self, model_path: str):
        """
        Loads the detector at model_path in the background. The previous one
        is dropped first, so two detectors are never held at once, and so
        are the results it produced. The same model twice is loaded once.
        """
        if self._detector.needs_load(model_path):
            self._drop_detector()
            self._detector.load(model_path)
        else:
            logger.debug("Model already loaded, skipping duplicate request: %s", model_path)

    def unload_detector(self):
        """Drops the detector and its results, e.g. when no model is left."""
        self._drop_detector()
        self._schedule()

    def load_classifier(self, model_path: str, patterns: list[str]):
        """
        Loads the classifier at model_path in the background, naming the
        detections whose class matches one of patterns. Names of the previous
        classifier are dropped.
        """
        self._drop_classifier()
        self._patterns = tuple(patterns)
        self._classifier.load(model_path, list(patterns))
        self._schedule()

    def unload_classifier(self):
        """Drops the classifier and the names it gave."""
        self._drop_classifier()
        self._schedule()

    def start_export(self, paths: list[str], detection_filter: DetectionFilter, writer: ExportWriter):
        """
        Runs the loaded models over paths and hands each image to writer, in
        order, which the caller has opened, with the detections
        detection_filter keeps. Only those are named. Browsing pauses until
        the run ends with export_finished, or export_failed if writing
        failed. Images already detected are not detected again. Waits for a
        model still loading.
        """
        self._export = ExportRun(paths, detection_filter, writer, self._store)
        self._schedule()

    def cancel_export(self):
        """Stops the export, keeping what was written, and reports it as cancelled."""
        run = self._end_export()
        if run is None:
            return
        self.export_finished.emit(run.writer.close(cancelled=True))
        self._schedule()

    def clear_caches(self):
        """Drops all decoded images and results, and serves the current request from scratch."""
        self._browsing.clear()
        for job in self._browsing_jobs():
            job.token.cancel()
        self._schedule()

    def shutdown(self):
        """Stops both lanes, waiting for the jobs they are running, and for model loads under way."""
        self._shut_down = True
        for job in (self._decode_job, self._inference_job):
            if job is not None:
                job.token.cancel()
        for thread in (self._image_thread, self._inference_thread):
            thread.quit()
            thread.wait()
        run = self._end_export()
        if run is not None:
            # Reported, so a caller waiting for the run stops waiting
            self.export_finished.emit(run.writer.close(cancelled=True))
        self._detector.shutdown()
        self._classifier.shutdown()

    def _drop_detector(self):
        self._set_detector.emit(None, None)
        self._detector.unload()
        self._browsing.on_detector_dropped()
        # An export job is left alone: what it detects with the dropped model is dropped as it arrives
        if self._inference_job is not None and not self._export_owns(self._inference_job):
            self._inference_job.token.cancel()

    def _drop_classifier(self):
        job = self._inference_job
        if isinstance(job, ClassifyJob) and not self._export_owns(job):
            job.token.cancel()  # its names belong to the old classifier
        self._set_classifier.emit(None, None)
        self._classifier.unload()
        self._patterns = ()
        self._browsing.on_classifier_dropped()

    def _on_detector_loaded(self, detector, model_path: str):
        self._set_detector.emit(detector, self._detector.model_id)
        self.model_loaded.emit(True, f"Loaded model: {model_path}", sorted(detector.class_names.values()),
                               detector.is_segmentation)
        self._schedule()

    def _on_detector_failed(self, message: str):
        self.model_loaded.emit(False, f"Error loading model: {message}", [], False)
        self._schedule()

    def _on_classifier_loaded(self, classifier, _model_path: str):
        self._set_classifier.emit(classifier, self._classifier.model_id)
        self._schedule()

    def _on_classifier_failed(self, message: str):
        self.classifier_error.emit(f"Error loading classifier: {message}")
        self._schedule()

    def _models(self) -> Models:
        return Models(self._detector.model_id, self._detector.state, self._classifier.model_id,
                      self._classifier.state, self._patterns)

    def _cancel_unwanted(self):
        """Cancels the lanes' jobs for paths neither shown nor prefetched anymore."""
        for job in self._browsing_jobs():
            if not self._browsing.is_wanted(job):
                job.token.cancel()

    def _browsing_jobs(self) -> list[DecodeJob | DisplayJob | DetectJob | ClassifyJob]:
        """The lanes' jobs, without those of the export under way."""
        return [job for job in (self._decode_job, self._inference_job)
                if job is not None and not self._export_owns(job)]

    def _export_owns(self, job) -> bool:
        return self._export is not None and self._export.owns(job)

    def _owner(self, job) -> Browsing | ExportRun:
        """Who made job, so its outcome goes back there."""
        return self._export if self._export_owns(job) else self._browsing

    def _end_export(self) -> ExportRun | None:
        """Forgets the export under way and cancels its jobs. Returns it, None if there was none."""
        run, self._export = self._export, None
        if run is not None:
            run.token.cancel()
        return run

    def _schedule(self):
        """Gives each idle lane its most wanted job, then reports what is ready."""
        if self._shut_down:
            return
        models = self._models()
        if self._export is None and self._browsing.should_preempt(self._inference_job, models):
            self._inference_job.token.cancel()
        if self._decode_job is None:
            self._decode_job = self._next_decode(models)
            if self._decode_job is not None:
                self._decode.emit(self._decode_job)
        if self._inference_job is None:
            self._inference_job = self._next_inference(models)
            if self._inference_job is not None:
                self._infer.emit(self._inference_job)
        # Asked again, as an export image that needed no inference has just made room for the next decode
        if self._decode_job is None:
            self._decode_job = self._next_decode(models)
            if self._decode_job is not None:
                self._decode.emit(self._decode_job)
        if self._export is not None:
            # Written after the next jobs went out, so the next image's inference runs meanwhile
            self._write_export()
            return
        for report in self._browsing.reports(models):
            self._report(report)

    def _next_decode(self, models: Models) -> DecodeJob | DisplayJob | None:
        if self._export is not None:
            return self._export.next_decode()
        return self._browsing.next_decode(models)

    def _next_inference(self, models: Models) -> DetectJob | ClassifyJob | None:
        if self._export is None:
            return self._browsing.next_inference(models)
        if models.detector_id is None:
            if not models.detector_state.is_loaded_or_loading:
                self._export.failure = "Model not loaded."
            return None  # waits for the model still loading
        return self._export.next_inference(models)

    def _report(self, report: Report):
        match report:
            case ImageLoaded():
                self.image_loaded.emit(report.path, report.image, report.display)
            case DetectionComplete():
                self.detection_complete.emit(report.path, report.detections, report.detection_time_ms)
            case ClassificationComplete():
                self.classification_complete.emit(report.path, report.names, report.classification_time_ms)
            case ImageError():
                self.error.emit(report.path, report.message)
            case ClassifierError():
                self.classifier_error.emit(report.message)
            case CacheUpdated():
                self.cache_updated.emit(report.paths)

    def _write_export(self):
        """
        Reports the export images that started and hands those through
        inference to the writer, in the order they happened, then ends a run
        that is done or cannot go on (see ExportRun.write_pending).
        """
        run = self._export
        try:
            for progress in run.write_pending():
                self.export_progress.emit(*progress)
                if self._export is not run:
                    return  # cancelled by a handler
            if run.failure is not None:
                raise RuntimeError(run.failure)
            if not run.done:
                return
            self._end_export()
            result = run.writer.close(cancelled=False)
        except Exception as e:
            logger.error("Export failed: %s", e, exc_info=not isinstance(e, RuntimeError))
            self._end_export()
            try:
                run.writer.close(cancelled=True)
            except Exception:
                logger.exception("Could not close the export output")
            self.export_failed.emit(str(e))
            self._schedule()
            return
        self.export_finished.emit(result)
        self._schedule()

    def _on_decoded(self, job: DecodeJob, image: ImageObject):
        self._decode_job = None
        if self._export_owns(job):
            self._export.on_decoded(image)
        else:
            self._browsing.on_decoded(job, image)
        self._schedule()

    def _on_displayed(self, job: DisplayJob, display):
        self._decode_job = None
        self._browsing.on_displayed(job, display)  # an export builds no display arrays
        self._schedule()

    def _on_decode_failed(self, job: DecodeJob | DisplayJob, message: str):
        self._decode_job = None
        if self._export_owns(job):
            self._export.on_decoded(None)
        else:
            self._browsing.on_decode_failed(job, message)
        self._schedule()

    def _on_decode_cancelled(self, job: DecodeJob | DisplayJob):
        self._decode_job = None
        self._schedule()

    def _on_detected(self, job: DetectJob, detections: list, detection_time_ms: float):
        self._inference_job = None
        self._owner(job).on_detected(job, detections, detection_time_ms, self._models())
        self._schedule()

    def _on_classified(self, job: ClassifyJob, names: dict, classification_time_ms: float):
        self._inference_job = None
        self._owner(job).on_classified(job, names, classification_time_ms, self._models())
        self._schedule()

    def _on_inference_failed(self, job: DetectJob | ClassifyJob, message: str):
        self._inference_job = None
        models = self._models()
        if isinstance(job, DetectJob):
            if self._export_owns(job):
                self._export.on_detect_failed()
            else:
                self._browsing.on_detect_failed(job, message, models)
        elif self._export_owns(job):
            self._export.on_classify_failed(job, models)
        else:
            self._browsing.on_classify_failed(job, message, models)
        self._schedule()

    def _on_inference_cancelled(self, job: DetectJob | ClassifyJob):
        self._inference_job = None
        self._schedule()
