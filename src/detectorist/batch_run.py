"""The Batch Run: one pass of a detector (and a classifier) over a set of images.

Owns the pipeline (load, detect, filter, classify, act, log) plus
cancellation. The rows it produces and the CSV files they go into are
batch_output's. Loading runs one image ahead on a background thread so
decode overlaps detection. Qt-free: progress crosses a callback seam, and the
per-image behaviour is a BatchAction adapter (Crop & Export or Sort by
Class), so the whole run can be exercised headless.
"""

import logging
import os
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Protocol

from .batch_output import (
    CLASSIFICATION_CSV_HEADER,
    DETECTIONS_CSV_HEADER,
    ClassificationRow,
    CsvTable,
    DetectionsRow,
    summarize_detections,
)
from .classifier import Classifier, detections_to_classify, identified_ranks
from .crop_planner import CropSettings, plan_crops
from .image_object import ImageObject
from .structures import Box, Detection, Taxonomy, clamp_box
from .utils import long_path, strip_model_ext

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
                        taxon_confidence: float, model_name: str) -> list[ClassificationRow]:
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
                                      x1, y1, x2 - x1, y2 - y1, *names, model_name))
    return rows


class BatchAction(Protocol):
    """
    Per-image behaviour of a Batch Run (e.g. CropExportAction, SortByClassAction).
    Actions only write image files. The CSV rows are run_batch's job (see
    summarize_detections and classification_rows).

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
              output_dir: str, detections_csv_filename: str, action: BatchAction, progress: ProgressFn,
              class_filter: str | None = None, classifier: Classifier | None = None,
              taxon_confidence: float = 0.0, classification_csv_filename: str = "") -> BatchResult:
    """
    Runs the detector (and the classifier) over the given images, delegating each one to the action
    and updating detections_csv_filename in the output directory with a row per image.
    With a classifier, classification_csv_filename gets a row per named
    detection too (see classification_rows).

    A filename already present in detections_csv_filename from a prior run keeps its row
    unless this run processes that same image again, in which case the row is
    replaced. Filenames untouched by this run are left as they were. This
    lets the CSV reflect the latest known state across repeated runs even
    though the underlying image files themselves get overwritten. The
    classification CSV is updated the same way, with all rows of an image
    replaced together.

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
        output_dir: Created if missing. Shared across runs. Receives the
            action's output alongside the CSV files.
        detections_csv_filename: Name of the detections CSV written into output_dir
            (see detections_csv_name()).
        action: The per-image behaviour (e.g. CropExportAction, SortByClassAction).
        progress: Called before each image. Returning False cancels the run.
        class_filter: Keep only detections of this class name. None keeps all
            classes. An image left without detections is handled by the
            action like one where nothing was detected.
        classifier: Names the detections of each image. None writes no
            classification CSV.
        taxon_confidence: Minimum score of a rank for its name to be written.
        classification_csv_filename: Name of the classification CSV written
            into output_dir (see classification_csv_name()). Only used with a
            classifier.

    Returns:
        A BatchResult with the output directory, whether the run was cancelled,
        and the rows this run produced (not the full merged CSV contents).
    """
    os.makedirs(long_path(output_dir), exist_ok=True)
    action.prepare(output_dir)

    total = len(image_paths)
    new_detections_rows: list[DetectionsRow] = []
    new_classification_rows: list[ClassificationRow] = []
    failed: list[str] = []
    cancelled = False

    detections_table = CsvTable(os.path.join(output_dir, detections_csv_filename), DETECTIONS_CSV_HEADER)
    classification_table = (CsvTable(os.path.join(output_dir, classification_csv_filename),
                                     CLASSIFICATION_CSV_HEADER)
                            if classifier is not None else None)
    classifier_name = strip_model_ext(os.path.basename(classifier.model_path)) if classifier is not None else ""

    try:
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
                try:
                    image = future.result()
                except Exception as e:
                    logger.warning("%s: could not load image: %s", file_name, e)
                    detections_row = DetectionsRow(file_name, 0, "load-error", 0, "n/a")
                    new_detections_rows.append(detections_row)
                    detections_table.replace(file_name, [detections_row])
                    failed.append(file_name)
                    if classification_table is not None:
                        # Rows of a prior run would contradict the load-error row
                        classification_table.replace(file_name, [])
                    continue

                image_classification_rows: list[ClassificationRow] = []
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
                                                                        taxon_confidence, classifier_name)
                    cropped = action.process(image, detections, taxonomy_by_box)
                    detections_row = summarize_detections(file_name, detections, cropped)
                except Exception:
                    logger.exception("%s: could not process image", file_name)
                    detections_row = DetectionsRow(file_name, 0, "process-error", 0, "n/a")
                    # Rows of detections the process-error row no longer lists would contradict it
                    image_classification_rows = []
                    failed.append(file_name)
                new_detections_rows.append(detections_row)
                detections_table.replace(file_name, [detections_row])

                if classification_table is not None:
                    new_classification_rows += image_classification_rows
                    classification_table.replace(file_name, image_classification_rows)
    finally:
        detections_table.write()
        if classification_table is not None:
            classification_table.write()

    return BatchResult(output_dir=output_dir, cancelled=cancelled, detections_rows=new_detections_rows,
                       failed=failed, classification_rows=new_classification_rows)


@dataclass
class CropExportAction:
    """
    Crops each image around its detections into the output directory,
    named <stem>_crop<ext>. Images without usable detections are just
    copied, renamed <stem>_ncrop<ext>, so every input image is accounted
    for in the output.
    """

    crop_settings: CropSettings
    # Derived from the output directory once run_batch calls prepare().
    # Unset until then, so a premature process() fails loudly with an
    # AttributeError. This is by design.
    output_dir: str = field(init=False)

    def prepare(self, output_dir: str) -> None:
        """Remember the output directory. Every file lands directly inside it."""
        self.output_dir = output_dir

    def process(self, image: ImageObject, detections: list[Detection], taxonomy_by_box: Mapping[Box, Taxonomy]) -> bool:
        """
        Save one crop per planned rectangle, named <stem>_crop<ext>, or
        <stem>_crop_<i><ext> when an image yields several crops (the
        EACH_OBJECT crop mode). Images with no detections, or whose
        detections produce no usable crop rectangle, are copied in renamed to
        <stem>_ncrop<ext>. Returns whether a crop was produced.
        """
        file_name = os.path.basename(image.image_path)
        base, ext = os.path.splitext(file_name)

        crop_tuples = plan_crops(detections, image.height, image.width, self.crop_settings, taxonomy_by_box) if detections else []

        if not crop_tuples:
            if detections:
                logger.warning("%s: invalid crop rectangle, crop_tuples: %s", file_name, crop_tuples)
            image.copy_image(self.output_dir, f"{base}_ncrop{ext}")
            return False

        for i, crop_tuple in enumerate(crop_tuples):
            if len(crop_tuples) > 1:
                crop_name = f"{base}_crop_{i}{ext}"
            else:
                crop_name = f"{base}_crop{ext}"
            image.save_cropped(crop_tuple, os.path.join(self.output_dir, crop_name))
        return True


class SortByClassAction:
    """Copies each image into a folder named after its top detection's class."""

    def prepare(self, output_dir: str) -> None:
        """
        Only remember the output directory. Unlike CropExportAction, no
        folders are created here because their names depend on which classes
        get detected during the run.
        """
        self._output_dir = output_dir

    def process(self, image: ImageObject, detections: list[Detection], taxonomy_by_box: Mapping[Box, Taxonomy]) -> bool:
        """
        Copy the image (never move it) into a folder named after its top
        detection's class, creating the folder on first use. Images without
        detections go to no-detection/ so every input image is accounted for
        in the output. Never crops, so always returns False.
        """
        folder = max(detections, key=lambda d: d.score).class_name if detections else "no-detection"
        class_dir = os.path.join(self._output_dir, folder)
        os.makedirs(long_path(class_dir), exist_ok=True)
        image.copy_image(class_dir)
        return False
