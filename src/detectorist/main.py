import os
import sys
import tempfile

from PySide6.QtWidgets import QApplication

from detectorist.detectorist_app import DetectoristApp


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("detectorist")
    window = DetectoristApp()

    # Signal the splash screen removal to nuitka
    if "NUITKA_ONEFILE_PARENT" in os.environ:
        splash_filename = os.path.join(
            tempfile.gettempdir(),
            f"onefile_{int(os.environ['NUITKA_ONEFILE_PARENT'])}_splash_feedback.tmp"
        )
        if os.path.exists(splash_filename):
            os.unlink(splash_filename)

    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
