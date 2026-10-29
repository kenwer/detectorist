"""Test doubles and small helpers shared across the suite."""

import os

import numpy as np
from PIL import Image

from detectorist.structures import RankedName, Taxonomy
from detectorist.utils import FileStamp


class FakeDetector:
    """Stands in for Detector, returning canned detections keyed by image basename.

    detected lists the basenames detect() ran on, in call order. on_detect, if
    given, is called with the basename before the detections are returned, so
    a test can act while an export is in flight.
    """

    def __init__(self, detections_by_file=None, class_names=None, model_path="fake.onnx", on_detect=None,
                 is_segmentation=False):
        self.detections_by_file = detections_by_file if detections_by_file is not None else {}
        self.class_names = class_names if class_names is not None else {1: "Fish"}
        self.model_path = model_path
        self.is_segmentation = is_segmentation
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

    Every detector it creates shares detections_by_file and, unless
    class_names_by_model names its file, class_names, so a test can fill it
    in after the window exists. created keeps the detectors in creation order:
    the worker's first, then one per export. Setting error makes the next
    call raise it, which is how a model that fails to load is simulated.
    """

    def __init__(self, detections_by_file=None, class_names=None):
        self.detections_by_file = detections_by_file if detections_by_file is not None else {}
        self.class_names = class_names if class_names is not None else {1: "Fish"}
        # Class names of the models that differ from class_names, keyed by model file name
        self.class_names_by_model: dict[str, dict] = {}
        self.error: Exception | None = None
        self.on_detect = None
        self.is_segmentation = False
        self.created: list[FakeDetector] = []

    def __call__(self, model_path: str) -> FakeDetector:
        if self.error is not None:
            raise self.error
        class_names = self.class_names_by_model.get(os.path.basename(model_path), self.class_names)
        detector = FakeDetector(self.detections_by_file, class_names, model_path, self.on_detect, self.is_segmentation)
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


TAXONOMY = Taxonomy(
    RankedName("Pomacentridae", 0.99),
    RankedName("Amphiprion", 0.97),
    RankedName("Amphiprion_ocellaris", 0.44),
)


class FakeClassifier:
    """Stands in for Classifier, giving every box the same taxonomy, or
    the one taxonomy_by_box holds for it.

    classified lists the boxes of each classify() call, in call order. Setting
    error makes the next call raise it.
    """

    def __init__(self, taxonomy=TAXONOMY, model_path="fake-classifier.onnx", error=None, patterns=("*",),
                 taxonomy_by_box=None):
        self.taxonomy = taxonomy
        self.taxonomy_by_box = taxonomy_by_box or {}
        self.model_path = model_path
        self.error = error
        self.patterns = tuple(patterns)
        self.classified: list[list] = []

    def classify(self, image, boxes):
        if self.error is not None:
            raise self.error
        self.classified.append(list(boxes))
        return [self.taxonomy_by_box.get(box, self.taxonomy) for box in boxes]


class FakeClassifierFactory:
    """Callable that replaces the Classifier class wherever one is injected.

    created keeps the classifiers in creation order. Setting error makes the
    next call raise it, which is how a classifier that fails to load is
    simulated. classify_error is handed to every classifier created after it
    was set. taxonomy_by_box is handed to them likewise (see FakeClassifier).
    """

    def __init__(self, taxonomy=TAXONOMY):
        self.taxonomy = taxonomy
        self.taxonomy_by_box: dict = {}
        self.error: Exception | None = None
        self.classify_error: Exception | None = None
        self.created: list[FakeClassifier] = []

    def __call__(self, model_path: str, patterns=("*",)) -> FakeClassifier:
        if self.error is not None:
            raise self.error
        classifier = FakeClassifier(self.taxonomy, model_path, self.classify_error, patterns, self.taxonomy_by_box)
        self.created.append(classifier)
        return classifier

    @property
    def classified(self) -> list[list]:
        """The boxes of every classify() call across all created classifiers."""
        return [boxes for classifier in self.created for boxes in classifier.classified]


class FakeImage:
    """Stands in for an ImageObject, with the fields the ImageStore and Browsing read."""

    def __init__(self, path: str, mtime_ns: int = 1, nbytes: int = 100):
        self.image_path = path
        self.stamp = FileStamp(path, mtime_ns, 2)
        self.image_data = np.zeros(nbytes, dtype=np.uint8)
