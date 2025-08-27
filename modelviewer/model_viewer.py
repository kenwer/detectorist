import os
import time
import pillow_heif

from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QProgressDialog
from PySide6.QtGui import QPixmap
from PySide6.QtCore import QDir, Qt, QStringListModel, QRect, QTimer

from modelviewer._version import __version__
from modelviewer.model_viewer_gui import Ui_ModelViewerUI

from .detector import Detector
from .image_object import ImageObject
from .image_label import ImageLabel
from .utils import get_model_path
from . import image_utils

class ModelViewer(QMainWindow):
    SUPPORTED_FORMATS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.heic', '.heif', '.hif', '.arw')

    @staticmethod
    def _calculate_crop_rect(detections: list, image_shape: tuple, crop_mode: str, padding_percentage: float, aspect_ratio: tuple[int, int]) -> tuple[int, int, int, int] | None:
        """
        Calculates a crop rectangle based on detections and parameters.
        
        Args:
            detections: A list of detections, where each detection is a tuple ((x, y, w, h), score, class_id).
            image_shape: The shape of the image (height, width, channels).
            crop_mode: 'top_confidence' or 'largest_area'.
            padding_percentage: Padding to add around the bounding box, as a float (e.g., 0.1 for 10%).
            aspect_ratio: A tuple (width, height) for the target aspect ratio.

        Returns:
            A tuple (x, y, w, h) for the crop rectangle, or None if no rectangle could be calculated.
        """
        if not detections:
            return None

        if crop_mode == 'top_confidence':
            top_detection = max(detections, key=lambda d: d[1])
            x, y, w, h = top_detection[0]
        elif crop_mode == 'largest_area':
            # The detection boxes are tuples of (x, y, w, h)
            left = min(d[0][0] for d in detections)
            top = min(d[0][1] for d in detections)
            right = max(d[0][0] + d[0][2] for d in detections)
            bottom = max(d[0][1] + d[0][3] for d in detections)
            x, y, w, h = left, top, right - left, bottom - top
        else:
            return None

        # Add padding
        padding_x = int(w * padding_percentage)
        padding_y = int(h * padding_percentage)
        
        x -= padding_x
        y -= padding_y
        w += 2 * padding_x
        h += 2 * padding_y

        # Adjust for aspect ratio
        if h <= 0 or aspect_ratio[1] <= 0:
            return None # Avoid division by zero

        ratio_w, ratio_h = aspect_ratio
        rect_w, rect_h = w, h
        
        current_ratio = rect_w / rect_h
        target_ratio = ratio_w / ratio_h

        if current_ratio > target_ratio:
            # Too wide, adjust height
            new_h = int(rect_w / target_ratio)
            diff_h = new_h - rect_h
            y -= diff_h // 2
            h = new_h
        else:
            # Too tall, adjust width
            new_w = int(rect_h * target_ratio)
            diff_w = new_w - rect_w
            x -= diff_w // 2
            w = new_w

        # Ensure the crop rectangle is within the image boundaries
        image_height, image_width, _ = image_shape
        
        # Intersection logic
        img_x, img_y = 0, 0
        
        final_x = max(x, img_x)
        final_y = max(y, img_y)
        
        end_x = min(x + w, img_x + image_width)
        end_y = min(y + h, img_y + image_height)

        final_w = end_x - final_x
        final_h = end_y - final_y

        if final_w < 0:
            final_w = 0
        if final_h < 0:
            final_h = 0

        return (final_x, final_y, final_w, final_h)

    def __init__(self):
        super().__init__()

        self.current_image_path = None
        self.current_folder_path = None
        self.last_confidence = None
        self.last_nms = None
        
        # Ensure opener is registered (otherwise the native code will segfault)
        pillow_heif.register_heif_opener()

        # Set up the UI
        self.ui = Ui_ModelViewerUI()
        self.ui.setupUi(self)
        self.setWindowTitle(f"Fish Model Viewer {__version__}")

        # Debounce timer for detection
        self.detection_timer = QTimer(self)
        self.detection_timer.setSingleShot(True)
        self.detection_timer.setInterval(500)  # 500ms delay
        self.detection_timer.timeout.connect(self.detect_fish)

        # Replace the imageLabel from the ui file with our custom ImageLabel
        # but keep/re-use the sizePolicy and alignment from the .ui file
        sizePolicy = self.ui.imageLabel.sizePolicy()
        alignment = self.ui.imageLabel.alignment()
        self.ui.imageLabel = ImageLabel(self, self.ui.centralWidget)
        self.ui.imageLabel.setSizePolicy(sizePolicy)
        self.ui.imageLabel.setAlignment(alignment)
        self.ui.splitter.replaceWidget(1, self.ui.imageLabel)
        self.ui.imageLabel.setText("Drop a folder with images")
        self.ui.imageLabel.setAcceptDrops(True) # Enable drag and drop for imageLabel

        self.model = QStringListModel()
        self.ui.imageListView.setModel(self.model)
        self.ui.imageListView.setAcceptDrops(True) # Enable drag and drop for imageListView
        self.setAcceptDrops(True) # Enable drag and drop for the main window

        # Connect signals
        self.ui.openFolderAction.triggered.connect(self.open_folder)
        self.ui.detectFishAction.triggered.connect(self.detect_fish)
        self.ui.imageListView.selectionModel().currentChanged.connect(self.on_image_selected)
        self.ui.actionCropSaveImage.triggered.connect(self.crop_save_image)
        self.ui.actionCropSaveAllImages.triggered.connect(self.crop_save_all_images)

        # Delayed Sliders and SpinBoxes (because they are emitted very often)
        self.ui.confidenceSlider.valueChanged.connect(self.request_detection)
        self.ui.nmsSlider.valueChanged.connect(self.request_detection)
        self.ui.confidenceSpinBox.valueChanged.connect(self.request_detection)
        self.ui.nmsSpinBox.valueChanged.connect(self.request_detection)

        # Immediate trigger 
        self.ui.confidenceSlider.sliderReleased.connect(self.detect_fish)
        self.ui.nmsSlider.sliderReleased.connect(self.detect_fish)
        self.ui.confidenceSpinBox.editingFinished.connect(self.detect_fish)
        self.ui.nmsSpinBox.editingFinished.connect(self.detect_fish)


        # Connect crop controls
        self.ui.rb_crop_to_top_conf.toggled.connect(self.update_crop_band)
        self.ui.rb_crop_largest_area.toggled.connect(self.update_crop_band)
        self.ui.cropRatioComboBox.currentIndexChanged.connect(self.update_crop_band)
        self.ui.paddingSlider.valueChanged.connect(self.update_crop_band)

        self.models_dir=get_model_path()
        if not os.path.exists(self.models_dir):
            print(f"Error: models directory does not exist at {self.models_dir}")
            # Handle the error, e.g., by raising an exception or showing a message
            raise FileNotFoundError(f"Models directory not found: {self.models_dir}")

        # Find and populate models
        self.onnx_models = [f for f in os.listdir(self.models_dir) if f.endswith(".onnx")]
        print(f"Found ONNX models: {self.onnx_models}")
        self.ui.modelSelectComboBox.addItems(self.onnx_models)
        self.ui.modelSelectComboBox.currentIndexChanged.connect(self.on_model_selected)

        # Load AI model
        self.on_model_selected(0)


    def _update_detection_info(self, objects="-", confidence="-", time="-"):
        detection_info_items = [
            ("Objects\t\t\t", objects),
            ("Highest confidence\t", confidence),
            ("Detection time\t\t", time)
        ]
        detection_info = "\n".join(f"{k}: {v}" for k, v in detection_info_items)
        self.ui.detectionInfoLabel.setText(detection_info)


    def request_detection(self):
        self.detection_timer.start()


    def open_folder(self, folder_path=None):
        if not folder_path:
            folder_path = QFileDialog.getExistingDirectory(self, "Open Folder", QDir.homePath())
        if folder_path:
            self.current_folder_path = folder_path
            # Clear existing list and main image
            self.model.setStringList([])
            self.current_image_path = None
            self.ui.imageLabel.clear()

            self.ui.imageLabel.setText("Loading Images...")
            QApplication.processEvents()  # Update the UI to show the message

            image_files = sorted([f for f in os.listdir(folder_path)
                           if f.lower().endswith(self.SUPPORTED_FORMATS)])

            if image_files:
                self.model.setStringList(image_files)
                # Select the first image in the list view
                first_index = self.model.index(0)
                self.ui.imageListView.setCurrentIndex(first_index)
                self.on_image_selected(first_index)
                self.ui.actionCropSaveAllImages.setEnabled(True)
            else:
                self.ui.actionCropSaveAllImages.setEnabled(False)
                self.ui.imageLabel.setText("No supported images found in folder.")


    def on_image_selected(self, index):
        file_name = self.model.stringList()[index.row()]
        if self.current_folder_path:
            self.current_image_path = os.path.join(self.current_folder_path, file_name)
            self.ui.statusBar.showMessage(file_name)

            if self.ui.imageLabel.replace_image(self.current_image_path):
                self.last_confidence = None  # Reset for new image
                self.last_nms = None  # Reset for new image
                self._update_detection_info() # Reset for new detection

                # Add image info to the self.ui.imageInfoLabel
                height, width, _ = self.ui.imageLabel.image.image_data.shape
                #color_depth = "16-bit" if self.ui.imageLabel.image.is16bit else "8-bit" #TODO: rework color depth logic HIF have BitDepthChroma and BitDepthLuma in EXIF, ARW and JPG have BitsPerSample
                file_type = self.ui.imageLabel.image.file_extension.upper()[1:]
                #self.ui.imageInfoLabel.setText(f"Resolution\t: {width}x{height}\nColor depth\t: {color_depth}\nFile type \t: {file_type}")
                self.ui.imageInfoLabel.setText(f"Resolution\t: {width}x{height}\nFile type \t: {file_type}")

                # Add EXIF info to the self.ui.imageExifLabel
                items = [
                    ("Camera\t\t", f"{self.ui.imageLabel.image.exif_wrapper.get('Image Make')} {self.ui.imageLabel.image.exif_wrapper.get('Image Model')}"),
                    ("Software\t\t", self.ui.imageLabel.image.exif_wrapper.get('Image Software')),
                    ("Lens model\t", self.ui.imageLabel.image.exif_wrapper.get('EXIF LensModel')),
                    ("Date\t\t", self.ui.imageLabel.image.exif_wrapper.get('Image DateTime')),
                    ("ISO\t\t", self.ui.imageLabel.image.exif_wrapper.get('EXIF ISOSpeedRatings')),
                    ("FNumber\t", self.ui.imageLabel.image.exif_wrapper.get('EXIF FNumber')),
                    ("Exposure\t", self.ui.imageLabel.image.exif_wrapper.get('EXIF ExposureTime')),
                    ("Focal length\t", self.ui.imageLabel.image.exif_wrapper.get('EXIF FocalLength')),
                    ("Focal length FF\t", self.ui.imageLabel.image.exif_wrapper.get('EXIF FocalLengthIn35mmFilm'))
                ]
                exif_info = "\n".join(f"{k}: {v}" for k, v in items if v)
                self.ui.imageExifLabel.setText(exif_info)

                QApplication.processEvents()  # Force UI update to allow the image being shown while the detection is running
                # A zero-delay timer to schedule a task to run as soon as the main thread is free.
                # This will ensure the image appears, and then the detection kicks off right away
                QTimer.singleShot(0, self.detect_fish)

    def on_model_selected(self, index):
        model_name = self.ui.modelSelectComboBox.itemText(index)
        model_path = os.path.join(self.models_dir, model_name)
        try:
            self.detector = Detector(model_path)
            print(f"Loaded model: {model_path}")
        except IOError as e:
            self.ui.imageLabel.setText(f"Error loading model: {e}")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isdir(path):
                self.open_folder(path)
                break
            elif os.path.isfile(path) and path.lower().endswith(self.SUPPORTED_FORMATS):
                self.open_file(path)
                break
        event.acceptProposedAction()

    def open_file(self, file_path):
        folder_path = os.path.dirname(file_path)
        self.current_folder_path = folder_path
        # Clear existing list and main image
        self.model.setStringList([])
        self.current_image_path = None
        self.ui.imageLabel.clear()
        image_files = sorted([f for f in os.listdir(folder_path)
                               if f.lower().endswith(self.SUPPORTED_FORMATS)])
        self.model.setStringList(image_files)
        
        # Select the dropped file in the list view
        try:
            index = image_files.index(os.path.basename(file_path))
            self.ui.imageListView.setCurrentIndex(self.model.index(index))
            self.on_image_selected(self.model.index(index))
        except ValueError:
            self.ui.imageLabel.setText(f"Error: {os.path.basename(file_path)} not found in folder.")

    def display_image(self, image_path):
        self.current_image_path = image_path
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            self.ui.imageLabel.setPixmap(pixmap)
        else:
            self.ui.imageLabel.setText(f"Cannot load image:\n{os.path.basename(self.current_image_path)}")
            self.ui.imageLabel.setAlignment(Qt.AlignCenter)

    def detect_fish(self):
        if not self.ui.imageLabel.image:
            return

        confidence = self.ui.confidenceSlider.value() / 100.0
        nms = self.ui.nmsSlider.value() / 100.0

        # Skip detection if the values haven't changed
        if confidence == self.last_confidence and nms == self.last_nms:
            # Still update the crop band, e.g. padding could have changed
            self.update_crop_band()
            return

        try:
            start_time = time.perf_counter()
            results = self.detector.detect(self.ui.imageLabel.image, confidence_threshold=confidence, nms_threshold=nms)
            end_time = time.perf_counter()            
            detection_time_ms = (end_time - start_time) * 1000

            self._update_detection_info(
                objects=len(results),
                confidence=f"{max((det[1] for det in results), default=0):.4f}",
                time=f"{detection_time_ms:.2f} ms"
            )

            self.ui.imageLabel.set_detection_boxes(results)
            self.update_crop_band()

            # Cache the new values
            self.last_confidence = confidence
            self.last_nms = nms

        except Exception as e:
            self.ui.imageLabel.setText(f"Error detecting fish: {e}")

    def _get_current_crop_settings(self):
        """Gets crop settings from the UI."""
        if self.ui.rb_crop_to_top_conf.isChecked():
            crop_mode = 'top_confidence'
        elif self.ui.rb_crop_largest_area.isChecked():
            crop_mode = 'largest_area'
        else:
            crop_mode = None

        padding_percentage = self.ui.paddingSlider.value() / 100.0
        ratio_str = self.ui.cropRatioComboBox.currentText()
        ratio_w, ratio_h = map(int, ratio_str.split(':'))
        aspect_ratio = (ratio_w, ratio_h)

        return crop_mode, padding_percentage, aspect_ratio

    def update_crop_band(self):
        if not self.ui.imageLabel.image or not self.ui.imageLabel.orig_detection_rects:
            self.ui.imageLabel.crop_band.hide()
            self.ui.actionCropSaveImage.setEnabled(False)
            return

        # The detections in imageLabel are (QRect, score, class_id)
        # convert them to ((x,y,w,h), score, class_id) for calculate_crop_rect
        detections = [
            ((d[0].x(), d[0].y(), d[0].width(), d[0].height()), d[1], d[2])
            for d in self.ui.imageLabel.orig_detection_rects
        ]

        crop_mode, padding_percentage, aspect_ratio = self._get_current_crop_settings()

        if not crop_mode:
            self.ui.imageLabel.crop_band.hide()
            self.ui.actionCropSaveImage.setEnabled(False)
            return

        image_shape = self.ui.imageLabel.image.image_data.shape
        crop_tuple = ModelViewer._calculate_crop_rect(detections, image_shape, crop_mode, padding_percentage, aspect_ratio)

        if not crop_tuple or crop_tuple[2] <= 0 or crop_tuple[3] <= 0:
            self.ui.imageLabel.crop_band.hide()
            self.ui.actionCropSaveImage.setEnabled(False)
            return

        crop_rect = QRect(*crop_tuple)
        self.ui.imageLabel.set_crop_box(crop_rect)
        self.ui.actionCropSaveImage.setEnabled(True)
        self.ui.actionCropSaveAllImages.setEnabled(True)

    def crop_save_image(self):
        if not self.current_image_path or not self.ui.imageLabel.last_crop_rect:
            return

        base_name, ext = os.path.splitext(os.path.basename(self.current_image_path))
        cropped_dir = os.path.join(self.current_folder_path, "cropped")
        os.makedirs(cropped_dir, exist_ok=True) # Create the output directory
        output_path = os.path.join(cropped_dir, f"{base_name}_cropped{ext}")
        rect = self.ui.imageLabel.last_crop_rect
        crop_tuple = (rect.x(), rect.y(), rect.width(), rect.height())
        image_utils.crop_image_file(self.current_image_path, output_path, crop_tuple)


    def crop_save_all_images(self):
        if not self.current_folder_path:
            return

        try:
            # Create the output directory
            cropped_dir = os.path.join(self.current_folder_path, "cropped")
            os.makedirs(cropped_dir, exist_ok=True)

            image_files = self.model.stringList()
            total_files = len(image_files)

            progress_dialog = QProgressDialog("Cropping images...", "Cancel", 0, total_files, self)
            progress_dialog.setWindowModality(Qt.WindowModal)
            progress_dialog.setAutoClose(True)

            crop_mode, padding_percentage, aspect_ratio = self._get_current_crop_settings()
            if not crop_mode:
                self.ui.statusBar.showMessage("No crop mode selected.", 5000)
                return

            for i, file_name in enumerate(image_files):
                progress_dialog.setValue(i)
                progress_dialog.setLabelText(f"Processing {i+1}/{total_files}: {file_name}")
                QApplication.processEvents()

                if progress_dialog.wasCanceled():
                    break

                image_path = os.path.join(self.current_folder_path, file_name)
                
                # Load image
                image = ImageObject(image_path)

                # Detect
                confidence = self.ui.confidenceSlider.value() / 100.0
                nms = self.ui.nmsSlider.value() / 100.0
                results = self.detector.detect(image, confidence_threshold=confidence, nms_threshold=nms)

                if not results:
                    continue

                # Get crop rect
                image_shape = image.image_data.shape
                crop_tuple = ModelViewer._calculate_crop_rect(results, image_shape, crop_mode, padding_percentage, aspect_ratio)

                # Validate crop rect, if faulty, skip
                if not crop_tuple or crop_tuple[2] <= 0 or crop_tuple[3] <= 0:
                    print(f"Skipping {file_name}: invalid crop rectangle, crop_tuple: {crop_tuple}")
                    continue

                # Crop and save
                base_name, ext = os.path.splitext(file_name)
                output_path = os.path.join(cropped_dir, f"{base_name}_cropped{ext}")
                image_utils.crop_image_file(image_path, output_path, crop_tuple)
                #image.crop(crop_tuple)
                #image.save_as(output_path)

            progress_dialog.setValue(total_files)
            self.ui.statusBar.showMessage("Finished cropping all images.", 5000)

        except Exception as e:
            print(f"Error cropping all images: {e}")
            self.ui.statusBar.showMessage(f"Error cropping all images: {e}", 5000)
        
    def closeEvent(self, event):
        # Clean up resources, if any
        print("Closing application...")
        super().closeEvent(event)
