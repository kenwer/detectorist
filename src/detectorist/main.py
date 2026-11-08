import logging
import os
import sys

# Disable onnxruntime telemetry on macOS and Linux
# Windows is covered below by disable_telemetry_events() in main()
os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")

import onnxruntime as ort  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from detectorist.detectorist_app import DetectoristApp  # noqa: E402


def main():
    # Handlers are configured only here at the entry point; library modules
    # just create loggers so embedding or testing them stays quiet.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    # Disable onnxruntime telemetry on Windows
    ort.disable_telemetry_events()

    app = QApplication(sys.argv)
    app.setApplicationName("detectorist")
    window = DetectoristApp()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
