"""Tests for the exposure correction policy shared by the ImageObject adapters.

save_cropped is exercised end-to-end for JPEG (OpencvImageObject) and HEIF
(HeifImageObject). RAW is omitted because a proprietary .arw fixture cannot
be generated. The output files are read back through ImageObject.create, so
the same adapters that write the EXIF also verify it.
"""

import numpy as np
import piexif
import pillow_heif
from PIL import Image

from detectorist import image_utils
from detectorist.image_object import ImageObject

pillow_heif.register_heif_opener()

MINUS_ONE_EV = (-1, 1)
CROP_RECT = (8, 8, 32, 24)


def exif_bytes_with_bias(bias):
    exif_dict = {"0th": {}, "Exif": {piexif.ExifIFD.ExposureBiasValue: bias}, "GPS": {}, "1st": {}, "thumbnail": None}
    return piexif.dump(exif_dict)


def make_image(path, bias=MINUS_ONE_EV, size=(64, 48)):
    Image.new("RGB", size, color=(60, 70, 80)).save(str(path), exif=exif_bytes_with_bias(bias))
    return str(path)


def exposure_bias_of(image_path):
    exif = ImageObject.create(image_path).exif_data["Exif"]
    return exif[piexif.ExifIFD.ExposureBiasValue]


def test_corrected_jpeg_crop_resets_exposure_bias(tmp_path):
    source = make_image(tmp_path / "biased.jpg")
    output = str(tmp_path / "biased_crop.jpg")

    image = ImageObject.create(source)
    image.exposure_correction = True
    image.save_cropped(CROP_RECT, output)

    assert exposure_bias_of(output) == (0, 1)


def test_corrected_jpeg_crop_updates_exif_dimensions(tmp_path):
    source = make_image(tmp_path / "biased.jpg")
    output = str(tmp_path / "biased_crop.jpg")

    image = ImageObject.create(source)
    image.exposure_correction = True
    image.save_cropped(CROP_RECT, output)

    exif = ImageObject.create(output).exif_data["Exif"]
    assert exif[piexif.ExifIFD.PixelXDimension] == 32
    assert exif[piexif.ExifIFD.PixelYDimension] == 24


def test_corrected_jpeg_crop_brightens_underexposed_pixels(tmp_path):
    source = make_image(tmp_path / "biased.jpg")
    output = str(tmp_path / "biased_crop.jpg")

    image = ImageObject.create(source)
    image.exposure_correction = True
    image.save_cropped(CROP_RECT, output)

    # A stored bias of -1 EV means the correction applies +1 EV
    original_mean = image.image_data.mean()
    corrected_mean = ImageObject.create(output).image_data.mean()
    assert corrected_mean > original_mean + 10


def test_uncorrected_jpeg_crop_keeps_exposure_bias(tmp_path):
    source = make_image(tmp_path / "biased.jpg")
    output = str(tmp_path / "biased_crop.jpg")

    image = ImageObject.create(source)
    image.save_cropped(CROP_RECT, output)

    assert exposure_bias_of(output) == MINUS_ONE_EV


def test_corrected_heif_crop_resets_exposure_bias_and_dimensions(tmp_path):
    source = make_image(tmp_path / "biased.heic")
    output = str(tmp_path / "biased_crop.heic")

    image = ImageObject.create(source)
    image.exposure_correction = True
    image.save_cropped(CROP_RECT, output)

    exif = ImageObject.create(output).exif_data["Exif"]
    assert exif[piexif.ExifIFD.ExposureBiasValue] == (0, 1)
    assert exif[piexif.ExifIFD.PixelXDimension] == 32
    assert exif[piexif.ExifIFD.PixelYDimension] == 24


def test_uncorrected_heif_crop_keeps_exposure_bias(tmp_path):
    source = make_image(tmp_path / "biased.heic")
    output = str(tmp_path / "biased_crop.heic")

    image = ImageObject.create(source)
    image.save_cropped(CROP_RECT, output)

    assert exposure_bias_of(output) == MINUS_ONE_EV


def test_correction_policy_negates_the_stored_bias(tmp_path):
    image = ImageObject.create(make_image(tmp_path / "biased.jpg"))
    image.exposure_correction = True

    data = np.full((4, 4, 3), 100, dtype=np.uint8)
    expected = image_utils.adjust_exposure(data, 1.0, 2.2, 8)
    np.testing.assert_array_equal(image._apply_exposure_correction(data, 8), expected)


def test_correction_policy_is_a_no_op_when_disabled(tmp_path):
    image = ImageObject.create(make_image(tmp_path / "biased.jpg"))

    data = np.full((4, 4, 3), 100, dtype=np.uint8)
    np.testing.assert_array_equal(image._apply_exposure_correction(data, 8), data)
