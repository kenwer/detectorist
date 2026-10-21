import logging

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QRubberBand, QToolTip

from .detection_style import MASK_COLORS, DetectionStyle, build_class_color_map
from .image_object import ImageObject
from .structures import clamp_box

logger = logging.getLogger(__name__)

DETECTION_BORDER_COLOR_RGB = (0, 255, 0)
DETECTION_FILL_COLOR_RGB = (0, 255, 0)
CROP_BORDER_COLOR_RGB = (255, 165, 0)
CROP_FILL_COLOR_RGBA = (255, 165, 0, 5)


class CustomRubberBand(QRubberBand):
    def __init__(self, shape, border_color, fill_color, parent=None, box: tuple | None = None,
                 detection_style: DetectionStyle | None = None):
        super().__init__(shape, parent)
        self.border_color = border_color
        self.fill_color = fill_color
        # The detection's box and style, as given to ImageLabel.set_detection_boxes
        self.box = box
        self.detection_style = detection_style
        self.highlighted = False

    def set_highlighted(self, highlighted: bool):
        if highlighted != self.highlighted:
            self.highlighted = highlighted
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setBrush(QBrush(self.fill_color))
        # A highlighted border is opaque, as that of a low scoring detection is nearly transparent
        pen = QPen(QColor(self.border_color.rgb()) if self.highlighted else self.border_color,
                   3 if self.highlighted else 1)
        painter.setPen(pen)
        # Inset by half the pen width, so a wide border is not clipped at the band's edges
        inset = pen.width() // 2
        painter.drawRect(self.rect().adjusted(inset, inset, -1 - inset, -1 - inset))


