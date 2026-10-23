import sys

from PySide6.QtCore import QFile, QIODeviceBase
from PySide6.QtGui import QTextDocument, QTextLength, QTextTable
from PySide6.QtWidgets import QDialog, QWidget

from .ui_shortcuts_dialog import Ui_ShortcutsDialog
from .utils import file_manager_name

# Applied identically to every table in the dialog so their columns line up, since
# QTextDocument otherwise sizes each markdown table's columns independently.
_COLUMN_WIDTH_PERCENTAGES = [20, 26, 54]

# The position of each platform's key column in the tables of SHORTCUTS.md, Linux's for any other platform
_KEY_COLUMNS = {"win32": 0, "darwin": 2}
_LINUX_KEY_COLUMN = 1
_KEY_COLUMN_COUNT = 3


class ShortcutsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.ui = Ui_ShortcutsDialog()
        self.ui.setupUi(self)

        shortcuts_file = QFile(":docs/SHORTCUTS.md")
        if shortcuts_file.open(QIODeviceBase.OpenModeFlag.ReadOnly | QIODeviceBase.OpenModeFlag.Text):
            shortcuts_text = shortcuts_file.readAll().data().decode("utf-8")
            self.ui.shortcuts_text_browser.setMarkdown(shortcuts_for_platform(shortcuts_text))
            _align_document_tables(self.ui.shortcuts_text_browser.document(), _COLUMN_WIDTH_PERCENTAGES)
            shortcuts_file.close()


def shortcuts_for_platform(markdown: str, platform: str = sys.platform) -> str:
    """SHORTCUTS.md with only the platform's key column, naming its file manager as the menu does."""
    key_column = _KEY_COLUMNS.get(platform, _LINUX_KEY_COLUMN)
    lines = []
    for line in markdown.splitlines():
        if line.startswith("|"):
            cells = [cell.strip() for cell in line.split("|")[1:-1]]
            line = "| " + " | ".join([cells[key_column], *cells[_KEY_COLUMN_COUNT:]]) + " |"
        lines.append(line)
    return "\n".join(lines).replace("Reveal in File Manager", f"Reveal in {file_manager_name(platform)}")


def _align_document_tables(document: QTextDocument, column_width_percentages: list[int]) -> None:
    constraints = [QTextLength(QTextLength.Type.PercentageLength, pct) for pct in column_width_percentages]
    for frame in document.rootFrame().childFrames():
        if isinstance(frame, QTextTable):
            table_format = frame.format()
            table_format.setColumnWidthConstraints(constraints)
            frame.setFormat(table_format)
