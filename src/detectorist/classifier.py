"""The species classifier: names the family, genus and species of a detection.

A second stage behind the Detector. Each detection box is cut from the image
the way the model's training crops were cut, and the model returns one
probability per species. Qt-free so it can be exercised headless.

The framing (classification_window, letterbox) reproduces window and
letterbox of species_probe.py in the rf-detr-training repository. A
difference would cost accuracy without raising an error, so both are pure
functions tested against values from that code.
"""

import ast
import fnmatch
import json
import math
from collections.abc import Sequence
from itertools import takewhile

import numpy as np
import onnxruntime as ort
from PIL import Image

from .image_object import ImageObject
from .structures import Box, Detection, RankedName, Taxonomy, clamp_box
from .utils import load_model_bytes

# Most boxes of one image the classifier is run on. A detection confidence slider pulled
# to the bottom displays every query of the detector, a few hundred boxes.
MAX_CLASSIFIED_BOXES = 20


def class_matches(patterns: Sequence[str], class_name: str) -> bool:
    """
    Whether a detection class is one a classifier names, given the
    classifier's "classifies" patterns from the manifest. The patterns are
    shell-style globs ("Fish*", "*") and match case sensitively on every
    platform.
    """
    return any(fnmatch.fnmatchcase(class_name, pattern) for pattern in patterns)


def detections_to_classify(detections: list[Detection], min_detection_score: float, patterns: Sequence[str]) -> list[Detection]:
    """
    The detections at or above min_detection_score whose class the classifier names,
    at most MAX_CLASSIFIED_BOXES of them, the highest score first.
    """
    ranked = sorted(detections, key=lambda d: d.score, reverse=True)
    return [d for d in ranked if d.score >= min_detection_score and class_matches(patterns, d.class_name)][:MAX_CLASSIFIED_BOXES]


def identified_ranks(taxonomy: Taxonomy, threshold: float) -> list[RankedName]:
    """
    The ranks of a taxonomy scoring at least the threshold, from the family
    down. Stopping at the first rank below the threshold keeps a name from
    showing without the ranks above it.
    """
    return list(takewhile(lambda rank: rank.score >= threshold, taxonomy))


def describe(taxonomy: Taxonomy, threshold: float) -> str:
    """
    A taxonomy as one line of tooltip text: the family, the deepest
    identified rank below it and that rank's score (see identified_ranks),
    e.g. "Pomacentridae · A. ocellaris 0.44". A species carries its genus
    as the initial, as in scientific writing. "Unidentified" if no rank is
    identified.
    """
    ranks = identified_ranks(taxonomy, threshold)
    if not ranks:
        return "Unidentified"
    names = [display_name(ranks[0].name)]
    if len(ranks) > 1:
        names.append(short_name(ranks[-1].name))
    return f"{' · '.join(names)} {ranks[-1].score:.2f}"


def short_name(name: str) -> str:
    """
    A taxon name with a species' genus cut to its initial, as in scientific
    writing, e.g. "A. ocellaris" for "Amphiprion_ocellaris". A genus or
    family has no "_", so it comes out unabbreviated.
    """
    genus, _, epithet = name.partition("_")
    return f"{genus[:1]}. {display_name(epithet)}" if epithet else display_name(genus)


def display_name(name: str) -> str:
    """A taxon name as shown to the user, e.g. "Bombus terrestris" for the model's "Bombus_terrestris"."""
    return name.replace("_", " ")


def classification_window(box: Box, image_width: int, image_height: int, margin: float) -> tuple[int, int, int, int]:
    """
    The part of the image to show the classifier for one detection.

    A square around the box: its long side plus margin (a fraction of that
    side) per end, moved back inside the image where it would leave it.
    Where the image is smaller than the square on an axis, the whole axis is
    used and the result is not square.

    Returns:
        (x1, y1, x2, y2) in image pixels, x2 and y2 exclusive.
    """
    # The training boxes never left the image
    x1, y1, x2, y2 = clamp_box(box, image_width, image_height)

    # Kept in this exact form: the training code computes it the same way, and
    # its floating point result decides the rounding below
    side = max(x2 - x1, y2 - y1) * (1 + 2 * margin)
    spans = []
    for low, high, limit in ((x1, x2, image_width), (y1, y2, image_height)):
        span = min(side, limit)
        start = min(max((low + high - span) / 2, 0.0), limit - span)
        first = min(math.floor(start), limit - 1)
        spans.append((first, min(limit, max(first + 1, math.ceil(start + span)))))
    return spans[0][0], spans[1][0], spans[0][1], spans[1][1]


