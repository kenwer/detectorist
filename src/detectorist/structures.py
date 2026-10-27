import zlib
from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import NamedTuple, Self

import numpy as np


class SettingEnum(StrEnum):
    """A choice stored in the settings by its value."""

    @classmethod
    def from_setting(cls, value: str | None) -> Self | None:
        """Parse a persisted value, or None if missing/unknown."""
        try:
            return cls(value)
        except ValueError:
            return None


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


@dataclass(frozen=True)
class PackedMask:
    """
    A detection mask stored as bits and compressed. A segmentation model
    returns 200 masks per image, about 50 MB as uint8 arrays but about 50 KB
    packed, so the results of thousands of images fit in memory.
    """
    data: bytes
    shape: tuple[int, int]
    area: int  # number of pixels inside the mask

    @classmethod
    def pack(cls, mask: np.ndarray) -> PackedMask:
        """Packs a mask, counting pixels above 127 as inside."""
        inside = mask > 127
        return cls(zlib.compress(np.packbits(inside).tobytes(), 1), inside.shape, int(inside.sum()))

    def unpack(self) -> np.ndarray:
        """The mask as a uint8 array of 0 or 255."""
        bits = np.unpackbits(np.frombuffer(zlib.decompress(self.data), dtype=np.uint8))
        return bits[:self.shape[0] * self.shape[1]].reshape(self.shape) * np.uint8(255)

    @property
    def nbytes(self) -> int:
        return len(self.data)


class Detection(NamedTuple):
    """
    One object the model found in an image.

    A NamedTuple so existing tuple indexing and unpacking keep working.
    The mask is only set by segmentation models: packed, at model input
    resolution, scaled by the display layer.
    """
    box: Box
    score: float
    class_name: str
    mask: PackedMask | None = None


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
