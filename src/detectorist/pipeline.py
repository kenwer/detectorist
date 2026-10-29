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

from PySide6.QtCore import QObject, QThread, QThreadPool, Signal

from .batch_run import BatchOptions, BatchRun, BatchWriter
from .cache import ImageResults, LoadedImage, LruCache, image_cache_budget, results_cache_budget
from .classifier import Classifier, detections_to_classify
from .detector import Detector
from .image_object import ImageObject
from .image_worker import ImageWorker
from .inference_worker import InferenceWorker
from .jobs import CancelToken, ClassifyJob, DecodeJob, DetectJob, DisplayJob, ModelId, ShowRequest
from .model_loader import ModelLoader
from .utils import physical_memory_bytes

logger = logging.getLogger(__name__)

# What has been reported for the current request, so each is reported once
IMAGE, DETECTIONS, NAMES, ERROR = "image", "detections", "names", "error"


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
    batch_progress = Signal(int, int, str)  # index, total, file name of the image a batch run starts on
    batch_finished = Signal(object)  # BatchResult
    batch_failed = Signal(str)  # error message, e.g. the disk is full

    _decode = Signal(object)  # DecodeJob or DisplayJob, to the ImageWorker
    _infer = Signal(object)  # DetectJob or ClassifyJob, to the InferenceWorker
    _set_detector = Signal(object, object)  # detector, ModelId
    _set_classifier = Signal(object, object)  # classifier, ModelId

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
        self._detector_factory = detector_factory
        self._classifier_factory = classifier_factory
        ram = physical_memory_bytes()
        self._image_budget = image_budget_bytes if image_budget_bytes is not None else image_cache_budget(ram)
        if results_budget_bytes is None:
            results_budget_bytes = results_cache_budget(ram)
        self._images: LruCache[str, LoadedImage] = LruCache(self._image_budget, LoadedImage.nbytes)
        self._results: LruCache[str, ImageResults] = LruCache(results_budget_bytes, ImageResults.nbytes)
        self._entry_bytes: int | None = None  # size of the image displayed last with its display array, the estimate for the others

        self._request: ShowRequest | None = None
        self._hints: list[str] = []  # prefetch paths, nearest first
        self._prefetched: set[str] = set()  # hints decoded since the last prefetch(), not decoded again when evicted
        self._delivered: set[str] = set()  # what was reported for the current request
        self._failed_paths: set[str] = set()  # paths that failed to decode, not retried until shown again
        self._detect_failed: set[str] = set()  # paths the detector failed on, not retried until shown again
        self._last_cached: list[str] = []  # the paths cache_updated reported last

        self._decode_job: DecodeJob | DisplayJob | None = None  # the job the ImageWorker is busy with
        self._inference_job: DetectJob | ClassifyJob | None = None  # the job the InferenceWorker is busy with

        self._detector_id: ModelId | None = None  # the detector the InferenceWorker holds
        self._detector_wanted: ModelId | None = None  # the detector being loaded
        self._classifier_id: ModelId | None = None  # the classifier the InferenceWorker holds
        self._classifier_wanted: ModelId | None = None  # the classifier being loaded
        self._classifier_requested = False  # whether the UI asked for a classifier
        self._classifier_failed = False  # whether the requested classifier failed to load
        self._patterns: tuple[str, ...] = ()  # the detection classes the classifier names
        self._loaders: list[ModelLoader] = []  # kept alive until they report
        self._shut_down = False
        self._batch: BatchRun | None = None  # the batch run under way, which pauses interactive work

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
            self._images.get(request.path)  # refreshes its recency
            self._images.pin(request.path)
            self._failed_paths.discard(request.path)
            self._detect_failed.discard(request.path)
            results = self._results.peek(request.path)
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
        try:
            model_id = ModelId.from_path(model_path)
        except OSError as e:
            self.model_loaded.emit(False, f"Error loading model: {e}", [], False)
            return
        if model_id in (self._detector_id, self._detector_wanted):
            logger.debug("Model already loaded, skipping duplicate request: %s", model_path)
            return
        self._drop_detector()
        self._detector_wanted = model_id
        loader = ModelLoader(self._detector_factory, (model_path,), model_id)
        loader.loaded.connect(lambda loaded_id, detector: self._on_detector_loaded(loaded_id, detector, model_path))
        loader.failed.connect(self._on_detector_failed)
        self._start_loader(loader)

    def unload_detector(self):
        """Drops the detector and its results, e.g. when no model is left."""
        self._drop_detector()
        self._schedule()

    def load_classifier(self, model_path: str | None, patterns: list[str]):
        """
        Loads the classifier at model_path in the background, naming the
        detections whose class matches one of patterns, or unloads it for no
        path. Names of the previous classifier are dropped.
        """
        job = self._inference_job
        if isinstance(job, ClassifyJob) and not self._batch_owns(job):
            job.token.cancel()  # its names belong to the old classifier
        self._set_classifier.emit(None, None)
        self._classifier_id = None
        self._classifier_wanted = None
        self._classifier_failed = False
        self._classifier_requested = bool(model_path)
        self._patterns = tuple(patterns)
        for _, results in self._results.items():
            results.clear_names()
        self._delivered.discard(NAMES)
        if model_path:
            try:
                model_id = ModelId.from_path(model_path)
            except OSError as e:
                self._on_classifier_failed(None, str(e))
                return
            self._classifier_wanted = model_id
            loader = ModelLoader(self._classifier_factory, (model_path, list(patterns)), model_id)
            loader.loaded.connect(self._on_classifier_loaded)
            loader.failed.connect(self._on_classifier_failed)
            self._start_loader(loader)
        self._schedule()

    def start_batch_run(self, paths: list[str], options: BatchOptions, writer: BatchWriter):
        """
        Runs the loaded models over paths and hands each image to writer, in
        order, which the caller has opened. Interactive work pauses until the
        run ends with batch_finished, or batch_failed if writing failed.
        Images already detected are not detected again. Waits for a model
        still loading.
        """
        self._batch = BatchRun(paths, options, writer)
        self._schedule()

    def cancel_batch_run(self):
        """Stops the batch run, keeping what was written, and reports it as cancelled."""
        batch = self._end_batch()
        if batch is None:
            return
        self.batch_finished.emit(batch.writer.close(cancelled=True))
        self._schedule()

    def clear_caches(self):
        """Drops all decoded images and results, and serves the current request from scratch."""
        self._images.clear()
        self._results.clear()
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
        batch = self._end_batch()
        if batch is not None:
            # Reported, so a caller waiting for the run stops waiting
            self.batch_finished.emit(batch.writer.close(cancelled=True))
        if self._loaders:
            QThreadPool.globalInstance().waitForDone()

    def _start_loader(self, loader: ModelLoader):
        self._loaders.append(loader)
        loader.loaded.connect(lambda *_: self._loaders.remove(loader))
        loader.failed.connect(lambda *_: self._loaders.remove(loader))
        loader.start()

    def _drop_detector(self):
        self._set_detector.emit(None, None)
        self._detector_id = None
        self._detector_wanted = None
        self._results.clear()
        self._detect_failed.clear()
        # The image too, as the window may have replaced it by a message, e.g. a model that failed to load
        self._delivered.clear()
        # A batch job is left alone: what it detects with the dropped model is dropped as it arrives
        if self._inference_job is not None and not self._batch_owns(self._inference_job):
            self._inference_job.token.cancel()

    def _on_detector_loaded(self, model_id: ModelId, detector, model_path: str):
        if self._shut_down or model_id != self._detector_wanted:
            return  # superseded by another load
        self._detector_wanted = None
        self._detector_id = model_id
        self._set_detector.emit(detector, model_id)
        self.model_loaded.emit(True, f"Loaded model: {model_path}", sorted(detector.class_names.values()),
                               detector.is_segmentation)
        self._schedule()

    def _on_detector_failed(self, model_id: ModelId, message: str):
        if self._shut_down or model_id != self._detector_wanted:
            return
        self._detector_wanted = None
        self.model_loaded.emit(False, f"Error loading model: {message}", [], False)
        self._schedule()

    def _on_classifier_loaded(self, model_id: ModelId, classifier):
        if self._shut_down or model_id != self._classifier_wanted:
            return
        self._classifier_wanted = None
        self._classifier_id = model_id
        self._set_classifier.emit(classifier, model_id)
        self._schedule()

    def _on_classifier_failed(self, model_id: ModelId | None, message: str):
        if self._shut_down or model_id != self._classifier_wanted:
            return
        self._classifier_wanted = None
        self._classifier_failed = True
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
        """The lanes' jobs, without those of the batch run under way."""
        return [job for job in (self._decode_job, self._inference_job)
                if job is not None and not self._batch_owns(job)]

    def _batch_owns(self, job) -> bool:
        return self._batch is not None and self._batch.owns(job)

    def _end_batch(self) -> BatchRun | None:
        """Forgets the batch run under way and cancels its jobs. Returns it, None if there was none."""
        batch, self._batch = self._batch, None
        if batch is not None:
            batch.token.cancel()
        return batch

    def _wanted_paths(self) -> list[str]:
        """The shown path first, then the prefetch hints."""
        paths = [] if self._request is None else [self._request.path]
        return paths + [path for path in self._fitting_hints() if path not in paths]

    def _fitting_hints(self) -> list[str]:
        """
        The hints that fit in the image budget next to the shown image,
        estimating every image at the size of the one displayed last. None
        before the first image is displayed, as the size is unknown.
        """
        if not self._entry_bytes:
            return []
        return self._hints[:max(self._image_budget // self._entry_bytes - 1, 0)]

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
        # Asked again, as a batch image that needed no inference has just made room for the next decode
        if self._decode_job is None:
            self._decode_job = self._next_decode()
            if self._decode_job is not None:
                self._decode.emit(self._decode_job)
        if self._batch is not None:
            # Written after the next jobs went out, so the next image's inference runs meanwhile
            self._write_batch()
            return
        self._deliver()
        self._update_cached()

    def _write_batch(self):
        """
        Reports the batch images that started and hands those through
        inference to the writer, in the order they happened, then ends a run
        that is done or cannot go on (see BatchRun.write_pending).
        """
        batch = self._batch
        try:
            for progress in batch.write_pending():
                self.batch_progress.emit(*progress)
                if self._batch is not batch:
                    return  # cancelled by a handler
            if batch.failure is not None:
                raise RuntimeError(batch.failure)
            if not batch.done:
                return
            self._end_batch()
            result = batch.writer.close(cancelled=False)
        except Exception as e:
            logger.error("Batch run failed: %s", e, exc_info=not isinstance(e, RuntimeError))
            self._end_batch()
            try:
                batch.writer.close(cancelled=True)
            except Exception:
                logger.exception("Could not close the batch output")
            self.batch_failed.emit(str(e))
            self._schedule()
            return
        self.batch_finished.emit(result)
        self._schedule()

    def _next_batch_inference(self) -> DetectJob | ClassifyJob | None:
        if self._detector_id is None:
            if self._detector_wanted is None:
                self._batch.failure = "Model not loaded."
            return None  # waits for the model still loading
        return self._batch.next_inference(self._results, self._detector_id,
                                          self._classifier_requested and not self._classifier_failed,
                                          self._classifier_id, self._patterns)

    def _preempt_for_shown(self):
        """
        Stops naming another image once the shown one is decoded and needs
        inference, so its boxes do not wait for a crowded neighbour. The job
        stops after its current batch of crops and keeps the names it got. A
        detect job is left to finish, as it cannot be interrupted and is short.
        """
        job = self._inference_job
        request = self._request
        if self._batch is not None or not isinstance(job, ClassifyJob) or request is None or job.path == request.path:
            return
        loaded = self._images.peek(request.path)
        if loaded is None:
            return
        results = self._valid_results(request.path)
        if results is None:
            needs_inference = request.path not in self._detect_failed
        else:
            needs_inference = self._classifier_id is not None and bool(
                results.unnamed_boxes(request.detection_threshold, self._patterns))
        if needs_inference:
            job.token.cancel()

    def _next_decode(self) -> DecodeJob | DisplayJob | None:
        """
        Decodes the wanted images that are not cached and builds the display
        arrays they lack, the shown image first. A hint keeps the exposure it
        was displayed with until it is shown, so toggling the exposure
        rebuilds the display of the shown image only.
        """
        if self._batch is not None:
            return self._batch.next_decode()
        for path in self._wanted_paths():
            if path in self._failed_paths:
                continue
            is_shown = self._request is not None and path == self._request.path
            loaded = self._images.peek(path)
            if loaded is None:
                # A hint evicted for lack of room is not decoded again, which would evict the next one, endlessly
                if not is_shown and path in self._prefetched:
                    continue
                if not is_shown:
                    self._prefetched.add(path)
                return DecodeJob(path, CancelToken())
            if loaded.display is None or (is_shown and loaded.display_exposure != self._exposure()):
                return DisplayJob(loaded.image, self._exposure(), CancelToken())
        return None

    def _next_inference(self) -> DetectJob | ClassifyJob | None:
        if self._batch is not None:
            return self._next_batch_inference()
        if self._detector_id is None:
            return None
        for path in self._wanted_paths():
            loaded = self._images.peek(path)
            if loaded is None:
                continue
            results = self._valid_results(path)
            if results is None:
                if path not in self._detect_failed:
                    return DetectJob(loaded.image, self._detector_id, CancelToken())
                continue
            if self._classifier_id is not None:
                boxes = results.unnamed_boxes(self._threshold(), self._patterns)
                if boxes:
                    return ClassifyJob(loaded.image, boxes, self._classifier_id, CancelToken())
        return None

    def _valid_results(self, path: str) -> ImageResults | None:
        """The results for path, if they belong to the version of the file decoded last."""
        results = self._results.peek(path)
        loaded = self._images.peek(path)
        if results is None or (loaded is not None and results.stamp != loaded.stamp):
            return None
        return results

    def _names_settled(self, results: ImageResults) -> bool:
        """
        Whether the names to report are all there: nothing is left to name,
        failed boxes included, as there is nothing more coming for them.
        """
        if not self._classifier_requested or self._classifier_failed:
            return True
        return self._classifier_id is not None and not results.unnamed_boxes(self._threshold(), self._patterns)

    def _deliver(self):
        """Reports what is ready for the current request and not reported yet, in order."""
        request = self._request
        if request is None:
            return
        loaded = self._images.peek(request.path)
        if IMAGE not in self._delivered:
            if loaded is None or loaded.display_exposure != request.exposure_correction:
                return
            self._delivered.add(IMAGE)
            self.image_loaded.emit(request.path, loaded.image, loaded.display)
            if self._detector_id is None and self._detector_wanted is None and ERROR not in self._delivered:
                self._delivered.add(ERROR)
                self.error.emit(request.path, "Model not loaded.")
        results = self._valid_results(request.path)
        if results is None:
            return
        if DETECTIONS not in self._delivered:
            self._delivered.add(DETECTIONS)
            self.detection_complete.emit(request.path, results.detections, results.detection_time_ms)
        if NAMES not in self._delivered and self._classifier_requested and self._names_settled(results):
            self._delivered.add(NAMES)
            self.classification_complete.emit(request.path, dict(results.names), results.classification_time_ms)

    def _update_cached(self):
        """
        Reports the paths a request would be served for instantly: image and
        detections cached and, with a classifier, every box at the current
        threshold named. A box the classifier failed on counts as unnamed,
        as a request would try it again.
        """
        cached = []
        for path, loaded in self._images.items():
            if loaded.display is None:
                continue
            results = self._results.peek(path)
            if results is None or results.stamp != loaded.stamp:
                continue
            if self._classifier_requested and not self._classifier_failed:
                if self._classifier_id is None:
                    continue  # still loading, so every image has names to come
                wanted = detections_to_classify(results.detections, self._threshold(), self._patterns)
                if any(d.box not in results.names for d in wanted):
                    continue
            cached.append(path)
        if cached != self._last_cached:
            self._last_cached = cached
            self.cache_updated.emit(cached)

    def _on_decoded(self, job: DecodeJob, image: ImageObject):
        self._decode_job = None
        if self._batch_owns(job):
            self._batch.on_decoded(image)
        elif not job.token.cancelled:
            results = self._results.peek(job.path)
            if results is not None and results.stamp != image.stamp:
                self._results.pop(job.path)  # the file changed since
            self._images.put(job.path, LoadedImage(image))
        self._schedule()

    def _on_displayed(self, job: DisplayJob, display):
        self._decode_job = None
        loaded = self._images.peek(job.path)
        if not job.token.cancelled and loaded is not None and loaded.image is job.image:
            loaded.display = display
            loaded.display_exposure = job.exposure_correction
            # Put again, as the cache sized the entry without its display
            self._images.put(job.path, loaded)
            self._entry_bytes = loaded.nbytes()
        self._schedule()

    def _on_decode_failed(self, job: DecodeJob | DisplayJob, message: str):
        self._decode_job = None
        if self._batch_owns(job):
            self._batch.on_decoded(None)
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
        if not job.token.cancelled and job.model_id == self._detector_id:
            self._results.put(job.path, ImageResults(job.image.stamp, detections, detection_time_ms))
        self._schedule()

    def _on_classified(self, job: ClassifyJob, names: dict, classification_time_ms: float):
        self._inference_job = None
        results = self._results.peek(job.path)
        # Names of a cancelled job are kept: they are valid for the classifier that gave them
        if job.model_id == self._classifier_id and results is not None:
            results.names.update(names)
            results.classification_time_ms += classification_time_ms
        self._schedule()

    def _on_inference_failed(self, job: DetectJob | ClassifyJob, message: str):
        self._inference_job = None
        by_batch = self._batch_owns(job)
        is_shown = not by_batch and self._request is not None and job.path == self._request.path
        if isinstance(job, DetectJob):
            if by_batch:
                self._batch.on_detect_failed()
            elif job.model_id == self._detector_id:
                self._detect_failed.add(job.path)
                if is_shown:
                    self.error.emit(job.path, f"Error processing image: {message}")
        else:
            results = self._results.peek(job.path)
            if job.model_id == self._classifier_id and results is not None:
                results.failed_boxes.update(job.boxes)
                if is_shown:
                    self.classifier_error.emit(f"{os.path.basename(job.path)}: {message}")
        self._schedule()

    def _on_inference_cancelled(self, job: DetectJob | ClassifyJob):
        self._inference_job = None
        self._schedule()
