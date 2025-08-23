import os
from PySide6.QtWidgets import QLabel, QRubberBand
from PySide6.QtGui import QPixmap, QPainter, QImage, QColor, QBrush, QPen
from PySide6.QtCore import Qt, QRect, QSize, QPoint
import numpy as np
from .image import Image


class CustomRubberBand(QRubberBand):
    def __init__(self, shape, parent=None, border_color=QColor(255, 165, 0, 255), fill_color=QColor(255, 165, 0, 13)):
        super().__init__(shape, parent)
        self.border_color = border_color
        self.fill_color = fill_color

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setBrush(QBrush(self.fill_color))
        pen = QPen(self.border_color)
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


class ImageLabel(QLabel):
    def __init__(self, app_instance, parent=None):
        super().__init__(parent)
        self.app_instance = app_instance
        self.detection_bands = []
        self.last_detection_rects = []
        self.crop_band = CustomRubberBand(QRubberBand.Shape.Rectangle, self, border_color=QColor(255, 165, 0, 255), fill_color=QColor(255, 165, 0, 5))
        self.crop_band.hide()
        self._pixmap = QPixmap()
        self.image = None
        self.last_crop_rect = None

    def _map_rect_from_image_to_widget(self, image_rect):
        if self._pixmap.isNull() or self.image is None:
            return QRect()

        widget_size = self.size()
        pixmap_size = self._pixmap.size()

        scaled_pixmap = pixmap_size.scaled(widget_size, Qt.KeepAspectRatio)

        scale_x = scaled_pixmap.width() / pixmap_size.width()
        scale_y = scaled_pixmap.height() / pixmap_size.height()

        offset_x = (widget_size.width() - scaled_pixmap.width()) / 2
        offset_y = (widget_size.height() - scaled_pixmap.height()) / 2

        widget_rect_x = int(image_rect.x() * scale_x + offset_x)
        widget_rect_y = int(image_rect.y() * scale_y + offset_y)
        widget_rect_w = int(image_rect.width() * scale_x)
        widget_rect_h = int(image_rect.height() * scale_y)

        return QRect(widget_rect_x, widget_rect_y, widget_rect_w, widget_rect_h)

    def _clear_detection_bands(self):
        for band in self.detection_bands:
            band.hide()
            band.setParent(None)
            band.deleteLater()
        self.detection_bands = []
        self.last_detection_rects = []

    def set_detection_boxes(self, image_rects, scores):
        self._clear_detection_bands()
        self.last_detection_rects = list(zip(image_rects, scores))
        for rect, score in self.last_detection_rects:
            alpha = int(10 + (score * (255-10))) # Scale score (0.0-1.0) to alpha (10-255)
            alpha_fill = int(score * 20) # Scale score (0.0-1.0) to alpha (0-20)
            band = CustomRubberBand(QRubberBand.Shape.Rectangle, self, border_color=QColor(0, 255, 0, alpha), fill_color=QColor(0, 255, 0, alpha_fill))
            widget_rect = self._map_rect_from_image_to_widget(rect)
            band.setGeometry(widget_rect)
            band.show()
            self.detection_bands.append(band)

    def set_crop_box(self, image_rect):
        self.last_crop_rect = image_rect
        widget_rect = self._map_rect_from_image_to_widget(image_rect)
        self.crop_band.setGeometry(widget_rect)
        self.crop_band.show()

    def hide_bands(self):
        self._clear_detection_bands()
        self.crop_band.hide()
        self.last_crop_rect = None

    def replace_image(self, image_path):
        self.hide_bands()
        try:
            self.image = Image(image_path)
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                self.setPixmap(pixmap)
            else:
                self.setText(f"Cannot load image:\n{os.path.basename(image_path)}")
                self.setAlignment(Qt.AlignCenter)
            return True
        except Exception as e:
            self.setText(f"Error loading image: {e}")
            print(f"Error loading image: {e}")
            self.image = None
            return False

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

        q_image = QImage(image_data.data, width, height, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(q_image)

        if not pixmap.isNull():
            self.setPixmap(pixmap)
        else:
            self.setText("Cannot load image from data")
            self.setAlignment(Qt.AlignCenter)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._pixmap.isNull():
            size = self.size()
            scaled_pixmap = self._pixmap.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            point = QPoint((size.width() - scaled_pixmap.width()) // 2, (size.height() - scaled_pixmap.height()) // 2)
            painter = QPainter(self)
            painter.drawPixmap(point, scaled_pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for i, (rect, score) in enumerate(self.last_detection_rects):
            if i < len(self.detection_bands):
                widget_rect = self._map_rect_from_image_to_widget(rect)
                self.detection_bands[i].setGeometry(widget_rect)
        if self.last_crop_rect and self.crop_band.isVisible():
            self.set_crop_box(self.last_crop_rect)

    # def mousePressEvent(self, event):
    #     if event.button() == Qt.LeftButton:
    #         self.origin = event.position().toPoint()
    #         self.detection_band.setGeometry(QRect(self.origin, QSize()))
    #         self.detection_band.show()

    # def mouseMoveEvent(self, event):
    #     if self.detection_band.isVisible():
    #         self.detection_band.setGeometry(QRect(self.origin, event.position().toPoint()).normalized())

    # def mouseReleaseEvent(self, event):
    #     # The detection_band is left visible for the user to see the result
    #     pass

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
