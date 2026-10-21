"""The files a Batch Run writes besides the action's images.

The rows and columns of the detections and classification CSV files, how a
run merges its rows into a prior run's file, and the names of the CSV and
settings files. Knows nothing about detecting or classifying.
"""

import csv
import locale
import logging
import os
from typing import NamedTuple

from .structures import Detection
from .utils import long_path, strip_model_ext

logger = logging.getLogger(__name__)

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


class CsvTable:
    """
    A Batch Run's CSV file as rows grouped by the image filename in their
    first column. Starts with a prior run's rows, so this run replaces the
    rows of the images it processes again and leaves the rest as they were.
    """

    def __init__(self, path: str, header: list[str]):
        """
        Reads the prior rows and fails before the run starts if the file
        cannot be written, e.g. because another program holds it locked.
        Otherwise the error would only surface after every image was processed.
        """
        self._path = path
        self._header = header
        self._rows_by_filename: dict[str, list[tuple]] = {}
        for row in self._read_prior_rows():
            self._rows_by_filename.setdefault(row[0], []).append(row)

        try:
            # Append mode probes without truncating
            with open(long_path(path), "a"):
                pass
        except OSError as e:
            raise OSError(
                f"Cannot write {os.path.basename(path)}. Close it if it is open in another program."
            ) from e

    def _read_prior_rows(self) -> list[tuple]:
        """
        A missing file, a header other than this table's (e.g. from an older
        app version), or a file that cannot be decoded is treated as "no prior
        data" rather than migrated.
        """
        if not os.path.isfile(long_path(self._path)):
            return []

        for encoding in (CSV_ENCODING, locale.getencoding()):
            try:
                with open(long_path(self._path), newline="", encoding=encoding) as f:
                    reader = csv.reader(f)
                    if next(reader, None) != self._header:
                        logger.warning("%s: header does not match, ignoring prior contents", self._path)
                        return []
                    # Skip blank lines, which a hand-edited file may contain
                    return [tuple(row) for row in reader if row]
            except UnicodeDecodeError:
                continue
        logger.warning("%s: cannot be decoded, ignoring prior contents", self._path)
        return []

    def replace(self, file_name: str, rows: list[tuple]) -> None:
        """Replaces all rows of an image. No rows drops the image from the file."""
        self._rows_by_filename[file_name] = rows

    def write(self) -> None:
        with open(long_path(self._path), "w", newline="", encoding=CSV_ENCODING) as csv_file:
            csv_writer = csv.writer(csv_file)
            csv_writer.writerow(self._header)
            csv_writer.writerows(row for rows in self._rows_by_filename.values() for row in rows)


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
    the same detection confidence and model overwrites its own prior CSV instead.
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
