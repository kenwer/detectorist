"""Timing harness for the ImageObject conversion hot paths.

Run with: uv run poe bench

Measures the 8-bit conversion pipeline (display and ONNX preprocessing)
on synthetic images sized like a 33 MP camera frame, across the source
formats the app actually loads: 16-bit RGB (RAW/HEIF), 16-bit BGR
(16-bit PNG via OpenCV), 8-bit BGR (JPEG), and 8-bit grayscale.

Prints a fixed-format table so runs can be diffed to detect regressions.
"""

import statistics
import sys
import timeit
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from detectorist.image_object import ImageObject  # noqa: E402
from detectorist.structures import ImageMode  # noqa: E402

# Sized like a 33 MP camera frame (7000x4700), the workload the cache
# comments in image_cache.py are written around.
HEIGHT, WIDTH = 4700, 7000
DETR_INPUT = 504  # RF-DETR "Large" model input resolution
REPEATS = 7


class SyntheticImage(ImageObject):
    """In-memory ImageObject that skips file I/O but keeps the production
    conversion code paths. __init__ is bypassed because the base class
    requires an existing file."""

    def __init__(self, data: np.ndarray, mode: ImageMode, bpc: int):
        self._image_path = f"<synthetic {mode.value} {bpc}bit>"
        self._image_data = data
        self._original_bpc = bpc
        self._mode = mode
        self._file_extension = ".synthetic"
        self._exif_dict = {}
        self._exposure_correction = False

    def save_cropped(self, rect, output_path):
        raise NotImplementedError("benchmark images are never saved")


def make_image(mode: ImageMode, bpc: int) -> SyntheticImage:
    channels = {"GRAY": None, "RGBA": 4, "BGRA": 4}.get(mode.name, 3)
    shape = (HEIGHT, WIDTH) if channels is None else (HEIGHT, WIDTH, channels)
    rng = np.random.default_rng(seed=42)
    if bpc > 8:
        data = rng.integers(0, 2**16, size=shape, dtype=np.uint16)
    else:
        data = rng.integers(0, 2**8, size=shape, dtype=np.uint8)
    return SyntheticImage(data, mode, bpc)


def bench(label: str, fn) -> None:
    times = timeit.repeat(fn, number=1, repeat=REPEATS)
    median_ms = statistics.median(times) * 1000
    min_ms = min(times) * 1000
    print(f"{label:<44} median {median_ms:9.1f} ms   min {min_ms:9.1f} ms")


def main() -> None:
    cases = [
        (ImageMode.RGB, 16),  # RAW / HEIF
        (ImageMode.BGR, 16),  # 16-bit PNG via OpenCV
        (ImageMode.BGR, 8),   # JPEG
        (ImageMode.GRAY, 8),
    ]
    print(f"image size: {WIDTH}x{HEIGHT} ({WIDTH * HEIGHT / 1e6:.0f} MP), "
          f"repeats: {REPEATS}, numpy {np.__version__}")
    for mode, bpc in cases:
        image = make_image(mode, bpc)
        tag = f"{mode.value}/{bpc}bit"
        bench(f"{tag} image_data_bgr_8bit", lambda: image.image_data_bgr_8bit)
        bench(f"{tag} image_data_rgb_8bit", lambda: image.image_data_rgb_8bit)
        bench(f"{tag} image_data_rgb_8bit_display", lambda: image.image_data_rgb_8bit_display)
        bench(f"{tag} preprocess_for_onnx_detr", lambda: image.preprocess_for_onnx_detr(DETR_INPUT, DETR_INPUT))


if __name__ == "__main__":
    main()
