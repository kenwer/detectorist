"""The Batch Run: one pass of a detector over a set of images.

Owns the pipeline (load, detect, filter, act, log) plus cancellation and
the detections.csv summary. Loading runs one image ahead on a background
thread so decode overlaps detection. Qt-free: progress crosses a callback
seam, and the per-image behaviour is a BatchAction adapter (Crop & Export
or Sort by Class), so the whole run can be exercised headless.
"""

import csv
import logging
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Protocol

from .crop_planner import CropSettings, plan_crops
from .image_object import ImageObject
from .structures import Detection
from .utils import long_path, strip_model_ext

logger = logging.getLogger(__name__)

# Called before each image as (index, total, filename). Returning False cancels the run.
ProgressFn = Callable[[int, int, str], bool]

# One detections.csv row. See CSV_HEADER for the columns.
CsvRow = tuple[str, float, str, int, str]

CSV_HEADER = ["Filename", "Highest confidence score", "Class name", "Number of detected objects", "cropped"]


class BatchAction(Protocol):
    """
    Per-image behaviour of a Batch Run (e.g. CropExportAction, SortByClassAction).

    A structural interface: actions don't subclass this, they satisfy it by
    providing matching prepare() and process() methods.
    """

    def prepare(self, output_dir: str) -> None:
        """Create whatever directories the action needs inside output_dir."""
        ...

    def process(self, image: ImageObject, detections: list[Detection]) -> CsvRow | None:
        """Handle one image and its confidence-filtered detections."""
        ...


@dataclass
class BatchResult:
    """
    The outcome a Batch Run reports back, so callers can react without
    re-reading the output directory. DetectoristApp uses it to export the
    settings alongside the CSV, reveal output_dir, and show finished vs.
    cancelled (a cancelled crop & export also keeps the images in the image
    list). Tests assert on rows instead of parsing detections.csv.
    """

    output_dir: str
    cancelled: bool
    rows: list[CsvRow]


def _load_image(image_path: str, exposure_correction: bool) -> ImageObject:
    """Load one image for the pipeline. Runs on the prefetch thread."""
    image = ImageObject.create(image_path)
    image.exposure_correction = exposure_correction
    return image


def _read_existing_csv(csv_path: str) -> dict[str, CsvRow]:
    """
    Loads a prior run's CSV into a dict keyed by filename, so this run can
    update just the rows it touches and leave the rest as they were. Missing
    file or a header that doesn't match CSV_HEADER (e.g. an older app version)
    is treated as "no prior data" rather than migrated or merged column-wise.
    """
    if not os.path.isfile(long_path(csv_path)):
        return {}
    with open(long_path(csv_path), newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header != CSV_HEADER:
            logger.warning("%s: header does not match CSV_HEADER, ignoring prior contents", csv_path)
            return {}
        return {row[0]: tuple(row) for row in reader}


def _run_suffix(confidence: int, model_filename: str) -> str:
    """The confidence+model fragment shared by detections_csv_name() and settings_json_name()."""
    return f"conf-{confidence}-{strip_model_ext(model_filename or '')}"


def detections_csv_name(confidence: int, model_filename: str) -> str:
    """
    The name of a Batch Run's detections CSV file, encoding the confidence
    level and the model used (like:
    detectorist-detections-conf-75-fish-seg-transformer-2026-02-24.csv).
    Every run shares the same output directory, so this is what keeps runs
    with different settings from overwriting each other's CSV. A re-run with
    the same confidence and model overwrites its own prior CSV instead.
    """
    return f"detectorist-detections-{_run_suffix(confidence, model_filename)}.csv"


def settings_json_name(confidence: int, model_filename: str) -> str:
    """
    The name of the settings snapshot exported alongside a Batch Run's CSV,
    encoding the same confidence level and model (like:
    detectorist-settings-conf-75-fish-seg-transformer-2026-02-24.json), so the
    two files pair up at a glance and a re-run overwrites its own prior copy.
    """
    return f"detectorist-settings-{_run_suffix(confidence, model_filename)}.json"


def run_batch(image_paths: list[str], detector, confidence: float, exposure_correction: bool,
              output_dir: str, csv_filename: str, action: BatchAction, progress: ProgressFn) -> BatchResult:
    """
    Runs the detector over the given images, delegating each one to the action
    and updating csv_filename in the output directory with a row per image.

    A filename already present in csv_filename from a prior run keeps its row
    unless this run processes that same image again, in which case the row is
    replaced. Filenames untouched by this run are left as they were. This
    lets the CSV reflect the latest known state across repeated runs even
    though the underlying image files themselves get overwritten.

    While an image runs detection and the action, the next image is already
    decoding on a background thread (pillow-heif and ONNX both release the
    GIL, so the overlap is real). The lookahead is one image deep because each
    decoded image can occupy hundreds of MB.

    An image whose load fails is skipped with a "load-error" row instead of
    aborting the run, so one corrupt file cannot end a batch of thousands.

    Args:
        image_paths: Full paths of the images to process.
        detector: Anything with detect(image) -> list of detections.
        confidence: Minimum score a detection must have to be kept.
        exposure_correction: Apply the camera exposure bias when loading images.
        output_dir: Created if missing. Shared across runs. Receives the
            action's output alongside csv_filename.
        csv_filename: Name of the CSV written into output_dir (see detections_csv_name()).
        action: The per-image behaviour (e.g. CropExportAction, SortByClassAction).
        progress: Called before each image. Returning False cancels the run.

    Returns:
        A BatchResult with the output directory, whether the run was cancelled,
        and the rows this run produced (not the full merged CSV contents).
    """
    os.makedirs(long_path(output_dir), exist_ok=True)
    action.prepare(output_dir)

    total = len(image_paths)
    rows: list[CsvRow] = []
    cancelled = False

    detections_csv_path = os.path.join(output_dir, csv_filename)
    rows_by_filename = _read_existing_csv(detections_csv_path)

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
                    row = (file_name, 0, "load-error", 0, "n/a")
                    rows.append(row)
                    rows_by_filename[file_name] = row
                    continue

                detections = [d for d in detector.detect(image) if d.score >= confidence]

                row = action.process(image, detections)
                if row:
                    rows.append(row)
                    rows_by_filename[row[0]] = row
    finally:
        with open(long_path(detections_csv_path), "w", newline="") as csv_file:
            csv_writer = csv.writer(csv_file)
            csv_writer.writerow(CSV_HEADER)
            csv_writer.writerows(rows_by_filename.values())

    return BatchResult(output_dir=output_dir, cancelled=cancelled, rows=rows)


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

    def process(self, image: ImageObject, detections: list[Detection]) -> CsvRow:
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

    def process(self, image: ImageObject, detections: list[Detection]) -> CsvRow:
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
