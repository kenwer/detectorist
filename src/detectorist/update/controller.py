"""Drives the in-app update: check, offer, download, restart.

Provides a menu action and a status bar link for the caller to place. The
update itself is applied by main() after the event loop has ended, through
apply_pending_update(), so nothing is applied unless the window really closed.
"""

import logging
from enum import Enum, auto
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QUrl, SignalInstance, Slot
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import QLabel, QMessageBox, QWidget

from detectorist import toasts

from .dialog import UpdateDialog
from .feed import Update
from .install import AppInstall, required_space
from .workers import UpdateCheckWorker, UpdateDownloadWorker

_log = logging.getLogger(__name__)

NO_INSTALL_REASON = "This copy cannot update itself. Install the new version from the download page."


class UpdateState(Enum):
    IDLE = auto()
    CHECKING = auto()
    AVAILABLE = auto()
    DOWNLOADING = auto()
    READY = auto()


class UpdateController(QObject):
    def __init__(
        self,
        window: QWidget,
        current_version: str,
        install: AppInstall | None,
        feed_url: str,
        asset_name: str | None,
    ) -> None:
        super().__init__(window)
        self._window = window
        self._current_version = current_version
        self._install = install
        self._feed_url = feed_url
        self._asset_name = asset_name
        self._state = UpdateState.IDLE
        self._update: Update | None = None
        self._payload: Path | None = None
        self._manual = False
        self._apply_on_exit = False
        self._download_thread: QThread | None = None
        self._apply_failed = install is not None and install.take_apply_failure()

        self.action = QAction("Check for Updates...", window)
        self.action.triggered.connect(self._activate)
        # Parented, so it never shows as a window of its own before being placed
        self.status_link = QLabel(window)
        self.status_link.setTextFormat(Qt.TextFormat.RichText)
        self.status_link.setContentsMargins(4, 0, 4, 0)
        self.status_link.linkActivated.connect(self._activate)
        self.status_link.hide()

    @property
    def state(self) -> UpdateState:
        return self._state

    @property
    def update(self) -> Update | None:
        return self._update

    def running(self) -> bool:
        """Whether a check or download thread still runs.

        It may be blocked on the network for a while, and destroying a running
        QThread aborts the process, so main() exits without waiting then.
        """
        return any(thread.isRunning() for thread in self.findChildren(QThread))

    def block_reason(self) -> str | None:
        """Why the app cannot install an update by itself, or None when it can."""
        if self._install is None:
            return NO_INSTALL_REASON
        if self._apply_failed:
            return self._install.apply_failed_reason
        return self._install.unwritable_reason()

    def check(self, manual: bool = False) -> None:
        if self._state in (UpdateState.CHECKING, UpdateState.DOWNLOADING):
            return
        self._manual = manual
        self._set_state(UpdateState.CHECKING)
        worker = UpdateCheckWorker(
            self._feed_url, self._current_version, self._asset_name, self._install, self.block_reason() is None
        )
        worker.finished.connect(self._on_checked)
        worker.failed.connect(self._on_check_failed)
        self._start(worker, worker.finished, worker.failed)

    def show_dialog(self) -> None:
        if self._update is None:
            return
        reason = self.block_reason()
        if not UpdateDialog(self._update, self._current_version, reason, self._window).exec():
            return
        if reason:
            QDesktopServices.openUrl(QUrl(self._update.page_url))
        else:
            self.start_download()

    def start_download(self) -> None:
        if self._update is None or self._install is None:
            return
        if not self._install.free_space_ok(self._update):
            size_gb = required_space(self._update) / 1e9
            toasts.show_error_toast(
                self._window, "Not enough disk space", f"The update needs about {size_gb:.1f} GB of free space."
            )
            return
        self._set_state(UpdateState.DOWNLOADING)
        worker = UpdateDownloadWorker(self._install, self._update)
        # Bound methods, never lambdas: Qt queues a connection to a QObject's
        # method onto that object's thread, a lambda runs on the worker thread
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_downloaded)
        worker.failed.connect(self._on_download_failed)
        worker.cancelled.connect(self._on_download_cancelled)
        self._download_thread = self._start(worker, worker.finished, worker.failed, worker.cancelled)

    def cancel_download(self) -> None:
        if self._state is UpdateState.DOWNLOADING and self._download_thread is not None:
            self._download_thread.requestInterruption()

    def request_restart(self) -> None:
        if self._state is not UpdateState.READY:
            return
        if self._install is not None and (blocker := self._install.restart_blocker()):
            toasts.show_error_toast(self._window, *blocker)
            return
        # False when the window refused to close
        self._apply_on_exit = self._window.close()

    def apply_pending_update(self) -> None:
        if self._apply_on_exit and self._install is not None and self._payload is not None:
            self._install.apply(self._payload)

    def _start(self, worker: QObject, *done: SignalInstance) -> QThread:
        thread = QThread(self)
        # Python alone owns the worker and frees it with the thread, once that
        # has finished. A worker.deleteLater would race that from the worker thread.
        thread.worker = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        for signal in done:
            signal.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        return thread

    @property
    def _version(self) -> str:
        return self._update.version if self._update else ""

    @Slot(object, object)
    def _on_checked(self, update: Update | None, staged: Path | None) -> None:
        if update is None:
            self._set_state(UpdateState.IDLE)
            if self._manual:
                toasts.show_info_toast(
                    self._window, "You're up to date", f"Detectorist {self._current_version} is the latest version."
                )
            return
        self._update = update
        if staged is not None:
            self._on_downloaded(staged)
            return
        self._set_state(UpdateState.AVAILABLE)
        if self._manual:
            self.show_dialog()
        else:
            toasts.show_info_toast(
                self._window,
                "Update available",
                f"Detectorist {update.version} is available.",
                link_text="What's new",
                on_link=self.show_dialog,
            )

    @Slot(str)
    def _on_check_failed(self, message: str) -> None:
        _log.info("update check failed: %s", message)
        self._set_state(UpdateState.IDLE)
        if self._manual:
            toasts.show_error_toast(self._window, "Update check failed", message)

    @Slot(object, object)
    def _on_progress(self, done: int, total: int) -> None:
        if self._state is UpdateState.DOWNLOADING and total:
            self._set_link_text(f"Downloading {self._version}: {100 * done // total}%")

    @Slot(object)
    def _on_downloaded(self, payload: Path) -> None:
        self._payload = payload
        self._set_state(UpdateState.READY)
        toasts.show_info_toast(
            self._window,
            "Update ready",
            f"Detectorist {self._version} is downloaded.",
            link_text="Install and relaunch",
            on_link=self.request_restart,
        )

    @Slot(str)
    def _on_download_failed(self, message: str) -> None:
        self._set_state(UpdateState.AVAILABLE)
        toasts.show_error_toast(self._window, "Update download failed", message)

    @Slot()
    def _on_download_cancelled(self) -> None:
        self._set_state(UpdateState.AVAILABLE)

    def _activate(self) -> None:
        """The menu action or the status bar link was clicked."""
        if self._state is UpdateState.AVAILABLE:
            self.show_dialog()
        elif self._state is UpdateState.READY:
            self.request_restart()
        elif self._state is UpdateState.DOWNLOADING:
            answer = QMessageBox.question(self._window, "Cancel update?", "Stop downloading the update?")
            if answer == QMessageBox.StandardButton.Yes:
                self.cancel_download()
        else:
            self.check(manual=True)

    def _set_link_text(self, text: str) -> None:
        # The href is unused, linkActivated only needs an anchor to click
        self.status_link.setText(f'<a href="#">{text}</a>' if text else "")
        self.status_link.setVisible(bool(text))

    def _set_state(self, state: UpdateState) -> None:
        self._state = state
        version = self._version
        texts = {
            UpdateState.AVAILABLE: (f"Update to {version}", f"Update to {version}..."),
            UpdateState.DOWNLOADING: (f"Downloading {version}...", "Downloading Update..."),
            UpdateState.READY: ("Install and relaunch", "Install and Relaunch"),
        }
        link_text, action_text = texts.get(state, ("", "Check for Updates..."))
        self._set_link_text(link_text)
        self.action.setText(action_text)
        self.action.setEnabled(state not in (UpdateState.CHECKING, UpdateState.DOWNLOADING))
