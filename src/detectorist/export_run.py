"""The Export: one pass of a detector (and a classifier) over a set of images.

Owns the per-image rules (filter, classify, export, log). An ExportRun
decides which job an export needs next and the ExportWriter writes what it
produces, while the Pipeline sends the jobs to its lanes, overlapping
decoding with inference. The rows and the CSV files they go into are
export_files's. Qt-free.
"""

import logging
import os
from collections import deque
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, suppress
from dataclasses import dataclass, field
from typing import Literal

from .cache import ImageStore
from .classifier import detections_to_classify, identified_ranks
from .export_files import (
    CLASSIFICATION_CSV_HEADER,
    CLASSIFICATION_CSV_NAME,
    DETECTIONS_CSV_HEADER,
    DETECTIONS_CSV_NAME,
    ClassificationRow,
    DetectionsRow,
    csv_writer,
)
from .export_planner import ExportOptions
from .image_object import ImageObject
from .jobs import CancelToken, ClassifyJob, DecodeJob, DetectJob
from .model_state import Models
from .structures import Box, Detection, Taxonomy, clamp_box
from .utils import long_path

logger = logging.getLogger(__name__)

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


@dataclass
class ExportResult:
    """
    The outcome an Export reports back, so callers can react without
    re-reading the output directory. DetectoristApp uses it to export the
    settings alongside the CSV, reveal output_dir, and show finished vs.
    cancelled (a cancelled export also keeps the images in the image
    list). Tests assert on the rows instead of parsing the CSV files.
    """

    output_dir: str
    cancelled: bool
    detections_rows: list[DetectionsRow]
    failed: list[str] = field(default_factory=list)  # Filenames of the images that could not be loaded or processed
    classification_rows: list[ClassificationRow] = field(default_factory=list)


@dataclass(frozen=True)
class DetectionFilter:
    """Which of an image's detections an Export keeps: those at or above the threshold, of class_filter if given."""
    detection_threshold: float
    class_filter: str | None  # keep only this class, None keeps all

    def keep(self, detections: list[Detection]) -> list[Detection]:
        return [d for d in detections
                if d.score >= self.detection_threshold and self.class_filter in (None, d.class_name)]


