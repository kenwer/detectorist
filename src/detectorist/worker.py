import time
from threading import Lock

from PySide6.QtCore import QMetaObject, QObject, Qt, Signal, Slot

from .detector import Detector
from .image_object import ImageObject


class DetectionWorker(QObject):
    """
    A worker class that performs image loading and object detection in a background thread.
    It is designed to handle a high volume of requests by only processing the most recent one.
    """
    model_loaded = Signal(bool, str)  # success, message
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

    @Slot(str)
    def load_model(self, model_path: str):
        """Loads a new detection model."""
        try:
            self.detector = Detector(model_path)
            print(f"Worker loaded model: {model_path}")
            self.model_loaded.emit(True, f"Loaded model: {model_path}")
        except Exception as e:
            self.detector = None
            print(f"Worker error loading model: {e}")
            self.model_loaded.emit(False, f"Error loading model: {e}")

    @Slot(str, float, float, bool)
    def process_image(self, image_path: str, confidence_threshold: float, nms_threshold: float, exposure_correction: bool):
        """
        Receives a request to process an image. Instead of processing immediately,
        it updates the latest request parameters and ensures the processing loop is running.
        """
        with self._lock:
            self._latest_request_params = (image_path, confidence_threshold, nms_threshold, exposure_correction)
            self._new_request_pending = True
            if not self._is_processing:
                self._is_processing = True
                QMetaObject.invokeMethod(self, "_process_loop", Qt.ConnectionType.QueuedConnection)

    @Slot()
    def _process_loop(self):
        """
        The main processing loop that runs in the worker thread.
        It continuously checks for and processes the most recent request.
        """
        while True:
            with self._lock:
                if not self._new_request_pending:
                    self._is_processing = False
                    return  # No new requests, exit the loop

                # Get the latest request and reset the pending flag
                params = self._latest_request_params
                self._new_request_pending = False
                assert params is not None  # Guaranteed by process_image setting both together

            # Start of processing for the latest request
            image_path, confidence_threshold, nms_threshold, exposure_correction = params

            if not self.detector:
                self.error.emit(image_path, "Model not loaded.")
                continue  # Continue to the next iteration of the loop

            try:
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
                results = self.detector.detect(image, confidence_threshold=confidence_threshold, nms_threshold=nms_threshold)
                end_time = time.perf_counter()
                detection_time_ms = (end_time - start_time) * 1000

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
