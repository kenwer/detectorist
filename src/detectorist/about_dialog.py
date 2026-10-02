from PySide6.QtCore import QFile, QIODeviceBase
from PySide6.QtWidgets import QDialog, QWidget

from detectorist import __version__

from .ui_about_dialog import Ui_AboutDialog

# Keep in sync with the "Acknowledgements" section of README.md.
_ACKNOWLEDGEMENTS_MARKDOWN = """\
The author would like to thank the following projects and people that made this work possible:

* The High Performance and Cloud Computing Group at the Zentrum für Datenverarbeitung, University of Tübingen, for providing computing resources via [bwForCluster BinAC 2](https://uni-tuebingen.de/en/einrichtungen/zentrum-fuer-datenverarbeitung/dienstleistungen/server/computing/resources/bwforcluster-binac-2/), funded by the state of Baden-Württemberg through bwHPC and the German Research Foundation (DFG) under Project number 455787709.
* [RF-DETR](https://github.com/roboflow/rf-detr) (Robinson et al., [arXiv:2511.09554](https://arxiv.org/abs/2511.09554), 2025) for powering object detection.
* [Prof. Dr. Nico Michiels](https://uni-tuebingen.de/en/fakultaeten/mathematisch-naturwissenschaftliche-fakultaet/fachbereiche/biologie/institute/evolution-und-oekologie/lehrbereiche/animal-evolutionary-ecology/people/nico-michiels/) (University of Tübingen) for providing thousands of images used for training the fish models.
* [Dr. Anja Buttstedt](https://uni-tuebingen.de/fakultaeten/mathematisch-naturwissenschaftliche-fakultaet/fachbereiche/biologie/institute/evolution-und-oekologie/lehrbereiche/vergleichende-zoologie/gruppe/anja-buttstedt/) for Apoidea images and testing the Windows version.

Many thanks also to the people behind the projects Detectorist builds on:

* [ONNX Runtime](https://onnxruntime.ai/)
* [Qt](https://www.qt.io/) / [PySide6](https://doc.qt.io/qtforpython/)
* [Python](https://www.python.org)
* [OpenCV](https://opencv.org)
* [NumPy](https://numpy.org)
* [Pillow](https://python-pillow.org) / [pillow-heif](https://github.com/bigcat88/pillow_heif) / [libheif](https://github.com/strukturag/libheif)
* [rawpy](https://github.com/letmaik/rawpy) / [LibRaw](https://www.libraw.org)
* [piexif](https://github.com/hMatoba/Piexif)
* [pyqt-toast-notification](https://github.com/niklashenning/pyqttoast)
* [Nuitka](https://nuitka.net)
* [uv](https://docs.astral.sh/uv/)
"""


def show_about_dialog(parent: QWidget | None = None) -> None:
    dialog = QDialog(parent)
    ui = Ui_AboutDialog()
    ui.setupUi(dialog)
    ui.version_label.setText(f"Version: {__version__}")

    # Load changelog programmatically from the qrc to render markdown as QTextBrowser.source only handles HTML
    changelog_file = QFile(":docs/CHANGELOG.md")
    if changelog_file.open(QIODeviceBase.OpenModeFlag.ReadOnly | QIODeviceBase.OpenModeFlag.Text):
        changelog_text = changelog_file.readAll().data().decode("utf-8")
        ui.changelog_text_browser.setMarkdown(changelog_text)
        changelog_file.close()

    ui.acknowledgements_text_browser.setMarkdown(_ACKNOWLEDGEMENTS_MARKDOWN)

    dialog.exec()
