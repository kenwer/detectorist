"""Tests for the EXIF orientation handling of JPEG images.

OpenCV decodes the stored pixel layout and ignores the EXIF Orientation tag,
so OpencvImageObject turns the data upright itself. Pillow's exif_transpose
is the reference for what "upright" means for each tag value.
"""

import numpy as np
import piexif
import pytest
from PIL import Image, ImageOps

from detectorist import image_utils
from detectorist.image_object import ImageObject

ROTATE_90_CW = 6


def make_oriented_jpeg(path, orientation):
    """
    Writes a 80x40 JPEG whose stored left half is dark and right half is
    bright, tagged with the given EXIF orientation.
    """
    pixels = np.zeros((40, 80, 3), dtype=np.uint8)
    pixels[:, 40:] = 255
    exif = piexif.dump({"0th": {piexif.ImageIFD.Orientation: orientation}, "Exif": {}, "GPS": {}, "1st": {}})
    Image.fromarray(pixels).save(str(path), exif=exif, quality=95)
    return str(path)


@pytest.mark.parametrize("orientation", range(1, 9))
def test_apply_exif_orientation_matches_pillow(orientation):
    pixels = np.random.default_rng(42).integers(0, 256, size=(4, 6, 3), dtype=np.uint8)
    reference = Image.fromarray(pixels)
    exif = reference.getexif()
    exif[0x0112] = orientation
    reference.info["exif"] = exif.tobytes()

    result = image_utils.apply_exif_orientation(pixels, orientation)

    np.testing.assert_array_equal(result, np.asarray(ImageOps.exif_transpose(reference)))


@pytest.mark.parametrize("shape", [(4, 6), (4, 6, 4)])
def test_apply_exif_orientation_handles_gray_and_alpha(shape):
    pixels = np.random.default_rng(42).integers(0, 65536, size=shape, dtype=np.uint16)

    result = image_utils.apply_exif_orientation(pixels, ROTATE_90_CW)

    np.testing.assert_array_equal(result, np.rot90(pixels, -1))


def test_portrait_jpeg_is_loaded_upright(tmp_path):
    image = ImageObject.create(make_oriented_jpeg(tmp_path / "portrait.jpg", ROTATE_90_CW))

    assert (image.width, image.height) == (40, 80)
    # A clockwise turn moves the stored dark left half to the top
    assert image.image_data[:30].mean() < 10
    assert image.image_data[50:].mean() > 245


def test_jpeg_without_orientation_is_loaded_as_stored(tmp_path):
    path = str(tmp_path / "plain.jpg")
    Image.new("RGB", (80, 40)).save(path)

    image = ImageObject.create(path)

    assert (image.width, image.height) == (80, 40)


def test_crop_of_portrait_jpeg_is_saved_upright(tmp_path):
    image = ImageObject.create(make_oriented_jpeg(tmp_path / "portrait.jpg", ROTATE_90_CW))
    output = str(tmp_path / "portrait_crop.jpg")

    # The top 20 rows of the upright image are all dark
    image.save_cropped((0, 0, 40, 20), output)

    with Image.open(output) as saved:
        assert saved.size == (40, 20)
        assert np.asarray(saved).mean() < 10
    # Orientation 1, so viewers do not rotate the upright pixels again
    assert piexif.load(output)["0th"][piexif.ImageIFD.Orientation] == 1
    # The source image keeps reporting its original orientation
    assert image.exif_data["0th"][piexif.ImageIFD.Orientation] == ROTATE_90_CW