class ImageLabel(QLabel):
    # The box of the detection under the mouse, as given to set_detection_boxes, or None
    detection_hovered = Signal(object)
    # Whether an image is shown, sent when that changes. Text such as the welcome or a loading message is not an image.
    image_shown_changed = Signal(bool)

    def __init__(self, app_instance, parent=None):
        super().__init__(parent)
        self.app_instance = app_instance
        self.detection_bands = []
        self.orig_detection_rects = [] # stores the original detection data—a list of QRect, score and class_id tuples—in the image's original coordinate system
        self.orig_detection_masks = []  # parallel to orig_detection_rects; each entry is a uint8 mask array or None
        self._hit_order = []  # (band, mask) pairs in the order _band_at tests them
        self._mask_overlay_pixmap: QPixmap | None = None
        self._highlight_pixmap: QPixmap | None = None  # the highlighted detection's mask, drawn over the others
        self.class_color_map: dict[str, tuple] = {}
        self.crop_bands = []
        # Kept across set_detection_boxes, so a refresh of the same detections keeps them
        self._hovered_box = None
        self._highlighted_box = None
        self._masks_visible = True
        self._boxes_visible = True
        self._labels_visible = True
        self._pixmap = QPixmap()
        self.image = None
        self.last_crop_rects = None
        self.setMouseTracking(True)

    def set_class_color_map(self, class_names: list[str]):
        """Fixes each class's mask color for the lifetime of the loaded model."""
        self.class_color_map = build_class_color_map(class_names)

    def _map_rect_from_image_to_widget(self, image_rect):
        if self._pixmap.isNull() or self.image is None:
            return QRect()

        widget_size = self.size()
        pixmap_size = self._pixmap.size()

        scaled_pixmap = pixmap_size.scaled(widget_size, Qt.AspectRatioMode.KeepAspectRatio)

        scale_x = scaled_pixmap.width() / pixmap_size.width()
        scale_y = scaled_pixmap.height() / pixmap_size.height()

        offset_x = (widget_size.width() - scaled_pixmap.width()) / 2
        offset_y = (widget_size.height() - scaled_pixmap.height()) / 2

        widget_rect_x = int(image_rect.x() * scale_x + offset_x)
        widget_rect_y = int(image_rect.y() * scale_y + offset_y)
        widget_rect_w = int(image_rect.width() * scale_x)
        widget_rect_h = int(image_rect.height() * scale_y)

        return QRect(widget_rect_x, widget_rect_y, widget_rect_w, widget_rect_h)

    def _map_point_from_widget_to_image(self, widget_point: QPoint) -> QPoint | None:
        """Maps a widget-space point to image-space coordinates, or None if outside the image."""
        rect = self._get_displayed_image_rect()
        if rect.isEmpty():
            return None
        img_x = (widget_point.x() - rect.x()) * self._pixmap.width() / rect.width()
        img_y = (widget_point.y() - rect.y()) * self._pixmap.height() / rect.height()
        if 0 <= img_x < self._pixmap.width() and 0 <= img_y < self._pixmap.height():
            return QPoint(int(img_x), int(img_y))
        return None

    @staticmethod
    def _destroy_bands(bands):
        for band in bands:
            band.hide()
            band.setParent(None)
            band.deleteLater()

    def mouseMoveEvent(self, event):
        # QRubberBand ignores the mouse, so the label finds the band under it and shows its tooltip
        band = self._band_at(event.pos())
        self._set_hovered_box(None if band is None else band.box)
        if band is None:
            QToolTip.hideText()
        else:
            QToolTip.showText(event.globalPos(), band.toolTip(), band)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._set_hovered_box(None)
        super().leaveEvent(event)

    def _band_at(self, pos: QPoint):
        """The detection band under a widget point, or None. Over a segmentation model's band, only its mask counts."""
        img_point = self._map_point_from_widget_to_image(pos)
        for band, mask in self._hit_order:
            if mask is not None and img_point is not None:
                # Map from image coordinates to mask coordinates (mask may be at a lower resolution).
                mx = int(img_point.x() * mask.shape[1] / self.image.width)
                my = int(img_point.y() * mask.shape[0] / self.image.height)
                if 0 <= my < mask.shape[0] and 0 <= mx < mask.shape[1] and mask[my, mx] > 128:
                    return band
            elif band.geometry().contains(pos):
                return band
        return None

    def _set_hovered_box(self, box):
        if box != self._hovered_box:
            self._hovered_box = box
            self.detection_hovered.emit(box)

    def highlight_box(self, box):
        """
        Draws the detection with the given box highlighted, and the others as
        usual. None highlights none. It is shown in the shape that hovering it
        uses, its mask or else its box, even while masks or boxes are hidden.
        """
        self._highlighted_box = box
        for band in self.detection_bands:
            band.set_highlighted(band.box == self._highlighted_box)
        self._build_highlight_pixmap()
        self._update_band_visibility()
        self.update()

    def _update_band_visibility(self):
        for band, mask in zip(self.detection_bands, self.orig_detection_masks, strict=True):
            # Without a mask, the box is the only shape that can show the highlighted detection
            band.setVisible(self._boxes_visible or (mask is None and band.highlighted))

    def _clear_detection_bands(self):
        self._destroy_bands(self.detection_bands)
        self.detection_bands = []
        self.orig_detection_rects = []
        self.orig_detection_masks = []
        self._hit_order = []
        self._mask_overlay_pixmap = None
        self._highlight_pixmap = None
        self.update()

    def set_detection_boxes(self, detections, tooltips: dict | None = None, styles: dict | None = None):
        """
        Shows the given detections. tooltips maps a detection's box to the text
        shown on hovering it, in place of its class and score. styles maps a
        box to its DetectionStyle (see taxon_styles), in place of the color of
        its class and its detection score.
        """
        self._clear_detection_bands()
        tooltips = tooltips or {}
        styles = styles or {}

        if self.image is None or self.image.image_data is None:
            self._set_hovered_box(None)
            return

        has_masks = any(mask is not None for *_, mask in detections)
        color_map = self.class_color_map if has_masks else {}
        fallback_color = MASK_COLORS[0] if has_masks else DETECTION_BORDER_COLOR_RGB

        # Clamp boxes to image bounds and store as QRects so we always have a
        # reference to the original bounding box coordinates in image space.
        for box, score, class_name, mask in detections:
            x1, y1, x2, y2 = clamp_box(box, self.image.width, self.image.height)
            if not (x2 > x1 and y2 > y1):
                continue
            rect = QRect(x1, y1, x2 - x1, y2 - y1)
            style = styles.get(box) or DetectionStyle(color_map.get(class_name, fallback_color), score)
            self.orig_detection_rects.append((rect, score, class_name))
            self.orig_detection_masks.append(mask)

            alpha = int(10 + style.score * (255 - 10))  # Scale score (0.0-1.0) to alpha (10-255)
            alpha_fill = 0 if has_masks else int(style.score * 20)

            band = CustomRubberBand(QRubberBand.Shape.Rectangle, border_color=QColor(*style.color, alpha),
                                    fill_color=QColor(*style.color, alpha_fill), parent=self, box=box,
                                    detection_style=style)
            band.setGeometry(self._map_rect_from_image_to_widget(rect))
            band.set_highlighted(band.box == self._highlighted_box)
            # Only stored here. QRubberBand ignores the mouse, so mouseMoveEvent
            # shows it, and only over the mask for a segmentation model.
            band.setToolTip(tooltips.get(band.box, f"{class_name} {score:.2f}"))
            self.detection_bands.append(band)
        self._update_band_visibility()

        # Sorted once here rather than on every mouse move, as summing a mask is not cheap.
        # Smaller objects come first, as they take priority when overlapping a larger one.
        # Masks are tested before boxes, as a mask's sum and a box's area are not comparable.
        def hit_priority(i):
            mask = self.orig_detection_masks[i]
            if mask is not None:
                return 0, int(mask.sum())
            rect = self.orig_detection_rects[i][0]
            return 1, rect.width() * rect.height()
        self._hit_order = [(self.detection_bands[i], self.orig_detection_masks[i])
                           for i in sorted(range(len(self.detection_bands)), key=hit_priority)]
        # The hovered detection stays hovered across a refresh, unless it is gone
        if all(band.box != self._hovered_box for band in self.detection_bands):
            self._set_hovered_box(None)
        if has_masks:
            self._build_mask_overlay_pixmap()
        self._build_highlight_pixmap()
        self.update()

    def _build_mask_overlay_pixmap(self):
        if not self.orig_detection_masks:
            self._mask_overlay_pixmap = None
            return

        h, w = self.orig_detection_masks[0].shape[:2]
        rgba = np.zeros((h, w, 4), dtype=np.uint8)

        for band, mask in zip(self.detection_bands, self.orig_detection_masks, strict=True):
            style = band.detection_style
            rgba[mask > 128] = (*style.color, int(style.score * 140))  # alpha scales with detection confidence

        self._mask_overlay_pixmap = self._pixmap_from_rgba(rgba)

    def _build_highlight_pixmap(self):
        self._highlight_pixmap = None
        for band, mask in zip(self.detection_bands, self.orig_detection_masks, strict=True):
            if mask is None or not band.highlighted:
                continue
            inside = mask > 128
            # A pixel whose four neighbours are all inside is not on the contour,
            # which shows where the mask meets an overlapping one of the same color
            padded = np.pad(inside, 1)
            interior = inside & padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:]
            rgba = np.zeros((*inside.shape, 4), dtype=np.uint8)
            rgba[inside] = (*band.detection_style.color, 160)
            rgba[inside & ~interior] = (*band.detection_style.color, 255)
            self._highlight_pixmap = self._pixmap_from_rgba(rgba)
            return

    @staticmethod
    def _pixmap_from_rgba(rgba: np.ndarray) -> QPixmap:
        rgba = np.ascontiguousarray(rgba)
        h, w = rgba.shape[:2]
        return QPixmap.fromImage(QImage(rgba.data, w, h, rgba.strides[0], QImage.Format.Format_RGBA8888))

    def _get_displayed_image_rect(self) -> QRect:
        if self._pixmap.isNull():
            return QRect()
        size = self.size()
        pixmap_size = self._pixmap.size()
        scaled = pixmap_size.scaled(size, Qt.AspectRatioMode.KeepAspectRatio)
        offset_x = (size.width() - scaled.width()) // 2
        offset_y = (size.height() - scaled.height()) // 2
        return QRect(offset_x, offset_y, scaled.width(), scaled.height())

    def set_crop_boxes(self, image_rects):
        self.last_crop_rects = image_rects
        self._destroy_bands(self.crop_bands)
        self.crop_bands = []

        for image_rect in image_rects:
            widget_rect = self._map_rect_from_image_to_widget(image_rect)
            crop_band = CustomRubberBand(QRubberBand.Shape.Rectangle, border_color=QColor(*CROP_BORDER_COLOR_RGB), fill_color=QColor(*CROP_FILL_COLOR_RGBA), parent=self)
            crop_band.setGeometry(widget_rect)
            crop_band.show()
            self.crop_bands.append(crop_band)

    def set_masks_visible(self, visible: bool):
        """Shows or hides the segmentation masks. Hit-testing still uses a hidden mask."""
        self._masks_visible = visible
        self.update()

    def set_boxes_visible(self, visible: bool):
        """Shows or hides the bounding boxes of the detections. Hit-testing still uses a hidden box."""
        self._boxes_visible = visible
        self._update_band_visibility()

    def set_labels_visible(self, visible: bool):
        """Shows or hides the labels of the detections (see DetectionStyle)."""
        self._labels_visible = visible
        self.update()

    def hide_bands(self):
        self._clear_detection_bands()
        self._set_hovered_box(None)
        self._destroy_bands(self.crop_bands)
        self.crop_bands = []
        self.last_crop_rects = None

    def replace_image(self, image_object: ImageObject):
        """Replaces the image to be shown from the given ImageObject."""
        self.hide_bands()
        self._set_image(image_object)
        pixmap = self._create_qpixmap(image_object) # TODO: move the QPixmap creation into the ImageObject class and create the QPixmap during image loading and just use it here
        self.setPixmap(pixmap)
        self.set_detection_boxes([])

    def refresh_pixmap(self):
        """
        Rebuilds the pixmap from the current image while keeping the detection
        and crop bands, e.g. after the exposure correction setting changed.
        The image geometry is unchanged, so the bands remain valid.
        """
        if self.image is not None:
            self.setPixmap(self._create_qpixmap(self.image))

    def _create_qpixmap(self, image: ImageObject) -> QPixmap:
        """Creates a QPixmap from an ImageObject, ready for display."""
        # A contiguous 8-bit RGB numpy array, with exposure correction applied when enabled.
        rgb_image = image.image_data_rgb_8bit_display

        qimage = QImage(rgb_image.data, image.width, image.height, rgb_image.strides[0], QImage.Format.Format_RGB888)

        return QPixmap.fromImage(qimage)

    def setPixmap(self, pixmap):
        super().setText("")
        self._pixmap = pixmap
        self.update()

    def pixmap(self):
        return self._pixmap

    def clear(self):
        self._drop_image()
        super().clear()
        self.update()

    def setText(self, text):
        self._drop_image()
        super().setText(text)
        self.update()

    def _drop_image(self):
        # Bands only make sense over an image, so text never shows stale ones
        self.hide_bands()
        self._set_image(None)
        self._pixmap = QPixmap()

    def _set_image(self, image: ImageObject | None):
        shown_changed = (image is None) != (self.image is None)
        self.image = image
        if shown_changed:
            self.image_shown_changed.emit(image is not None)

    def setImageData(self, image_data):
        """Sets the pixmap from a numpy array, handling both 8-bit and 16-bit data."""
        if image_data is None:
            self.clear()
            return

        # Ensure the data is contiguous in memory for QImage
        image_data = np.ascontiguousarray(image_data)

        # Check if the image data is 16-bit and convert it to 8-bit for display
        if image_data.dtype == np.uint16:
            # Convert 16-bit to 8-bit using right-shifting
            image_data = (image_data >> 8).astype(np.uint8)

        if image_data.dtype != np.uint8:
            logger.warning("setImageData received unsupported dtype: %s", image_data.dtype)
            return

        if len(image_data.shape) != 3 or image_data.shape[2] != 3:
            logger.warning("setImageData expects a 3-channel RGB image, but got shape %s", image_data.shape)
            # Handle other cases or return
            return

        height, width, channel = image_data.shape
        bytes_per_line = 3 * width

        q_image = QImage(image_data.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(q_image)

        if not pixmap.isNull():
            self.setPixmap(pixmap)
        else:
            self.setText("Cannot load image from data")
            self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._pixmap.isNull():
            size = self.size()
            scaled_pixmap = self._pixmap.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            point = QPoint((size.width() - scaled_pixmap.width()) // 2, (size.height() - scaled_pixmap.height()) // 2)
            painter = QPainter(self)
            painter.drawPixmap(point, scaled_pixmap)
            if self._masks_visible and self._mask_overlay_pixmap is not None:
                painter.drawPixmap(self._get_displayed_image_rect(), self._mask_overlay_pixmap)
            if self._highlight_pixmap is not None:
                painter.drawPixmap(self._get_displayed_image_rect(), self._highlight_pixmap)
            if self._labels_visible:
                self._draw_labels(painter)

    def _draw_labels(self, painter: QPainter):
        metrics = painter.fontMetrics()
        for band in self.detection_bands:
            style = band.detection_style
            if style.label is None:
                continue
            box = band.geometry()
            text_rect = metrics.boundingRect(style.label).adjusted(-3, -1, 3, 1)
            # Above the box, or inside it where the box touches the top of the widget
            top = box.top() - text_rect.height()
            text_rect.moveTo(box.left(), top if top >= 0 else box.top())
            # Text in the box's color would be unreadable on some images, so the color is the background
            painter.fillRect(text_rect, QColor(*style.color))
            r, g, b = style.color
            painter.setPen(Qt.GlobalColor.black if 0.299 * r + 0.587 * g + 0.114 * b > 140 else Qt.GlobalColor.white)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, style.label)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Update the rubber band geometries based on the new size
        for i, (rect, _score, _class_name) in enumerate(self.orig_detection_rects):
            if i < len(self.detection_bands):
                widget_rect = self._map_rect_from_image_to_widget(rect)
                self.detection_bands[i].setGeometry(widget_rect)
        if self.last_crop_rects and self.crop_bands:
            self.set_crop_boxes(self.last_crop_rects)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            # Pass the event to the main application instance to handle the drop
            self.app_instance.dropEvent(event)
            event.acceptProposedAction()
