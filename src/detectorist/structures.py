from enum import Enum
from typing import NamedTuple

import numpy as np


class ImageMode(Enum):
    """
    Represents the color mode of an image.
    """
    RGB = "RGB"
    RGBA = "RGBA"
    BGR = "BGR"
    BGRA = "BGRA"
    GRAY = "GRAY"
    PALETTE = "P"


class Detection(NamedTuple):
    """
    One object the model found in an image.

    A NamedTuple so existing tuple indexing and unpacking keep working.
    The mask is only set by segmentation models: a uint8 array (0 or 255)
    at model input resolution, scaled by the display layer.
    """
    box: tuple[int, int, int, int]  # (x, y, w, h) in image pixel space
    score: float
    class_name: str
    mask: np.ndarray | None = None
