"""The Batch Run: one pass of a detector (and a classifier) over a set of images.

Owns the pipeline (load, detect, filter, act, classify, log) plus
cancellation, the detections.csv summary and, with a classifier, the
classification.csv. Loading runs one image ahead on a background thread so
decode overlaps detection. Qt-free: progress crosses a callback seam, and the
per-image behaviour is a BatchAction adapter (Crop & Export or Sort by
Class), so the whole run can be exercised headless.
"""

import csv
import locale
import logging
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Protocol

from .classifier import Classifier, detections_to_classify, identified_ranks
from .crop_planner import CropSettings, plan_crops
from .image_object import ImageObject
from .structures import Detection, clamp_box
from .utils import long_path, strip_model_ext

logger = logging.getLogger(__name__)

# Called before each image as (index, total, filename). Returning False cancels the run.
ProgressFn = Callable[[int, int, str], bool]

# One detections.csv row. See DETECTIONS_CSV_HEADER for the columns.
DetectionsRow = tuple[str, float, str, int, str]

DETECTIONS_CSV_HEADER = ["Filename", "Highest confidence score", "Class name", "Number of detected objects", "cropped"]
CSV_ENCODING = "utf-8-sig"

# One classification.csv row. See CLASSIFICATION_CSV_HEADER for the columns.
ClassificationRow = tuple[str, int, str, float, int, int, int, int,
                          str, float | str, str, float | str, str, float | str, str]

CLASSIFICATION_CSV_HEADER = ["Filename", "Detection", "Class name", "Confidence score", "x", "y", "w", "h",
                             "Family", "Family score", "Genus", "Genus score", "Species", "Species score",
                             "Classifier model"]


def classify_detections(classifier: Classifier, taxon_confidence: float, image: ImageObject,
                        detections: list[Detection]) -> list[ClassificationRow]:
    """
    Runs the classifier over the detections of one image and returns their
    classification CSV rows.

    One row per detection the classifier names (see detections_to_classify),
    numbered from 1 in that order. A rank scoring below taxon_confidence is
    left empty, and so is every rank below it, as in the tooltip (see
    identified_ranks). A detection without any identified rank still gets
    its row, so it is counted.

    The box is clamped to the image (see clamp_box).
    """
    to_classify = detections_to_classify(detections, 0.0, classifier.patterns)
    if not to_classify:
        return []
    taxonomies = classifier.classify(image, [d.box for d in to_classify])
    file_name = os.path.basename(image.image_path)
    model_name = strip_model_ext(os.path.basename(classifier.model_path))

    rows = []
    for number, (detection, taxonomy) in enumerate(zip(to_classify, taxonomies, strict=True), start=1):
        x1, y1, x2, y2 = clamp_box(detection.box, image.width, image.height)
        ranks = identified_ranks(taxonomy, taxon_confidence)
        names = [value for rank in ranks for value in rank] + ["", ""] * (len(taxonomy) - len(ranks))
        rows.append((file_name, number, detection.class_name, detection.score, x1, y1, x2 - x1, y2 - y1,
                     *names, model_name))
    return rows


class BatchAction(Protocol):
    """
    Per-image behaviour of a Batch Run (e.g. CropExportAction, SortByClassAction).

    A structural interface: actions don't subclass this, they satisfy it by
    providing matching prepare() and process() methods.
    """

    def prepare(self, output_dir: str) -> None:
        """Create whatever directories the action needs inside output_dir."""
        ...

    def process(self, image: ImageObject, detections: list[Detection]) -> DetectionsRow | None:
        """Handle one image and its confidence-filtered detections."""
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


class _CsvTable:
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


def _run_suffix(confidence: int, model_filename: str) -> str:
    """The confidence+model fragment shared by the CSV and settings file names."""
    return f"conf-{confidence}-{strip_model_ext(model_filename or '')}"


def detections_csv_name(detection_confidence: int, model_filename: str) -> str:
    """
    The name of a Batch Run's detections CSV file, encoding the confidence
    level and the model used (like:
    detectorist-detections-conf-75-fish-seg-transformer-2026-02-24.csv).
    Every run shares the same output directory, so this is what keeps runs
    with different settings from overwriting each other's CSV. A re-run with
    the same confidence and model overwrites its own prior CSV instead.
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
    encoding the same confidence level and model (like:
    detectorist-settings-conf-75-fish-seg-transformer-2026-02-24.json), so the
    two files pair up at a glance and a re-run overwrites its own prior copy.
    """
    return f"detectorist-settings-{_run_suffix(detection_confidence, model_filename)}.json"


