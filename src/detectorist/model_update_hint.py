"""A status bar link that points to Manage Models when an installed model has a newer version."""

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QLabel, QWidget

from .model_downloader import ModelDownloader


class ModelUpdateHint(QObject):
    """
    Shows "Model update available" while the cached manifest offers a newer
    version of a model on disk. Clicking it calls open_dialog. The link is
    shown neither while suppressed, so an app update link can take priority,
    nor once the model is updated or removed.
    """

    def __init__(self, downloader: ModelDownloader, open_dialog: Callable[[], None], window: QWidget) -> None:
        super().__init__(window)
        self._downloader = downloader
        self._count = 0
        self._suppressed = False

        # Parented, so it never shows as a window of its own before being placed
        self.status_link = QLabel(window)
        self.status_link.setTextFormat(Qt.TextFormat.RichText)
        self.status_link.setContentsMargins(4, 0, 4, 0)
        self.status_link.linkActivated.connect(open_dialog)
        self.status_link.hide()

        # A failed manifest fetch can still have refreshed the other manifest.
        # A failed or cancelled download drops the queue, so its models count as outdated again.
        for signal in (downloader.manifest_loaded, downloader.manifest_error, downloader.download_started,
                       downloader.download_finished, downloader.download_error, downloader.download_cancelled):
            signal.connect(self.refresh)
        self.refresh()

    @property
    def count(self) -> int:
        """The number of installed models with a newer version not yet downloaded."""
        return self._count

    def check(self) -> None:
        """
        Fetch the manifests to learn of new versions. A failed fetch is not
        reported, the link keeps showing what the cached manifest knows.
        """
        self._downloader.fetch_manifest()

    def refresh(self) -> None:
        self._count = len(self._downloader.outdated_models())
        text = "Model update available" if self._count == 1 else f"{self._count} model updates available"
        # The href is unused, linkActivated only needs an anchor to click
        self.status_link.setText(f'<a href="#">{text}</a>')
        self._show()

    def set_suppressed(self, suppressed: bool) -> None:
        self._suppressed = suppressed
        self._show()

    def _show(self) -> None:
        self.status_link.setVisible(self._count > 0 and not self._suppressed)
