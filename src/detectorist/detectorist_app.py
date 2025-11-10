import csv
import os
import subprocess
import sys
import time

import piexif
import pillow_heif
from PySide6.QtCore import QDir, QRect, QStringListModel, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QMainWindow,
    QProgressDialog,
)

from detectorist._version import __version__

from .about_dialog import Ui_AboutDialog
from .detector import Detector
from .detectorist_app_gui import Ui_DetectoristAppUI
from .image_label import ImageLabel
from .image_object import ImageObject
from .utils import get_model_path

# The Non-Maximum Suppression threshold used for object detection
NMS_THRESHOLD = 0.4

class DetectoristApp(QMainWindow):


    @staticmethod
    def _calculate_single_crop_rect(detections: list, image_height: int, image_width: int, crop_mode: str, padding_percentage: float, aspect_ratio: tuple[int, int]) -> tuple[int, int, int, int] | None:
        """
        Calculates a single crop rectangle crop rectangle based on detections and parameters.

        Args:
            detections: A list of detections, where each detection is a tuple ((x, y, w, h), score, class_id).
            image_height: The height of the image.
            image_width: The width of the image.
            crop_mode: 'top_confidence' or 'largest_area'.
            padding_percentage: Padding to add around the bounding box, as a float (e.g., 0.1 for 10%).
            aspect_ratio: A tuple (width, height) for the target aspect ratio.

        Returns:
            A tuple (x, y, w, h) for the crop rectangle, or None if no rectangle could be calculated.
        """
        if not detections:
            return None

        # The detection boxes are tuples of (x, y, w, h)
        if crop_mode == 'top_confidence':
            top_detection = max(detections, key=lambda d: d[1])
            x, y, w, h = top_detection[0]
        elif crop_mode == 'largest_area':
            left = min(d[0][0] for d in detections)
            top = min(d[0][1] for d in detections)
            right = max(d[0][0] + d[0][2] for d in detections)
            bottom = max(d[0][1] + d[0][3] for d in detections)
            x, y, w, h = left, top, right - left, bottom - top
        else:
            print(f"Warning {crop_mode}: invalid crop mode for _calculate_single_crop_rect")
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
        # If the crop rectangle is larger than the image, scale it down
        scale = 1.0
        if w > image_width:
            scale = image_width / w
        if h > image_height:
            scale = min(scale, image_height / h)

        if scale < 1.0:
            new_w = int(w * scale)
            new_h = int(h * scale)
            x += (w - new_w) // 2
            y += (h - new_h) // 2
            w = new_w
            h = new_h

        # If the crop rectangle is outside the image, move it
        if x < 0:
            x = 0
        if y < 0:
            y = 0
        if x + w > image_width:
            x = image_width - w
        if y + h > image_height:
            y = image_height - h

        return (x, y, w, h)

    @staticmethod
    def _calculate_crop_rectangles(detections: list, image_height: int, image_width: int, crop_mode: str, padding_percentage: float, aspect_ratio: tuple[int, int]) -> list[tuple[int, int, int, int]]:
        """
        Calculates crop rectangles based on detections and parameters.

        Args:
            detections: A list of detections, where each detection is a tuple ((x, y, w, h), score, class_id).
            image_height: The height of the image.
            image_width: The width of the image.
            crop_mode: 'top_confidence' or 'largest_area'.
            padding_percentage: Padding to add around the bounding box, as a float (e.g., 0.1 for 10%).
            aspect_ratio: A tuple (width, height) for the target aspect ratio.

        Returns:
            A list of tuples (x, y, w, h) for the crop rectangles.
        """
        if not detections:
            return []

        if crop_mode == 'all_detected_objects': # We might have more than one crop rectangle
            crop_rects = []
            # For 'all_detected_objects', we treat each detection individually
            for detection in detections:
                # For 'all_detected_objects', we treat each detection individually with 'top_confidence'
                rect = DetectoristApp._calculate_single_crop_rect([detection], image_height, image_width, 'top_confidence', padding_percentage, aspect_ratio)
                if rect:
                    crop_rects.append(rect)
            return crop_rects
        else: # Just a single crop rectangle
            rect = DetectoristApp._calculate_single_crop_rect(detections, image_height, image_width, crop_mode, padding_percentage, aspect_ratio)
            return [rect] if rect else []

    def __init__(self):
        super().__init__()

        self.current_image_path = None
        self.current_folder_path = None
        self.last_confidence = None

        # Ensure opener is registered (otherwise the native code will segfault)
        pillow_heif.register_heif_opener()

        # Set up the UI
        self.ui = Ui_DetectoristAppUI()
        self.ui.setupUi(self)
        self.setWindowTitle(f"Detectorist {__version__}")

        # Debounce timer for detection
        self.detection_timer = QTimer(self)
        self.detection_timer.setSingleShot(True)
        self.detection_timer.setInterval(500)  # 500ms delay
        self.detection_timer.timeout.connect(self.detect_objects)

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
        self.ui.detectObjectAction.triggered.connect(self.detect_objects)
        self.ui.imageListView.selectionModel().currentChanged.connect(self.on_image_selected)
        self.ui.actionCropSaveImage.triggered.connect(self.crop_save_image)
        self.ui.actionCropSaveAllImages.triggered.connect(self.crop_save_all_images)
        self.ui.actionAbout.triggered.connect(self.show_about_dialog)
        self.ui.actionSort_images_by_object_class.triggered.connect(self.sort_images_by_class_into_folders)

        # Delayed Sliders and SpinBoxes (because they are emitted very often)
        self.ui.confidenceSlider.valueChanged.connect(self.request_detection)
        self.ui.confidenceSpinBox.valueChanged.connect(self.request_detection)

        # Immediate trigger
        self.ui.confidenceSlider.sliderReleased.connect(self.detect_objects)
        self.ui.confidenceSpinBox.editingFinished.connect(self.detect_objects)


        # Connect crop controls
        self.ui.rb_crop_to_top_conf.toggled.connect(self.update_crop_bands)
        self.ui.rb_crop_largest_area.toggled.connect(self.update_crop_bands)
        self.ui.rb_crop_all_detected_objects.toggled.connect(self.update_crop_bands)
        self.ui.cropRatioComboBox.currentIndexChanged.connect(self.update_crop_bands)
        self.ui.paddingSlider.valueChanged.connect(self.update_crop_bands)

        self.ui.cb_comp_cam_exposure.toggled.connect(self.on_exposure_compensation_toggled)

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

            # Filter the selected directory for supported files
            image_files = sorted([f for f in os.listdir(folder_path)
                           if f.lower().endswith(ImageObject.get_supported_extensions())])

            if image_files:
                self.model.setStringList(image_files)
                first_index = self.model.index(0) # Select the first image in the list view
                self.ui.imageListView.setCurrentIndex(first_index)
                self.on_image_selected(first_index)
                self.ui.actionCropSaveAllImages.setEnabled(True)
                self.ui.actionSort_images_by_object_class.setEnabled(True)
            else:
                self.ui.imageLabel.set_detection_boxes([])
                self.ui.imageLabel.hide_bands()
                self._update_detection_info()
                self.ui.actionCropSaveImage.setEnabled(False)
                self.ui.actionCropSaveAllImages.setEnabled(False)
                self.ui.actionSort_images_by_object_class.setEnabled(False)
                self.ui.imageLabel.setText("No supported images found in folder.")


    def on_image_selected(self, index):
        file_name = self.model.stringList()[index.row()]
        if self.current_folder_path:
            self.current_image_path = os.path.join(self.current_folder_path, file_name)
            self.ui.statusBar.showMessage(file_name)

            if self.ui.imageLabel.replace_image(self.current_image_path):
                self.last_confidence = None  # Reset for new image
                self._update_detection_info() # Reset for new detection

                if self.ui.imageLabel.image:
                    self.ui.imageLabel.image.exposure_correction = self.ui.cb_comp_cam_exposure.isChecked()

                height, width = self.ui.imageLabel.image.height, self.ui.imageLabel.image.width
                original_bpc = self.ui.imageLabel.image.original_bpc
                file_type = self.ui.imageLabel.image.file_extension.upper()[1:]
                self.ui.imageInfoLabel.setText(f"File type \t: {file_type}\nResolution\t: {width}x{height}\nBits per channel\t: {original_bpc}")

                self.ui.imageExifLabel.setText("") # Clear previous EXIF info
                # Extract EXIF data and show it if available
                if self.ui.imageLabel.image.exif_data:
                    # Camera Make
                    camera_make = self.ui.imageLabel.image.exif_data['0th'].get(piexif.ImageIFD.Make, b'').decode('utf-8', errors='ignore').strip()

                    # Camera Model
                    camera_model = self.ui.imageLabel.image.exif_data['0th'].get(piexif.ImageIFD.Model, b'').decode('utf-8', errors='ignore').strip()

                    # Combine Make and Model to form Camera info
                    camera_info = f"{camera_make} {camera_model}".strip()

                    # Software
                    software = self.ui.imageLabel.image.exif_data['0th'].get(piexif.ImageIFD.Software, b'').decode('utf-8', errors='ignore').strip()

                    # Lens Model
                    lens_model = self.ui.imageLabel.image.exif_data['Exif'].get(piexif.ExifIFD.LensModel, b'').decode('utf-8', errors='ignore').strip()

                    # Date and Time
                    date_time = self.ui.imageLabel.image.exif_data['0th'].get(piexif.ImageIFD.DateTime, b'').decode('utf-8', errors='ignore').strip()

                    # GPS coordinates
                    gps_coordinates = self.ui.imageLabel.image.get_gps_coordinates_from_exif()

                    # ISO
                    iso = self.ui.imageLabel.image.exif_data['Exif'].get(piexif.ExifIFD.ISOSpeedRatings, None)
                    iso = None

                    # F-Number
                    fnumber = self.ui.imageLabel.image.exif_data['Exif'].get(piexif.ExifIFD.FNumber, None)
                    if fnumber:
                        # Convert from rational number to float
                        fnumber = fnumber[0] / fnumber[1]

                    # Exposure Time
                    exposure_time = self.ui.imageLabel.image.exif_data['Exif'].get(piexif.ExifIFD.ExposureTime, None)
                    if exposure_time:
                        # Convert from rational number to readable fraction
                        exposure_time = f"1/{int(1/exposure_time[0])}" if exposure_time[0] != 0 else None

                    # Exposure Compensation
                    exposure_comp = self.ui.imageLabel.image.exif_data['Exif'].get(piexif.ExifIFD.ExposureBiasValue, None)
                    if exposure_comp:
                        # Convert from rational number to float
                        exposure_comp = exposure_comp[0] / exposure_comp[1]

                    # Focal Length
                    focal_length = self.ui.imageLabel.image.exif_data['Exif'].get(piexif.ExifIFD.FocalLength, None)
                    if focal_length:
                        # Convert from rational number to float
                        focal_length = focal_length[0] / focal_length[1]

                    # Focal Length FF (Full Frame Equivalent)
                    focal_length_ff = self.ui.imageLabel.image.exif_data['Exif'].get(piexif.ExifIFD.FocalLengthIn35mmFilm, None)
                    if focal_length_ff:
                        # Convert from rational number to float, or use directly if it's an int
                        if isinstance(focal_length_ff, tuple):
                            focal_length_ff = focal_length_ff[0] / focal_length_ff[1]

                    # print(f"  Camera: {camera_info}")
                    # print(f"  Software: {software}")
                    # print(f"  Lens Model: {lens_model}")
                    # print(f"  Date: {date_time}")
                    # print(f"  GPS Info: {gps_coordinates}")
                    # print(f"  ISO: {iso}")
                    # print(f"  FNumber: {fnumber}")
                    # print(f"  Exposure: {exposure_time}")
                    # print(f"  Exposure Comp: {exposure_comp}")
                    # print(f"  Focal Length: {focal_length}")
                    # print(f"  Focal Length FF: {focal_length_ff}")

                    # Add EXIF info to the self.ui.imageExifLabel
                    items = [
                        ("Camera\t", camera_info),
                        ("Software\t", software),
                        ("Lens model\t", lens_model),
                        ("Date\t", date_time),
                        ("GPS coords\t", gps_coordinates),
                        ("ISO\t", iso),
                        ("FNumber\t", fnumber),
                        ("Exposure\t", exposure_time),
                        ("Exp. comp.\t", exposure_comp),
                        ("Focal length\t", focal_length),
                        ("Focal len. FF\t", focal_length_ff)
                    ]
                    exif_info = "\n".join(f"{k}: {v}" for k, v in items if v)
                    self.ui.imageExifLabel.setText(exif_info)

                QApplication.processEvents()  # Force UI update to allow the image being shown while the detection is running
                # A zero-delay timer to schedule a task to run as soon as the main thread is free.
                # This will ensure the image appears, and then the detection kicks off right away
                QTimer.singleShot(0, self.detect_objects)

    def on_model_selected(self, index):
        model_name = self.ui.modelSelectComboBox.itemText(index)
        model_path = os.path.join(self.models_dir, model_name)
        try:
            self.detector = Detector(model_path)
            print(f"Loaded model: {model_path}")

            if self.ui.imageLabel.image:
                self.last_confidence = None
                self._update_detection_info()
                self.ui.imageLabel.set_detection_boxes([])
                QTimer.singleShot(0, self.detect_objects)

        except OSError as e:
            self.ui.imageLabel.setText(f"Error loading model: {e}")

    def on_exposure_compensation_toggled(self, checked: bool):
        if self.ui.imageLabel.image:
            self.ui.imageLabel.image.exposure_correction = checked

    def show_about_dialog(self):
        about_dialog = QDialog(self)
        about_ui = Ui_AboutDialog()
        about_ui.setupUi(about_dialog)
        about_ui.versionLabel.setText(f"Version: {__version__}")
        about_dialog.exec()

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
            elif os.path.isfile(path) and path.lower().endswith(ImageObject.get_supported_extensions()):
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
                               if f.lower().endswith(ImageObject.get_supported_extensions())])
        self.model.setStringList(image_files)

        # Select the dropped file in the list view
        try:
            index = image_files.index(os.path.basename(file_path))
            self.ui.imageListView.setCurrentIndex(self.model.index(index))
            self.on_image_selected(self.model.index(index))
        except ValueError:
            self.ui.imageLabel.setText(f"Error: {os.path.basename(file_path)} not found in folder.")

    def detect_objects(self):
        if not self.ui.imageLabel.image:
            return

        confidence = self.ui.confidenceSlider.value() / 100.0

        # Skip detection if the value hasn't changed
        if confidence == self.last_confidence:
            # Still update the crop bands, e.g. padding could have changed
            self.update_crop_bands()
            return

        try:
            start_time = time.perf_counter()
            results = self.detector.detect(self.ui.imageLabel.image, confidence_threshold=confidence, nms_threshold=NMS_THRESHOLD)
            end_time = time.perf_counter()
            detection_time_ms = (end_time - start_time) * 1000

            self._update_detection_info(
                objects=len(results),
                confidence=f"{max((det[1] for det in results), default=0):.4f}",
                time=f"{detection_time_ms:.2f} ms"
            )

            self.ui.imageLabel.set_detection_boxes(results)
            self.update_crop_bands()

            # Cache the new value
            self.last_confidence = confidence

        except Exception as e:
            self.ui.imageLabel.setText(f"Error detecting objects: {e}")

    def _get_current_crop_settings(self):
        """Gets crop settings from the UI."""
        if self.ui.rb_crop_all_detected_objects.isChecked():
            crop_mode = 'all_detected_objects'
        elif self.ui.rb_crop_to_top_conf.isChecked():
            crop_mode = 'top_confidence'
        elif self.ui.rb_crop_largest_area.isChecked():
            crop_mode = 'largest_area'
        else:
            self.ui.imageLabel.hide_bands()
            self.ui.actionCropSaveImage.setEnabled(False)
            self.ui.actionCropSaveAllImages.setEnabled(False)
            crop_mode = None

        padding_percentage = self.ui.paddingSlider.value() / 100.0
        ratio_str = self.ui.cropRatioComboBox.currentText()

        if ratio_str == "aspect ratio: same as source image":
            if self.ui.imageLabel.image:
                height, width = self.ui.imageLabel.image.height, self.ui.imageLabel.image.width
                aspect_ratio = (width, height)
            else:
                # Default to something sensible if no image, though this path is unlikely
                aspect_ratio = (1, 1)
        else:
            # Handle strings like "3:2 (landscape)"
            ratio_part = ratio_str.split(' ')[0]
            try:
                ratio_w, ratio_h = map(int, ratio_part.split(':'))
                aspect_ratio = (ratio_w, ratio_h)
            except ValueError:
                # Fallback for any unexpected format
                print(f"Warning: Could not parse aspect ratio '{ratio_str}'. Defaulting to 1:1.")
                aspect_ratio = (1, 1)

        return crop_mode, padding_percentage, aspect_ratio

    def update_crop_bands(self):
        if not self.ui.imageLabel.image or not self.ui.imageLabel.orig_detection_rects:
            self.ui.imageLabel.hide_bands()
            self.ui.actionCropSaveImage.setEnabled(False)
            return

        # The detections in imageLabel are (QRect, score, class_id)
        # convert them to ((x,y,w,h), score, class_id) for calculate_crop_rect
        detections = [
            ((d[0].x(), d[0].y(), d[0].width(), d[0].height()), d[1], d[2])
            for d in self.ui.imageLabel.orig_detection_rects
        ]

        crop_mode, padding_percentage, aspect_ratio = self._get_current_crop_settings()
        crop_tuples = DetectoristApp._calculate_crop_rectangles(detections, self.ui.imageLabel.image.height, self.ui.imageLabel.image.width, crop_mode, padding_percentage, aspect_ratio)
        crop_rects = [QRect(*crop_tuple) for crop_tuple in crop_tuples if crop_tuple and crop_tuple[2] > 0 and crop_tuple[3] > 0]

        if not crop_rects:
            self.ui.imageLabel.hide_bands()
            self.ui.actionCropSaveImage.setEnabled(False)
            self.ui.actionCropSaveAllImages.setEnabled(False)
            return

        self.ui.imageLabel.set_crop_boxes(crop_rects)
        self.ui.actionCropSaveImage.setEnabled(True)
        self.ui.actionCropSaveAllImages.setEnabled(True)

    def _create_output_dir(self):
        """
        Create the output directory for the images, encoding the date and model name.
        Returns the paths to the output directory.
        """

        #timestamp = time.strftime("%Y%m%d")
        confidence = self.ui.confidenceSlider.value()
        model_name = os.path.splitext(self.ui.modelSelectComboBox.currentText())[0]
        output_dir = os.path.join(self.current_folder_path, f"detectorist_conf-{confidence}_{model_name}")
        os.makedirs(output_dir, exist_ok=True)
        return output_dir

    def _create_crop_dirs(self, output_dir):
        """
        Creates the output directories for the cropped and non-cropped images inside the given directory
        Returns the paths to the cropped and not-cropped directories.
        """
        cropped_dir = os.path.join(output_dir, "cropped")
        not_cropped_dir = os.path.join(output_dir, "not-cropped")
        os.makedirs(cropped_dir, exist_ok=True)
        os.makedirs(not_cropped_dir, exist_ok=True)
        return cropped_dir, not_cropped_dir

    def _open_native_file_manager(self, path):
        """Opens a folder in the native (OS specicic) file manager."""
        path = os.path.normpath(path)
        if sys.platform == 'win32': # Windows
            os.startfile(path)
        elif sys.platform == 'darwin': # macOS
            subprocess.Popen(['open', path])
        elif os.name == 'posix': # Linux
            subprocess.Popen(['xdg-open', path])

    def crop_save_image(self):
        """Crops and saves the currently displayed image based on the last crop rectangle."""
        if not self.ui.imageLabel.image or not self.ui.imageLabel.last_crop_rects:
            return

        output_dir = self._create_output_dir()
        cropped_dir, _ = self._create_crop_dirs(output_dir)

        for i, rect in enumerate(self.ui.imageLabel.last_crop_rects):
            crop_tuple = (rect.x(), rect.y(), rect.width(), rect.height())
            base, ext = os.path.splitext(os.path.basename(self.current_image_path))
            if len(self.ui.imageLabel.last_crop_rects) > 1:
                file_name = f"{base}_crop_{i}{ext}"
            else:
                file_name = f"{base}_crop{ext}"
            output_path = os.path.join(cropped_dir, file_name)
            self.ui.imageLabel.image.save_cropped(crop_tuple, output_path)
        self._open_native_file_manager(output_dir)

    def _process_all_images(self, process_name: str, setup_callback: callable, process_image_callback: callable):
        """
        Helper method that encapsulates the loop that goes through all the images.
        It covers the progress dialog, image loading, and object detection.
        This helper accepts a setup_callback for any pre-processing steps (like preparing directories)
        and a process_callback to execute the specific action (cropping or sorting) for each image.
        """
        if not self.current_folder_path:
            return

        image_files = self.model.stringList()
        if not image_files:
            return

        try:
            output_dir = self._create_output_dir()

            state = setup_callback(output_dir)
            if state is None:
                return

            total_files = len(image_files)
            progress_dialog = QProgressDialog(f"{process_name}...", "Cancel", 0, total_files, self)
            progress_dialog.setWindowModality(Qt.WindowModal)
            progress_dialog.setAutoClose(True)

            confidence = self.ui.confidenceSlider.value() / 100.0

            log_file_path = os.path.join(output_dir, "detections.csv")
            with open(log_file_path, "w", newline="") as log_file:
                csv_writer = csv.writer(log_file)
                csv_writer.writerow(["Filename", "Highest confidence score", "Class name", "Number of detected objects", "Subdirectory"])

                cancelled = False
                for i, file_name in enumerate(image_files):
                    progress_dialog.setValue(i)
                    progress_dialog.setLabelText(f"Processing {i+1}/{total_files}: {file_name}")
                    QApplication.processEvents()

                    if progress_dialog.wasCanceled():
                        cancelled = True
                        break

                    image_path = os.path.join(self.current_folder_path, file_name)
                    image = ImageObject.create(image_path)
                    image.exposure_correction = self.ui.cb_comp_cam_exposure.isChecked()
                    results = self.detector.detect(image, confidence_threshold=confidence, nms_threshold=NMS_THRESHOLD)

                    log_data = process_image_callback(image, results, output_dir, **state)
                    if log_data:
                        csv_writer.writerow(log_data)

            if not cancelled:
                self.ui.statusBar.showMessage(f"Finished {process_name.lower()}.", 5000)
            else:
                self.ui.statusBar.showMessage(f"{process_name} cancelled.", 5000)

            self._open_native_file_manager(output_dir)
            progress_dialog.close()

        except Exception as e:
            print(f"Error during {process_name}: {e}")
            self.ui.statusBar.showMessage(f"Error during {process_name}: {e}", 5000)

    def crop_save_all_images(self):
        """Crops and saves all images in the current folder based on detections and crop settings."""
        def setup(output_dir):
            crop_mode, padding_percentage, aspect_ratio = self._get_current_crop_settings()

            cropped_dir, not_cropped_dir = self._create_crop_dirs(output_dir)
            return {
                "crop_mode": crop_mode,
                "padding_percentage": padding_percentage,
                "aspect_ratio": aspect_ratio,
                "cropped_dir": cropped_dir,
                "not_cropped_dir": not_cropped_dir
            }

        def process_image_for_cropping(image, results, output_dir, **state):
            if not results:
                image.copy_image(state["not_cropped_dir"])
                return os.path.basename(image.image_path), 0, "N/A", 0, os.path.basename(state["not_cropped_dir"])

            top_detection = max(results, key=lambda d: d[1])
            confidence_score = top_detection[1]
            class_name = top_detection[2]

            crop_tuples = DetectoristApp._calculate_crop_rectangles(results, image.height, image.width, state["crop_mode"], state["padding_percentage"], state["aspect_ratio"])

            if not crop_tuples:
                print(f"Warning {os.path.basename(image.image_path)}: invalid crop rectangle, crop_tuples: {crop_tuples}")
                image.copy_image(state["not_cropped_dir"])
                return os.path.basename(image.image_path), confidence_score, class_name, len(results), os.path.basename(state["not_cropped_dir"])

            base, ext = os.path.splitext(os.path.basename(image.image_path))
            for i, crop_tuple in enumerate(crop_tuples):
                if len(crop_tuples) > 1:
                    file_name = f"{base}_crop_{i}{ext}"
                else:
                    file_name = f"{base}_crop{ext}"
                output_path = os.path.join(state["cropped_dir"], file_name)
                image.save_cropped(crop_tuple, output_path)

            return os.path.basename(image.image_path), confidence_score, class_name, len(results), os.path.basename(state["cropped_dir"])

        self._process_all_images("Cropping images", setup, process_image_for_cropping)

    def sort_images_by_class_into_folders(self):
        """Sorts images into folders based on the detected object class name."""
        def setup(output_dir):
            return {} # Return empty dict for state

        def process_image_for_sorting(image, results, output_dir, **state):
            if results:
                top_detection = max(results, key=lambda d: d[1])
                confidence_score = top_detection[1]
                class_name = top_detection[2]
                class_dir = os.path.join(output_dir, class_name)
                os.makedirs(class_dir, exist_ok=True)
                image.copy_image(class_dir)
                return os.path.basename(image.image_path), confidence_score, class_name, len(results), class_name
            else:
                no_detection_dir = os.path.join(output_dir, "no-detection")
                os.makedirs(no_detection_dir, exist_ok=True)
                image.copy_image(no_detection_dir)
                return os.path.basename(image.image_path), 0, "no-detection", 0, "no-detection"

        self._process_all_images("Sorting images", setup, process_image_for_sorting)

    def closeEvent(self, event):
        # Clean up resources, if any
        print("Closing application...")
        super().closeEvent(event)
