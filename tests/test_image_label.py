"""Tests for ImageLabel, the widget that draws the image with its bands.

A 200x100 image in a 400x400 label is scaled by 2 and centred vertically, so
it occupies the widget rectangle (0, 100, 400, 200). The expected band
geometries below follow from that. Bands are checked through their geometry
and hidden flag, since the label is not shown on screen.
"""

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from detectorist.detection_style import DetectionStyle
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


@pytest.mark.parametrize("replace", [lambda label: label.clear(), lambda label: label.setText("Loading image...")])
def test_image_is_forgotten_once_it_is_no_longer_shown(label, replace):
    label.set_detection_boxes([FISH])
    label.set_crop_boxes([QRect(0, 0, 100, 100)])

    replace(label)

    assert label.image is None
    # Bands only make sense over an image
    assert label.detection_bands == []
    assert label.crop_bands == []
    # Nothing left that a refresh could bring back
    label.refresh_pixmap()
    assert label.pixmap().isNull()


def test_detection_band_is_mapped_into_the_scaled_image(label):
    label.set_detection_boxes([FISH])

    (band,) = label.detection_bands
    assert band.geometry() == QRect(40, 140, 80, 80)


def test_boxes_are_clamped_to_the_image(label):
    label.set_detection_boxes([
        Detection((180, 80, 50, 50), 0.9, "Fish"),
        Detection((-10, -10, 30, 30), 0.8, "Fish"),
    ])

    assert label.orig_detection_rects == [QRect(180, 80, 20, 20), QRect(0, 0, 20, 20)]


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


def test_mask_toggle_hides_only_the_masks(label):
    mask = np.full((32, 32), 255, dtype=np.uint8)
    label.set_detection_boxes([Detection((20, 20, 40, 40), 0.9, "Fish", mask)])
    label.set_crop_boxes([QRect(0, 0, 100, 100)])
    # Inside the image, which the mask covers, but clear of both bands
    def pixel():
        return label.grab().toImage().pixel(300, 250)
    with_masks = pixel()

    label.set_masks_visible(False)

    assert pixel() != with_masks
    assert not label.detection_bands[0].isHidden()
    assert not label.crop_bands[0].isHidden()

    label.set_masks_visible(True)
    assert pixel() == with_masks


def test_box_toggle_hides_only_the_boxes_and_keeps_them_hoverable(label):
    label.set_detection_boxes([FISH])
    label.set_crop_boxes([QRect(0, 0, 100, 100)])

    label.set_boxes_visible(False)

    assert label.detection_bands[0].isHidden()
    assert not label.crop_bands[0].isHidden()
    # The band at (40, 140, 40, 40) is still found under the mouse
    assert label._band_at(QPoint(60, 160)) is label.detection_bands[0]

    # A new image's boxes start hidden as well
    label.set_detection_boxes([FISH])
    assert label.detection_bands[0].isHidden()

    label.set_boxes_visible(True)
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


def test_tooltip_of_a_detection_is_its_class_and_score_unless_given(label):
    other = Detection((100, 10, 40, 40), 0.8, "Fish")

    label.set_detection_boxes([FISH, other], {other.box: "Amphiprion ocellaris 0.44"})

    assert [band.toolTip() for band in label.detection_bands] == ["Fish 0.90", "Amphiprion ocellaris 0.44"]


def test_a_box_given_as_a_list_is_matched_like_a_tuple(label):
    label.set_detection_boxes([Detection((20, 20, 40, 40), 0.9, "Fish")], {(20, 20, 40, 40): "Amphiprion"})

    assert label.detection_bands[0].toolTip() == "Amphiprion"


def test_highlighting_marks_the_band_of_the_given_box(label):
    label.set_detection_boxes([FISH, Detection((60, 60, 80, 80), 0.5, "Fish")])

    label.highlight_box((20, 20, 40, 40))
    assert [band.highlighted for band in label.detection_bands] == [True, False]

    label.highlight_box(None)
    assert [band.highlighted for band in label.detection_bands] == [False, False]


