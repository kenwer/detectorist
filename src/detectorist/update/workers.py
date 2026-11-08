"""Background work for the in-app update: the release check and the download."""

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from . import feed
from .download import DownloadCancelled
from .feed import Update, UpdateError
from .install import AppInstall

_log = logging.getLogger(__name__)


class UpdateCheckWorker(QObject):
    """Clears applied updates, asks the feed for a newer release and looks for one staged earlier.

    install is None when the app cannot install by itself. reuse_staged is
    False when it could but is blocked, since a staged update would then
    offer an install that cannot work.
    """

    # Update or None, staged payload Path or None
    finished = Signal(object, object)
    failed = Signal(str)

    def __init__(
        self,
        feed_url: str,
        current_version: str,
        asset_name: str | None,
        install: AppInstall | None,
        reuse_staged: bool,
    ) -> None:
        super().__init__()
        self._feed_url = feed_url
        self._current_version = current_version
        self._asset_name = asset_name
        self._install = install
        self._reuse_staged = reuse_staged

    @Slot()
    def run(self) -> None:
        # Here rather than on a thread of its own, so it never prunes the
        # staging folder at the same time as the staged lookup below
        if self._install is not None:
            self._install.cleanup(self._current_version)
        try:
            release = feed.fetch_latest_release(self._feed_url)
            update = feed.find_update(release, self._current_version, self._asset_name)
        except UpdateError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001  a raising slot would leave the check stuck
            _log.exception("update check crashed")
            self.failed.emit(str(exc))
            return
        self.finished.emit(update, self._staged(update))

    def _staged(self, update: Update | None) -> Path | None:
        if update is None or self._install is None or not self._reuse_staged:
            return None
        try:
            return self._install.staged_payload(update)
        except Exception as exc:  # noqa: BLE001  a broken staged copy only means downloading again
            _log.info("no reusable staged update: %s", exc)
            return None


class UpdateDownloadWorker(QObject):
    """Downloads, verifies and prepares an update, or reuses one staged earlier."""

    # object, not int: Qt's int is 32 bit and installers may pass 2 GB
    progress = Signal(object, object)
    # the payload Path
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, install: AppInstall, update: Update) -> None:
        super().__init__()
        self._install = install
        self._update = update

    def _is_cancelled(self) -> bool:
        thread = self.thread()
        return thread is not None and thread.isInterruptionRequested()

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self._install.fetch_payload(self._update, self.progress.emit, self._is_cancelled))
        except DownloadCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001  a raising slot would leave the download stuck
            # A traceback only for a bug, not for a network or disk failure
            _log.warning("update download failed: %s", exc, exc_info=not isinstance(exc, UpdateError | OSError))
            self.failed.emit(str(exc))
