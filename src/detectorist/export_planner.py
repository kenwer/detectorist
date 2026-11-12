"""Plans the files an export writes: the crop rectangles and the file names.

Qt-free, so the crop bands, the export and the export dialog preview
share one rule, and the preview cannot drift from what the export writes.
Ranks are counted 1 family, 2 genus, 3 species.
"""

import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, NamedTuple

from .classifier import identified_ranks
from .structures import Box, Detection, RankedName, SettingEnum, Taxonomy

# A crop rectangle as (x, y, w, h) in image pixel space.
Rect = tuple[int, int, int, int]

RANK_COUNT = 3  # family, genus, species
UNIDENTIFIED = "unidentified"  # stands in for the ranks below the taxon confidence
NO_DETECTION = "no-detection"  # prefix of an image without detections

_UNSAFE_CHARS = str.maketrans(dict.fromkeys('<>:"/\\|?*', "_"))

PrefixPart = Literal["class", "taxa"]
# How the Export preview spells out each part of a file name prefix
_PLACEHOLDERS: dict[PrefixPart, str] = {"class": "<Class>", "taxa": "<Family>_<Genus>_<Species>"}


class CropMode(SettingEnum):
    MOST_CONFIDENT_DETECTION = "most_confident"  # box of the detection with the highest detection score
    MOST_CENTERED = "most_centered"    # box of the detection closest to the image center
    EACH_OBJECT = "each_object"  # one crop per detection
    BEST_CLASSIFICATION = "best_classification"  # box of the detection named to the deepest rank (see _classification_quality)


@dataclass(frozen=True)
class CropSettings:
    """What the user chose in the crop panel, independent of any widget."""

    mode: CropMode
    padding: float  # fraction of the detection box, e.g. 0.1 for 10%
    aspect: tuple[int, int] | Literal["detection_frame", "source_image"]
    taxon_confidence: float = 0.0  # score a rank needs to count as identified


class PlannedFile(NamedTuple):
    """A file exporting an image writes."""

    rect: Rect | None  # the crop, or None for a copy of the whole image
    name: str


@dataclass(frozen=True)
class ExportOptions:
    """How an export crops, names and skips the images."""

    crop_settings: CropSettings
    # The defaults are also the Export dialog's first choices, see Settings
    crop: bool = True  # False copies each image whole
    prefix_class: bool = False  # names start with the detected class
    prefix_taxa: bool = True  # then with the identified ranks, see taxon_prefix. Without a classifier, the class.
    has_classifier: bool = False  # whether a classifier names the detections, which taxa and skip_unidentified take
    skip_no_detection: bool = False  # plan nothing for an image without detections
    skip_unidentified: bool = False  # also leave out unidentified detections, see _skips_unidentified

    def plan(self, file_name: str, detections: list[Detection], image_height: int, image_width: int,
             taxonomy_by_box: Mapping[Box, Taxonomy]) -> list[PlannedFile]:
        """
        The files exporting one image writes.

        A crop is named <prefix>_<stem>_crop<ext>, numbered _crop_<i> when the
        image yields several (the EACH_OBJECT crop mode). Without crop, or
        without a usable crop rectangle, the whole image is copied once as
        <prefix>_<stem><ext>, named by the detection the crop mode would crop,
        or the top score where the mode crops each object or no box has an area.

        The prefix is the class, then the taxa, as far as prefix_class and
        prefix_taxa ask for them. Without a classifier the class stands in for
        the taxa, so the files still sort by what they show. A
        detection missing from taxonomy_by_box, because the classifier failed,
        is "unidentified". An image without detections is "no-detection".

        With skip_no_detection, an image without detections plans no file.
        With skip_unidentified as well, and a classifier, only the detections
        identified to family at the taxon confidence count, so the crop mode
        picks among them, and an image without one plans no file either.
        """
        if self._skips_unidentified():
            detections = [d for d in detections if self._identified(taxonomy_by_box.get(d.box))]
        if self.skip_no_detection and not detections:
            return []
        stem, ext = os.path.splitext(file_name)

        def part_name(part: PrefixPart, detection: Detection) -> str:
            if part == "class":
                return safe_name(detection.class_name)
            taxonomy = taxonomy_by_box.get(detection.box)
            if taxonomy is None:
                return UNIDENTIFIED
            return taxon_prefix(identified_ranks(taxonomy, self.crop_settings.taxon_confidence))

        def name(detection: Detection | None, suffix: str) -> str:
            if detection is None:
                prefix = [NO_DETECTION] if self.prefix_class or self.prefix_taxa else []
            else:
                prefix = [part_name(part, detection) for part in self._prefix_parts()]
            return f"{'_'.join([*prefix, stem])}{suffix}{ext}"

        targets = _plan_crop_targets(detections, image_height, image_width, self.crop_settings, taxonomy_by_box)
        if self.crop and targets:
            return [PlannedFile(rect, name(detection, f"_crop_{i}" if len(targets) > 1 else "_crop"))
                    for i, (rect, detection) in enumerate(targets)]
        if not detections:
            named = None
        elif self.crop_settings.mode is CropMode.EACH_OBJECT or not targets:
            named = max(detections, key=lambda d: d.score)
        else:
            _, named = targets[0]
        return [PlannedFile(None, name(named, ""))]

    def name_scheme(self, ext: str) -> str:
        """The names plan() gives, with placeholders for the parts that vary, for the Export preview."""
        prefix = [_PLACEHOLDERS[part] for part in self._prefix_parts()]
        # Several crops of one image are numbered, a single crop is not
        return f"{'_'.join([*prefix, '<Filename>'])}{'_crop[_<n>]' if self.crop else ''}{ext}"

    def _identified(self, taxonomy: Taxonomy | None) -> bool:
        """Whether the classifier named a detection to at least its family, see identified_ranks."""
        return taxonomy is not None and bool(identified_ranks(taxonomy, self.crop_settings.taxon_confidence))

    def _skips_unidentified(self) -> bool:
        """
        Whether plan() leaves out unidentified detections. An image without
        detections has none identified either, so this takes skip_no_detection,
        and a classifier to identify them.
        """
        return self.skip_no_detection and self.skip_unidentified and self.has_classifier

    def _taxa_apply(self) -> bool:
        """Whether names hold taxa, which takes a classifier."""
        return self.prefix_taxa and self.has_classifier

    def _prefix_parts(self) -> list[PrefixPart]:
        """What the name of a detection starts with (see plan), shared with name_scheme() so the two agree."""
        taxa = self._taxa_apply()
        parts: list[PrefixPart] = []
        if self.prefix_class or (self.prefix_taxa and not taxa):
            parts.append("class")
        if taxa:
            parts.append("taxa")
        return parts


