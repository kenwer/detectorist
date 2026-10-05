"""Tests for ImageLabel, the widget that draws the image with its bands.

A 200x100 image in a 400x400 label is scaled by 2 and centred vertically, so
it occupies the widget rectangle (0, 100, 400, 200). The expected band
geometries below follow from that. Bands are checked through their geometry
and hidden flag, since the label is not shown on screen.
"""

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QRect

from detectorist.image_label import ImageLabel
from detectorist.image_object import ImageObject
from detectorist.structures import Detection
from tests.fakes import make_images

FISH = Detection((20, 20, 40, 40), 0.9, "Fish")


@pytest.fixture
def label(qtbot, tmp_path):
    label = ImageLabel(app_instance=None)
    qtbot.addWidget(label)
    label.resize(400, 400)
    (path,) = make_images(tmp_path, ["image.png"], size=(200, 100))
    label.replace_image(ImageObject.create(path))
    return label


def test_detection_band_is_mapped_into_the_scaled_image(label):
    label.set_detection_boxes([FISH])

    (band,) = label.detection_bands
    assert band.geometry() == QRect(40, 140, 80, 80)


def test_boxes_are_clamped_to_the_image(label):
    label.set_detection_boxes([
        Detection((180, 80, 50, 50), 0.9, "Fish"),
        Detection((-10, -10, 30, 30), 0.8, "Fish"),
    ])

    assert [rect for rect, _score, _name in label.orig_detection_rects] == [QRect(180, 80, 20, 20), QRect(0, 0, 20, 20)]


def test_box_outside_the_image_gets_no_band(label):
    label.set_detection_boxes([Detection((300, 300, 10, 10), 0.9, "Fish")])

    assert label.detection_bands == []


def test_setting_boxes_replaces_the_previous_ones(label):
    label.set_detection_boxes([FISH, FISH])
    label.set_detection_boxes([FISH])

    assert len(label.detection_bands) == 1


def test_boxes_are_ignored_without_an_image(qtbot):
    label = ImageLabel(app_instance=None)
    qtbot.addWidget(label)

    label.set_detection_boxes([FISH])

    assert label.detection_bands == []


def test_crop_band_is_mapped_and_replaced(label):
    label.set_crop_boxes([QRect(0, 0, 100, 100), QRect(100, 0, 100, 100)])
    label.set_crop_boxes([QRect(0, 0, 100, 100)])

    (band,) = label.crop_bands
    assert band.geometry() == QRect(0, 100, 200, 200)


def test_overlay_toggle_hides_detection_bands_but_not_crop_bands(label):
    label.set_detection_boxes([FISH])
    label.set_crop_boxes([QRect(0, 0, 100, 100)])

    label.set_detection_overlay_visible(False)
    assert label.detection_bands[0].isHidden()
    assert not label.crop_bands[0].isHidden()

    label.set_detection_overlay_visible(True)
    assert not label.detection_bands[0].isHidden()


def test_hide_bands_removes_everything(label):
    label.set_detection_boxes([FISH])
    label.set_crop_boxes([QRect(0, 0, 100, 100)])

    label.hide_bands()

    assert label.detection_bands == []
    assert label.crop_bands == []
    assert label.orig_detection_rects == []
    assert label.last_crop_rects is None


def test_text_replaces_the_image(label):
    label.setText("Loading image...")

    assert label.pixmap().isNull()
    assert label.text() == "Loading image..."


def test_detections_with_masks_get_bands(label):
    mask = np.zeros((32, 32), dtype=np.uint8)
    mask[:, :16] = 255
    label.set_class_color_map(["Fish"])

    label.set_detection_boxes([Detection((20, 20, 40, 40), 0.9, "Fish", mask)])

    assert len(label.detection_bands) == 1
    assert label.orig_detection_masks[0] is mask


def test_resizing_the_label_remaps_the_bands(qtbot, label):
    label.set_detection_boxes([FISH])
    label.set_crop_boxes([QRect(0, 0, 100, 100)])
    # A hidden widget defers its resize event until it is shown
    label.show()
    qtbot.waitExposed(label)

    label.resize(200, 200)
    qtbot.waitUntil(lambda: label.detection_bands[0].geometry() == QRect(20, 70, 40, 40))

    assert label.crop_bands[0].geometry() == QRect(0, 50, 100, 100)


def test_widget_points_map_back_to_image_pixels(label):
    # The tooltip uses this mapping. It has no public caller that returns a
    # value, so the private method is the only place to pin the arithmetic.
    assert label._map_point_from_widget_to_image(QPoint(200, 200)) == QPoint(100, 50)
    assert label._map_point_from_widget_to_image(QPoint(10, 10)) is None  # in the margin above the image
