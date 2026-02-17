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

from .download_models_dialog import Ui_DownloadModelsDialog
from .model_downloader import ModelDownloader


class _ModelRow:
    """Holds references to widgets for a single model row."""
    __slots__ = ("model", "action_button", "progress_bar", "status_label", "state")

    def __init__(self, model: dict, action_button: QPushButton,
                 progress_bar: QProgressBar, status_label: QLabel):
        self.model = model
        self.action_button = action_button
        self.progress_bar = progress_bar
        self.status_label = status_label
        self.state = "available"


class DownloadModelsDialog(QDialog):
    models_changed = Signal()

    def __init__(self, downloader: ModelDownloader, models_dir: str, parent=None):
        super().__init__(parent)
        self._models_dir = models_dir
        self._manifest: list[dict] = []
        self._rows: list[_ModelRow] = []
        self._downloader = downloader

        self.ui = Ui_DownloadModelsDialog()
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
        """Disconnect all downloader signals to prevent stale callbacks."""
        self._downloader.manifest_loaded.disconnect(self._on_manifest_loaded)
        self._downloader.download_started.disconnect(self._on_download_started)
        self._downloader.download_progress.disconnect(self._on_download_progress)
        self._downloader.download_finished.disconnect(self._on_download_finished)
        self._downloader.download_error.disconnect(self._on_download_error)
        self._downloader.all_downloads_finished.disconnect(self._on_all_downloads_finished)
        super().done(result)

    def _on_manifest_loaded(self, manifest: list[dict]):
        self._manifest = manifest
        self.ui.status_label.setText("")

        existing_models = {f for f in os.listdir(self._models_dir) if f.endswith(".onnx")}
        active_filenames = set()
        if self._downloader.is_downloading:
            active_filenames.add(self._downloader.current_filename)
            active_filenames.update(self._downloader.queued_filenames)

        for i, model in enumerate(manifest):
            # TODO: maybe there's a more elegant way to separate rows than manually adding a separator widget?
            if i > 0:
                separator = QFrame()
                separator.setFrameShape(QFrame.Shape.HLine)
                separator.setFrameShadow(QFrame.Shadow.Raised)
                self.ui.scroll_contents_layout.addWidget(separator)

            row_widget = QWidget()
            grid = QGridLayout(row_widget)
            #grid.setContentsMargins(4, 4, 4, 4)

            filename = model["filename"]
            is_downloaded = filename in existing_models
            is_active = filename in active_filenames

            # Row 0: name + progress bar (combined), status label
            name_label = QLabel(f"<b>{model['name']}</b>")

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

            grid.addWidget(header_widget, 0, 0)
            grid.addWidget(status_label, 0, 1)

            # Row 1: description, action button
            desc_label = QLabel(f"""
            <p>{model.get("description", "no description available")}</p>
            <p><table style="border-collapse: collapse;">
                <tr>
                    <td style="text-align: left; padding-right: 10px; white-space: nowrap;">File name:</td>
                    <td style="font-family: 'Courier New', Consolas, monospace; white-space: nowrap;">{model.get("filename", "unknown filename")}</td>
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
            action_button.clicked.connect(lambda _checked, m=model: self._on_action_clicked(m))

            grid.addWidget(desc_label, 1, 0)
            grid.addWidget(action_button, 1, 1, Qt.AlignmentFlag.AlignTop)

            # Column stretch: col 0 stretches, col 1 is fixed
            grid.setColumnStretch(0, 1)

            row = _ModelRow(model, action_button, progress_bar, status_label)
            self._rows.append(row)

            if is_active:
                self._set_row_state(row, "downloading")
            elif is_downloaded:
                self._set_row_state(row, "downloaded")
            else:
                self._set_row_state(row, "available")

            self.ui.scroll_contents_layout.addWidget(row_widget)

        self._update_download_all_button_state()

    def _set_row_state(self, row: _ModelRow, state: str):
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
        elif state == "error":
            row.action_button.setText("Retry")
            row.progress_bar.setVisible(False)
            row.status_label.setText("Error")
            row.status_label.setStyleSheet("color: red; font-weight: bold;")
            row.status_label.setVisible(True)

    def _on_action_clicked(self, model: dict):
        row = self._find_row(model["filename"])
        if not row:
            return

        if row.state == "available" or row.state == "error":
            self._downloader.download([model])
            self._set_row_state(row, "downloading")
        elif row.state == "downloading":
            self._downloader.cancel()
            for r in self._rows:
                if r.state == "downloading":
                    self._set_row_state(r, "available")
            self.ui.status_label.setText("Download cancelled.")
            self._update_download_all_button_state()
        elif row.state == "downloaded":
            self._delete_model(model)

    def _find_row(self, filename: str) -> _ModelRow | None:
        for row in self._rows:
            if row.model["filename"] == filename:
                return row
        return None

    def _delete_model(self, model: dict):
        filepath = os.path.join(self._models_dir, model["filename"])
        if os.path.exists(filepath):
            os.remove(filepath)

        row = self._find_row(model["filename"])
        if row:
            self._set_row_state(row, "available")

        self._update_download_all_button_state()
        self.models_changed.emit()

    def _update_download_all_button_state(self):
        any_available = any(row.state in ("available", "error") for row in self._rows)
        self.ui.download_button.setEnabled(any_available)

    def _on_download_all_clicked(self):
        models_to_download = [row.model for row in self._rows
                              if row.state in ("available", "error")]
        if not models_to_download:
            return
        self.ui.status_label.setText("Downloading...")
        self._downloader.download(models_to_download)

    def _on_download_started(self, filename: str):
        row = self._find_row(filename)
        if row:
            self._set_row_state(row, "downloading")
        self._update_download_all_button_state()

    def _on_download_progress(self, filename: str, bytes_received: int, bytes_total: int):
        row = self._find_row(filename)
        if row and bytes_total > 0:
            row.progress_bar.setMaximum(bytes_total)
            row.progress_bar.setValue(bytes_received)

    def _on_download_finished(self, filename: str):
        row = self._find_row(filename)
        if row:
            self._set_row_state(row, "downloaded")
        self._update_download_all_button_state()

    def _on_download_error(self, error_message: str):
        filename = self._downloader.current_filename
        row = self._find_row(filename)
        if row:
            self._set_row_state(row, "error")
            row.status_label.setToolTip(error_message)
        self.ui.status_label.setText(f"Error: {error_message}")
        self._on_all_downloads_finished()

    def _on_all_downloads_finished(self):
        self.ui.status_label.setText("")
        self._update_download_all_button_state()
