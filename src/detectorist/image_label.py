from collections import Counter

import numpy as np
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QRubberBand, QToolTip

from .image_object import ImageObject

DETECTION_BORDER_COLOR_RGB = (0, 255, 0)
DETECTION_FILL_COLOR_RGB = (0, 255, 0)
CROP_BORDER_COLOR_RGB = (255, 165, 0)
CROP_FILL_COLOR_RGBA = (255, 165, 0, 5)

# 12 visually distinct colors for instance segmentation masks. Color is assigned
# per class name by detection frequency, so all instances of the same class share
# a color. The most frequently detected class always gets MASK_COLORS[0] (green).
MASK_COLORS = [
    (50, 180, 50),   # green
    (220, 50, 50),   # red
    (50, 100, 220),  # blue
    (220, 180, 50),  # yellow
    (180, 50, 220),  # purple
    (50, 200, 200),  # cyan
    (220, 120, 50),  # orange
    (50, 220, 120),  # mint
    (220, 50, 150),  # pink
    (100, 50, 220),  # indigo
    (50, 150, 220),  # sky
    (150, 220, 50),  # lime
]


def _build_class_color_map(class_names: list[str]) -> dict[str, tuple]:
    """Assigns colors by detection count: the most detected class gets MASK_COLORS[0] (green)."""
    ranked = [name for name, _ in Counter(class_names).most_common()]
    return {name: MASK_COLORS[i % len(MASK_COLORS)] for i, name in enumerate(ranked)}


class CustomRubberBand(QRubberBand):
    def __init__(self, shape, border_color, fill_color, score=None, class_name=None, parent=None):
        super().__init__(shape, parent)
        self.border_color = border_color
        self.fill_color = fill_color
        self.score = score
        self.class_name = class_name

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setBrush(QBrush(self.fill_color))
        pen = QPen(self.border_color)
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


