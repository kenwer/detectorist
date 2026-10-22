import html
import logging
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pillow_heif
from PySide6.QtCore import (
    Q_ARG,
    QMetaObject,
    QRect,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QRadioButton,
)

from detectorist import __version__

from .about_dialog import show_about_dialog
from .batch_output import classification_csv_name, detections_csv_name, settings_json_name
from .batch_run import CropExportAction, run_batch
from .classifier import Classifier, class_matches, describe
from .crop_planner import CropMode, CropSettings, plan_crops
from .detection_style import taxon_styles
from .detector import Detector
from .export_layout import describe_export
from .image_cache import PrefetchPlanner
from .image_label import ImageLabel
from .image_list_model import ImageListModel
from .image_object import (
    ImageObject,
    filter_out_appledouble_files,
    is_supported_image,
    list_supported_images,
    supported_extensions,
)
from .manage_models import ManageModelsDialog
from .model_downloader import ModelDownloader
from .settings import Settings
from .shortcuts_dialog import ShortcutsDialog
from .toasts import show_error_toast, show_success_toast, show_warning_toast
from .ui_detectorist_app_gui import Ui_DetectoristAppUI
from .utils import (
    SharedFactory,
    contract_user_path,
    get_model_path,
    list_model_files,
    long_path,
    resolve_short_path,
    strip_model_ext,
)
from .worker import DetectionWorker

logger = logging.getLogger(__name__)

OUTPUT_DIR_NAME = "processed"  # export folder in each image folder, for any model or confidence


def image_name_filter(platform: str = sys.platform) -> str:
    """
    The name filter of the Open Image(s) dialog.

    The native dialogs of macOS and Windows match the patterns ignoring case.
    The GTK dialog of Linux desktops does not, and cameras write upper case
    extensions. There each letter is spelled as a character class, like
    *.[jJ][pP][gG], which also covers mixed case. Windows would take the
    brackets literally, hence the platform switch.
    """
    extensions = supported_extensions()
    if platform in ("win32", "darwin"):
        patterns = ["*" + ext for ext in extensions]
    else:
        patterns = [
            "*" + "".join(f"[{char}{char.upper()}]" if char.isalpha() else char for char in ext)
            for ext in extensions
        ]
    return f"Images ({' '.join(patterns)})"


NO_MODELS_MESSAGE = "No models available<br/>Use File -> Download Models"

# The crop aspect ratio combo box's entries, in order. Settings save the ratio, see aspect_ratio_setting().
ASPECT_RATIOS: list[tuple[str, tuple[int, int] | str]] = [
    ("Same as source image", "source_image"),
    ("Same as detection frame", "detection_frame"),
    ("3:2 (landscape)", (3, 2)),
    ("4:3 (landscape)", (4, 3)),
    ("5:4 (landscape)", (5, 4)),
    ("16:9 (landscape)", (16, 9)),
    ("21:9 (landscape)", (21, 9)),
    ("1:1", (1, 1)),
    ("2:3 (portrait)", (2, 3)),
    ("3:4 (portrait)", (3, 4)),
    ("4:5 (portrait)", (4, 5)),
    ("9:16 (portrait)", (9, 16)),
    ("9:21 (portrait)", (9, 21)),
]


def aspect_ratio_setting(aspect: tuple[int, int] | str) -> str:
    """How settings store an aspect ratio: "3:2" for a ratio, and the name of a ratio taken from elsewhere."""
    return f"{aspect[0]}:{aspect[1]}" if isinstance(aspect, tuple) else aspect


def _count(number: int, noun: str) -> str:
    """A number with a noun in the matching form, e.g. "1 classification" or "20 classifications"."""
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


