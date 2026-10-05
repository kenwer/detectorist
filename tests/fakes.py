"""Test doubles and small helpers shared across the suite."""

import os

from PIL import Image


class FakeDetector:
    """Stands in for Detector, returning canned detections keyed by image basename.

    detected lists the basenames detect() ran on, in call order. on_detect, if
    given, is called with the basename before the detections are returned, so
    a test can act while a batch run is in flight.
    """

    def __init__(self, detections_by_file=None, class_names=None, model_path="fake.onnx", on_detect=None):
        self.detections_by_file = detections_by_file if detections_by_file is not None else {}
        self.class_names = class_names if class_names is not None else {1: "Fish"}
        self.model_path = model_path
        self.on_detect = on_detect
        self.detected: list[str] = []

    def detect(self, image):
        name = os.path.basename(image.image_path)
        self.detected.append(name)
        if self.on_detect is not None:
            self.on_detect(name)
        return list(self.detections_by_file.get(name, []))


class FakeDetectorFactory:
    """Callable that replaces the Detector class wherever one is injected.

    Every detector it creates shares detections_by_file, so a test can fill it
    in after the window exists. created keeps the detectors in creation order:
    the worker's first, then one per batch run. Setting error makes the next
    call raise it, which is how a model that fails to load is simulated.
    """

    def __init__(self, detections_by_file=None, class_names=None):
        self.detections_by_file = detections_by_file if detections_by_file is not None else {}
        self.class_names = class_names if class_names is not None else {1: "Fish"}
        self.error: Exception | None = None
        self.on_detect = None
        self.created: list[FakeDetector] = []

    def __call__(self, model_path: str) -> FakeDetector:
        if self.error is not None:
            raise self.error
        detector = FakeDetector(self.detections_by_file, self.class_names, model_path, self.on_detect)
        self.created.append(detector)
        return detector


def make_images(dir_path, names, size=(64, 48)) -> list[str]:
    """Write one small solid-colour image per name and return the full paths."""
    paths = []
    for name in names:
        path = str(dir_path / name)
        Image.new("RGB", size, color=(120, 130, 140)).save(path)
        paths.append(path)
    return paths
