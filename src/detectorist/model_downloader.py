import json
import os

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

MANIFEST_URL = "https://raw.githubusercontent.com/kenwer/detectorist/main/models/models.json"


class ModelDownloader(QObject):
    manifest_loaded = Signal(list)
    download_started = Signal(str)         # filename
    download_progress = Signal(str, int, int)  # filename, bytes_received, bytes_total
    download_finished = Signal(str)        # filename
    download_error = Signal(str)           # error message
    all_downloads_finished = Signal()

    def __init__(self, models_dir: str, parent=None):
        super().__init__(parent)
        self._models_dir = models_dir
        self._nam = QNetworkAccessManager(self)
        self._current_reply: QNetworkReply | None = None
        self._current_file = None
        self._current_filename = ""
        self._download_queue: list[dict] = []

    @property
    def is_downloading(self) -> bool:
        return self._current_reply is not None or len(self._download_queue) > 0

    @property
    def current_filename(self) -> str:
        return self._current_filename

    @property
    def queued_filenames(self) -> list[str]:
        return [m["filename"] for m in self._download_queue]

    def fetch_manifest(self):
        request = QNetworkRequest(QUrl(MANIFEST_URL))
        reply = self._nam.get(request)
        reply.finished.connect(lambda: self._on_manifest_finished(reply))

    def _on_manifest_finished(self, reply: QNetworkReply):
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self.download_error.emit(f"Failed to fetch manifest: {reply.errorString()}")
            reply.deleteLater()
            return

        try:
            data = json.loads(bytes(reply.readAll()))
            self.manifest_loaded.emit(data)
        except (json.JSONDecodeError, ValueError) as e:
            self.download_error.emit(f"Invalid manifest: {e}")
        finally:
            reply.deleteLater()

    def download(self, models: list[dict]):
        already_active = self._current_reply is not None
        self._download_queue.extend(models)
        if not already_active:
            self._download_next()

    def _download_next(self):
        if not self._download_queue:
            self.all_downloads_finished.emit()
            return

        model = self._download_queue.pop(0)
        self._current_filename = model["filename"]
        part_path = os.path.join(self._models_dir, self._current_filename + ".part")

        self._current_file = open(part_path, "wb")  # noqa: SIM115
        self.download_started.emit(self._current_filename)

        request = QNetworkRequest(QUrl(model["url"]))
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        self._current_reply = self._nam.get(request)
        self._current_reply.downloadProgress.connect(self._on_download_progress)
        self._current_reply.readyRead.connect(self._on_ready_read)
        self._current_reply.finished.connect(self._on_download_finished)

    def _on_download_progress(self, bytes_received: int, bytes_total: int):
        self.download_progress.emit(self._current_filename, bytes_received, bytes_total)

    def _on_ready_read(self):
        if self._current_reply and self._current_file:
            self._current_file.write(bytes(self._current_reply.readAll()))

    def _on_download_finished(self):
        reply = self._current_reply
        self._current_reply = None

        if self._current_file:
            self._current_file.close()
            self._current_file = None

        if reply is None:
            return

        part_path = os.path.join(self._models_dir, self._current_filename + ".part")
        final_path = os.path.join(self._models_dir, self._current_filename)

        if reply.error() != QNetworkReply.NetworkError.NoError:
            # Clean up partial file and stop remaining downloads
            if os.path.exists(part_path):
                os.remove(part_path)
            self._download_queue.clear()
            self.download_error.emit(f"Download failed: {reply.errorString()}")
            reply.deleteLater()
            return

        # Rename .part to final filename
        if os.path.exists(final_path):
            os.remove(final_path)
        os.rename(part_path, final_path)

        reply.deleteLater()
        self.download_finished.emit(self._current_filename)
        self._download_next()

    def cancel(self):
        self._download_queue.clear()
        if self._current_reply:
            self._current_reply.abort()
        if self._current_file:
            self._current_file.close()
            self._current_file = None
        # Clean up partial file
        part_path = os.path.join(self._models_dir, self._current_filename + ".part")
        if os.path.exists(part_path):
            os.remove(part_path)
