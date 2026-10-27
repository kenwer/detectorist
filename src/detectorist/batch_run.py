"""The Batch Run: one pass of a detector (and a classifier) over a set of images.

Owns the per-image rules (filter, classify, act, log). The BatchWriter
writes what a run produces, the Pipeline drives the run in the app and
overlaps decoding with inference, and run_batch drives it synchronously.
The rows and the CSV files they go into are batch_output's. Qt-free: the
per-image behaviour is a BatchAction adapter (Export), so the whole run can
be exercised headless.
"""

import logging
import os
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack, suppress
from dataclasses import dataclass, field
from typing import Protocol

from .batch_output import (
    CLASSIFICATION_CSV_HEADER,
    CLASSIFICATION_CSV_NAME,
    DETECTIONS_CSV_HEADER,
    DETECTIONS_CSV_NAME,
    ClassificationRow,
    DetectionsRow,
    csv_writer,
    summarize_detections,
)
from .classifier import Classifier, detections_to_classify, identified_ranks
from .export_planner import ExportOptions
from .image_object import ImageObject
from .structures import Box, Detection, Taxonomy, clamp_box
from .utils import long_path

logger = logging.getLogger(__name__)

# Called before each image as (index, total, filename). Returning False cancels the run.
ProgressFn = Callable[[int, int, str], bool]


def classify_detections(classifier: Classifier, image: ImageObject, detections: list[Detection]) -> dict[Box, Taxonomy]:
    """Runs the classifier over the detections of one image and returns their taxonomies by box."""
    if not detections:
        return {}
    taxonomies = classifier.classify(image, [d.box for d in detections])
    return dict(zip([d.box for d in detections], taxonomies, strict=True))


def classification_rows(image: ImageObject, named: list[Detection], taxonomy_by_box: Mapping[Box, Taxonomy],
                        taxon_confidence: float) -> list[ClassificationRow]:
    """
    The classification CSV rows of one image: one per named detection,
    numbered from 1 in the order of named (see detections_to_classify). A
    rank scoring below taxon_confidence is left empty, and so is every rank
    below it, as in the tooltip (see identified_ranks). A detection without
    any identified rank still gets its row, so it is counted. So does one
    missing from taxonomy_by_box because the classifier failed, with
    "classify-error" as its family.

    The box is clamped to the image (see clamp_box).
    """
    file_name = os.path.basename(image.image_path)
    rows = []
    for number, detection in enumerate(named, start=1):
        x1, y1, x2, y2 = clamp_box(detection.box, image.width, image.height)
        taxonomy = taxonomy_by_box.get(detection.box)
        if taxonomy is None:
            names = ["classify-error"] + [""] * (2 * len(Taxonomy._fields) - 1)
        else:
            ranks = identified_ranks(taxonomy, taxon_confidence)
            names = [value for rank in ranks for value in rank] + ["", ""] * (len(taxonomy) - len(ranks))
        rows.append(ClassificationRow(file_name, number, detection.class_name, detection.score,
                                      x1, y1, x2 - x1, y2 - y1, *names))
    return rows


class BatchAction(Protocol):
    """
    Per-image behaviour of a Batch Run (e.g. CropExportAction).
    Actions write image files. The detections and classification CSV rows are
    run_batch's job (see summarize_detections and classification_rows).

    A structural interface: actions don't subclass this, they satisfy it by
    providing matching prepare() and process() methods.
    """

    def prepare(self, output_dir: str) -> None:
        """Create whatever directories the action needs inside output_dir."""
        ...

    def process(self, image: ImageObject, detections: list[Detection], taxonomy_by_box: Mapping[Box, Taxonomy]) -> bool:
        """
        Handle one image and its detections filtered by detection confidence.
        taxonomy_by_box holds what the classifier named them, empty without
        one. Returns whether the image was cropped.
        """
        ...


@dataclass
class BatchResult:
    """
    The outcome a Batch Run reports back, so callers can react without
    re-reading the output directory. DetectoristApp uses it to export the
    settings alongside the CSV, reveal output_dir, and show finished vs.
    cancelled (a cancelled crop & export also keeps the images in the image
    list). Tests assert on the rows instead of parsing the CSV files.
    """

    output_dir: str
    cancelled: bool
    detections_rows: list[DetectionsRow]
    failed: list[str] = field(default_factory=list)  # Filenames of the images that could not be loaded or processed
    classification_rows: list[ClassificationRow] = field(default_factory=list)


