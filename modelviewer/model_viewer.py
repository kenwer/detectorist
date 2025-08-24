import os


from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog
from PySide6.QtGui import QPixmap
from PySide6.QtCore import QDir, Qt, QStringListModel, QRect, QTimer

from modelviewer._version import __version__
from modelviewer.model_viewer_gui import Ui_ModelViewerUI

from .detector import Detector
from .image_label import ImageLabel
from .utils import get_model_path

class ModelViewer(QMainWindow):
    SUPPORTED_FORMATS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.heic', '.heif', '.hif', '.arw')

    def __init__(self):
        super().__init__()

        self.current_image_path = None
        self.current_folder_path = None
        self.last_confidence = None
        self.last_nms = None
        
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
        self.ui.cropAction.setEnabled(False)
        self.ui.resetCropAction.triggered.connect(self.reset_crop)

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

            if not image_files:
                self.ui.imageLabel.setText("No supported images found in folder.")
                return

            self.model.setStringList(image_files)
            if image_files:
                # Select the first image in the list view
                first_index = self.model.index(0)
                self.ui.imageListView.setCurrentIndex(first_index)
                self.on_image_selected(first_index)
            else:
                self.ui.imageLabel.setText("No supported images found in folder.")


    def on_image_selected(self, index):
        file_name = self.model.stringList()[index.row()]
        if self.current_folder_path:
            self.current_image_path = os.path.join(self.current_folder_path, file_name)
            self.ui.statusBar.showMessage(file_name)
            # TODO: show the image dimension and other info at the imageInfoLabel
            #self.ui.imageInfoLabel.setText()
            
            if self.ui.imageLabel.replace_image(self.current_image_path):
                self.last_confidence = None  # Reset for new image
                self.last_nms = None  # Reset for new image
                self.ui.numDetectionsLabel.setText("0")

                # Add EXIF info to the self.ui.imageExifLabel
                items = [
                    ("Camera\t\t", f"{self.ui.imageLabel.image.exif.get('Image Make')} {self.ui.imageLabel.image.exif.get('Image Model')}"),
                    ("Software\t\t", self.ui.imageLabel.image.exif.get('Image Software')),
                    ("Lens model\t", self.ui.imageLabel.image.exif.get('EXIF LensModel')),
                    ("Date\t\t", self.ui.imageLabel.image.exif.get('Image DateTime')),
                    ("ISO\t\t", self.ui.imageLabel.image.exif.get('EXIF ISOSpeedRatings')),
                    ("FNumber\t", self.ui.imageLabel.image.exif.get('EXIF FNumber')),
                    ("Exposure\t", self.ui.imageLabel.image.exif.get('EXIF ExposureTime')),
                    ("Focal length\t", self.ui.imageLabel.image.exif.get('EXIF FocalLength')),
                    ("Focal length FF\t", self.ui.imageLabel.image.exif.get('EXIF FocalLengthIn35mmFilm'))
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
            return

        print("Detecting fish...")

        try:
            results = self.detector.detect(self.ui.imageLabel.image, confidence_threshold=confidence, nms_threshold=nms)
            print(f"-> Detected {len(results)} fish")

            # Update the number of detections label
            self.ui.numDetectionsLabel.setText(str(len(results)))

            self.ui.imageLabel.set_detection_boxes(results)

            # Cache the new values
            self.last_confidence = confidence
            self.last_nms = nms

        except Exception as e:
            self.ui.imageLabel.setText(f"Error detecting fish: {e}")

    def reset_crop(self):
        if self.ui.imageLabel.image:
            self.ui.imageLabel.setPixmap(QPixmap(self.current_image_path))

    def crop_image(self):
        # TODO unclear which box to use when multiple are detected.
        pass

        # if not self.ui.imageLabel.image or not self.ui.imageLabel.detection_band.isVisible():
        #     return

        # original_size = self.ui.imageLabel.image.image_data.shape[1], self.ui.imageLabel.image.image_data.shape[0]
        # scaled_size = self.ui.imageLabel.pixmap().size()

        # # Calculate the scale factors
        # x_scale = original_size[0] / scaled_size.width()
        # y_scale = original_size[1] / scaled_size.height()

        # # Get the rubber band geometry (in label coordinates)
        # rect = self.ui.imageLabel.detection_band.geometry()

        # # Scale the rectangle to original image coordinates
        # x = int(rect.x() * x_scale)
        # y = int(rect.y() * y_scale)
        # w = int(rect.width() * x_scale)
        # h = int(rect.height() * y_scale)

        # # Create a new QRect for cropping
        # crop_rect = QRect(x, y, w, h)

        # self.ui.imageLabel.image.crop(crop_rect)
        # # Update pixmap
        # self.ui.imageLabel.setImageData(self.ui.imageLabel.image.image_data)

        # # Hide the rubber band after cropping
        # self.ui.imageLabel.detection_band.hide()