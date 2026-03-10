import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QWidget,
)

from .manage_models_dialog import Ui_ManageModelsDialog
from .model_downloader import ModelDownloader, model_filename_from_url

# Row states where the action button triggers a download
_DOWNLOADABLE_STATES = ("available", "error", "outdated")


class _ModelRow:
    """Holds the widgets and state for a single model row in the dialog.

    Attributes:
        local_path: Absolute path to the model file on disk, or empty string if not downloaded.

    States:
        "available"   — not on disk, ready to download
        "downloading" — download in progress
        "downloaded"  — on disk and in the manifest
        "error"       — last download attempt failed
        "outdated"    — old version on disk, new version not yet downloaded
        "local_only"  — on disk but not in the manifest
    """
    __slots__ = ("model", "action_button", "progress_bar", "status_label", "desc_label", "state", "local_path")

    def __init__(self, model: dict, action_button: QPushButton,
                 progress_bar: QProgressBar, status_label: QLabel,
                 desc_label: QLabel, local_path: str = ""):
        self.model = model
        self.action_button = action_button
        self.progress_bar = progress_bar
        self.status_label = status_label
        self.desc_label = desc_label
        self.state = "available"
        self.local_path = local_path


class ManageModelsDialog(QDialog):
    """Dialog for browsing, downloading, and removing models.

    Fetches the remote manifest on open and renders one row per model.
    Models already on disk but absent from the manifest are shown as
    "local only" with a Remove button. Downloads are delegated to the
    shared ModelDownloader so they survive the dialog being closed.

    Signals:
        models_changed(): Emitted after a model is downloaded or removed.
    """

    models_changed = Signal()

    def __init__(self, downloader: ModelDownloader, models_dir: str, parent=None):
        super().__init__(parent)
        self._models_dir = models_dir
        self._manifest: list[dict] = []
        self._rows: list[_ModelRow] = []
        self._downloader = downloader

        self.ui = Ui_ManageModelsDialog()
        self.ui.setupUi(self)
        self.ui.scroll_contents_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._downloader.manifest_loaded.connect(self._on_manifest_loaded)
        self._downloader.download_started.connect(self._on_download_started)
        self._downloader.download_progress.connect(self._on_download_progress)
        self._downloader.download_finished.connect(self._on_download_finished)
        self._downloader.download_error.connect(self._on_download_error)
        self._downloader.all_downloads_finished.connect(self._on_all_downloads_finished)

        self.ui.download_button.clicked.connect(self._on_download_all_clicked)
        self.ui.close_button.clicked.connect(self.accept)

        self._downloader.fetch_manifest()

    def done(self, result):
        """Disconnect all downloader signals to prevent stale callbacks after close."""
        self._downloader.manifest_loaded.disconnect(self._on_manifest_loaded)
        self._downloader.download_started.disconnect(self._on_download_started)
        self._downloader.download_progress.disconnect(self._on_download_progress)
        self._downloader.download_finished.disconnect(self._on_download_finished)
        self._downloader.download_error.disconnect(self._on_download_error)
        self._downloader.all_downloads_finished.disconnect(self._on_all_downloads_finished)
        super().done(result)

    def _build_row_header(self, name: str) -> tuple[QWidget, QProgressBar, QLabel]:
        """Build the header row widget shared by all model rows.

        Returns:
            (header_widget, progress_bar, status_label)
        """
        name_label = QLabel(f"<b>{name}</b>")

        progress_bar = QProgressBar()
        progress_bar.setTextVisible(True)
        progress_bar.setVisible(False)

        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(name_label)
        header_layout.addWidget(progress_bar, stretch=1)

        status_label = QLabel()
        status_label.setFixedWidth(90)
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_label.setVisible(False)

        return header_widget, progress_bar, status_label

    def _on_manifest_loaded(self, manifest: list[dict]):
        """Populate the scroll area with a row for each manifest entry and any local-only models."""
        self._manifest = manifest
        self.ui.status_label.setText("")

        existing_models = {f for f in os.listdir(self._models_dir) if f.endswith(".onnx") or f.endswith(".onnx.gz")}
        active_filenames = set()
        if self._downloader.is_downloading:
            active_filenames.add(self._downloader.current_filename)
            active_filenames.update(self._downloader.queued_filenames)

        # Set of all filenames superseded by any manifest entry
        all_superseded = {fname for m in manifest for fname in m.get("supersedes", [])}

        for i, model in enumerate(manifest):
            # TODO: maybe there's a more elegant way to separate rows than manually adding a separator widget?
            if i > 0:
                separator = QFrame()
                separator.setFrameShape(QFrame.Shape.HLine)
                separator.setFrameShadow(QFrame.Shadow.Raised)
                self.ui.scroll_contents_layout.addWidget(separator)

            row_widget = QWidget()
            grid = QGridLayout(row_widget)

            filename = model_filename_from_url(model["url"])
            is_downloaded = filename in existing_models
            is_active = filename in active_filenames
            superseded_on_disk = not is_downloaded and not is_active and any(f in existing_models for f in model.get("supersedes", []))

            # Row 0: name + progress bar (combined), status label
            header_widget, progress_bar, status_label = self._build_row_header(model["name"])
            grid.addWidget(header_widget, 0, 0)
            grid.addWidget(status_label, 0, 1)

            # Row 1: description, action button
            filename_label = "Update available:" if superseded_on_disk else "File name:"
            desc_label = QLabel(f"""
            <p>{model.get("description", "no description available")}</p>
            <p><table style="border-collapse: collapse;">
                <tr>
                    <td style="text-align: left; padding-right: 10px; white-space: nowrap;">{filename_label}</td>
                    <td style="font-family: 'Courier New', Consolas, monospace; white-space: nowrap;">{filename}</td>
                </tr>
                <tr>
                    <td style="text-align: left; padding-right: 10px; white-space: nowrap;">Release date:</td>
                    <td style="font-family: 'Courier New', Consolas, monospace; white-space: nowrap;">{model.get("release_date", "unknown date")}</td>
                </tr>
                <tr>
                    <td style="text-align: left; padding-right: 10px; white-space: nowrap;">File size:</td>
                    <td style="font-family: 'Courier New', Consolas, monospace; white-space: nowrap;">{model.get("size_mb", "unknown size")} MB</td>
                </tr>
            </table></p>
            """)

            desc_label.setWordWrap(True)
            desc_label.setStyleSheet("color: dimgray;")

            action_button = QPushButton("Download")
            action_button.setFixedWidth(90)

            local_path = os.path.join(self._models_dir, filename) if is_downloaded else ""
            row = _ModelRow(model, action_button, progress_bar, status_label, desc_label, local_path)
            action_button.clicked.connect(lambda _checked, r=row: self._on_action_clicked(r))
            self._rows.append(row)

            grid.addWidget(desc_label, 1, 0)
            grid.addWidget(action_button, 1, 1, Qt.AlignmentFlag.AlignTop)

            # Column stretch: col 0 stretches, col 1 is fixed
            grid.setColumnStretch(0, 1)

            if is_active:
                self._set_row_state(row, "downloading")
            elif is_downloaded:
                self._set_row_state(row, "downloaded")
            else:
                if superseded_on_disk:
                    self._set_row_state(row, "outdated")
                else:
                    self._set_row_state(row, "available")

            self.ui.scroll_contents_layout.addWidget(row_widget)

        # Add local-only models (on disk but not in manifest, and not superseded by a manifest entry)
        manifest_filenames = {model_filename_from_url(m["url"]) for m in manifest}
        for filename in existing_models:
            # Skip manifest models, active downloads, and files represented by an "outdated" manifest row
            if filename in manifest_filenames or filename in active_filenames or filename in all_superseded:
                continue
            separator = QFrame()
            separator.setFrameShape(QFrame.Shape.HLine)
            separator.setFrameShadow(QFrame.Shadow.Raised)
            self.ui.scroll_contents_layout.addWidget(separator)

            model = {
                "name": filename,
                "url": filename,
                "description": "This model is not available for download.",
            }

            row_widget = QWidget()
            grid = QGridLayout(row_widget)

            # Row 0: name + progress bar (combined), status label
            header_widget, progress_bar, status_label = self._build_row_header(model["name"])
            grid.addWidget(header_widget, 0, 0)
            grid.addWidget(status_label, 0, 1)

            desc_label = QLabel(f"<p>{model['description']}</p>")
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet("color: dimgray;")

            action_button = QPushButton("Remove")
            action_button.setFixedWidth(90)

            local_path = os.path.join(self._models_dir, filename)
            row = _ModelRow(model, action_button, progress_bar, status_label, desc_label, local_path)
            action_button.clicked.connect(lambda _checked, r=row: self._on_action_clicked(r))
            self._rows.append(row)

            grid.addWidget(desc_label, 1, 0)
            grid.addWidget(action_button, 1, 1, Qt.AlignmentFlag.AlignTop)
            grid.setColumnStretch(0, 1)

            self._set_row_state(row, "local_only")

            self.ui.scroll_contents_layout.addWidget(row_widget)

        self._update_download_all_button_state()

    def _set_row_state(self, row: _ModelRow, state: str):
        """Update a row's button label, progress bar, and status label to match the given state."""
        row.state = state
        if state == "available":
            row.action_button.setText("Download")
            row.progress_bar.setVisible(False)
            row.status_label.setVisible(False)
        elif state == "downloading":
            row.action_button.setText("Cancel")
            row.progress_bar.setVisible(True)
            row.progress_bar.setMaximum(0)
            row.progress_bar.setValue(0)
            row.status_label.setVisible(False)
        elif state == "downloaded":
            row.action_button.setText("Remove")
            row.progress_bar.setVisible(False)
            row.status_label.setText("Downloaded")
            row.status_label.setStyleSheet("color: green; font-weight: bold;")
            row.status_label.setToolTip("")
            row.status_label.setVisible(True)
            row.desc_label.setText(row.desc_label.text().replace("Update available:", "File name:"))
        elif state == "error":
            row.action_button.setText("Retry")
            row.progress_bar.setVisible(False)
            row.status_label.setText("Error")
            row.status_label.setStyleSheet("color: red; font-weight: bold;")
            row.status_label.setVisible(True)
        elif state == "outdated":
            row.action_button.setText("Update")
            row.action_button.setEnabled(True)
            row.progress_bar.setVisible(False)
            row.status_label.setText("Outdated")
            row.status_label.setStyleSheet("color: darkorange; font-weight: bold;")
            row.status_label.setToolTip("")
            row.status_label.setVisible(True)
        elif state == "local_only":
            row.action_button.setText("Remove")
            row.progress_bar.setVisible(False)
            row.status_label.setText("Local only")
            row.status_label.setStyleSheet("color: gray; font-weight: bold;")
            row.status_label.setToolTip("This model is not available for download.")
            row.status_label.setVisible(True)

    def _on_action_clicked(self, row: _ModelRow):
        """Handle Download / Cancel / Remove / Retry button clicks for a model row."""
        if row.state in _DOWNLOADABLE_STATES:
            self._downloader.download([row.model])
            self._set_row_state(row, "downloading")
        elif row.state == "downloading":
            self._downloader.cancel()
            existing_models = {f for f in os.listdir(self._models_dir)
                               if f.endswith(".onnx") or f.endswith(".onnx.gz")}
            for r in self._rows:
                if r.state == "downloading":
                    superseded_on_disk = [f for f in r.model.get("supersedes", [])
                                          if f in existing_models]
                    self._set_row_state(r, "outdated" if superseded_on_disk else "available")
            self.ui.status_label.setText("Download cancelled.")
            self._update_download_all_button_state()
        elif row.state in ("downloaded", "local_only"):
            self._delete_model(row)

    def _find_row(self, filename: str) -> _ModelRow | None:
        """Return the row whose model's filename matches the given filename, or None."""
        for row in self._rows:
            if model_filename_from_url(row.model["url"]) == filename:
                return row
        return None

    def _delete_model(self, row: _ModelRow):
        """Delete the model file from disk and update the row state.

        Local-only rows are removed from the layout entirely; manifest rows
        revert to "available" state.
        """
        if row.local_path and os.path.exists(row.local_path):
            os.remove(row.local_path)
        row.local_path = ""

        if row.state == "local_only":
            # Remove the row widget and its preceding separator from the layout
            row_widget = row.action_button.parent()
            layout = self.ui.scroll_contents_layout
            idx = layout.indexOf(row_widget)
            if idx > 0:
                separator_item = layout.itemAt(idx - 1)
                if separator_item and separator_item.widget():
                    separator_item.widget().deleteLater()
                    layout.removeWidget(separator_item.widget())
            row_widget.deleteLater()
            layout.removeWidget(row_widget)
            self._rows.remove(row)
        else:
            self._set_row_state(row, "available")

        self._update_download_all_button_state()
        self.models_changed.emit()

    def _update_download_all_button_state(self):
        """Enable the Download All button only if at least one row can be downloaded."""
        any_available = any(row.state in _DOWNLOADABLE_STATES for row in self._rows)
        self.ui.download_button.setEnabled(any_available)

    def _on_download_all_clicked(self):
        """Queue all available (and errored) models for download."""
        models_to_download = [row.model for row in self._rows
                              if row.state in _DOWNLOADABLE_STATES]
        if not models_to_download:
            return
        self.ui.status_label.setText("Downloading...")
        self._downloader.download(models_to_download)

    def _on_download_started(self, filename: str):
        """Mark the row as downloading when the downloader begins a file."""
        row = self._find_row(filename)
        if row:
            self._set_row_state(row, "downloading")
        self._update_download_all_button_state()

    def _on_download_progress(self, filename: str, bytes_received: int, bytes_total: int):
        """Update the progress bar for the actively downloading row."""
        row = self._find_row(filename)
        if row and bytes_total > 0:
            row.progress_bar.setMaximum(bytes_total)
            row.progress_bar.setValue(bytes_received)

    def _on_download_finished(self, filename: str):
        """Mark the row as downloaded and set its local_path when the file has been saved."""
        row = self._find_row(filename)
        if row:
            row.local_path = os.path.join(self._models_dir, filename)
            self._set_row_state(row, "downloaded")

        self._update_download_all_button_state()

    def _on_download_error(self, error_message: str):
        """Mark the active row as errored and surface the message in the status bar."""
        filename = self._downloader.current_filename
        row = self._find_row(filename)
        if row:
            self._set_row_state(row, "error")
            row.status_label.setToolTip(error_message)
        self.ui.status_label.setText(f"Error: {error_message}")
        self._on_all_downloads_finished()

    def _on_all_downloads_finished(self):
        """Clear the status label and refresh the Download All button when the queue drains."""
        self.ui.status_label.setText("")
        self._update_download_all_button_state()
