"""Constants baked into the committed tiny ONNX models in tests/data.

The models ignore their input and return these values, so Detector tests can
assert exact results. scripts/make_test_models.py imports this module from a
throwaway environment that has no detectorist installed, so it must not
import anything from the project.

Each model reports three detections, deliberately not in score order, so
tests can tell whether Detector sorts them. Detection models name their
classes from index 1 (index 0 is background). Segmentation models start at 0.
"""

from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DETECT_MODEL = DATA_DIR / "tiny-detect.onnx"
SEG_MODEL = DATA_DIR / "tiny-seg.onnx"
CLASSIFY_MODEL = DATA_DIR / "tiny-classify.onnx"

INPUT_SIZE = 32
MASK_SIZE = 8

# Normalized (cx, cy, w, h). Every value is a multiple of 1/8, which float32
# represents exactly, so the pixel boxes the tests expect have no rounding
# ambiguity.
BOXES = [
    [0.25, 0.25, 0.5, 0.5],
    [0.5, 0.5, 0.25, 0.5],
    [0.75, 0.75, 0.25, 0.25],
]

DETECT_CLASS_NAMES = {1: "Fish", 2: "Crab"}
DETECT_LOGITS = [
    [-10.0, -3.0, 0.0],
    [-10.0, 2.0, -3.0],
    [-10.0, -2.0, -4.0],
]

SEG_CLASS_NAMES = {0: "Fish", 1: "Crab"}
SEG_LOGITS = [
    [-3.0, 0.0],
    [2.0, -3.0],
    [-2.0, -4.0],
]

MASK_LOGIT = 8.0


def mask_logits() -> list[list[list[float]]]:
    """Mask logits per detection, in model output order: left half, top half, and empty."""
    masks = [[[-MASK_LOGIT] * MASK_SIZE for _ in range(MASK_SIZE)] for _ in BOXES]
    half = MASK_SIZE // 2
    for row in range(MASK_SIZE):
        for col in range(MASK_SIZE):
            if col < half:
                masks[0][row][col] = MASK_LOGIT
            if row < half:
                masks[1][row][col] = MASK_LOGIT
    return masks


# The classifier does depend on its input, unlike the detectors above: it
# averages each colour channel of a crop and scores the species from those
# three numbers. A red crop gives species 0, a green one species 1, a blue one
# species 2 and a dark one species 3, so a test can tell which crop produced
# which answer.
CLASSIFY_SIZE = 16
CLASSIFY_MARGIN = 0.05
CLASSIFY_FILL = "crop-mean"
CLASSIFY_SPECIES = {
    0: "Amphiprion_ocellaris",
    1: "Amphiprion_clarkii",
    2: "Halichoeres_hortulanus",
    3: "Halichoeres_marginatus",
}
CLASSIFY_GENERA = ["Amphiprion", "Halichoeres"]
CLASSIFY_FAMILIES = ["Pomacentridae", "Labridae"]
CLASSIFY_GENUS_OF = [0, 0, 1, 1]
CLASSIFY_FAMILY_OF = [0, 0, 1, 1]
# Rows are the red, green and blue channel means, columns the species.
CLASSIFY_WEIGHTS = [
    [8.0, 0.0, 0.0, 0.0],
    [0.0, 8.0, 0.0, 0.0],
    [0.0, 0.0, 8.0, 0.0],
]
CLASSIFY_BIAS = [0.0, 0.0, 0.0, 2.0]
