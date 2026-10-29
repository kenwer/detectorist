"""
The Pipeline: the one place that decides what gets decoded, detected and
classified, and when. It lives on the GUI thread and only keeps books. The
work runs on two lanes, an ImageWorker and an InferenceWorker, each on a
thread of its own and each given one job at a time, so a newer request never
queues up behind stale work in a lane's event queue.

The UI describes what it wants to see with a ShowRequest, and the Pipeline
works out what is missing from its caches. Results come back as queued
signals, so the caches and queues are only touched on the GUI thread and
need no locks.
"""
import logging
import os
from dataclasses import dataclass
from enum import Enum, auto

from PySide6.QtCore import QObject, QThread, Signal

from .cache import ImageStore, image_cache_budget, results_cache_budget
from .classifier import Classifier
from .detector import Detector
from .export_run import DetectionFilter, ExportRun, ExportWriter
from .image_object import ImageObject
from .image_worker import ImageWorker
from .inference_worker import InferenceWorker
from .jobs import CancelToken, ClassifyJob, DecodeJob, DetectJob, DisplayJob, ShowRequest
from .model_loader import ModelLoader
from .model_state import Models, ModelState
from .structures import Box
from .utils import physical_memory_bytes

logger = logging.getLogger(__name__)

# What has been reported for the current request, so each is reported once
IMAGE, DETECTIONS, NAMES, ERROR = "image", "detections", "names", "error"


class Work(Enum):
    """A step a path still needs, see Needs."""
    DECODE = auto()
    DISPLAY = auto()  # build the display array
    DETECT = auto()
    CLASSIFY = auto()  # name Needs.boxes
    WAIT = auto()  # results come once a model is loaded or the image is decoded


