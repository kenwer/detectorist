"""Pure geometry for planning crop rectangles from detections.

The crop planner is deliberately Qt-free: its interface is plain tuples plus
CropSettings, so both callers (the interactive crop bands and the batch
crop/export loop) and tests exercise the same seam headless.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

# A crop rectangle as (x, y, w, h) in image pixel space.
Rect = tuple[int, int, int, int]


class CropMode(StrEnum):
    TOP_CONFIDENCE = "top_confidence"  # box of the highest-confidence detection
    UNION = "union"                    # one box framing all detections
    MOST_CENTERED = "most_centered"    # box of the detection closest to the image center
    EACH_OBJECT = "all_detected_objects"  # one crop per detection

    @classmethod
    def from_setting(cls, value: str | None) -> "CropMode | None":
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
    aspect: tuple[int, int] | Literal["detection_frame"]


def plan_crops(detections: list, image_height: int, image_width: int, settings: CropSettings) -> list[Rect]:
    """
    Plans crop rectangles based on detections and crop settings.

    Args:
        detections: A list of detections, where each detection is a tuple
            ((x, y, w, h), score, class_name). Only the box and score are read.
        image_height: The height of the image.
        image_width: The width of the image.
        settings: Crop mode, padding and aspect ratio to apply.

    Returns:
        A list of tuples (x, y, w, h) for the crop rectangles.
    """
    if not detections:
        return []

    if settings.mode == CropMode.EACH_OBJECT:  # We might have more than one crop rectangle
        crop_rects = []
        # Treat each detection individually with TOP_CONFIDENCE
        for detection in detections:
            rect = _plan_single_crop([detection], image_height, image_width, CropMode.TOP_CONFIDENCE, settings.padding, settings.aspect)
            if rect:
                crop_rects.append(rect)
        return crop_rects
    else:  # Just a single crop rectangle
        rect = _plan_single_crop(detections, image_height, image_width, settings.mode, settings.padding, settings.aspect)
        return [rect] if rect else []


def _plan_single_crop(detections: list, image_height: int, image_width: int, mode: CropMode, padding_percentage: float, aspect_ratio: tuple[int, int] | str) -> Rect | None:
    """
    Calculates a single crop rectangle based on detections and parameters.

    Returns:
        A tuple (x, y, w, h) for the crop rectangle, or None if no rectangle could be calculated.
    """
    if not detections:
        return None

    # The detection boxes are tuples of (x, y, w, h)
    if mode == CropMode.TOP_CONFIDENCE:
        top_detection = max(detections, key=lambda d: d[1])
        x, y, w, h = top_detection[0]
    elif mode == CropMode.UNION:
        left = min(d[0][0] for d in detections)
        top = min(d[0][1] for d in detections)
        right = max(d[0][0] + d[0][2] for d in detections)
        bottom = max(d[0][1] + d[0][3] for d in detections)
        x, y, w, h = left, top, right - left, bottom - top
    elif mode == CropMode.MOST_CENTERED:
        image_center_x = image_width / 2
        image_center_y = image_height / 2

        min_distance = float('inf')
        most_centered_detection = None

        # Iterate through each detected object to find the one closest to the image center
        for detection in detections:
            # Bounding box coordinates and dimensions for the current detection
            det_x, det_y, det_w, det_h = detection[0]
            # Calculate the center coordinates of the current detection's bounding box
            det_center_x = det_x + det_w / 2
            det_center_y = det_y + det_h / 2

            # Euclidean distance between the detection's center and the image's center
            distance = ((det_center_x - image_center_x)**2 + (det_center_y - image_center_y)**2)**0.5

            # If this detection is closer to the image center than previous ones, update
            if distance < min_distance:
                min_distance = distance
                most_centered_detection = detection

        # If a most centered detection was found, use its bounding box for cropping
        if most_centered_detection:
            x, y, w, h = most_centered_detection[0]
        else:
            return None # No centered detection found
    else:
        raise ValueError(f"invalid crop mode for _plan_single_crop: {mode}")

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

    # Handle aspect ratio for "detection_frame"
    if isinstance(aspect_ratio, str):
        if detection_w > 0 and detection_h > 0:
            final_aspect_ratio = (detection_w, detection_h)
        else:
            final_aspect_ratio = (1, 1)  # Fallback to square if detection has zero area
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