class ExportWriter:
    """
    Writes what an Export produces for each image: its crops, or a copy of
    the whole image, as the options plan, and the rows of both CSV files.
    Images are written in the order given. Images without detections are
    copied too, so every input image is accounted for in the output.

    The CSV files only ever hold this run's rows. CSV files from an earlier
    run are replaced, as are image files of the same name. Files an earlier
    export named otherwise are left in place. Without classification, an earlier run's classification
    CSV is removed, as it would not belong to this run. Other files in the
    output directory are left alone. Rows are written as each image is, so
    a cancelled or failed run keeps the rows of the images it got through.

    An image that failed to load gets a "load-error" row, one that could not
    be exported a "process-error" row, and both are listed in the result's
    failed, so one corrupt file cannot end an export of thousands. A box
    missing from the names marks its classification row with
    "classify-error" (see classification_rows).
    """

    def __init__(self, output_dir: str, options: ExportOptions, exposure_correction: bool, with_classification: bool,
                 patterns: Sequence[str], taxon_confidence: float):
        """
        Args:
            output_dir: Created if missing. Receives the exported images
                alongside the CSV files.
            options: How the images are cropped and named.
            exposure_correction: Whether the exported images are exposure corrected.
            with_classification: Whether a classifier names the detections,
                which writes the classification CSV.
            patterns: The detection classes the classifier names (see class_matches).
            taxon_confidence: Minimum score of a rank for its name to be written.
        """
        self._output_dir = output_dir
        self._options = options
        self._exposure_correction = exposure_correction
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
        Exports one image and writes its rows. detections are those the run
        keeps (see DetectionFilter), names what the classifier said about
        them, empty without one.
        """
        file_name = os.path.basename(image_path)
        rows: list[ClassificationRow] = []
        try:
            if self._with_classification:
                named = detections_to_classify(detections, 0.0, self._patterns)
                rows = classification_rows(image, named, names, self._taxon_confidence)
            cropped = self._export_image(image, detections, names)
            detections_row = DetectionsRow.from_detections(file_name, detections, cropped)
        except Exception:
            logger.exception("%s: could not process image", file_name)
            detections_row = DetectionsRow(file_name, 0, "process-error", 0, "n/a")
            # Rows of detections the process-error row no longer lists would contradict it
            rows = []
            self._failed.append(file_name)
        self._add_rows(detections_row, rows)

    def _export_image(self, image: ImageObject, detections: list[Detection],
                      names: Mapping[Box, Taxonomy]) -> bool:
        """Writes the files the options plan for the image. Returns whether a crop was produced."""
        file_name = os.path.basename(image.image_path)
        planned = self._options.plan(file_name, detections, image.height, image.width, names)
        if planned[0].rect is None:
            if self._options.crop and detections:
                logger.warning("%s: no usable crop rectangle, copying the image", file_name)
            image.copy_image(self._output_dir, planned[0].name)
            return False
        for file in planned:
            image.save_cropped(file.rect, os.path.join(self._output_dir, file.name), self._exposure_correction)
        return True

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

    def close(self, cancelled: bool) -> ExportResult:
        """Closes the CSV files and returns the rows written."""
        self._csv_files.close()
        return ExportResult(output_dir=self._output_dir, cancelled=cancelled, detections_rows=self._detections_rows,
                           failed=self._failed, classification_rows=self._classification_rows)


@dataclass(eq=False)
class _ExportImage:
    """One image of an Export on its way from the decode lane to the writer."""
    index: int
    path: str  # kept apart from image, as an image that failed to load still gets its row
    image: ImageObject | None  # None if it failed to load
    detections: list[Detection] | None = None  # the ones kept, None until detected or if detection failed
    names: dict[Box, Taxonomy] = field(default_factory=dict)


class ExportRun:
    """
    Decides which job an Export needs next and hands its images to the
    writer, in order. The Pipeline sends the jobs and reports back what came
    of them, one decode and one inference at a time. Images go through
    strictly in order: at most one decoded image waits while another is in
    inference, as each decoded image takes hundreds of MB.

    Detections go into the Pipeline's results cache like any others, so an
    image already detected is not detected again.
    """

    def __init__(self, paths: list[str], detection_filter: DetectionFilter, writer: ExportWriter):
        self.paths = list(paths)
        self.detection_filter = detection_filter
        self.writer = writer
        self.token = CancelToken()  # carried by every job of the run, cancelled when the run ends
        self.failure: str | None = None  # why the run cannot go on, raised once the images before are written
        self._next_decode = 0  # index of the next path to decode
        self._ready: _ExportImage | None = None  # decoded, waiting for inference
        self._current: _ExportImage | None = None  # in inference
        self._events: deque[tuple[Literal["start", "write"], _ExportImage]] = deque()  # what write_pending reports, in order
        self._written = 0  # images handed to the writer

    def owns(self, job) -> bool:
        return job.token is self.token

    @property
    def done(self) -> bool:
        return self._written == len(self.paths)

    def next_decode(self) -> DecodeJob | None:
        if self._ready is not None or self._next_decode >= len(self.paths):
            return None
        self._next_decode += 1
        return DecodeJob(self.paths[self._next_decode - 1], self.token)

    def on_decoded(self, image: ImageObject | None) -> None:
        """Takes the image the decode lane loaded last, None if it failed to load."""
        index = self._next_decode - 1
        self._ready = _ExportImage(index, self.paths[index], image)

    def on_detect_failed(self) -> None:
        self._finish_current()

    def next_inference(self, store: ImageStore, models: Models) -> DetectJob | ClassifyJob | None:
        """
        The next inference job, or None while waiting for a decode or the
        classifier. Images that need none (no boxes to name, or failed) move
        on to the writer here, in order. The detector must be loaded. The
        detections the run keeps are named if a classifier is loaded or
        loading.
        """
        while True:
            if self._current is None:
                if self._ready is None:
                    return None
                self._current, self._ready = self._ready, None
                self._events.append(("start", self._current))
            item = self._current
            if item.image is not None:
                cached = store.results_for(item.image)
                if cached is None:
                    return DetectJob(item.image, models.detector_id, self.token)
                item.detections = self.detection_filter.keep(cached.detections)
                if models.classifier_state.is_loaded_or_loading:
                    if models.classifier_id is None:
                        return None
                    kept = {d.box for d in item.detections}
                    boxes = [box for box in cached.unnamed_boxes(0.0, models.patterns) if box in kept]
                    if boxes:
                        return ClassifyJob(item.image, boxes, models.classifier_id, self.token)
                    item.names = {box: cached.names[box] for box in kept if box in cached.names}
            self._finish_current()

    def write_pending(self) -> Iterator[tuple[int, int, str]]:
        """
        Hands the images through inference to the writer, in order, yielding
        (index, total, file name) as each image starts. A caller that stops
        iterating on a progress report, e.g. to cancel the run, therefore
        finds every image before the reported one written, and nothing after it.
        """
        while self._events:
            kind, item = self._events.popleft()
            if kind == "start":
                yield item.index, len(self.paths), os.path.basename(item.path)
                continue
            if item.image is None:
                self.writer.write_failure(item.path)
            elif item.detections is None:
                self.writer.write_failure(item.path, "process-error")
            else:
                self.writer.write(item.path, item.image, item.detections, item.names)
            self._written += 1

    def _finish_current(self) -> None:
        self._events.append(("write", self._current))
        self._current = None