def letterbox(rgb: np.ndarray, size: int) -> np.ndarray:
    """
    Resize an 8-bit RGB crop so its long side is size, centred on a
    size x size canvas of the crop's mean colour.

    The mean is computed as letterbox of species_probe.py computes it (a half
    rounds to even).

    Never stretched: body depth relative to length is a diagnostic trait.
    Pillow does the resize because training used it. Its bicubic filter
    widens when shrinking, which OpenCV's does not, and a large fish shrunk
    without that looks different to the model.
    """
    fill = [int(v) for v in np.rint(np.asarray(rgb, dtype=np.float64).reshape(-1, 3).mean(axis=0))]
    image = Image.fromarray(np.ascontiguousarray(rgb))
    scale = size / max(image.size)
    width = max(1, round(image.width * scale))
    height = max(1, round(image.height * scale))
    canvas = Image.new("RGB", (size, size), tuple(fill))
    canvas.paste(image.resize((width, height), Image.Resampling.BICUBIC), ((size - width) // 2, (size - height) // 2))
    return np.asarray(canvas)


def roll_up(probs: np.ndarray, species: Sequence[str], genera: Sequence[str], families: Sequence[str],
            genus_of: np.ndarray, family_of: np.ndarray) -> Taxonomy:
    """
    Species probabilities of one detection as a family, a genus and a species.

    A genus's probability is the sum of its species', a family's the sum of
    its species' too. The choice runs top-down (the best family, the best
    genus in it, the best species in that genus), so the three names never
    contradict each other. The price is that the species named is not always
    the single most probable one.

    Args:
        probs: One probability per species.
        species, genera, families: The names per rank.
        genus_of, family_of: The genus and family index of each species.
    """
    family_scores = np.bincount(family_of, weights=probs, minlength=len(families))
    family = int(family_scores.argmax())

    genus_scores = np.bincount(genus_of, weights=np.where(family_of == family, probs, 0.0), minlength=len(genera))
    genus = int(genus_scores.argmax())

    best = int(np.where(genus_of == genus, probs, -1.0).argmax())

    return Taxonomy(
        RankedName(families[family], float(family_scores[family])),
        RankedName(genera[genus], float(genus_scores[genus])),
        RankedName(species[best], float(probs[best])),
    )


class Classifier:
    """
    Species classifier using an ONNX model exported by species_export.py.

    The model takes RGB crops in 0..1 as [batch, 3, size, size] (its
    normalisation is inside the graph) and returns one probability per
    species. How to cut the crops and how species map to genera and families
    is in the model's metadata, so a retrained model brings its own framing.

    classify() may run on several threads at once (the worker and a batch
    run share one instance): it only reads the attributes, and an ONNX
    Runtime session can run concurrently.
    """

    def __init__(self, model_path: str, patterns: Sequence[str] = ("*",)):
        """
        Args:
            model_path (str): Path to the ONNX model file.
            patterns: The detection classes the classifier names, its
                "classifies" in the manifest (see class_matches).

        Raises:
            OSError: If the file cannot be loaded or is not a classifier.
        """
        try:
            self.session = ort.InferenceSession(load_model_bytes(model_path))
            metadata = self.session.get_modelmeta().custom_metadata_map
            if "classifier" not in metadata:
                raise ValueError("this is a detection model, not a classifier")
            names = ast.literal_eval(metadata["names"].strip())
            info = json.loads(metadata["classifier"])

            self.species = [names[i] for i in range(len(names))]
            self.genera = list(info["genera"])
            self.families = list(info["families"])
            self.genus_of = np.asarray(info["genus_of"], dtype=np.intp)
            self.family_of = np.asarray(info["family_of"], dtype=np.intp)
            self.size = int(info["size"])
            self.margin = float(info["margin"])
            # letterbox() fills with the crop's mean colour. A model trained with
            # another fill (e.g. the fixed colour of older models) would lose
            # accuracy without raising an error.
            if info["fill"] != "crop-mean":
                raise ValueError(f"unsupported letterbox fill {info['fill']!r}, this version only knows 'crop-mean'")
            if not len(self.species) == len(self.genus_of) == len(self.family_of):
                raise ValueError("the taxonomy does not cover every species")
        except Exception as e:
            raise OSError(f"Error loading classifier from '{model_path}': {e}") from e

        self.model_path = model_path
        self.patterns = tuple(patterns)
        self.input_name = self.session.get_inputs()[0].name

    def classify(self, image: ImageObject, boxes: Sequence[Box]) -> list[Taxonomy]:
        """
        Names what is inside each box of an image.

        The crops come from the image's uncorrected pixels, like the
        detector's input: the training crops were never exposure corrected.

        Args:
            image: The image the boxes were detected in.
            boxes: Detection boxes as (x, y, w, h) in image pixels.

        Returns:
            One Taxonomy per box, in the order given.
        """
        if not boxes:
            return []

        rgb = image.image_data_rgb_8bit
        crops = []
        for box in boxes:
            x1, y1, x2, y2 = classification_window(box, image.width, image.height, self.margin)
            crops.append(letterbox(rgb[y1:y2, x1:x2], self.size))

        pixels = np.stack(crops).astype(np.float32).transpose(0, 3, 1, 2) / 255
        probs = self.session.run(None, {self.input_name: pixels})[0]

        return [roll_up(row, self.species, self.genera, self.families, self.genus_of, self.family_of) for row in probs]
