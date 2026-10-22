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
from .utils import long_path

CSV_ENCODING = "utf-8-sig"
DETECTIONS_CSV_HEADER = ["Filename", "Highest confidence score", "Class name", "Number of detected objects", "cropped"]
DETECTIONS_CSV_NAME = "detectorist-detections.csv"
CLASSIFICATION_CSV_NAME = "detectorist-classification.csv"
SETTINGS_JSON_NAME = "detectorist-settings.json"
CLASSIFICATION_CSV_HEADER = ["Filename", "Detection", "Class name", "Confidence score", "x", "y", "w", "h",
                             "Family", "Family score", "Genus", "Genus score", "Species", "Species score"]

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
