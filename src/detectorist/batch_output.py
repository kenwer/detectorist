"""The files a Batch Run writes besides the action's images.

The rows and columns of the detections and classification CSV files, and
the names of the CSV and settings files. Knows nothing about detecting or
classifying.
"""

import csv
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, NamedTuple

from .structures import Detection
from .utils import long_path, strip_model_ext

CSV_ENCODING = "utf-8-sig"
DETECTIONS_CSV_HEADER = ["Filename", "Highest confidence score", "Class name", "Number of detected objects", "cropped"]
CLASSIFICATION_CSV_HEADER = ["Filename", "Detection", "Class name", "Confidence score", "x", "y", "w", "h",
                             "Family", "Family score", "Genus", "Genus score", "Species", "Species score",
                             "Classifier model"]

class DetectionsRow(NamedTuple):
    """One detections.csv row, its fields in the order of DETECTIONS_CSV_HEADER."""
    filename: str
    highest_score: float
    class_name: str
    object_count: int
    cropped: str  # "yes", "no", or "n/a" for an image that failed


class ClassificationRow(NamedTuple):
    """
    One classification.csv row, its fields in the order of
    CLASSIFICATION_CSV_HEADER. A rank below the taxon confidence has an
    empty name and score.
    """
    filename: str
    detection: int  # Numbered from 1 within the image
    class_name: str
    score: float
    x: int
    y: int
    w: int
    h: int
    family: str
    family_score: float | str
    genus: str
    genus_score: float | str
    species: str
    species_score: float | str
    classifier_model: str


def summarize_detections(file_name: str, detections: list[Detection], cropped: bool) -> DetectionsRow:
    """
    The detections CSV row of one image: its top detection, how many there
    are, and whether the action cropped the image. "N/A" for the class name
    when nothing was detected.
    """
    if not detections:
        return DetectionsRow(file_name, 0, "N/A", 0, "no")
    top_detection = max(detections, key=lambda d: d.score)
    return DetectionsRow(file_name, top_detection.score, top_detection.class_name, len(detections),
                         "yes" if cropped else "no")


@contextmanager
def csv_writer(path: str, header: list[str]) -> Iterator[Any]:
    """
    A csv writer for one of a Batch Run's CSV files, with the header written.
    The file is created anew, replacing one left by an earlier run. Opening it
    up front fails the run before any image is processed if another program
    holds the file locked, instead of after every image was.
    """
    try:
        csv_file = open(long_path(path), "w", newline="", encoding=CSV_ENCODING)
    except OSError as e:
        raise OSError(f"Cannot write {os.path.basename(path)}. Close it if it is open in another program.") from e
    with csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(header)
        yield writer


def _run_suffix(threshold: int, model_filename: str) -> str:
    """The threshold+model fragment shared by the CSV and settings file names."""
    return f"conf-{threshold}-{strip_model_ext(model_filename or '')}"


def detections_csv_name(detection_confidence: int, model_filename: str) -> str:
    """
    The name of a Batch Run's detections CSV file, encoding the detection
    confidence and the model used (like:
    detectorist-detections-conf-75-fish-seg-transformer-2026-02-24.csv).
    Every run shares the same output directory, so this is what keeps runs
    with different settings from overwriting each other's CSV. A re-run with
    the same detection confidence and model replaces its own prior CSV instead.
    """
    return f"detectorist-detections-{_run_suffix(detection_confidence, model_filename)}.csv"


def classification_csv_name(taxon_confidence: int, classifier_filename: str) -> str:
    """
    The name of a Batch Run's classification CSV file, encoding the taxon
    confidence and the classifier used (like:
    detectorist-classification-conf-73-sulawesi-fish-classification-2026-10-17.csv),
    for the same reason as detections_csv_name().
    """
    return f"detectorist-classification-{_run_suffix(taxon_confidence, classifier_filename)}.csv"


def settings_json_name(detection_confidence: int, model_filename: str) -> str:
    """
    The name of the settings snapshot exported alongside a Batch Run's CSV,
    encoding the same detection confidence and model (like:
    detectorist-settings-conf-75-fish-seg-transformer-2026-02-24.json), so the
    two files pair up at a glance and a re-run overwrites its own prior copy.
    """
    return f"detectorist-settings-{_run_suffix(detection_confidence, model_filename)}.json"
