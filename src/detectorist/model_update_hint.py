"""A status bar link that points to Manage Models when an installed model has a newer version."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from .model_downloader import ModelDownloader


class ModelUpdateHint(QLabel):
    """
    Shows "Model update available" while the cached manifest offers a newer
    version of a model on disk, and emits linkActivated when clicked. The
    link is shown neither while suppressed, so an app update link can take
    priority, nor once the model is updated or removed.
    """

    def __init__(self, downloader: ModelDownloader, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._downloader = downloader
        self._has_updates = False
        self._suppressed = False
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setContentsMargins(4, 0, 4, 0)

        # A failed manifest fetch can still have refreshed the other manifest.
        # A failed or cancelled download drops the queue, so its models count as outdated again.
        for signal in (downloader.manifest_loaded, downloader.manifest_error, downloader.download_started,
                       downloader.download_finished, downloader.download_error, downloader.download_cancelled):
            signal.connect(self.refresh)
        self.refresh()

    def check(self) -> None:
        """
        Fetch the manifests to learn of new versions. A failed fetch is not
        reported, the link keeps showing what the cached manifest knows.
        """
        self._downloader.fetch_manifest()

    def refresh(self) -> None:
        count = len(self._downloader.outdated_models())
        self._has_updates = count > 0
        text = "Model update available" if count == 1 else f"{count} model updates available"
        # The href is unused, linkActivated only needs an anchor to click
        self.setText(f'<a href="#">{text}</a>')
        self._update_visibility()

    def set_suppressed(self, suppressed: bool) -> None:
        self._suppressed = suppressed
        self._update_visibility()

    def _update_visibility(self) -> None:
        # An explicit hide also keeps QStatusBar.addPermanentWidget from showing the link
        self.setVisible(self._has_updates and not self._suppressed)
