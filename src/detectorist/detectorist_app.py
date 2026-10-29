import html
import logging
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pillow_heif
from PySide6.QtCore import (
    QRect,
    QSignalBlocker,
    Qt,
    QTimer,
)
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
)

from detectorist import __version__

from .about_dialog import show_about_dialog
from .classifier import Classifier, class_matches, detections_to_classify
from .detection_style import taxon_styles
from .detector import Detector
from .enum_button_group import EnumButtonGroup
from .export_dialog import ExportDialog, PreviewImage
from .export_files import CLASSIFICATION_CSV_NAME, DETECTIONS_CSV_NAME, SETTINGS_JSON_NAME
from .export_planner import CropMode, CropSettings, ExportOptions, plan_crops
from .export_run import DetectionFilter, ExportResult, ExportWriter
from .image_label import ImageLabel
from .image_list_model import ImageListModel
from .image_object import (
    ImageObject,
    filter_out_appledouble_files,
    is_supported_image,
    list_supported_images,
    supported_extensions,
)
from .jobs import ShowRequest
from .manage_models import ManageModelsDialog
from .model_downloader import ModelDownloader
from .pipeline import Pipeline, neighbours
from .settings import Settings
from .shortcuts_dialog import ShortcutsDialog
from .toasts import show_error_toast, show_success_toast, show_warning_toast
from .ui_detectorist_app_gui import Ui_DetectoristAppUI
from .utils import (
    contract_user_path,
    count_noun,
    file_manager_name,
    get_model_path,
    list_model_files,
    long_path,
    resolve_short_path,
    reveal_in_file_manager,
    strip_model_ext,
)

logger = logging.getLogger(__name__)


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

# Neighbours offered to the Pipeline on each side of the shown image. It prefetches as many as its
# image budget holds: on 16 GB of RAM about 7 per side of a 33 MP image.
PREFETCH_PER_SIDE = 16

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


@dataclass
class _RunningExport:
    """An export the window started, until the Pipeline reports its end."""
    progress_dialog: QProgressDialog
    output_dir: str
    classifier_filename: str | None  # the classifier the run names with, None for none


