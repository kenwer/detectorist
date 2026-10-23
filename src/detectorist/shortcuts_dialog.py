import re
import sys

from PySide6.QtGui import QTextDocument, QTextLength, QTextTable
from PySide6.QtWidgets import QDialog, QWidget

from .ui_shortcuts_dialog import Ui_ShortcutsDialog
from .utils import file_manager_name, read_resource_text, readme_section

# Applied identically to every table in the dialog so their columns line up, since
# QTextDocument otherwise sizes each markdown table's columns independently.
_COLUMN_WIDTH_PERCENTAGES = [20, 26, 54]

# The position of each platform's key column in the README's shortcut tables, Linux's for any other platform
_KEY_COLUMNS = {"win32": 0, "darwin": 2}
_LINUX_KEY_COLUMN = 1
_KEY_COLUMN_COUNT = 3


class ShortcutsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.ui = Ui_ShortcutsDialog()
        self.ui.setupUi(self)

        # README.md is the single source for the shortcuts, bundled so release builds pick up its current text
        readme = read_resource_text(":docs/README.md")
        self.ui.shortcuts_text_browser.setMarkdown(shortcuts_for_platform(shortcut_tables(readme)))
        _align_document_tables(self.ui.shortcuts_text_browser.document(), _COLUMN_WIDTH_PERCENTAGES)


def shortcut_tables(readme: str) -> str:
    """The README's keyboard shortcuts section without its intro, which points to this dialog.

    The table headings are level 4 so the README's TOC skips them, but Qt renders those
    barely larger than body text, so they are raised to level 2.
    """
    section = readme_section(readme, "Keyboard shortcuts", level=3)
    first_table_heading = section.find("#### ")
    tables = section[first_table_heading:] if first_table_heading >= 0 else section
    return re.sub(r"^#### ", "## ", tables, flags=re.MULTILINE)


def shortcuts_for_platform(markdown: str, platform: str = sys.platform) -> str:
    """The shortcut tables with only the platform's key column, naming its file manager as the menu does."""
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