def plan_crops(detections: list[Detection], image_height: int, image_width: int, settings: CropSettings,
               taxonomy_by_box: Mapping[Box, Taxonomy] = MappingProxyType({})) -> list[Rect]:
    """
    Plans the crop rectangles the crop mode frames.

    Args:
        detections: The detections to frame. Only the box and score are read.
        image_height: The height of the image.
        image_width: The width of the image.
        settings: Crop mode, padding, aspect ratio and taxon confidence to apply.
        taxonomy_by_box: What the classifier named the detections, read by
            BEST_CLASSIFICATION only. Detections missing here count as unidentified.
    """
    return [rect for rect, _ in _plan_crop_targets(detections, image_height, image_width, settings, taxonomy_by_box)]


def safe_name(name: str) -> str:
    """Make a class or taxon name usable in a file name on Windows."""
    return name.translate(_UNSAFE_CHARS).rstrip(". ") or "_"


def taxon_prefix(ranks: Sequence[RankedName]) -> str:
    """
    The file name prefix of a classified detection: its identified ranks
    (see identified_ranks), then "unidentified" for the ranks it missed,
    like "Pomacentridae_Amphiprion_unidentified".
    """
    names = [r.name for r in ranks]
    # The model names species Genus_species, so the genus is already in the species name
    if len(names) == RANK_COUNT:
        return f"{safe_name(names[0])}_{safe_name(names[2])}"
    return "_".join([*(safe_name(n) for n in names), UNIDENTIFIED])


def _plan_crop_targets(detections: list[Detection], image_height: int, image_width: int, settings: CropSettings,
                       taxonomy_by_box: Mapping[Box, Taxonomy]) -> list[tuple[Rect, Detection]]:
    """The crop rectangles the crop mode frames, each with the detection it frames. See plan_crops."""
    # A box without area cannot be framed and would divide by zero in the aspect fit
    detections = [d for d in detections if d.box[2] > 0 and d.box[3] > 0]
    if not detections:
        return []
    chosen = _detections_to_frame(detections, image_height, image_width, settings, taxonomy_by_box)
    return [(_frame(d.box, image_height, image_width, settings.padding, settings.aspect), d) for d in chosen]


def _detections_to_frame(detections: list[Detection], image_height: int, image_width: int, settings: CropSettings,
                         taxonomy_by_box: Mapping[Box, Taxonomy]) -> list[Detection]:
    """The detections the crop mode frames, one per crop."""
    match settings.mode:
        case CropMode.EACH_OBJECT:
            return list(detections)
        case CropMode.MOST_CONFIDENT_DETECTION:
            chosen = max(detections, key=lambda d: d.score)
        case CropMode.MOST_CENTERED:
            def distance_to_center(d: Detection) -> float:
                x, y, w, h = d.box
                return math.hypot(x + w / 2 - image_width / 2, y + h / 2 - image_height / 2)
            chosen = min(detections, key=distance_to_center)
        case CropMode.BEST_CLASSIFICATION:
            chosen = max(detections, key=lambda d: _classification_quality(d, taxonomy_by_box.get(d.box), settings.taxon_confidence))
    return [chosen]


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


def _frame(box: Box, image_height: int, image_width: int, padding: float, aspect_ratio: tuple[int, int] | str) -> Rect:
    """
    Pads the box by the padding fraction of its size on each side, widens or
    heightens it to the aspect ratio, and shrinks and moves the result to fit
    the image, keeping its center while it fits. The box must have an area.
    """
    x, y, w, h = box
    padding_x, padding_y = int(w * padding), int(h * padding)

    if aspect_ratio == "source_image":
        ratio_w, ratio_h = image_width, image_height
    elif isinstance(aspect_ratio, str):
        ratio_w, ratio_h = w, h
    else:
        ratio_w, ratio_h = aspect_ratio
    target_ratio = ratio_w / ratio_h

    x, y, w, h = x - padding_x, y - padding_y, w + 2 * padding_x, h + 2 * padding_y
    if w / h > target_ratio:
        new_h = int(w / target_ratio)
        y -= (new_h - h) // 2
        h = new_h
    else:
        new_w = int(h * target_ratio)
        x -= (new_w - w) // 2
        w = new_w

    scale = min(1.0, image_width / w, image_height / h)
    if scale < 1.0:
        new_w, new_h = int(w * scale), int(h * scale)
        x += (w - new_w) // 2
        y += (h - new_h) // 2
        w, h = new_w, new_h

    return min(max(x, 0), image_width - w), min(max(y, 0), image_height - h), w, h