class DetectoristApp(QMainWindow):
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
            detector_factory: Called with a model path to build a detector.
                The Pipeline holds one for browsing and exports alike.
            classifier_factory: Likewise for the classifier.
        """
        super().__init__()

        self.settings = settings if settings is not None else Settings()
        self._detector_factory = detector_factory
        self._classifier_factory = classifier_factory
        self.current_image_path = None
        self._all_detection_results: list = []
        self._last_detection_time_ms: float = 0.0
        self._last_classification_time_ms: float = 0.0
        # What the classifier said about the current image's detections, keyed by box
        self._taxonomy_by_box: dict = {}
        self._classification_pending = False
        # Whether the detections of the current image arrived, after which the names are what is awaited
        self._detected = False
        # The step the current image is at, as the status bar names it (see _set_activity), and the
        # text shown in place of the image meanwhile
        self._activity: str | None = None
        self._activity_placeholder: str | None = None
        # The classifier the user chose, by filename. It stays the choice while a
        # detection model is loaded that it does not apply to.
        self._preferred_classifier: str | None = None
        # The class chosen in Show, kept while a model that does not detect it is loaded
        self._preferred_class_filter: str | None = None
        # Classes of the loaded detection model. They decide which classifiers are offered.
        self._detector_class_names: list[str] = []
        self._last_output_dir: str | None = None
        # When the Manage Models dialog is open it reports download progress
        # itself, so app-level toasts are suppressed to avoid double feedback.
        self._models_dialog_open = False
        self._running_export: _RunningExport | None = None  # the export under way, which keeps the actions locked
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
        self.ui.image_label.detection_hovered.connect(self.ui.results_table.set_highlighted_box)
        self.ui.results_table.row_hovered.connect(self.ui.image_label.highlight_box)

        # Shown while the current image is at a step. It has no range, as neither decoding nor
        # detection can tell how far it got.
        self.ui.busy_bar = QProgressBar()
        self.ui.busy_bar.setRange(0, 0)
        self.ui.busy_bar.setTextVisible(False)
        self.ui.busy_bar.setMaximumWidth(120)
        self.ui.busy_bar.hide()
        self.ui.status_bar.addPermanentWidget(self.ui.busy_bar)
        # A permanent widget, so the status bar's messages (the image's name, notices) do not replace it
        self.ui.results_summary_label = QLabel()
        self.ui.status_bar.addPermanentWidget(self.ui.results_summary_label)
        # The results only describe a shown image, so the welcome and message screens get the full height
        self.ui.results_table.setVisible(False)
        self.ui.image_label.image_shown_changed.connect(self.ui.results_table.setVisible)

        for label, aspect in ASPECT_RATIOS:
            self.ui.crop_ratio_combo_box.addItem(label, aspect_ratio_setting(aspect))

        self._crop_modes = EnumButtonGroup(self.ui.btngroup_crop, {
            CropMode.MOST_CONFIDENT_DETECTION: self.ui.rb_crop_most_confident_detection,
            CropMode.BEST_CLASSIFICATION: self.ui.rb_crop_best_classification,
            CropMode.MOST_CENTERED: self.ui.rb_crop_centered_obj,
            CropMode.EACH_OBJECT: self.ui.rb_crop_all_detected_objects,
        })

        # Snapshot the .ui file's built-in defaults before _load_settings() can override
        # them, so "Reset Settings to Defaults" has real values to restore.
        self._default_detection_confidence = self.ui.detection_confidence_slider.value()
        self._default_taxon_confidence = self.ui.taxon_confidence_slider.value()
        self._default_padding = self.ui.padding_slider.value()
        self._default_aspect_ratio_index = self.ui.crop_ratio_combo_box.currentIndex()
        self._default_auto_correct_exposure = self.ui.cb_comp_cam_exposure.isChecked()
        self._default_crop_mode = self._crop_modes.value()

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
        self.ui.image_list_view.addAction(self.ui.reveal_image_action)
        self.ui.image_list_view.addAction(self.ui.copy_filenames_to_clipboard_action)

        # Platform shortcuts can't be expressed in the .ui file, which only stores fixed key strings
        self.ui.open_images_action.setShortcuts(QKeySequence.StandardKey.Open)
        self.ui.copy_filenames_to_clipboard_action.setShortcuts(QKeySequence.StandardKey.Copy)
        self.ui.quit_action.setShortcuts(QKeySequence.StandardKey.Quit)
        self.ui.shortcuts_action.setShortcuts(
            [QKeySequence("Ctrl+/"), *QKeySequence.keyBindings(QKeySequence.StandardKey.HelpContents)])
        if sys.platform == 'win32':
            self.ui.quit_action.setText("Exit")
        self.ui.reveal_image_action.setText(f"Reveal in {file_manager_name()}")
        # Delete is the convention on Windows and Linux, Backspace on macOS, whose keyboards lack a Delete key
        self.ui.remove_selected_images_from_list_action.setShortcuts(
            [QKeySequence(Qt.Key.Key_Delete), QKeySequence(Qt.Key.Key_Backspace)])

        # Connect signals
        self.ui.open_images_action.triggered.connect(self.open_images)
        self.ui.open_folder_action.triggered.connect(self.open_folder)
        self.ui.clear_image_list_action.triggered.connect(self.clear_image_list)
        self.ui.image_list_view.selectionModel().currentChanged.connect(self.on_image_selected)
        self.ui.export_action.triggered.connect(self.export_with_dialog)
        self.ui.image_list_view.selectionModel().selectionChanged.connect(self._update_selection_dependent_actions_state)
        self.ui.about_action.triggered.connect(self.show_about_dialog)
        self.ui.shortcuts_action.triggered.connect(self.show_shortcuts_dialog)
        self.ui.reveal_image_action.triggered.connect(self._reveal_selected_image)
        self.ui.copy_filenames_to_clipboard_action.triggered.connect(self._copy_selected_filenames_to_clipboard)
        self.ui.remove_selected_images_from_list_action.triggered.connect(self._remove_selected_images_from_list)
        self.ui.clear_recent_folders_action.triggered.connect(self._clear_recent_folders)
        self.ui.import_settings_action.triggered.connect(self._import_settings)
        self.ui.export_settings_action.triggered.connect(self._export_settings)
        self.ui.reset_settings_action.triggered.connect(self._reset_settings)
        self.ui.manage_models_action.triggered.connect(self.show_manage_models_dialog)
        self.ui.open_output_folder_action.triggered.connect(self._open_last_output_folder)
        self.ui.quit_action.triggered.connect(self.close)

        self.ui.detection_confidence_slider.valueChanged.connect(self._on_detection_confidence_changed)
        self.ui.detection_confidence_spin_box.valueChanged.connect(self._display_filtered_results)
        self.ui.taxon_confidence_slider.valueChanged.connect(self._display_filtered_results)

        # Connect crop controls
        self._crop_modes.value_changed.connect(self.update_crop_bands)
        self.ui.crop_ratio_combo_box.currentIndexChanged.connect(self.update_crop_bands)
        self.ui.padding_slider.valueChanged.connect(self.update_crop_bands)

        self.ui.cb_comp_cam_exposure.toggled.connect(self.on_exposure_compensation_toggled)
        self.ui.toggle_masks_action.toggled.connect(self.ui.image_label.set_masks_visible)
        self.ui.toggle_boxes_action.toggled.connect(self.ui.image_label.set_boxes_visible)
        self.ui.toggle_labels_action.toggled.connect(self.ui.image_label.set_labels_visible)
        self.ui.toggle_all_overlays_action.triggered.connect(self.toggle_all_overlays)
        # The .ui file's defaults, like the hidden masks, would otherwise only reach the image on a toggle
        self.ui.image_label.set_masks_visible(self.ui.toggle_masks_action.isChecked())
        self.ui.image_label.set_boxes_visible(self.ui.toggle_boxes_action.isChecked())
        self.ui.image_label.set_labels_visible(self.ui.toggle_labels_action.isChecked())

        # Connect model signals
        self.model.modelReset.connect(self._update_clear_image_list_action_state)
        self.model.modelReset.connect(self._update_selection_dependent_actions_state)

        self.models_dir = models_dir if models_dir is not None else get_model_path()

        # Shared model downloader (lives for the app's lifetime so downloads survive dialog close)
        self._model_downloader = ModelDownloader(self.models_dir, self)
        self._model_downloader.download_finished.connect(self._refresh_model_list)
        self._model_downloader.download_finished.connect(self._notify_model_download_finished)
        self._model_downloader.download_error.connect(self._notify_model_download_error)

        # Defers showing the activity: a cached image arrives within a few
        # milliseconds, detections and names included, so nothing flashes for it.
        self._activity_timer = QTimer(self)
        self._activity_timer.setSingleShot(True)
        self._activity_timer.setInterval(200)
        self._activity_timer.timeout.connect(self._show_activity)

        # Decoding and inference run on the Pipeline's own threads, so the GUI remains responsive
        self.pipeline = Pipeline(self._detector_factory, self._classifier_factory, parent=self)
        self.pipeline.model_loaded.connect(self.handle_model_loaded)
        self.pipeline.image_loaded.connect(self.handle_image_loaded)
        self.pipeline.detection_complete.connect(self.handle_detection_complete)
        self.pipeline.error.connect(self.handle_pipeline_error)
        self.pipeline.cache_updated.connect(self.model.setCachedPaths)
        self.pipeline.classification_complete.connect(self.handle_classification_complete)
        self.pipeline.classifier_error.connect(self.handle_classifier_error)
        # Queue export progress to the window so the progress dialog cannot re-enter the Pipeline
        self.pipeline.export_progress.connect(self._on_export_progress, Qt.ConnectionType.QueuedConnection)
        self.pipeline.export_finished.connect(self._on_export_finished)
        self.pipeline.export_failed.connect(self._on_export_failed)
        self.ui.model_select_combo_box.currentIndexChanged.connect(self.on_model_selected)
        self.ui.classifier_combo_box.currentIndexChanged.connect(self._on_classifier_chosen)
        self.ui.class_filter_combo_box.currentIndexChanged.connect(self.on_class_filter_changed)

        # Find and populate models (must be after the Pipeline exists so _on_model_availability_changed can reach it)
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
        """Apply the persisted window geometry, splitter state and shown overlays."""
        if self.settings.window_geometry:
            self.restoreGeometry(self.settings.window_geometry)
        if self.settings.main_splitter_state:
            self.ui.splitter.restoreState(self.settings.main_splitter_state)
        if self.settings.image_splitter_state:
            self.ui.image_splitter.restoreState(self.settings.image_splitter_state)
        for action, shown in ((self.ui.toggle_masks_action, self.settings.show_masks),
                              (self.ui.toggle_boxes_action, self.settings.show_boxes),
                              (self.ui.toggle_labels_action, self.settings.show_labels)):
            if shown is not None:
                action.setChecked(shown)

    def _load_settings(self):
        """
        Apply the persistent settings to the UI. The model combo
        box is set with its signals blocked, so the caller has to follow up
        with on_model_selected() to load the selected model in the Pipeline. The
        classifier is selected once a model it applies to has loaded.
        """
        # Model selection
        if self.settings.detection_model:
            combo = self.ui.model_select_combo_box
            with QSignalBlocker(combo):
                idx = self._find_model_index(combo, self.settings.detection_model)
                if idx >= 0:
                    combo.setCurrentIndex(idx)

        # Classifier choice. At startup no detection model has loaded yet, so the
        # list stays at "No classifier" until handle_model_loaded refreshes it.
        # After Import Settings, the refresh selects the imported choice.
        self._preferred_classifier = self.settings.classification_model
        self._refresh_classifier_list()

        # Like the classifier, the Show filter is selected once a model that detects its class has loaded.
        # After Import Settings the loaded model may stay, and its classes are listed already.
        self._preferred_class_filter = self.settings.export_class_filter
        if self.ui.class_filter_combo_box.count():
            self._select_preferred_class_filter()
            self._display_filtered_results()

        # Detection confidence (slider and spinbox are linked)
        if (detection_confidence := self.settings.detection_min_confidence_percent) is not None:
            self.ui.detection_confidence_slider.setValue(detection_confidence)

        # Taxon confidence (slider and spinbox are linked)
        if (taxon_confidence := self.settings.classification_min_confidence_percent) is not None:
            self.ui.taxon_confidence_slider.setValue(taxon_confidence)

        # Crop mode
        # A mode that is missing or no longer exists, like the removed union, falls back to the default
        crop_mode = CropMode.from_setting(self.settings.crop_mode) or self._default_crop_mode
        self._crop_modes.set_value(crop_mode)

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

    def _save_settings(self):
        """Save current UI state to persistent settings."""
        self.settings.save_current_version()

        # Window geometry and splitter state
        self.settings.window_geometry = self.saveGeometry()
        self.settings.main_splitter_state = self.ui.splitter.saveState()
        self.settings.image_splitter_state = self.ui.image_splitter.saveState()
        self.settings.show_masks = self.ui.toggle_masks_action.isChecked()
        self.settings.show_boxes = self.ui.toggle_boxes_action.isChecked()
        self.settings.show_labels = self.ui.toggle_labels_action.isChecked()

        # Model selection
        self.settings.detection_model = self.ui.model_select_combo_box.currentData()

        # Classifier selection and taxon confidence
        self.settings.classification_model = self._preferred_classifier
        self.settings.classification_min_confidence_percent = self.ui.taxon_confidence_slider.value()

        # Detection confidence
        self.settings.detection_min_confidence_percent = self.ui.detection_confidence_slider.value()

        # Crop mode
        if (crop_mode := self._crop_modes.value()) is not None:
            self.settings.crop_mode = crop_mode.value

        # Aspect ratio
        self.settings.crop_aspect_ratio = self.ui.crop_ratio_combo_box.currentData()

        # Padding
        self.settings.crop_padding_percent = self.ui.padding_slider.value()

        # Auto correct camera exposure bias
        self.settings.image_correct_exposure = self.ui.cb_comp_cam_exposure.isChecked()

        # Show filter
        self.settings.export_class_filter = self._preferred_class_filter

    def _clear_results(self):
        """Empties the results table and its summary, while no detection result is shown."""
        self.ui.results_table.clear()
        self.ui.results_summary_label.clear()

    def _show_message(self, text: str):
        """Shows text in place of the image, and drops what was detected in it."""
        self._set_activity(None)
        self.ui.image_label.setText(text)
        self._clear_results()

    def _show_results(self, detections: list, threshold: float, pending: set):
        """
        Lists the detections in the results table, and sums them up with how
        many of them are classified, and the time each took.
        """
        self.ui.results_table.show_detections(detections, self._taxonomy_by_box, threshold, pending)
        summary = f"{count_noun(len(detections), 'object')} detected ({self._last_detection_time_ms:.0f} ms)."
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
        # The caches stay: the Pipeline notices a changed file by its stamp when decoding it

        self.ui.image_label.setText("Loading Images...")
        self.model.setImagePaths(supported_files)
        QApplication.processEvents() # Ensure UI updates

        # Enable actions that operate on all loaded images (only if a model is available)
        can_run = self.ui.model_select_combo_box.count() > 0 and not self._exporting
        self.ui.export_action.setEnabled(can_run)

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
        """Import settings from a JSON file written by a previous export."""
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
        # Set directly, as the combo box may show all classes already and then not signal the change
        self._preferred_class_filter = None
        self.ui.class_filter_combo_box.setCurrentIndex(0)
        self.ui.padding_slider.setValue(self._default_padding)
        self.ui.crop_ratio_combo_box.setCurrentIndex(self._default_aspect_ratio_index)
        self.ui.cb_comp_cam_exposure.setChecked(self._default_auto_correct_exposure)
        self._crop_modes.set_value(self._default_crop_mode)

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
        self.ui.export_action.setEnabled(False)

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
        self._detected = False

        if self.ui.model_select_combo_box.count() == 0:
            self._show_message(NO_MODELS_MESSAGE)
            self.ui.status_bar.clearMessage()
            return

        self._set_activity(f"Loading {os.path.basename(new_image_path)}...", placeholder="Loading image...")
        self.ui.image_label.hide_bands()
        self._clear_results()
        self.ui.image_exif_label.setText("")

        # Ask the Pipeline to load and process the image
        self.trigger_processing()

    def _set_activity(self, text: str | None, placeholder: str | None = None):
        """
        Names the step the current image is at in the status bar, next to the
        busy bar, and shows placeholder in place of the image. None ends the
        activity and names the image again. A step shows once the activity
        took longer than the timer's interval, and while the busy bar is up
        the next step replaces it at once.
        """
        if text == self._activity:
            return
        self._activity, self._activity_placeholder = text, placeholder
        if text is None:
            self._activity_timer.stop()
            self.ui.busy_bar.hide()
            if self.current_image_path:
                self.ui.status_bar.showMessage(os.path.basename(self.current_image_path))
            else:
                self.ui.status_bar.clearMessage()
        elif not self.ui.busy_bar.isHidden():
            self._show_activity()
        elif not self._activity_timer.isActive():
            self._activity_timer.start()

    def _show_activity(self):
        if self._activity_placeholder:
            self.ui.image_label.setText(self._activity_placeholder)
        self.ui.status_bar.showMessage(self._activity)
        self.ui.busy_bar.show()

    def trigger_processing(self):
        """Asks the Pipeline for the current image and the neighbours to prefetch."""
        if not self._show_current_image():
            return
        self.pipeline.prefetch(neighbours(self.model.imagePaths(), self.current_image_path, PREFETCH_PER_SIDE))

    def _show_current_image(self) -> bool:
        """
        Tells the Pipeline what the current image should look like: the
        exposure correction and the detection confidence down to which its
        boxes are named. Returns whether there is an image and a model to ask for.
        """
        if not self.current_image_path or self.ui.model_select_combo_box.count() == 0:
            return False
        self.pipeline.show(ShowRequest(self.current_image_path, self.ui.cb_comp_cam_exposure.isChecked(),
                                       self.ui.detection_confidence_slider.value() / 100.0))
        return True

    def toggle_all_overlays(self):
        """Hides the masks, boxes and labels if any of them is shown, otherwise shows all of them."""
        # A disabled toggle, e.g. the masks of a detection model, keeps its state
        actions = [action for action in (self.ui.toggle_masks_action, self.ui.toggle_boxes_action,
                                         self.ui.toggle_labels_action) if action.isEnabled()]
        show = not any(action.isChecked() for action in actions)
        for action in actions:
            action.setChecked(show)

    def handle_model_loaded(self, success: bool, message: str, class_names: list, is_segmentation: bool):
        """Handles the result of loading a model in the Pipeline."""
        self.ui.image_label.set_class_color_map(class_names)
        self.ui.toggle_masks_action.setEnabled(is_segmentation)
        with QSignalBlocker(self.ui.class_filter_combo_box):
            self.ui.class_filter_combo_box.clear()
            self.ui.class_filter_combo_box.addItems(["All classes", *class_names])
        self._select_preferred_class_filter()
        self._all_detection_results = []
        # An image still loading moves on to detection by itself, see handle_image_loaded
        image_shown, self._detected = self._detected, False
        self._detector_class_names = class_names
        self._refresh_classifier_list()
        if success:
            logger.info(message)
            # If an image is currently displayed, trigger a new detection with the new model.
            if self.current_image_path:
                if image_shown:
                    self._set_activity("Detecting objects...")
                self.trigger_processing()
        else:
            self._show_message(message)
            logger.error(message)

    def handle_image_loaded(self, image_path: str, image_object: ImageObject, display):
        """
        Handles the image_loaded signal from the Pipeline. The image shown
        already only gets its new display array, e.g. after the exposure
        correction setting changed, and keeps its bands.
        """
        if image_path != self.current_image_path:
            return  # Stale result for a different image

        if not image_object:
            self._show_message(f"Could not load image:\n{image_path}")
            return

        if image_object is self.ui.image_label.image:
            self.ui.image_label.set_display(display)
            return
        self.ui.image_label.replace_image(image_object, display)
        # Named until the detection step shows, if it takes that long
        self.ui.status_bar.showMessage(os.path.basename(image_path))
        self._set_activity("Detecting objects...")

        # Update the Image info label
        height, width = image_object.height, image_object.width
        original_bpc = image_object.original_bpc
        file_type = image_object.file_extension.upper()[1:]
        self.ui.image_info_label.setText(f"File type \t: {file_type}\nResolution\t: {width}x{height}\nBits per channel\t: {original_bpc}")

        # Update the EXIF info label
        self.ui.image_exif_label.setText(image_object.get_exif_summary())


    def handle_detection_complete(self, image_path: str, results: list, detection_time_ms: float):
        """Handles the detection_complete signal from the Pipeline."""
        if image_path != self.current_image_path:
            return  # Stale result (this can happen if user quickly switches images)

        self._all_detection_results = results
        self._detected = True
        self._last_detection_time_ms = detection_time_ms
        # The names follow with classification_complete
        self._taxonomy_by_box = {}
        self._classification_pending = self.ui.classifier_combo_box.currentData() is not None
        self._display_filtered_results()

    def handle_classification_complete(self, image_path: str, taxonomy_by_box: dict, classification_time_ms: float):
        """Handles the classification_complete signal from the Pipeline."""
        if image_path != self.current_image_path:
            return
        self._taxonomy_by_box = taxonomy_by_box
        self._classification_pending = False
        self._last_classification_time_ms = classification_time_ms
        self._display_filtered_results()

    def handle_classifier_error(self, message: str):
        """Handles the classifier_error signal from the Pipeline. The detections stay as they are."""
        show_error_toast(self, "Classifier error", message)

    def _select_preferred_class_filter(self) -> None:
        """
        Selects the preferred class in Show, or all classes while the loaded
        model does not detect it. The preference stays for a model that does.
        """
        combo = self.ui.class_filter_combo_box
        with QSignalBlocker(combo):
            combo.setCurrentIndex(max(combo.findText(self._preferred_class_filter or ""), 0))

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

    def _pending_boxes(self) -> set:
        """
        The boxes the classifier is still to name. Those out of its reach, by
        their class or detection score, are not, as no name is coming for them.
        """
        filename = self.ui.classifier_combo_box.currentData()
        if not self._classification_pending or filename is None:
            return set()
        to_name = detections_to_classify(self._all_detection_results, self.ui.detection_confidence_slider.value() / 100.0,
                                         self._model_downloader.classifies(filename))
        return {d.box for d in to_name} - self._taxonomy_by_box.keys()

    def _display_filtered_results(self):
        """Updates the UI with detection results filtered by the current class selection."""
        filtered = self._filtered_results()
        threshold = self.ui.taxon_confidence_slider.value() / 100.0
        # Counted over all detections, as the class filter does not change what is named
        pending = self._pending_boxes()
        self._show_results(filtered, threshold, pending)
        styles = taxon_styles(filtered, self._taxonomy_by_box, threshold)
        self.ui.image_label.set_detection_boxes(filtered, styles, pending)
        self.update_crop_bands()
        if self._detected:
            self._set_activity(f"Classifying {count_noun(len(pending), 'object')}..." if pending else None)

    def _on_detection_confidence_changed(self):
        """
        Shows the detections at the new confidence. Only boxes at or above it
        are named, so a lower one asks the Pipeline for the rest, which reports
        the names again for any new confidence. A drag needs no debouncing, as
        the Pipeline serves the latest request only.
        """
        self._classification_pending = self._detected and self.ui.classifier_combo_box.currentData() is not None
        self._show_current_image()
        self._display_filtered_results()

    def on_class_filter_changed(self):
        """Re-displays detection results when the class filter selection changes."""
        self._preferred_class_filter = self._selected_class_filter()
        self._display_filtered_results()

    def handle_pipeline_error(self, image_path: str, message: str):
        """Handles an error signal from the Pipeline."""
        if image_path != self.current_image_path:
            return  # Stale error for a different image (ignored)

        logger.error("Error for %s: %s", image_path, message)
        self._show_message(f"Error: {message}")
        self.ui.status_bar.clearMessage()
        show_error_toast(self, "Could not process image", f"{os.path.basename(image_path)}: {message}")

    def on_model_selected(self, index):
        if index < 0:
            return
        filename = self.ui.model_select_combo_box.itemData(index)
        self.pipeline.load_detector(os.path.join(self.models_dir, filename))

    def on_exposure_compensation_toggled(self, checked: bool):
        """Has the Pipeline rebuild the display array. The models always get the corrected image."""
        self._show_current_image()

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
        with QSignalBlocker(combo):
            for filename in onnx_files:
                display_name = name_map.get(filename) or strip_model_ext(filename)
                combo.addItem(display_name, filename)

            # Restore previous selection by filename
            idx = self._find_model_index(combo, previous_filename)
            if idx >= 0:
                combo.setCurrentIndex(idx)

        # If the selected model changed (e.g. first download), load it in the Pipeline.
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

        with QSignalBlocker(combo):
            combo.clear()
            combo.addItem("No classifier", None)
            for filename in applicable:
                combo.addItem(name_map.get(filename) or strip_model_ext(filename), filename)
            combo.setCurrentIndex(max(self._find_model_index(combo, self._preferred_classifier), 0))
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
        Greys out the taxon confidence, the labels action and the Best
        classification crop mode and hides the results' family, genus and
        species columns for "No classifier", as nothing is classified then.
        """
        active = self.ui.classifier_combo_box.currentData() is not None
        for widget in (self.ui.taxon_confidence_label, self.ui.taxon_confidence_slider,
                       self.ui.taxon_confidence_spin_box, self.ui.toggle_labels_action,
                       self.ui.rb_crop_best_classification):
            widget.setEnabled(active)
        self.ui.results_table.set_taxonomy_visible(active)

    def _load_selected_classifier(self):
        """
        Loads the classifier selected in the combo box in the Pipeline, or
        unloads it for "No classifier". The Pipeline names the shown image again.
        """
        filename = self.ui.classifier_combo_box.currentData()
        model_path = os.path.join(self._model_downloader.classifiers_dir, filename) if filename else None
        self.pipeline.load_classifier(model_path, self._model_downloader.classifies(filename) if filename else [])
        self._taxonomy_by_box = {}
        self._classification_pending = bool(filename and self.current_image_path)
        self._display_filtered_results()

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
        # A background download can finish during an export
        can_run = has_models and not self._exporting

        # Enable/disable actions that require a model
        self.ui.export_action.setEnabled(can_run and has_images)

        if not has_models:
            self._show_message(NO_MODELS_MESSAGE)
            self.pipeline.unload_detector()
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
            show_warning_toast(self, "Skipped files", f"Skipped {count_noun(skipped, 'unsupported file')}.")

        event.acceptProposedAction()

    def _get_current_crop_settings(self) -> CropSettings | None:
        """Gets crop settings from the UI, or None if no crop mode is selected."""
        crop_mode = self._crop_modes.value()
        if crop_mode is None:
            return None

        padding_percentage = self.ui.padding_slider.value() / 100.0
        _, aspect_ratio = ASPECT_RATIOS[self.ui.crop_ratio_combo_box.currentIndex()]
        return CropSettings(mode=crop_mode, padding=padding_percentage, aspect=aspect_ratio,
                            taxon_confidence=self.ui.taxon_confidence_slider.value() / 100.0)

    def update_crop_bands(self):
        """
        Frames the crops an export would write for the shown detections. They are
        planned from the detections as the detector returned them, like in the
        export, not from the drawn boxes, which are clamped to the image.
        """
        image = self.ui.image_label.image
        crop_settings = self._get_current_crop_settings()
        # Until the names arrive, a best classification band would frame the most
        # confident detection only to jump to the best classified one
        if (image is None or crop_settings is None
                or crop_settings.mode == CropMode.BEST_CLASSIFICATION and self._classification_pending):
            self.ui.image_label.set_crop_boxes([])
            return
        crop_tuples = plan_crops(self._filtered_results(), image.height, image.width, crop_settings, self._taxonomy_by_box)
        self.ui.image_label.set_crop_boxes([QRect(*crop_tuple) for crop_tuple in crop_tuples])

    def _set_last_output_dir(self, path: str):
        """Remembers the latest export directory and enables the reveal action."""
        self._last_output_dir = path
        self.ui.open_output_folder_action.setEnabled(True)

    def _open_last_output_folder(self):
        """Reveals the most recent export directory in the native file manager."""
        if self._last_output_dir:
            reveal_in_file_manager(self._last_output_dir)

    def _start_export(self, options: ExportOptions, output_dir: str, image_paths: list[str]) -> None:
        """
        Starts exporting the given images through the Pipeline,
        writing into output_dir, with a window modal progress dialog. When the
        run ends, _on_export_finished exports the settings alongside the CSV and
        reports the outcome.
        """
        classifier_filename = self.ui.classifier_combo_box.currentData()
        writer = ExportWriter(output_dir, options, exposure_correction=self.ui.cb_comp_cam_exposure.isChecked(),
                              with_classification=bool(classifier_filename),
                              patterns=self._model_downloader.classifies(classifier_filename)
                              if classifier_filename else [],
                              taxon_confidence=self.ui.taxon_confidence_slider.value() / 100.0)
        try:
            # Opened before the run, so a locked CSV file fails it before any image is processed
            writer.open()
        except Exception as e:
            logger.exception("Export failed")
            self._report_export_failure(str(e))
            return

        progress_dialog = QProgressDialog("Loading models...", "Cancel", 0, len(image_paths), self)
        progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dialog.setAutoClose(True)
        # Default minimumDuration is 4s, during which the dialog is invisible
        # but the window underneath stays fully clickable. Show it immediately
        # so the action lock below has a visible reason to exist.
        progress_dialog.setMinimumDuration(0)
        progress_dialog.canceled.connect(self.pipeline.cancel_export)
        # Shown before a model still loading is ready, which takes seconds for a classifier
        progress_dialog.show()

        self._running_export = _RunningExport(progress_dialog, output_dir, classifier_filename)
        self._lock_actions_during_export(True)
        detection_filter = DetectionFilter(self.ui.detection_confidence_slider.value() / 100.0,
                                           self._selected_class_filter())
        self.pipeline.start_export(image_paths, detection_filter, writer)

    def _on_export_progress(self, index: int, total: int, file_name: str):
        if self._running_export is not None:
            dialog = self._running_export.progress_dialog
            dialog.setLabelText(f"Processing {index+1}/{total}: {file_name}")
            # Last, as it processes events, during which the export may end
            dialog.setValue(index)

    def _on_export_finished(self, result: ExportResult):
        """Exports the settings alongside the CSV and reports how the export went."""
        export = self._end_export()
        if export is None:
            return
        try:
            # A classifier or class set aside for the loaded model is still the choice, but this run went without it
            self._save_settings()
            self.settings.export_to_file(Path(export.output_dir) / SETTINGS_JSON_NAME, {
                Settings.classification_model: export.classifier_filename,
                Settings.export_class_filter: self._selected_class_filter(),
            })
        except Exception as e:
            logger.exception("Export failed")
            self._report_export_failure(str(e))
            return

        if result.cancelled:
            self.ui.status_bar.showMessage("Exporting images cancelled.", 5000)
            return
        self.ui.status_bar.showMessage("Finished exporting images.", 5000)
        self._set_last_output_dir(export.output_dir)
        if result.failed:
            show_warning_toast(
                self,
                "Detectorist",
                f"Finished exporting images, but {count_noun(len(result.failed), 'image')} failed. "
                f"See {DETECTIONS_CSV_NAME} for details.",
                link_text=f"Reveal in {file_manager_name()}",
                on_link=lambda: reveal_in_file_manager(export.output_dir),
                duration=0,  # keep the toast up, as the user may not be watching a long run
            )
        else:
            show_success_toast(
                self,
                "Detectorist",
                "Finished exporting images.",
                link_text=f"Reveal in {file_manager_name()}",
                on_link=lambda: reveal_in_file_manager(export.output_dir),
            )

    def _on_export_failed(self, message: str):
        """Reports an export that could not go on, e.g. because the disk is full."""
        if self._end_export() is not None:
            self._report_export_failure(message)

    def _end_export(self) -> _RunningExport | None:
        """Closes the progress dialog and unlocks the actions. Returns the export, None if there was none."""
        export, self._running_export = self._running_export, None
        if export is not None:
            export.progress_dialog.close()
            export.progress_dialog.deleteLater()
            self._lock_actions_during_export(False)
        return export

    def _report_export_failure(self, message: str):
        self.ui.status_bar.showMessage(f"Export failed: {message}", 5000)
        show_error_toast(self, "Export failed", message, duration=0)

    @property
    def _exporting(self) -> bool:
        return self._running_export is not None

    def _lock_actions_during_export(self, locked: bool) -> None:
        """
        Guards against starting a second export. The window stays
        responsive while the Pipeline runs it, which leaves every action
        reachable through the app menu bar (unlike toolbar widgets, it isn't
        covered by the progress dialog's window modality) for the whole run.
        Without this, clicking Export again mid-run starts a second
        run writing to the same output directory.

        Locking forces every guarded action off. Unlocking recomputes each
        action's real state instead of forcing it on, since model/selection
        state may have changed while the export was running.

        The actions that load other images or change the settings are disabled
        too, so the settings JSON exported with the CSV matches what the run
        used and the window still shows the run's images. As loading images
        or a finished download recomputes the action states, those code paths
        check _exporting, so they cannot enable a locked action mid-run.
        """
        for action in (self.ui.recent_folders_menu.menuAction(), self.ui.import_settings_action,
                       self.ui.reset_settings_action, self.ui.manage_models_action):
            action.setEnabled(not locked)
        if not locked:
            self._on_model_availability_changed()
            self._update_selection_dependent_actions_state()
            self._update_clear_image_list_action_state()
            self.ui.open_images_action.setEnabled(True)
            self.ui.open_folder_action.setEnabled(True)
        else:
            self.ui.export_action.setEnabled(False)
            self.ui.clear_image_list_action.setEnabled(False)
            self.ui.remove_selected_images_from_list_action.setEnabled(False)
            self.ui.open_images_action.setEnabled(False)
            self.ui.open_folder_action.setEnabled(False)

    def export_with_dialog(self) -> None:
        """
        Asks in the Export dialog which images to export and how, then starts
        exporting them with the current crop settings.
        """
        all_images = self.model.imagePaths()
        crop_settings = self._get_current_crop_settings()
        if not all_images or crop_settings is None:
            return
        classifier_filename = self.ui.classifier_combo_box.currentData()
        patterns = tuple(self._model_downloader.classifies(classifier_filename)) if classifier_filename else None
        options = ExportOptions(crop_settings, crop=self.settings.export_crop_images,
                                prefix_class=self.settings.export_prefix_class,
                                prefix_taxa=self.settings.export_prefix_taxa, classifier_patterns=patterns)

        # Only the shown image has its detections at hand
        image = self.ui.image_label.image
        preview_image = (PreviewImage(self.current_image_path, self._filtered_results(), image.height, image.width,
                                      self._taxonomy_by_box) if image is not None else None)
        run_files = [DETECTIONS_CSV_NAME, *([CLASSIFICATION_CSV_NAME] if classifier_filename else []), SETTINGS_JSON_NAME]
        crop_summary = (f"{self._crop_modes.button(crop_settings.mode).text()}, "
                        f"{self.ui.crop_ratio_combo_box.currentText()}, {self.ui.padding_slider.value()}% padding")

        dialog = ExportDialog(all_images, self._selected_image_files(), options=options, preview_image=preview_image,
                              run_files=run_files, crop_summary=crop_summary,
                              class_filter=self._selected_class_filter(), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        options = dialog.options()
        self.settings.export_crop_images = options.crop
        self.settings.export_prefix_class = options.prefix_class
        self.settings.export_prefix_taxa = options.prefix_taxa
        self._start_export(options, dialog.output_dir(), dialog.images())

    def _selected_image_files(self) -> list[str]:
        """Full paths of the selected images, in list order."""
        rows = sorted(index.row() for index in self.ui.image_list_view.selectionModel().selectedIndexes())
        return [self.model.data(self.model.index(row), ImageListModel.FullPathRole) for row in rows]

    def _update_selection_dependent_actions_state(self):
        """Enables/disables actions based on the current selection in the image list view."""
        has_selection = len(self.ui.image_list_view.selectionModel().selectedIndexes()) > 0
        self.ui.reveal_image_action.setEnabled(has_selection)
        self.ui.copy_filenames_to_clipboard_action.setEnabled(has_selection)
        self.ui.remove_selected_images_from_list_action.setEnabled(has_selection and not self._exporting)

    def _update_clear_image_list_action_state(self):
        """Enables/disables clear_image_list_action based on whether the model has images."""
        self.ui.clear_image_list_action.setEnabled(self.model.rowCount() > 0 and not self._exporting)

    def show_image_list_view_context_menu(self, position):
        index = self.ui.image_list_view.indexAt(position)
        if not index.isValid():
            return

        if self.ui.image_list_view.selectionModel().hasSelection():
            menu = QMenu()
            menu.addAction(self.ui.reveal_image_action)
            menu.addSeparator()
            menu.addAction(self.ui.remove_selected_images_from_list_action)
            menu.addAction(self.ui.clear_image_list_action)
            menu.addSeparator()
            menu.addAction(self.ui.copy_filenames_to_clipboard_action)

            menu.exec(self.ui.image_list_view.mapToGlobal(position))

    def _reveal_selected_image(self):
        index = self.ui.image_list_view.currentIndex()
        if not index.isValid():
            return

        file_path = self.model.data(index, ImageListModel.FullPathRole)
        reveal_in_file_manager(file_path)

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

        # Home/End, Ctrl + Up/Down or Ctrl + Left/Right to jump to the first/last image
        ctrl = modifiers & Qt.KeyboardModifier.ControlModifier # Cmd key on macOS
        first = key == Qt.Key.Key_Home or (ctrl and key in (Qt.Key.Key_Up, Qt.Key.Key_Left))
        last = key == Qt.Key.Key_End or (ctrl and key in (Qt.Key.Key_Down, Qt.Key.Key_Right))
        if first or last:
            self.ui.image_list_view.selectionModel().clear()
            self.ui.image_list_view.setCurrentIndex(self.model.index(0 if first else self.model.rowCount() - 1, 0))
            event.accept()
            return
        # Navigation through the image list using Left/Right keys, stop at the ends
        if not ctrl:
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
        self.pipeline.shutdown()
        super().closeEvent(event)