def move_mouse(label, pos: QPoint):
    # Sent directly, as a label that is not shown on screen gets no mouse events
    point = QPointF(pos)
    QApplication.sendEvent(label, QMouseEvent(QEvent.Type.MouseMove, point, point, Qt.MouseButton.NoButton,
                                              Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))


def test_moving_the_mouse_over_a_band_reports_its_box(label):
    label.set_detection_boxes([FISH])
    hovered = []
    label.detection_hovered.connect(hovered.append)
    center = label.detection_bands[0].geometry().center()

    move_mouse(label, center)
    move_mouse(label, center + QPoint(1, 0))
    move_mouse(label, QPoint(0, 0))

    # Once per change
    assert hovered == [FISH.box, None]


def test_a_hovered_band_is_highlighted_until_the_mouse_leaves_it(label):
    label.set_detection_boxes([FISH])

    move_mouse(label, label.detection_bands[0].geometry().center())
    assert label.detection_bands[0].highlighted

    move_mouse(label, QPoint(0, 0))
    assert not label.detection_bands[0].highlighted


def test_a_hovered_detection_stays_hovered_until_it_is_gone(label):
    label.set_detection_boxes([FISH])
    hovered = []
    label.detection_hovered.connect(hovered.append)
    move_mouse(label, label.detection_bands[0].geometry().center())

    label.set_detection_boxes([FISH])
    assert hovered == [FISH.box]

    label.set_detection_boxes([])
    assert hovered == [FISH.box, None]


def test_a_smaller_box_takes_priority_where_boxes_overlap(label):
    big = Detection((10, 10, 90, 90), 0.9, "Fish")
    small = Detection((30, 30, 50, 50), 0.9, "Fish")
    label.set_detection_boxes([big, small])

    assert label._band_at(label.detection_bands[1].geometry().center()).box == small.box


def test_a_highlighted_box_is_shown_while_boxes_are_hidden(label):
    label.set_detection_boxes([FISH, Detection((60, 60, 80, 80), 0.5, "Fish")])
    label.set_boxes_visible(False)

    label.highlight_box(FISH.box)
    assert [band.isHidden() for band in label.detection_bands] == [False, True]

    label.highlight_box(None)
    assert [band.isHidden() for band in label.detection_bands] == [True, True]


def test_a_highlighted_mask_is_drawn_while_masks_and_boxes_are_hidden(label):
    mask = np.full((32, 32), 255, dtype=np.uint8)
    label.set_detection_boxes([Detection((20, 20, 40, 40), 0.9, "Fish", mask)])
    label.set_masks_visible(False)
    label.set_boxes_visible(False)
    # Inside the image, which the mask covers, but clear of the band
    def pixel():
        return label.grab().toImage().pixel(300, 250)
    hidden = pixel()

    label.highlight_box((20, 20, 40, 40))

    assert pixel() != hidden
    # The mask shows the detection, so its box stays hidden
    assert label.detection_bands[0].isHidden()

    label.highlight_box(None)
    assert pixel() == hidden


def test_highlighting_lasts_across_new_bands(label):
    label.highlight_box(FISH.box)

    label.set_detection_boxes([FISH])

    assert label.detection_bands[0].highlighted


def test_a_given_style_sets_the_band_color_and_opacity(label):
    label.set_detection_boxes([FISH], styles={FISH.box: DetectionStyle((0, 0, 230), 0.5, "Labridae")})

    color = label.detection_bands[0].border_color
    assert (color.red(), color.green(), color.blue(), color.alpha()) == (0, 0, 230, int(10 + 0.5 * 245))


def test_labels_are_drawn_above_their_box_until_hidden(label):
    label.set_detection_boxes([FISH], styles={FISH.box: DetectionStyle((0, 0, 230), 0.5, "Labridae")})
    # In the label's left padding, just above the band at (40, 140)
    point = QPoint(41, 137)

    assert label.grab().toImage().pixelColor(point).getRgb()[:3] == (0, 0, 230)

    label.set_labels_visible(False)

    assert label.grab().toImage().pixelColor(point).getRgb()[:3] != (0, 0, 230)