@dataclass(frozen=True)
class Needs:
    """What a path still needs from each lane. None means nothing more is coming: done, failed or no model."""
    image: Work | None  # DECODE or DISPLAY
    inference: Work | None  # DETECT, CLASSIFY or WAIT
    boxes: tuple[Box, ...] = ()  # the boxes to name, for CLASSIFY

    @property
    def settled(self) -> bool:
        return self.image is None and self.inference is None


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
    Schedules decode and inference jobs for the shown image and its
    prefetch neighbours, keeps their results and reports those of the shown
    image. The signals to the UI keep the payloads the window already handled.
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
        self._store = ImageStore(image_budget_bytes if image_budget_bytes is not None else image_cache_budget(ram),
                                 results_budget_bytes if results_budget_bytes is not None else results_cache_budget(ram))

        self._request: ShowRequest | None = None
        self._hints: list[str] = []  # prefetch paths, nearest first
        self._prefetched: set[str] = set()  # hints decoded since the last prefetch(), not decoded again when evicted
        self._delivered: set[str] = set()  # what was reported for the current request
        self._failed_paths: set[str] = set()  # paths that failed to decode, not retried until shown again
        self._detect_failed: set[str] = set()  # paths the detector failed on, not retried until shown again
        self._last_cached: list[str] = []  # the paths cache_updated reported last

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
        self._export: ExportRun | None = None  # the export under way, which pauses interactive work

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
        """
        Makes request the one to serve. Another path starts over: its earlier
        failures are retried and everything about it is reported again.
        Another threshold reports the names again, another exposure the image.
        """
        previous, self._request = self._request, request
        if previous is None or previous.path != request.path:
            self._store.pin(request.path)
            self._failed_paths.discard(request.path)
            self._detect_failed.discard(request.path)
            results = self._store.results(request.path)
            if results is not None:
                results.failed_boxes.clear()
            self._delivered.clear()
        else:
            if previous.detection_threshold != request.detection_threshold:
                self._delivered.discard(NAMES)
            if previous.exposure_correction != request.exposure_correction:
                self._delivered.discard(IMAGE)
        self._cancel_unwanted()
        self._schedule()

    def prefetch(self, paths: list[str]):
        """
        Sets the images to decode, detect and classify ahead of time while
        idle, nearest first. Only as many as the image budget holds next to
        the shown image are prefetched, so a longer list costs nothing.
        """
        self._hints = list(paths)
        self._prefetched.clear()
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
        detection_filter keeps. Only those are named. Interactive work pauses
        until the run ends with export_finished, or export_failed if writing
        failed. Images already detected are not detected again. Waits for a
        model still loading.
        """
        self._export = ExportRun(paths, detection_filter, writer)
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
        self._store.clear()
        self._failed_paths.clear()
        self._detect_failed.clear()
        self._delivered.clear()
        for job in self._interactive_jobs():
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
        self._store.clear_results()
        self._detect_failed.clear()
        # The image too, as the window may have replaced it by a message, e.g. a model that failed to load
        self._delivered.clear()
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
        self._store.clear_names()
        self._delivered.discard(NAMES)

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

    def _cancel_unwanted(self):
        """Cancels the lanes' jobs for paths neither shown nor prefetched anymore."""
        wanted = set(self._fitting_hints())
        if self._request is not None:
            wanted.add(self._request.path)
        for job in self._interactive_jobs():
            if job.path not in wanted:
                job.token.cancel()

    def _interactive_jobs(self) -> list[DecodeJob | DisplayJob | DetectJob | ClassifyJob]:
        """The lanes' jobs, without those of the export under way."""
        return [job for job in (self._decode_job, self._inference_job)
                if job is not None and not self._export_owns(job)]

    def _export_owns(self, job) -> bool:
        return self._export is not None and self._export.owns(job)

    def _end_export(self) -> ExportRun | None:
        """Forgets the export under way and cancels its jobs. Returns it, None if there was none."""
        run, self._export = self._export, None
        if run is not None:
            run.token.cancel()
        return run

    def _wanted_paths(self) -> list[str]:
        """The shown path first, then the prefetch hints."""
        paths = [] if self._request is None else [self._request.path]
        return paths + [path for path in self._fitting_hints() if path not in paths]

    def _fitting_hints(self) -> list[str]:
        """
        The hints that fit in the image budget next to the shown image. None
        before the first image is displayed (see ImageStore.room).
        """
        return self._hints[:self._store.room()]

    def _models(self) -> Models:
        return Models(self._detector.model_id, self._detector.state, self._classifier.model_id,
                      self._classifier.state, self._patterns)

    def _threshold(self) -> float:
        return self._request.detection_threshold if self._request is not None else 0.0

    def _exposure(self) -> bool:
        return self._request.exposure_correction if self._request is not None else False

    def _schedule(self):
        """Gives each idle lane its most wanted job, then reports what is ready."""
        if self._shut_down:
            return
        self._preempt_for_shown()
        if self._decode_job is None:
            self._decode_job = self._next_decode()
            if self._decode_job is not None:
                self._decode.emit(self._decode_job)
        if self._inference_job is None:
            self._inference_job = self._next_inference()
            if self._inference_job is not None:
                self._infer.emit(self._inference_job)
        # Asked again, as an export image that needed no inference has just made room for the next decode
        if self._decode_job is None:
            self._decode_job = self._next_decode()
            if self._decode_job is not None:
                self._decode.emit(self._decode_job)
        if self._export is not None:
            # Written after the next jobs went out, so the next image's inference runs meanwhile
            self._write_export()
            return
        self._deliver()
        self._update_cached()

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

    def _next_export_inference(self) -> DetectJob | ClassifyJob | None:
        models = self._models()
        if models.detector_id is None:
            if not models.detector_state.is_loaded_or_loading:
                self._export.failure = "Model not loaded."
            return None  # waits for the model still loading
        return self._export.next_inference(self._store, models)

    def _preempt_for_shown(self):
        """
        Stops naming another image once the shown one is decoded and needs
        inference, so its boxes do not wait for a crowded neighbour. The job
        stops after its current batch of crops and keeps the names it got. A
        detect job is left to finish, as it cannot be interrupted and is short.
        """
        job = self._inference_job
        request = self._request
        if self._export is not None or not isinstance(job, ClassifyJob) or request is None or job.path == request.path:
            return
        if self._needs(request.path, self._models()).inference in (Work.DETECT, Work.CLASSIFY):
            job.token.cancel()

    def _next_decode(self) -> DecodeJob | DisplayJob | None:
        """Decodes the wanted images and builds their display arrays, the shown image first."""
        if self._export is not None:
            return self._export.next_decode()
        models = self._models()
        for path in self._wanted_paths():
            is_shown = self._request is not None and path == self._request.path
            work = self._needs(path, models, as_shown=is_shown).image
            if work is Work.DECODE:
                if not is_shown:
                    # A hint evicted for lack of room is not decoded again, which would evict the next one, endlessly
                    if path in self._prefetched:
                        continue
                    self._prefetched.add(path)
                return DecodeJob(path, CancelToken())
            if work is Work.DISPLAY:
                return DisplayJob(self._store.image(path).image, self._exposure(), CancelToken())
        return None

    def _next_inference(self) -> DetectJob | ClassifyJob | None:
        """Detects and names the wanted images, the shown image first."""
        if self._export is not None:
            return self._next_export_inference()
        models = self._models()
        for path in self._wanted_paths():
            needs = self._needs(path, models)
            if needs.inference is Work.DETECT:
                return DetectJob(self._store.image(path).image, models.detector_id, CancelToken())
            if needs.inference is Work.CLASSIFY:
                return ClassifyJob(self._store.image(path).image, list(needs.boxes), models.classifier_id,
                                   CancelToken())
        return None

    def _needs(self, path: str, models: Models, as_shown: bool = False, retry_failures: bool = False) -> Needs:
        """
        What path still needs, the one answer behind scheduling, preemption
        and what is reported. as_shown also asks for a display at the current
        exposure, as a hint keeps the exposure it was displayed with until it
        is shown, so toggling the exposure rebuilds the display of the shown
        image only. retry_failures counts what failed as still needed, as
        showing a path again tries it again.
        """
        loaded = self._store.image(path)
        if path in self._failed_paths and not retry_failures:
            image = None
        elif loaded is None:
            image = Work.DECODE
        elif loaded.display is None or (as_shown and loaded.display_exposure != self._exposure()):
            image = Work.DISPLAY
        else:
            image = None

        results = self._store.results(path)
        if models.detector_id is None:
            return Needs(image, Work.WAIT if models.detector_state.is_loaded_or_loading else None)
        if loaded is None:
            # Without a decode coming, the image failed to load
            return Needs(image, Work.WAIT if image is Work.DECODE else None)
        if results is None:
            detect = retry_failures or path not in self._detect_failed
            return Needs(image, Work.DETECT if detect else None)
        if models.classifier_id is not None:
            boxes = results.unnamed_boxes(self._threshold(), models.patterns, include_failed=retry_failures)
            if boxes:
                return Needs(image, Work.CLASSIFY, tuple(boxes))
        return Needs(image, Work.WAIT if models.classifier_state is ModelState.LOADING else None)

    def _deliver(self):
        """Reports what is ready for the current request and not reported yet, in order."""
        request = self._request
        if request is None:
            return
        models = self._models()
        loaded = self._store.image(request.path)
        if IMAGE not in self._delivered:
            if loaded is None or loaded.display_exposure != request.exposure_correction:
                return
            self._delivered.add(IMAGE)
            self.image_loaded.emit(request.path, loaded.image, loaded.display)
            if not models.detector_state.is_loaded_or_loading and ERROR not in self._delivered:
                self._delivered.add(ERROR)
                self.error.emit(request.path, "Model not loaded.")
        results = self._store.results(request.path)
        if results is None:
            return
        if DETECTIONS not in self._delivered:
            self._delivered.add(DETECTIONS)
            self.detection_complete.emit(request.path, results.detections, results.detection_time_ms)
        # Reported once no more names come. A classifier that failed to load still reports, without names, as the
        # window waits while one is selected.
        if (NAMES not in self._delivered and models.classifier_state is not ModelState.NONE
                and self._needs(request.path, models).inference is None):
            self._delivered.add(NAMES)
            self.classification_complete.emit(request.path, dict(results.names), results.classification_time_ms)

    def _update_cached(self):
        """
        Reports the paths a request would be served for without inference:
        image and detections cached and, with a classifier, every box at the
        current threshold named. A box the classifier failed on counts as
        unnamed, as a request would try it again. A display built with the
        other exposure counts, as the window highlights what is analyzed.
        """
        models = self._models()
        cached = [path for path in self._store.paths()
                  if self._store.results(path) is not None and self._needs(path, models, retry_failures=True).settled]
        if cached != self._last_cached:
            self._last_cached = cached
            self.cache_updated.emit(cached)

    def _on_decoded(self, job: DecodeJob, image: ImageObject):
        self._decode_job = None
        if self._export_owns(job):
            self._export.on_decoded(image)
        elif not job.token.cancelled:
            self._store.put_image(job.path, image)
        self._schedule()

    def _on_displayed(self, job: DisplayJob, display):
        self._decode_job = None
        if not job.token.cancelled:
            self._store.put_display(job.image, display, job.exposure_correction)
        self._schedule()

    def _on_decode_failed(self, job: DecodeJob | DisplayJob, message: str):
        self._decode_job = None
        if self._export_owns(job):
            self._export.on_decoded(None)
        elif not job.token.cancelled:
            self._failed_paths.add(job.path)
            if self._request is not None and job.path == self._request.path:
                self.error.emit(job.path, message)
        self._schedule()

    def _on_decode_cancelled(self, job: DecodeJob | DisplayJob):
        self._decode_job = None
        self._schedule()

    def _on_detected(self, job: DetectJob, detections: list, detection_time_ms: float):
        self._inference_job = None
        # A job for a replaced model is stale. One for an older version of the file is stored with its image's
        # stamp, which tells it apart from the current version.
        if not job.token.cancelled and job.model_id == self._detector.model_id:
            self._store.put_detections(job.image, detections, detection_time_ms)
        self._schedule()

    def _on_classified(self, job: ClassifyJob, names: dict, classification_time_ms: float):
        self._inference_job = None
        results = self._store.results(job.path)
        # Names of a cancelled job are kept: they are valid for the classifier that gave them
        if job.model_id == self._classifier.model_id and results is not None:
            results.names.update(names)
            results.classification_time_ms += classification_time_ms
        self._schedule()

    def _on_inference_failed(self, job: DetectJob | ClassifyJob, message: str):
        self._inference_job = None
        by_export = self._export_owns(job)
        is_shown = not by_export and self._request is not None and job.path == self._request.path
        if isinstance(job, DetectJob):
            if by_export:
                self._export.on_detect_failed()
            elif job.model_id == self._detector.model_id:
                self._detect_failed.add(job.path)
                if is_shown:
                    self.error.emit(job.path, f"Error processing image: {message}")
        else:
            results = self._store.results(job.path)
            if job.model_id == self._classifier.model_id and results is not None:
                results.failed_boxes.update(job.boxes)
                if is_shown:
                    self.classifier_error.emit(f"{os.path.basename(job.path)}: {message}")
        self._schedule()

    def _on_inference_cancelled(self, job: DetectJob | ClassifyJob):
        self._inference_job = None
        self._schedule()
