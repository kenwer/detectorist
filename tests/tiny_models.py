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
