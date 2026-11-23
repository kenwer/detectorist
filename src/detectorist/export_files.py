"""The files an Export writes besides the images.

The rows and columns of the detections and classification CSV files, and
the names of the CSV and settings files. Turns detections and taxonomies
into CSV cells, without running a detector or classifier.
"""

import csv
import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, NamedTuple

from .classifier import identified_ranks
from .structures import RANK_COUNT, Box, Detection, Taxonomy
from .utils import long_path

CSV_ENCODING = "utf-8-sig"
DETECTIONS_CSV_HEADER = ["Filename", "Highest confidence score", "Class name", "Number of detected objects", "cropped"]
DETECTIONS_CSV_NAME = "detectorist-detections.csv"
CLASSIFICATION_CSV_NAME = "detectorist-classification.csv"
SETTINGS_JSON_NAME = "detectorist-settings.json"
CLASSIFICATION_CSV_HEADER = ["Filename", "Detection", "Class name", "Confidence score", "x", "y", "w", "h",
                             "Family", "Family score", "Genus", "Genus score", "Species", "Species score",
                             "List fit"]

class DetectionsRow(NamedTuple):
    """One detections.csv row, its fields in the order of DETECTIONS_CSV_HEADER."""
    filename: str
    highest_score: float
    class_name: str
    object_count: int
    cropped: str  # "yes", "no", "skipped" for an image the options leave out, or "n/a" for one that failed

    @classmethod
    def from_detections(cls, file_name: str, detections: list[Detection], cropped: str) -> DetectionsRow:
        """
        The row of one image: its top detection and how many there are. "N/A"
        for the class name when nothing was detected.
        """
        if not detections:
            return cls(file_name, 0, "N/A", 0, cropped)
        top_detection = max(detections, key=lambda d: d.score)
        return cls(file_name, top_detection.score, top_detection.class_name, len(detections), cropped)


class ClassificationRow(NamedTuple):
    """
    One classification.csv row, its fields in the order of
    CLASSIFICATION_CSV_HEADER. A rank below the taxon confidence has an
    empty name and score. The list fit is empty without a species list (see
    Taxonomy).
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
    list_fit: float | str

    @classmethod
    def from_taxonomy(cls, file_name: str, number: int, detection: Detection, box: Box,
                      taxonomy: Taxonomy | None, taxon_confidence: float) -> ClassificationRow:
        """
        The row of one named detection, numbered within its image, with box
        as its (x1, y1, x2, y2) corners. A rank scoring below
        taxon_confidence is left empty, and so is every rank below it, as in
        the tooltip (see identified_ranks). Without a taxonomy, because the
        classifier failed, the family reads "classify-error".
        """
        x1, y1, x2, y2 = box
        head = (file_name, number, detection.class_name, detection.score, x1, y1, x2 - x1, y2 - y1)
        if taxonomy is None:
            return cls(*head, "classify-error", "", "", "", "", "", "")
        ranks: list[tuple[str, float | str]] = [*identified_ranks(taxonomy, taxon_confidence)]
        family, genus, species = ranks + [("", "")] * (RANK_COUNT - len(ranks))
        list_fit = "" if taxonomy.list_fit is None else taxonomy.list_fit
        return cls(*head, *family, *genus, *species, list_fit)


@contextmanager
def csv_writer(path: str, header: list[str]) -> Generator[Any]:
    """
    A csv writer for one of an Export's CSV files, with the header written.
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
