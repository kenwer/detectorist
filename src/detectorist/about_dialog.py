from PySide6.QtWidgets import QDialog, QWidget

from detectorist import __version__

from .ui_about_dialog import Ui_AboutDialog
from .utils import read_resource_text, readme_section


def show_about_dialog(parent: QWidget | None = None) -> None:
    dialog = QDialog(parent)
    ui = Ui_AboutDialog()
    ui.setupUi(dialog)
    ui.version_label.setText(f"Version: {__version__}")

    # Load changelog programmatically from the qrc to render markdown as QTextBrowser.source only handles HTML
    ui.changelog_text_browser.setMarkdown(read_resource_text(":docs/CHANGELOG.md"))

    # README.md is the single source for the acknowledgements, bundled so release builds pick up its current text
    readme = read_resource_text(":docs/README.md")
    ui.acknowledgements_text_browser.setMarkdown(readme_section(readme, "Acknowledgements"))

    dialog.exec()
