import os
from PySide6.QtWidgets import QLabel, QRubberBand, QToolTip
from PySide6.QtGui import QPixmap, QPainter, QImage, QColor, QBrush, QPen
from PySide6.QtCore import Qt, QRect, QSize, QPoint, QObject, QEvent
import numpy as np
from .image_object import ImageObject


class CustomRubberBand(QRubberBand):
    def __init__(self, shape, parent=None, border_color=QColor(255, 165, 0, 255), fill_color=QColor(255, 165, 0, 13), score=None, class_name=None):
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
            for band in self.parent_label.detection_bands:
                if band.geometry().contains(event.pos()):
                    tooltip_text = f"{band.class_name} {band.score:.2f}"
                    QToolTip.showText(event.globalPos(), tooltip_text, band)
                    return True
            QToolTip.hideText()
        return super().eventFilter(watched, event)


class ImageLabel(QLabel):
    def __init__(self, app_instance, parent=None):
        super().__init__(parent)
        self.app_instance = app_instance
        self.detection_bands = []
        self.orig_detection_rects = [] # stores the original detection data—a list of QRect, score and class_id tuples—in the image's original coordinate system
        self.crop_band = CustomRubberBand(QRubberBand.Shape.Rectangle, self, border_color=QColor(255, 165, 0, 255), fill_color=QColor(255, 165, 0, 5))
        self.crop_band.hide()
        self._pixmap = QPixmap()
        self.image = None
        self.last_crop_rect = None
        self.setMouseTracking(True)
        self._tooltip_filter = TooltipEventFilter(self)
        self.installEventFilter(self._tooltip_filter)

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
        self.orig_detection_rects = []

    def set_detection_boxes(self, detections):
        self._clear_detection_bands()

        if self.image is None or self.image.image_data is None:
            return

        image_height, image_width, _ = self.image.image_data.shape

        clamped_detections = []
        for (x, y, w, h), score, class_name in detections:
            x1, y1 = max(0, x), max(0, y)
            x2, y2 = min(x + w, image_width), min(y + h, image_height)
            
            # Ensure the box has a non-zero area
            if x2 > x1 and y2 > y1:
                clamped_w, clamped_h = x2 - x1, y2 - y1
                clamped_detections.append(((x1, y1, clamped_w, clamped_h), score, class_name))

        # Convert detections to QRects and store them to always have a reference to the original bounding box coordinates
        self.orig_detection_rects = [(QRect(x, y, w, h), score, class_name) for (x, y, w, h), score, class_name in clamped_detections]

        for rect, score, class_name in self.orig_detection_rects:
            alpha = int(10 + (score * (255-10))) # Scale score (0.0-1.0) to alpha (10-255)
            alpha_fill = int(score * 20) # Scale score (0.0-1.0) to alpha (0-20)
            band = CustomRubberBand(QRubberBand.Shape.Rectangle, self, border_color=QColor(0, 255, 0, alpha), fill_color=QColor(0, 255, 0, alpha_fill), score=score, class_name=class_name)
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
            self.image = ImageObject(image_path)
            pixmap = self._create_qpixmap(self.image)
            self.setPixmap(pixmap)
            return True
        except Exception as e:
            self.setText(f"Error loading image: {e}")
            print(f"Error loading image: {e}")
            self.image = None
            return False

    def _create_qpixmap(self, image):
        rgb_image = image.image_data
        
        # Convert 16-bit to 8-bit if needed
        if rgb_image.dtype == np.uint16:
            rgb_image = (rgb_image / 256).astype(np.uint8)
        
        # Ensure correct format
        if len(rgb_image.shape) != 3 or rgb_image.shape[2] != 3:
            raise ValueError("Invalid image format: must be (height, width, 3)")
        
        height, width, _ = rgb_image.shape
        # Create QImage from the NumPy array
        #qimage = QImage(rgb_image.data, width, height, width * 3, QImage.Format_RGB888)
        qimage = QImage(rgb_image.data, width, height, rgb_image.strides[0], QImage.Format.Format_RGB888)
        
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
        # Update the rubber band geometries based on the new size
        for i, (rect, score, class_name) in enumerate(self.orig_detection_rects):
            if i < len(self.detection_bands):
                widget_rect = self._map_rect_from_image_to_widget(rect)
                self.detection_bands[i].setGeometry(widget_rect)
        if self.last_crop_rect and self.crop_band.isVisible():
            self.set_crop_box(self.last_crop_rect)

    # TODO: the cropping band logic has issues with the confidence tooltips - probably caused by the event filter
    # def mousePressEvent(self, event):
    #     if event.button() == Qt.LeftButton:
    #         self.origin = event.position().toPoint()
    #         self.crop_band.setGeometry(QRect(self.origin, QSize()))
    #         self.crop_band.show()

    # def mouseMoveEvent(self, event):
    #     if self.crop_band.isVisible():
    #         self.crop_band.setGeometry(QRect(self.origin, event.position().toPoint()).normalized())

    # def mouseReleaseEvent(self, event):
    #     # The crop_band is left visible for the user to see the result
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
