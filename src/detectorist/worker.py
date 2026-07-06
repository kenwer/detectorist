import time
from threading import Lock

from PySide6.QtCore import QMetaObject, QObject, Qt, Signal, Slot

from .detector import Detector
from .image_cache import CacheEntry, ImageCache
from .image_object import ImageObject


class DetectionWorker(QObject):
    """
    A worker class that performs image loading and object detection in a background thread.
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

    def __init__(self):
        super().__init__()
        self.detector = None
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

    @Slot(str)
    def load_model(self, model_path: str):
        """Loads a new detection model. Cached results belong to the previous model, so the cache is dropped."""
        self._cache.clear()
        try:
            self.detector = Detector.create(model_path)
            print(f"Worker loaded model: {model_path}")
            class_names = sorted(self.detector.class_names.values())
            self.model_loaded.emit(True, f"Loaded model: {model_path}", class_names)
        except Exception as e:
            self.detector = None
            print(f"Worker error loading model: {e}")
            self.model_loaded.emit(False, f"Error loading model: {e}", [])

    @Slot()
    def clear_cache(self):
        """Drops all cached images, e.g. after a new folder was loaded and files may have changed."""
        self._cache.clear()

    @Slot(str, bool, list)
    def process_image(self, image_path: str, exposure_correction: bool, prefetch_paths: list):
        """
        Receives a request to process an image. Instead of processing immediately,
        it updates the latest request parameters and ensures the processing loop is running.
        prefetch_paths are images to decode and detect ahead of time while idle.
        """
        with self._lock:
            self._latest_request_params = (image_path, exposure_correction)
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
                if self._new_request_pending:
                    params = self._latest_request_params
                    self._new_request_pending = False
                    assert params is not None  # Guaranteed by process_image setting both together
                elif self.detector is not None and self._prefetch_paths:
                    params = None
                    prefetch_path = self._prefetch_paths.pop(0)
                else:
                    self._is_processing = False
                    return  # No new requests, exit the loop

            if prefetch_path is not None:
                self._prefetch(prefetch_path)
                continue

            # Start of processing for the latest request
            image_path, exposure_correction = params

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
                self._cache.put(image_path, CacheEntry(image, results, detection_time_ms))

                # After detection, check one last time. If a new request came in,
                # discard these results and start over.
                if self._new_request_pending:
                    continue

                self.detection_complete.emit(image_path, results, detection_time_ms)

            except Exception as e:
                # Only emit error if it's for the request we just tried to process
                with self._lock:
                    if not self._new_request_pending:
                        self.error.emit(image_path, f"Error processing image: {e}")

    def _prefetch(self, image_path: str):
        """
        Loads and detects one image into the cache. Emits no signals: a later
        real request for this path presents the results (or surfaces errors)
        through the normal path.
        """
        if self._cache.get(image_path) is not None:
            # Already cached; get() promotes it to MRU so it survives upcoming evictions.
            return
        try:
            image = ImageObject.create(image_path)
            if self._abandon_prefetch(image_path):
                return
            start_time = time.perf_counter()
            results = self.detector.detect(image)
            detection_time_ms = (time.perf_counter() - start_time) * 1000
            self._cache.put(image_path, CacheEntry(image, results, detection_time_ms))
        except Exception as e:
            print(f"Prefetch failed for {image_path}: {e}")

    def _abandon_prefetch(self, image_path: str) -> bool:
        """
        A user request that arrived mid-prefetch wins, unless it asks for the
        image just decoded; then finishing the prefetch is the fastest way to
        serve it (the request is answered from the cache right after).
        """
        with self._lock:
            return (self._new_request_pending
                    and self._latest_request_params[0] != image_path)
