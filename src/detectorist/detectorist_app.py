import os
import subprocess
import sys
from pathlib import Path

import pillow_heif
from PySide6.QtCore import (
    Q_ARG,
    QFile,
    QIODeviceBase,
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
    QMenu,
    QMessageBox,
    QProgressDialog,
    QRadioButton,
)

from detectorist._version import __version__

from .batch_run import CropExportAction, SortByClassAction, output_dir_name, run_batch
from .crop_planner import CropMode, CropSettings, plan_crops
from .detector import Detector
from .image_label import ImageLabel
from .image_list_model import ImageListModel
from .image_object import ImageObject
from .manage_models import ManageModelsDialog
from .model_downloader import ModelDownloader
from .settings import Settings
from .ui_about_dialog import Ui_AboutDialog
from .ui_detectorist_app_gui import Ui_DetectoristAppUI
from .utils import contract_user_path, get_model_path, strip_model_ext
from .worker import DetectionWorker


class DetectoristApp(QMainWindow):
    # Signal to request processing in the worker thread
    request_processing = Signal(str, bool, list)  # image_path, exposure_correction, prefetch_paths

    def __init__(self):
        super().__init__()

        self.current_image_path = None
        self._previous_row: int | None = None
        self._all_detection_results: list = []
        self._last_detection_time_ms: float = 0.0

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
        self.ui.splitter.replaceWidget(1, self.ui.image_label)
        self.ui.image_label.setText("Drop a folder with images<br/>Or use: File -> Open...")
        self.ui.image_label.setAcceptDrops(True) # Enable drag and drop for image_label

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
        self.ui.group_images_by_object_class_action.triggered.connect(self.sort_images_by_class_into_folders)
        self.ui.locate_image_in_filemanager_action.triggered.connect(self._locate_selected_image_in_file_manager)
        self.ui.copy_filenames_to_clipboard_action.triggered.connect(self._copy_selected_filenames_to_clipboard)
        self.ui.remove_selected_images_from_list_action.triggered.connect(self._remove_selected_images_from_list)
        self.ui.copy_export_remove_action.triggered.connect(self._copy_export_remove_selected_images)
        self.ui.clear_recent_folders_action.triggered.connect(self._clear_recent_folders)
        self.ui.import_settings_action.triggered.connect(self._import_settings)
        self.ui.export_settings_action.triggered.connect(self._export_settings)
        self.ui.manage_models_action.triggered.connect(self.show_manage_models_dialog)

        # Confidence slider/spinbox update the display filter only (no re-inference)
        self.ui.confidence_slider.valueChanged.connect(self._display_filtered_results)
        self.ui.confidence_spin_box.valueChanged.connect(self._display_filtered_results)

        # Connect crop controls
        self.ui.rb_crop_to_top_conf.toggled.connect(self.update_crop_bands)
        self.ui.rb_crop_union.toggled.connect(self.update_crop_bands)
        self.ui.rb_crop_all_detected_objects.toggled.connect(self.update_crop_bands)
        self.ui.rb_crop_centered_obj.toggled.connect(self.update_crop_bands)
        self.ui.crop_ratio_combo_box.currentIndexChanged.connect(self.update_crop_bands)
        self.ui.padding_slider.valueChanged.connect(self.update_crop_bands)

        self.ui.cb_comp_cam_exposure.toggled.connect(self.on_exposure_compensation_toggled)

        # Connect model signals
        self.model.modelReset.connect(self._update_clear_image_list_action_state)

        self.models_dir = get_model_path()

        # Shared model downloader (lives for the app's lifetime so downloads survive dialog close)
        self._model_downloader = ModelDownloader(self.models_dir, self)
        self._model_downloader.download_finished.connect(self._refresh_model_list)

        # Deferred loading placeholder: started when an image is selected,
        # stopped when it arrives. Cached images arrive within a few
        # milliseconds, so the placeholder never flashes for them.
        self._loading_indicator_timer = QTimer(self)
        self._loading_indicator_timer.setSingleShot(True)
        self._loading_indicator_timer.setInterval(200)
        self._loading_indicator_timer.timeout.connect(self._show_loading_indicator)

        # Setup worker thread, to offload image loading and detection, so the GUI remains responsive.
        self._worker_thread = QThread()
        self.worker = DetectionWorker()
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
        self.ui.model_select_combo_box.currentIndexChanged.connect(self.on_model_selected)
        self.ui.class_filter_combo_box.currentIndexChanged.connect(self.on_class_filter_changed)

        # Start the thread
        self._worker_thread.start()

        # Find and populate models (must be after worker setup so _on_model_availability_changed can reach it)
        self._refresh_model_list()

        # Load settings (must be after UI setup and before triggering model load)
        self._load_settings()
        self._update_recent_folders_menu()

        # Load AI model (combo box index was set by _load_settings if a saved model exists)
        self.on_model_selected(self.ui.model_select_combo_box.currentIndex())

        # Auto-show download dialog if no models found
        if self.ui.model_select_combo_box.count() == 0:
            QTimer.singleShot(0, self.show_manage_models_dialog)

    def _load_settings(self):
        """Load persistent settings and apply to UI."""
        self.settings = Settings()

        # Window geometry and splitter state
        if self.settings.window_geometry:
            self.restoreGeometry(self.settings.window_geometry)
        if self.settings.splitter_state:
            self.ui.splitter.restoreState(self.settings.splitter_state)

        # Model selection
        if self.settings.model:
            combo = self.ui.model_select_combo_box
            combo.blockSignals(True)
            idx = combo.findData(self.settings.model)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.blockSignals(False)

        # Confidence (slider and spinbox are linked)
        if (confidence := self.settings.confidence) is not None:
            self.ui.confidence_slider.setValue(confidence)

        # Crop mode
        if (crop_mode := CropMode.from_setting(self.settings.crop_mode)) is not None:
            self._crop_mode_radios()[crop_mode].setChecked(True)

        # Aspect ratio
        if (aspect_ratio_index := self.settings.aspect_ratio_index) is not None:
            if 0 <= aspect_ratio_index < self.ui.crop_ratio_combo_box.count():
                self.ui.crop_ratio_combo_box.setCurrentIndex(aspect_ratio_index)

        # Padding
        if (padding := self.settings.padding) is not None:
            self.ui.padding_slider.setValue(padding)

        # Auto correct camera exposure bias
        if (auto_exposure := self.settings.auto_correct_exposure_enabled) is not None:
            self.ui.cb_comp_cam_exposure.setChecked(auto_exposure)

    def _save_settings(self):
        """Save current UI state to persistent settings."""
        self.settings.save_current_version()

        # Window geometry and splitter state
        self.settings.window_geometry = self.saveGeometry()
        self.settings.splitter_state = self.ui.splitter.saveState()

        # Model selection
        self.settings.model = self.ui.model_select_combo_box.currentData()

        # Confidence
        self.settings.confidence = self.ui.confidence_slider.value()

        # Crop mode
        for mode, radio in self._crop_mode_radios().items():
            if radio.isChecked():
                self.settings.crop_mode = mode.value
                break

        # Aspect ratio
        self.settings.aspect_ratio_index = self.ui.crop_ratio_combo_box.currentIndex()

        # Padding
        self.settings.padding = self.ui.padding_slider.value()

        # Auto correct camera exposure bias
        self.settings.auto_correct_exposure_enabled = self.ui.cb_comp_cam_exposure.isChecked()

    def _update_detection_info(self, objects="-", confidence="-", time="-"):
        detection_info_items = [
            ("Objects\t\t\t", objects),
            ("Highest confidence\t", confidence),
            ("Detection time\t\t", time)
        ]
        detection_info = "\n".join(f"{k}: {v}" for k, v in detection_info_items)
        self.ui.detection_info_label.setText(detection_info)

    def _load_images_from_paths(self, file_paths: list[str]):
        supported_files = sorted({f for f in file_paths if f.lower().endswith(ImageObject.get_supported_extensions())})

        if not supported_files:
            # Handle UI state for no images
            # (Selection-dependent actions are handled via selectionChanged signal from model.clear())
            self.ui.image_label.set_detection_boxes([])
            self.ui.image_label.hide_bands()
            self._update_detection_info()
            self.ui.crop_and_export_all_images_action.setEnabled(False)
            self.ui.group_images_by_object_class_action.setEnabled(False)
            self.ui.image_label.setText("No supported images found or selected.")
            self.model.clear()
            return

        # Clear existing list and main image
        self.model.clear()
        self.current_image_path = None
        self._previous_row = None
        self.ui.image_label.clear()
        # Files on disk may have changed, so cached decodes are not trustworthy.
        # The queued invocation runs clear_cache on the worker thread, which is
        # the only thread allowed to touch the cache (no lock needed there).
        QMetaObject.invokeMethod(self.worker, "clear_cache", Qt.ConnectionType.QueuedConnection)

        self.ui.image_label.setText("Loading Images...")
        self.model.setImagePaths(supported_files)
        QApplication.processEvents() # Ensure UI updates

        # Enable actions that operate on all loaded images (only if a model is available)
        has_models = self.ui.model_select_combo_box.count() > 0
        self.ui.crop_and_export_all_images_action.setEnabled(has_models)
        self.ui.group_images_by_object_class_action.setEnabled(has_models)

        # Select the first image in the list view
        first_file_path = supported_files[0]
        try:
            index = supported_files.index(first_file_path)
            self.ui.image_list_view.setCurrentIndex(self.model.index(index))
            self.on_image_selected(self.model.index(index))
        except ValueError:
            print(f"Error: Could not find {first_file_path} in the list.")
            self.ui.image_label.setText(f"Error: Could not find {os.path.basename(first_file_path)} in the list.")
    def open_images(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Open Image(s)",
            self.settings.last_directory,
            f"Images ({' '.join(['*' + ext for ext in ImageObject.get_supported_extensions()])})"
        )
        if file_paths:
            self.settings.add_recent_directory(os.path.dirname(file_paths[0]))
            self._update_recent_folders_menu()
            self._load_images_from_paths(file_paths)

    def open_folder(self) -> None:
        folder_path = QFileDialog.getExistingDirectory(self, "Open Folder", self.settings.last_directory)
        if folder_path:
            self._open_folder_by_path(folder_path)

    def _open_folder_by_path(self, folder_path: str) -> None:
        """Open a folder and load its images."""
        self.settings.add_recent_directory(folder_path)
        self._update_recent_folders_menu()
        image_files_basenames = sorted([f for f in os.listdir(folder_path)
                       if f.lower().endswith(ImageObject.get_supported_extensions())])
        full_paths = [os.path.join(folder_path, f) for f in image_files_basenames]
        self._load_images_from_paths(full_paths)

    def _update_recent_folders_menu(self) -> None:
        """Rebuild the Recent Folders submenu from settings."""
        self.ui.recent_folders_menu.clear()

        recent = self.settings.recent_directories
        if not recent:
            no_recent = self.ui.recent_folders_menu.addAction("No Recent Folders")
            no_recent.setEnabled(False)
        else:
            for path in recent:
                action = self.ui.recent_folders_menu.addAction(contract_user_path(path))
                action.triggered.connect(lambda checked, p=path: self._open_recent_folder(p))

        # Re-add the separator and Clear Recent action (defined in .ui, removed by clear())
        self.ui.recent_folders_menu.addSeparator()
        self.ui.clear_recent_folders_action.setEnabled(bool(recent))
        self.ui.recent_folders_menu.addAction(self.ui.clear_recent_folders_action)

    def _open_recent_folder(self, path: str) -> None:
        """Open a folder from the recent list."""
        if os.path.isdir(path):
            self._open_folder_by_path(path)
        else:
            QMessageBox.warning(self, "Folder Not Found", f"The folder is not accessible anymore (e.g. no longer exists):\n{path}")

    def _clear_recent_folders(self) -> None:
        """Clear the recent folders list."""
        self.settings.clear_recent_directories()
        self._update_recent_folders_menu()

    def _import_settings(self) -> None:
        """Import settings from a JSON file exported during a previous batch run."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Settings",
            self.settings.last_directory,
            "Settings Files (*.json)"
        )
        if not file_path:
            return

        self.settings.import_from_file(
            Path(file_path),
            [Settings.GROUP_MODEL, Settings.GROUP_CROP]
        )
        self._load_settings()
        self.ui.status_bar.showMessage("Settings imported.", 3000)

    def _export_settings(self) -> None:
        """Export current settings to a JSON file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Settings",
            self.settings.last_directory + "/settings.json",
            "Settings Files (*.json)"
        )
        if not file_path:
            return

        self._save_settings()
        self.settings.export_to_file(
            Path(file_path),
            [Settings.GROUP_MODEL, Settings.GROUP_CROP]
        )
        self.ui.status_bar.showMessage("Settings exported.", 3000)

    def clear_image_list(self):
        """Clears the image list and resets the application to its initial state."""
        self.model.clear()
        self.current_image_path = None
        self._all_detection_results = []

        # Clear the main image view and reset text
        self.ui.image_label.clear()
        self.ui.image_label.setText("Drop a folder with images<br/>Or use: File -> Open...")
        self.ui.image_label.set_detection_boxes([])
        self.ui.image_label.hide_bands()

        # Reset UI elements
        self._update_detection_info()
        self.ui.image_info_label.setText("")
        self.ui.image_exif_label.setText("")
        self.ui.status_bar.clearMessage()

        # Disable actions that depend on images being loaded
        # (Selection-dependent actions are handled via selectionChanged signal)
        self.ui.crop_and_export_all_images_action.setEnabled(False)
        self.ui.group_images_by_object_class_action.setEnabled(False)

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

        try:
            self._previous_row = self.model.imagePaths().index(self.current_image_path)
        except ValueError:
            self._previous_row = None

        self.current_image_path = new_image_path
        self._all_detection_results = []

        if self.ui.model_select_combo_box.count() == 0:
            self.ui.image_label.setText(
                "No models available<br/>Use File -> Download Models"
            )
            self._update_detection_info()
            self.ui.status_bar.clearMessage()
            return

        # Clear previous results. The loading placeholder is deferred so that
        # cache hits do not flash "Loading image..." for a single frame.
        self._loading_indicator_timer.start()
        self.ui.image_label.hide_bands()
        self._update_detection_info()
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
        self.request_processing.emit(self.current_image_path, exposure_correction, self._prefetch_hints())

    def _prefetch_hints(self) -> list[str]:
        """
        Returns paths to decode ahead of time. In both directions: protect the
        from-image (so it survives the upcoming evictions) then prefetch 3 in the
        direction of travel, giving 3 instant steps ahead and 1 instant step back.
        Falls back to 2 ahead and 2 behind (n+1, n-1, n+2, n-2) for the first
        selection or a jump.
        """
        paths = self.model.imagePaths()
        try:
            row = paths.index(self.current_image_path)
        except ValueError:
            return []

        prev_row = self._previous_row
        if prev_row is not None and abs(row - prev_row) == 1:
            if row > prev_row:
                # Promote the from-image first so it survives the forward loads.
                return [paths[prev_row]] + paths[row + 1:row + 4]
            else:
                # Same pattern as forward: protect the from-image first, then
                # prefetch 3 in the direction of travel.
                return [paths[prev_row]] + list(reversed(paths[max(0, row - 3):row]))

        # No clear direction: nearest 2 in each direction, alternating so the
        # closest neighbors are always decoded first.
        return [paths[i] for i in [row + 1, row - 1, row + 2, row - 2]
                if 0 <= i < len(paths)]

    def handle_model_loaded(self, success: bool, message: str, class_names: list):
        """Handles the result of loading a model in the worker."""
        self.ui.class_filter_combo_box.blockSignals(True)
        self.ui.class_filter_combo_box.clear()
        self.ui.class_filter_combo_box.addItem("All classes")
        for name in class_names:
            self.ui.class_filter_combo_box.addItem(name)
        self.ui.class_filter_combo_box.blockSignals(False)
        self._all_detection_results = []
        if success:
            print(message)
            # If an image is currently displayed, trigger a new detection with the new model.
            if self.current_image_path:
                self.trigger_processing()
        else:
            self.ui.image_label.hide_bands()
            self.ui.image_label.setText(message)
            self._update_detection_info()
            print(message)

    def handle_image_loaded(self, image_path: str, image_object: ImageObject):
        """Handles the image_loaded signal from the worker."""
        if image_path != self.current_image_path:
            return  # Stale result for a different image

        self._loading_indicator_timer.stop()

        if not image_object:
            self.ui.image_label.clear()
            self.ui.image_label.setText(f"Could not load image:\n{image_path}")
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
        self._display_filtered_results()

    def _filtered_results(self) -> list:
        """Returns detection results filtered by the current confidence and class filter selections."""
        confidence = self.ui.confidence_slider.value() / 100.0
        results = [d for d in self._all_detection_results if d[1] >= confidence]
        if self.ui.class_filter_combo_box.currentIndex() <= 0:
            return results
        selected = self.ui.class_filter_combo_box.currentText()
        return [d for d in results if d[2] == selected]

    def _display_filtered_results(self):
        """Updates the UI with detection results filtered by the current class selection."""
        filtered = self._filtered_results()
        self._update_detection_info(
            objects=len(filtered),
            confidence=f"{max((det[1] for det in filtered), default=0):.4f}",
            time=f"{self._last_detection_time_ms:.2f} ms"
        )
        self.ui.image_label.set_detection_boxes(filtered)
        self.update_crop_bands()

    def on_class_filter_changed(self):
        """Re-displays detection results when the class filter selection changes."""
        self._display_filtered_results()

    def handle_worker_error(self, image_path: str, message: str):
        """Handles an error signal from the worker."""
        if image_path != self.current_image_path:
            return  # Stale error for a different image (ignored)

        self._loading_indicator_timer.stop()
        print(f"Worker error for {image_path}: {message}")
        self.ui.image_label.setText(f"Error: {message}")
        self._update_detection_info()
        self.ui.status_bar.clearMessage()

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
        about_dialog = QDialog(self)
        about_ui = Ui_AboutDialog()
        about_ui.setupUi(about_dialog)
        about_ui.version_label.setText(f"Version: {__version__}")

        # Load changelog programmatically from the qrc to render markdown as QTextBrowser.source only handles HTML
        changelog_file = QFile(":docs/CHANGELOG.md")
        if changelog_file.open(QIODeviceBase.OpenModeFlag.ReadOnly | QIODeviceBase.OpenModeFlag.Text):
            changelog_text = changelog_file.readAll().data().decode("utf-8")
            about_ui.changelog_text_browser.setMarkdown(changelog_text)
            changelog_file.close()

        about_dialog.exec()

    def show_manage_models_dialog(self):
        dialog = ManageModelsDialog(self._model_downloader, self.models_dir, self)
        dialog.models_changed.connect(self._refresh_model_list)
        dialog.exec()

    def _refresh_model_list(self):
        """Re-scan the models directory and update the combo box."""
        previous_filename = self.ui.model_select_combo_box.currentData()
        self.ui.model_select_combo_box.clear()

        name_map = self._model_downloader.filename_to_name

        onnx_files = sorted(f for f in os.listdir(self.models_dir)
                            if f.endswith(".onnx") or f.endswith(".onnx.gz"))

        combo = self.ui.model_select_combo_box
        combo.blockSignals(True)
        for filename in onnx_files:
            display_name = name_map.get(filename) or strip_model_ext(filename)
            combo.addItem(display_name, filename)

        # Restore previous selection by filename
        idx = combo.findData(previous_filename)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)

        # If the selected model changed (e.g. first download), load it in the worker.
        # on_model_selected is not triggered automatically because signals were blocked.
        new_filename = combo.currentData()
        if new_filename and new_filename != previous_filename:
            self.on_model_selected(combo.currentIndex())

        self._on_model_availability_changed()

    def _on_model_availability_changed(self):
        """React to the model combo box becoming empty or populated."""
        has_models = self.ui.model_select_combo_box.count() > 0
        has_images = self.model.rowCount() > 0

        # Enable/disable actions that require a model
        self.ui.crop_and_export_all_images_action.setEnabled(has_models and has_images)
        self.ui.crop_and_export_selected_images_action.setEnabled(
            has_models and self.ui.image_list_view.selectionModel().hasSelection()
        )
        self.ui.group_images_by_object_class_action.setEnabled(has_models and has_images)

        if not has_models:
            # Clear visual state completely
            self.ui.image_label.hide_bands()
            self.ui.image_label.setText("No models available<br/>Use File -> Download Models")
            self._update_detection_info()
            QMetaObject.invokeMethod(self.worker, "unload_model", Qt.ConnectionType.QueuedConnection)
        elif not has_images:
            self.ui.image_label.setText("Drop a folder with images<br/>Or use: File -> Open...")

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

    def _crop_mode_radios(self) -> dict[CropMode, QRadioButton]:
        """The crop panel radio button for each CropMode."""
        return {
            CropMode.TOP_CONFIDENCE: self.ui.rb_crop_to_top_conf,
            CropMode.UNION: self.ui.rb_crop_union,
            CropMode.MOST_CENTERED: self.ui.rb_crop_centered_obj,
            CropMode.EACH_OBJECT: self.ui.rb_crop_all_detected_objects,
        }

    def _get_current_crop_settings(self) -> CropSettings | None:
        """Gets crop settings from the UI, or None if no crop mode is selected."""
        crop_mode = next((mode for mode, radio in self._crop_mode_radios().items() if radio.isChecked()), None)
        if crop_mode is None:
            self.ui.image_label.hide_bands()
            return None

        padding_percentage = self.ui.padding_slider.value() / 100.0
        ratio_str = self.ui.crop_ratio_combo_box.currentText()

        if ratio_str == "aspect ratio: same as source image":
            if self.ui.image_label.image:
                height, width = self.ui.image_label.image.height, self.ui.image_label.image.width
                aspect_ratio = (width, height)
            else:
                # Default to something sensible if no image, though this path is unlikely
                aspect_ratio = (1, 1)
        elif ratio_str == "aspect ratio: same as detection frame":
            aspect_ratio = 'detection_frame'
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

        return CropSettings(mode=crop_mode, padding=padding_percentage, aspect=aspect_ratio)

    def update_crop_bands(self):
        if not self.ui.image_label.image or not self.ui.image_label.orig_detection_rects:
            self.ui.image_label.hide_bands()
            return

        # The detections in image_label are (QRect, score, class_id)
        # convert them to ((x,y,w,h), score, class_id) for calculate_crop_rect
        detections = [
            ((d[0].x(), d[0].y(), d[0].width(), d[0].height()), d[1], d[2])
            for d in self.ui.image_label.orig_detection_rects
        ]

        crop_settings = self._get_current_crop_settings()
        if crop_settings is None:
            self.ui.image_label.hide_bands()
            return
        crop_tuples = plan_crops(detections, self.ui.image_label.image.height, self.ui.image_label.image.width, crop_settings)
        crop_rects = [QRect(*crop_tuple) for crop_tuple in crop_tuples if crop_tuple and crop_tuple[2] > 0 and crop_tuple[3] > 0]

        if not crop_rects:
            self.ui.image_label.hide_bands()
            return

        self.ui.image_label.set_crop_boxes(crop_rects)

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


    def _run_batch_with_progress(self, process_name: str, action, image_files_to_process: list[str] | None = None) -> bool:
        """
        Runs a Batch Run over the given images (or all loaded images) with a
        modal progress dialog, then exports the settings alongside the CSV and
        reveals the output directory.

        Returns:
            bool: True if the process completed, False if it was cancelled or an error occurred.
        """
        if self.model.rowCount() == 0:
            return False # No images loaded at all
        # Use the directory of the first loaded image as the base for output
        output_base_dir = os.path.dirname(self.model.imagePaths()[0])

        image_full_paths = image_files_to_process if image_files_to_process is not None else self.model.imagePaths()
        if not image_full_paths:
            return False

        try:
            model_filename = self.ui.model_select_combo_box.currentData()
            output_dir = os.path.join(output_base_dir, output_dir_name(self.ui.confidence_slider.value(), model_filename))

            # The detector lives in the worker thread. We can't access it directly.
            # For batch processing, we need a separate detector instance.
            batch_detector = Detector.create(os.path.join(self.models_dir, model_filename))

            total_files = len(image_full_paths)
            progress_dialog = QProgressDialog(f"{process_name}...", "Cancel", 0, total_files, self)
            progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
            progress_dialog.setAutoClose(True)

            def progress(index: int, total: int, file_name: str) -> bool:
                progress_dialog.setValue(index)
                progress_dialog.setLabelText(f"Processing {index+1}/{total}: {file_name}")
                QApplication.processEvents()
                return not progress_dialog.wasCanceled()

            result = run_batch(
                image_full_paths,
                batch_detector,
                confidence=self.ui.confidence_slider.value() / 100.0,
                exposure_correction=self.ui.cb_comp_cam_exposure.isChecked(),
                output_dir=output_dir,
                action=action,
                progress=progress,
            )

            # Export Model & Crop settings to JSON alongside the CSV
            self._save_settings()
            settings_file_path = Path(result.output_dir) / "settings.json"
            self.settings.export_to_file(
                settings_file_path,
                [Settings.GROUP_MODEL, Settings.GROUP_CROP]
            )

            if not result.cancelled:
                self.ui.status_bar.showMessage(f"Finished {process_name.lower()}.", 5000)
            else:
                self.ui.status_bar.showMessage(f"{process_name} cancelled.", 5000)

            self._open_native_file_manager(result.output_dir)
            progress_dialog.close()
            return not result.cancelled

        except Exception as e:
            print(f"Error during {process_name}: {e}")
            self.ui.status_bar.showMessage(f"Error during {process_name}: {e}", 5000)
            return False

    def _crop_and_export_images_with_progress(self, process_name: str, image_files_to_process: list[str] | None = None):
        """Crops and exports images via a Batch Run using the current crop settings."""
        crop_settings = self._get_current_crop_settings()
        if crop_settings is None:
            return False
        return self._run_batch_with_progress(process_name, CropExportAction(crop_settings), image_files_to_process)

    def crop_and_export_selected_images(self):
        """Crop and export the currently selected images."""
        selected_indexes = self.ui.image_list_view.selectionModel().selectedIndexes()
        if not selected_indexes:
            return False

        selected_image_files = [self.model.data(index, ImageListModel.FullPathRole) for index in selected_indexes]
        return self._crop_and_export_images_with_progress("Cropping selected images", selected_image_files)

    def crop_and_export_all_images(self):
        """Crop and export all images."""
        return self._crop_and_export_images_with_progress("Cropping images")

    def sort_images_by_class_into_folders(self):
        """Sorts images into folders based on the detected object class name."""
        return self._run_batch_with_progress("Sorting images", SortByClassAction())

    def _copy_export_remove_selected_images(self):
        """Copies filenames, exports cropped images, and removes selected images from the list."""
        if not self.ui.image_list_view.selectionModel().hasSelection():
            return

        self._copy_selected_filenames_to_clipboard()
        success = self.crop_and_export_selected_images()
        if success:
            self._remove_selected_images_from_list()

    def _update_selection_dependent_actions_state(self):
        """Enables/disables actions based on the current selection in the image list view."""
        has_selection = len(self.ui.image_list_view.selectionModel().selectedIndexes()) > 0
        has_models = self.ui.model_select_combo_box.count() > 0
        self.ui.crop_and_export_selected_images_action.setEnabled(has_selection and has_models)
        self.ui.locate_image_in_filemanager_action.setEnabled(has_selection)
        self.ui.copy_filenames_to_clipboard_action.setEnabled(has_selection)
        self.ui.remove_selected_images_from_list_action.setEnabled(has_selection)
        self.ui.copy_export_remove_action.setEnabled(has_selection and has_models)

    def _update_clear_image_list_action_state(self):
        """Enables/disables clear_image_list_action based on whether the model has images."""
        self.ui.clear_image_list_action.setEnabled(self.model.rowCount() > 0)

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
        print("Closing application...")
        self._worker_thread.quit()
        self._worker_thread.wait()
        super().closeEvent(event)
