import logging
import os
import sys
from pathlib import Path

# Disable onnxruntime telemetry on macOS and Linux
# Windows is covered below by disable_telemetry_events() in main()
os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")

import onnxruntime as ort  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import detectorist.resources_rc  # noqa: F401, E402  registers :/icons/* resources
from detectorist import __version__  # noqa: E402
from detectorist.detectorist_app import DetectoristApp  # noqa: E402
from detectorist.running_mutex import hold_running_mutex  # noqa: E402
from detectorist.update.controller import UpdateController  # noqa: E402
from detectorist.update.feed import DEFAULT_FEED_URL, release_asset_name  # noqa: E402
from detectorist.update.install import detect_install  # noqa: E402


def attach_updater(window: DetectoristApp, compiled: bool) -> UpdateController:
    """Give window the in-app updater.

    A source run gets no install, so it only reports new versions.
    DETECTORIST_UPDATE_FEED_URL points the check at another feed, for testing.
    """
    install = detect_install(sys.platform, Path(sys.executable), os.environ) if compiled else None
    feed_url = os.environ.get("DETECTORIST_UPDATE_FEED_URL", DEFAULT_FEED_URL)
    updater = UpdateController(window, __version__, install, feed_url, release_asset_name())
    window.ui.menu_help.insertAction(window.ui.about_action, updater.action)
    window.ui.status_bar.addPermanentWidget(updater.status_link)
    return updater


def main():
    # Handlers are configured only here at the entry point; library modules
    # just create loggers so embedding or testing them stays quiet.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    # Disable onnxruntime telemetry on Windows
    ort.disable_telemetry_events()

    app = QApplication(sys.argv)
    app.setApplicationName("detectorist")
    app.setWindowIcon(QIcon(":/icons/icon.svg"))
    hold_running_mutex()
    window = DetectoristApp()
    # Nuitka defines __compiled__ in every compiled module
    updater = attach_updater(window, compiled="__compiled__" in globals())
    window.show()
    QTimer.singleShot(0, updater.check)
    exit_code = app.exec()
    # Only reached once the window closed, so a refused close applies nothing
    updater.apply_pending_update()
    if updater.running():
        # A check or download blocked on the network. Destroying its QThread on
        # the way out would abort the process, so leave without waiting for it.
        window.settings.sync()
        logging.shutdown()
        os._exit(exit_code)
    sys.exit(exit_code)

if __name__ == '__main__':
    main()
