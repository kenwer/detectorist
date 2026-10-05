"""Tests for the EXIF summary shown in the EXIF panel."""

import piexif
import pytest
from PIL import Image

from detectorist.image_object import ImageObject

# 48 deg 31' 12" and 9 deg 3' 36"
LATITUDE = ((48, 1), (31, 1), (12, 1))
LONGITUDE = ((9, 1), (3, 1), (36, 1))
NO_FIX = ((0, 0), (0, 0), (0, 0))


def make_jpeg(path, gps):
    exif = piexif.dump({"0th": {piexif.ImageIFD.Make: b"Acme"}, "Exif": {}, "GPS": gps, "1st": {}})
    Image.new("RGB", (64, 48)).save(str(path), exif=exif)
    return str(path)


def test_summary_shows_gps_coordinates_in_decimal_degrees(tmp_path):
    gps = {
        piexif.GPSIFD.GPSLatitude: LATITUDE, piexif.GPSIFD.GPSLatitudeRef: b"N",
        piexif.GPSIFD.GPSLongitude: LONGITUDE, piexif.GPSIFD.GPSLongitudeRef: b"W",
    }

    image = ImageObject.create(make_jpeg(tmp_path / "located.jpg", gps))

    assert image.get_gps_coordinates_from_exif() == "48.520000° N, 9.060000° W"
    assert "GPS coords\t: 48.520000° N, 9.060000° W" in image.get_exif_summary()


@pytest.mark.parametrize(("latitude", "longitude"), [
    (NO_FIX, NO_FIX),
    (LATITUDE, NO_FIX),
    (LATITUDE, LONGITUDE[:2]),
])
def test_unusable_gps_coordinates_are_left_out_of_the_summary(tmp_path, latitude, longitude):
    gps = {piexif.GPSIFD.GPSLatitude: latitude, piexif.GPSIFD.GPSLongitude: longitude}

    image = ImageObject.create(make_jpeg(tmp_path / "no_fix.jpg", gps))

    assert image.get_gps_coordinates_from_exif() == ""
    # The rest of the summary is still shown
    assert image.get_exif_summary() == "Camera\t: Acme"


def test_summary_without_gps_data(tmp_path):
    image = ImageObject.create(make_jpeg(tmp_path / "plain.jpg", {}))

    assert image.get_exif_summary() == "Camera\t: Acme"