class DetectoristApp(QMainWindow):
    # Signal to request processing in the worker thread
    request_processing = Signal(str, bool, list, float)  # image_path, exposure_correction, prefetch_paths, min_detection_score
    request_classifier = Signal(str, list)  # model_path ("" for none), the classes it names (see class_matches)
    request_classification = Signal(str, float)  # image_path, min_detection_score

    def __init__(
        self,
        settings: Settings | None = None,
        models_dir: str | None = None,
        detector_factory: Callable[[str], Detector] = Detector,
        classifier_factory: Callable[[str, Sequence[str]], Classifier] = Classifier,
    ):
        """
        Args:
            settings: Persistent settings store. Defaults to the per-user store.
            models_dir: Folder scanned for model files. Defaults to get_model_path().
            detector_factory: Called with a model path to build a detector, by
                the worker for interactive use and here for each batch run.
            classifier_factory: Likewise for the classifier. The worker and the
                batch runs share the classifier it builds, as it takes
                hundreds of MB.
        """
        super().__init__()

        self.settings = settings if settings is not None else Settings()
        self._detector_factory = detector_factory
        self._classifier_factory = SharedFactory(classifier_factory)
        self.current_image_path = None
        self._prefetch_planner = PrefetchPlanner()
        self._all_detection_results: list = []
        self._last_detection_time_ms: float = 0.0
        self._last_classification_time_ms: float = 0.0
        # What the classifier said about the current image's detections, keyed by box
        self._taxonomy_by_box: dict = {}
        self._classification_pending = False
        # The classifier the user chose, by filename. It stays the choice while a
        # detection model is loaded that it does not apply to.
        self._preferred_classifier: str | None = None
        # Classes of the loaded detection model. They decide which classifiers are offered.
        self._detector_class_names: list[str] = []
        self._last_output_dir: str | None = None
        # When the Manage Models dialog is open it reports download progress
        # itself, so app-level toasts are suppressed to avoid double feedback.
        self._models_dialog_open = False
        self._batch_running = False  # keeps the batch actions disabled while a Batch Run is running
        self._shortcuts_dialog: ShortcutsDialog | None = None

        # Ensure opener is registered (otherwise the native code will segfault)
        pillow_heif.register_heif_opener()

        # Set up the UI
        self.ui = Ui_DetectoristAppUI()
        self.ui.setupUi(self)
        self.setWindowTitle(f"Detectorist {__version__}")

        # Replace the image_label from the ui file with our custom ImageLabel
        # but keep/re-use the sizePolicy and alignment from the .ui file
        sizePolicy = self.ui.image_label.sizePolicy()
        alignment = self.ui.image_label.alignment()
        self.ui.image_label = ImageLabel(self, self.ui.central_widget)
        self.ui.image_label.setSizePolicy(sizePolicy)
        self.ui.image_label.setAlignment(alignment)
        self.ui.image_splitter.replaceWidget(0, self.ui.image_label)
        # Only the results can be dragged away, the image keeps a minimum height
        self.ui.image_splitter.setCollapsible(0, False)
        self.ui.image_label.linkActivated.connect(self._open_recent_folder)
        self.ui.image_label.setAcceptDrops(True) # Enable drag and drop for image_label
        # Hovering a detection marks its results row, as hovering a row highlights its detection
        self.ui.image_label.detection_hovered.connect(self.ui.results_table.set_bold_box)
        self.ui.results_table.row_hovered.connect(self.ui.image_label.highlight_box)

        # A permanent widget, so the status bar's messages (the image's name, notices) do not replace it
        self.ui.results_summary_label = QLabel()
        self.ui.status_bar.addPermanentWidget(self.ui.results_summary_label)
        # The results only describe a shown image, so the welcome and message screens get the full height
        self.ui.results_table.setVisible(False)
        self.ui.image_label.image_shown_changed.connect(self.ui.results_table.setVisible)

        for label, aspect in ASPECT_RATIOS:
            self.ui.crop_ratio_combo_box.addItem(label, aspect_ratio_setting(aspect))

        # Snapshot the .ui file's built-in defaults before _load_settings() can override
        # them, so "Reset Settings to Defaults" has real values to restore.
        self._default_detection_confidence = self.ui.detection_confidence_slider.value()
        self._default_taxon_confidence = self.ui.taxon_confidence_slider.value()
        self._default_padding = self.ui.padding_slider.value()
        self._default_aspect_ratio_index = self.ui.crop_ratio_combo_box.currentIndex()
        self._default_auto_correct_exposure = self.ui.cb_comp_cam_exposure.isChecked()
        self._default_crop = self.ui.cb_crop.isChecked()
        self._default_crop_mode = next(
            mode for mode, radio in self._crop_mode_radios().items() if radio.isChecked()
        )

        self.model = ImageListModel()
        self.ui.image_list_view.setModel(self.model)
        self.ui.image_list_view.setAcceptDrops(True) # Enable drag and drop for imageListView
        self.setAcceptDrops(True) # Enable drag and drop for the main window

        # Add context menu for the image list view
        self.ui.image_list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.ui.image_list_view.customContextMenuRequested.connect(self.show_image_list_view_context_menu)

        # Add actions (of the context menu) to the QListView (for its shortcut to be active)
        # Since we add it to the QListView, it's only active if it has focus, aligning with Cmd+A Ctrl+A behavior
        self.ui.image_list_view.addAction(self.ui.remove_selected_images_from_list_action)
        self.ui.image_list_view.addAction(self.ui.locate_image_in_filemanager_action)
        self.ui.image_list_view.addAction(self.ui.copy_filenames_to_clipboard_action)
        self.ui.image_list_view.addAction(self.ui.copy_export_remove_action)

        # Connect signals
        self.ui.open_images_action.triggered.connect(self.open_images)
        self.ui.open_folder_action.triggered.connect(self.open_folder)
        self.ui.clear_image_list_action.triggered.connect(self.clear_image_list)
        self.ui.image_list_view.selectionModel().currentChanged.connect(self.on_image_selected)
        self.ui.crop_and_export_all_images_action.triggered.connect(self.crop_and_export_all_images)
        self.ui.crop_and_export_selected_images_action.triggered.connect(self.crop_and_export_selected_images)
        self.ui.image_list_view.selectionModel().selectionChanged.connect(self._update_selection_dependent_actions_state)
        self.ui.about_action.triggered.connect(self.show_about_dialog)
        self.ui.shortcuts_action.triggered.connect(self.show_shortcuts_dialog)
        self.ui.locate_image_in_filemanager_action.triggered.connect(self._locate_selected_image_in_file_manager)
        self.ui.copy_filenames_to_clipboard_action.triggered.connect(self._copy_selected_filenames_to_clipboard)
        self.ui.remove_selected_images_from_list_action.triggered.connect(self._remove_selected_images_from_list)
        self.ui.copy_export_remove_action.triggered.connect(self._copy_export_remove_selected_images)
        self.ui.clear_recent_folders_action.triggered.connect(self._clear_recent_folders)
        self.ui.import_settings_action.triggered.connect(self._import_settings)
        self.ui.export_settings_action.triggered.connect(self._export_settings)
        self.ui.reset_settings_action.triggered.connect(self._reset_settings)
        self.ui.manage_models_action.triggered.connect(self.show_manage_models_dialog)
        self.ui.open_output_folder_action.triggered.connect(self._open_last_output_folder)

        # Detection confidence slider/spinbox update the display filter only (no re-inference)
        self.ui.detection_confidence_slider.valueChanged.connect(self._display_filtered_results)
        self.ui.detection_confidence_spin_box.valueChanged.connect(self._display_filtered_results)
        # The worker only names boxes at or above the detection confidence, so a lower one asks for the rest.
        # Debounced: the worker handles one request at a time, and the ticks of a drag queued
        # up there would delay the next image.
        self._classification_timer = QTimer(self)
        self._classification_timer.setSingleShot(True)
        self._classification_timer.setInterval(200)
        self._classification_timer.timeout.connect(self._request_classification)
        self.ui.detection_confidence_slider.valueChanged.connect(self._classification_timer.start)
        self.ui.taxon_confidence_slider.valueChanged.connect(self._display_filtered_results)

        # Connect crop controls
        self.ui.rb_crop_most_confident_detection.toggled.connect(self.update_crop_bands)
        self.ui.rb_crop_best_classification.toggled.connect(self.update_crop_bands)
        self.ui.rb_crop_all_detected_objects.toggled.connect(self.update_crop_bands)
        self.ui.rb_crop_centered_obj.toggled.connect(self.update_crop_bands)
        self.ui.crop_ratio_combo_box.currentIndexChanged.connect(self.update_crop_bands)
        self.ui.padding_slider.valueChanged.connect(self.update_crop_bands)

        self.ui.cb_comp_cam_exposure.toggled.connect(self.on_exposure_compensation_toggled)
        self.ui.cb_crop.toggled.connect(self._on_crop_toggled)
        self.ui.toggle_masks_action.toggled.connect(self.ui.image_label.set_masks_visible)
        self.ui.toggle_boxes_action.toggled.connect(self.ui.image_label.set_boxes_visible)
        self.ui.toggle_labels_action.toggled.connect(self.ui.image_label.set_labels_visible)
        self.ui.toggle_all_overlays_action.triggered.connect(self.toggle_all_overlays)

        # Connect model signals
        self.model.modelReset.connect(self._update_clear_image_list_action_state)
        self.model.modelReset.connect(self._update_selection_dependent_actions_state)

        self.models_dir = models_dir if models_dir is not None else get_model_path()

        # Shared model downloader (lives for the app's lifetime so downloads survive dialog close)
        self._model_downloader = ModelDownloader(self.models_dir, self)
        self._model_downloader.download_finished.connect(self._refresh_model_list)
        self._model_downloader.download_finished.connect(self._notify_model_download_finished)
        self._model_downloader.download_error.connect(self._notify_model_download_error)

        # Deferred loading placeholder: started when an image is selected,
        # stopped when it arrives. Cached images arrive within a few
        # milliseconds, so the placeholder never flashes for them.
        self._loading_indicator_timer = QTimer(self)
        self._loading_indicator_timer.setSingleShot(True)
        self._loading_indicator_timer.setInterval(200)
        self._loading_indicator_timer.timeout.connect(self._show_loading_indicator)

        # Setup worker thread, to offload image loading and detection, so the GUI remains responsive.
        self._worker_thread = QThread()
        self.worker = DetectionWorker(self._detector_factory, self._classifier_factory)
        self.worker.moveToThread(self._worker_thread)

        # Connect signals/slots for worker
        # DirectConnection runs process_image on this (GUI) thread: it only
        # updates lock-protected request state, and the worker loop must see a
        # new request immediately to abandon stale work and prefetches.
        self.request_processing.connect(self.worker.process_image, Qt.ConnectionType.DirectConnection)
        self.worker.model_loaded.connect(self.handle_model_loaded)
        self.worker.image_loaded.connect(self.handle_image_loaded)
        self.worker.detection_complete.connect(self.handle_detection_complete)
        self.worker.error.connect(self.handle_worker_error)
        self.worker.cache_updated.connect(self.model.setCachedPaths)
        self.worker.classification_complete.connect(self.handle_classification_complete)
        self.worker.classifier_error.connect(self.handle_classifier_error)
        self.request_classifier.connect(self.worker.set_classifier)
        self.request_classification.connect(self.worker.classify_image)
        self.ui.model_select_combo_box.currentIndexChanged.connect(self.on_model_selected)
        self.ui.classifier_combo_box.currentIndexChanged.connect(self._on_classifier_chosen)
        self.ui.class_filter_combo_box.currentIndexChanged.connect(self.on_class_filter_changed)

        # Start the thread
        self._worker_thread.start()

        # Find and populate models (must be after worker setup so _on_model_availability_changed can reach it)
        self._refresh_model_list()

        # Load settings (must be after UI setup and before triggering model load)
        self._restore_window_layout()
        self._load_settings()
        self._update_recent_folders_menu()
        self._show_welcome_state()

        # Load AI model (combo box index was set by _load_settings if a saved model exists)
        self.on_model_selected(self.ui.model_select_combo_box.currentIndex())

        # Auto-show download dialog if no models found
        if self.ui.model_select_combo_box.count() == 0:
            QTimer.singleShot(0, self.show_manage_models_dialog)

    def _restore_window_layout(self):
        """Apply the persisted window geometry and splitter state."""
        if self.settings.window_geometry:
            self.restoreGeometry(self.settings.window_geometry)
        if self.settings.main_splitter_state:
            self.ui.splitter.restoreState(self.settings.main_splitter_state)
        if self.settings.image_splitter_state:
            self.ui.image_splitter.restoreState(self.settings.image_splitter_state)

    def _load_settings(self):
        """
        Apply the persistent settings to the UI. The model combo
        box is set with its signals blocked, so the caller has to follow up
        with on_model_selected() to load the selected model in the worker. The
        classifier is selected once a model it applies to has loaded.
        """
        # Model selection
        if self.settings.detection_model:
            combo = self.ui.model_select_combo_box
            combo.blockSignals(True)
            idx = self._find_model_index(combo, self.settings.detection_model)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.blockSignals(False)

        # Classifier choice. At startup no detection model has loaded yet, so the
        # list stays at "No classifier" until handle_model_loaded refreshes it.
        # After Import Settings, the refresh selects the imported choice.
        self._preferred_classifier = self.settings.classification_model
        self._refresh_classifier_list()

        # Detection confidence (slider and spinbox are linked)
        if (detection_confidence := self.settings.detection_min_confidence_percent) is not None:
            self.ui.detection_confidence_slider.setValue(detection_confidence)

        # Taxon confidence (slider and spinbox are linked)
        if (taxon_confidence := self.settings.classification_min_confidence_percent) is not None:
            self.ui.taxon_confidence_slider.setValue(taxon_confidence)

        # Crop mode
        # A mode that is missing or no longer exists, like the removed union, falls back to the default
        crop_mode = CropMode.from_setting(self.settings.crop_mode) or self._default_crop_mode
        self._crop_mode_radios()[crop_mode].setChecked(True)

        # Aspect ratio
        # A ratio that is not offered keeps the current one
        if (index := self.ui.crop_ratio_combo_box.findData(self.settings.crop_aspect_ratio)) >= 0:
            self.ui.crop_ratio_combo_box.setCurrentIndex(index)

        # Padding
        if (padding := self.settings.crop_padding_percent) is not None:
            self.ui.padding_slider.setValue(padding)

        # Auto correct camera exposure bias
        if (auto_exposure := self.settings.image_correct_exposure) is not None:
            self.ui.cb_comp_cam_exposure.setChecked(auto_exposure)

        if (crop := self.settings.crop_images) is not None:
            self.ui.cb_crop.setChecked(crop)
        self._update_crop_controls()

    def _save_settings(self):
        """Save current UI state to persistent settings."""
        self.settings.save_current_version()

        # Window geometry and splitter state
        self.settings.window_geometry = self.saveGeometry()
        self.settings.main_splitter_state = self.ui.splitter.saveState()
        self.settings.image_splitter_state = self.ui.image_splitter.saveState()

        # Model selection
        self.settings.detection_model = self.ui.model_select_combo_box.currentData()

        # Classifier selection and taxon confidence
        self.settings.classification_model = self._preferred_classifier
        self.settings.classification_min_confidence_percent = self.ui.taxon_confidence_slider.value()

        # Detection confidence
        self.settings.detection_min_confidence_percent = self.ui.detection_confidence_slider.value()

        # Crop mode
        for mode, radio in self._crop_mode_radios().items():
            if radio.isChecked():
                self.settings.crop_mode = mode.value
                break

        # Aspect ratio
        self.settings.crop_aspect_ratio = self.ui.crop_ratio_combo_box.currentData()

        # Padding
        self.settings.crop_padding_percent = self.ui.padding_slider.value()

        # Auto correct camera exposure bias
        self.settings.image_correct_exposure = self.ui.cb_comp_cam_exposure.isChecked()
        self.settings.crop_images = self.ui.cb_crop.isChecked()

    def _clear_results(self):
        """Empties the results table and its summary, while no detection result is shown."""
        self.ui.results_table.clear()
        self.ui.results_summary_label.clear()

    def _show_message(self, text: str):
        """Shows text in place of the image, and drops what was detected in it."""
        self.ui.image_label.setText(text)
        self._clear_results()

    def _show_results(self, detections: list, threshold: float):
        """
        Lists the detections in the results table, and sums them up with how
        many of them are classified, and the time each took.
        """
        self.ui.results_table.show_detections(detections, self._taxonomy_by_box, threshold)
        summary = f"{_count(len(detections), 'object')} detected ({self._last_detection_time_ms:.0f} ms)."
        if self._taxonomy_by_box:
            # The time also covers the names of detections the filters hide
            classified = sum(d.box in self._taxonomy_by_box for d in detections)
            summary += f" {classified} of them classified ({self._last_classification_time_ms:.0f} ms)."
        self.ui.results_summary_label.setText(summary)

    def _load_images_from_paths(self, file_paths: list[str]) -> bool:
        """
        Replaces the image list with the supported images among file_paths.
        Without any, the list stays as it is, as a stray file dropped by
        mistake should not throw away a loaded folder. Returns whether
        images were loaded.
        """
        supported_files = sorted({f for f in file_paths if is_supported_image(f)})

        if not supported_files:
            if self.model.rowCount() == 0:
                self._show_message("No supported images found or selected.")
            else:
                # The image label is taken by the current image
                show_warning_toast(self, "No images to open", "No supported images found or selected.")
            return False

        # Clear existing list and main image
        self.model.clear()
        self.current_image_path = None
        self._prefetch_planner.reset()
        # Files on disk may have changed, so cached decodes are not trustworthy.
        # The queued invocation runs clear_cache on the worker thread, which is
        # the only thread allowed to touch the cache (no lock needed there).
        QMetaObject.invokeMethod(self.worker, "clear_cache", Qt.ConnectionType.QueuedConnection)

        self.ui.image_label.setText("Loading Images...")
        self.model.setImagePaths(supported_files)
        QApplication.processEvents() # Ensure UI updates

        # Enable actions that operate on all loaded images (only if a model is available)
        can_run = self.ui.model_select_combo_box.count() > 0 and not self._batch_running
        self.ui.crop_and_export_all_images_action.setEnabled(can_run)

        # Select the first image in the list view
        first_file_path = supported_files[0]
        try:
            index = supported_files.index(first_file_path)
            self.ui.image_list_view.setCurrentIndex(self.model.index(index))
            self.on_image_selected(self.model.index(index))
        except ValueError:
            logger.error("Could not find %s in the list.", first_file_path)
            self.ui.image_label.setText(f"Error: Could not find {os.path.basename(first_file_path)} in the list.")
        return True

    def open_images(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Open Image(s)",
            self.settings.last_folder,
            image_name_filter(),
            # Qt's own dialog would otherwise spell out all the patterns in its filter box
            options=QFileDialog.Option.HideNameFilterDetails,
        )
        if file_paths:
            self.settings.add_recent_folder(os.path.dirname(file_paths[0]))
            self._update_recent_folders_menu()
            self._load_images_from_paths(file_paths)

    def open_folder(self) -> None:
        folder_path = QFileDialog.getExistingDirectory(self, "Open Folder", self.settings.last_folder)
        if folder_path:
            self._open_folder_by_path(folder_path)

    def _list_folder_images(self, folder_path: str) -> list[str] | None:
        """
        Full paths of the supported images in a folder. Returns None after
        telling the user if the folder cannot be read, e.g. for lack of
        permission or because a network share or drive went away.
        """
        try:
            return [os.path.join(folder_path, f) for f in list_supported_images(folder_path)]
        except OSError as e:
            logger.warning("Could not read folder %s: %s", folder_path, e)
            show_warning_toast(
                self,
                "Could not open folder",
                f"{contract_user_path(folder_path)}:\n{e.strerror or e}",
            )
            return None

    def _open_folder_by_path(self, folder_path: str) -> None:
        """Open a folder and load its images. An unreadable folder leaves the current image list as it is."""
        full_paths = self._list_folder_images(folder_path)
        if full_paths is None:
            return
        if self._load_images_from_paths(full_paths):
            self.settings.add_recent_folder(folder_path)
            self._update_recent_folders_menu()

    def _update_recent_folders_menu(self) -> None:
        """Rebuild the Recent Folders submenu from settings."""
        self.ui.recent_folders_menu.clear()

        recent = self.settings.recent_folders
        if not recent:
            no_recent = self.ui.recent_folders_menu.addAction("No Recent Folders")
            no_recent.setEnabled(False)
        else:
            for path in recent:
                # Qt reads a single "&" in a menu text as mnemonic marker and hides it ("R&D" is shown as "RD"), "&&" is shown as "&".
                action = self.ui.recent_folders_menu.addAction(contract_user_path(path).replace("&", "&&"))
                action.triggered.connect(lambda checked, p=path: self._open_recent_folder(p))

        # Re-add the separator and Clear Recent action (defined in .ui, removed by clear())
        self.ui.recent_folders_menu.addSeparator()
        self.ui.clear_recent_folders_action.setEnabled(bool(recent))
        self.ui.recent_folders_menu.addAction(self.ui.clear_recent_folders_action)

    def _open_recent_folder(self, path: str) -> None:
        """Open a folder from the recent list."""
        if os.path.isdir(long_path(path)):
            self._open_folder_by_path(path)
        else:
            show_warning_toast(self, "Folder not found", f"The folder is no longer accessible:\n{path}")

    def _clear_recent_folders(self) -> None:
        """Clear the recent folders list."""
        self.settings.clear_recent_folders()
        self._update_recent_folders_menu()

    def _import_settings(self) -> None:
        """Import settings from a JSON file exported during a previous batch run."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Settings",
            self.settings.last_folder,
            "Settings Files (*.json)"
        )
        if not file_path:
            return

        try:
            self.settings.import_from_file(Path(file_path))
        except (OSError, ValueError) as e:
            logger.error("Could not import settings from %s: %s", file_path, e)
            show_error_toast(self, "Could not import settings", f"{os.path.basename(file_path)}: {e}")
            return
        self._load_settings()
        self.on_model_selected(self.ui.model_select_combo_box.currentIndex())
        self.ui.status_bar.showMessage("Settings imported.", 3000)

    def _export_settings(self) -> None:
        """Export current settings to a JSON file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Settings",
            self.settings.last_folder + "/settings.json",
            "Settings Files (*.json)"
        )
        if not file_path:
            return

        self._save_settings()
        self.settings.export_to_file(Path(file_path))
        self.ui.status_bar.showMessage("Settings exported.", 3000)

    def _reset_settings(self) -> None:
        """Reset all settings but the recent folders and window layout to their defaults after confirmation."""
        reply = QMessageBox.question(
            self,
            "Reset Settings",
            "Reset all settings to their defaults?\n"
            "Recent folders and window layout are not affected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.settings.reset_to_defaults()

        # _load_settings() only overwrites a widget when a persisted value exists, so it
        # can't restore a value that was just cleared. Re-apply the .ui defaults directly.
        self.ui.detection_confidence_slider.setValue(self._default_detection_confidence)
        self.ui.taxon_confidence_slider.setValue(self._default_taxon_confidence)
        self._preferred_classifier = None
        self.ui.classifier_combo_box.setCurrentIndex(0)
        self.ui.padding_slider.setValue(self._default_padding)
        self.ui.crop_ratio_combo_box.setCurrentIndex(self._default_aspect_ratio_index)
        self.ui.cb_comp_cam_exposure.setChecked(self._default_auto_correct_exposure)
        self._crop_mode_radios()[self._default_crop_mode].setChecked(True)
        self.ui.cb_crop.setChecked(self._default_crop)
        self._update_crop_controls()

        self._save_settings()
        self.ui.status_bar.showMessage("Settings reset to defaults.", 3000)

    def _show_welcome_state(self) -> None:
        parts = ['<span style="font-size: large;">Drop images or a folder with images</span><br/>']
        recents = self.settings.recent_folders
        if recents:
            parts.append('<span style="color: #000000;"><br/>You can also use File menu<br/><br/><br/><br/>Recent Folders:</span><br/>')
            for path in recents:
                name = html.escape(os.path.basename(path.rstrip(os.sep)))
                href = html.escape(path, quote=True)
                escaped_path = html.escape(contract_user_path(path))
                parts.append(
                    f'<br/><a href="{href}" style="color: #4b5563; font-weight: bold; text-decoration: none;">{name}</a>'
                    f'<br/><span style="color: #4b5563; font-size: small;">{escaped_path}</span><br>'
                )
        self._show_message("".join(parts))

    def clear_image_list(self):
        """Clears the image list and resets the application to its initial state."""
        self.model.clear()
        self.current_image_path = None
        self._all_detection_results = []

        self._show_welcome_state()
        self.ui.image_info_label.setText("")
        self.ui.image_exif_label.setText("")
        self.ui.status_bar.clearMessage()

        # Disable actions that depend on images being loaded
        # (Selection-dependent actions are handled via the modelReset signal)
        self.ui.crop_and_export_all_images_action.setEnabled(False)

    def on_image_selected(self, index):
        if not index.isValid():
            return

        # Get the full path of the selected image from our internal list
        # The index.row() corresponds to the position in the model
        new_image_path = self.model.data(index, ImageListModel.FullPathRole)

        if new_image_path is None:
            # This can happen if the model is cleared and the view hasn't updated yet
            return

        if new_image_path == self.current_image_path:
            return  # No need to reload the same image

        self.current_image_path = new_image_path
        self._all_detection_results = []

        if self.ui.model_select_combo_box.count() == 0:
            self._show_message(NO_MODELS_MESSAGE)
            self.ui.status_bar.clearMessage()
            return

        # Clear previous results. The loading placeholder is deferred so that
        # cache hits do not flash "Loading image..." for a single frame.
        self._loading_indicator_timer.start()
        self.ui.image_label.hide_bands()
        self._clear_results()
        self.ui.image_exif_label.setText("")

        # Request the worker to load and process the image
        self.trigger_processing()

    def _show_loading_indicator(self):
        """
        Shows the loading placeholder. Only reached when the image did not
        arrive within the timer interval, i.e. it was not served from the
        worker's cache.
        """
        self.ui.image_label.setText("Loading image...")
        if self.current_image_path:
            self.ui.status_bar.showMessage(f"Loading {os.path.basename(self.current_image_path)}...")

    def trigger_processing(self):
        """Emits a signal to the worker to start processing the current image."""
        if not self.current_image_path:
            return
        if self.ui.model_select_combo_box.count() == 0:
            return

        exposure_correction = self.ui.cb_comp_cam_exposure.isChecked()
        prefetch_hints = self._prefetch_planner.hints(self.model.imagePaths(), self.current_image_path)
        min_detection_score = self.ui.detection_confidence_slider.value() / 100.0
        self.request_processing.emit(self.current_image_path, exposure_correction, prefetch_hints, min_detection_score)

    def toggle_all_overlays(self):
        """Hides the masks, boxes and labels if any of them is shown, otherwise shows all of them."""
        # A disabled toggle, e.g. the masks of a detection model, keeps its state
        actions = [action for action in (self.ui.toggle_masks_action, self.ui.toggle_boxes_action,
                                         self.ui.toggle_labels_action) if action.isEnabled()]
        show = not any(action.isChecked() for action in actions)
        for action in actions:
            action.setChecked(show)

    def handle_model_loaded(self, success: bool, message: str, class_names: list, is_segmentation: bool):
        """Handles the result of loading a model in the worker."""
        self.ui.image_label.set_class_color_map(class_names)
        self.ui.toggle_masks_action.setEnabled(is_segmentation)
        self.ui.class_filter_combo_box.blockSignals(True)
        self.ui.class_filter_combo_box.clear()
        self.ui.class_filter_combo_box.addItem("All classes")
        for name in class_names:
            self.ui.class_filter_combo_box.addItem(name)
        self.ui.class_filter_combo_box.blockSignals(False)
        self._all_detection_results = []
        self._detector_class_names = class_names
        self._refresh_classifier_list()
        if success:
            logger.info(message)
            # If an image is currently displayed, trigger a new detection with the new model.
            if self.current_image_path:
                self.trigger_processing()
        else:
            self._show_message(message)
            logger.error(message)

    def handle_image_loaded(self, image_path: str, image_object: ImageObject):
        """Handles the image_loaded signal from the worker."""
        if image_path != self.current_image_path:
            return  # Stale result for a different image

        self._loading_indicator_timer.stop()

        if not image_object:
            self._show_message(f"Could not load image:\n{image_path}")
            return

        self.ui.image_label.replace_image(image_object)
        self.ui.status_bar.showMessage(os.path.basename(image_path))

        # Update the Image info label
        height, width = image_object.height, image_object.width
        original_bpc = image_object.original_bpc
        file_type = image_object.file_extension.upper()[1:]
        self.ui.image_info_label.setText(f"File type \t: {file_type}\nResolution\t: {width}x{height}\nBits per channel\t: {original_bpc}")

        # Update the EXIF info label
        self.ui.image_exif_label.setText(image_object.get_exif_summary())


    def handle_detection_complete(self, image_path: str, results: list, detection_time_ms: float):
        """Handles the detection_complete signal from the worker."""
        if image_path != self.current_image_path:
            return  # Stale result (this can happen if user quickly switches images)

        self._all_detection_results = results
        self._last_detection_time_ms = detection_time_ms
        # The names follow with classification_complete
        self._taxonomy_by_box = {}
        self._classification_pending = self.ui.classifier_combo_box.currentData() is not None
        self._display_filtered_results()

    def handle_classification_complete(self, image_path: str, taxonomy_by_box: dict, classification_time_ms: float):
        """Handles the classification_complete signal from the worker."""
        if image_path != self.current_image_path:
            return
        self._taxonomy_by_box = taxonomy_by_box
        self._classification_pending = False
        self._last_classification_time_ms = classification_time_ms
        self._display_filtered_results()

    def _request_classification(self):
        """Asks the worker to name the shown image's boxes down to the current detection confidence."""
        if self.current_image_path and self.ui.classifier_combo_box.currentData():
            self.request_classification.emit(self.current_image_path, self.ui.detection_confidence_slider.value() / 100.0)

    def handle_classifier_error(self, message: str):
        """Handles the classifier_error signal from the worker. The detections stay as they are."""
        show_error_toast(self, "Classifier error", message)

    def _selected_class_filter(self) -> str | None:
        """The class name chosen in the class filter, or None for "All classes"."""
        if self.ui.class_filter_combo_box.currentIndex() <= 0:
            return None
        return self.ui.class_filter_combo_box.currentText()

    def _filtered_results(self) -> list:
        """Returns detection results filtered by the current detection confidence and class filter selections."""
        detection_confidence = self.ui.detection_confidence_slider.value() / 100.0
        results = [d for d in self._all_detection_results if d.score >= detection_confidence]
        selected = self._selected_class_filter()
        if selected is None:
            return results
        return [d for d in results if d.class_name == selected]

    def _display_filtered_results(self):
        """Updates the UI with detection results filtered by the current class selection."""
        filtered = self._filtered_results()
        threshold = self.ui.taxon_confidence_slider.value() / 100.0
        self._show_results(filtered, threshold)
        tooltips = {box: describe(taxonomy, threshold) for box, taxonomy in self._taxonomy_by_box.items()}
        styles = taxon_styles(filtered, self._taxonomy_by_box, threshold)
        self.ui.image_label.set_detection_boxes(filtered, tooltips, styles)
        self.update_crop_bands()

    def on_class_filter_changed(self):
        """Re-displays detection results when the class filter selection changes."""
        self._display_filtered_results()

    def handle_worker_error(self, image_path: str, message: str):
        """Handles an error signal from the worker."""
        if image_path != self.current_image_path:
            return  # Stale error for a different image (ignored)

        self._loading_indicator_timer.stop()
        logger.error("Worker error for %s: %s", image_path, message)
        self._show_message(f"Error: {message}")
        self.ui.status_bar.clearMessage()
        show_error_toast(self, "Could not process image", f"{os.path.basename(image_path)}: {message}")

    def on_model_selected(self, index):
        if index < 0:
            return
        filename = self.ui.model_select_combo_box.itemData(index)
        model_path = os.path.join(self.models_dir, filename)
        # The worker lives in another thread, so we must use invokeMethod to call it safely.
        QMetaObject.invokeMethod(self.worker, "load_model", Qt.ConnectionType.QueuedConnection, Q_ARG(str, model_path))

    def on_exposure_compensation_toggled(self, checked: bool):
        if self.ui.image_label.image:
            self.ui.image_label.image.exposure_correction = checked
            self.ui.image_label.refresh_pixmap()

    def show_about_dialog(self):
        show_about_dialog(self)

    def show_shortcuts_dialog(self):
        if self._shortcuts_dialog is None:
            self._shortcuts_dialog = ShortcutsDialog(self)

        self._shortcuts_dialog.show()
        self._shortcuts_dialog.raise_()
        self._shortcuts_dialog.activateWindow()

    def show_manage_models_dialog(self):
        dialog = ManageModelsDialog(self._model_downloader, self.models_dir, self)
        dialog.models_changed.connect(self._refresh_model_list)
        self._models_dialog_open = True
        try:
            dialog.exec()
        finally:
            self._models_dialog_open = False

    def _notify_model_download_finished(self, filename: str):
        """Toasts a completed background download when the Manage Models dialog isn't shown."""
        if self._models_dialog_open:
            return
        name = self._model_downloader.filename_to_name.get(filename) or strip_model_ext(filename)
        show_success_toast(self, "Model downloaded", f"{name} is ready to use.")

    def _notify_model_download_error(self, message: str):
        """Toasts a failed background download when the Manage Models dialog isn't shown."""
        if self._models_dialog_open:
            return
        show_error_toast(self, "Model download failed", message)

    def _refresh_model_list(self):
        """
        Re-scan the models directory and update the model and classifier
        combo boxes. Detection models live in the top-level dir (for historical
        reasons). Classification models live in the "classifiers" subfolder.
        """
        previous_filename = self.ui.model_select_combo_box.currentData()
        self.ui.model_select_combo_box.clear()

        name_map = self._model_downloader.filename_to_name
        onnx_files = list_model_files(self.models_dir)
        self._refresh_classifier_list()

        combo = self.ui.model_select_combo_box
        combo.blockSignals(True)
        for filename in onnx_files:
            display_name = name_map.get(filename) or strip_model_ext(filename)
            combo.addItem(display_name, filename)

        # Restore previous selection by filename
        idx = self._find_model_index(combo, previous_filename)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)

        # If the selected model changed (e.g. first download), load it in the worker.
        # on_model_selected is not triggered automatically because signals were blocked.
        new_filename = combo.currentData()
        if new_filename and new_filename != previous_filename:
            self.on_model_selected(combo.currentIndex())

        self._on_model_availability_changed()

    def _refresh_classifier_list(self):
        """
        Update the classifier combo box with the classifiers in the models
        directory that name at least one class of the loaded detection model,
        and select the user's choice if it is among them.
        """
        combo = self.ui.classifier_combo_box
        previous_filename = combo.currentData()
        name_map = self._model_downloader.filename_to_name
        applicable = [
            filename for filename in list_model_files(self._model_downloader.classifiers_dir)
            if any(class_matches(self._model_downloader.classifies(filename), name) for name in self._detector_class_names)
        ]

        combo.blockSignals(True)
        combo.clear()
        combo.addItem("No classifier", None)
        for filename in applicable:
            combo.addItem(name_map.get(filename) or strip_model_ext(filename), filename)
        combo.setCurrentIndex(max(self._find_model_index(combo, self._preferred_classifier), 0))
        combo.blockSignals(False)
        combo.setEnabled(combo.count() > 1)
        self._update_classifier_controls()

        # Signals were blocked, so the change is loaded here without becoming the user's choice
        if combo.currentData() != previous_filename:
            self._load_selected_classifier()

    def _on_classifier_chosen(self):
        """Remembers the classifier picked in the combo box as the user's choice and loads it."""
        self._preferred_classifier = self.ui.classifier_combo_box.currentData()
        self._update_classifier_controls()
        self._load_selected_classifier()

    def _update_classifier_controls(self):
        """
        Greys out the taxon confidence and the labels action and hides the
        results' family, genus and species columns for "No classifier", as
        nothing is classified then.
        """
        active = self.ui.classifier_combo_box.currentData() is not None
        for widget in (self.ui.taxon_confidence_label, self.ui.taxon_confidence_slider,
                       self.ui.taxon_confidence_spin_box, self.ui.toggle_labels_action):
            widget.setEnabled(active)
        self.ui.results_table.set_taxonomy_visible(active)
        # Without a classifier the export is not sorted
        self._update_export_summary()

    def _load_selected_classifier(self):
        """
        Loads the classifier selected in the combo box in the worker, or
        unloads it for "No classifier", and has the shown image named again.
        """
        filename = self.ui.classifier_combo_box.currentData()
        model_path = os.path.join(self._model_downloader.classifiers_dir, filename) if filename else ""
        if not filename:
            # The worker drops its reference, so this frees the model
            self._classifier_factory.release()
        self.request_classifier.emit(model_path, self._model_downloader.classifies(filename) if filename else [])
        self._taxonomy_by_box = {}
        self._classification_pending = bool(filename and self.current_image_path)
        self._display_filtered_results()
        self._request_classification()

    def _find_model_index(self, combo: QComboBox, filename: str | None) -> int:
        """
        Index of the given model file in the combo box, or -1. A file that is
        gone resolves to the model that supersedes it, so the selection
        follows a model across an update instead of jumping to the first one
        in the list.
        """
        idx = combo.findData(filename)
        if idx < 0 and filename:
            successor = self._model_downloader.successor_of(filename)
            if successor:
                idx = combo.findData(successor)
        return idx

    def _on_model_availability_changed(self):
        """React to the model combo box becoming empty or populated."""
        has_models = self.ui.model_select_combo_box.count() > 0
        has_images = self.model.rowCount() > 0
        # A background download can finish during a Batch Run
        can_run = has_models and not self._batch_running

        # Enable/disable actions that require a model
        self.ui.crop_and_export_all_images_action.setEnabled(can_run and has_images)
        self.ui.crop_and_export_selected_images_action.setEnabled(
            can_run and self.ui.image_list_view.selectionModel().hasSelection()
        )

        if not has_models:
            self._show_message(NO_MODELS_MESSAGE)
            QMetaObject.invokeMethod(self.worker, "unload_model", Qt.ConnectionType.QueuedConnection)
        elif not has_images:
            self._show_welcome_state()

    @staticmethod
    def _dropped_paths(event) -> list[str]:
        """
        The local paths dragged in an event. Windows Explorer substitutes 8.3
        short names into drag-and-drop data when the real path exceeds
        MAX_PATH, and those cut the extension to three letters, so they are
        resolved back.
        """
        return [resolve_short_path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]

    @staticmethod
    def _is_one_folder(paths: list[str]) -> bool:
        """
        Whether the paths are one folder, images in one folder, or both. The
        image list holds a single folder, so the export has one source folder.
        Only parent folders are compared, as listing one mid-drag could stall
        on a slow share.
        """
        folders = {path if os.path.isdir(long_path(path)) else os.path.dirname(path) for path in paths}
        return len(folders) == 1

    def dragEnterEvent(self, event):
        # Refusing here shows the "not allowed" cursor before the user lets go
        paths = self._dropped_paths(event)
        if self._is_one_folder(paths) and any(os.path.isdir(long_path(path)) or is_supported_image(path) for path in paths):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        paths = self._dropped_paths(event)
        if not self._is_one_folder(paths):
            event.ignore()
            return

        folder = next((path for path in paths if os.path.isdir(long_path(path))), None)
        files_to_load = set(filter_out_appledouble_files([path for path in paths if os.path.isfile(long_path(path))]))
        skipped = sum(not is_supported_image(f) for f in files_to_load)

        # Load even if empty to report a readable folder without images (an unreadable one already warned)
        folder_read = False
        if folder is not None and (folder_images := self._list_folder_images(folder)) is not None:
            folder_read = True
            files_to_load.update(folder_images)

        if (files_to_load or folder_read) and self._load_images_from_paths(list(files_to_load)) and skipped:
            show_warning_toast(self, "Skipped files", f"Skipped {_count(skipped, 'unsupported file')}.")

        event.acceptProposedAction()

    def _crop_mode_radios(self) -> dict[CropMode, QRadioButton]:
        """The crop panel radio button for each CropMode."""
        return {
            CropMode.MOST_CONFIDENT_DETECTION: self.ui.rb_crop_most_confident_detection,
            CropMode.BEST_CLASSIFICATION: self.ui.rb_crop_best_classification,
            CropMode.MOST_CENTERED: self.ui.rb_crop_centered_obj,
            CropMode.EACH_OBJECT: self.ui.rb_crop_all_detected_objects,
        }

    def _get_current_crop_settings(self) -> CropSettings | None:
        """Gets crop settings from the UI, or None if no crop mode is selected."""
        crop_mode = next((mode for mode, radio in self._crop_mode_radios().items() if radio.isChecked()), None)
        if crop_mode is None:
            return None

        padding_percentage = self.ui.padding_slider.value() / 100.0
        _, aspect_ratio = ASPECT_RATIOS[self.ui.crop_ratio_combo_box.currentIndex()]
        return CropSettings(mode=crop_mode, padding=padding_percentage, aspect=aspect_ratio,
                            taxon_confidence=self.ui.taxon_confidence_slider.value() / 100.0)

    def update_crop_bands(self):
        """
        Frames the crops a Batch Run would export for the shown detections, none
        while the Crop checkbox is off. They are planned from the detections as the
        detector returned them, like in the Batch Run, not from the drawn boxes,
        which are clamped to the image.
        """
        image = self.ui.image_label.image
        crop_settings = self._get_current_crop_settings() if self.ui.cb_crop.isChecked() else None
        # Until the names arrive, a best classification band would frame the most
        # confident detection only to jump to the best classified one
        if (image is None or crop_settings is None
                or crop_settings.mode == CropMode.BEST_CLASSIFICATION and self._classification_pending):
            self.ui.image_label.set_crop_boxes([])
            return
        crop_tuples = plan_crops(self._filtered_results(), image.height, image.width, crop_settings, self._taxonomy_by_box)
        self.ui.image_label.set_crop_boxes([QRect(*crop_tuple) for crop_tuple in crop_tuples])

    def _open_native_file_manager(self, path):
        """Opens a folder in the native (OS specific) file manager, revealing the file if a file path is provided."""
        path = os.path.normpath(path)
        if sys.platform == 'win32':  # Windows
            if os.path.isfile(path):
                subprocess.Popen(['explorer', '/select,', path])
            else:
                subprocess.Popen(['explorer', path])
        elif sys.platform == 'darwin':  # macOS
            if os.path.isfile(path):
                subprocess.Popen(['open', '-R', path])
            else:
                subprocess.Popen(['open', path])
        elif os.name == 'posix':  # Linux
            dir_path = os.path.dirname(path) if os.path.isfile(path) else path
            subprocess.Popen(['xdg-open', dir_path])

    def _set_last_output_dir(self, path: str):
        """Remembers the latest export directory and enables the reveal action."""
        self._last_output_dir = path
        self.ui.open_output_folder_action.setEnabled(True)

    def _open_last_output_folder(self):
        """Reveals the most recent export directory in the native file manager."""
        if self._last_output_dir:
            self._open_native_file_manager(self._last_output_dir)


    def _run_batch_with_progress(self, process_name: str, action, output_dir_name: str,
                                 image_files_to_process: list[str] | None = None) -> bool:
        """
        Runs a Batch Run over the given images (or all loaded images) with a
        modal progress dialog, writing into the folder output_dir_name of the
        image folder, then exports the settings alongside the CSV and reveals
        the output directory.

        Returns:
            bool: True if every image was processed, False if the run was
                cancelled, an error occurred or some images failed.
        """
        if self.model.rowCount() == 0:
            return False # No images loaded at all

        image_full_paths = image_files_to_process if image_files_to_process is not None else self.model.imagePaths()
        if not image_full_paths:
            return False

        self._set_batch_actions_enabled(False)
        progress_dialog = None
        try:
            model_filename = self.ui.model_select_combo_box.currentData()
            detections_csv_filename = detections_csv_name(self.ui.detection_confidence_slider.value(), model_filename)

            total_files = len(image_full_paths)
            progress_dialog = QProgressDialog("Loading models...", "Cancel", 0, total_files, self)
            progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
            progress_dialog.setAutoClose(True)
            # Default minimumDuration is 4s, during which the dialog is invisible
            # but the window underneath stays fully clickable. Show it immediately
            # so the batch-actions guard below has a visible reason to exist.
            progress_dialog.setMinimumDuration(0)
            # Shown before the models load, which takes seconds for a classifier
            progress_dialog.show()
            QApplication.processEvents()

            # The batch run builds its own detector, as the worker's lives in its thread. The
            # classifier is the worker's (see SharedFactory), or waits for the worker to load it.
            batch_detector = self._detector_factory(os.path.join(self.models_dir, model_filename))
            classifier_filename = self.ui.classifier_combo_box.currentData()
            batch_classifier = (self._classifier_factory(os.path.join(self._model_downloader.classifiers_dir,
                                                                      classifier_filename),
                                                         self._model_downloader.classifies(classifier_filename))
                                if classifier_filename else None)

            def progress(index: int, total: int, file_name: str) -> bool:
                progress_dialog.setValue(index)
                progress_dialog.setLabelText(f"Processing {index+1}/{total}: {file_name}")
                QApplication.processEvents()
                return not progress_dialog.wasCanceled()

            # The image list holds one folder (see _is_one_folder)
            output_dir = os.path.join(os.path.dirname(image_full_paths[0]), output_dir_name)
            result = run_batch(
                image_full_paths,
                detector=batch_detector,
                detection_confidence=self.ui.detection_confidence_slider.value() / 100.0,
                exposure_correction=self.ui.cb_comp_cam_exposure.isChecked(),
                output_dir=output_dir,
                detections_csv_filename=detections_csv_filename,
                action=action,
                progress=progress,
                class_filter=self._selected_class_filter(),
                classifier=batch_classifier,
                taxon_confidence=self.ui.taxon_confidence_slider.value() / 100.0,
                classification_csv_filename=classification_csv_name(self.ui.taxon_confidence_slider.value(),
                                                                    classifier_filename),
            )
            cancelled = result.cancelled
            failed_count = len(result.failed)

            # Export the settings to JSON alongside the CSV
            self._save_settings()
            settings_filename = settings_json_name(self.ui.detection_confidence_slider.value(), model_filename)
            self.settings.export_to_file(Path(output_dir) / settings_filename)

            if not cancelled:
                self.ui.status_bar.showMessage(f"Finished {process_name.lower()}.", 5000)
                self._set_last_output_dir(output_dir)
                if failed_count:
                    show_warning_toast(
                        self,
                        "Detectorist",
                        f"Finished {process_name.lower()}, but {_count(failed_count, 'image')} failed. "
                        f"See {detections_csv_filename} for details.",
                        link_text="Show in file manager",
                        on_link=lambda: self._open_native_file_manager(output_dir),
                        duration=0,  # keep the toast up, as the user may not be watching a long run
                    )
                else:
                    show_success_toast(
                        self,
                        "Detectorist",
                        f"Finished {process_name.lower()}.",
                        link_text="Show in file manager",
                        on_link=lambda: self._open_native_file_manager(output_dir),
                    )
            else:
                self.ui.status_bar.showMessage(f"{process_name} cancelled.", 5000)

            return not cancelled and not failed_count

        except Exception as e:
            logger.exception("Error during %s", process_name)
            self.ui.status_bar.showMessage(f"Error during {process_name}: {e}", 5000)
            show_error_toast(self, f"{process_name} failed", str(e), duration=0)
            return False
        finally:
            if progress_dialog is not None:
                progress_dialog.close()
            self._set_batch_actions_enabled(True)

    def _set_batch_actions_enabled(self, enabled: bool) -> None:
        """
        Guards against re-entering run_batch. It blocks the GUI thread and
        pumps QApplication.processEvents() to keep the progress dialog alive,
        which leaves every action reachable through the app menu bar (unlike
        toolbar widgets, it isn't covered by the dialog's window modality) for
        the whole run. Without this, clicking a batch action again mid-run
        starts a second run_batch writing to the same output directory.

        Disabling forces every guarded action off. Re-enabling recomputes each
        action's real state instead of forcing it on, since model/selection
        state may have changed while the batch was running.

        The actions that load other images or change the settings are disabled
        too. Loading images mid-run would swap the list that a "Copy, export &
        remove" run removes its images from afterwards, and new settings would
        not match the settings JSON exported with the CSV. As loading images
        or a finished download recomputes the action states, those code paths
        check _batch_running, so they cannot enable a batch action mid-run.
        """
        self._batch_running = not enabled
        for action in (self.ui.recent_folders_menu.menuAction(), self.ui.import_settings_action,
                       self.ui.reset_settings_action, self.ui.manage_models_action):
            action.setEnabled(enabled)
        if enabled:
            self._on_model_availability_changed()
            self._update_selection_dependent_actions_state()
            self._update_clear_image_list_action_state()
            self.ui.open_images_action.setEnabled(True)
            self.ui.open_folder_action.setEnabled(True)
        else:
            self.ui.crop_and_export_all_images_action.setEnabled(False)
            self.ui.crop_and_export_selected_images_action.setEnabled(False)
            self.ui.copy_export_remove_action.setEnabled(False)
            self.ui.clear_image_list_action.setEnabled(False)
            self.ui.remove_selected_images_from_list_action.setEnabled(False)
            self.ui.open_images_action.setEnabled(False)
            self.ui.open_folder_action.setEnabled(False)

    def _crop_and_export_images_with_progress(self, process_name: str, image_files_to_process: list[str] | None = None):
        """
        Exports images via a Batch Run using the current crop
        settings, into the processed folder of each image folder. The files are
        named by taxon while a classifier is selected, else by class.
        """
        crop_settings = self._get_current_crop_settings()
        if crop_settings is None:
            return False
        classifier_filename = self.ui.classifier_combo_box.currentData()
        patterns = tuple(self._model_downloader.classifies(classifier_filename)) if classifier_filename else None
        action = CropExportAction(crop_settings, crop=self.ui.cb_crop.isChecked(), classifier_patterns=patterns)
        return self._run_batch_with_progress(process_name, action, OUTPUT_DIR_NAME,
                                             image_files_to_process)

    def _selected_image_files(self) -> list[str]:
        """Full paths of the selected images, in list order."""
        rows = sorted(index.row() for index in self.ui.image_list_view.selectionModel().selectedIndexes())
        return [self.model.data(self.model.index(row), ImageListModel.FullPathRole) for row in rows]

    def crop_and_export_selected_images(self):
        """Export the currently selected images."""
        selected_image_files = self._selected_image_files()
        if not selected_image_files:
            return False
        return self._crop_and_export_images_with_progress("Exporting selected images", selected_image_files)

    def crop_and_export_all_images(self):
        """Export all images."""
        return self._crop_and_export_images_with_progress("Exporting images")

    def _update_export_summary(self) -> None:
        """Shows in the crop panel how the export names its files."""
        self.ui.export_summary_label.setText(describe_export(bool(self.ui.classifier_combo_box.currentData()),
                                                             self.ui.cb_crop.isChecked()))

    def _on_crop_toggled(self, _checked: bool) -> None:
        self._update_crop_controls()
        self.update_crop_bands()

    def _update_crop_controls(self) -> None:
        """Enables the controls that only matter for crops while the Crop checkbox is on, and updates the summary."""
        crop = self.ui.cb_crop.isChecked()
        for widget in [*self._crop_mode_radios().values(), self.ui.crop_ratio_label, self.ui.crop_ratio_combo_box,
                       self.ui.padding_label, self.ui.padding_slider, self.ui.padding_spin_box]:
            widget.setEnabled(crop)
        self._update_export_summary()

    def _copy_export_remove_selected_images(self):
        """Copies filenames, exports the selected images, and removes them from the list."""
        if not self.ui.image_list_view.selectionModel().hasSelection():
            return

        self._copy_selected_filenames_to_clipboard()
        success = self.crop_and_export_selected_images()
        if success:
            self._remove_selected_images_from_list()

    def _update_selection_dependent_actions_state(self):
        """Enables/disables actions based on the current selection in the image list view."""
        has_selection = len(self.ui.image_list_view.selectionModel().selectedIndexes()) > 0
        can_run = self.ui.model_select_combo_box.count() > 0 and not self._batch_running
        self.ui.crop_and_export_selected_images_action.setEnabled(has_selection and can_run)
        self.ui.locate_image_in_filemanager_action.setEnabled(has_selection)
        self.ui.copy_filenames_to_clipboard_action.setEnabled(has_selection)
        self.ui.remove_selected_images_from_list_action.setEnabled(has_selection and not self._batch_running)
        self.ui.copy_export_remove_action.setEnabled(has_selection and can_run)

    def _update_clear_image_list_action_state(self):
        """Enables/disables clear_image_list_action based on whether the model has images."""
        self.ui.clear_image_list_action.setEnabled(self.model.rowCount() > 0 and not self._batch_running)

    def show_image_list_view_context_menu(self, position):
        index = self.ui.image_list_view.indexAt(position)
        if not index.isValid():
            return

        if self.ui.image_list_view.selectionModel().hasSelection():
            menu = QMenu()
            menu.addAction(self.ui.locate_image_in_filemanager_action)
            menu.addSeparator()
            menu.addAction(self.ui.crop_and_export_selected_images_action)
            menu.addAction(self.ui.copy_export_remove_action)
            menu.addAction(self.ui.remove_selected_images_from_list_action)
            menu.addAction(self.ui.clear_image_list_action)
            menu.addSeparator()
            menu.addAction(self.ui.copy_filenames_to_clipboard_action)

            menu.exec(self.ui.image_list_view.mapToGlobal(position))

    def _locate_selected_image_in_file_manager(self):
        index = self.ui.image_list_view.currentIndex()
        if not index.isValid():
            return

        file_path = self.model.data(index, ImageListModel.FullPathRole)
        self._open_native_file_manager(file_path)

    def _copy_selected_filenames_to_clipboard(self):
        selected_indexes = self.ui.image_list_view.selectionModel().selectedIndexes()
        if not selected_indexes:
            return

        filenames = [self.model.data(index) for index in selected_indexes if index.isValid()]
        clipboard_text = "\n".join(filenames)
        clipboard = QApplication.clipboard()
        clipboard.setText(clipboard_text)

        count = len(filenames)
        show_success_toast(
            self,
            "Copied to clipboard",
            f"Copied {count} filename{'s' if count != 1 else ''}.",
        )

    def _remove_selected_images_from_list(self):
        """Removes the currently selected images filenames from the list."""
        selected_indexes = self.ui.image_list_view.selectionModel().selectedIndexes()
        rows_to_remove = sorted({idx.row() for idx in selected_indexes if idx.isValid()})
        if not rows_to_remove:
            return

        self.model.removeImagePaths(rows_to_remove)

        # Handle selection after removal
        if self.model.rowCount() == 0:
            self.clear_image_list()
        else:
            # Calculate next selection row, ensuring it's within model bounds
            next_selection_row = min(rows_to_remove[-1] - len(rows_to_remove) + 1,
                                     self.model.rowCount() - 1)
            # If we'd want to select the item that now occupies the position of the first removed item:
            #next_selection_row = rows_to_remove[0]
            next_index = self.model.index(next_selection_row, 0)
            self.ui.image_list_view.setCurrentIndex(next_index)

    def keyPressEvent(self, event):
        """Handles key press events for navigating the image list."""
        key = event.key()
        modifiers = event.modifiers()

        if self.model.rowCount() == 0: # No images loaded, ignore key events
            super().keyPressEvent(event) # Pass other key events to the base class
            return

        # Ctrl + Up/Down or Ctrl + Left/Right to jump to the first/last image
        if modifiers & Qt.KeyboardModifier.ControlModifier: # Cmd key on macOS
            if key == Qt.Key.Key_Up or key == Qt.Key.Key_Left:
                self.ui.image_list_view.selectionModel().clear()
                self.ui.image_list_view.setCurrentIndex(self.model.index(0, 0))
                event.accept()
                return
            elif key == Qt.Key.Key_Down or key == Qt.Key.Key_Right:
                self.ui.image_list_view.selectionModel().clear()
                self.ui.image_list_view.setCurrentIndex(self.model.index(self.model.rowCount() - 1, 0))
                event.accept()
                return
        # Navigation through the image list using Left/Right keys, stop at the ends
        else:
            current_row = self.ui.image_list_view.currentIndex().row()
            next_row = -1 # Initialize with an invalid value
            if key == Qt.Key.Key_Left:
                next_row = max(0, current_row - 1)
            elif key == Qt.Key.Key_Right:
                next_row = min(self.model.rowCount() - 1, current_row + 1)

            if next_row != -1 and next_row != current_row: # Only update if a valid new row is calculated and it's different from the current one
                next_index = self.model.index(next_row, 0)
                self.ui.image_list_view.setCurrentIndex(next_index)
                event.accept()
                return

        super().keyPressEvent(event) # Pass other key events to the base class

    def closeEvent(self, event):
        # Save settings before closing
        self._save_settings()
        # Clean up resources, if any
        logger.info("Closing application...")
        self._worker_thread.quit()
        self._worker_thread.wait()
        super().closeEvent(event)
