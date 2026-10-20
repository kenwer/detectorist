import json
import os

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

MANIFEST_FILENAME = "models.json"
CLASSIFICATION_MODELS_DIRNAME = "classifiers"
MODELS_BASE_URL = "https://raw.githubusercontent.com/kenwer/detectorist/main/models"
DETECTION_MODELS_MANIFEST_URL = f"{MODELS_BASE_URL}/{MANIFEST_FILENAME}"
CLASSIFICATION_MODELS_MANIFEST_URL = f"{MODELS_BASE_URL}/{CLASSIFICATION_MODELS_DIRNAME}/{MANIFEST_FILENAME}"
MANIFEST_TIMEOUT_MS = 15000  # Without a limit a stalled connection would leave the Manage Models dialog loading forever


def model_filename_from_url(url: str) -> str:
    """Derive the model filename from its download URL (last URL path segment)."""
    return url.rsplit("/", 1)[-1]


def _entries_of_kind(manifest: list, kind: str) -> list[dict]:
    """
    The entries of the manifest in the folder of the given kind of model.
    Classifier entries are tagged with kind "classifier", entries without a
    kind are detection models. An entry that names another kind is left out,
    so a later release can add one without this release offering it as the
    wrong kind of model.
    """
    if kind == "classifier":
        return [entry | {"kind": kind} for entry in manifest if entry.get("kind", kind) == kind]
    return [entry for entry in manifest if entry.get("kind", kind) == kind]


def _read_cached_manifest(folder: str, kind: str) -> list[dict]:
    """The manifest a previous fetch left in the folder, or an empty list if there is none."""
    try:
        with open(os.path.join(folder, MANIFEST_FILENAME), encoding="utf-8") as f:
            manifest = json.load(f)
    except (ValueError, OSError):
        return []
    return _entries_of_kind(manifest, kind) if isinstance(manifest, list) else []


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
        self._classifiers_dir = os.path.join(models_dir, CLASSIFICATION_MODELS_DIRNAME)
        self._nam = QNetworkAccessManager(self)
        # The manifest fetches in flight and the errors of those that finished, by kind
        self._manifest_replies: dict[str, QNetworkReply] = {}
        self._manifest_errors: dict[str, str] = {}
        self._current_reply: QNetworkReply | None = None
        self._current_file = None
        self._current_filename = ""
        self._current_dir = models_dir
        self._download_queue: list[dict] = []
        # Manifests cached by a previous network fetch. A clean install has none.
        self._manifests: dict[str, list[dict]] = {
            kind: _read_cached_manifest(self._folder_of(kind), kind) for kind in ("detector", "classifier")
        }

    @property
    def _manifest(self) -> list[dict]:
        """The detection models and classifiers of both manifests, in that order."""
        return self._manifests["detector"] + self._manifests["classifier"]

    def _folder_of(self, kind: str) -> str:
        return self._classifiers_dir if kind == "classifier" else self._models_dir

    @property
    def classifiers_dir(self) -> str:
        """The folder classifiers are downloaded to. It need not exist."""
        return self._classifiers_dir

    def model_dir(self, model: dict) -> str:
        """The folder the file of a manifest entry is downloaded to."""
        return self._folder_of(model.get("kind", "detector"))

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

    @property
    def classifier_patterns(self) -> dict[str, list[str]]:
        """
        The classifiers of the cached classifier manifest, each with the
        patterns of the detection classes it names (its "classifies", see
        class_matches). The files an entry supersedes get the same patterns.
        An entry that does not say is taken to name every class.
        """
        result: dict[str, list[str]] = {}
        for m in self._manifests["classifier"]:
            patterns = list(m.get("classifies", ["*"]))
            result[model_filename_from_url(m["url"])] = patterns
            for fname in m.get("supersedes", []):
                result.setdefault(fname, patterns)
        return result

    def classifies(self, filename: str) -> list[str]:
        """
        The patterns of the detection classes the classifier file names (see
        classifier_patterns). A file the manifest does not know, e.g. one
        copied into the classifiers folder by hand, is taken to name every class.
        """
        return self.classifier_patterns.get(filename, ["*"])

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
        Fetch the detection model and classifier manifests, each from the
        local models dir if available, otherwise from the network.

        Both are fetched at once, and one signal reports the pair: manifest_loaded
        with both lists, or manifest_error with the first failure. A manifest
        that did arrive is kept even if the other failed, so cached_manifest
        then holds it next to the other's last known version.

        A fetch that is already running is not repeated. Its result goes to
        whoever listens when it arrives, so a dialog that is closed and
        reopened while the list loads gets exactly one answer.
        """
        if self._manifest_replies:
            return

        self._manifest_errors = {}
        local_models_dir = os.path.realpath(os.path.normpath(os.path.join(os.getcwd(), "models")))
        is_checkout = os.path.realpath(self._models_dir) == local_models_dir
        for kind, remote_url in (("detector", DETECTION_MODELS_MANIFEST_URL), ("classifier", CLASSIFICATION_MODELS_MANIFEST_URL)):
            manifest_path = os.path.join(self._folder_of(kind), MANIFEST_FILENAME)
            url = QUrl.fromLocalFile(manifest_path) if is_checkout and os.path.isfile(manifest_path) else QUrl(remote_url)

            # async: when the reply is ready _on_manifest_finished is called
            # The defaults bind this iteration's values (finished carries no arguments)
            request = QNetworkRequest(url)
            request.setTransferTimeout(MANIFEST_TIMEOUT_MS)
            reply = self._nam.get(request)
            self._manifest_replies[kind] = reply
            reply.finished.connect(lambda kind=kind, reply=reply: self._on_manifest_finished(kind, reply))

    def _on_manifest_finished(self, kind: str, reply: QNetworkReply):
        """
        Handle one manifest reply: cache it to disk (network only) and parse
        it. Once both replies are in, emit manifest_loaded or manifest_error.
        """
        del self._manifest_replies[kind]
        label = "classifier manifest" if kind == "classifier" else "manifest"
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self._manifest_errors[kind] = f"Failed to fetch {label}: {reply.errorString()}"
            else:
                data = bytes(reply.readAll())
                manifest = json.loads(data)
                if not isinstance(manifest, list):
                    raise ValueError("not a list of models")

                if not reply.url().isLocalFile():
                    folder = self._folder_of(kind)
                    os.makedirs(folder, exist_ok=True)
                    with open(os.path.join(folder, MANIFEST_FILENAME), "wb") as f:
                        f.write(data)
                self._manifests[kind] = _entries_of_kind(manifest, kind)
        except (OSError, ValueError) as e:
            self._manifest_errors[kind] = f"Invalid {label}: {e}"
        finally:
            reply.deleteLater()

        if self._manifest_replies:
            return
        # The detection model manifest's error first, whichever reply came in first
        errors = [self._manifest_errors[k] for k in ("detector", "classifier") if k in self._manifest_errors]
        if errors:
            self.manifest_error.emit(errors[0])
        else:
            self.manifest_loaded.emit(self._manifest)

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
        self._current_dir = self.model_dir(model)
        os.makedirs(self._current_dir, exist_ok=True)
        part_path = os.path.join(self._current_dir, self._current_filename + ".part")

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

        part_path = os.path.join(self._current_dir, self._current_filename + ".part")
        final_path = os.path.join(self._current_dir, self._current_filename)

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
                    old_path = os.path.join(self._current_dir, old_fname)
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
        part_path = os.path.join(self._current_dir, self._current_filename + ".part")
        if os.path.exists(part_path):
            os.remove(part_path)
