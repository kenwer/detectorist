"""Smoke tests for the About and Shortcuts dialogs.

Both render Markdown from the compiled Qt resources, so a broken resource
path or .ui change shows up here as an empty dialog or an exception.
"""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog, QLabel, QTextBrowser

from detectorist import __version__
from detectorist.about_dialog import show_about_dialog
from detectorist.shortcuts_dialog import ShortcutsDialog, shortcuts_for_platform

SHORTCUTS_MD = Path(__file__).parents[1] / "SHORTCUTS.md"


def test_shortcuts_dialog_renders_the_shortcuts_document(qtbot):
    dialog = ShortcutsDialog()
    qtbot.addWidget(dialog)

    assert dialog.ui.shortcuts_text_browser.toPlainText().strip()


def test_about_dialog_shows_version_changelog_and_acknowledgements(qtbot, monkeypatch):
    shown = []
    # exec() would block on a modal dialog, so capture the dialog instead
    monkeypatch.setattr(QDialog, "exec", lambda self: shown.append(self))

    show_about_dialog()

    (dialog,) = shown
    qtbot.addWidget(dialog)
    assert dialog.findChild(QLabel, "version_label").text() == f"Version: {__version__}"
    assert dialog.findChild(QTextBrowser, "changelog_text_browser").toPlainText().strip()
    assert "RF-DETR" in dialog.findChild(QTextBrowser, "acknowledgements_text_browser").toPlainText()


def test_shortcuts_document_names_the_current_export_actions(qtbot):
    dialog = ShortcutsDialog()
    qtbot.addWidget(dialog)
    text = dialog.ui.shortcuts_text_browser.toPlainText()

    assert "Export Images..." in text
    assert "Export all Images" not in text
    assert "Export selected Images" not in text
    assert "Export & Remove" not in text
    assert "Group Images" not in text



@pytest.mark.parametrize(("platform", "rows"), [
    ("linux", ["| Linux | Action | Description |", "| Ctrl+Q | **Quit** | Quits Detectorist |",
               "| Ctrl+R | **Reveal in File Manager** | Shows the image in its folder |"]),
    ("win32", ["| Windows | Action | Description |", "| Alt+F4 | **Quit** | Quits Detectorist |",
               "| Ctrl+R | **Reveal in File Explorer** | Shows the image in its folder |"]),
    ("darwin", ["| macOS | Action | Description |", "| ⌘Q | **Quit** | Quits Detectorist |",
                "| ⌘R | **Reveal in Finder** | Shows the image in its folder |"]),
])
def test_shortcuts_show_only_the_keys_of_this_platform(platform, rows):
    lines = shortcuts_for_platform(SHORTCUTS_MD.read_text(encoding="utf-8"), platform).splitlines()

    assert all(row in lines for row in rows)
