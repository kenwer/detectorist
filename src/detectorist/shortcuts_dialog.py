from PySide6.QtCore import QFile, QIODeviceBase
from PySide6.QtGui import QTextDocument, QTextLength, QTextTable
from PySide6.QtWidgets import QDialog, QWidget

from .ui_shortcuts_dialog import Ui_ShortcutsDialog

# Applied identically to every table in the dialog so their columns line up, since
# QTextDocument otherwise sizes each markdown table's columns independently.
_COLUMN_WIDTH_PERCENTAGES = [12, 8, 28, 52]


class ShortcutsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.ui = Ui_ShortcutsDialog()
        self.ui.setupUi(self)

        shortcuts_file = QFile(":docs/SHORTCUTS.md")
        if shortcuts_file.open(QIODeviceBase.OpenModeFlag.ReadOnly | QIODeviceBase.OpenModeFlag.Text):
            shortcuts_text = shortcuts_file.readAll().data().decode("utf-8")
            self.ui.shortcuts_text_browser.setMarkdown(shortcuts_text)
            _align_document_tables(self.ui.shortcuts_text_browser.document(), _COLUMN_WIDTH_PERCENTAGES)
            shortcuts_file.close()


def _align_document_tables(document: QTextDocument, column_width_percentages: list[int]) -> None:
    constraints = [QTextLength(QTextLength.Type.PercentageLength, pct) for pct in column_width_percentages]
    for frame in document.rootFrame().childFrames():
        if isinstance(frame, QTextTable):
            table_format = frame.format()
            table_format.setColumnWidthConstraints(constraints)
            frame.setFormat(table_format)
