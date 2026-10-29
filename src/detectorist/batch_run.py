"""The Batch Run: one pass of a detector (and a classifier) over a set of images.

Owns the per-image rules (filter, classify, act, log). A BatchRun decides
which job a run needs next and the BatchWriter writes what it produces,
while the Pipeline sends the jobs to its lanes, overlapping decoding with
inference. The rows and the CSV files they go into are batch_output's.
Qt-free: the per-image behaviour is a BatchAction adapter (Export).
"""

import logging
import os
from collections import deque
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, suppress
from dataclasses import dataclass, field
from typing import Literal, Protocol

from .batch_output import (
    CLASSIFICATION_CSV_HEADER,
    CLASSIFICATION_CSV_NAME,
    DETECTIONS_CSV_HEADER,
    DETECTIONS_CSV_NAME,
    ClassificationRow,
    DetectionsRow,
    csv_writer,
)
from .cache import ImageResults, LruCache
from .classifier import detections_to_classify, identified_ranks
from .export_planner import ExportOptions
from .image_object import ImageObject
from .jobs import CancelToken, ClassifyJob, DecodeJob, DetectJob, FileStamp, ModelId
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


class BatchAction(Protocol):
    """
    Per-image behaviour of a Batch Run (e.g. CropExportAction).
    Actions write image files. The detections and classification CSV rows are
    BatchWriter's job (see DetectionsRow.from_detections and classification_rows).

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
            detections_row = DetectionsRow.from_detections(file_name, detections, cropped)
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


@dataclass(frozen=True)
class BatchOptions:
    """What a batch run keeps of each image's detections, and how its exports look."""
    detection_threshold: float
    class_filter: str | None  # keep only this class, None keeps all
    exposure_correction: bool  # whether the exported images are exposure corrected


@dataclass(eq=False)
class _BatchImage:
    """One image of a batch run on its way from the decode lane to the writer."""
    index: int
    path: str
    image: ImageObject | None  # None if it failed to load
    stamp: FileStamp | None
    detections: list[Detection] | None = None  # the ones kept, None until detected or if detection failed
    names: dict[Box, Taxonomy] = field(default_factory=dict)


class BatchRun:
    """
    Decides which job a Batch Run needs next and hands its images to the
    writer, in order. The Pipeline sends the jobs and reports back what came
    of them, one decode and one inference at a time. Images go through
    strictly in order: at most one decoded image waits while another is in
    inference, as each decoded image takes hundreds of MB.

    Detections go into the Pipeline's results cache like any others, so an
    image already detected is not detected again.
    """

    def __init__(self, paths: list[str], options: BatchOptions, writer: BatchWriter):
        self.paths = list(paths)
        self.options = options
        self.writer = writer
        self.token = CancelToken()  # carried by every job of the run, cancelled when the run ends
        self.failure: str | None = None  # why the run cannot go on, raised once the images before are written
        self._next_decode = 0  # index of the next path to decode
        self._ready: _BatchImage | None = None  # decoded, waiting for inference
        self._current: _BatchImage | None = None  # in inference
        self._events: deque[tuple[Literal["start", "write"], _BatchImage]] = deque()  # what write_pending reports, in order
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
        return DecodeJob(self.paths[self._next_decode - 1], self.options.exposure_correction, self.token,
                         for_batch=True)

    def on_decoded(self, job: DecodeJob, image: ImageObject | None, stamp: FileStamp | None) -> None:
        """Takes the image the decode lane loaded for job, None if it failed to load."""
        self._ready = _BatchImage(self._next_decode - 1, job.path, image, stamp)

    def on_detect_failed(self) -> None:
        self._finish_current()

    def next_inference(self, results: LruCache[str, ImageResults], detector_id: ModelId,
                       classify: bool, classifier_id: ModelId | None,
                       patterns: Sequence[str]) -> DetectJob | ClassifyJob | None:
        """
        The next inference job, or None while waiting for a decode or the
        classifier. Images that need none (no boxes to name, or failed) move
        on to the writer here, in order.

        Args:
            classify: Whether the run names the detections it keeps.
            classifier_id: The classifier loaded, None while it is loading.
        """
        while True:
            if self._current is None:
                if self._ready is None:
                    return None
                self._current, self._ready = self._ready, None
                self._events.append(("start", self._current))
            item = self._current
            if item.image is not None:
                cached = results.peek(item.path)
                if cached is None or cached.stamp != item.stamp:
                    return DetectJob(item.path, item.image, item.stamp, detector_id, self.token)
                item.detections = batch_detections(cached.detections, self.options.detection_threshold,
                                                   self.options.class_filter)
                if classify:
                    if classifier_id is None:
                        return None
                    kept = {d.box for d in item.detections}
                    boxes = [box for box in cached.unnamed_boxes(0.0, patterns) if box in kept]
                    if boxes:
                        return ClassifyJob(item.path, item.image, boxes, classifier_id, self.token)
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
    # Derived from the output directory once BatchWriter.open calls prepare().
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