def run_batch(image_paths: list[str], detector, detection_confidence: float, exposure_correction: bool,
              output_dir: str, detections_csv_filename: str, action: BatchAction, progress: ProgressFn,
              class_filter: str | None = None, classifier: Classifier | None = None,
              taxon_confidence: float = 0.0, classification_csv_filename: str = "") -> BatchResult:
    """
    Runs the detector (and the classifier) over the given images, delegating each one to the action
    and updating detections_csv_filename in the output directory with a row per image.
    With a classifier, classification_csv_filename gets a row per named
    detection too (see classify_detections).

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
    failing classification is only logged and leaves the image without
    classification rows: the action has already handled it.

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

    detections_table = _CsvTable(os.path.join(output_dir, detections_csv_filename), DETECTIONS_CSV_HEADER)
    classification_table = (_CsvTable(os.path.join(output_dir, classification_csv_filename),
                                      CLASSIFICATION_CSV_HEADER)
                            if classifier is not None else None)

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
                    detections_row = (file_name, 0, "load-error", 0, "n/a")
                    new_detections_rows.append(detections_row)
                    detections_table.replace(file_name, [detections_row])
                    failed.append(file_name)
                    if classification_table is not None:
                        # Rows of a prior run would contradict the load-error row
                        classification_table.replace(file_name, [])
                    continue

                try:
                    detections = [d for d in detector.detect(image)
                                  if d.score >= detection_confidence and class_filter in (None, d.class_name)]
                    detections_row = action.process(image, detections)
                except Exception:
                    logger.exception("%s: could not process image", file_name)
                    detections_row = (file_name, 0, "process-error", 0, "n/a")
                    detections = []
                    failed.append(file_name)

                if detections_row:
                    new_detections_rows.append(detections_row)
                    detections_table.replace(file_name, [detections_row])

                if classification_table is not None:
                    image_classification_rows = []
                    try:
                        image_classification_rows = classify_detections(classifier, taxon_confidence, image, detections)
                    except Exception:
                        logger.exception("%s: could not classify the detections", file_name)
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

    def process(self, image: ImageObject, detections: list[Detection]) -> DetectionsRow:
        """
        Save one crop per planned rectangle, named <stem>_crop<ext>, or
        <stem>_crop_<i><ext> when an image yields several crops (the
        EACH_OBJECT crop mode). Images with no detections, or whose
        detections produce no usable crop rectangle, are copied in renamed to
        <stem>_ncrop<ext>. The returned row reports the top detection and
        whether a crop was produced.
        """
        file_name = os.path.basename(image.image_path)
        base, ext = os.path.splitext(file_name)

        if not detections:
            image.copy_image(self.output_dir, f"{base}_ncrop{ext}")
            return file_name, 0, "N/A", 0, "no"

        top_detection = max(detections, key=lambda d: d.score)
        confidence_score = top_detection.score
        class_name = top_detection.class_name

        crop_tuples = plan_crops(detections, image.height, image.width, self.crop_settings)

        if not crop_tuples:
            logger.warning("%s: invalid crop rectangle, crop_tuples: %s", file_name, crop_tuples)
            image.copy_image(self.output_dir, f"{base}_ncrop{ext}")
            return file_name, confidence_score, class_name, len(detections), "no"

        for i, crop_tuple in enumerate(crop_tuples):
            if len(crop_tuples) > 1:
                crop_name = f"{base}_crop_{i}{ext}"
            else:
                crop_name = f"{base}_crop{ext}"
            image.save_cropped(crop_tuple, os.path.join(self.output_dir, crop_name))

        return file_name, confidence_score, class_name, len(detections), "yes"


class SortByClassAction:
    """Copies each image into a folder named after its top detection's class."""

    def prepare(self, output_dir: str) -> None:
        """
        Only remember the output directory. Unlike CropExportAction, no
        folders are created here because their names depend on which classes
        get detected during the run.
        """
        self._output_dir = output_dir

    def process(self, image: ImageObject, detections: list[Detection]) -> DetectionsRow:
        """
        Copy the image (never move it) into a folder named after its top
        detection's class, creating the folder on first use. Images without
        detections go to no-detection/ so every input image is accounted for
        in the output. This action never crops, so the returned row always
        reports "no" in the cropped column. The class name is already in the
        Class name column.
        """
        file_name = os.path.basename(image.image_path)
        if detections:
            top_detection = max(detections, key=lambda d: d.score)
            class_name = top_detection.class_name
            class_dir = os.path.join(self._output_dir, class_name)
            os.makedirs(long_path(class_dir), exist_ok=True)
            image.copy_image(class_dir)
            return file_name, top_detection.score, class_name, len(detections), "no"
        else:
            no_detection_dir = os.path.join(self._output_dir, "no-detection")
            os.makedirs(long_path(no_detection_dir), exist_ok=True)
            image.copy_image(no_detection_dir)
            return file_name, 0, "no-detection", 0, "no"
