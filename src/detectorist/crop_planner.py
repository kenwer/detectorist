"""Pure geometry for planning crop rectangles from detections.

The crop planner is deliberately Qt-free: its interface is plain tuples plus
CropSettings, so both callers (the interactive crop bands and the batch
crop/export loop) and tests exercise the same seam headless.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from .classifier import identified_ranks
from .structures import Box, Detection, Taxonomy

# A crop rectangle as (x, y, w, h) in image pixel space.
Rect = tuple[int, int, int, int]


class CropMode(StrEnum):
    MOST_CONFIDENT_DETECTION = "top_confidence"  # box of the detection with the highest detection score
    UNION = "union"                    # one box framing all detections
    MOST_CENTERED = "most_centered"    # box of the detection closest to the image center
    EACH_OBJECT = "all_detected_objects"  # one crop per detection
    BEST_CLASSIFICATION = "best_classification"  # box of the detection named to the deepest rank (see _classification_quality)

    @classmethod
    def from_setting(cls, value: str | None) -> CropMode | None:
        """Parse a persisted mode name, or None if missing/unknown."""
        if value == "largest_area":  # persisted name before the UNION rename
            return cls.UNION
        if value is None:
            return None
        try:
            return cls(value)
        except ValueError:
            return None


@dataclass(frozen=True)
class CropSettings:
    """What the user chose in the crop panel, independent of any widget."""

    mode: CropMode
    padding: float  # fraction of the detection box, e.g. 0.1 for 10%
    aspect: tuple[int, int] | Literal["detection_frame", "source_image"]
    taxon_confidence: float = 0.0  # score a rank needs to count as identified


def plan_crops(detections: list[Detection], image_height: int, image_width: int, settings: CropSettings,
               taxonomy_by_box: Mapping[Box, Taxonomy] = {}) -> list[Rect]:
    """
    Plans crop rectangles based on detections and crop settings.

    Args:
        detections: The detections to frame. Only the box and score are read.
        image_height: The height of the image.
        image_width: The width of the image.
        settings: Crop mode, padding, aspect ratio and taxon confidence to apply.
        taxonomy_by_box: What the classifier named the detections, read by
            BEST_CLASSIFICATION only. Detections missing here count as unidentified.

    Returns:
        A list of tuples (x, y, w, h) for the crop rectangles.
    """
    # A box without area cannot be framed and would divide by zero in the aspect fit
    detections = [d for d in detections if d.box[2] > 0 and d.box[3] > 0]
    if not detections:
        return []
    boxes = _boxes_to_frame(detections, image_height, image_width, settings, taxonomy_by_box)
    return [_frame(box, image_height, image_width, settings.padding, settings.aspect) for box in boxes]


def _boxes_to_frame(detections: list[Detection], image_height: int, image_width: int, settings: CropSettings,
                    taxonomy_by_box: Mapping[Box, Taxonomy]) -> list[Box]:
    """The boxes the crop mode frames, one per crop."""
    match settings.mode:
        case CropMode.EACH_OBJECT:
            return [d.box for d in detections]
        case CropMode.UNION:
            left = min(d.box[0] for d in detections)
            top = min(d.box[1] for d in detections)
            right = max(d.box[0] + d.box[2] for d in detections)
            bottom = max(d.box[1] + d.box[3] for d in detections)
            return [(left, top, right - left, bottom - top)]
        case CropMode.MOST_CONFIDENT_DETECTION:
            return [max(detections, key=lambda d: d.score).box]
        case CropMode.MOST_CENTERED:
            def distance_to_center(d: Detection) -> float:
                x, y, w, h = d.box
                return math.hypot(x + w / 2 - image_width / 2, y + h / 2 - image_height / 2)
            return [min(detections, key=distance_to_center).box]
        case CropMode.BEST_CLASSIFICATION:
            return [max(detections, key=lambda d: _classification_quality(d, taxonomy_by_box.get(d.box), settings.taxon_confidence)).box]


def _classification_quality(detection: Detection, taxonomy: Taxonomy | None, taxon_confidence: float) -> tuple[int, float, float]:
    """
    Orders detections by how well they were classified: the deepest
    identified rank first, then the score at that rank, then the detection
    score. Comparing scores across ranks would favor shallow ones, as a
    genus scores the sum of its species. A detection identified at no rank
    is ordered by its detection score alone.
    """
    ranks = identified_ranks(taxonomy, taxon_confidence) if taxonomy else []
    return len(ranks), ranks[-1].score if ranks else 0.0, detection.score


def _frame(box: Box, image_height: int, image_width: int, padding_percentage: float, aspect_ratio: tuple[int, int] | str) -> Rect:
    """
    Pads the box, widens or heightens it to the aspect ratio and fits the
    result inside the image. The box must have an area.
    """
    x, y, w, h = box
    detection_w, detection_h = w, h

    # Calculate the horizontal/vertical padding based on the width/height of the bounding box and the padding percentage
    padding_x = int(detection_w * padding_percentage)
    padding_y = int(detection_h * padding_percentage)

    # Extend the bounding box's x-coordinate to the left by `padding_x`
    x -= padding_x
    # Extend the bounding box's y-coordinate upwards by `padding_y`
    y -= padding_y
    # Increase the width of the bounding box by `2 * padding_x` (left and right)
    w += 2 * padding_x
    # Increase the height of the bounding box by `2 * padding_y` (top and bottom)
    h += 2 * padding_y

    if aspect_ratio == "source_image":
        final_aspect_ratio = (image_width, image_height)
    elif isinstance(aspect_ratio, str):
        final_aspect_ratio = (detection_w, detection_h)
    else:
        final_aspect_ratio = aspect_ratio

    ratio_w, ratio_h = final_aspect_ratio
    rect_w, rect_h = w, h

    current_ratio = rect_w / rect_h
    target_ratio = ratio_w / ratio_h

    if current_ratio > target_ratio:
        # Too wide, adjust height
        new_h = int(rect_w / target_ratio)
        diff_h = new_h - rect_h
        y -= diff_h // 2
        h = new_h
    else:
        # Too tall, adjust width
        new_w = int(rect_h * target_ratio)
        diff_w = new_w - rect_w
        x -= diff_w // 2
        w = new_w

    # Ensure the crop rectangle is within the image boundaries
    # If the crop rectangle is larger than the image, scale it down
    scale = 1.0
    if w > image_width:
        scale = image_width / w
    if h > image_height:
        scale = min(scale, image_height / h)

    if scale < 1.0:
        new_w = int(w * scale)
        new_h = int(h * scale)
        x += (w - new_w) // 2
        y += (h - new_h) // 2
        w = new_w
        h = new_h

    # If the crop rectangle is outside the image, move it
    if x < 0:
        x = 0
    if y < 0:
        y = 0
    if x + w > image_width:
        x = image_width - w
    if y + h > image_height:
        y = image_height - h

    return (x, y, w, h)
