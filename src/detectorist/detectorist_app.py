import csv
import os
import subprocess
import sys

import pillow_heif
from PySide6.QtCore import (
    Q_ARG,
    QDir,
    QMetaObject,
    QRect,
    Qt,
    QThread,
    QTimer,
    Signal,
)
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
from .image_list_model import ImageListModel
from .image_object import ImageObject
from .utils import get_model_path
from .worker import DetectionWorker

# The Non-Maximum Suppression threshold used for object detection
NMS_THRESHOLD = 0.4

class DetectoristApp(QMainWindow):
    # Signal to request processing in the worker thread
    request_processing = Signal(str, float, float, bool)

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
        self.last_opened_directory = QDir.homePath()

        # Ensure opener is registered (otherwise the native code will segfault)
        pillow_heif.register_heif_opener()

        # Set up the UI
        self.ui = Ui_DetectoristAppUI()
        self.ui.setupUi(self)
        self.setWindowTitle(f"Detectorist {__version__}")

        # Debounce timer for processing
        self.processing_timer = QTimer(self)
        self.processing_timer.setSingleShot(True)
        self.processing_timer.setInterval(200)  # 200ms delay
        self.processing_timer.timeout.connect(self.trigger_processing)

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

        self.model = ImageListModel()
        self.ui.imageListView.setModel(self.model)
        self.ui.imageListView.setAcceptDrops(True) # Enable drag and drop for imageListView
        self.setAcceptDrops(True) # Enable drag and drop for the main window

        # Connect signals
        self.ui.openImagesAction.triggered.connect(self.open_images)
        self.ui.openFolderAction.triggered.connect(self.open_folder)
        self.ui.imageListView.selectionModel().currentChanged.connect(self.on_image_selected)
        self.ui.actionCropSaveImage.triggered.connect(self.crop_save_image)
        self.ui.actionCropSaveAllImages.triggered.connect(self.crop_save_all_images)
        self.ui.actionCropSaveSelectedImages.triggered.connect(self.crop_save_selected_images)
        self.ui.imageListView.selectionModel().selectionChanged.connect(self._update_crop_save_selected_images_action_state)
        self.ui.actionAbout.triggered.connect(self.show_about_dialog)
        self.ui.actionSort_images_by_object_class.triggered.connect(self.sort_images_by_class_into_folders)

        # Delayed/debounced Slider and SpinBoxe (because they are emitted very often as they both change)
        self.ui.confidenceSlider.valueChanged.connect(self.debounce_processing_trigger)
        self.ui.confidenceSpinBox.valueChanged.connect(self.debounce_processing_trigger)

        # Immediate trigger
        self.ui.confidenceSlider.sliderReleased.connect(self.trigger_processing_immediately)
        self.ui.confidenceSpinBox.editingFinished.connect(self.trigger_processing_immediately)

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

        # Setup worker thread, to offload image loading and detection, so the GUI remains responsive.
        self.thread = QThread()
        self.worker = DetectionWorker()
        self.worker.moveToThread(self.thread)

        # Connect signals/slots for worker
        self.request_processing.connect(self.worker.process_image)
        self.worker.model_loaded.connect(self.handle_model_loaded)
        self.worker.image_loaded.connect(self.handle_image_loaded)
        self.worker.detection_complete.connect(self.handle_detection_complete)
        self.worker.error.connect(self.handle_worker_error)
        self.ui.modelSelectComboBox.currentIndexChanged.connect(self.on_model_selected)

        # Start the thread and load initial model
        self.thread.start()
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

    def _load_images_from_paths(self, file_paths: list[str]):
        supported_files = sorted({f for f in file_paths if f.lower().endswith(ImageObject.get_supported_extensions())})

        if not supported_files:
            # Handle UI state for no images
            self.ui.imageLabel.set_detection_boxes([])
            self.ui.imageLabel.hide_bands()
            self._update_detection_info()
            self.ui.actionCropSaveImage.setEnabled(False)
            self.ui.actionCropSaveSelectedImages.setEnabled(False)
            self.ui.actionCropSaveAllImages.setEnabled(False)
            self.ui.actionSort_images_by_object_class.setEnabled(False)
            self.ui.imageLabel.setText("No supported images found or selected.")
            self.model.clear()
            return

        # Clear existing list and main image
        self.model.clear()
        self.current_image_path = None
        self.ui.imageLabel.clear()

        self.ui.imageLabel.setText("Loading Images...")
        self.model.setImagePaths(supported_files)
        QApplication.processEvents() # Ensure UI updates

        # Select the first image in the list view
        first_file_path = supported_files[0]
        try:
            index = supported_files.index(first_file_path)
            self.ui.imageListView.setCurrentIndex(self.model.index(index))
            self.on_image_selected(self.model.index(index))
        except ValueError:
            print(f"Error: Could not find {first_file_path} in the list.")
            self.ui.imageLabel.setText(f"Error: Could not find {os.path.basename(first_file_path)} in the list.")

        self.ui.actionCropSaveImage.setEnabled(True)
        self.ui.actionCropSaveAllImages.setEnabled(True)
        self.ui.actionCropSaveSelectedImages.setEnabled(True)
        self.ui.actionSort_images_by_object_class.setEnabled(True)

    def open_images(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Open Image(s)",
            QDir.homePath(),
            f"Images ({' '.join(['*' + ext for ext in ImageObject.get_supported_extensions()])})"
        )
        if file_paths:
            self._load_images_from_paths(file_paths)

    def open_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Open Folder", QDir.homePath())
        if folder_path:
            image_files_basenames = sorted([f for f in os.listdir(folder_path)
                           if f.lower().endswith(ImageObject.get_supported_extensions())])
            full_paths = [os.path.join(folder_path, f) for f in image_files_basenames]
            self._load_images_from_paths(full_paths)

    def on_image_selected(self, index):
        if self.model.rowCount() == 0: # Check if any images are loaded
            return

        # Get the full path of the selected image from our internal list
        # The index.row() corresponds to the position in the model
        new_image_path = self.model.data(index, ImageListModel.FullPathRole)

        if new_image_path == self.current_image_path:
            return  # No need to reload the same image

        self.current_image_path = new_image_path
        file_name = os.path.basename(new_image_path) # Get basename for display purposes
        self.ui.statusBar.showMessage(f"Loading {file_name}...")

        # Clear previous results and show loading state
        self.ui.imageLabel.setText("Loading image...")
        self.ui.imageLabel.hide_bands()
        self._update_detection_info()
        self.ui.imageExifLabel.setText("")
        QApplication.processEvents()

        # Request the worker to load and process the image
        self.trigger_processing_immediately()

    def debounce_processing_trigger(self):
        """Starts or restarts the debounce timer."""
        self.processing_timer.start()

    def trigger_processing_immediately(self):
        """Triggers processing immediately and cancels any pending debounced trigger."""
        self.processing_timer.stop() # cancel any pending debounced processing requests
        self.trigger_processing()    # and start processing right away

    def trigger_processing(self):
        """Emits a signal to the worker to start processing the current image."""
        if not self.current_image_path:
            return

        confidence = self.ui.confidenceSlider.value() / 100.0
        exposure_correction = self.ui.cb_comp_cam_exposure.isChecked()

        self.request_processing.emit(self.current_image_path, confidence, NMS_THRESHOLD, exposure_correction)

    def handle_model_loaded(self, success: bool, message: str):
        """Handles the result of loading a model in the worker."""
        if success:
            print(message)
            # If an image is currently displayed, trigger a new detection with the new model.
            if self.current_image_path:
                self.trigger_processing()
        else:
            self.ui.imageLabel.setText(message)
            print(message)

    def handle_image_loaded(self, image_path: str, image_object: ImageObject):
        """Handles the image_loaded signal from the worker."""
        if image_path != self.current_image_path:
            return  # Stale result for a different image

        if not image_object:
            self.ui.imageLabel.clear()
            self.ui.imageLabel.setText(f"Could not load image:\n{image_path}")
            return

        self.ui.imageLabel.replace_image(image_object)
        self.ui.statusBar.showMessage(os.path.basename(image_path))

        # Update the Image info label
        height, width = image_object.height, image_object.width
        original_bpc = image_object.original_bpc
        file_type = image_object.file_extension.upper()[1:]
        self.ui.imageInfoLabel.setText(f"File type \t: {file_type}\nResolution\t: {width}x{height}\nBits per channel\t: {original_bpc}")

        # Update the EXIF info label
        self.ui.imageExifLabel.setText(image_object.get_exif_summary())


    def handle_detection_complete(self, image_path: str, results: list, detection_time_ms: float):
        """Handles the detection_complete signal from the worker."""
        if image_path != self.current_image_path:
            return  # Stale result (this can happen if user quickly switches images)

        self._update_detection_info(
            objects=len(results),
            confidence=f"{max((det[1] for det in results), default=0):.4f}",
            time=f"{detection_time_ms:.2f} ms"
        )

        self.ui.imageLabel.set_detection_boxes(results)
        self.update_crop_bands()

    def handle_worker_error(self, image_path: str, message: str):
        """Handles an error signal from the worker."""
        if image_path != self.current_image_path:
            return  # Stale error for a different image (ignored)

        print(f"Worker error for {image_path}: {message}")
        self.ui.imageLabel.setText(f"Error: {message}")
        self._update_detection_info()

    def on_model_selected(self, index):
        model_name = self.ui.modelSelectComboBox.itemText(index)
        model_path = os.path.join(self.models_dir, model_name)
        # The worker lives in another thread, so we must use invokeMethod to call it safely.
        QMetaObject.invokeMethod(self.worker, "load_model", Qt.QueuedConnection, Q_ARG(str, model_path))

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
        urls = event.mimeData().urls()
        if not urls:
            return

        files_to_load = set()
        folders_to_scan = []

        for url in urls:
            path = url.toLocalFile()
            if not url.isLocalFile():
                continue

            if os.path.isdir(path):
                folders_to_scan.append(path)
            elif os.path.isfile(path):
                files_to_load.add(path)

        if folders_to_scan:
            # Scan the first folder for images
            first_folder = folders_to_scan[0]
            folder_images = {
                os.path.join(first_folder, f)
                for f in os.listdir(first_folder)
                if f.lower().endswith(ImageObject.get_supported_extensions())
            }
            files_to_load.update(folder_images)

        if files_to_load:
            self._load_images_from_paths(list(files_to_load))

        event.acceptProposedAction()

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

    def _create_output_dir(self, base_dir: str):
        """
        Create the output directory for the images, encoding the date and model name.
        Returns the paths to the output directory.
        """

        #timestamp = time.strftime("%Y%m%d")
        confidence = self.ui.confidenceSlider.value()
        model_name = os.path.splitext(self.ui.modelSelectComboBox.currentText())[0]
        output_dir = os.path.join(base_dir, f"detectorist_conf-{confidence}_{model_name}")
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

    def _process_all_images(self, process_name: str, setup_callback: callable, process_image_callback: callable, image_files_to_process: list[str] = None):
        """
        Helper method that encapsulates the loop that goes through all the images.
        It covers the progress dialog, image loading, and object detection.
        This helper accepts a setup_callback for any pre-processing steps (like preparing directories)
        and a process_callback to execute the specific action (cropping or sorting) for each image.
        """
        if self.model.rowCount() == 0:
            return # No images loaded at all
        # Use the directory of the first loaded image as the base for output
        output_base_dir = os.path.dirname(self.model.imagePaths()[0])


        image_full_paths = image_files_to_process if image_files_to_process is not None else self.model.imagePaths()
        if not image_full_paths:
            return

        try:
            output_dir = self._create_output_dir(output_base_dir)

            # The detector lives in the worker thread. We can't access it directly.
            # For batch processing, we need a separate detector instance.
            model_path = os.path.join(self.models_dir, self.ui.modelSelectComboBox.currentText())
            batch_detector = Detector(model_path)

            state = setup_callback(output_dir)
            if state is None:
                return

            total_files = len(image_full_paths)
            progress_dialog = QProgressDialog(f"{process_name}...", "Cancel", 0, total_files, self)
            progress_dialog.setWindowModality(Qt.WindowModal)
            progress_dialog.setAutoClose(True)

            confidence = self.ui.confidenceSlider.value() / 100.0

            log_file_path = os.path.join(output_dir, "detections.csv")
            with open(log_file_path, "w", newline="") as log_file:
                csv_writer = csv.writer(log_file)
                csv_writer.writerow(["Filename", "Highest confidence score", "Class name", "Number of detected objects", "Subdirectory"])

                cancelled = False
                for i, image_path in enumerate(image_full_paths): # Iterate over full paths
                    file_name_display = os.path.basename(image_path) # Use basename for display
                    progress_dialog.setValue(i)
                    progress_dialog.setLabelText(f"Processing {i+1}/{total_files}: {file_name_display}")
                    QApplication.processEvents()

                    if progress_dialog.wasCanceled():
                        cancelled = True
                        break

                    image = ImageObject.create(image_path)
                    image.exposure_correction = self.ui.cb_comp_cam_exposure.isChecked()
                    results = batch_detector.detect(image, confidence_threshold=confidence, nms_threshold=NMS_THRESHOLD)

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

    def _crop_and_save_images_with_progress(self, process_name: str, image_files_to_process: list[str] = None):
        """
        Helper method that encapsulates the loop that goes through all the images for cropping.
        It covers the progress dialog, image loading, and object detection.
        """
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

        self._process_all_images(process_name, setup, process_image_for_cropping, image_files_to_process)

    def crop_save_all_images(self):
        """Crops and saves all images in the current folder based on detections and crop settings."""
        self._crop_and_save_images_with_progress("Cropping images")

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

    def crop_save_selected_images(self):
        """Crops and saves selected images in the current folder based on detections and crop settings."""
        selected_indexes = self.ui.imageListView.selectionModel().selectedIndexes()
        if not selected_indexes:
            return

        selected_image_files = [self.model.data(index, ImageListModel.FullPathRole) for index in selected_indexes]
        self._crop_and_save_images_with_progress("Cropping selected images", selected_image_files)

    def _update_crop_save_selected_images_action_state(self):
        """Enables/disables actionCropSaveSelectedImages based on imageListView selection."""
        selected_indexes = self.ui.imageListView.selectionModel().selectedIndexes()
        self.ui.actionCropSaveSelectedImages.setEnabled(len(selected_indexes) > 0)

    def closeEvent(self, event):
        # Clean up resources, if any
        print("Closing application...")
        self.thread.quit()
        self.thread.wait()
        super().closeEvent(event)