def _load_image(image_path: str, exposure_correction: bool) -> ImageObject:
    """Load one image for run_batch."""
    image = ImageObject.create(image_path)
    image.exposure_correction = exposure_correction
    return image


def batch_detections(detections: list[Detection], threshold: float, class_filter: str | None) -> list[Detection]:
    """What a Batch Run keeps of an image's detections: those at or above threshold, of class_filter if given."""
    return [d for d in detections if d.score >= threshold and class_filter in (None, d.class_name)]


class BatchWriter:
    """
    Writes what a Batch Run produces for each image: the action's files and
    the rows of both CSV files. Images are written in the order given.

    The CSV files only ever hold this run's rows. CSV files from an earlier
    run are replaced, as are image files the action writes under a name
    already taken. Without classification, an earlier run's classification
    CSV is removed, as it would not belong to this run. Other files in the
    output directory are left alone. Rows are written as each image is, so
    a cancelled or failed run keeps the rows of the images it got through.

    An image that failed to load gets a "load-error" row, one whose action
    fails a "process-error" row, and both are listed in the result's
    failed, so one corrupt file cannot end a batch of thousands. A box
    missing from the names marks its classification row with
    "classify-error" (see classification_rows).
    """

    def __init__(self, output_dir: str, action: BatchAction, with_classification: bool,
                 patterns: Sequence[str], taxon_confidence: float):
        """
        Args:
            output_dir: Created if missing. Receives the action's output
                alongside the CSV files.
            action: The per-image behaviour (e.g. CropExportAction).
            with_classification: Whether a classifier names the detections,
                which writes the classification CSV.
            patterns: The detection classes the classifier names (see class_matches).
            taxon_confidence: Minimum score of a rank for its name to be written.
        """
        self._output_dir = output_dir
        self._action = action
        self._with_classification = with_classification
        self._patterns = tuple(patterns)
        self._taxon_confidence = taxon_confidence
        self._csv_files = ExitStack()
        self._detections_csv = None
        self._classification_csv = None
        self._detections_rows: list[DetectionsRow] = []
        self._classification_rows: list[ClassificationRow] = []
        self._failed: list[str] = []  # names of the images that could not be loaded or processed

    def open(self) -> None:
        """
        Creates the output directory and opens both CSV files before the
        first image, so a locked one fails the run before anything is written.
        """
        os.makedirs(long_path(self._output_dir), exist_ok=True)
        self._action.prepare(self._output_dir)
        self._detections_csv = self._csv_files.enter_context(
            csv_writer(os.path.join(self._output_dir, DETECTIONS_CSV_NAME), DETECTIONS_CSV_HEADER))
        if self._with_classification:
            self._classification_csv = self._csv_files.enter_context(
                csv_writer(os.path.join(self._output_dir, CLASSIFICATION_CSV_NAME), CLASSIFICATION_CSV_HEADER))
        else:
            with suppress(FileNotFoundError):
                os.remove(long_path(os.path.join(self._output_dir, CLASSIFICATION_CSV_NAME)))

    def write(self, image_path: str, image: ImageObject, detections: list[Detection],
              names: Mapping[Box, Taxonomy]) -> None:
        """
        Hands one image to the action and writes its rows. detections are
        those the run keeps (see batch_detections), names what the
        classifier said about them, empty without one.
        """
        file_name = os.path.basename(image_path)
        rows: list[ClassificationRow] = []
        try:
            if self._with_classification:
                named = detections_to_classify(detections, 0.0, self._patterns)
                rows = classification_rows(image, named, names, self._taxon_confidence)
            cropped = self._action.process(image, detections, names)
            detections_row = summarize_detections(file_name, detections, cropped)
        except Exception:
            logger.exception("%s: could not process image", file_name)
            detections_row = DetectionsRow(file_name, 0, "process-error", 0, "n/a")
            # Rows of detections the process-error row no longer lists would contradict it
            rows = []
            self._failed.append(file_name)
        self._add_rows(detections_row, rows)

    def write_failure(self, image_path: str, kind: str = "load-error") -> None:
        """Writes the row of an image that could not be loaded, or with kind "process-error" not detected."""
        file_name = os.path.basename(image_path)
        self._failed.append(file_name)
        self._add_rows(DetectionsRow(file_name, 0, kind, 0, "n/a"), [])

    def _add_rows(self, detections_row: DetectionsRow, rows: list[ClassificationRow]) -> None:
        self._detections_rows.append(detections_row)
        self._detections_csv.writerow(detections_row)
        if self._classification_csv is not None:
            self._classification_rows += rows
            self._classification_csv.writerows(rows)

    def close(self, cancelled: bool) -> BatchResult:
        """Closes the CSV files and returns the rows written."""
        self._csv_files.close()
        return BatchResult(output_dir=self._output_dir, cancelled=cancelled, detections_rows=self._detections_rows,
                           failed=self._failed, classification_rows=self._classification_rows)


