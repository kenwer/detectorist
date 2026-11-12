"""Tests for the exposure correction policy shared by the ImageObject adapters.

save_cropped is exercised end-to-end for JPEG (OpencvImageObject), HEIF
(HeifImageObject) and palette PNG and GIF (PillowImageObject). RAW is omitted because a proprietary .arw fixture cannot
be generated. The output files are read back through ImageObject.create, so
the same adapters that write the EXIF also verify it.
"""

import numpy as np
import piexif
import pillow_heif
import pytest
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


def test_every_corrected_jpeg_crop_is_brightened_once_and_says_so_in_its_exif(tmp_path):
    # One image yields several crops in the "each object" crop mode
    image = ImageObject.create(make_image(tmp_path / "biased.jpg"))
    outputs = [str(tmp_path / f"biased_crop_{i}.jpg") for i in range(2)]

    for output in outputs:
        image.save_cropped(CROP_RECT, output, exposure_correction=True)

    first, second = (ImageObject.create(output) for output in outputs)
    # A stored bias of -1 EV means the correction applies +1 EV, and the source keeps its bias for the next crop
    assert second.image_data.mean() == first.image_data.mean()
    assert second.image_data.mean() > image.image_data.mean() + 10
    assert image.get_exposure_compensation() == -1.0
    # A bias of 0, so a later correction of the crop does not brighten it again
    exif = second.exif_data["Exif"]
    assert exif[piexif.ExifIFD.ExposureBiasValue] == (0, 1)
    assert (exif[piexif.ExifIFD.PixelXDimension], exif[piexif.ExifIFD.PixelYDimension]) == (32, 24)


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
    image.save_cropped(CROP_RECT, output, exposure_correction=True)

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


def make_heif(path, exif=None):
    heif = pillow_heif.from_pillow(Image.new("RGB", (64, 48), color=(60, 70, 80)))
    heif.save(str(path), exif=exif)
    return str(path)


def test_heif_without_exif_supports_exposure_correction(tmp_path):
    image = ImageObject.create(make_heif(tmp_path / "plain.heic"))
    output = str(tmp_path / "plain_crop.heic")

    # No stored bias means there is nothing to correct, not an error
    assert image.exif_data == {}
    np.testing.assert_array_equal(image.display_rgb_8bit(True), image.image_data_rgb_8bit)
    image.save_cropped(CROP_RECT, output, exposure_correction=True)
    assert ImageObject.create(output).width == 32


def test_heif_with_unreadable_exif_still_loads(tmp_path):
    image = ImageObject.create(make_heif(tmp_path / "broken.heic", exif=b"Exif\x00\x00not a tiff structure"))

    assert image.exif_data == {}
    assert image.get_exif_summary() == ""
    assert (image.width, image.height) == (64, 48)


def make_transparent_palette_image(path):
    """
    A 4-color palette image whose top-left quadrant is transparent. The
    transparent color is index 1, which re-quantizing the colors moves.
    """
    pixels = np.full((40, 40), 2, dtype=np.uint8)
    pixels[:20, :20] = 1
    pixels[20:, :20] = 0
    pixels[20:, 20:] = 3
    image = Image.fromarray(pixels, "P")
    image.putpalette([40, 50, 60, 255, 0, 0, 90, 30, 20, 10, 80, 10])
    image.save(str(path), transparency=1)
    return str(path)


def rgba_of(image_path):
    with Image.open(image_path) as image:
        return np.asarray(image.convert("RGBA"))


@pytest.mark.parametrize("extension", ["png", "gif"])
@pytest.mark.parametrize("compensation", [0.0, -1.0])
def test_corrected_palette_crop_keeps_its_transparent_pixels(tmp_path, monkeypatch, extension, compensation):
    source = make_transparent_palette_image(tmp_path / f"palette.{extension}")
    output = str(tmp_path / f"palette_crop.{extension}")
    image = ImageObject.create(source)
    # PNG and GIF files carry no EXIF the app reads, so the stored bias is set directly
    monkeypatch.setattr(image, "get_exposure_compensation", lambda: compensation)

    image.save_cropped((0, 0, 40, 40), output, exposure_correction=True)

    original, corrected = rgba_of(source), rgba_of(output)
    np.testing.assert_array_equal(corrected[..., 3], original[..., 3])
    opaque = original[..., 3] == 255
    expected = image_utils.adjust_exposure(original[..., :3], -compensation, 2.2, 8)
    np.testing.assert_array_equal(corrected[..., :3][opaque], expected[opaque])


def test_model_input_is_always_exposure_corrected(tmp_path):
    image = ImageObject.create(make_image(tmp_path / "biased.jpg"))
    corrected = image_utils.adjust_exposure(image.image_data_rgb_8bit, 1.0, 2.2, 8)

    np.testing.assert_array_equal(image.image_data_rgb_8bit_exposure_corrected, corrected)
    assert not np.array_equal(corrected, image.image_data_rgb_8bit)


def test_image_without_bias_is_unchanged_for_models(tmp_path):
    image = ImageObject.create(make_image(tmp_path / "plain.jpg", bias=(0, 1)))

    np.testing.assert_array_equal(image.image_data_rgb_8bit_exposure_corrected, image.image_data_rgb_8bit)


def test_display_is_corrected_only_when_asked(tmp_path):
    image = ImageObject.create(make_image(tmp_path / "biased.jpg"))

    np.testing.assert_array_equal(image.display_rgb_8bit(False), image.image_data_rgb_8bit)
    np.testing.assert_array_equal(image.display_rgb_8bit(True), image.image_data_rgb_8bit_exposure_corrected)
