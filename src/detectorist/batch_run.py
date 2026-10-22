"""The Batch Run: one pass of a detector (and a classifier) over a set of images.

Owns the pipeline (load, detect, filter, classify, act, log) plus
cancellation. The rows it produces and the CSV files they go into are
batch_output's. Loading runs one image ahead on a background thread so
decode overlaps detection. Qt-free: progress crosses a callback seam, and the
per-image behaviour is a BatchAction adapter (Export), so the whole run can
be exercised headless.
"""

import logging
import os
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
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
    """Load one image for the pipeline. Runs on the prefetch thread."""
    image = ImageObject.create(image_path)
    image.exposure_correction = exposure_correction
    return image


def run_batch(image_paths: list[str], detector, detection_confidence: float, exposure_correction: bool,
              output_dir: str, action: BatchAction, progress: ProgressFn,
              class_filter: str | None = None, classifier: Classifier | None = None,
              taxon_confidence: float = 0.0) -> BatchResult:
    """
    Runs the detector (and the classifier) over the given images, delegating each one to the action
    and writing DETECTIONS_CSV_NAME in the output directory with a row per image.
    With a classifier, CLASSIFICATION_CSV_NAME gets a row per named
    detection too (see classification_rows).

    The CSV files only ever hold this run's rows. CSV files from an earlier
    run are replaced, as are image files the action writes under a name
    already taken. Without a classifier, an earlier run's classification CSV
    is removed, as it would not belong to this run. Other files in the output
    directory are left alone.
    Rows are written as each image finishes, so a cancelled or failed run
    keeps the rows of the images it got through.

    While an image runs detection and the action, the next image is already
    decoding on a background thread (pillow-heif and ONNX both release the
    GIL, so the overlap is real). The lookahead is one image deep because each
    decoded image can occupy hundreds of MB.

    An image whose load fails is skipped with a "load-error" row instead of
    aborting the run, so one corrupt file cannot end a batch of thousands.
    The same goes for an image whose detection or action fails. It gets a
    "process-error" row. Both kinds are listed in the result's failed. A
    failing classification is logged and marks the image's classification
    rows with "classify-error" (see classification_rows). The action still
    handles the image, as if nothing was named.

    The detections are classified before the action runs, as the
    BEST_CLASSIFICATION crop mode picks its crop by their names.

    Args:
        image_paths: Full paths of the images to process.
        detector: Anything with detect(image) -> list of detections.
        detection_confidence: Minimum score a detection must have to be kept.
        exposure_correction: Apply the camera exposure bias when loading images.
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
    os.makedirs(long_path(output_dir), exist_ok=True)
    action.prepare(output_dir)

    total = len(image_paths)
    new_detections_rows: list[DetectionsRow] = []
    new_classification_rows: list[ClassificationRow] = []
    failed: list[str] = []
    cancelled = False

    # Both CSVs are opened before the first image, so a locked one fails the run before anything is written
    with ExitStack() as csv_files:
        detections_csv = csv_files.enter_context(
            csv_writer(os.path.join(output_dir, DETECTIONS_CSV_NAME), DETECTIONS_CSV_HEADER))
        classification_csv = (csv_files.enter_context(
            csv_writer(os.path.join(output_dir, CLASSIFICATION_CSV_NAME), CLASSIFICATION_CSV_HEADER))
            if classifier is not None else None)
        if classifier is None:
            with suppress(FileNotFoundError):
                os.remove(long_path(os.path.join(output_dir, CLASSIFICATION_CSV_NAME)))

        # The context manager drains any in-flight load on exit (bounded by
        # one decode), so cancellation and errors cannot leak a thread.
        with ThreadPoolExecutor(max_workers=1) as executor:
            next_future = None
            for i, image_path in enumerate(image_paths):
                if not progress(i, total, os.path.basename(image_path)):
                    cancelled = True
                    break

                future = next_future or executor.submit(_load_image, image_path, exposure_correction)
                # Queue the next load before waiting on the current one: the
                # single worker starts it the moment the current load ends,
                # and a failed load still leaves the lookahead running.
                next_future = (executor.submit(_load_image, image_paths[i + 1], exposure_correction)
                               if i + 1 < total else None)

                file_name = os.path.basename(image_path)
                image_classification_rows: list[ClassificationRow] = []
                try:
                    image = future.result()
                except Exception as e:
                    logger.warning("%s: could not load image: %s", file_name, e)
                    detections_row = DetectionsRow(file_name, 0, "load-error", 0, "n/a")
                    failed.append(file_name)
                else:
                    try:
                        detections = [d for d in detector.detect(image)
                                      if d.score >= detection_confidence and class_filter in (None, d.class_name)]
                        taxonomy_by_box: dict[Box, Taxonomy] = {}
                        if classifier is not None:
                            named = detections_to_classify(detections, 0.0, classifier.patterns)
                            try:
                                taxonomy_by_box = classify_detections(classifier, image, named)
                            except Exception:
                                logger.exception("%s: could not classify the detections", file_name)
                            image_classification_rows = classification_rows(image, named, taxonomy_by_box,
                                                                            taxon_confidence)
                        cropped = action.process(image, detections, taxonomy_by_box)
                        detections_row = summarize_detections(file_name, detections, cropped)
                    except Exception:
                        logger.exception("%s: could not process image", file_name)
                        detections_row = DetectionsRow(file_name, 0, "process-error", 0, "n/a")
                        # Rows of detections the process-error row no longer lists would contradict it
                        image_classification_rows = []
                        failed.append(file_name)

                new_detections_rows.append(detections_row)
                detections_csv.writerow(detections_row)
                if classification_csv is not None:
                    new_classification_rows += image_classification_rows
                    classification_csv.writerows(image_classification_rows)

    return BatchResult(output_dir=output_dir, cancelled=cancelled, detections_rows=new_detections_rows,
                       failed=failed, classification_rows=new_classification_rows)


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
