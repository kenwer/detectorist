"""The Batch Run: one pass of a detector over a set of images.

Owns the pipeline (load, detect, filter, act, log) plus cancellation and
the detections.csv summary. Loading runs one image ahead on a background
thread so decode overlaps detection. Qt-free: progress crosses a callback
seam, and the per-image behaviour is a BatchAction adapter (Crop & Export
or Sort by Class), so the whole run can be exercised headless.
"""

import csv
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Protocol

from .crop_planner import CropSettings, plan_crops
from .image_object import ImageObject
from .utils import long_path, strip_model_ext

# Called before each image as (index, total, filename); returning False cancels the run.
ProgressFn = Callable[[int, int, str], bool]

# One detections.csv row; see CSV_HEADER for the columns.
CsvRow = tuple[str, float, str, int, str]

CSV_HEADER = ["Filename", "Highest confidence score", "Class name", "Number of detected objects", "Subdirectory"]


class BatchAction(Protocol):
    """
    Per-image behaviour of a Batch Run (e.g. CropExportAction, SortByClassAction).

    A structural interface: actions don't subclass this, they satisfy it by
    providing matching prepare() and process() methods.
    """

    def prepare(self, output_dir: str) -> None:
        """Create whatever directories the action needs inside output_dir."""
        ...

    def process(self, image: ImageObject, detections: list) -> CsvRow | None:
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


def output_dir_name(confidence: int, model_filename: str) -> str:
    """
    The name of a Batch Run's output directory, encoding the confidence level
    and the model used (like: detectorist_conf-75_fish-seg-transformer-2026-02-24).
    """
    return f"detectorist_conf-{confidence}_{strip_model_ext(model_filename or '')}"


def run_batch(image_paths: list[str], detector, confidence: float, exposure_correction: bool,
              output_dir: str, action: BatchAction, progress: ProgressFn) -> BatchResult:
    """
    Runs the detector over the given images, delegating each one to the action
    and writing a row per image to detections.csv in the output directory.

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
        output_dir: Created if missing. Receives detections.csv and the action's output.
        action: The per-image behaviour (e.g. CropExportAction, SortByClassAction).
        progress: Called before each image; returning False cancels the run.

    Returns:
        A BatchResult with the output directory, whether the run was cancelled,
        and the rows written to detections.csv.
    """
    os.makedirs(long_path(output_dir), exist_ok=True)
    action.prepare(output_dir)

    total = len(image_paths)
    rows: list[CsvRow] = []
    cancelled = False

    detections_csv_path = os.path.join(output_dir, "detections.csv")
    with open(long_path(detections_csv_path), "w", newline="") as csv_file:
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(CSV_HEADER)

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
                    print(f"Warning {file_name}: could not load image: {e}")
                    row = (file_name, 0, "load-error", 0, "")
                    csv_writer.writerow(row)
                    rows.append(row)
                    continue

                detections = [d for d in detector.detect(image) if d[1] >= confidence]

                row = action.process(image, detections)
                if row:
                    csv_writer.writerow(row)
                    rows.append(row)

    return BatchResult(output_dir=output_dir, cancelled=cancelled, rows=rows)


@dataclass
class CropExportAction:
    """
    Crops each image around its detections into cropped/. Images without
    usable detections are copied to not-cropped/.
    """

    crop_settings: CropSettings
    # Both dirs are derived from the output directory once run_batch calls
    # prepare(). Until then they are unset, so a premature process() fails
    # loudly with an AttributeError. This is by design.
    cropped_dir: str = field(init=False)
    not_cropped_dir: str = field(init=False)

    def prepare(self, output_dir: str) -> None:
        """
        Create cropped/ and not-cropped/ inside the output directory. Both are
        created eagerly so every finished run has the same folder layout, even
        when one of them stays empty.
        """
        self.cropped_dir = os.path.join(output_dir, "cropped")
        self.not_cropped_dir = os.path.join(output_dir, "not-cropped")
        os.makedirs(long_path(self.cropped_dir), exist_ok=True)
        os.makedirs(long_path(self.not_cropped_dir), exist_ok=True)

    def process(self, image: ImageObject, detections: list) -> CsvRow:
        """
        Save one crop per planned rectangle into cropped/, named
        <stem>_crop<ext>, or <stem>_crop_<i><ext> when an image yields several
        crops (the EACH_OBJECT crop mode). Images with no detections, or whose
        detections produce no usable crop rectangle, are copied unchanged to
        not-cropped/ so every input image is accounted for in the output.
        The returned row reports the top detection and the subdirectory the
        image landed in.
        """
        file_name = os.path.basename(image.image_path)
        if not detections:
            image.copy_image(self.not_cropped_dir)
            return file_name, 0, "N/A", 0, os.path.basename(self.not_cropped_dir)

        top_detection = max(detections, key=lambda d: d[1])
        confidence_score = top_detection[1]
        class_name = top_detection[2]

        crop_tuples = plan_crops(detections, image.height, image.width, self.crop_settings)

        if not crop_tuples:
            print(f"Warning {file_name}: invalid crop rectangle, crop_tuples: {crop_tuples}")
            image.copy_image(self.not_cropped_dir)
            return file_name, confidence_score, class_name, len(detections), os.path.basename(self.not_cropped_dir)

        base, ext = os.path.splitext(file_name)
        for i, crop_tuple in enumerate(crop_tuples):
            if len(crop_tuples) > 1:
                crop_name = f"{base}_crop_{i}{ext}"
            else:
                crop_name = f"{base}_crop{ext}"
            image.save_cropped(crop_tuple, os.path.join(self.cropped_dir, crop_name))

        return file_name, confidence_score, class_name, len(detections), os.path.basename(self.cropped_dir)


class SortByClassAction:
    """Copies each image into a folder named after its top detection's class."""

    def prepare(self, output_dir: str) -> None:
        """
        Only remember the output directory. Unlike CropExportAction, no
        folders are created here because their names depend on which classes
        get detected during the run.
        """
        self._output_dir = output_dir

    def process(self, image: ImageObject, detections: list) -> CsvRow:
        """
        Copy the image (never move it) into a folder named after its top
        detection's class, creating the folder on first use. Images without
        detections go to no-detection/ so every input image is accounted for
        in the output. The returned row reports the top detection and the
        folder the image landed in.
        """
        file_name = os.path.basename(image.image_path)
        if detections:
            top_detection = max(detections, key=lambda d: d[1])
            class_name = top_detection[2]
            class_dir = os.path.join(self._output_dir, class_name)
            os.makedirs(long_path(class_dir), exist_ok=True)
            image.copy_image(class_dir)
            return file_name, top_detection[1], class_name, len(detections), class_name
        else:
            no_detection_dir = os.path.join(self._output_dir, "no-detection")
            os.makedirs(long_path(no_detection_dir), exist_ok=True)
            image.copy_image(no_detection_dir)
            return file_name, 0, "no-detection", 0, "no-detection"
