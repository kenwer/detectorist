import logging
import os
import time
from collections.abc import Callable, Sequence
from threading import Lock

from PySide6.QtCore import QMetaObject, QObject, Qt, Signal, Slot

from .classifier import Classifier, detections_to_classify
from .detector import Detector
from .image_cache import CacheEntry, ImageCache
from .image_object import ImageObject

logger = logging.getLogger(__name__)


class DetectionWorker(QObject):
    """
    A worker class that performs image loading, object detection and classification in a background thread.
    It is designed to handle a high volume of requests by only processing the most recent one.

    Recently viewed images and their detection results are kept in a small LRU
    cache, and while idle the worker prefetches the images the caller hints at
    (typically the adjacent images in both directions), so stepping through
    images is served from the cache without decoding or inference.

    process_image is intended to be called directly from other threads (it only
    touches lock-protected state); the heavy work always runs on this object's
    thread via the queued _process_loop invocation.
    """
    model_loaded = Signal(bool, str, list)  # success, message, sorted class names
    image_loaded = Signal(str, object)  # image_path, image_object
    detection_complete = Signal(str, list, float)  # image_path, results, detection_time_ms
    error = Signal(str, str)  # image_path, error_message
    cache_updated = Signal(list)  # paths currently held in the cache
    # image_path, {box: Taxonomy}, classification_time_ms. Sent after detection_complete.
    # The dict goes as object: as a QVariantMap it would lose its tuple keys.
    classification_complete = Signal(str, object, float)
    classifier_error = Signal(str)  # error_message

    def __init__(self, detector_factory: Callable[[str], Detector] = Detector,
                 classifier_factory: Callable[[str, Sequence[str]], Classifier] = Classifier):
        """
        Args:
            detector_factory: Called with a model path to build the detector
                on each model load. Defaults to the Detector class.
            classifier_factory: Called with a model path and the classes it
                names to build the classifier. Defaults to the Classifier class.
        """
        super().__init__()
        self._detector_factory = detector_factory
        self._classifier_factory = classifier_factory
        self.detector = None
        self.classifier = None
        self._lock = Lock()
        self._latest_request_params = None
        self._new_request_pending = False
        self._is_processing = False
        # Both are shared with calling threads and protected by _lock. The
        # cache itself is only touched on the worker thread.
        self._prefetch_paths: list[str] = []
        self._cache = ImageCache()

    @Slot()
    def unload_model(self):
        """Unloads the current detection model."""
        self.detector = None
        self._cache.clear()
        self._notify_cache_updated()

    @Slot(str)
    def load_model(self, model_path: str):
        """Loads a new detection model. Cached results belong to the previous model, so the cache is dropped."""
        if self.detector is not None and self.detector.model_path == model_path:
            logger.debug("Model already loaded, skipping duplicate request: %s", model_path)
            return
        self._cache.clear()
        self._notify_cache_updated()
        try:
            self.detector = self._detector_factory(model_path)
            logger.info("Worker loaded model: %s", model_path)
            class_names = sorted(self.detector.class_names.values())
            self.model_loaded.emit(True, f"Loaded model: {model_path}", class_names)
        except Exception as e:
            self.detector = None
            logger.error("Worker error loading model: %s", e)
            self.model_loaded.emit(False, f"Error loading model: {e}", [])

    @Slot(str, list)
    def set_classifier(self, model_path: str, patterns: list):
        """
        Loads the classifier at model_path, naming detections whose class
        matches one of patterns, or unloads it for an empty path. Cached names
        belong to the previous classifier, so they are dropped. Naming the
        shown image again is up to the caller, via classify_image.
        """
        self.classifier = None
        self._cache.clear_taxonomy()
        if model_path:
            try:
                self.classifier = self._classifier_factory(model_path, patterns)
                logger.info("Worker loaded classifier: %s", model_path)
            except Exception as e:
                logger.error("Worker error loading classifier: %s", e)
                self.classifier_error.emit(f"Error loading classifier: {e}")

    @Slot(str, float)
    def classify_image(self, image_path: str, min_score: float):
        """
        Names the boxes of a cached image down to min_score, e.g. after the
        confidence was lowered, and reports them. Only the boxes without names
        are classified. An image no longer cached is ignored: the next request
        for it classifies down to the confidence it carries.
        """
        entry = self._cache.get(image_path)
        if entry is not None:
            self._classify_and_report(image_path, entry, min_score)

    def _classify_missing(self, entry: CacheEntry, min_score: float):
        """
        Names the detections picked by detections_to_classify whose boxes the
        entry has no names for yet. Does nothing without a classifier. Raises
        if the classifier fails, leaving the entry's names as they were.
        """
        if self.classifier is None:
            return
        boxes = [d.box for d in detections_to_classify(entry.results, min_score, self.classifier.patterns)
                 if d.box not in entry.taxonomy]
        if boxes:
            start_time = time.perf_counter()
            taxonomies = self.classifier.classify(entry.image, boxes)
            entry.classification_time_ms += (time.perf_counter() - start_time) * 1000
            entry.taxonomy.update(zip(boxes, taxonomies, strict=True))

    def _classify_and_report(self, image_path: str, entry: CacheEntry, min_score: float):
        """
        Names the boxes the entry misses (see _classify_missing) and reports
        all of the entry's names. A failure is reported too, and leaves the
        detections shown as they are.
        """
        if self.classifier is None:
            return
        try:
            self._classify_missing(entry, min_score)
        except Exception as e:
            logger.exception("Could not classify the detections of %s", image_path)
            self.classifier_error.emit(f"{os.path.basename(image_path)}: {e}")
        self.classification_complete.emit(image_path, dict(entry.taxonomy), entry.classification_time_ms)

    @Slot()
    def clear_cache(self):
        """Drops all cached images, e.g. after a new folder was loaded and files may have changed."""
        self._cache.clear()
        self._notify_cache_updated()

    def _notify_cache_updated(self):
        """Reports the current set of cached paths, e.g. so the image list can highlight them."""
        self.cache_updated.emit(self._cache.paths())

    @Slot(str, bool, list, float)
    def process_image(self, image_path: str, exposure_correction: bool, prefetch_paths: list, min_score: float):
        """
        Receives a request to process an image. Instead of processing immediately,
        it updates the latest request parameters and ensures the processing loop is running.
        prefetch_paths are images to decode and detect ahead of time while idle.
        Detections scoring below min_score are not classified, here and in the prefetch.
        """
        with self._lock:
            self._latest_request_params = (image_path, exposure_correction, min_score)
            self._prefetch_paths = list(prefetch_paths)
            self._new_request_pending = True
            if not self._is_processing:
                self._is_processing = True
                QMetaObject.invokeMethod(self, "_process_loop", Qt.ConnectionType.QueuedConnection)

    @Slot()
    def _process_loop(self):
        """
        The main processing loop that runs in the worker thread. It serves the
        most recent request first and uses idle time for prefetching.
        """
        while True:
            prefetch_path = None
            with self._lock:
                params = self._latest_request_params
                if self._new_request_pending:
                    self._new_request_pending = False
                elif self.detector is not None and self._prefetch_paths:
                    prefetch_path = self._prefetch_paths.pop(0)
                else:
                    self._is_processing = False
                    return  # No new requests, exit the loop

            assert params is not None
            image_path, exposure_correction, min_score = params

            if prefetch_path is not None:
                self._prefetch(prefetch_path, min_score)
                continue

            # Start of processing for the latest request
            if not self.detector:
                self.error.emit(image_path, "Model not loaded.")
                continue  # Continue to the next iteration of the loop

            try:
                entry = self._cache.get(image_path)
                if entry is not None:
                    # The exposure flag is per request, not part of the cached state
                    entry.image.exposure_correction = exposure_correction
                    self.image_loaded.emit(image_path, entry.image)
                    self.detection_complete.emit(image_path, entry.results, entry.detection_time_ms)
                    self._classify_and_report(image_path, entry, min_score)
                    continue

                # Check for new requests before doing expensive work
                if self._new_request_pending:
                    continue

                # Load image
                image = ImageObject.create(image_path)

                if self._new_request_pending:
                    continue

                if not image:
                    self.error.emit(image_path, "Could not load image.")
                    continue

                image.exposure_correction = exposure_correction
                self.image_loaded.emit(image_path, image)

                if self._new_request_pending:
                    continue

                # Perform detection
                start_time = time.perf_counter()
                results = self.detector.detect(image)
                end_time = time.perf_counter()
                detection_time_ms = (end_time - start_time) * 1000

                # Cache even if the result turns out stale below; the work is done
                # and the user may come back to this image.
                entry = CacheEntry(image, results, detection_time_ms)
                self._cache.put(image_path, entry)
                self._notify_cache_updated()

                # After detection, check one last time. If a new request came in,
                # discard these results and start over.
                if self._new_request_pending:
                    continue

                self.detection_complete.emit(image_path, results, detection_time_ms)
                self._classify_and_report(image_path, entry, min_score)

            except Exception as e:
                # Only emit error if it's for the request we just tried to process
                with self._lock:
                    if not self._new_request_pending:
                        self.error.emit(image_path, f"Error processing image: {e}")

    def _prefetch(self, image_path: str, min_score: float):
        """
        Loads, detects and classifies one image into the cache. A cached one
        only gets the names it misses. Emits no signals: a later real request
        for this path presents the results (or surfaces errors) through the
        normal path, and retries a failed classification.
        """
        # get() also promotes a cached entry to MRU so it survives upcoming evictions
        entry = self._cache.get(image_path)
        try:
            if entry is None:
                image = ImageObject.create(image_path)
                if self._abandon_prefetch(image_path):
                    return
                start_time = time.perf_counter()
                results = self.detector.detect(image)
                detection_time_ms = (time.perf_counter() - start_time) * 1000
                entry = CacheEntry(image, results, detection_time_ms)
                self._cache.put(image_path, entry)
                self._notify_cache_updated()
            if not self._abandon_prefetch(image_path):
                self._classify_missing(entry, min_score)
        except Exception as e:
            logger.warning("Prefetch failed for %s: %s", image_path, e)

    def _abandon_prefetch(self, image_path: str) -> bool:
        """
        A user request that arrived mid-prefetch wins, unless it asks for the
        image just decoded; then finishing the prefetch is the fastest way to
        serve it (the request is answered from the cache right after).
        """
        with self._lock:
            return (self._new_request_pending
                    and self._latest_request_params[0] != image_path)
