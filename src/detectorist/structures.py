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


# The (x, y, w, h) of a Detection in image pixels, hashable so it can key what is known about it
Box = tuple[int, int, int, int]


def clamp_box(box: Box, image_width: int, image_height: int) -> tuple[int, int, int, int]:
    """
    The part of a box inside the image as (x1, y1, x2, y2), x2 and y2
    exclusive. The detector does not clamp its boxes, so one can reach past
    the image edge. A box entirely outside comes back with zero area.
    """
    x, y, w, h = box
    return (min(max(x, 0), image_width), min(max(y, 0), image_height),
            min(max(x + w, 0), image_width), min(max(y + h, 0), image_height))


class Detection(NamedTuple):
    """
    One object the model found in an image.

    A NamedTuple so existing tuple indexing and unpacking keep working.
    The mask is only set by segmentation models: a uint8 array (0 or 255)
    at model input resolution, scaled by the display layer.
    """
    box: Box
    score: float
    class_name: str
    mask: np.ndarray | None = None


class RankedName(NamedTuple):
    """The name a classifier chose at one taxonomic rank and its probability."""
    name: str
    score: float


class Taxonomy(NamedTuple):
    """
    What a classifier makes of one detection. The chain is consistent: the
    genus belongs to the family and the species to the genus, so the scores
    never rise going down. The species name is in the model's Genus_species
    form.
    """
    family: RankedName
    genus: RankedName
    species: RankedName
