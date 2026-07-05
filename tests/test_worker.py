"""Tests for the DetectionWorker's cache and prefetch scheduling.

The worker normally lives on a QThread; here it stays on the test thread and
a QCoreApplication pumps the queued _process_loop invocations, so the tests
run headless (no display, no real model). The detector is faked by assigning
worker.detector directly, bypassing load_model.
"""

import os

from PIL import Image
from PySide6.QtCore import QCoreApplication

from detectorist.worker import DetectionWorker


class FakeDetector:
    """Records which images detect() ran on."""

    def __init__(self):
        self.detected_paths = []
        self.class_names = {0: "Fish"}

    def detect(self, image):
        self.detected_paths.append(os.path.basename(image.image_path))
        return [((1, 1, 5, 5), 0.9, "Fish")]


def make_images(dir_path, names, size=(32, 24)):
    paths = []
    for name in names:
        path = str(dir_path / name)
        Image.new("RGB", size, color=(120, 130, 140)).save(path)
        paths.append(path)
    return paths


def make_worker():
    QCoreApplication.instance() or QCoreApplication([])
    worker = DetectionWorker()
    worker.detector = FakeDetector()
    completed = []
    worker.detection_complete.connect(lambda path, results, ms: completed.append((path, results)))
    return worker, completed


def pump(condition, max_iterations=100):
    """Process pending Qt events until condition() holds."""
    app = QCoreApplication.instance()
    for _ in range(max_iterations):
        app.processEvents()
        if condition():
            return True
    return False


def test_repeated_request_is_served_from_cache(tmp_path):
    (path_a,) = make_images(tmp_path, ["a.png"])
    worker, completed = make_worker()

    worker.process_image(path_a, False, [])
    assert pump(lambda: len(completed) == 1)

    worker.process_image(path_a, False, [])
    assert pump(lambda: len(completed) == 2)

    assert worker.detector.detected_paths == ["a.png"]
    assert completed[0] == completed[1]


def test_prefetch_hint_fills_cache_while_idle(tmp_path):
    path_a, path_b = make_images(tmp_path, ["a.png", "b.png"])
    worker, completed = make_worker()

    worker.process_image(path_a, False, [path_b])
    assert pump(lambda: worker.detector.detected_paths == ["a.png", "b.png"])
    assert len(completed) == 1  # prefetching emits no signals

    worker.process_image(path_b, False, [])
    assert pump(lambda: len(completed) == 2)
    assert worker.detector.detected_paths == ["a.png", "b.png"]  # no re-detection
    assert completed[1][0] == path_b


def test_clear_cache_forces_reprocessing(tmp_path):
    (path_a,) = make_images(tmp_path, ["a.png"])
    worker, completed = make_worker()

    worker.process_image(path_a, False, [])
    assert pump(lambda: len(completed) == 1)

    worker.clear_cache()
    worker.process_image(path_a, False, [])
    assert pump(lambda: len(completed) == 2)
    assert worker.detector.detected_paths == ["a.png", "a.png"]


def test_prefetch_failure_is_swallowed(tmp_path):
    (path_a,) = make_images(tmp_path, ["a.png"])
    missing = str(tmp_path / "missing.png")
    worker, completed = make_worker()
    errors = []
    worker.error.connect(lambda path, message: errors.append(path))

    worker.process_image(path_a, False, [missing])
    assert pump(lambda: len(completed) == 1)
    QCoreApplication.instance().processEvents()

    assert errors == []
    assert worker.detector.detected_paths == ["a.png"]
