import json
import os

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

MANIFEST_URL = "https://raw.githubusercontent.com/kenwer/detectorist/main/models/models.json"
MANIFEST_FILENAME = MANIFEST_URL.rsplit("/", 1)[-1]
MANIFEST_TIMEOUT_MS = 15000  # Without a limit a stalled connection would leave the Manage Models dialog loading forever


def model_filename_from_url(url: str) -> str:
    """Derive the model filename from its download URL (last URL path segment)."""
    return url.rsplit("/", 1)[-1]


class ModelDownloader(QObject):
    """Downloads the model manifest and model files from the remote server.

    Signals:
        manifest_loaded(list):              Emitted after a successful manifest fetch with the parsed list.
        manifest_error(str):                Emitted when the manifest cannot be fetched or parsed (message).
        download_started(str):              Emitted when a file download begins (filename).
        download_progress(str, int, int):   Emitted periodically during download (filename, received, total).
        download_finished(str):             Emitted when a file has been saved successfully (filename).
        download_error(str):                Emitted when a model download fails (message).
        all_downloads_finished():           Emitted when the download queue is drained.
    """

    manifest_loaded = Signal(list)
    manifest_error = Signal(str)           # error message
    download_started = Signal(str)         # filename
    download_progress = Signal(str, int, int)  # filename, bytes_received, bytes_total
    download_finished = Signal(str)        # filename
    download_error = Signal(str)           # error message
    all_downloads_finished = Signal()

    def __init__(self, models_dir: str, parent=None):
        super().__init__(parent)
        self._models_dir = models_dir
        self._nam = QNetworkAccessManager(self)
        self._manifest_reply: QNetworkReply | None = None
        self._current_reply: QNetworkReply | None = None
        self._current_file = None
        self._current_filename = ""
        self._download_queue: list[dict] = []
        # Load manifest cached by a previous network fetch; absent on a clean install.
        self._manifest: list[dict] = []
        manifest_path = os.path.join(models_dir, "models.json")
        if os.path.isfile(manifest_path):
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    self._manifest = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

    @property
    def is_downloading(self) -> bool:
        """True while a download is active or files remain in the queue."""
        return self._current_reply is not None or len(self._download_queue) > 0

    @property
    def current_filename(self) -> str:
        """Filename of the model currently being downloaded, or empty string if idle."""
        return self._current_filename

    @property
    def queued_filenames(self) -> list[str]:
        """Filenames of models waiting in the download queue (excludes the active download)."""
        return [model_filename_from_url(m["url"]) for m in self._download_queue]

    @property
    def cached_manifest(self) -> list[dict]:
        """The manifest of the last successful fetch, in this or an earlier session. Empty if there was none."""
        return list(self._manifest)

    @property
    def filename_to_name(self) -> dict[str, str]:
        """Map of filename to human-readable name built from the cached manifest.

        Superseded filenames are included and resolve to the same name as their replacement,
        so older on-disk models display their conceptual name rather than a raw filename.
        """
        result = {}
        for m in self._manifest:
            result[model_filename_from_url(m["url"])] = m["name"]
            for fname in m.get("supersedes", []):
                result.setdefault(fname, m["name"])
        return result

    def successor_of(self, filename: str) -> str | None:
        """
        Filename of the model that supersedes the given one according to the
        cached manifest, or None. A file the manifest still offers itself has
        no successor.
        """
        entries = {model_filename_from_url(m["url"]): m for m in self._manifest}
        if filename in entries:
            return None
        for current_filename, model in entries.items():
            if filename in model.get("supersedes", []):
                return current_filename
        return None

    def fetch_manifest(self):
        """
        Fetch manifest from the local models dir if available, otherwise fetch from the network.

        A fetch that is already running is not repeated. Its result goes to
        whoever listens when it arrives, so a dialog that is closed and
        reopened while the list loads gets exactly one answer.
        """
        if self._manifest_reply is not None:
            return

        local_models_dir = os.path.realpath(os.path.normpath(os.path.join(os.getcwd(), "models")))
        manifest_path = os.path.join(self._models_dir, MANIFEST_FILENAME)
        if os.path.realpath(self._models_dir) == local_models_dir and os.path.isfile(manifest_path):
            url = QUrl.fromLocalFile(manifest_path)
        else:
            url = QUrl(MANIFEST_URL)

        # async: when the reply is ready _on_manifest_finished is called
        # The lambda captures `reply` so it can be passed to the callback (finished carries no arguments)
        request = QNetworkRequest(url)
        request.setTransferTimeout(MANIFEST_TIMEOUT_MS)
        reply = self._nam.get(request)
        self._manifest_reply = reply
        reply.finished.connect(lambda: self._on_manifest_finished(reply))

    def _on_manifest_finished(self, reply: QNetworkReply):
        """Handle the manifest reply: cache it to disk (network only), parse it, and emit manifest_loaded."""
        manifest_path = os.path.join(self._models_dir, MANIFEST_FILENAME)
        self._manifest_reply = None
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.manifest_error.emit(f"Failed to fetch manifest: {reply.errorString()}")
                return
            data = bytes(reply.readAll())
            manifest = json.loads(data)
            if not isinstance(manifest, list):
                raise ValueError("not a list of models")

            if not reply.url().isLocalFile():
                with open(manifest_path, "wb") as f:
                    f.write(data)
            self._manifest = manifest
            self.manifest_loaded.emit(self._manifest)
        except (OSError, ValueError) as e:
            self.manifest_error.emit(f"Invalid manifest: {e}")
        finally:
            reply.deleteLater()

    def download(self, models: list[dict]):
        """Add models to the download queue and start downloading if not already active.

        Args:
            models: List of manifest entries (dicts with at least a "url" key).
        """
        already_active = self._current_reply is not None
        self._download_queue.extend(models)
        if not already_active:
            self._download_next()

    def _download_next(self):
        if not self._download_queue:
            # Close pooled SSL connections so the server's keep-alive timeout does not
            # trigger a "QIODevice::read (QSslSocket): device not open" warning later.
            self._nam.clearConnectionCache()
            self.all_downloads_finished.emit()
            return

        model = self._download_queue.pop(0)
        self._current_filename = model_filename_from_url(model["url"])
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

        # Delete any files that this download supersedes
        for m in self._manifest:
            if model_filename_from_url(m["url"]) == self._current_filename:
                for old_fname in m.get("supersedes", []):
                    old_path = os.path.join(self._models_dir, old_fname)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                break

        reply.deleteLater()
        self.download_finished.emit(self._current_filename)
        self._download_next()

    def cancel(self):
        """Abort the active download and clear the queue. Removes any partial file."""
        self._download_queue.clear()
        # Detach the reply before aborting it as abort() emits finished, and _on_download_finished would report a cancel the user asked for as a failed download
        reply = self._current_reply
        self._current_reply = None
        if reply:
            reply.abort()
            reply.deleteLater()
        if self._current_file:
            self._current_file.close()
            self._current_file = None
        # Clean up partial file
        part_path = os.path.join(self._models_dir, self._current_filename + ".part")
        if os.path.exists(part_path):
            os.remove(part_path)