class TooltipEventFilter(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_label = parent

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseMove:
            masks = self.parent_label.orig_detection_masks
            img_point = self.parent_label._map_point_from_widget_to_image(event.pos())

            # Pair each band with its mask and sort by mask area ascending so smaller
            # objects are checked first — they take priority when overlapping a larger one.
            pairs = sorted(
                zip(self.parent_label.detection_bands, masks, strict=True),
                key=lambda bm: int(bm[1].sum()) if bm[1] is not None else float('inf'),
            )
            for band, mask in pairs:
                if mask is not None and img_point is not None:
                    # Map from image coordinates to mask coordinates (mask may be at a lower resolution).
                    mx = int(img_point.x() * mask.shape[1] / self.parent_label.image.width)
                    my = int(img_point.y() * mask.shape[0] / self.parent_label.image.height)
                    if 0 <= my < mask.shape[0] and 0 <= mx < mask.shape[1] and mask[my, mx] > 128:
                        QToolTip.showText(event.globalPos(), f"{band.class_name} {band.score:.2f}", band)
                        return True
                else:
                    if band.geometry().contains(event.pos()):
                        QToolTip.showText(event.globalPos(), f"{band.class_name} {band.score:.2f}", band)
                        return True
            QToolTip.hideText()
        return super().eventFilter(watched, event)


class ImageLabel(QLabel):
    def __init__(self, app_instance, parent=None):
        super().__init__(parent)
        self.app_instance = app_instance
        self.detection_bands = []
        self.orig_detection_rects = [] # stores the original detection data—a list of QRect, score and class_id tuples—in the image's original coordinate system
        self.orig_detection_masks = []  # parallel to orig_detection_rects; each entry is a uint8 mask array or None
        self._mask_overlay_pixmap: QPixmap | None = None
        self.crop_bands = []
        self._pixmap = QPixmap()
        self.image = None
        self.last_crop_rects = None
        self.setMouseTracking(True)
        self._tooltip_filter = TooltipEventFilter(self)
        self.installEventFilter(self._tooltip_filter)

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

    def _clear_detection_bands(self):
        for band in self.detection_bands:
            band.hide()
            band.setParent(None)
            band.deleteLater()
        self.detection_bands = []
        self.orig_detection_rects = []
        self.orig_detection_masks = []
        self._mask_overlay_pixmap = None
        self.update()

    def set_detection_boxes(self, detections):
        self._clear_detection_bands()

        if self.image is None or self.image.image_data is None:
            return

        image_height, image_width = self.image.height, self.image.width

        # Clamp boxes to image bounds and store as QRects so we always have a
        # reference to the original bounding box coordinates in image space.
        for (x, y, w, h), score, class_name, mask in detections:
            x1, y1 = max(0, x), max(0, y)
            x2, y2 = min(x + w, image_width), min(y + h, image_height)

            # Ensure the box has a non-zero area
            if x2 > x1 and y2 > y1:
                self.orig_detection_rects.append((QRect(x1, y1, x2 - x1, y2 - y1), score, class_name))
                self.orig_detection_masks.append(mask)

        has_masks = any(m is not None for m in self.orig_detection_masks)
        class_names = [class_name for _, _, class_name in self.orig_detection_rects]
        color_map = _build_class_color_map(class_names) if has_masks else {}
        for rect, score, class_name in self.orig_detection_rects:
            alpha = int(10 + (score * (255-10))) # Scale score (0.0-1.0) to alpha (10-255)
            alpha_fill = 0 if has_masks else int(score * 20) # Suppress fill when masks are present — the mask is a better region indicator
            color_rgb = color_map.get(class_name, MASK_COLORS[0]) if has_masks else DETECTION_BORDER_COLOR_RGB
            band = CustomRubberBand(QRubberBand.Shape.Rectangle, border_color=QColor(*color_rgb, alpha), fill_color=QColor(*color_rgb, alpha_fill), score=score, class_name=class_name, parent=self)
            widget_rect = self._map_rect_from_image_to_widget(rect)
            band.setGeometry(widget_rect)
            band.show()
            self.detection_bands.append(band)

        self._build_mask_overlay_pixmap(color_map if has_masks else None)
        self.update()

    def _build_mask_overlay_pixmap(self, color_map: dict | None):
        if color_map is None:
            self._mask_overlay_pixmap = None
            return

        h, w = self.orig_detection_masks[0].shape[:2]
        rgba = np.zeros((h, w, 4), dtype=np.uint8)

        for (_, score, class_name), mask in zip(self.orig_detection_rects, self.orig_detection_masks, strict=True):
            r, g, b = color_map.get(class_name, MASK_COLORS[0])
            rgba[mask > 128] = (r, g, b, int(score * 140))  # alpha scales with confidence

        rgba_contiguous = np.ascontiguousarray(rgba)
        qimage = QImage(rgba_contiguous.data, w, h, rgba_contiguous.strides[0], QImage.Format.Format_RGBA8888)
        self._mask_overlay_pixmap = QPixmap.fromImage(qimage)

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
        # Clear existing crop bands
        for band in self.crop_bands:
            band.hide()
            band.setParent(None)
            band.deleteLater()
        self.crop_bands = []

        for image_rect in image_rects:
            widget_rect = self._map_rect_from_image_to_widget(image_rect)
            crop_band = CustomRubberBand(QRubberBand.Shape.Rectangle, border_color=QColor(*CROP_BORDER_COLOR_RGB), fill_color=QColor(*CROP_FILL_COLOR_RGBA), parent=self)
            crop_band.setGeometry(widget_rect)
            crop_band.show()
            self.crop_bands.append(crop_band)

    def hide_bands(self):
        self._clear_detection_bands()
        for band in self.crop_bands:
            band.hide()
            band.setParent(None)
            band.deleteLater()
        self.crop_bands = []
        self.last_crop_rects = None

    def replace_image(self, image_object: ImageObject):
        """Replaces the image to be shown from the given ImageObject."""
        self.hide_bands()
        self.image = image_object
        pixmap = self._create_qpixmap(image_object) # TODO: move the QPixmap creation into the ImageObject class and create the QPixmap during image loading and just use it here
        self.setPixmap(pixmap)
        self.set_detection_boxes([])

    def _create_qpixmap(self, image: ImageObject) -> QPixmap:
        """Creates a QPixmap from an ImageObject, ready for display."""
        # image_data_rgb_8bit provides a contiguous 8-bit RGB numpy array.
        rgb_image = image.image_data_rgb_8bit

        qimage = QImage(rgb_image.data, image.width, image.height, rgb_image.strides[0], QImage.Format.Format_RGB888)

        return QPixmap.fromImage(qimage)

    def setPixmap(self, pixmap):
        super().setText("")
        self._pixmap = pixmap
        self.update()

    def pixmap(self):
        return self._pixmap

    def clear(self):
        self._pixmap = QPixmap()
        super().clear()
        self.update()

    def setText(self, text):
        self._pixmap = QPixmap()
        super().setText(text)
        self.update()

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
            print(f"Warning: setImageData received unsupported dtype: {image_data.dtype}")
            return

        if len(image_data.shape) != 3 or image_data.shape[2] != 3:
            print(f"Warning: setImageData expects a 3-channel RGB image, but got shape {image_data.shape}")
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
            if self._mask_overlay_pixmap is not None:
                painter.drawPixmap(self._get_displayed_image_rect(), self._mask_overlay_pixmap)

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