def run_batch(image_paths: list[str], detector, detection_confidence: float, exposure_correction: bool,
              output_dir: str, action: BatchAction, progress: ProgressFn,
              class_filter: str | None = None, classifier: Classifier | None = None,
              taxon_confidence: float = 0.0) -> BatchResult:
    """
    Runs the detector (and the classifier) over the given images one after
    the other on the calling thread, writing through a BatchWriter. The app
    runs batches through the Pipeline instead, which overlaps decoding with
    inference. This synchronous runner keeps the per-image rules testable
    without threads.

    The detections are classified before the action runs, as the
    BEST_CLASSIFICATION crop mode picks its crop by their names. A failing
    classification is logged and the image is written as if nothing was named.

    Args:
        image_paths: Full paths of the images to process.
        detector: Anything with detect(image) -> list of detections.
        detection_confidence: Minimum score a detection must have to be kept.
        exposure_correction: Apply the camera exposure bias to the exported images.
        output_dir: Created if missing. Receives the action's output
            alongside the CSV files.
        action: The per-image behaviour (e.g. CropExportAction).
        progress: Called before each image. Returning False cancels the run.
        class_filter: Keep only detections of this class name. None keeps all
            classes. An image left without detections is handled by the
            action like one where nothing was detected.
        classifier: Names the detections of each image. None writes no
            classification CSV.
        taxon_confidence: Minimum score of a rank for its name to be written.

    Returns:
        A BatchResult with the output directory, whether the run was cancelled,
        and the rows written to the CSV files.
    """
    writer = BatchWriter(output_dir, action, classifier is not None,
                         classifier.patterns if classifier is not None else (), taxon_confidence)
    writer.open()
    total = len(image_paths)
    for i, image_path in enumerate(image_paths):
        if not progress(i, total, os.path.basename(image_path)):
            return writer.close(cancelled=True)
        try:
            image = _load_image(image_path, exposure_correction)
        except Exception as e:
            logger.warning("%s: could not load image: %s", os.path.basename(image_path), e)
            writer.write_failure(image_path)
            continue
        try:
            detections = batch_detections(detector.detect(image), detection_confidence, class_filter)
        except Exception:
            logger.exception("%s: could not detect objects", os.path.basename(image_path))
            writer.write_failure(image_path, "process-error")
            continue
        names: dict[Box, Taxonomy] = {}
        if classifier is not None:
            try:
                names = classify_detections(classifier, image,
                                            detections_to_classify(detections, 0.0, classifier.patterns))
            except Exception:
                logger.exception("%s: could not classify the detections", os.path.basename(image_path))
        writer.write(image_path, image, detections, names)
    return writer.close(cancelled=False)


@dataclass
class CropExportAction:
    """
    Exports each image flat into the output directory, as crops or as a copy
    of the whole image, as the options plan. Images without detections are
    copied too, so every input image is accounted for in the output.

    A file of the same name from an earlier export is overwritten. Files
    the earlier export named otherwise are left in place.
    """

    options: ExportOptions
    # Derived from the output directory once run_batch calls prepare().
    # Unset until then, so a premature process() fails loudly with an
    # AttributeError. This is by design.
    output_dir: str = field(init=False)

    def prepare(self, output_dir: str) -> None:
        self.output_dir = output_dir

    def process(self, image: ImageObject, detections: list[Detection], taxonomy_by_box: Mapping[Box, Taxonomy]) -> bool:
        """Write the files the options plan for the image. Returns whether a crop was produced."""
        file_name = os.path.basename(image.image_path)
        planned = self.options.plan(file_name, detections, image.height, image.width, taxonomy_by_box)
        if planned[0].rect is None:
            if self.options.crop and detections:
                logger.warning("%s: no usable crop rectangle, copying the image", file_name)
            image.copy_image(self.output_dir, planned[0].name)
            return False
        for file in planned:
            image.save_cropped(file.rect, os.path.join(self.output_dir, file.name))
        return True
