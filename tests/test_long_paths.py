"""Tests that every image file access goes through utils.long_path.

On Windows a path beyond MAX_PATH only works in its extended-length form,
which long_path produces. That cannot be exercised on other platforms, so
these tests replace long_path with a mapping from a folder that does not
exist to the real one. An access that skips long_path then fails here the
same way it would for a long path on Windows.
"""

import os

import numpy as np
import piexif
import pillow_heif
import pytest
from PIL import Image

from detectorist import image_utils, utils
from detectorist.image_object import ImageObject

VIRTUAL_DIR = os.path.join(os.sep, "detectorist-virtual-long-path")
ISO = 400
EXIF = piexif.dump({"0th": {}, "Exif": {piexif.ExifIFD.ISOSpeedRatings: ISO}, "GPS": {}, "1st": {}})


@pytest.fixture
def virtual_dir(tmp_path, monkeypatch):
    """Redirects long_path from VIRTUAL_DIR to tmp_path and returns tmp_path."""
    def fake_long_path(path):
        return path.replace(VIRTUAL_DIR, str(tmp_path))

    monkeypatch.setattr(utils, "long_path", fake_long_path)
    # image_utils binds the function by name at import time
    monkeypatch.setattr(image_utils, "long_path", fake_long_path)
    return tmp_path


def write_image(real_dir, name):
    path = str(real_dir / name)
    if name.endswith(".heic"):
        pillow_heif.from_pillow(Image.new("RGB", (64, 48), (60, 70, 80))).save(path, exif=EXIF)
    elif name.endswith(".gif"):
        Image.new("P", (64, 48)).save(path)
    else:
        kwargs = {"exif": EXIF} if name.endswith(".jpg") else {}
        Image.new("RGB", (64, 48), (60, 70, 80)).save(path, **kwargs)


@pytest.mark.parametrize("name", ["a.jpg", "a.png", "a.heic", "a.gif"])
def test_image_is_loaded_and_cropped_through_long_path(virtual_dir, name):
    write_image(virtual_dir, name)
    output_name = "crop" + os.path.splitext(name)[1]

    image = ImageObject.create(os.path.join(VIRTUAL_DIR, name))
    image.save_cropped((8, 8, 32, 24), os.path.join(VIRTUAL_DIR, output_name))
    image.copy_image(VIRTUAL_DIR, "copy_" + name)

    assert (image.width, image.height) == (64, 48)
    with Image.open(virtual_dir / output_name) as crop:
        assert crop.size == (32, 24)
    assert (virtual_dir / ("copy_" + name)).is_file()


def test_jpeg_exif_is_read_and_written_through_long_path(virtual_dir):
    write_image(virtual_dir, "a.jpg")

    image = ImageObject.create(os.path.join(VIRTUAL_DIR, "a.jpg"))
    image.save_cropped((8, 8, 32, 24), os.path.join(VIRTUAL_DIR, "crop.jpg"))

    assert image.exif_data["Exif"][piexif.ExifIFD.ISOSpeedRatings] == ISO
    crop_exif = piexif.load(str(virtual_dir / "crop.jpg"))["Exif"]
    assert crop_exif[piexif.ExifIFD.ISOSpeedRatings] == ISO
    assert crop_exif[piexif.ExifIFD.PixelXDimension] == 32


def test_image_utils_roundtrip_through_long_path(virtual_dir):
    pixels = np.full((4, 6, 3), 100, dtype=np.uint8)

    image_utils.imwrite(os.path.join(VIRTUAL_DIR, "a.png"), pixels)

    np.testing.assert_array_equal(image_utils.imread(os.path.join(VIRTUAL_DIR, "a.png")), pixels)
